"""
policies/load_balance.py — 负载均衡调度器

实现请求分发策略：
  - "static":       静态入口绑定（Baseline）
  - "round_robin":  轮询调度
  - "random":       随机选择（用于诊断：区分 RR 实现问题 vs 切换开销问题）
  - 可扩展: 加权轮询、最少连接等

线程安全，支持实验并发请求。
"""

import threading
import random as _random
from core.server_cluster import SERVER1_IP, SERVER2_IP, DEFAULT_STATIC_MAPPING

SERVERS = [SERVER1_IP, SERVER2_IP]


class LoadBalancer:
    """
    请求调度器 — 控制客户端请求分发至哪个服务入口。

    用法:
        lb = LoadBalancer(algorithm="round_robin")
        target = lb.get_server("dorm1")
    """

    def __init__(self, algorithm="static", static_mapping=None):
        """
        参数:
            algorithm:      "static" | "round_robin" | "random"
            static_mapping: 静态映射字典（仅 algorithm="static" 时使用）
        """
        self.algorithm = algorithm
        self.static_mapping = static_mapping or DEFAULT_STATIC_MAPPING
        self.rr_index = 0
        self.lock = threading.Lock()

    def get_server(self, client_name):
        """
        根据调度算法为请求选择目标服务器 IP。

        返回:
            server_ip: 目标服务入口 IP 地址
        """
        if self.algorithm == "static":
            return self.static_mapping.get(client_name, SERVER1_IP)

        elif self.algorithm == "round_robin":
            with self.lock:
                target = SERVERS[self.rr_index % len(SERVERS)]
                self.rr_index += 1
                return target

        elif self.algorithm == "random":
            # 50% 随机选择，无状态，天然线程安全
            return _random.choice(SERVERS)

        else:
            return SERVER1_IP

    def reset(self):
        """重置调度器状态。"""
        with self.lock:
            self.rr_index = 0

    def get_stats(self):
        """返回当前调度统计。"""
        with self.lock:
            return {
                "algorithm": self.algorithm,
                "total_requests": self.rr_index,
            }
