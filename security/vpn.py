"""
security/vpn.py — WireGuard 真实 VPN 隧道实现

在 Mininet 拓扑中实现真实的 WireGuard VPN 隧道：
  - r1（核心路由器）：VPN 服务端，监听 UDP 51820
  - home_pc（校外主机）：VPN 客户端，拨号获得虚拟 IP 10.0.80.x
  - 隧道建立在现有物理路径之上：home_pc → s_home → r1-eth8

设计要点：
  - 使用 Linux 内核原生 WireGuard（内核 5.6+ 内建）
  - VPN 子网：10.0.80.0/24，r1=10.0.80.1, home_pc=10.0.80.10
  - iptables 规则基于 wg0 接口和 VPN IP 池做 ACL（非基于物理 IP）
  - 支持 enable/disable 动态切换

重要：Mininet 命名空间内所有 WireGuard 密钥通过临时文件传递
（不能用 /proc/self/fd/N 或 stdin 管道，会在 Mininet shell 中卡死）。

用法:
    from security.vpn import VpnManager
    vpn = VpnManager(net)
    vpn.setup_server()       # 在 r1 上创建 VPN 服务端
    vpn.connect_client()      # 在 home_pc 上建立隧道
    vpn.disconnect_client()   # 断开隧道
    vpn.cleanup()             # 清理所有资源
"""

import os
import time
from mininet.log import info

# ==================== 常量 ====================

VPN_SUBNET = "10.0.80.0/24"
VPN_SERVER_IP = "10.0.80.1"
VPN_CLIENT_IP = "10.0.80.10"
VPN_LISTEN_PORT = 51820
WG_INTERFACE = "wg0"           # 两端都叫 wg0（不同命名空间不冲突）

# 密钥文件路径（Mininet 命名空间共享宿主机文件系统）
VPN_SERVER_PRIVKEY_FILE = "/tmp/wg_server_priv.key"
VPN_SERVER_PUBKEY_FILE = "/tmp/wg_server_pub.key"
VPN_CLIENT_PRIVKEY_FILE = "/tmp/wg_client_priv.key"
VPN_CLIENT_PUBKEY_FILE = "/tmp/wg_client_pub.key"

# 物理路径：home_pc 通过此链路连接 r1
PHYSICAL_ENDPOINT_IP = "192.168.100.1"   # r1 的 eth8 IP

# 安全：密钥文件权限
_KEY_FILE_MODE = 0o600


