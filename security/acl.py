"""
security/acl.py — ACL 访问控制策略

实现基于部门的跨区域访问控制：
  白名单:
    - 办公楼 → 人事处（日常公务）
    - 办公楼 → 财务处（日常公务）

  黑名单（LOG + DROP）:
    - 宿舍区 → 财务处
    - 教学楼 → 财务处
    - 宿舍区 → 人事处
    - 教学楼 → 人事处

所有规则部署在核心路由器 r1 的 FORWARD 链上。
"""

from mininet.log import info
from security.event_logger import log_acl_deny


def apply_stateful_firewall(r1):
    """应用状态防火墙：允许已建立连接和关联协议回传。"""
    info("[ACL] 应用状态防火墙规则...\n")
    r1.cmd("iptables -A FORWARD -m state --state ESTABLISHED,RELATED -j ACCEPT")
    info("[ACL] 状态防火墙已启用 (ESTABLISHED,RELATED)\n")


def apply_acl_policies(r1):
    """
    应用 ACL 跨部门访问策略。

    注意：ACL 规则应在状态防火墙规则之后添加。
    """
    info("[ACL] 应用 ACL 跨部门访问策略...\n")

    # --- 白名单 ---
    info("[ACL] 配置白名单...\n")

    r1.cmd("iptables -A FORWARD -s 10.0.4.0/24 -d 10.0.6.0/24 -j ACCEPT")
    info("  [+] 办公楼 (10.0.4.0/24) -> 人事处 (10.0.6.0/24): 允许\n")

    r1.cmd("iptables -A FORWARD -s 10.0.4.0/24 -d 10.0.5.0/24 -j ACCEPT")
    info("  [+] 办公楼 (10.0.4.0/24) -> 财务处 (10.0.5.0/24): 允许\n")

    # --- 黑名单（LOG + DROP）---
    info("[ACL] 配置黑名单规则（带日志审计）...\n")

    acl_rules = [
        ("10.0.1.0/24", "10.0.5.0/24", "DORM2FIN", "宿舍区→财务处"),
        ("10.0.2.0/24", "10.0.5.0/24", "TEACH2FIN", "教学楼→财务处"),
        ("10.0.1.0/24", "10.0.6.0/24", "DORM2HR", "宿舍区→人事处"),
        ("10.0.2.0/24", "10.0.6.0/24", "TEACH2HR", "教学楼→人事处"),
    ]

    for src, dst, tag, desc in acl_rules:
        r1.cmd(f'iptables -A FORWARD -s {src} -d {dst} -j LOG '
               f'--log-prefix "ACL_DENY:{tag}: " --log-level 4')
        r1.cmd(f"iptables -A FORWARD -s {src} -d {dst} -j DROP")
        info(f"  [-] {desc}: 阻止+日志\n")
        # 记录到 SQLite 审计中心
        log_acl_deny(src, dst, tag, r1)

    info("[ACL] ACL 规则已全部生效\n")


def apply_default_drop(r1):
    """设置默认 FORWARD 策略为 DROP（严格模式）。"""
    info("[ACL] 设置默认 FORWARD 策略为 DROP...\n")
    r1.cmd("iptables -P FORWARD DROP")
    info("[ACL] 默认丢弃策略已生效\n")


def apply_default_accept(r1):
    """设置默认 FORWARD 策略为 ACCEPT（宽松模式）。"""
    r1.cmd("iptables -P FORWARD ACCEPT")


def clear_all_rules(r1):
    """清除所有 iptables 规则。"""
    info("[ACL] 清除所有 iptables 规则...\n")
    r1.cmd("iptables -F")
    r1.cmd("iptables -X")
    r1.cmd("iptables -P FORWARD ACCEPT")
    r1.cmd("iptables -P INPUT ACCEPT")
    r1.cmd("iptables -P OUTPUT ACCEPT")
    info("[ACL] 所有 iptables 规则已清除\n")
