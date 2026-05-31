"""
policies/qos.py — QoS 流量控制策略

实现 HTB（Hierarchy Token Bucket）队列调度：
  - 财务处(10.0.5.0/24) 和 人事处(10.0.6.0/24)：高优先级 + 保底带宽
  - 普通业务（其余 TCP）：中等优先级
  - 宿舍区 UDP 视频流：最低优先级
  - 出口 r1-eth5 总限速 35Mbps

三种策略:
  1. baseline_policy:  pfifo FIFO（无 QoS）
  2. prio_policy:      严格优先级队列
  3. htb_policy:       HTB 分层 + sfq 公平队列（默认 QoS 策略）
"""

from mininet.log import info
from core.topology import SERVER_INTF, BOTTLENECK_BW


def apply_baseline_policy(r1, bottleneck_bw=None):
    """
    Baseline：pfifo FIFO 队列（无优先级）。

    在瓶颈链路 r1-eth5 上：
      1. HTB 总出口限制
      2. pfifo 纯 FIFO 队列
    """
    bw = bottleneck_bw if bottleneck_bw is not None else BOTTLENECK_BW
    intf = SERVER_INTF

    info(f"[QOS] 配置 Baseline (pfifo): {intf}={bw}Mbps, 无优先级\n")

    r1.cmd(f"tc qdisc del dev {intf} root 2>/dev/null || true")
    r1.cmd(f"tc qdisc add dev {intf} root handle 1: htb default 1")
    r1.cmd(f"tc class add dev {intf} parent 1: classid 1:1 "
           f"htb rate {bw}mbit ceil {bw}mbit")
    r1.cmd(f"tc qdisc add dev {intf} parent 1:1 handle 10: pfifo limit 1000")

    info(f"[QOS] Baseline 已生效: {intf} {bw}Mbps, pfifo\n")


def apply_prio_policy(r1, bottleneck_bw=None):
    """
    QoS：prio 严格优先级队列。

    在瓶颈链路 r1-eth5 上：
      - 财务处 + 人事处 → band 0（最高优先级）
      - 其余流量 → band 1（普通）

    严格优先级：band 0 有包时不服务 band 1。
    """
    bw = bottleneck_bw if bottleneck_bw is not None else BOTTLENECK_BW
    intf = SERVER_INTF

    info(f"[QOS] 配置 prio QoS: 严格优先级调度\n")

    r1.cmd(f"tc qdisc del dev {intf} root 2>/dev/null || true")

    qos_rate = bw - 5
    r1.cmd(f"tc qdisc add dev {intf} root handle 1: htb default 1")
    r1.cmd(f"tc class add dev {intf} parent 1: classid 1:1 "
           f"htb rate {qos_rate}mbit ceil {bw}mbit")

    r1.cmd(f"tc qdisc add dev {intf} parent 1:1 handle 10: prio bands 2")

    # 财务处 + 人事处 → band 0（高优先级）
    r1.cmd(f"tc filter add dev {intf} parent 10: protocol ip prio 1 u32 "
           f"match ip src 10.0.5.0/24 flowid 10:1")
    r1.cmd(f"tc filter add dev {intf} parent 10: protocol ip prio 2 u32 "
           f"match ip src 10.0.6.0/24 flowid 10:1")
    # 其余 → band 1
    r1.cmd(f"tc filter add dev {intf} parent 10: protocol ip prio 10 u32 "
           f"match ip src 0.0.0.0/0 flowid 10:2")

    info(f"[QOS] prio QoS 已生效: ceil={bw}Mbps, 财务+人事→band 0\n")


def apply_htb_policy(r1, bottleneck_bw=None):
    """
    QoS：HTB 分层 + 软优先级（保底带宽 + sfq 公平队列）。

    在瓶颈链路 r1-eth5 上：
        class 1:10 — 财务处 + 人事处: rate=12Mbps, ceil=35Mbps, prio=0（最高）
        class 1:20 — 普通业务（其余TCP）: rate=15Mbps, ceil=28Mbps, prio=1
        class 1:30 — UDP/背景流（宿舍区）: rate=6Mbps, ceil=20Mbps, prio=2（最低）
        三层 rate 合计 33Mbps < 总出口 35Mbps（欠分配预留借用空间）

    每个子类附加 sfq 防 TCP 踩踏。
    """
    bw = bottleneck_bw if bottleneck_bw is not None else BOTTLENECK_BW
    intf = SERVER_INTF

    info(f"[QOS] 配置 HTB QoS: 分层 + 软优先级（保底带宽 + sfq）\n")

    r1.cmd(f"tc qdisc del dev {intf} root 2>/dev/null || true")

    # 根 HTB
    r1.cmd(f"tc qdisc add dev {intf} root handle 1: htb default 20")
    r1.cmd(f"tc class add dev {intf} parent 1: classid 1:1 "
           f"htb rate {bw}mbit ceil {bw}mbit")

    # class 1:10 — 财务处 + 人事处（高优先级 + 保底）
    r1.cmd(f"tc class add dev {intf} parent 1:1 classid 1:10 htb "
           f"rate 12mbit ceil {bw}mbit prio 0")
    r1.cmd(f"tc qdisc add dev {intf} parent 1:10 handle 10: sfq perturb 10")

    # class 1:20 — 普通业务（中等优先级）
    r1.cmd(f"tc class add dev {intf} parent 1:1 classid 1:20 htb "
           f"rate 15mbit ceil 28mbit prio 1")
    r1.cmd(f"tc qdisc add dev {intf} parent 1:20 handle 20: sfq perturb 10")

    # class 1:30 — UDP/背景流（最低优先级）
    r1.cmd(f"tc class add dev {intf} parent 1:1 classid 1:30 htb "
           f"rate 6mbit ceil 20mbit prio 2")
    r1.cmd(f"tc qdisc add dev {intf} parent 1:30 handle 30: sfq perturb 10")

    # 过滤器
    r1.cmd(f"tc filter add dev {intf} parent 1: protocol ip prio 1 u32 "
           f"match ip src 10.0.5.0/24 flowid 1:10")
    r1.cmd(f"tc filter add dev {intf} parent 1: protocol ip prio 2 u32 "
           f"match ip src 10.0.6.0/24 flowid 1:10")
    r1.cmd(f"tc filter add dev {intf} parent 1: protocol ip prio 3 u32 "
           f"match ip src 10.0.1.0/24 flowid 1:30")
    r1.cmd(f"tc filter add dev {intf} parent 1: protocol ip prio 10 u32 "
           f"match ip src 0.0.0.0/0 flowid 1:20")

    info(f"[QOS] HTB QoS 已生效: {intf} {bw}Mbps\n"
         f"      财务+人事→class 1:10 rate=12Mbps ceil={bw}Mbps prio=0\n"
         f"      普通业务→class 1:20 rate=15Mbps ceil=28Mbps prio=1\n"
         f"      宿舍UDP→class 1:30 rate=6Mbps ceil=20Mbps prio=2\n"
         f"      三层合计 33Mbps < {bw}Mbps（欠分配）\n")


def clear_qos(r1):
    """清除所有 QoS 配置。"""
    info("[QOS] 清除所有 QoS 配置...\n")
    for dev in [f"r1-eth{i}" for i in range(7)]:
        r1.cmd(f"tc qdisc del dev {dev} root 2>/dev/null || true")
    r1.cmd("iptables -t mangle -F 2>/dev/null || true")
    info("[QOS] QoS 配置已清除\n")
