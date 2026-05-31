"""
services/iperf.py — iperf3 性能测试服务

在服务器节点上启动 iperf3 服务（端口 5201），
支持多端口并发测试。
"""

from mininet.log import info


def start_iperf_server(server, ports=None):
    """
    启动 iperf3 服务。

    参数:
        server: 服务器节点
        ports:  端口列表，默认 [5201]
    """
    if ports is None:
        ports = [5201]

    server.cmd("pkill -f iperf3 2>/dev/null || true")

    for port in ports:
        server.cmd(f"iperf3 -s -p {port} -D")
        info(f"[SERVICES] iperf3 服务已启动 (端口 {port})\n")


def start_dual_iperf(server1, server2):
    """
    在两个服务器上分别启动 iperf3 服务。
    Server1: 端口 5201-5204
    Server2: 端口 5201-5202
    """
    start_iperf_server(server1, ports=[5201, 5202, 5203, 5204])
    start_iperf_server(server2, ports=[5201, 5202])
    info("[SERVICES] 双服务器 iperf3 已全部启动\n")
