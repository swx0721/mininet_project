"""
policies/vpn.py — VPN 远程接入模块

模拟 OpenVPN / IPsec 风格的远程接入 VPN：
  - VPN 网关分配虚拟地址池 10.0.80.0/24
  - 校外主机通过 VPN 隧道获得虚拟地址后访问校园内网
  - 支持 VPN 用户身份标记（用于 ACL 联动）

设计思路（Mininet 环境下的模拟方案）：
  由于 Mininet 不支持真实 VPN 隧道（IPsec/OpenVPN），本模块采用
  "路由级 VPN 模拟"：
  1. VPN 网关双接口：校园网侧 (10.0.34.10) + VPN 虚拟网侧 (10.0.80.1)
  2. 校外主机的流量经家庭路由器转发到 VPN 网关
  3. VPN 网关执行源地址替换，将校外流量伪装为 10.0.80.0/24 段地址
  4. ACL 通过匹配源地址 10.0.80.0/24 来识别 VPN 用户
"""

from mininet.log import info


# VPN 用户身份常量
VPN_VIRTUAL_POOL = "10.0.80.0/24"
VPN_GW_CAMPUS_IP = "10.0.34.10"      # VPN 网关在校园网侧的 IP
VPN_GW_VIRTUAL_IP = "10.0.80.1"       # VPN 网关虚拟侧 IP
VPN_CLIENT_VIRTUAL_IP = "10.0.80.10"  # VPN 客户端分配到的虚拟 IP

# VPN 用户访问策略
VPN_ALLOWED_TARGETS = [
    "10.0.0.0/20",    # 宿舍区
    "10.0.16.0/20",   # 教学楼
    "10.0.32.0/23",   # 图书馆
    "10.0.34.0/24",   # 办公楼
    "10.0.60.0/28",   # Server1
    "10.0.60.16/28",  # Server2
]
VPN_DENIED_TARGETS = [
    "10.0.35.0/26",   # 财务处
    "10.0.35.64/26",  # 人事处
]

# VPN 用户允许的服务端口
VPN_ALLOWED_PORTS = [80, 21, 5201, 5202, 5203, 5204, 5205, 5206, 5207]


def setup_vpn_gateway(r1, vpn_gw):
    """
    在 VPN 网关上配置源地址伪装（SNAT），
    将来自校外家庭网络的流量伪装为 VPN 虚拟地址池的地址。

    参数:
        r1:     Campus-A 核心路由器
        vpn_gw: VPN 网关节点
    """
    info("[VPN] 配置 VPN 网关...\n")

    # 清除 VPN 网关原有 iptables 规则
    vpn_gw.cmd("iptables -t nat -F")
    vpn_gw.cmd("iptables -F FORWARD")

    # SNAT：将来自家庭网的流量源地址伪装为 VPN 虚拟 IP
    # 这模拟了 VPN 隧道解封装后的地址分配
    vpn_gw.cmd(
        "iptables -t nat -A POSTROUTING "
        "-s 192.168.100.0/24 -d 10.0.0.0/16 "
        "-j SNAT --to-source 10.0.80.10"
    )

    # 允许 VPN 用户的转发流量
    vpn_gw.cmd("iptables -A FORWARD -s 192.168.100.0/24 -j ACCEPT")
    vpn_gw.cmd("iptables -A FORWARD -d 192.168.100.0/24 -j ACCEPT")

    # 启动 IP 转发
    vpn_gw.cmd("sysctl -w net.ipv4.ip_forward=1")

    info(f"[VPN] VPN 网关已配置: SNAT 192.168.100.0/24 → {VPN_CLIENT_VIRTUAL_IP}\n")
    info(f"[VPN] VPN 用户虚拟 IP: {VPN_CLIENT_VIRTUAL_IP} (池: {VPN_VIRTUAL_POOL})\n")


