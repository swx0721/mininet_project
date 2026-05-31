"""
security.py — 安全策略模块 [兼容性存根]

⚠ 此文件保留用于向后兼容。
   新代码请使用 security/ 子包：
     from security.acl import apply_stateful_firewall, apply_acl_policies
     from security.intrusion import apply_intrusion_detection
     from security.firewall import ban_ip
     from security.audit_db import init_db, query_events
     from security.event_logger import log_acl_deny

所有功能已迁移至 security/ 目录下的独立模块。
注意：QoS 相关代码已从 security 中移除，迁移至 policies/qos.py。
"""

from security.acl import (
    apply_stateful_firewall, apply_acl_policies,
    apply_default_drop, apply_default_accept, clear_all_rules,
)
from security.intrusion import (
    apply_icmp_flood_protection, apply_syn_flood_protection,
    apply_intrusion_detection,
)
from security.firewall import ban_ip, unban_ip, is_banned, clear_all_bans
from security.audit_db import init_db, query_events, get_statistics, clear_db
from security.event_logger import (
    log_acl_deny, log_port_scan, log_flood_event, log_ban_event,
)

# QoS 已迁移到 policies/qos.py
# 为兼容保留引用
from policies.qos import apply_htb_policy as apply_qos_finance_priority
from policies.qos import clear_qos

from mininet.log import info


def apply_all_security(r1, with_qos=False, default_drop=False):
    """一键应用所有安全策略（兼容旧调用）。"""
    info("=" * 60 + "\n")
    info("  应用安全策略\n")
    info("=" * 60 + "\n")

    apply_default_accept(r1)
    apply_stateful_firewall(r1)
    apply_acl_policies(r1)
    apply_icmp_flood_protection(r1)

    if with_qos:
        from policies.qos import apply_htb_policy
        apply_htb_policy(r1)

    if default_drop:
        apply_default_drop(r1)

    info("[SECURITY] 所有安全策略已生效\n")


def cleanup_network(r1):
    """清理路由器残留状态（兼容旧调用）。"""
    info("[CLEANUP] 清理路由器残留状态...\n")
    r1.cmd("iptables -F")
    r1.cmd("iptables -t mangle -F")
    r1.cmd("iptables -t nat -F 2>/dev/null || true")
    r1.cmd("iptables -X")
    r1.cmd("iptables -P INPUT ACCEPT")
    r1.cmd("iptables -P FORWARD ACCEPT")
    r1.cmd("iptables -P OUTPUT ACCEPT")

    for dev in [f"r1-eth{i}" for i in range(7)]:
        r1.cmd(f"tc qdisc del dev {dev} root 2>/dev/null || true")

    r1.cmd("pkill -f iperf3 2>/dev/null || true")
    r1.cmd("pkill -f pyftpdlib 2>/dev/null || true")
    r1.cmd("pkill -f http.server 2>/dev/null || true")
    info("[CLEANUP] 路由器状态已清理\n")


def cleanup_all():
    """全局强制清理（兼容旧调用）。"""
    import os
    info("[CLEANUP] 全局环境清理...\n")
    os.system("mn -c 2>/dev/null")
    info("[CLEANUP] 全局清理完成\n")
