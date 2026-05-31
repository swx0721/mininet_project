"""
models/baseline.py — Baseline 模型

组成:
  - 基础拓扑（core/topology.py）
  - Web + FTP + iperf3 服务（services/）
  - 基础 ACL（状态防火墙 + 白名单/黑名单）

不含:
  - QoS
  - 负载均衡
  - 入侵检测
  - SQLite 审计
"""

from mininet.log import info

from core.topology import build_topology
from core.server_cluster import get_server_hosts
from services.web import start_web_server
from services.ftp import start_ftp_server
from services.iperf import start_iperf_server
from security.acl import (
    apply_stateful_firewall, apply_acl_policies,
    apply_default_accept, apply_default_drop
)


def deploy_baseline(with_cli=True, access_bw=None, access_delay=None,
                    strict=False):
    """
    部署 Baseline 模型。

    参数:
        with_cli:     是否进入 CLI
        access_bw:    统一接入带宽 (Mbps)
        access_delay: 统一接入时延
        strict:       是否启用严格模式（默认 DROP）

    返回:
        (net, r1, hosts, switches)
    """
    info("=" * 60 + "\n")
    info("  部署 Baseline 模型\n")
    info("  QoS=OFF | LB=OFF | Security=Basic ACL\n")
    info("=" * 60 + "\n")

    # 1. 拓扑
    net, r1, hosts, switches = build_topology(
        with_cli=False,
        access_bw=access_bw,
        access_delay=access_delay,
    )

    # 2. 服务
    server1, server2 = get_server_hosts(hosts)
    if server1:
        start_web_server(server1)
        start_ftp_server(server1)
        start_iperf_server(server1)
    if server2:
        start_iperf_server(server2)
    info("[MODEL] 双服务器服务已启动\n")

    # 3. 基础安全（仅 ACL）
    apply_default_accept(r1)
    apply_stateful_firewall(r1)
    apply_acl_policies(r1)

    if strict:
        apply_default_drop(r1)

    info("[MODEL] Baseline 模型部署完成\n")

    if with_cli:
        from mininet.cli import CLI
        CLI(net)
        net.stop()

    return net, r1, hosts, switches