def apply_vpn_routing(r1, vpn_gw):
    """配置 Campus-A 路由器与 VPN 网关之间的路由。"""
    info("[VPN] 配置 VPN 路由...\n")

    # r1 添加去往 VPN 虚拟地址池的路由
    r1.cmd(f"ip route add {VPN_VIRTUAL_POOL} via {VPN_GW_CAMPUS_IP}")
    r1.cmd("ip route add 192.168.100.0/24 via 10.0.34.10")

    info(f"[VPN] 路由已配置: r1 → {VPN_VIRTUAL_POOL} via {VPN_GW_CAMPUS_IP}\n")


def list_vpn_users():
    """返回当前 VPN 用户列表及权限信息。"""
    return {
        "vpn_user_1": {
            "virtual_ip": VPN_CLIENT_VIRTUAL_IP,
            "home_ip": "192.168.100.10",
            "role": "VPN_USER",
            "allowed_targets": VPN_ALLOWED_TARGETS,
            "denied_targets": VPN_DENIED_TARGETS,
            "allowed_ports": VPN_ALLOWED_PORTS,
        }
    }


def test_vpn_connectivity(net, r1, home_pc):
    """
    VPN 连通性测试：
    1. VPN 用户能否访问校园网内 HTTP/FTP 服务
    2. VPN 用户能否访问敏感区域（预期失败）

    返回:
        dict: 测试结果
    """
    info("\n[VPN TEST] 执行 VPN 连通性测试...\n")
    results = {}

    # 测试 1: VPN 用户访问 Server1 HTTP
    info("[VPN TEST] 测试 1: home_pc → Server1 HTTP (应成功)\n")
    out = home_pc.cmd("curl -s -o /dev/null -w '%{http_code}' --connect-timeout 5 http://10.0.60.2/")
    results["vpn_to_http"] = {"success": "200" in out, "http_code": out.strip()}

    # 测试 2: VPN 用户访问 FTP
    info("[VPN TEST] 测试 2: home_pc → Server1 FTP (应成功)\n")
    out = home_pc.cmd("curl -s -o /dev/null -w '%{http_code}' --connect-timeout 5 ftp://10.0.60.2/ 2>&1 || echo 'FTP_ERROR'")
    results["vpn_to_ftp"] = {"raw": out.strip()[:100]}

    # 测试 3: VPN 用户访问财务处 (应失败)
    info("[VPN TEST] 测试 3: home_pc → finance1 (应被拒绝)\n")
    out = home_pc.cmd("ping -c 3 -W 2 10.0.35.2 2>&1")
    packet_loss = "100% packet loss" if "100% packet loss" in out else "partial"
    results["vpn_to_finance"] = {
        "expected_denied": True,
        "actual_result": "blocked" if "100% packet loss" in out else "ALLOWED (VULNERABILITY!)",
        "packet_loss": packet_loss,
    }

    # 测试 4: VPN 用户访问人事处 (应失败)
    info("[VPN TEST] 测试 4: home_pc → hr1 (应被拒绝)\n")
    out = home_pc.cmd("ping -c 3 -W 2 10.0.35.66 2>&1")
    results["vpn_to_hr"] = {
        "expected_denied": True,
        "actual_result": "blocked" if "100% packet loss" in out else "ALLOWED (VULNERABILITY!)",
    }

    info("[VPN TEST] VPN 连通性测试完成\n")
    return results


def print_vpn_test_results(results):
    """格式化输出 VPN 测试结果。"""
    info("\n" + "=" * 60 + "\n")
    info("  VPN 功能测试结果\n")
    info("=" * 60 + "\n")

    for test, result in results.items():
        if "http_code" in result:
            info(f"  {test}: HTTP {result['http_code']}\n")
        elif "expected_denied" in result:
            status = "✓ 通过 (已阻断)" if result["actual_result"].startswith("blocked") else "✗ 失败"
            info(f"  {test}: {status}\n")
        else:
            info(f"  {test}: {result.get('raw', 'N/A')}\n")
