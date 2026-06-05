"""
security/acl_vpn.py — 防 VPN 绕过 ACL 升级模块

升级点：
  1. 引入身份组概念：VPN_USER, STAFF, FINANCE_ADMIN
  2. ACL 决策从"仅依赖源 IP"升级为多维度匹配
  3. 防止 VPN 用户通过虚拟地址伪装绕过现有 ACL

身份组定义：
  - VPN_USER:     VPN 远程用户 (10.0.80.0/24)
  - STAFF:        办公楼普通员工 (10.0.34.0/24)  
  - FINANCE_ADMIN: 财务处管理员 (10.0.35.0/26)
  - STUDENT:      宿舍区 + 教学楼 + 图书馆

ACL 决策矩阵 (源身份 × 目标区域 × 服务类型):
  ┌──────────────────┬────────────┬──────────┬──────────┬──────────┐
  │ 源身份           │ → HTTP/FTP  │ → 教学楼  │ → 财务处  │ → 人事处  │
  ├──────────────────┼────────────┼──────────┼──────────┼──────────┤
  │ VPN_USER         │ ALLOW      │ ALLOW     │ DENY      │ DENY      │
  │ STAFF            │ ALLOW      │ ALLOW     │ ALLOW     │ ALLOW     │
  │ STUDENT          │ ALLOW      │ ALLOW     │ DENY      │ DENY      │
  │ FINANCE_ADMIN    │ ALLOW      │ ALLOW     │ ALLOW     │ ALLOW     │
  └──────────────────┴────────────┴──────────┴──────────┴──────────┘
"""

from mininet.log import info


# ==================== 身份组定义 ====================

IDENTITY_GROUPS = {
    "VPN_USER": {
        "subnets": ["10.0.80.0/24"],
        "description": "VPN 远程接入用户",
        "max_privilege": "RESTRICTED",
    },
    "STAFF": {
        "subnets": ["10.0.34.0/24"],
        "description": "办公楼普通员工",
        "max_privilege": "STANDARD",
    },
    "STUDENT": {
        "subnets": ["10.0.0.0/20", "10.0.16.0/20", "10.0.32.0/23"],
        "description": "学生用户",
        "max_privilege": "RESTRICTED",
    },
    "FINANCE_ADMIN": {
        "subnets": ["10.0.35.0/26"],
        "description": "财务处管理员",
        "max_privilege": "FINANCIAL",
    },
    "HR_ADMIN": {
        "subnets": ["10.0.35.64/26"],
        "description": "人事处管理员",
        "max_privilege": "PERSONNEL",
    },
}

# 敏感区域（需要特权的目标）
SENSITIVE_ZONES = {
    "finance": {"subnet": "10.0.35.0/26", "required_role": "FINANCIAL"},
    "hr": {"subnet": "10.0.35.64/26", "required_role": "PERSONNEL"},
}


def get_identity(src_ip):
    """根据源 IP 判断身份组。"""
    # 注意：Mininet 环境中的 IP 判断基于地址前缀匹配
    # VPN 用户的流量已经由 VPN 网关做了 SNAT，源地址变为 10.0.80.10
    if src_ip.startswith("10.0.80."):
        return "VPN_USER"
    elif src_ip.startswith("10.0.34."):
        return "STAFF"
    elif src_ip.startswith("10.0.35.") and not src_ip.startswith("10.0.35.64"):
        return "FINANCE_ADMIN"
    elif src_ip.startswith("10.0.35.64"):
        return "HR_ADMIN"
    elif (src_ip.startswith("10.0.0.") or src_ip.startswith("10.0.16.") or
          src_ip.startswith("10.0.32.")):
        return "STUDENT"
    return "UNKNOWN"


