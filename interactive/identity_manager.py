"""
interactive/identity_manager.py — 身份管理系统

定义校园网用户身份组：
  HOME_USER      — 校外家庭用户（192.168.100.0/24）
  VPN_USER       — VPN 远程接入用户（10.0.80.0/24，真实 WireGuard 隧道）
  STUDENT        — 学生（宿舍/教学楼/图书馆）
  STAFF          — 办公楼员工（10.0.34.0/24）
  FINANCE_ADMIN  — 财务处管理员（10.0.35.0/26）
  HR_ADMIN       — 人事处管理员（10.0.35.64/26）

提供：show_identity() / switch_identity() / enable_vpn() / disable_vpn()

VPN 实现模式：
  - 真实模式（默认）：通过 security/vpn.py 的 VpnManager 建立 WireGuard 隧道，
    home_pc 获得真实虚拟 IP 10.0.80.10，iptables 基于 wg0 接口做 ACL
  - 兼容模式：回退到旧版 iptables 模拟方式（内核不支持 WireGuard 时自动回退）
"""

import os
from mininet.log import info as _info

# 预定义身份映射
IDENTITY_MAP = {
    "dorm1":     "STUDENT",
    "dorm2":     "STUDENT",
    "teach1":    "STUDENT",
    "teach2":    "STUDENT",
    "lib1":      "STUDENT",
    "lib2":      "STUDENT",
    "office1":   "STAFF",
    "office2":   "STAFF",
    "finance1":  "FINANCE_ADMIN",
    "finance2":  "FINANCE_ADMIN",
    "hr1":       "HR_ADMIN",
    "hr2":       "HR_ADMIN",
    "home_pc":   "HOME_USER",
    "campusb_h1": "STUDENT",
}

# 动态身份覆盖（用于 VPN 切换等场景）
_dynamic_identities = {}


def set_dynamic_identity(host_name, identity):
    """动态设置主机身份（运行时覆盖默认身份）。"""
    _dynamic_identities[host_name] = identity


def clear_dynamic_identity(host_name):
    """清除动态身份，恢复默认。"""
    _dynamic_identities.pop(host_name, None)


def get_identity(host_name):
    """
    获取主机的当前身份。
    优先级：动态身份 > 默认身份映射。
    """
    if host_name in _dynamic_identities:
        return _dynamic_identities[host_name]
    return IDENTITY_MAP.get(host_name, "UNKNOWN")


def show_identity(host_name):
    """
    显示主机身份信息。

    用法:
        mininet> py show_identity("home_pc")
        mininet> py show_identity("finance1")
    """
    identity = get_identity(host_name)

    # 获取 IP（包括虚拟 IP）
    from interactive import get_net
    net = get_net()
    ip = "N/A"
    vpn_ip = "N/A"
    if net:
        host = net.get(host_name)
        if host:
            out = host.cmd("hostname -I 2>/dev/null").strip()
            ips = out.split()
            ip = ips[0] if ips else "N/A"
            # 检查是否有 VPN 虚拟 IP (wg0 接口的 IP)
            vpn_out = host.cmd(
                "ip -4 addr show wg0 2>/dev/null "
                "| grep inet | awk '{print $2}' | cut -d/ -f1"
            ).strip()
            vpn_ip = vpn_out if vpn_out and vpn_out != "N/A" else "(未连接)"

    print()
    print("=" * 45)
    print(f"  Host:       {host_name}")
    print(f"  Physical IP:{ip}")
    print(f"  VPN IP:     {vpn_ip}")
    print(f"  Identity:   {identity}")
    # 显示隧道状态
    if host_name == "home_pc":
        from security.vpn import get_or_create_vpn_manager, reset_vpn_manager
        try:
            vpn = get_or_create_vpn_manager(net) if net else None
            if vpn and vpn.is_connected:
                status = vpn.home_pc_cmd_status()
                print(f"  Tunnel:     ACTIVE (WireGuard)")
                if status:
                    for line in status.split('\n')[:5]:
                        print(f"               {line}")
            else:
                print(f"  Tunnel:     INACTIVE")
        except Exception:
            print(f"  Tunnel:     N/A")
    print("=" * 45)
    print()
    return identity


def switch_identity(host_name, new_identity):
    """
    切换主机身份（用于演示不同身份下的访问控制差异）。

    用法:
        mininet> py switch_identity("home_pc", "STAFF")
    """
    valid = {"HOME_USER", "VPN_USER", "STUDENT", "STAFF", "FINANCE_ADMIN", "HR_ADMIN"}
    if new_identity not in valid:
        print(f"[IDENTITY] ERROR: 无效身份 {new_identity}, 有效值: {valid}")
        return

    set_dynamic_identity(host_name, new_identity)
    print(f"[IDENTITY] {host_name} 身份已切换: → {new_identity}")


# ================================================================
# VPN 开关（真实 WireGuard 隧道 + iptables ACL）
# ================================================================

_use_real_vpn = None  # None=未检测, True=使用真实VPN, False=回退模拟


def _detect_wireguard_support():
    """
    检测当前环境是否支持 WireGuard。

    Returns:
        bool: 是否支持
    """
    global _use_real_vpn
    from interactive import get_net
    net = get_net()
    if not net:
        _use_real_vpn = False
        return False

    r1 = net.get("r1")
    if not r1:
        _use_real_vpn = False
        return False

    # 尝试创建 wireguard 类型接口来检测支持（加 timeout 防卡死）
    out = r1.cmd(
        "timeout 5 ip link add __wg_test type wireguard 2>&1; "
        "ip link del __wg_test 2>/dev/null; "
        "echo RC=$?"
    ).strip()
    supported = ("RC=0" in out)
    _use_real_vpn = supported
    if not supported:
        print("[VPN] [FALLBACK] 内核不支持 WireGuard，将使用 iptables 模拟模式")
    return supported


