"""
policies/qos.py — QoS 流量控制策略

QoS 作用位置：核心路由器 → 服务器的出口链路（r1-eth5, r1-eth6）
  - 实验瓶颈在服务器出口（默认 20Mbps），QoS 配在此处控制竞争
  - HTB: 为每个区域创建独立 class + tc filter（按源 IP 子网分类）
  - Baseline: pfifo 公平竞争（无分类，作为消融对照组）
  - 财务处获得较高带宽保障（70% 瓶颈带宽）
  - 宿舍区获得较低带宽限制（60% 瓶颈带宽）

三种策略:
  1. baseline_policy:  pfifo FIFO（无 QoS，平等竞争）
  2. htb_policy:       HTB 分层 + sfq 公平队列（按区域优先级调度）
"""

from mininet.log import info
from core.topology import ZONE_UPLINKS, ZONE_BASELINE_BW, SERVER1_INTF, SERVER2_INTF


# ==================== 各区域 QoS 配置 ====================

# 区域 → 上行接口映射
ZONE_INTF_MAP = {
    "r1-eth0": "dorm",
    "r1-eth1": "teach",
    "r1-eth2": "lib",
    "r1-eth3": "office",
    "r1-eth4": "finance",
}

# 服务器出口接口 — HTB 配在此处，控制各区域去往服务器的流量竞争
SERVER_UPLINKS = [SERVER1_INTF, SERVER2_INTF]

# 区域 → 子网映射（用于 tc filter 按源 IP 分类流量）
ZONE_SUBNET_MAP = {
    "dorm":    "10.0.1.0/24",
    "teach":   "10.0.2.0/24",
    "lib":     "10.0.3.0/24",
    "office":  "10.0.4.0/24",
    "finance": "10.0.5.0/24",
}

# 区域 → HTB class ID 映射（hh:minor 格式）
ZONE_CLASS_MAP = {
    "dorm":    "1:10",
    "teach":   "1:20",
    "lib":     "1:30",
    "office":  "1:40",
    "finance": "1:50",
}

# 服务器出口瓶颈带宽（Mbps，实验中的实际瓶颈）
DEFAULT_BOTTLENECK = 20

# HTB QoS 各区域带宽分配（Mbps）
#   finance/office: 保底 70% 拓扑带宽 （其中财务需求较高，办公需求预留空间）
#   teach/lib: 保底 70% 拓扑带宽
#   dorm: 保底 60% 拓扑带宽（视频流限速）
HTB_RATE_RATIO = {
    "finance": 0.70,
    "office":  0.70,
    "teach":   0.70,
    "lib":     0.70,
    "dorm":    0.60,
}


def _clear_interface_qos(r1, intf):
    """清除单个接口的 tc qdisc。"""
    r1.cmd(f"tc qdisc del dev {intf} root 2>/dev/null || true")


def apply_baseline_policy(r1, bottleneck_bw=None):
    """
    Baseline：服务器出口链路无 QoS 优先级，所有流量公平竞争。

    在 r1-eth5（→Server1）和 r1-eth6（→Server2）上配置简单的 pfifo 队列，
    不使用 tc filter 按源 IP 分类——各区域流量在出口处平等竞争带宽。

    QoS 消融实验中作为"去掉 QoS"的对照组。
    """
    bw = bottleneck_bw or DEFAULT_BOTTLENECK
    info(f"[QOS] 配置 Baseline (pfifo): 服务器出口 {bw}Mbps, 无分类, 公平竞争\n")

    for intf in SERVER_UPLINKS:
        _clear_interface_qos(r1, intf)
        r1.cmd(f"tc qdisc add dev {intf} root handle 1: htb default 1")
        r1.cmd(f"tc class add dev {intf} parent 1: classid 1:1 "
               f"htb rate {bw}mbit ceil {bw}mbit")
        r1.cmd(f"tc qdisc add dev {intf} parent 1:1 handle 10: pfifo limit 1000")
        info(f"  [BASELINE] {intf}: {bw}Mbps pfifo (无分类, 公平竞争)\n")

    info(f"[QOS] Baseline 已生效: {len(SERVER_UPLINKS)} 条服务器出口链路\n")


