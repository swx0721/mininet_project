"""
services/ftp.py — FTP 服务器

在服务器节点上启动 FTP 服务（端口 21），使用 pyftpdlib。
"""

from mininet.log import info


def start_ftp_server(server):
    """启动 FTP 服务。"""
    info("[SERVICES] 启动 FTP 服务器 (端口 21)...\n")

    server.cmd("mkdir -p /tmp/ftp")

    server.cmd('echo "===========================================" > /tmp/ftp/README.txt')
    server.cmd('echo "  校园网 FTP 服务器 - 文件共享中心" >> /tmp/ftp/README.txt')
    server.cmd('echo "===========================================" >> /tmp/ftp/README.txt')
    server.cmd('echo "" >> /tmp/ftp/README.txt')
    server.cmd('echo "欢迎使用校园网文件共享服务！" >> /tmp/ftp/README.txt')
    server.cmd('echo "此目录包含以下共享资源：" >> /tmp/ftp/README.txt')
    server.cmd('echo "  - share_doc.txt: 公共共享文档" >> /tmp/ftp/README.txt')
    server.cmd('echo "  - notices/: 校园通知" >> /tmp/ftp/README.txt')
    server.cmd('echo "  - software/: 常用软件下载" >> /tmp/ftp/README.txt')
    server.cmd('echo "" >> /tmp/ftp/README.txt')
    server.cmd('echo "最后更新: 2026-05-31" >> /tmp/ftp/README.txt')

    server.cmd('echo "这是所有校园网用户共享的公共文档。" > /tmp/ftp/share_doc.txt')
    server.cmd('echo "请遵守校园网使用规范，勿上传非法内容。" >> /tmp/ftp/share_doc.txt')

    server.cmd("mkdir -p /tmp/ftp/notices /tmp/ftp/software")
    server.cmd('echo "校园网将于本周六凌晨2:00-4:00进行维护升级。" > /tmp/ftp/notices/maintenance.txt')

    server.cmd("cd /tmp/ftp && python3 -m pyftpdlib -p 21 -w &")
    info("[SERVICES] FTP 服务已启动 (ftp://10.0.100.2, 匿名可写)\n")
