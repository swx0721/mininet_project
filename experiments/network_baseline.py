"""
network_baseline.py - 统一实验基线网络策略

该模块定义两个消融实验共同使用的 baseline：
  - 相同校园网双服务器基础拓扑
  - 相同安全策略（由实验脚本调用 apply_all_security(..., with_qos=False)）
  - 相同服务器出口瓶颈 r1-eth5
  - 相同无优先级 FIFO 队列

在此基础上：
  - QoS 实验只替换队列策略：pfifo -> prio
  - 负载均衡实验只替换请求调度：static binding -> round robin
"""

from mininet.log import info


SERVER_INTF = "r1-eth5"
BASELINE_BOTTLENECK_BW = 35  # Mbps（降低拥塞强度，使 QoS 对比更平滑）
SERVER1_IP = "10.0.100.2"
SERVER2_IP = "10.0.100.3"

# 统一 baseline 的静态服务入口选择：无负载均衡、无动态调度。
UNIFIED_STATIC_MAPPING = {
    "finance1": SERVER1_IP,
    "finance_probe": SERVER1_IP,
    "teach1": SERVER1_IP,
    "office1": SERVER1_IP,
    "dorm1": SERVER2_IP,
    "lib1": SERVER2_IP,
}


def apply_unified_baseline_policy(r1, label="统一 Baseline"):
    """
    应用两个消融实验共同使用的无优化 baseline 网络策略。

    该策略只制造共享服务器出口瓶颈，不做 QoS 优先级分类：
      1. HTB 将 r1-eth5 限制为 BASELINE_BOTTLENECK_BW Mbps
      2. pfifo 作为无优先级 FIFO 队列
    """
    info(f"[BASELINE] 配置 {label}: "
         f"{SERVER_INTF}={BASELINE_BOTTLENECK_BW}Mbps, pfifo 无优先级队列\n")

    r1.cmd(f"tc qdisc del dev {SERVER_INTF} root 2>/dev/null || true")
    r1.cmd(f"tc qdisc add dev {SERVER_INTF} root handle 1: htb default 1")
    r1.cmd(f"tc class add dev {SERVER_INTF} parent 1: classid 1:1 "
           f"htb rate {BASELINE_BOTTLENECK_BW}mbit "
           f"ceil {BASELINE_BOTTLENECK_BW}mbit")
    r1.cmd(f"tc qdisc add dev {SERVER_INTF} parent 1:1 "
           f"handle 10: pfifo limit 1000")

    info(f"[BASELINE] {label} 已生效：共享出口瓶颈 + FIFO 队列\n")
