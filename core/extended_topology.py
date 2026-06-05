"""
core/extended_topology.py — 扩展网络拓扑（VPN + NAT + 双校区）

新增节点类型：
  - VPN Gateway (vpn_gw): 虚拟专用网网关，分配 10.0.80.0/24
  - Home Router (home_rt): 校外家庭路由器
  - Internet Router (inet_rt): 公网路由器（NAT 边界）
  - Campus-B Router (campusb_rt): 第二校区核心路由器
  - WAN Router (wan_rt): 跨校区互联 WAN 路由器
  - 外网服务器 (ext_server): 公网服务器 (203.0.113.0/28)

地址规划（与原有 10.0.0.0/16 无冲突）：
  - Campus-A:  10.0.0.0/16（原有）
  - VPN 地址池: 10.0.80.0/24（新增，独立于业务区）
  - 校外家庭网: 192.168.100.0/24
  - 公网段:     203.0.113.0/28
  - Campus-B:  10.1.0.0/16
  - WAN 互联:   172.16.0.0/30
"""

import random
from mininet.net import Mininet
from mininet.link import TCLink
from mininet.node import OVSBridge
from mininet.log import info
from mininet.cli import CLI

from core.router import LinuxRouter
from utils import print_separator, print_subnet_info


# ==================== Campus-A 原有拓扑（保持不变） ====================
# 复用 core/topology.py 的 build_topology 函数

# ==================== VPN 配置 ====================

VPN_SUBNET = "10.0.80.0/24"        # VPN 虚拟地址池
VPN_GW_IP = "10.0.80.1/24"         # VPN 网关地址
VPN_CLIENT_IP = "10.0.80.10/24"    # VPN 客户端分配地址
VPN_GW_LAN_IP = "10.0.34.10/24"    # VPN 网关在校园网侧的接口地址（接入办公楼子网）

# 校外家庭网络
HOME_SUBNET = "192.168.100.0/24"
HOME_RT_LAN_IP = "192.168.100.1/24"
HOME_PC_IP = "192.168.100.10/24"

# ==================== NAT / 公网配置 ====================

INTERNET_SUBNET = "203.0.113.0/28"       # 模拟公网段
INTERNET_RT_LAN_IP = "203.0.113.1/28"    # 公网路由器 LAN 侧
INTERNET_RT_WAN_IP = "203.0.113.14/28"   # 公网路由器 WAN 侧 (校园网出口)
EXT_SERVER_IP = "203.0.113.10/28"        # 外网服务器

# ==================== 双校区配置 ====================

CAMPUS_B_SUBNET = "10.1.0.0/16"
CAMPUSB_RT_LAN_IP = "10.1.0.1/16"
CAMPUSB_HOST_IP = "10.1.0.10/16"

WAN_SUBNET = "172.16.0.0/30"
WAN_RT_IP_A = "172.16.0.1/30"    # WAN 路由器 → Campus-A 侧
WAN_RT_IP_B = "172.16.0.2/30"    # WAN 路由器 → Campus-B 侧
CAMPUSA_WAN_IP = "172.16.0.1/30" # Campus-A r1 的 WAN 接口
CAMPUSB_WAN_IP = "172.16.0.2/30" # Campus-B 路由器的 WAN 接口


