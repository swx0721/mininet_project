"""
models/lb_model.py — 负载均衡增强模型

组成:
  - Baseline（拓扑 + 服务 + 基础 ACL）
  - Round Robin 负载均衡
"""

from mininet.log import info

from models.baseline import deploy_baseline
from policies.load_balance import LoadBalancer


def deploy_lb_model(with_cli=True, access_bw=None, access_delay=None,
                    lb_algorithm="round_robin", strict=False):
    """
    部署负载均衡增强模型。

    参数:
        with_cli:     是否进入 CLI
        access_bw:    统一接入带宽 (Mbps)
        access_delay: 统一接入时延
        lb_algorithm: 负载均衡算法 ("round_robin" | "static")
        strict:       是否启用严格安全模式

    返回:
        (net, r1, hosts, switches, LoadBalancer)
    """
    info("=" * 60 + "\n")
    info("  部署负载均衡增强模型\n")
    info(f"  QoS=OFF | LB=ON({lb_algorithm}) | Security=Basic ACL\n")
    info("=" * 60 + "\n")

    # 1. Baseline
    net, r1, hosts, switches = deploy_baseline(
        with_cli=False,
        access_bw=access_bw,
        access_delay=access_delay,
        strict=strict,
    )

    # 2. 负载均衡器
    lb = LoadBalancer(algorithm=lb_algorithm)

    info(f"[MODEL] 负载均衡增强模型部署完成（算法: {lb_algorithm}）\n")

    if with_cli:
        from mininet.cli import CLI
        CLI(net)
        net.stop()

    return net, r1, hosts, switches, lb