def apply_vpn_acl_policies(r1):
    """
    在核心路由器 r1 上部署防 VPN 绕过的增强 ACL 规则。

    部署策略：
      1. 先清除现有 FORWARD 链 ACL 规则（保留状态防火墙）
      2. 部署身份感知的 iptables 规则
      3. 所有拒绝事件记录到系统日志（供 SQLite 审计）

    iptables 规则顺序（优先级从高到低）：
      Chain FORWARD (policy DROP)
        ├─ ESTABLISHED,RELATED → ACCEPT          (状态防火墙)
        ├─ STAFF → finance/hr → ACCEPT           (白名单)
        ├─ FINANCE_ADMIN → any → ACCEPT          (财务管理员)
        ├─ HR_ADMIN → any → ACCEPT               (人事管理员)
        ├─ VPN_USER → finance → LOG+DROP         (VPN防绕过)
        ├─ VPN_USER → hr → LOG+DROP              (VPN防绕过)
        ├─ VPN_USER → HTTP/FTP → ACCEPT          (VPN允许基本服务)
        └─ default → DROP                        (默认拒绝)
    """
    info("[ACL-VPN] 部署防 VPN 绕过增强 ACL...\n")

    # 清除旧规则（保留默认策略）
    r1.cmd("iptables -F FORWARD")

    # Step 1: 状态防火墙（链首，优先匹配）
    r1.cmd("iptables -A FORWARD -m state --state ESTABLISHED,RELATED -j ACCEPT")

    # Step 2: 白名单——STAFF 可以访问敏感区域
    r1.cmd("iptables -A FORWARD -s 10.0.34.0/24 -d 10.0.35.0/26 -j ACCEPT")
    r1.cmd("iptables -A FORWARD -s 10.0.34.0/24 -d 10.0.35.64/26 -j ACCEPT")

    # Step 3: FINANCE_ADMIN 和 HR_ADMIN 可以访问各自敏感区
    r1.cmd("iptables -A FORWARD -s 10.0.35.0/26 -d 10.0.35.0/26 -j ACCEPT")
    r1.cmd("iptables -A FORWARD -s 10.0.35.64/26 -d 10.0.35.64/26 -j ACCEPT")

    # Step 4: VPN 用户 LOG+DROP 访问敏感区域（防 VPN 绕过）
    r1.cmd(
        'iptables -A FORWARD -s 10.0.80.0/24 -d 10.0.35.0/26 '
        '-j LOG --log-prefix "ACL_VPN_DENY:FINANCE: " --log-level 4'
    )
    r1.cmd("iptables -A FORWARD -s 10.0.80.0/24 -d 10.0.35.0/26 -j DROP")

    r1.cmd(
        'iptables -A FORWARD -s 10.0.80.0/24 -d 10.0.35.64/26 '
        '-j LOG --log-prefix "ACL_VPN_DENY:HR: " --log-level 4'
    )
    r1.cmd("iptables -A FORWARD -s 10.0.80.0/24 -d 10.0.35.64/26 -j DROP")

    # Step 5: VPN 用户允许 HTTP(80) 和 FTP(21) 和 iperf3(5201-5207)
    r1.cmd("iptables -A FORWARD -s 10.0.80.0/24 -p tcp --dport 80 -j ACCEPT")
    r1.cmd("iptables -A FORWARD -s 10.0.80.0/24 -p tcp --dport 21 -j ACCEPT")
    r1.cmd("iptables -A FORWARD -s 10.0.80.0/24 -p tcp --dport 5201:5207 -j ACCEPT")

    # Step 6: 其他区域间流量 (STUDENT → 非敏感区)
    # PSTUDENT 不能访问 financial/hr (沿用原有黑名单)
    for src in ["10.0.0.0/20", "10.0.16.0/20", "10.0.32.0/23"]:
        for dst, tag in [("10.0.35.0/26", "FINANCE"), ("10.0.35.64/26", "HR")]:
            r1.cmd(f'iptables -A FORWARD -s {src} -d {dst} '
                   f'-j LOG --log-prefix "ACL_VPN_DENY:STUDENT→{tag}: " --log-level 4')
            r1.cmd(f"iptables -A FORWARD -s {src} -d {dst} -j DROP")

    # 默认拒绝
    r1.cmd("iptables -P FORWARD DROP")

    info("[ACL-VPN] 防 VPN 绕过增强 ACL 已部署\n")
    info("[ACL-VPN]   规则数: " + r1.cmd("iptables -L FORWARD -n | wc -l").strip() + "\n")


def log_vpn_acl_event(r1, event_type, src_ip, dst_ip, details):
    """
    记录 VPN ACL 拦截事件到 SQLite 审计数据库。
    
    参数:
        r1:         路由器节点
        event_type: 事件类型
        src_ip:     源 IP
        dst_ip:     目标 IP
        details:    详情
    """
    from security.event_logger import ensure_db
    from security.audit_db import record_event

    ensure_db(r1)
    record_event(
        event_type=f"VPN_ACL_{event_type}",
        source_ip=src_ip,
        target_ip=dst_ip,
        details=details,
        severity="WARNING",
        r1=r1,
    )
    info(f"[ACL-VPN] 事件已记录: {event_type} {src_ip} → {dst_ip}: {details}\n")


def print_identity_matrix():
    """打印身份×区域的 ACL 决策矩阵。"""
    info("\n" + "=" * 70 + "\n")
    info("  身份 × 区域 ACL 决策矩阵\n")
    info("=" * 70 + "\n")
    info(f"  {'身份组':<18} {'→ HTTP/FTP':<12} {'→ 教学楼':<12} {'→ 财务处':<12} {'→ 人事处':<12}\n")
    info("  " + "-" * 66 + "\n")
    for group_name, group_info in IDENTITY_GROUPS.items():
        priv = group_info["max_privilege"]
        can_access_finance = "ALLOW" if priv in ("FINANCIAL", "STANDARD") else "DENY"
        can_access_hr = "ALLOW" if priv in ("PERSONNEL", "STANDARD") else "DENY"
        can_access_services = "ALLOW" if priv in ("VPN_USER", "RESTRICTED", "STANDARD", "FINANCIAL", "PERSONNEL") else "DENY"
        info(f"  {group_name:<18} {can_access_services:<12} {'ALLOW':<12} {can_access_finance:<12} {can_access_hr:<12}\n")
    info("=" * 70 + "\n")
