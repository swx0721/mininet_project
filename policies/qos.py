"""
policies/qos.py — QoS 流量控制策略

QoS 作用位置：各区域交换机 → 核心路由器的上行链路（r1-eth0 ~ r1-eth4, r1-eth7）
  - 每个区域上行链路独立限速与分类
  - 财务处/人事处获得较高带宽保障
  - 宿舍区获得较低带宽限制
  - 服务器链路（r1-eth5, r1-eth6）不参与 QoS，保持独立对称

三种策略:
  1. baseline_policy:  pfifo FIFO（无 QoS，仅拓扑级带宽）
  2. htb_policy:       HTB 分层 + sfq 公平队列（默认 QoS 策略）
"""

from mininet.log import info
from core.topology import ZONE_UPLINKS, ZONE_BASELINE_BW


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

# HTB QoS 各区域带宽分配（Mbps）
#   finance/hr: 保底 80% 拓扑带宽（关键业务保障）
#   teach/lib/office: 保底 70% 拓扑带宽
#   dorm: 保底 60% 拓扑带宽（视频流限速）
HTB_RATE_RATIO = {
    "finance": 0.80,
    "hr":      0.80,
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
    Baseline：各区域上行链路保持拓扑级带宽，仅附加 pfifo。

    QoS 消融实验中作为"去掉 QoS"的对照组：
      各区域流量按其拓扑带宽自然竞争，无额外优先级或限速。
    """
    info(f"[QOS] 配置 Baseline (pfifo): 各区域上行链路拓扑带宽, 无优先级\n")

    for intf in ZONE_UPLINKS:
        zone = ZONE_INTF_MAP[intf]
        bw = ZONE_BASELINE_BW[intf]
        _clear_interface_qos(r1, intf)
        r1.cmd(f"tc qdisc add dev {intf} root handle 1: htb default 1")
        r1.cmd(f"tc class add dev {intf} parent 1: classid 1:1 "
               f"htb rate {bw}mbit ceil {bw}mbit")
        r1.cmd(f"tc qdisc add dev {intf} parent 1:1 handle 10: pfifo limit 1000")
        info(f"  [QOS] {intf} ({zone}): {bw}Mbps pfifo\n")

    info(f"[QOS] Baseline 已生效: {len(ZONE_UPLINKS)} 条区域上行链路, pfifo\n")


def apply_htb_policy(r1, bottleneck_bw=None):
    """
    QoS：各区域上行链路 HTB 分层调度。

    每条区域上行链路独立配置 HTB：
      - 根类速率 = 拓扑带宽 × HTB_RATE_RATIO（欠分配，预留突发空间）
      - ceil = 拓扑带宽
      - 队列类型: sfq 公平队列（防同区域 TCP 流踩踏）

    优先级通过各区域的 rate/ceil 比例隐式实现：
      - finance/hr: 80% 拓扑带宽保障
      - dorm: 60% 拓扑带宽（视频流受限）
    """
    info(f"[QOS] 配置 HTB QoS: 各区域上行链路独立调度\n")

    for intf in ZONE_UPLINKS:
        zone = ZONE_INTF_MAP[intf]
        topo_bw = ZONE_BASELINE_BW[intf]
        ratio = HTB_RATE_RATIO.get(zone, 0.70)
        rate = int(topo_bw * ratio)
        ceil = topo_bw

        _clear_interface_qos(r1, intf)

        r1.cmd(f"tc qdisc add dev {intf} root handle 1: htb default 10")
        r1.cmd(f"tc class add dev {intf} parent 1: classid 1:1 "
               f"htb rate {rate}mbit ceil {ceil}mbit")
        r1.cmd(f"tc qdisc add dev {intf} parent 1:1 handle 10: sfq perturb 10")

        info(f"  [QOS] {intf} ({zone}): rate={rate}Mbps ceil={ceil}Mbps "
             f"(拓扑={topo_bw}Mbps, ratio={ratio:.0%}) sfq\n")

    info(f"[QOS] HTB QoS 已生效: {len(ZONE_UPLINKS)} 条区域上行链路\n"
         f"      finance/hr → 80% 带宽保障 | dorm → 60% 限速 | 其余 → 70%\n")


def clear_qos(r1):
    """清除所有 QoS 配置（含服务器链路）。"""
    info("[QOS] 清除所有 QoS 配置...\n")
    for dev in [f"r1-eth{i}" for i in range(8)]:
        r1.cmd(f"tc qdisc del dev {dev} root 2>/dev/null || true")
    r1.cmd("iptables -t mangle -F 2>/dev/null || true")
    info("[QOS] QoS 配置已清除\n")