def build_extended_topology(with_cli=True, access_bw=None, access_delay=None, core_bw=None,
                           include_vpn=True, include_nat=True, include_dual_campus=True):
    """
    构建扩展拓扑：原有 Campus-A + VPN Gateway + 校外网络 + Internet Router + Campus-B。
    
    参数:
        with_cli:           是否进入 Mininet CLI
        access_bw:          接入链路带宽 (Mbps)
        access_delay:       接入链路时延 (ms)
        core_bw:            核心链路带宽 (Mbps)
        include_vpn:        是否包含 VPN 模块
        include_nat:        是否包含 NAT 模块
        include_dual_campus: 是否包含双校区互联模块
    
    返回:
        net, r1 (Campus-A 路由器), hosts, switches, extra_nodes
    """
    from core.topology import build_topology
    
    # 先构建原有 Campus-A 拓扑
    net, r1, hosts, switches = build_topology(
        with_cli=False,
        access_bw=access_bw,
        access_delay=access_delay,
        core_bw=core_bw
    )
    
    extra_nodes = {
        "routers": {},
        "hosts": {},
        "switches": {}
    }
    
    # ──────────────────────────────────────────────
    # Phase 1: VPN 远程接入模块
    # ──────────────────────────────────────────────
    if include_vpn:
        info("\n" + "=" * 60 + "\n")
        info("[EXTENDED] 部署 VPN 远程接入模块\n")
        info("=" * 60 + "\n")
        
        # VPN 网关（LinuxRouter，双接口：校园网侧 + VPN 虚拟网侧）
        vpn_gw = net.addHost("vpn_gw", cls=LinuxRouter, ip=VPN_GW_LAN_IP)
        extra_nodes["routers"]["vpn_gw"] = vpn_gw
        
        # 家庭路由器
        home_rt = net.addHost("home_rt", cls=LinuxRouter, ip=HOME_RT_LAN_IP)
        extra_nodes["routers"]["home_rt"] = home_rt
        
        # 校外家庭 PC
        home_pc = net.addHost("home_pc", ip=HOME_PC_IP)
        extra_nodes["hosts"]["home_pc"] = home_pc
        
        # 家庭网络交换机
        home_sw = net.addSwitch("s_home", cls=OVSBridge, dpid="0000000000001000")
        extra_nodes["switches"]["s_home"] = home_sw
        
        # 链路：家庭 PC → 家庭交换机 → 家庭路由器
        net.addLink(home_pc, home_sw, cls=TCLink,
                    bw=access_bw or 100, delay=access_delay or "5ms")
        net.addLink(home_sw, home_rt, cls=TCLink,
                    bw=access_bw or 100, delay=access_delay or "1ms")
        
        # 链路：家庭路由器 → VPN 网关（模拟公网隧道）
        net.addLink(home_rt, vpn_gw, cls=TCLink,
                    bw=50, delay="20ms")  # 模拟互联网延迟
        
        # 链路：VPN 网关 → 办公楼交换机（接入校园网内部）
        net.addLink(vpn_gw, switches["office"], cls=TCLink,
                    bw=100, delay="1ms")
        
        info("[EXTENDED] VPN 模块已部署: home_pc(192.168.100.10) → home_rt → vpn_gw(10.0.80.0/24) → office_sw\n")
    
    # ──────────────────────────────────────────────
    # Phase 2: NAT 模块（公网路由器）
    # ──────────────────────────────────────────────
    if include_nat:
        info("\n" + "=" * 60 + "\n")
        info("[EXTENDED] 部署 NAT 模块\n")
        info("=" * 60 + "\n")
        
        # 公网路由器
        inet_rt = net.addHost("inet_rt", cls=LinuxRouter, ip=INTERNET_RT_LAN_IP)
        extra_nodes["routers"]["inet_rt"] = inet_rt
        
        # 外网服务器
        ext_server = net.addHost("ext_server", ip=EXT_SERVER_IP)
        extra_nodes["hosts"]["ext_server"] = ext_server
        
        # 公网交换机
        inet_sw = net.addSwitch("s_inet", cls=OVSBridge, dpid="0000000000001001")
        extra_nodes["switches"]["s_inet"] = inet_sw
        
        # 链路：外网服务器 → 公网交换机 → 公网路由器
        net.addLink(ext_server, inet_sw, cls=TCLink,
                    bw=100, delay="1ms")
        net.addLink(inet_sw, inet_rt, cls=TCLink,
                    bw=100, delay="1ms")
        
        # 链路：公网路由器 → Campus-A r1（r1 新增 WAN 接口）
        net.addLink(inet_rt, r1, cls=TCLink,
                    bw=20, delay="10ms")  # 模拟互联网出口带宽
        
        info("[EXTENDED] NAT 模块已部署: ext_server(203.0.113.10) → inet_rt → r1\n")
    
    # ──────────────────────────────────────────────
    # Phase 3: 双校区互联模块
    # ──────────────────────────────────────────────
    if include_dual_campus:
        info("\n" + "=" * 60 + "\n")
        info("[EXTENDED] 部署双校区互联模块\n")
        info("=" * 60 + "\n")
        
        # WAN 路由器（互联两个校区）
        wan_rt = net.addHost("wan_rt", cls=LinuxRouter, ip=WAN_RT_IP_A)
        extra_nodes["routers"]["wan_rt"] = wan_rt
        
        # Campus-B 路由器
        campusb_rt = net.addHost("campusb_rt", cls=LinuxRouter, ip=CAMPUSB_RT_LAN_IP)
        extra_nodes["routers"]["campusb_rt"] = campusb_rt
        
        # Campus-B 主机
        campusb_h1 = net.addHost("campusb_h1", ip=CAMPUSB_HOST_IP)
        extra_nodes["hosts"]["campusb_h1"] = campusb_h1
        
        # Campus-B 交换机
        campusb_sw = net.addSwitch("s_campusb", cls=OVSBridge, dpid="0000000000001002")
        extra_nodes["switches"]["s_campusb"] = campusb_sw
        
        # 链路：Campus-B 主机 → 交换机 → Campus-B 路由器
        net.addLink(campusb_h1, campusb_sw, cls=TCLink,
                    bw=100, delay="1ms")
        net.addLink(campusb_sw, campusb_rt, cls=TCLink,
                    bw=100, delay="1ms")
        
        # 链路：Campus-A r1 → WAN 路由器 → Campus-B 路由器
        net.addLink(r1, wan_rt, cls=TCLink,
                    bw=100, delay="10ms")
        net.addLink(wan_rt, campusb_rt, cls=TCLink,
                    bw=100, delay="10ms")
        
        info("[EXTENDED] 双校区模块已部署: Campus-B(10.1.0.0/16) ↔ WAN(172.16.0.0/30) ↔ Campus-A(10.0.0.0/16)\n")
    
    # ──────────────────────────────────────────────
    # 启动网络
    # ──────────────────────────────────────────────
    info("\n[EXTENDED] 启动扩展网络...\n")
    net.start()
    
    # 配置路由表
    _configure_extended_routes(r1, extra_nodes, include_vpn, include_nat, include_dual_campus)
    
    # 可选 CLI
    if with_cli:
        CLI(net)
    
    return net, r1, hosts, switches, extra_nodes


