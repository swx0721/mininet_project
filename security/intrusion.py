"""
security/intrusion.py — 入侵检测模块

实现:
  1. 端口扫描检测：监控单个源 IP 对目标 IP 的端口访问数量，
     当在时间窗口内访问端口数超过阈值时判定为端口扫描。
  2. ICMP Flood 防护：限制 ping 速率 1/s，burst 5
  3. TCP SYN Flood 防护：限制 SYN 包速率

所有检测结果通过 event_logger 记录到 SQLite 审计中心。
"""

import time
from mininet.log import info
from security.event_logger import log_port_scan, log_flood_event


# ==================== 端口扫描检测 ====================

# { (src_ip, dst_ip): [(port, timestamp), ...] }
_scan_tracker = {}

SCAN_WINDOW = 10       # 时间窗口（秒）
SCAN_PORT_THRESHOLD = 20  # 端口数阈值


def detect_port_scan(src_ip, dst_ip, port, r1=None):
    """
    检测单个源 IP 是否在短时间内对目标 IP 进行了端口扫描。

    每当有新的连接尝试时调用此函数。
    如果判定为端口扫描：
      - 记录到 SQLite 审计中心
      - 触发自动封禁（调用 firewall 模块）

    返回:
        True 如果检测到扫描行为，否则 False
    """
    key = (src_ip, dst_ip)
    now = time.time()

    if key not in _scan_tracker:
        _scan_tracker[key] = []

    # 清理过期记录
    _scan_tracker[key] = [
        (p, t) for p, t in _scan_tracker[key]
        if now - t < SCAN_WINDOW
    ]

    _scan_tracker[key].append((port, now))

    if len(_scan_tracker[key]) >= SCAN_PORT_THRESHOLD:
        info(f"[INTRUSION] ⚠ 端口扫描检测: {src_ip} → {dst_ip}, "
             f"{len(_scan_tracker[key])} 端口 / {SCAN_WINDOW}s\n")

        log_port_scan(src_ip, dst_ip, len(_scan_tracker[key]), r1)

        # 触发自动封禁
        from security.firewall import ban_ip
        ban_ip(src_ip, reason="端口扫描", r1=r1)

        _scan_tracker[key] = []  # 重置计数
        return True

    return False


def reset_scan_tracker():
    """重置扫描检测状态。"""
    global _scan_tracker
    _scan_tracker = {}


# ==================== ICMP Flood 防护 ====================

def apply_icmp_flood_protection(r1):
    """
    ICMP Flood 防护。
    限制 ICMP echo-request 速率 1/s，burst 5。

    设计要点（2026-06-07 修订版）：
      1. 使用自定义子链 ICMP_LIMIT，不在主链中用 -j ACCEPT 终止处理，
         避免绕过后续 ACL 黑名单规则。
      2. 限速内的包通过 RETURN 回到 FORWARD 主链，继续匹配 ACL；
         超额的包在子链中被 DROP。
      3. ICMP 子链跳转插入 FORWARD 位置 1（ESTABLISHED 之前），
         防止 conntrack ESTABLISHED 绕过 Flood 防护。

    修复历史：
      - 2026-06-07 (初版): 直接 -I FORWARD 1 -j ACCEPT，
        导致 ACL 黑名单被 bypass（dorm→finance ICMP 可达）。
      - 2026-06-07 (修订版): 改用子链 + RETURN，ACL 优先匹配。
    """
    info("[INTRUSION] 应用 ICMP Flood 防护...\n")

    # 创建自定义 ICMP 限速子链
    r1.cmd("iptables -N ICMP_LIMIT 2>/dev/null || iptables -F ICMP_LIMIT")
    # 限速内 RETURN（回到 FORWARD 主链继续匹配 ACL）
    r1.cmd("iptables -A ICMP_LIMIT -m limit --limit 1/s --limit-burst 5 "
           "-j RETURN")
    # 超额 DROP
    r1.cmd("iptables -A ICMP_LIMIT -j DROP")

    # FORWARD 链位置 1：所有 ICMP echo-request 跳转子链（在 ESTABLISHED 之前）
    r1.cmd("iptables -I FORWARD 1 -p icmp --icmp-type echo-request "
           "-j ICMP_LIMIT")

    info("[INTRUSION] ICMP 限速已启用 (1/s, burst=5, 子链 ICMP_LIMIT,\n"
         "          FORWARD pos=1 → 限速内 RETURN → ACL 继续匹配)\n")


