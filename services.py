"""
services.py — 资源共享服务模块 [兼容性存根]

⚠ 此文件保留用于向后兼容。
   新代码请使用 services/ 子包：
     from services.web import start_web_server
     from services.ftp import start_ftp_server
     from services.iperf import start_iperf_server

所有函数已迁移至 services/ 目录下的独立模块。
"""

from services.web import start_web_server
from services.ftp import start_ftp_server
from services.iperf import start_iperf_server

from mininet.log import info


def start_all_services(server, with_samba=False):
    """一键启动所有服务（单服务器版本，兼容旧调用）。"""
    info("=" * 60 + "\n")
    info("  启动网络服务\n")
    info("=" * 60 + "\n")
    start_web_server(server)
    start_ftp_server(server)
    start_iperf_server(server)
    info("[SERVICES] 所有服务已启动\n")


def start_dual_server_services(server1, server2, with_samba=False):
    """一键在双服务器上启动服务（兼容旧调用）。"""
    from services.iperf import start_dual_iperf
    info("=" * 60 + "\n")
    info("  启动双服务器网络服务\n")
    info("=" * 60 + "\n")
    start_web_server(server1)
    start_ftp_server(server1)
    start_dual_iperf(server1, server2)
    info("[SERVICES] 双服务器服务已全部启动\n")
