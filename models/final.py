"""
models/final.py — CampusNet-Final 统一模型

组成（全部模块）:
  - Baseline（拓扑 + 服务 + 基础 ACL）
  - HTB QoS（财务处 + 人事处高优先级）
  - Round Robin 负载均衡
  - 完整安全体系（端口扫描检测 + Flood 防护 + 自动封禁 + SQLite 审计）
"""

from mininet.log import info

from models.baseline import deploy_baseline
from policies.qos import apply_htb_policy
from policies.load_balance import LoadBalancer
from security.intrusion import apply_intrusion_detection
from security.audit_db import init_db


def deploy_final(with_cli=True, access_bw=None, access_delay=None,
                 bottleneck_bw=None, lb_algorithm="round_robin",
                 strict=False):
    """
    部署 CampusNet-Final 统一模型。

    参数:
        with_cli:       是否进入 CLI
        access_bw:      统一接入带宽 (Mbps)
        access_delay:   统一接入时延
        bottleneck_bw:  瓶颈带宽 (Mbps), None 使用默认 35Mbps
        lb_algorithm:   负载均衡算法
        strict:         是否启用严格安全模式

    返回:
        (net, r1, hosts, switches, LoadBalancer)
    """
    info("=" * 60 + "\n")
    info("  部署 CampusNet-Final 统一模型\n")
    info("  QoS=ON(HTB) | LB=ON(RR) | Security=Full\n")
    info("=" * 60 + "\n")

    # 1. Baseline（含基础 ACL）
    net, r1, hosts, switches = deploy_baseline(
        with_cli=False,
        access_bw=access_bw,
        access_delay=access_delay,
        strict=strict,
    )

    # 2. HTB QoS
    apply_htb_policy(r1, bottleneck_bw=bottleneck_bw)

    # 3. 负载均衡器
    lb = LoadBalancer(algorithm=lb_algorithm)

    # 4. 入侵检测 + Flood 防护
    apply_intrusion_detection(r1)

    # 5. SQLite 审计中心
    init_db(r1)

    info("[MODEL] CampusNet-Final 统一模型部署完成\n")

    if with_cli:
        from mininet.cli import CLI
        CLI(net)
        net.stop()

    return net, r1, hosts, switches, lb
