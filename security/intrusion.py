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

    修复（2026-06-07 最终版）：
    conntrack 会把 ICMP echo request/reply 当作"连接"追踪，
    后续 ICMP 包被标记为 ESTABLISHED。若 Flood 防护规则在 ESTABLISHED
    规则之后（位置 2/3），ICMP 包直接被位置 1 的 ESTABLISHED ACCEPT，
    永远匹配不到 Flood 规则 → 40/40。

    本修复将 ICMP 规则插入位置 1（ESTABLISHED 之前），
    强制所有 ICMP echo-request 先经过限速检查。
    """
    info("[INTRUSION] 应用 ICMP Flood 防护...\n")
    # 插入顺序（逆序）:
    #   1. 先插入 DROP 到位置 1
    #   2. 再插入 limit ACCEPT 到位置 1（在 DROP 之前）
    # 最终链位置:
    #   1: ICMP limit ACCEPT（限速内放行）— 在 ESTABLISHED 之前！
    #   2: ICMP DROP（超额丢弃）
    #   3: ESTABLISHED,RELATED → ACCEPT（TCP/UDP 仍正常）
    #   4~: 其他 ACL 规则
    r1.cmd("iptables -I FORWARD 1 -p icmp --icmp-type echo-request -j DROP")
    r1.cmd("iptables -I FORWARD 1 -p icmp --icmp-type echo-request "
           "-m limit --limit 1/s --limit-burst 5 -j ACCEPT")
    info("[INTRUSION] ICMP 限速已启用 (1/s, burst=5, 插入 FORWARD 位置 1-2, "
         "ESTABLISHED 之前)\n")


# ==================== TCP SYN Flood 防护 ====================

def apply_syn_flood_protection(r1):
    """
    TCP SYN Flood 防护。
    限制 SYN 包速率 50/s，burst 100，超出部分 LOG + DROP。

    修复（2026-06-07）：
    旧实现用 -A 追加到 FORWARD 链尾，服务器 ACCEPT 规则在链中位置更靠前，
    发往服务器的 SYN 包被服务器 ACCEPT 规则匹配，SYN Flood 防护被 bypass。

    新实现：用 -I FORWARD 插入到位置 4/5/6（在 ICMP 防护 + ESTABLISHED 之后），
    TCP SYN 包不会被 ESTABLISHED 规则匹配（SYN = NEW，非 ESTABLISHED），
    确保 SYN 包先被 Flood 防护规则处理。
    """
    info("[INTRUSION] 应用 TCP SYN Flood 防护...\n")
    # 插入顺序（逆序）:
    #   1. 先插入 DROP 到位置 4
    #   2. 再插入 LOG 到位置 4
    #   3. 最后插入 limit ACCEPT 到位置 4
    # 最终链位置:
    #   1: ICMP limit ACCEPT（限速内放行，ESTABLISHED 之前）
    #   2: ICMP DROP（超额丢弃）
    #   3: ESTABLISHED,RELATED → ACCEPT
    #   4: SYN limit ACCEPT（限速内放行）
    #   5: SYN LOG（记录超额）
    #   6: SYN DROP（超额丢弃）
    r1.cmd("iptables -I FORWARD 4 -p tcp --syn -j DROP")
    r1.cmd('iptables -I FORWARD 4 -p tcp --syn -j LOG '
           '--log-prefix "SYN_FLOOD: " --log-level 4')
    r1.cmd("iptables -I FORWARD 4 -p tcp --syn "
           "-m limit --limit 50/s --limit-burst 100 -j ACCEPT")
    info("[INTRUSION] TCP SYN Flood 防护已启用 "
          "(50/s, burst=100, 插入 FORWARD 位置 4-6)\n")


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
    # 只清除 FORWARD 链中的 SYN/ICMP 相关规则
    r1.cmd("iptables -F FORWARD 2>/dev/null || true")
    reset_scan_tracker()
    info("[INTRUSION] 入侵检测规则已清除\n")
