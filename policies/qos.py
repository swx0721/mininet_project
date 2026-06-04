"""
policies/qos.py — QoS 流量控制策略

QoS 作用位置：核心路由器 → 服务器的出口链路（r1-eth5, r1-eth6）
  - 实验瓶颈在服务器出口（默认 20Mbps），QoS 配在此处控制竞争
  - HTB: 两级优先级体系 — 财务处独享 prio=0 高优先级，其余区域 prio=10 低优先级
  - 低优先级区域只有在财务处下限带宽被满足后才能获得剩余带宽
  - Baseline: pfifo 公平竞争（无分类，作为消融对照组）

策略:
  1. baseline_policy:  pfifo FIFO（无 QoS，平等竞争）
  2. htb_policy:       HTB 两级优先级 + sfq 公平队列（prio: finance=0, others=10）
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
    "r1-eth7": "hr",
}

# 服务器出口接口 — HTB 配在此处，控制各区域去往服务器的流量竞争
SERVER_UPLINKS = [SERVER1_INTF, SERVER2_INTF]

# 区域 → 子网映射（用于 tc filter 按源 IP 分类流量）
ZONE_SUBNET_MAP = {
    "dorm":    "10.0.0.0/20",
    "teach":   "10.0.16.0/20",
    "lib":     "10.0.32.0/23",
    "office":  "10.0.34.0/24",
    "finance": "10.0.35.0/26",
    "hr":      "10.0.35.64/26",
}

# 区域 → HTB class ID 映射（hh:minor 格式）
ZONE_CLASS_MAP = {
    "dorm":    "1:10",
    "teach":   "1:20",
    "lib":     "1:30",
    "office":  "1:40",
    "finance": "1:50",
    "hr":      "1:60",
}

# 服务器出口瓶颈带宽（Mbps，实验中的实际瓶颈）
DEFAULT_BOTTLENECK = 20

# HTB 两级优先级配置
#   prio=0:  财务处独享最高优先级 — 保底带宽优先保障，低优先级区域借用受限
#   prio=7: 其余四区域低优先级 — 只在财务处下限满足后才分配剩余带宽
#   rate_ratio: 保底带宽占比（相对于瓶颈带宽 20Mbps）
#     finance=60% (12Mbps) — 关键业务保障
#     others=10% ( 2Mbps) — 低优先级，仅保活
#   注意: HTB prio 取值范围 0~7（tc 强制限制），0=最高优先级
HTB_CONFIG = {
    "finance": {"rate_ratio": 0.60, "prio": 0},   # 高优先级, 12Mbps 保底
    "office":  {"rate_ratio": 0.10, "prio": 7},   # 低优先级,  2Mbps 保底
    "teach":   {"rate_ratio": 0.10, "prio": 7},
    "lib":     {"rate_ratio": 0.10, "prio": 7},
    "dorm":    {"rate_ratio": 0.10, "prio": 7},
    "hr":      {"rate_ratio": 0.10, "prio": 7},   # 人事处：普通优先级（非高优先级）
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
    HTB QoS：在服务器出口链路（r1-eth5, r1-eth6）上配置两级优先级调度。

    优先级体系:
      prio=0  (最高): 财务处 — 关键业务独享高优先级，保底 60% 瓶颈带宽
      prio=10 (普通): 宿舍/教学/图书馆/办公 — 低优先级，保底仅 10% 瓶颈
                      只有在财务处带宽需求被满足后，剩余带宽才分配给这些区域。

    HTB prio 机制：sibling class 中 prio 值越小调度优先级越高。
    高优先级 class 的 rate 被满足后，剩余带宽才流向低优先级 class。

    参数:
        r1:             路由器节点
        bottleneck_bw:  服务器出口瓶颈带宽 (Mbps)，默认 DEFAULT_BOTTLENECK (20 Mbps)
    """
    bw = bottleneck_bw or DEFAULT_BOTTLENECK
    info(f"[QOS] 配置 HTB QoS: 服务器出口 {bw}Mbps "
         f"(两级优先级: 财务处 prio=0, 其余 prio=10)\n")

    for intf in SERVER_UPLINKS:
        _clear_interface_qos(r1, intf)

        # Step 1: 创建 HTB root qdisc
        r1.cmd(f"tc qdisc add dev {intf} root handle 1: htb default 99")

        # Step 2: 根类 — 总带宽 = 瓶颈带宽
        r1.cmd(f"tc class add dev {intf} parent 1: classid 1:1 "
               f"htb rate {bw}mbit ceil {bw}mbit")

        # Step 3: 为每个区域创建子类（带 prio）+ sfq 队列 + tc filter
        for zone, classid in ZONE_CLASS_MAP.items():
            cfg = HTB_CONFIG.get(zone, {"rate_ratio": 0.10, "prio": 10})
            ratio = cfg["rate_ratio"]
            prio = cfg["prio"]
            rate = max(int(bw * ratio), 1)   # 保底带宽，至少 1Mbps
            ceil = bw

            # 创建子类（含 prio 参数）
            r1.cmd(f"tc class add dev {intf} parent 1:1 classid {classid} "
                   f"htb rate {rate}mbit ceil {ceil}mbit prio {prio}")
            # sfq 公平队列（防止同区域 TCP 流之间互相踩踏）
            leaf_handle = classid.split(":")[1]
            r1.cmd(f"tc qdisc add dev {intf} parent {classid} "
                   f"handle {leaf_handle}: sfq perturb 10")
            # tc filter: 按源 IP 子网将流量分类到对应 class
            subnet = ZONE_SUBNET_MAP[zone]
            r1.cmd(f"tc filter add dev {intf} protocol ip parent 1:0 prio 1 "
                   f"u32 match ip src {subnet} flowid {classid}")

            info(f"  [HTB] {intf} {zone}: class={classid} rate={rate}Mbps "
                 f"ceil={ceil}Mbps prio={prio} (ratio={ratio:.0%}) src={subnet}\n")

        # Step 4: 默认 catch-all 类（兜底未分类流量，最低优先级 prio=7）
        r1.cmd(f"tc class add dev {intf} parent 1:1 classid 1:99 "
               f"htb rate 1mbit ceil {bw}mbit prio 7")
        r1.cmd(f"tc qdisc add dev {intf} parent 1:99 handle 99: sfq perturb 10")

        info(f"  [HTB] {intf}: 默认 class 1:99 已创建 (未分类流量, prio=99)\n")

    info(f"[QOS] HTB QoS 已生效: {len(SERVER_UPLINKS)} 条服务器出口链路, "
         f"5 个区域 class (两级优先级) + filter\n")


def clear_qos(r1):
    """清除所有 QoS 配置（区域上行链路 + 服务器出口链路）。"""
    info("[QOS] 清除所有 QoS 配置...\n")
    for intf in ZONE_UPLINKS + SERVER_UPLINKS:
        r1.cmd(f"tc qdisc del dev {intf} root 2>/dev/null || true")
    info("[QOS] QoS 配置已清除\n")
