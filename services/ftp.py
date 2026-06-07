"""
services/ftp.py — FTP 服务器（基于 vsftpd 真实服务）

在 Server1/Server2 上启动真实的 vsftpd 服务（端口 21），支持匿名访问。
替代之前的 pyftpdlib 方案，提供标准 FTP 协议支持。

用法:
    from services.ftp import start_ftp_server
    start_ftp_server(server1)
    start_ftp_server(server2)

客户端访问:
    dorm1 ftp 10.0.60.2          # 匿名登录
    dorm1 curl ftp://10.0.60.2/   # 列出目录

前置条件:
    sudo apt-get install vsftpd -y   # 必须在宿主机上预装！
"""

import time
import os

from mininet.log import info


# 用于区分 server1/server2 的配置文件（避免两个节点写同一个 /etc/vsftpd.conf）
_SERVER_INSTANCE_COUNTER = 0


def start_ftp_server(server):
    """
    在指定服务器节点上启动 vsftpd FTP 服务。

    配置要点:
      - 匿名访问（anonymous）
      - 根目录: /tmp/ftp/
      - 每个 server 使用独立的配置文件 (/tmp/vsftpd_s1.conf, /tmp/vsftpd_s2.conf)
      - 监听端口 21

    Args:
        server: Mininet 主机节点（server1 / server2）
    """
    global _SERVER_INSTANCE_COUNTER
    _SERVER_INSTANCE_COUNTER += 1
    instance_id = _SERVER_INSTANCE_COUNTER
    config_path = f"/tmp/vsftpd_s{instance_id}.conf"
    log_path = f"/tmp/vsftpd_s{instance_id}.log"
    pid_path = f"/tmp/vsftpd_s{instance_id}.pid"

    srv_ip = server.cmd("hostname -I 2>/dev/null | awk '{print $1}'").strip()
    info(f"[SERVICES] 启动 FTP 服务器 ({srv_ip}:21)...\n")

    # ---- 1. 检查 vsftpd 是否已安装（需宿主机预装）----
    install_out = server.cmd(
        "timeout 2 which vsftpd 2>/dev/null && echo INSTALLED || echo NOT_FOUND"
    ).strip()
    if "NOT_FOUND" in install_out or not install_out:
        info("[SERVICES] [ERROR] vsftpd 未安装！\n"
             "[SERVICES] 请在宿主机上执行: sudo apt-get install vsftpd -y\n")
        return False

    # ---- 2. 准备 FTP 共享目录 ----
    server.cmd("mkdir -p /tmp/ftp/pub/notices /tmp/ftp/pub/software")

    server.cmd('echo "===========================================" > /tmp/ftp/README.txt')
    server.cmd('echo "  Campus Network FTP Server" >> /tmp/ftp/README.txt')
    server.cmd('echo "===========================================" >> /tmp/ftp/README.txt')
    server.cmd('echo "" >> /tmp/ftp/README.txt')
    server.cmd('echo "Welcome to campus network file sharing!" >> /tmp/ftp/README.txt')
    server.cmd('echo "" >> /tmp/ftp/README.txt')
    server.cmd(f'echo "Server: {srv_ip}" >> /tmp/ftp/README.txt')
    server.cmd('echo "Available: README.txt, share_doc.txt, pub/" >> /tmp/ftp/README.txt')

    server.cmd('echo "Public document for all campus zones." > /tmp/ftp/share_doc.txt')
    server.cmd('echo "Please comply with campus network policies." >> /tmp/ftp/share_doc.txt')
    server.cmd('echo "Maintenance: Saturday 02:00-04:00." > /tmp/ftp/pub/notices/maintenance.txt')

    # ---- 3. 写入独立的 vsftpd 配置文件 ----
    vsftpd_conf = f"""\
listen=YES
listen_ipv6=NO
listen_port=21
anonymous_enable=YES
local_enable=NO
write_enable=YES
anon_upload_enable=YES
anon_mkdir_write_enable=YES
anon_other_write_enable=YES
connect_timeout=60
data_connection_timeout=300
idle_session_timeout=600
xferlog_std_format=YES
anon_root=/tmp/ftp
local_root=/tmp/ftp
pasv_min_port=50000
pasv_max_port=50010
seccomp_sandbox=NO
hide_ids=YES
xferlog_file=/tmp/vsftpd_xfer_s{instance_id}.log
"""
    server.cmd(f"cat > {config_path} << 'VSFTPD_EOF'\n{vsftpd_conf}\nVSFTPD_EOF")

    # ---- 4. 启动 vsftpd ----
    # 使用 setsid + nohup 确保进程完全脱离终端，避免 Mininet cmd() 阻塞
    server.cmd(
        f"setsid vsftpd {config_path} "
        f"> {log_path} 2>&1 < /dev/null &"
    )
    time.sleep(0.6)

    # ---- 5. 验证启动 ----
    check = server.cmd(
        "ss -tlnp 2>/dev/null | grep ':21 ' | head -1 || "
        "netstat -tlnp 2>/dev/null | grep ':21 ' | head -1 || "
        "echo NOT_LISTEN"
    ).strip()
    if 'NOT_LISTEN' in check or not check:
        log_content = server.cmd(f"cat {log_path} 2>/dev/null | tail -10").strip()
        info(f"[SERVICES] [WARN] FTP 可能未启动\n"
             f"[SERVICES] vsftpd log:\n{log_content}\n")
        return False

    info(f"[SERVICES] FTP 服务已启动 (ftp://{srv_ip}/, vsftpd, 匿名可读写)\n")
    return True


def stop_ftp_server(server):
    """停止 FTP 服务。"""
    server.cmd("timeout 3 pkill -9 vsftpd 2>/dev/null; true")
    info("[SERVICES] FTP 服务已停止\n")
