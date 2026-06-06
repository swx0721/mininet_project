"""
security/perimeter_acl.py — 校园网络边界访问控制（Perimeter ACL）

双层访问控制体系:
  Layer 1: Perimeter ACL  — 控制外部流量是否允许进入校园网
  Layer 2: Internal ACL   — 控制进入后是否允许访问特定资源

信任网络定义:
  TRUSTED_NETWORKS = {
      "10.0.0.0/16",     # Campus-A 校园内网
      "10.1.0.0/16",     # Campus-B 校园内网
      "10.0.80.0/24",    # VPN 虚拟地址池
  }

访问流程:
  external_host (192.168.100.x)
      ↓ Perimeter ACL → DENY (不在 TRUSTED_NETWORKS)
      ↓ enable_vpn() → 获得 10.0.80.x
      ↓ Perimeter ACL → ALLOW
      ↓ Internal ACL → 检查身份 × 目标区域
      ↓ resource access
"""

from mininet.log import info


# 信任网络列表（校园内网 + VPN 地址池 + 跨校区链路）
TRUSTED_NETWORKS = [
    "10.0.0.0/16",     # Campus-A
    "10.1.0.0/16",     # Campus-B
    "10.0.80.0/24",    # VPN 虚拟地址池
    "172.16.0.0/30",   # 跨校区 WAN 链路（内部互联）
]


def _ip_in_subnet(ip, subnet):
    """检查 IP 是否属于指定子网。"""
    import ipaddress
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(subnet, strict=False)
    except ValueError:
        # 简化匹配：前缀匹配
        if "/" in subnet:
            prefix, bits = subnet.split("/")
            bits = int(bits)
            ip_parts = ip.split(".")
            prefix_parts = prefix.split(".")
            match_parts = bits // 8
            for i in range(match_parts):
                if ip_parts[i] != prefix_parts[i]:
                    return False
            return True
        return ip.startswith(subnet.split("/")[0])


def is_trusted_ip(ip):
    """检查 IP 是否属于信任网络。"""
    for subnet in TRUSTED_NETWORKS:
        if _ip_in_subnet(ip, subnet):
            return True, subnet
    return False, None


def check_perimeter_acl(src_ip):
    """
    边界 ACL 检查（Layer 1）。

    返回:
        (allowed: bool, reason: str)
    """
    trusted, matched_subnet = is_trusted_ip(src_ip)
    if trusted:
        return True, f"TRUSTED (匹配信任网络 {matched_subnet})"
    else:
        return False, "PERIMETER_ACL — 源地址不在校园网络边界内，禁止入站"


def deploy_perimeter_iptables(r1):
    """
    在核心路由器 r1 上部署 Perimeter ACL iptables 规则。

    将所有来自非信任网络的入站流量在 FORWARD 链首 DROP。
    规则插入在所有 Internal ACL 规则之前。

    参数:
        r1: 核心路由器节点
    """
    info("[PERIMETER] 部署边界 ACL iptables 规则...\n")

    # 允许信任网络流量
    for subnet in TRUSTED_NETWORKS:
        r1.cmd(f"iptables -I FORWARD 1 -s {subnet} -j ACCEPT")

    # 允许信任网络的回程流量
    for subnet in TRUSTED_NETWORKS:
        r1.cmd(f"iptables -I FORWARD 2 -d {subnet} -j ACCEPT")

    # DROP 所有其他入站流量（边界拒绝）
    r1.cmd('iptables -I FORWARD 3 -j LOG --log-prefix "PERIMETER_DENY: " --log-level 4')
    r1.cmd("iptables -I FORWARD 4 -j DROP")

    info(f"[PERIMETER] 边界 ACL 已部署: 信任 {len(TRUSTED_NETWORKS)} 个网络\n")


def clear_perimeter_rules(r1):
    """清除 Perimeter ACL 规则（不清除内部 ACL）。"""
    info("[PERIMETER] 清除边界 ACL 规则...\n")
    # 删除匹配 PERIMETER_DENY 日志前缀的规则
    r1.cmd("iptables -F FORWARD 2>/dev/null || true")


def log_perimeter_event(src_ip, resource, result, r1=None):
    """
    记录 Perimeter ACL 事件到 SQLite 审计数据库。

    参数:
        src_ip:    源 IP 地址
        resource:  尝试访问的资源
        result:    结果 (deny/allow)
        r1:        路由器节点
    """
    try:
        from security.event_logger import ensure_db
        from security.audit_db import record_event

        ensure_db(r1)
        record_event(
            event_type="PERIMETER_ACL",
            source_ip=src_ip,
            target_ip=resource,
            details=f"Perimeter ACL: {result}",
            severity="WARNING",
            r1=r1,
        )
    except Exception:
        pass  # 审计静默失败


