"""
core/router.py — LinuxRouter 封装

提供启用 IP 转发的路由器节点类。
"""

from mininet.node import Node


class LinuxRouter(Node):
    """
    支持 IP 转发的 Linux 路由器节点。
    启动时自动启用 net.ipv4.ip_forward，
    终止时恢复默认值。
    """

    def config(self, **params):
        super(LinuxRouter, self).config(**params)
        self.cmd("sysctl -w net.ipv4.ip_forward=1")

    def terminate(self):
        self.cmd("sysctl -w net.ipv4.ip_forward=0")
        super(LinuxRouter, self).terminate()
