"""
security/firewall.py — 自动封禁机制

当检测到持续异常行为时，自动下发 iptables DROP 规则
阻断恶意 IP 的所有流量。

封禁记录通过 event_logger 写入 SQLite 审计中心。
"""

import time
from mininet.log import info
from security.event_logger import log_ban_event

# 封禁列表: { ip: ban_time }
_banned_ips = {}

BAN_DURATION = 300  # 默认封禁时长（秒）


def ban_ip(ip, reason="未知", duration=None, r1=None):
    """
    封禁指定 IP。

    参数:
        ip:       要封禁的 IP 地址
        reason:   封禁原因
        duration: 封禁时长（秒），None 则使用默认值
        r1:       路由器节点（用于执行 iptables 命令）
    """
    if duration is None:
        duration = BAN_DURATION

    now = time.time()

    # 如果已在封禁列表中，延长封禁时间
    if ip in _banned_ips:
        info(f"[FIREWALL] {ip} 已在封禁列表中，延长封禁时长\n")

    _banned_ips[ip] = now + duration

    # 下发 iptables 规则（使用 -I 插入到链首，确保优先于已有 ACCEPT 规则）
    if r1 is not None:
        r1.cmd(f"iptables -I FORWARD 1 -s {ip} -j DROP")
        r1.cmd(f"iptables -I FORWARD 1 -d {ip} -j DROP")
        r1.cmd(f"iptables -I INPUT 1 -s {ip} -j DROP")

    info(f"[FIREWALL] 🔒 已封禁 {ip}，原因: {reason}，时长: {duration}s\n")

    log_ban_event(ip, reason, duration, r1)

    return True


def unban_ip(ip, r1=None):
    """解封指定 IP。"""
    if ip in _banned_ips:
        del _banned_ips[ip]

    if r1 is not None:
        r1.cmd(f"iptables -D FORWARD -s {ip} -j DROP 2>/dev/null || true")
        r1.cmd(f"iptables -D FORWARD -d {ip} -j DROP 2>/dev/null || true")
        r1.cmd(f"iptables -D INPUT -s {ip} -j DROP 2>/dev/null || true")

    info(f"[FIREWALL] 🔓 已解封 {ip}\n")


def is_banned(ip):
    """检查 IP 是否被封禁。"""
    if ip not in _banned_ips:
        return False
    if time.time() > _banned_ips[ip]:
        del _banned_ips[ip]
        return False
    return True


def get_ban_list():
    """返回当前封禁列表。"""
    now = time.time()
    return {ip: remaining for ip, expiry in _banned_ips.items()
            if (remaining := expiry - now) > 0}


def clear_all_bans(r1=None):
    """清除所有封禁。"""
    global _banned_ips
    for ip in list(_banned_ips.keys()):
        unban_ip(ip, r1)
    _banned_ips = {}
    info("[FIREWALL] 所有封禁已清除\n")
