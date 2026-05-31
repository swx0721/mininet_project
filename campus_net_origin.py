from mininet.net import Mininet
from mininet.node import Node, OVSBridge
from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import setLogLevel


class LinuxRouter(Node):
    def config(self, **params):
        super(LinuxRouter, self).config(**params)
        self.cmd("sysctl -w net.ipv4.ip_forward=1")

    def terminate(self):
        self.cmd("sysctl -w net.ipv4.ip_forward=0")
        super(LinuxRouter, self).terminate()


def build_topology():
    net = Mininet(link=TCLink, switch=OVSBridge, controller=None)

    # 路由器
    r1 = net.addHost("r1", cls=LinuxRouter)

    # 交换机
    s_dorm = net.addSwitch("s_dorm", dpid="0000000000000001")
    s_teach = net.addSwitch("s_teach", dpid="0000000000000002")
    s_lib = net.addSwitch("s_lib", dpid="0000000000000003")
    s_office = net.addSwitch("s_office", dpid="0000000000000004")
    s_finance = net.addSwitch("s_finance", dpid="0000000000000005")
    s_server = net.addSwitch("s_server", dpid="0000000000000006")
    s_hr = net.addSwitch("s_hr", dpid="0000000000000007")

    # 人事处
    hr1 = net.addHost("hr1", ip="10.0.6.2/24", defaultRoute="via 10.0.6.1")
    hr2 = net.addHost("hr2", ip="10.0.6.3/24", defaultRoute="via 10.0.6.1")

    # 宿舍区
    dorm1 = net.addHost("dorm1", ip="10.0.1.2/24", defaultRoute="via 10.0.1.1")
    dorm2 = net.addHost("dorm2", ip="10.0.1.3/24", defaultRoute="via 10.0.1.1")

    # 教学楼
    teach1 = net.addHost("teach1", ip="10.0.2.2/24", defaultRoute="via 10.0.2.1")
    teach2 = net.addHost("teach2", ip="10.0.2.3/24", defaultRoute="via 10.0.2.1")

    # 图书馆
    lib1 = net.addHost("lib1", ip="10.0.3.2/24", defaultRoute="via 10.0.3.1")
    lib2 = net.addHost("lib2", ip="10.0.3.3/24", defaultRoute="via 10.0.3.1")

    # 办公楼
    office1 = net.addHost("office1", ip="10.0.4.2/24", defaultRoute="via 10.0.4.1")
    office2 = net.addHost("office2", ip="10.0.4.3/24", defaultRoute="via 10.0.4.1")

    # 财务处
    finance1 = net.addHost("finance1", ip="10.0.5.2/24", defaultRoute="via 10.0.5.1")
    finance2 = net.addHost("finance2", ip="10.0.5.3/24", defaultRoute="via 10.0.5.1")

    # Web/FTP 服务器
    server = net.addHost("server", ip="10.0.100.2/24", defaultRoute="via 10.0.100.1")

    # 主机连接交换机（配置带宽和时延以模拟真实网络环境）
    # 宿舍区：带宽较低，时延适中
    net.addLink(dorm1, s_dorm, bw=10, delay="5ms")
    net.addLink(dorm2, s_dorm, bw=10, delay="5ms")

    # 教学楼：带宽适中，时延稍高（距离较远）
    net.addLink(teach1, s_teach, bw=20, delay="10ms")
    net.addLink(teach2, s_teach, bw=20, delay="10ms")

    # 图书馆：带宽适中，时延较低
    net.addLink(lib1, s_lib, bw=30, delay="5ms")
    net.addLink(lib2, s_lib, bw=30, delay="5ms")

    # 办公楼：带宽较高，时延较低
    net.addLink(office1, s_office, bw=50, delay="2ms")
    net.addLink(office2, s_office, bw=50, delay="2ms")

    # 财务处：带宽高，时延低（关键部门）
    net.addLink(finance1, s_finance, bw=50, delay="2ms")
    net.addLink(finance2, s_finance, bw=50, delay="2ms")

    # 人事处：带宽高，时延低（关键部门）
    net.addLink(hr1, s_hr, bw=50, delay="2ms")
    net.addLink(hr2, s_hr, bw=50, delay="2ms")

    # 服务器区：最高带宽，最低时延
    net.addLink(server, s_server, bw=100, delay="1ms")

    # 各区域交换机连接路由器（上行链路分配更高带宽）
    net.addLink(s_dorm, r1, intfName2="r1-eth0", bw=100, delay="5ms")
    net.addLink(s_teach, r1, intfName2="r1-eth1", bw=100, delay="10ms")
    net.addLink(s_lib, r1, intfName2="r1-eth2", bw=100, delay="5ms")
    net.addLink(s_office, r1, intfName2="r1-eth3", bw=200, delay="2ms")
    net.addLink(s_finance, r1, intfName2="r1-eth4", bw=200, delay="2ms")
    net.addLink(s_server, r1, intfName2="r1-eth5", bw=1000, delay="1ms")
    net.addLink(s_hr, r1, intfName2="r1-eth6", bw=200, delay="2ms")
    net.start()

    # 配置路由器接口 IP
    r1.cmd("ifconfig r1-eth0 10.0.1.1/24")
    r1.cmd("ifconfig r1-eth1 10.0.2.1/24")
    r1.cmd("ifconfig r1-eth2 10.0.3.1/24")
    r1.cmd("ifconfig r1-eth3 10.0.4.1/24")
    r1.cmd("ifconfig r1-eth4 10.0.5.1/24")
    r1.cmd("ifconfig r1-eth6 10.0.6.1/24")
    r1.cmd("ifconfig r1-eth5 10.0.100.1/24")

    # ========== 细粒度 ACL 安全策略 ==========
    # 规则顺序：先放行合法流量，再记录并阻止非法流量

    # --- 白名单：明确允许的跨部门访问 ---
    # 允许办公楼访问人事处（日常公务）
    r1.cmd("iptables -A FORWARD -s 10.0.4.0/24 -d 10.0.6.0/24 -j ACCEPT")
    # 允许办公楼访问财务处（日常公务）
    r1.cmd("iptables -A FORWARD -s 10.0.4.0/24 -d 10.0.5.0/24 -j ACCEPT")

    # --- 黑名单：记录日志并阻止非法访问 ---
    # 禁止宿舍区访问财务处（带日志审计）
    r1.cmd('iptables -A FORWARD -s 10.0.1.0/24 -d 10.0.5.0/24 -j LOG --log-prefix "ACL_DENY:DORM2FIN: " --log-level 4')
    r1.cmd("iptables -A FORWARD -s 10.0.1.0/24 -d 10.0.5.0/24 -j DROP")

    # 禁止教学楼访问财务处（带日志审计）
    r1.cmd('iptables -A FORWARD -s 10.0.2.0/24 -d 10.0.5.0/24 -j LOG --log-prefix "ACL_DENY:TEACH2FIN: " --log-level 4')
    r1.cmd("iptables -A FORWARD -s 10.0.2.0/24 -d 10.0.5.0/24 -j DROP")

    # 禁止宿舍区访问人事处（带日志审计）
    r1.cmd('iptables -A FORWARD -s 10.0.1.0/24 -d 10.0.6.0/24 -j LOG --log-prefix "ACL_DENY:DORM2HR: " --log-level 4')
    r1.cmd("iptables -A FORWARD -s 10.0.1.0/24 -d 10.0.6.0/24 -j DROP")

    # 禁止教学楼访问人事处（带日志审计）
    r1.cmd('iptables -A FORWARD -s 10.0.2.0/24 -d 10.0.6.0/24 -j LOG --log-prefix "ACL_DENY:TEACH2HR: " --log-level 4')
    r1.cmd("iptables -A FORWARD -s 10.0.2.0/24 -d 10.0.6.0/24 -j DROP")

    # --- 防止 ICMP Flood（Ping 攻击） ---
    # 限制入站 ICMP 回显请求速率，防止宿舍区/教学楼主机恶意 Ping  Flood
    r1.cmd("iptables -A FORWARD -p icmp --icmp-type echo-request -m limit --limit 1/s --limit-burst 5 -j ACCEPT")
    r1.cmd("iptables -A FORWARD -p icmp --icmp-type echo-request -j DROP")

    # ========== 启动资源共享服务 ==========

    # 启动 Web 服务器（HTTP 服务）
    server.cmd("mkdir -p /tmp/www")
    server.cmd('echo "<html><body><h1>Welcome to Campus Web Server</h1>" > /tmp/www/index.html')
    server.cmd('echo "<p>This is the internal campus network web service.</p></body></html>" >> /tmp/www/index.html')
    server.cmd("cd /tmp/www && python3 -m http.server 80 &")

    # 启动 FTP 服务器（文件共享服务）
    # 使用 pyftpdlib 提供匿名 FTP 访问，共享 /tmp/ftp 目录下的文件
    server.cmd("mkdir -p /tmp/ftp")
    server.cmd('echo "Welcome to Campus FTP Server - File Sharing Center" > /tmp/ftp/README.txt')
    server.cmd('echo "This is a shared document for all campus users." > /tmp/ftp/share_doc.txt')
    server.cmd("cd /tmp/ftp && python3 -m pyftpdlib -p 21 -w &")
    print("[INFO] Web 服务已启动 (端口 80)")
    print("[INFO] FTP 服务已启动 (端口 21, 匿名可写)")

    # ========== 网络状态提示 ==========
    print("=" * 50)
    print("校园网络拓扑已启动!")
    print("=" * 50)
    print("子网划分方案：")
    print("  - 宿舍区: 10.0.1.0/24 (预留: 10.0.11.0/24)")
    print("  - 教学楼: 10.0.2.0/24 (预留: 10.0.12.0/24)")
    print("  - 图书馆: 10.0.3.0/24 (预留: 10.0.13.0/24)")
    print("  - 办公楼: 10.0.4.0/24 (预留: 10.0.14.0/24)")
    print("  - 财务处: 10.0.5.0/24 (预留: 10.0.15.0/24)")
    print("  - 人事处: 10.0.6.0/24 (预留: 10.0.16.0/24)")
    print("  - 服务器区: 10.0.100.0/24 (预留: 10.0.110.0/24)")
    print("=" * 50)
    print("ACL 安全策略已生效 (日志前缀: ACL_DENY_*)")
    print("查看日志: 在 CLI 中输入 'r1 dmesg | tail'")
    print("=" * 50)
    print("可用服务测试命令：")
    print("  - Web: 任意主机执行 'curl http://10.0.100.2'")
    print("  - FTP: 任意主机执行 'curl ftp://10.0.100.2/README.txt'")
    print("  - Ping: 任意主机执行 'ping 10.0.100.2'")
    print("=" * 50)

    CLI(net)

    net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    build_topology()
