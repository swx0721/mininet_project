"""
security/acl.py — ACL 访问控制策略

实现基于部门的跨区域访问控制：
  白名单:
    - 办公楼 → 财务处（日常公务，明确允许）
    - 办公楼 → 人事处（日常公务，明确允许）

  黑名单（LOG + DROP）:
    - 宿舍区   → 财务处（学生无权限）
    - 教学楼   → 财务处（教室设备无权限）
    - 图书馆   → 财务处（公共区域无权限）
    - 宿舍区   → 人事处（学生无权限）
    - 教学楼   → 人事处（教室设备无权限）
    - 图书馆   → 人事处（公共区域无权限）

  其他跨区域访问：默认 ACCEPT（实验网络简化，仅控制核心敏感区域）

所有规则部署在核心路由器 r1 的 FORWARD 链上。
"""

from mininet.log import info


def apply_stateful_firewall(r1):
    """应用状态防火墙：允许已建立连接和关联协议回传。"""
    info("[ACL] 应用状态防火墙规则...\n")
    r1.cmd("iptables -A FORWARD -m state --state ESTABLISHED,RELATED -j ACCEPT")
    info("[ACL] 状态防火墙已启用 (ESTABLISHED,RELATED)\n")


def apply_acl_policies(r1):
    """
    应用 ACL 跨部门访问策略。

    使用 -A（append）追加规则到 FORWARD 链末尾。
    规则顺序：
      1. 状态防火墙（ESTABLISHED,RELATED）— 最先匹配
      2. 白名单（明确允许）
      3. 黑名单（LOG + DROP）
      4. 后续安全规则（ICMP/SYN Flood 防护等）— 追加在 ACL 之后

    ACL 规则应在状态防火墙规则之后添加，
    确保 ESTABLISHED 回包不被 ACL 误拦。
    """
    info("[ACL] 应用 ACL 跨部门访问策略...\n")

    # --- 白名单：明确允许的跨部门访问 ---
    info("[ACL] 配置白名单规则...\n")

    r1.cmd("iptables -A FORWARD -s 10.0.34.0/24 -d 10.0.35.0/26 -j ACCEPT")
    info("  [+] 办公楼 (10.0.34.0/24) -> 财务处 (10.0.35.0/26): 允许\n")
    r1.cmd("iptables -A FORWARD -s 10.0.34.0/24 -d 10.0.35.64/26 -j ACCEPT")
    info("  [+] 办公楼 (10.0.34.0/24) -> 人事处 (10.0.35.64/26): 允许\n")

    # --- 黑名单：记录日志并阻止非法访问 ---
    info("[ACL] 配置黑名单规则（带日志审计）...\n")

    # 财务处黑名单
    acl_rules = [
        ("10.0.0.0/20", "10.0.35.0/26", "DORM2FIN",  "宿舍区→财务处"),
        ("10.0.16.0/20", "10.0.35.0/26", "TEACH2FIN", "教学楼→财务处"),
        ("10.0.32.0/23", "10.0.35.0/26", "LIB2FIN",   "图书馆→财务处"),
        ("10.0.0.0/20", "10.0.35.64/26", "DORM2HR",  "宿舍区→人事处"),
        ("10.0.16.0/20", "10.0.35.64/26", "TEACH2HR", "教学楼→人事处"),
        ("10.0.32.0/23", "10.0.35.64/26", "LIB2HR",   "图书馆→人事处"),
    ]

    for src, dst, tag, desc in acl_rules:
        r1.cmd(f'iptables -A FORWARD -s {src} -d {dst} -j LOG '
               f'--log-prefix "ACL_DENY:{tag}: " --log-level 4')
        r1.cmd(f"iptables -A FORWARD -s {src} -d {dst} -j DROP")
        info(f"  [-] {desc}: 阻止+日志\n")

    info("[ACL] ACL 规则已全部生效\n")

    # --- 放通服务器区流量（所有区域均可访问 server1/server2）---
    info("[ACL] 放通服务器区访问...\n")
    # server1: 10.0.60.0/28, server2: 10.0.60.16/28
    r1.cmd("iptables -A FORWARD -d 10.0.60.0/28 -j ACCEPT")
    r1.cmd("iptables -A FORWARD -d 10.0.60.16/28 -j ACCEPT")
    info("  [+] 所有区域 → 服务器区 (10.0.60.0/25): 允许\n")