# ==================== TCP SYN Flood 防护 ====================

def apply_syn_flood_protection(r1):
    """
    TCP SYN Flood 防护。
    限制 SYN 包速率 50/s，burst 100，超出部分 LOG + DROP。

    设计要点（2026-06-07 修订版）：
      1. 使用自定义子链 SYN_LIMIT，不在主链中用 -j ACCEPT 终止处理，
         避免绕过后续 ACL 黑名单规则。
      2. 限速内的包通过 RETURN 回到 FORWARD 主链，继续匹配 ACL；
         超额的包在子链中被 LOG + DROP。
      3. SYN 子链跳转插入 FORWARD 位置 4（ESTABLISHED 之后），
         SYN 包不会被 ESTABLISHED 规则匹配（SYN = NEW）。

    修复历史：
      - 2026-06-07 (初版): 直接 -j ACCEPT，导致 ACL 黑名单被 bypass。
      - 2026-06-07 (修订版): 改用子链 + RETURN，ACL 优先匹配。
    """
    info("[INTRUSION] 应用 TCP SYN Flood 防护...\n")

    # 创建自定义 SYN 限速子链
    r1.cmd("iptables -N SYN_LIMIT 2>/dev/null || iptables -F SYN_LIMIT")
    # 限速内 RETURN（回到 FORWARD 主链继续匹配 ACL）
    r1.cmd("iptables -A SYN_LIMIT -m limit --limit 50/s --limit-burst 100 "
           "-j RETURN")
    # 超额 LOG + DROP
    r1.cmd('iptables -A SYN_LIMIT -j LOG '
           '--log-prefix "SYN_FLOOD: " --log-level 4')
    r1.cmd("iptables -A SYN_LIMIT -j DROP")

    # FORWARD 链位置 4：所有 TCP SYN 跳转子链（在 ESTABLISHED 之后）
    r1.cmd("iptables -I FORWARD 4 -p tcp --syn -j SYN_LIMIT")

    info("[INTRUSION] TCP SYN Flood 防护已启用 (50/s, burst=100,\n"
         "          子链 SYN_LIMIT, FORWARD pos=4 → 限速内 RETURN → ACL 继续匹配)\n")


# ==================== 一键应用 ====================

def apply_intrusion_detection(r1):
    """
    一键应用所有入侵检测和 Flood 防护。

    参数:
        r1: 路由器节点
    """
    info("=" * 60 + "\n")
    info("  部署入侵检测系统 (IDS)\n")
    info("=" * 60 + "\n")

    apply_icmp_flood_protection(r1)
    apply_syn_flood_protection(r1)

    info("[INTRUSION] 入侵检测系统已全部部署\n")


def clear_intrusion_rules(r1):
    """清除所有入侵检测相关 iptables 规则。"""
    info("[INTRUSION] 清除入侵检测规则...\n")
    # 删除子链 FORWARD 中的跳转规则
    r1.cmd("iptables -D FORWARD -p icmp --icmp-type echo-request "
           "-j ICMP_LIMIT 2>/dev/null || true")
    r1.cmd("iptables -D FORWARD -p tcp --syn "
           "-j SYN_LIMIT 2>/dev/null || true")
    # 清空并删除自定义子链
    r1.cmd("iptables -F ICMP_LIMIT 2>/dev/null || true")
    r1.cmd("iptables -X ICMP_LIMIT 2>/dev/null || true")
    r1.cmd("iptables -F SYN_LIMIT 2>/dev/null || true")
    r1.cmd("iptables -X SYN_LIMIT 2>/dev/null || true")
    reset_scan_tracker()
    info("[INTRUSION] 入侵检测规则已清除\n")
