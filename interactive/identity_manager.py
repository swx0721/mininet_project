"""
interactive/identity_manager.py — 身份管理系统

定义校园网用户身份组：
  HOME_USER      — 校外家庭用户（192.168.100.0/24）
  VPN_USER       — VPN 远程接入用户（10.0.80.0/24）
  STUDENT        — 学生（宿舍/教学楼/图书馆）
  STAFF          — 办公楼员工（10.0.34.0/24）
  FINANCE_ADMIN  — 财务处管理员（10.0.35.0/26）
  HR_ADMIN       — 人事处管理员（10.0.35.64/26）

提供：show_identity() / switch_identity() / enable_vpn() / disable_vpn()
"""

import os

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

    # 获取 IP
    import __main__
    net = getattr(__main__, "net", None)
    ip = "N/A"
    if net:
        host = net.get(host_name)
        if host:
            out = host.cmd("hostname -I 2>/dev/null | head -1").strip()
            ip = out if out else "N/A"

    print()
    print("=" * 40)
    print(f"  IP:         {ip}")
    print(f"  Identity:   {identity}")
    print("=" * 40)
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


def enable_vpn(host_name):
    """
    启用 VPN（模拟远程接入）。

    两层效果：
      1. 软件层：将 HOME_USER 身份升级为 VPN_USER
      2. 网络层：删除 r1 上 home_pc 的全局 DROP 规则，替换为精细化 VPN ACL
         - 允许访问校内普通区域（宿舍/教学/图书馆/办公/服务器）
         - 禁止访问敏感区域（财务处/人事处）

    用法:
        mininet> py enable_vpn("home_pc")
    """
    if host_name != "home_pc":
        print(f"[VPN] WARNING: {host_name} 不是校外主机，VPN 仅对 home_pc 有效")
    
    # 1. 软件层：更新动态身份
    set_dynamic_identity(host_name, "VPN_USER")
    
    # 2. 网络层：修改 iptables 规则（从全局隔离切换到精细化 VPN ACL）
    _vpn_iptables(host_name, enable=True)
    
    print(f"[VPN] VPN 已连接 — {host_name} 身份: HOME_USER → VPN_USER")
    print(f"[VPN] 虚拟 IP: 10.0.80.10 (池: 10.0.80.0/24)")
    print(f"[VPN] 权限: 可访问校内普通区域，仍禁止访问财务处/人事处")


def disable_vpn(host_name):
    """
    断开 VPN，恢复原始身份和全局隔离。

    用法:
        mininet> py disable_vpn("home_pc")
    """
    # 1. 软件层：清除动态身份
    clear_dynamic_identity(host_name)
    
    # 2. 网络层：恢复全局隔离
    _vpn_iptables(host_name, enable=False)
    
    identity = get_identity(host_name)
    print(f"[VPN] VPN 已断开 — {host_name} 身份恢复: {identity}")
    print(f"[VPN] 状态: 完全隔离，无法访问校园网任何主机")


def _vpn_iptables(host_name, enable):
    """
    操作 r1 上的 iptables 规则实现 VPN 开关。
    
    enable=True:  删除全局隔离规则，应用 VPN ACL
    enable=False: 删除 VPN ACL，恢复全局隔离
    """
    import __main__
    from security.acl import (remove_external_isolation, apply_vpn_acl,
                              remove_vpn_acl, apply_external_isolation)
    
    net = getattr(__main__, "net", None)
    if not net:
        print("[VPN] WARNING: 无法获取 Mininet 网络对象，iptables 规则未修改")
        return
    
    r1 = net.get("r1")
    if not r1:
        print("[VPN] WARNING: 无法获取路由器 r1，iptables 规则未修改")
        return
    
    if enable:
        remove_external_isolation(r1)  # 删除全局 DROP
        apply_vpn_acl(r1)              # 应用精细化 VPN ACL
    else:
        remove_vpn_acl(r1)             # 删除 VPN ACL
        apply_external_isolation(r1)   # 恢复全局 DROP