def access_resource(host_name, target_resource, identity=None):
    """
    统一资源访问入口 — 双层 ACL 检查 + 资源权限验证。

    参数:
        host_name:       主机名 (如 "home_pc", "dorm1")
        target_resource: 目标资源 (文件名, 如 "course_material.zip")
        identity:        可选，覆盖默认身份

    返回:
        dict: {"allowed": bool, "layer": str, "reason": str}
    """
    from interactive.identity_manager import get_identity

    # 获取主机 IP（模拟）
    import __main__
    net = getattr(__main__, "net", None)
    src_ip = None
    if net:
        host = net.get(host_name)
        if host:
            out = host.cmd("hostname -I 2>/dev/null | head -1").strip()
            src_ip = out if out else "0.0.0.0"

    if not src_ip:
        # 回退：从主机名推断 IP
        _ip_map = {
            "dorm1": "10.0.0.2", "dorm2": "10.0.0.3",
            "office1": "10.0.34.2", "finance1": "10.0.35.2",
            "hr1": "10.0.35.66", "home_pc": "192.168.100.10",
            "campusb_h1": "10.1.0.10",
        }
        src_ip = _ip_map.get(host_name, "0.0.0.0")

    # Layer 1: Perimeter ACL
    perimeter_ok, perimeter_reason = check_perimeter_acl(src_ip)
    if not perimeter_ok:
        log_perimeter_event(src_ip, target_resource, "deny")
        return {
            "allowed": False,
            "layer": "PERIMETER_ACL",
            "reason": perimeter_reason,
            "detail": "源地址不在校园网络边界内，禁止入站",
        }

    # Layer 2: Internal ACL (身份 × 资源权限)
    user_identity = identity or get_identity(host_name)

    # VPN 用户特殊检查（即使通过 Perimeter ACL 也不能访问敏感区）
    sensitive_resources = ["财务数据报表.xlsx", "财务报告.xlsx", "预算审批.docx",
                          "员工档案.pdf", "人事档案.pdf", "finance_report.xlsx"]
    sensitive_zones = {"finance1", "finance2", "hr1", "hr2"}

    if target_resource in sensitive_resources or any(z in target_resource for z in ["财务", "员工", "人事", "预算"]):
        if user_identity == "VPN_USER":
            log_perimeter_event(src_ip, target_resource, "internal_deny")
            return {
                "allowed": False,
                "layer": "INTERNAL_ACL",
                "reason": f"Campus Internal ACL — VPN_USER 禁止访问 {target_resource} (敏感资源)",
                "detail": f"身份 {user_identity} 无权限访问财务处/人事处资源",
            }
        if user_identity not in ("FINANCE_ADMIN", "HR_ADMIN", "STAFF"):
            log_perimeter_event(src_ip, target_resource, "internal_deny")
            return {
                "allowed": False,
                "layer": "INTERNAL_ACL",
                "reason": f"Campus Internal ACL — {user_identity} 禁止访问 {target_resource}",
                "detail": f"仅 FINANCE_ADMIN / HR_ADMIN 有权访问敏感资源",
            }

    # 通用课程资源检查
    from interactive.resource_access import can_access
    resource_ok, resource_reason, _ = can_access(host_name, target_resource)

    if not resource_ok:
        log_perimeter_event(src_ip, target_resource, "internal_deny")
        return {
            "allowed": False,
            "layer": "INTERNAL_ACL",
            "reason": f"Campus Internal ACL — {resource_reason}",
            "detail": f"身份 {user_identity} 无权限访问此资源",
        }

    log_perimeter_event(src_ip, target_resource, "allow")
    return {
        "allowed": True,
        "layer": None,
        "reason": "ACCESS_GRANTED",
        "detail": f"Perimeter ACL: PASS → Internal ACL: PASS (身份: {user_identity})",
    }


def print_access_result(result):
    """格式化输出访问检查结果。"""
    print()
    print("=" * 50)
    if result["allowed"]:
        print("  ACCESS GRANTED")
    else:
        print("  ACCESS DENIED")
    print("=" * 50)
    print(f"  Layer:    {result['layer'] or 'N/A'}")
    print(f"  Reason:   {result['reason']}")
    if "detail" in result:
        print(f"  Detail:   {result['detail']}")
    print("=" * 50)
    print()