def _configure_extended_routes(r1, extra_nodes, include_vpn, include_nat, include_dual_campus):
    """配置扩展拓扑的路由表。"""
    info("\n[EXTENDED] 配置路由表...\n")
    
    # ── VPN 路由 ──
    if include_vpn:
        vpn_gw = extra_nodes["routers"]["vpn_gw"]
        home_rt = extra_nodes["routers"]["home_rt"]
        
        # VPN 网关：添加去往家庭网的路由，配置 VPN 虚拟接口
        vpn_gw.cmd("ip addr add 10.0.80.1/24 dev vpn_gw-eth0")
        vpn_gw.cmd("sysctl -w net.ipv4.ip_forward=1")
        vpn_gw.cmd("ip route add 192.168.100.0/24 via 192.168.100.1 dev vpn_gw-eth2 2>/dev/null || true")
        vpn_gw.cmd("ip route add 10.0.0.0/16 via 10.0.34.1 dev vpn_gw-eth1 2>/dev/null || true")
        vpn_gw.cmd("ip route add 0.0.0.0/0 via 10.0.34.1")
        
        # 家庭路由器：添加去往 VPN 网段的路由，启用转发
        home_rt.cmd("sysctl -w net.ipv4.ip_forward=1")
        home_rt.cmd("ip route add 10.0.0.0/16 via 10.0.80.1 dev home_rt-eth1 2>/dev/null || true")
        
        # r1：添加去往 VPN 网段的路由
        r1.cmd("ip route add 10.0.80.0/24 via 10.0.34.10")
        info("[EXTENDED] VPN 路由已配置\n")
    
    # ── NAT 路由 ──
    if include_nat:
        inet_rt = extra_nodes["routers"]["inet_rt"]
        
        inet_rt.cmd("sysctl -w net.ipv4.ip_forward=1")
        inet_rt.cmd("ip route add 10.0.0.0/16 via 10.0.34.1 dev inet_rt-eth2 2>/dev/null || true")
        
        # r1：添加去往公网的路由
        r1.cmd("ip route add 203.0.113.0/28 via 203.0.113.1 dev r1-eth8 2>/dev/null || true")
        info("[EXTENDED] NAT 路由已配置\n")
    
    # ── 双校区路由 ──
    if include_dual_campus:
        wan_rt = extra_nodes["routers"]["wan_rt"]
        campusb_rt = extra_nodes["routers"]["campusb_rt"]
        
        # WAN 路由器
        wan_rt.cmd("sysctl -w net.ipv4.ip_forward=1")
        wan_rt.cmd("ip route add 10.0.0.0/16 via 172.16.0.1")
        wan_rt.cmd("ip route add 10.1.0.0/16 via 172.16.0.2")
        
        # Campus-B 路由器
        campusb_rt.cmd("sysctl -w net.ipv4.ip_forward=1")
        campusb_rt.cmd("ip route add 0.0.0.0/0 via 172.16.0.1")
        
        # r1：添加去往 Campus-B 的路由
        r1.cmd("ip route add 10.1.0.0/16 via 172.16.0.1 dev r1-eth9 2>/dev/null || true")
        info("[EXTENDED] 双校区路由已配置\n")


def create_fresh_extended_network(access_bw=None, access_delay=None, core_bw=None,
                                  include_vpn=True, include_nat=True, include_dual_campus=True):
    """清理环境后创建全新的扩展网络。"""
    import os
    os.system("mn -c 2>/dev/null")
    return build_extended_topology(
        with_cli=False,
        access_bw=access_bw,
        access_delay=access_delay,
        core_bw=core_bw,
        include_vpn=include_vpn,
        include_nat=include_nat,
        include_dual_campus=include_dual_campus
    )
