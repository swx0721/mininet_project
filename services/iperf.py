"""
services/iperf.py — iperf3 性能测试服务

在服务器节点上启动 iperf3 服务（端口 5201），
支持多端口并发测试。
"""

from mininet.log import info


def start_iperf_server(server, ports=None, skip_kill=False):
    """
    启动 iperf3 服务。

    参数:
        server:    服务器节点
        ports:     端口列表，默认 [5201]
        skip_kill: 是否跳过 pkill（当调用方已统一清理时使用）
    """
    if ports is None:
        ports = [5201]

    if not skip_kill:
        server.cmd("pkill -f iperf3 2>/dev/null || true")

    for port in ports:
        server.cmd(f"iperf3 -s -p {port} -D")
        info(f"[SERVICES] iperf3 服务已启动 (端口 {port})\n")


def start_dual_iperf(server1, server2):
    """
    在两个服务器上分别启动 iperf3 服务（对称端口）。
    两台服务器均开放 5201-5204 端口，确保 RR 分配时所有流都能命中。

    ⚠️ 关键：由于 Mininet 节点共享宿主机 PID 命名空间，
    必须先统一清理所有残留 iperf3 进程，再分别启动两个服务器。
    """
    import time

    # === 统一清理：在启动任何服务器之前，一次性清理所有残留 ===
    server1.cmd("pkill -f iperf3 2>/dev/null || true")
    server2.cmd("pkill -f iperf3 2>/dev/null || true")
    time.sleep(1.5)

    # === 启动两个服务器（skip_kill=True 避免互相误杀）===
    # 对称端口：两服务器均开放 5201-5207，确保所有客户端独占端口
    # 避免 teach1(TCP:5202) 和 lib1(TCP:5205) 等共用端口导致解析失败
    # 5207 为 hr1（人事处）保留
    start_iperf_server(server1, ports=[5201, 5202, 5203, 5204, 5205, 5206, 5207], skip_kill=True)
    start_iperf_server(server2, ports=[5201, 5202, 5203, 5204, 5205, 5206, 5207], skip_kill=True)

    # === 等待端口完全打开 ===
    time.sleep(2)

    # === 验证端口是否打开 ===
    all_ports = [5201, 5202, 5203, 5204, 5205, 5206, 5207]
    for server, name in [(server1, "Server1"), (server2, "Server2")]:
        for port in all_ports:
            result = server.cmd(
                f"ss -tuln 2>/dev/null | grep ':{port} ' || "
                f"echo 'port_not_found'"
            )
            if "port_not_found" in result:
                info(f"[SERVICES] ⚠ {name} 端口 {port} 未监听，重试启动...\n")
                server.cmd(f"iperf3 -s -p {port} -D")
                time.sleep(0.5)
            else:
                info(f"[SERVICES] ✓ {name} 端口 {port} 已就绪\n")

    info("[SERVICES] 双服务器 iperf3 已全部启动并就绪\n")
