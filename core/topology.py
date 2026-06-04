"""
core/topology.py — 校园网络拓扑定义

纯拓扑搭建模块，负责：
  - 创建 Mininet 网络（宿舍/教学楼采用接入-汇聚二级交换结构）
  - 创建路由器、交换机（接入层 / 汇聚层）、主机
  - 配置链路参数与路由
  - 验证连通性

不包含任何控制逻辑（QoS / ACL / LB）。
"""

import random
import os

random.seed(42)  # 固定种子，确保实验可复现

from mininet.net import Mininet
from mininet.link import TCLink
from mininet.node import OVSBridge
from mininet.log import info
from mininet.cli import CLI

from core.router import LinuxRouter
from utils import print_separator, print_subnet_info


# ==================== 子网与链路配置 ====================

# 差异化子网划分：宿舍/教学楼 /20（约4094可用地址）满足大量终端接入；
# 图书馆 /23（约510）、办公楼 /24（约254）适配中等终端密度；
# 财务处 /26（约62）、人事处 /26（约62）限定精小可控范围。
# 服务器 /28（约14）独立划块，与业务区域在地址空间上完全隔离。
# 各子网在 10.0.0.0/16 空间内按功能分区排列，业务区（0~35）与服务器区（60+）分离。
SUBNET_CONFIG = {
    "dorm":    {"net": "10.0.0.0/20", "gw": "10.0.0.1"},
    "teach":   {"net": "10.0.16.0/20", "gw": "10.0.16.1"},
    "lib":     {"net": "10.0.32.0/23", "gw": "10.0.32.1"},
    "office":  {"net": "10.0.34.0/24", "gw": "10.0.34.1"},
    "finance": {"net": "10.0.35.0/26", "gw": "10.0.35.1"},
    "hr":      {"net": "10.0.35.64/26", "gw": "10.0.35.65"},
    "server":  {"net": "10.0.60.0/28", "gw": "10.0.60.1"},
    "server2": {"net": "10.0.60.16/28", "gw": "10.0.60.17"},
}

HOST_DEFINITIONS = [
    ("dorm1",   "10.0.0.2/20",   "dorm"),
    ("dorm2",   "10.0.0.3/20",   "dorm"),
    ("teach1",  "10.0.16.2/20",  "teach"),
    ("teach2",  "10.0.16.3/20",  "teach"),
    ("lib1",    "10.0.32.2/23",  "lib"),
    ("lib2",    "10.0.32.3/23",  "lib"),
    ("office1", "10.0.34.2/24",  "office"),
    ("office2", "10.0.34.3/24",  "office"),
    ("finance1","10.0.35.2/26",  "finance"),
    ("finance2","10.0.35.3/26",  "finance"),
    ("hr1",     "10.0.35.66/26", "hr"),
    ("hr2",     "10.0.35.67/26", "hr"),
    ("server1", "10.0.60.2/28", "server"),    # s_server1 → r1-eth5
    ("server2", "10.0.60.18/28", "server2"),  # s_server2 → r1-eth6（独立子网）
]

# 上行链路配置：各区域汇聚层交换机（或单交换机） → 核心路由器
# 宿舍区/教学楼采用接入-汇聚二级结构，汇聚交换机接核心路由器
# 其他区域单交换机直连核心路由器
# 注意：服务器双链路在 build_topology 中特殊处理（不在此列表中）
UPLINK_CONFIG = [
    ("dorm_agg", "r1-eth0", 100, "5ms"),
    ("teach_agg","r1-eth1", 100, "5ms"),
    ("lib",      "r1-eth2", 100, "5ms"),
    ("office",   "r1-eth3", 100, "5ms"),
    ("finance",  "r1-eth4", 100, "5ms"),
    ("hr",       "r1-eth7", 100, "5ms"),
]

# 接入层→汇聚层二级拓扑区域
AGGREGATION_ZONES = {"dorm", "teach"}

ROUTER_IPS = {
    "r1-eth0": "10.0.0.1/20",
    "r1-eth1": "10.0.16.1/20",
    "r1-eth2": "10.0.32.1/23",
    "r1-eth3": "10.0.34.1/24",
    "r1-eth4": "10.0.35.1/26",
    "r1-eth7": "10.0.35.65/26",    # 人事处上行
    "r1-eth5": "10.0.60.1/28",    # 服务器1 独立链路（s_server1）
    "r1-eth6": "10.0.60.17/28",   # 服务器2 独立链路（s_server2，对称）
}

DEFAULT_LINK_PARAMS = {
    "dorm":    {"bw": 100, "delay": "5ms"},
    "teach":   {"bw": 100, "delay": "5ms"},
    "lib":     {"bw": 100, "delay": "5ms"},
    "office":  {"bw": 100, "delay": "5ms"},
    "finance": {"bw": 100, "delay": "5ms"},
    "hr":      {"bw": 100, "delay": "5ms"},
    "server":  {"bw": 100, "delay": "1ms"},   # 服务器1 独立链路
    "server2": {"bw": 100, "delay": "1ms"},   # 服务器2 独立链路（对称）
}

# ==================== 全局常量 ====================

# 各区域上行链路接口（QoS 作用位置）
ZONE_UPLINKS = ["r1-eth0", "r1-eth1", "r1-eth2", "r1-eth3", "r1-eth4", "r1-eth7"]

# 服务器出口接口（负载均衡实验独立链路）
SERVER1_INTF = "r1-eth5"
SERVER2_INTF = "r1-eth6"

# 服务器 IP
SERVER1_IP = "10.0.60.2"
SERVER2_IP = "10.0.60.18"   # 独立子网，通过 s_server2 → r1-eth6