def apply_default_drop(r1):
    """设置默认 FORWARD 策略为 DROP（严格模式）。"""
    info("[ACL] 设置默认 FORWARD 策略为 DROP...\n")
    r1.cmd("iptables -P FORWARD DROP")
    info("[ACL] 默认丢弃策略已生效\n")


def apply_external_isolation(r1):
    """
    校外主机 home_pc (192.168.100.10) 默认完全隔离。
    
    VPN 未开启时，home_pc 的所有流量在 FORWARD 链被 DROP。
    此规则插入 ESTABLISHED 规则之后（位置 2），优先于后续所有 ACCEPT 规则。
    
    VPN 开启后由 enable_vpn() 删除此规则，替换为精细化的 ACL。
    """
    info("[ACL] 应用校外主机默认隔离规则...\n")
    
    # 先删除已存在的同类规则（避免重复）
    r1.cmd("iptables -D FORWARD -s 192.168.100.10 -j DROP 2>/dev/null || true")
    
    # 插入到位置 2（在 ESTABLISHED 规则之后）
    r1.cmd("iptables -I FORWARD 2 -s 192.168.100.10 -j DROP")
    
    info("  [-] home_pc (192.168.100.10): 默认完全隔离（需 VPN 接入）\n")


def remove_external_isolation(r1):
    """删除 home_pc 的全局隔离规则（VPN 开启时调用）。"""
    r1.cmd("iptables -D FORWARD -s 192.168.100.10 -j DROP 2>/dev/null || true")


def apply_vpn_acl(r1):
    """
    VPN 用户 (home_pc 192.168.100.10) 的精细化 ACL。
    
    VPN 开启后调用，替换全局隔离规则：
      - 允许访问校内普通区域（宿舍/教学/图书馆/办公/服务器）
      - 禁止访问敏感区域（财务处 10.0.35.0/26、人事处 10.0.35.64/26）
    """
    info("[VPN] 应用 VPN 用户 ACL 规则...\n")
    # 黑名单：VPN 用户禁止访问敏感区域
    r1.cmd('iptables -A FORWARD -s 192.168.100.10 -d 10.0.35.0/26 '
           '-j LOG --log-prefix "ACL_VPN_DENY:FIN: " --log-level 4')
    r1.cmd("iptables -A FORWARD -s 192.168.100.10 -d 10.0.35.0/26 -j DROP")
    r1.cmd('iptables -A FORWARD -s 192.168.100.10 -d 10.0.35.64/26 '
           '-j LOG --log-prefix "ACL_VPN_DENY:HR: " --log-level 4')
    r1.cmd("iptables -A FORWARD -s 192.168.100.10 -d 10.0.35.64/26 -j DROP")
    info("  [-] VPN_USER: 禁止访问财务处/人事处\n")
    # 其他区域 ACCEPT：追加在 VPN 黑名单之后，不影响黑名单优先匹配
    r1.cmd("iptables -A FORWARD -s 192.168.100.10 -j ACCEPT")
    info("  [+] VPN_USER: 允许访问校内普通区域（宿舍/教学/图书馆/办公/服务器）\n")


def remove_vpn_acl(r1):
    """删除 VPN 用户的精细化 ACL 规则（VPN 断开时调用）。"""
    r1.cmd("iptables -D FORWARD -s 192.168.100.10 -d 10.0.35.0/26 -j LOG "
           '--log-prefix "ACL_VPN_DENY:FIN: " --log-level 4 2>/dev/null || true')
    r1.cmd("iptables -D FORWARD -s 192.168.100.10 -d 10.0.35.0/26 -j DROP 2>/dev/null || true")
    r1.cmd("iptables -D FORWARD -s 192.168.100.10 -d 10.0.35.64/26 -j LOG "
           '--log-prefix "ACL_VPN_DENY:HR: " --log-level 4 2>/dev/null || true')
    r1.cmd("iptables -D FORWARD -s 192.168.100.10 -d 10.0.35.64/26 -j DROP 2>/dev/null || true")
    r1.cmd("iptables -D FORWARD -s 192.168.100.10 -j ACCEPT 2>/dev/null || true")


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
