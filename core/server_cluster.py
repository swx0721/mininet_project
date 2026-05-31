"""
core/server_cluster.py — 双服务器集群管理

负责：
  - 服务器节点定位
  - 静态入口映射
  - 服务器分组信息
"""

from core.topology import SERVER1_IP, SERVER2_IP, SERVER1_INTF, SERVER2_INTF

# 双服务器 IP 列表
SERVER_IPS = [SERVER1_IP, SERVER2_IP]

# 默认静态入口映射（无负载均衡时使用）
# 用途：Baseline 和 QoS 模型中，客户端固定绑定到某个服务器
DEFAULT_STATIC_MAPPING = {
    "finance1": SERVER1_IP,
    "finance_probe": SERVER1_IP,
    "teach1": SERVER1_IP,
    "office1": SERVER1_IP,
    "dorm1": SERVER2_IP,
    "lib1": SERVER2_IP,
}


def get_server_hosts(hosts):
    """从 hosts 字典中提取 server1 和 server2。"""
    return hosts.get("server1"), hosts.get("server2")


def get_server_label(ip):
    """返回服务器 IP 的可读标签。"""
    return "Server1" if ip == SERVER1_IP else "Server2"
