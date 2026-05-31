"""
models/qos_model.py — QoS 增强模型

组成:
  - Baseline（拓扑 + 服务 + 基础 ACL）
  - HTB QoS（财务处 + 人事处高优先级保障）
"""

from mininet.log import info

from models.baseline import deploy_baseline
from policies.qos import apply_htb_policy, clear_qos


def deploy_qos_model(with_cli=True, access_bw=None, access_delay=None,
                     bottleneck_bw=None, strict=False):
    """
    部署 QoS 增强模型。

    参数:
        with_cli:       是否进入 CLI
        access_bw:      统一接入带宽 (Mbps)
        access_delay:   统一接入时延
        bottleneck_bw:  瓶颈带宽 (Mbps), None 使用默认 35Mbps
        strict:         是否启用严格安全模式

    返回:
        (net, r1, hosts, switches)
    """
    info("=" * 60 + "\n")
    info("  部署 QoS 增强模型\n")
    info("  QoS=ON(HTB) | LB=OFF | Security=Basic ACL\n")
    info("=" * 60 + "\n")

    # 1. Baseline
    net, r1, hosts, switches = deploy_baseline(
        with_cli=False,
        access_bw=access_bw,
        access_delay=access_delay,
        strict=strict,
    )

    # 2. HTB QoS
    apply_htb_policy(r1, bottleneck_bw=bottleneck_bw)

    info("[MODEL] QoS 增强模型部署完成\n")

    if with_cli:
        from mininet.cli import CLI
        CLI(net)
        net.stop()

    return net, r1, hosts, switches