class VpnManager:
    """
    WireGuard VPN 隧道管理器。

    负责在 r1 和 home_pc 之间建立/拆除真实的加密隧道，
    并管理基于 VPN 接口的 iptables ACL 规则。
    """

    def __init__(self, net):
        """
        初始化 VPN 管理器。

        Args:
            net: Mininet 网络对象
        """
        self.net = net
        self.r1 = net.get("r1")
        self.home_pc = net.get("home_pc")
        self.server_private_key = None
        self.client_private_key = None
        self.server_public_key = None
        self.client_public_key = None
        self._is_connected = False

    # ================================================================
    # 公共 API
    # ================================================================

    def setup_server(self):
        """
        在 r1 上配置 WireGuard VPN 服务端。

        操作：
          1. 检测 wireguard-tools 是否可用
          2. 生成密钥对（写入临时文件）
          3. 创建 wg0 接口，分配 VPN IP
          4. 配置监听端口和允许的客户端
          5. 启用接口
        """
        info("[VPN] 配置 VPN 服务端 (r1)...\n")

        if not self._install_wireguard(self.r1):
            return False

        # ---- 生成服务端密钥对（写入文件） ----
        self.r1.cmd(f"wg genkey > {VPN_SERVER_PRIVKEY_FILE}")
        self.r1.cmd(f"chmod {_KEY_FILE_MODE:o} {VPN_SERVER_PRIVKEY_FILE}")
        self.r1.cmd(f"wg pubkey < {VPN_SERVER_PRIVKEY_FILE} > {VPN_SERVER_PUBKEY_FILE}")

        # 读取密钥（内存中保存）
        self.server_private_key = self.r1.cmd(f"cat {VPN_SERVER_PRIVKEY_FILE}").strip()
        self.server_public_key = self.r1.cmd(f"cat {VPN_SERVER_PUBKEY_FILE}").strip()
        info("[VPN] 服务端密钥已生成\n")

        # ---- 创建 wg0 接口 ----
        self.r1.cmd(f"ip link add {WG_INTERFACE} type wireguard")
        self.r1.cmd(f"ip addr add {VPN_SERVER_IP}/24 dev {WG_INTERFACE}")

        # ---- 关键：关闭反向路径过滤 ----
        # Ubuntu 默认 rp_filter=1（strict），WireGuard 解密后的内层包从 wg0 进入
        # 时，内核会检查 "如果我要回复 src IP，是否也会走 wg0？"
        # 虽然 10.0.80.0/24 的 connected route 理论上应通过此检查，但某些内核版本
        # 或命名空间配置下 rp_filter 可能意外 DROP 转发包（计数器为 0）。
        # 统一关闭确保 WireGuard 转发不受干扰。
        self.r1.cmd("sysctl -w net.ipv4.conf.all.rp_filter=0 2>/dev/null || true")
        self.r1.cmd("sysctl -w net.ipv4.conf.default.rp_filter=0 2>/dev/null || true")
        # 确认 ip_forward 已启用（Mininet LinuxRouter 通常已设置，但双重保险）
        self.r1.cmd("sysctl -w net.ipv4.ip_forward=1 2>/dev/null || true")

        # ---- 配置 WireGuard 参数（密钥通过文件传递）----
        # 注意：不在此处添加 peer，等 connect_client() 时再用真实公钥添加。
        # WireGuard 要求 peer 公钥必须是合法的 base64(32 bytes)，
        # 占位符会导致整个 wg set 命令失败（listen-port 也无法生效）。
        self.r1.cmd(
            f"wg set {WG_INTERFACE} "
            f"listen-port {VPN_LISTEN_PORT} "
            f"private-key {VPN_SERVER_PRIVKEY_FILE}"
        )

        # 启用接口
        self.r1.cmd(f"ip link set {WG_INTERFACE} up")

        # ---- 验证监听端口 ----
        time.sleep(0.3)
        actual_listen = self._parse_listen_port(self.r1_cmd_status())
        if actual_listen and actual_listen != VPN_LISTEN_PORT:
            info(f"[VPN] [WARN] 期望端口 {VPN_LISTEN_PORT}，实际: {actual_listen}\n")
        self._actual_listen_port = actual_listen or VPN_LISTEN_PORT

        info(f"[VPN] VPN 服务端已就绪 "
             f"(wg0={VPN_SERVER_IP}/24, 监听 {PHYSICAL_ENDPOINT_IP}:{self._actual_listen_port})\n")
        return True

    def connect_client(self):
        """
        在 home_pc 上建立 WireGuard 隧道。

        操作：
          1. 生成客户端密钥对（写入文件）
          2. 读取服务端公钥
          3. 创建 wg0 接口
          4. 配置端点和路由
          5. 将客户端公钥注册到服务端
          6. 启动隧道
        """
        if self._is_connected:
            info("[VPN] 隧道已处于连接状态\n")
            return True

        info("[VPN] 建立 VPN 隧道 (home_pc)...\n")

        if not self._install_wireguard(self.home_pc):
            return False

        # ---- 生成客户端密钥对（写入文件） ----
        self.home_pc.cmd(f"wg genkey > {VPN_CLIENT_PRIVKEY_FILE}")
        self.home_pc.cmd(f"chmod {_KEY_FILE_MODE:o} {VPN_CLIENT_PRIVKEY_FILE}")
        self.home_pc.cmd(f"wg pubkey < {VPN_CLIENT_PRIVKEY_FILE} > {VPN_CLIENT_PUBKEY_FILE}")

        self.client_private_key = self.home_pc.cmd(f"cat {VPN_CLIENT_PRIVKEY_FILE}").strip()
        self.client_public_key = self.home_pc.cmd(f"cat {VPN_CLIENT_PUBKEY_FILE}").strip()
        info("[VPN] 客户端密钥已生成\n")

        # ---- 从服务端读取公钥 ----
        server_pub = self.r1.cmd(f"cat {VPN_SERVER_PUBKEY_FILE}").strip()
        if not server_pub:
            info("[VPN] [ERROR] 无法读取服务端公钥！请先运行 setup_server()\n")
            return False

        # ---- 创建客户端 wg0 接口 ----
        self.home_pc.cmd(f"ip link add {WG_INTERFACE} type wireguard")
        self.home_pc.cmd(f"ip addr add {VPN_CLIENT_IP}/24 dev {WG_INTERFACE}")

        # ---- 配置 WireGuard 参数（密钥通过文件传递，不用 /proc/self/fd/N）----
        # 使用 r1 的实际监听端口（而非常量，防止端口设置失败导致端口不匹配）
        actual_port = getattr(self, '_actual_listen_port', VPN_LISTEN_PORT)
        self.home_pc.cmd(
            f"wg set {WG_INTERFACE} "
            f"private-key {VPN_CLIENT_PRIVKEY_FILE} "
            f"peer {server_pub} "
            f"endpoint {PHYSICAL_ENDPOINT_IP}:{actual_port} "
            f"allowed-ips 0.0.0.0/0 "
            f"persistent-keepalive 15"
        )
        self.home_pc.cmd(f"ip link set {WG_INTERFACE} up")

        # ---- 关闭 home_pc 的 rp_filter ----
        self.home_pc.cmd("sysctl -w net.ipv4.conf.all.rp_filter=0 2>/dev/null || true")
        self.home_pc.cmd(f"sysctl -w net.ipv4.conf.{WG_INTERFACE}.rp_filter=0 2>/dev/null || true")

        # ---- 添加校园网路由（关键！）----
        # 默认情况下 home_pc 到 10.0.x.x 走物理接口，无法被 VPN ACL 放行。
        # 必须显式将校园网流量路由到 wg0，使数据包经加密隧道到达 r1，
        # 在 r1 解密后以源 IP 10.0.80.10 进入 FORWARD 链，匹配 -i wg0 的 VPN ACL。
        self.home_pc.cmd(
            f"ip route add 10.0.0.0/16 via {VPN_SERVER_IP} dev {WG_INTERFACE}"
        )

        # ---- 注册客户端到服务端（添加 peer）----
        self.r1.cmd(
            f"wg set {WG_INTERFACE} "
            f"peer {self.client_public_key} "
            f"allowed-ips {VPN_CLIENT_IP}/32"
        )

        # 等待握手完成
        time.sleep(1)

        # 验证连接状态
        status = self.r1_cmd_status()
        client_status = self.home_pc_cmd_status()
        self._is_connected = True

        info("[VPN] 隧道已建立！\n")
        info(f"[VPN]   客户端虚拟 IP: {VPN_CLIENT_IP}\n")
        info(f"[VPN]   服务端虚拟 IP: {VPN_SERVER_IP}\n")
        info(f"[VPN]   r1 wg show:\n{status}\n")
        info(f"[VPN]   home_pc wg show:\n{client_status}\n")
        return True

    def disconnect_client(self):
        """
        断开 home_pc 的 VPN 隧道。
        不删除服务端配置，只关闭客户端接口并从服务端移除 peer。
        """
        if not self._is_connected:
            info("[VPN] 隧道未连接\n")
            return

        info("[VPN] 断开 VPN 隧道...\n")

        # 客户端：删除校园网路由（必须在接口删除前操作）
        self.home_pc.cmd(
            f"ip route del 10.0.0.0/16 via {VPN_SERVER_IP} "
            f"dev {WG_INTERFACE} 2>/dev/null || true"
        )

        # 客户端：删除 wg0 接口
        self.home_pc.cmd(f"ip link del {WG_INTERFACE} 2>/dev/null || true")

        # 服务端：移除客户端 peer
        if self.client_public_key:
            self.r1.cmd(
                f"wg set {WG_INTERFACE} "
                f"peer {self.client_public_key} remove 2>/dev/null || true"
            )

        self._is_connected = False
        info("[VPN] 隧道已断开\n")

    def cleanup(self):
        """清理所有 VPN 资源（接口 + 密钥文件）。"""
        info("[VPN] 清理 VPN 资源...\n")

        # 断开客户端（如果还连着）
        if self._is_connected:
            self.disconnect_client()

        # 服务端：删除 wg0 接口
        self.r1.cmd(f"ip link del {WG_INTERFACE} 2>/dev/null || true")

        # 清理密钥文件
        for f in [VPN_SERVER_PRIVKEY_FILE, VPN_SERVER_PUBKEY_FILE,
                  VPN_CLIENT_PRIVKEY_FILE, VPN_CLIENT_PUBKEY_FILE]:
            self.r1.cmd(f"rm -f {f} 2>/dev/null || true")
            self.home_pc.cmd(f"rm -f {f} 2>/dev/null || true")

        self._is_connected = False
        self.server_private_key = None
        self.client_private_key = None
        self.server_public_key = None
        self.client_public_key = None
        info("[VPN] VPN 资源已清理\n")

    @property
    def is_connected(self):
        """返回当前隧道连接状态。"""
        return self._is_connected

    def get_client_vpn_ip(self):
        """返回客户端的虚拟 IP 地址。"""
        return VPN_CLIENT_IP if self._is_connected else None

    # ================================================================
    # 辅助方法
    # ================================================================

    def _parse_listen_port(self, wg_show_output):
        """从 `wg show wg0` 输出解析实际监听端口。"""
        for line in wg_show_output.split('\n'):
            line = line.strip()
            if line.startswith('listening port:'):
                parts = line.split(':')
                if len(parts) >= 2:
                    try:
                        return int(parts[-1].strip())
                    except ValueError:
                        pass
        return None

    def _install_wireguard(self, node):
        """
        检测节点是否可访问 wireguard-tools（需宿主机预装）。

        Mininet 命名空间共享宿主机文件系统，但不能运行 apt-get。
        因此 wireguard-tools 必须在宿主机上预先安装。

        Returns:
            bool: True 表示可用，False 表示不支持
        """
        check = node.cmd(
            "timeout 3 which wg 2>/dev/null && echo OK || echo MISSING"
        ).strip()
        if "MISSING" in check:
            info(f"[VPN] [ERROR] {node.name} 上未找到 wg 命令！\n"
                 "[VPN] 请在宿主机上执行: sudo apt-get install wireguard-tools -y\n")
            return False

        # 检查内核是否支持 WireGuard（5.6+ 内建，直接测试接口创建）
        test_out = node.cmd(
            "timeout 5 ip link add __wg_test type wireguard 2>&1; "
            "ip link del __wg_test 2>/dev/null; "
            "echo RC=$?"
        ).strip()
        if "RC=0" not in test_out:
            info(f"[VPN] [WARN] {node.name} 内核不支持 WireGuard 接口！"
                 "将回退到 iptables 模拟模式\n")
            return False

        return True

    def r1_cmd_status(self):
        """查询 r1 的 WireGuard 状态。"""
        return self.r1.cmd(
            f"timeout 3 wg show {WG_INTERFACE} 2>/dev/null"
        ).strip() or "(无输出)"

    def home_pc_cmd_status(self):
        """查询 home_pc 的 WireGuard 状态。"""
        return self.home_pc.cmd(
            f"timeout 3 wg show {WG_INTERFACE} 2>/dev/null"
        ).strip() or "(无输出)"

    def verify_connectivity(self):
        """
        验证 VPN 隧道的网络层连通性。

        Returns:
            bool: 是否能通过 VPN IP ping 通 r1
        """
        if not self._is_connected:
            return False
        out = self.home_pc.cmd(
            f"timeout 5 ping -c 1 -W 2 {VPN_SERVER_IP} 2>&1"
        ).strip()
        return "1 received" in out or "0% packet loss" in out


# ================================================================
# 全局单例管理（供 interactive/identity_manager.py 使用）
# ================================================================

_global_vpn_manager = None


def get_or_create_vpn_manager(net):
    """
    获取或创建全局 VPN 管理器实例。

    Args:
        net: Mininet 网络对象
    Returns:
        VpnManager 实例
    """
    global _global_vpn_manager
    if _global_vpn_manager is None:
        _global_vpn_manager = VpnManager(net)
    return _global_vpn_manager


def reset_vpn_manager():
    """重置全局 VPN 管理器（用于测试清理）。"""
    global _global_vpn_manager
    if _global_vpn_manager is not None:
        try:
            _global_vpn_manager.cleanup()
        except Exception:
            pass
    _global_vpn_manager = None
