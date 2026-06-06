"""
services/web.py — Web 服务器

在服务器节点上启动线程化 HTTP Web 服务（端口 80）。
"""

from mininet.log import info


def start_web_server(server):
    """启动 HTTP Web 服务。"""
    info("[SERVICES] 启动 Web 服务器 (端口 80, 线程化)...\n")

    server.cmd("mkdir -p /tmp/www")

    server.cmd('cat > /tmp/www/index.html << "EOF"\n'
               '<!DOCTYPE html>\n'
               '<html lang="zh-CN">\n'
               '<head><meta charset="UTF-8">\n'
               '<title>校园网 Web 服务</title>\n'
               '<style>\n'
               '  body { font-family: Arial, sans-serif; margin: 40px; }\n'
               '  h1 { color: #1565C0; }\n'
               '  .info { background: #E3F2FD; padding: 15px; border-radius: 5px; }\n'
               '</style>\n'
               '</head>\n'
               '<body>\n'
               '  <h1>欢迎访问校园网 Web 服务器</h1>\n'
               '  <div class="info">\n'
               '    <p>这是校园网内部 Web 服务。</p>\n'
               '    <p>本系统提供文件共享和信息发布功能。</p>\n'
               '  </div>\n'
               '  <hr>\n'
               '  <p><small>Campus Network Simulation - Mininet</small></p>\n'
               '</body>\n'
               '</html>\n'
               'EOF')

    # 大文件用于带宽/QoS测试（50MB）
    server.cmd("dd if=/dev/zero of=/tmp/www/bigfile.bin bs=1M count=50 2>/dev/null")
    info("[SERVICES] 已创建 50MB 大文件 (/tmp/www/bigfile.bin)\n")

    # 线程化 HTTP 服务器（写入 .py 文件，避免 Mininet cmd() 解析内联多行代码失败）
    import time
    server.cmd('cat > /tmp/start_http.py << \'PYEOF\'\n'
               'import socketserver, http.server, os\n'
               'class THTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):\n'
               '    allow_reuse_address = True\n'
               '    daemon_threads = True\n'
               'os.chdir("/tmp/www")\n'
               's = THTTPServer(("0.0.0.0", 80), http.server.SimpleHTTPRequestHandler)\n'
               's.serve_forever()\n'
               'PYEOF\n')
    server.cmd("python3 /tmp/start_http.py &")
    time.sleep(0.5)
    # 验证启动是否成功
    check = server.cmd("netstat -tlnp 2>/dev/null | grep ':80 ' || ss -tlnp 2>/dev/null | grep ':80 ' || echo NOT_LISTEN")
    if 'NOT_LISTEN' in check:
        info("[SERVICES] [WARN] Web 服务器可能未成功启动，请检查 pyftpdlib 是否安装\n")
    info("[SERVICES] Web 服务已启动 (http://10.0.60.2)\n")


def create_test_file(server, filename, size_mb=2):
    """创建指定大小的测试文件用于负载均衡实验。"""
    server.cmd(f"dd if=/dev/zero of=/tmp/www/{filename} bs=1M count={size_mb} 2>/dev/null")
    info(f"[SERVICES] 已创建 {size_mb}MB 测试文件 (/tmp/www/{filename})\n")
