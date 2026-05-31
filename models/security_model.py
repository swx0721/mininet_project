"""
models/security_model.py — 安全增强模型

组成:
  - Baseline（拓扑 + 服务 + 基础 ACL）
  - 完整安全体系：端口扫描检测 + Flood 防护 + 自动封禁 + SQLite 审计
"""

from mininet.log import info

from models.baseline import deploy_baseline
from security.intrusion import apply_intrusion_detection
from security.audit_db import init_db


def deploy_security_model(with_cli=True, access_bw=None, access_delay=None,
                          strict=False):
    """
    部署安全增强模型。

    参数:
        with_cli:     是否进入 CLI
        access_bw:    统一接入带宽 (Mbps)
        access_delay: 统一接入时延
        strict:       是否启用严格安全模式

    返回:
        (net, r1, hosts, switches)
    """
    info("=" * 60 + "\n")
    info("  部署安全增强模型\n")
    info("  QoS=OFF | LB=OFF | Security=Full(ACL + IDS + Audit)\n")
    info("=" * 60 + "\n")

    # 1. Baseline（已含基础 ACL）
    net, r1, hosts, switches = deploy_baseline(
        with_cli=False,
        access_bw=access_bw,
        access_delay=access_delay,
        strict=strict,
    )

    # 2. 入侵检测 + Flood 防护
    apply_intrusion_detection(r1)

    # 3. SQLite 审计中心
    init_db(r1)

    info("[MODEL] 安全增强模型部署完成\n")

    if with_cli:
        from mininet.cli import CLI
        CLI(net)
        net.stop()

    return net, r1, hosts, switches