# 各区域上行链路基准带宽（用于 QoS 实验，基于 DEFAULT_LINK_PARAMS）
ZONE_BASELINE_BW = {
    "r1-eth0": 100,  # dorm
    "r1-eth1": 100,  # teach
    "r1-eth2": 100,  # lib
    "r1-eth3": 100,  # office
    "r1-eth4": 100,  # finance
    "r1-eth7": 100,  # hr
}


def build_topology(with_cli=True, access_bw=None, access_delay=None,
                   core_bw=None):
    """
    构建完整的校园网拓扑。
    
    特殊处理：server1 和 server2 分别通过独立的交换机（s_server1 和 s_server2）
    连接到核心路由器的不同上行链路（r1-eth5 和 r1-eth6），形成对称的双链路结构。

    返回:
        net:     Mininet 网络对象
        r1:      路由器节点
        hosts:   主机名 → 节点映射
        switches: 交换机名 → 节点映射
    """
    net = Mininet(link=TCLink, switch=OVSBridge, controller=None)

    # ---------- 创建路由器 ----------
    r1 = net.addHost("r1", cls=LinuxRouter)

    # ---------- 创建交换机 ----------
    switches = {}

    # 宿舍区/教学楼：3 台接入交换机 + 1 台汇聚交换机（接入-汇聚二级结构）
    for zone in ("dorm", "teach"):
        for i in range(1, 4):  # s_dorm1/2/3, s_teach1/2/3
            switches[f"{zone}{i}"] = net.addSwitch(f"s_{zone}{i}")
        switches[f"{zone}_agg"] = net.addSwitch(f"s_{zone}_agg")

    # 其他区域：单交换机直连核心路由器
    for zone in ("lib", "office", "finance", "hr"):
        switches[zone] = net.addSwitch(f"s_{zone}")

    # 服务器双交换机（对称结构）
    switches["s_server1"] = net.addSwitch("s_server1")
    switches["s_server2"] = net.addSwitch("s_server2")

    # ---------- 创建主机 ----------
    hosts = {}
    for name, ip, zone in HOST_DEFINITIONS:
        gw = SUBNET_CONFIG[zone]["gw"]
        host = net.addHost(name, ip=ip, defaultRoute=f"via {gw}")
        hosts[name] = host

    # ---------- 接入链路 ----------
    link_params = {}
    for zone, params in DEFAULT_LINK_PARAMS.items():
        link_params[zone] = {
            "bw": access_bw if access_bw is not None else params["bw"],
            "delay": access_delay if access_delay is not None else params["delay"],
        }

    for name, ip, zone in HOST_DEFINITIONS:
        params = link_params[zone]
        # server1/2 特殊处理：各自独立交换机
        if name == "server1":
            net.addLink(hosts[name], switches["s_server1"],
                        bw=params["bw"], delay=params["delay"])
        elif name == "server2":
            net.addLink(hosts[name], switches["s_server2"],
                        bw=params["bw"], delay=params["delay"])
        elif zone in AGGREGATION_ZONES:
            # 宿舍区/教学楼：终端连接第 1 台接入交换机（s_dorm1 / s_teach1）
            net.addLink(hosts[name], switches[f"{zone}1"],
                        bw=params["bw"], delay=params["delay"])
        else:
            net.addLink(hosts[name], switches[zone],
                        bw=params["bw"], delay=params["delay"])

    # ---------- 接入-汇聚链路（仅宿舍/教学楼） ----------
    # 3 台接入交换机 → 汇聚交换机，区内时延 1ms，带宽 100Mbps
    for zone in ("dorm", "teach"):
        for i in range(1, 4):
            net.addLink(switches[f"{zone}{i}"], switches[f"{zone}_agg"],
                        bw=100, delay="1ms")

    # ---------- 上行链路 ----------
    # 汇聚交换机（或单交换机）→ 核心路由器
    for zone, intf_name, bw, delay in UPLINK_CONFIG:
        effective_bw = core_bw if core_bw is not None else bw
        net.addLink(switches[zone], r1, intfName2=intf_name,
                    bw=effective_bw, delay=delay)
    
    # 服务器双链路上行（对称：同带宽同延迟）
    srv1_params = link_params["server"]
    srv2_params = link_params["server2"]
    net.addLink(switches["s_server1"], r1, intfName2="r1-eth5",
                bw=srv1_params["bw"], delay=srv1_params["delay"])
    net.addLink(switches["s_server2"], r1, intfName2="r1-eth6",
                bw=srv2_params["bw"], delay=srv2_params["delay"])

    # ---------- 启动 ----------
    net.start()

    # ---------- 配置路由器 IP ----------
    for intf, ip in ROUTER_IPS.items():
        r1.cmd(f"ifconfig {intf} {ip}")

    # ---------- 验证连通性 ----------
    info("[TOPOLOGY] 验证全网连通性...\n")
    result = net.pingAll()
    info(f"[TOPOLOGY] pingAll 结果: {result}% 丢包\n")

    print_separator("校园网络拓扑已启动")
    print_subnet_info()

    if with_cli:
        CLI(net)
        net.stop()

    return net, r1, hosts, switches


def create_fresh_network(access_bw=None, access_delay=None, core_bw=None):
    """
    创建全新 Mininet 实例，确保实验环境干净隔离。
    在调用前自动执行 mn -c + iptables flush 清理残留状态。

    返回:
        (net, r1, hosts, switches)
    """
    import os as _os
    from mininet.log import info as _info

    _info("[CLEANUP] 全局环境清理...\n")
    _os.system("mn -c 2>/dev/null")

    return build_topology(
        with_cli=False,
        access_bw=access_bw,
        access_delay=access_delay,
        core_bw=core_bw,
    )
