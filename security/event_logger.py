"""
security/event_logger.py — 安全事件统一记录入口

为所有安全模块提供统一的事件记录接口，
自动将事件写入 SQLite 审计中心和 Mininet 日志。
"""

from mininet.log import info
from security.audit_db import record_event, init_db


# 全局初始化标志
_db_initialized = False


def ensure_db(r1=None):
    """确保 SQLite 审计数据库已初始化。"""
    global _db_initialized
    if not _db_initialized:
        init_db(r1)
        _db_initialized = True
        info("[AUDIT] SQLite 安全审计中心已初始化\n")


def log_acl_deny(src_subnet, dst_subnet, tag, r1=None):
    """记录 ACL 拒绝事件。"""
    ensure_db(r1)
    record_event(
        event_type="ACL_DENY",
        source_ip=src_subnet,
        target_ip=dst_subnet,
        details=f"规则标签: {tag}",
        severity="WARNING",
        r1=r1,
    )


def log_port_scan(src_ip, dst_ip, port_count, r1=None):
    """记录端口扫描事件。"""
    ensure_db(r1)
    record_event(
        event_type="PORT_SCAN",
        source_ip=src_ip,
        target_ip=dst_ip,
        details=f"扫描端口数: {port_count}",
        severity="CRITICAL",
        r1=r1,
    )


def log_flood_event(src_ip, flood_type, r1=None):
    """记录 Flood 攻击事件。"""
    ensure_db(r1)
    record_event(
        event_type="FLOOD",
        source_ip=src_ip,
        target_ip="N/A",
        details=f"Flood 类型: {flood_type}",
        severity="CRITICAL",
        r1=r1,
    )


def log_ban_event(ip, reason, duration, r1=None):
    """记录自动封禁事件。"""
    ensure_db(r1)
    record_event(
        event_type="BAN",
        source_ip=ip,
        target_ip="N/A",
        details=f"封禁原因: {reason}, 时长: {duration}s",
        severity="WARNING",
        r1=r1,
    )