def apply_htb_policy(r1, bottleneck_bw=None):
    """
    HTB QoS：在服务器出口链路（r1-eth5, r1-eth6）上配置分层调度。

    为每个区域创建独立的 HTB class，使用 tc filter 按源 IP 子网分类流量：
      - finance（财务处）: 70% 瓶颈带宽保障（关键业务优先级最高）
      - office/teach/lib:  70% 瓶颈带宽保障（同等优先级）
      - dorm（宿舍区）:     60% 瓶颈带宽（视频流限速）

    当多个区域同时访问同一台服务器时，HTB 按 rate/ceil 分配出口带宽，
    TCP 流将自动收敛到各自的 rate 上限，关键业务得以保障。

    参数:
        r1:             路由器节点
        bottleneck_bw:  服务器出口瓶颈带宽 (Mbps)，默认 DEFAULT_BOTTLENECK (20 Mbps)
    """
    bw = bottleneck_bw or DEFAULT_BOTTLENECK
    info(f"[QOS] 配置 HTB QoS: 服务器出口 {bw}Mbps, 按源 IP 子网分类\n")

    for intf in SERVER_UPLINKS:
        _clear_interface_qos(r1, intf)

        # Step 1: 创建 HTB root qdisc
        r1.cmd(f"tc qdisc add dev {intf} root handle 1: htb default 99")

        # Step 2: 根类 — 总带宽 = 瓶颈带宽
        r1.cmd(f"tc class add dev {intf} parent 1: classid 1:1 "
               f"htb rate {bw}mbit ceil {bw}mbit")

        # Step 3: 为每个区域创建子类 + sfq 队列 + tc filter
        for zone, classid in ZONE_CLASS_MAP.items():
            ratio = HTB_RATE_RATIO.get(zone, 0.50)
            rate = max(int(bw * ratio), 1)   # 保底带宽，至少 1Mbps
            ceil = bw

            # 创建子类
            r1.cmd(f"tc class add dev {intf} parent 1:1 classid {classid} "
                   f"htb rate {rate}mbit ceil {ceil}mbit")
            # sfq 公平队列（防止同区域 TCP 流之间互相踩踏）
            leaf_handle = classid.split(":")[1]
            r1.cmd(f"tc qdisc add dev {intf} parent {classid} "
                   f"handle {leaf_handle}: sfq perturb 10")
            # tc filter: 按源 IP 子网将流量分类到对应 class
            subnet = ZONE_SUBNET_MAP[zone]
            r1.cmd(f"tc filter add dev {intf} protocol ip parent 1:0 prio 1 "
                   f"u32 match ip src {subnet} flowid {classid}")

            info(f"  [HTB] {intf} {zone}: class={classid} rate={rate}Mbps "
                 f"ceil={ceil}Mbps (ratio={ratio:.0%}) src={subnet}\n")

        # Step 4: 默认 catch-all 类（兜底未分类流量）
        r1.cmd(f"tc class add dev {intf} parent 1:1 classid 1:99 "
               f"htb rate 1mbit ceil {bw}mbit")
        r1.cmd(f"tc qdisc add dev {intf} parent 1:99 handle 99: sfq perturb 10")

        info(f"  [HTB] {intf}: 默认 class 1:99 已创建 (未分类流量)\n")

    info(f"[QOS] HTB QoS 已生效: {len(SERVER_UPLINKS)} 条服务器出口链路, "
         f"5 个区域 class + filter\n")


def clear_qos(r1):
    """清除所有 QoS 配置（区域上行链路 + 服务器出口链路）。"""
    info("[QOS] 清除所有 QoS 配置...\n")
    for intf in ZONE_UPLINKS + SERVER_UPLINKS:
        r1.cmd(f"tc qdisc del dev {intf} root 2>/dev/null || true")
    info("[QOS] QoS 配置已清除\n")
