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
    """
    info("[INTRUSION] 应用 ICMP Flood 防护...\n")
    r1.cmd("iptables -A FORWARD -p icmp --icmp-type echo-request "
           "-m limit --limit 1/s --limit-burst 5 -j ACCEPT")
    r1.cmd("iptables -A FORWARD -p icmp --icmp-type echo-request -j DROP")
    info("[INTRUSION] ICMP 限速已启用 (1/s, burst=5)\n")


# ==================== TCP SYN Flood 防护 ====================

def apply_syn_flood_protection(r1):
    """
    TCP SYN Flood 防护。
    限制 SYN 包速率，超出部分 LOG + DROP。
    """
    info("[INTRUSION] 应用 TCP SYN Flood 防护...\n")

    # 限制 SYN 速率
    r1.cmd("iptables -A FORWARD -p tcp --syn "
           "-m limit --limit 50/s --limit-burst 100 -j ACCEPT")
    r1.cmd('iptables -A FORWARD -p tcp --syn -j LOG '
           '--log-prefix "SYN_FLOOD: " --log-level 4')
    r1.cmd("iptables -A FORWARD -p tcp --syn -j DROP")

    info("[INTRUSION] TCP SYN Flood 防护已启用 (50/s, burst=100)\n")


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