def enable_vpn(host_name):
    """
    启用 VPN（真实 WireGuard 隔道）。

    两层效果：
      1. 隧道层：在 r1 和 home_pc 之间建立 WireGuard 加密隧道
         home_pc 获得真实虚拟 IP 10.0.80.10
      2. 网络层：删除物理链路隔离规则，替换为基于 wg0 接口的精细化 ACL
         - 从 wg0 接口进入的流量 → 允许普通区域，禁止敏感区域

    用法:
        mininet> py enable_vpn("home_pc")
    """
    if host_name != "home_pc":
        print(f'[VPN] WARNING: {host_name} 不是校外主机，VPN 仅对 home_pc 有效')
        return

    from interactive import get_net
    net = get_net()
    if not net:
        print("[VPN] ERROR: Mininet 网络不可用")
        return

    r1 = net.get("r1")

    # ---- 检测并选择 VPN 模式 ----
    if _use_real_vpn is None:
        _detect_wireguard_support()

    # ---- 1. 软件层：更新动态身份 ----
    set_dynamic_identity(host_name, "VPN_USER")

    # ---- 2. 隧道层 / 网络层 ----
    if _use_real_vpn:
        _enable_real_vpn(net, r1, host_name)
    else:
        _enable_simulated_vpn(r1, host_name)


def _enable_real_vpn(net, r1, host_name):
    """真实 WireGuard 隧道模式。"""
    from security.vpn import get_or_create_vpn_manager
    from security.acl import apply_vpn_acl_real

    print("[VPN] 使用真实 WireGuard 隧道模式...")

    # 获取或创建 VPN 管理器
    vpn = get_or_create_vpn_manager(net)

    # 如果服务端未初始化，先初始化
    server_up = vpn.r1_cmd_status()
    if not server_up or "interface" not in server_up.lower():
        vpn.setup_server()

    # 建立客户端连接（含路由设置）
    vpn.connect_client()

    # 验证连通性
    if vpn.verify_connectivity():
        print("[VPN] ✓ 隧道连通性验证通过")
    else:
        print("[VPN] ⚠ 隧道已建立但 ping 验证超时（可能需要更长时间握手）")

    # ---- 3. 更新 iptables 规则 ----
    # 注意：不删除外部隔离规则（-s 192.168.100.10 -j DROP）
    # 外部隔离作为安全兜底：即使 home_pc 流量意外走物理路径，也会被 DROP
    # WireGuard 加密隧道的流量从 wg0 接口进入，源 IP 为 10.0.80.10，
    # 不匹配外部隔离规则的 -s 192.168.100.10，因此不受影响
    apply_vpn_acl_real(r1)

    vpn_ip = vpn.get_client_vpn_ip()
    print(f"[VPN] VPN 已连接 — {host_name} 身份: HOME_USER → VPN_USER")
    print(f"[VPN] 虚拟 IP: {vpn_ip} (WireGuard 隧道, 真实分配)")
    print(f"[VPN] 权限: 通过 wg0 接口访问校内网")
    print(f"[VPN]       可访问: 宿舍/教学/图书馆/办公/服务器")
    print(f"[VPN]       禁止: 财务处(10.0.35.0/26)/人事处(10.0.35.64/26)")


def _enable_simulated_vpn(r1, host_name):
    """回退到 iptables 模拟模式（内核不支持 WireGuard 时）。"""
    from security.acl import (
        remove_external_isolation, apply_vpn_acl,
    )

    print("[VPN] [FALLBACK] 内核不支持 WireGuard，使用 iptables 模拟模式")

    remove_external_isolation(r1)
    apply_vpn_acl(r1)

    print(f"[VPN] VPN 已连接（模拟模式）— {host_name}: HOME_USER → VPN_USER")
    print(f"[VPN] ⚠ 注意：此模式无加密隧道，仅模拟 ACL 行为")


def disable_vpn(host_name):
    """
    断开 VPN，恢复原始身份和全局隔离。

    用法:
        mininet> py disable_vpn("home_pc")
    """
    # ---- 1. 软件层：清除动态身份 ----
    clear_dynamic_identity(host_name)

    # ---- 2. 隧道层 / 网络层 ----
    if _use_real_vpn:
        _disable_real_vpn(host_name)
    else:
        _disable_simulated_vpn(host_name)

    identity = get_identity(host_name)
    print(f"[VPN] VPN 已断开 — {host_name} 身份恢复: {identity}")
    print(f"[VPN] 状态: 物理链路已封锁，无法访问校园网任何主机")


def _disable_real_vpn(host_name):
    """断开真实 WireGuard 隧道。"""
    from interactive import get_net
    net = get_net()
    if not net:
        return

    from security.vpn import get_or_create_vpn_manager
    from security.acl import remove_vpn_acl, remove_vpn_acl_real

    r1 = net.get("r1")
    vpn = get_or_create_vpn_manager(net)

    # 断开客户端隧道（含路由删除）
    vpn.disconnect_client()

    # 清理 VPN ACL 规则（外部隔离未被删除，无需重新添加）
    remove_vpn_acl(r1)
    remove_vpn_acl_real(r1)


def _disable_simulated_vpn(host_name):
    """断开模拟 VPN。"""
    from interactive import get_net
    from security.acl import remove_vpn_acl, apply_external_isolation

    net = get_net()
    r1 = net.get("r1") if net else None
    if r1:
        remove_vpn_acl(r1)
        apply_external_isolation(r1)
