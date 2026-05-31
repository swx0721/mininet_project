"""
topology.py — 校园网络拓扑定义模块 [兼容性存根]

⚠ 此文件保留用于向后兼容。
   新代码请使用 core/ 子包：
     from core.topology import build_topology, create_fresh_network
     from core.router import LinuxRouter
     from core.server_cluster import get_server_hosts
"""

from core.topology import (
    build_topology, create_fresh_network,
    SUBNET_CONFIG, HOST_DEFINITIONS, UPLINK_CONFIG, ROUTER_IPS,
    DEFAULT_LINK_PARAMS, ZONE_UPLINKS, ZONE_BASELINE_BW,
    SERVER1_INTF, SERVER2_INTF, SERVER1_IP, SERVER2_IP,
)
from core.router import LinuxRouter
