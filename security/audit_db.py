"""
security/audit_db.py — SQLite 安全审计中心

统一存储四类安全事件：
  1. ACL 拒绝事件
  2. 端口扫描事件
  3. Flood 攻击事件
  4. 自动封禁事件

提供查询和统计接口。
"""

import os
import sqlite3
import time
from datetime import datetime

# 数据库路径：项目根目录，确保跨环境可访问
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_PROJECT_ROOT, "campus_security_audit.db")


def get_db_path(r1=None):
    """
    返回数据库路径。
    数据库位于项目根目录，Mininet 节点与宿主机共享文件系统，均可访问。
    """
    return DB_PATH


def init_db(r1=None):
    """
    初始化 SQLite 审计数据库，创建事件表。
    可在路由器节点或本地执行。
    """
    db_path = get_db_path(r1)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS security_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            source_ip TEXT,
            target_ip TEXT,
            details TEXT,
            severity TEXT DEFAULT 'INFO'
        )
    """)

    # 为常见查询创建索引
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_event_type
        ON security_events(event_type)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_timestamp
        ON security_events(timestamp)
    """)

    conn.commit()
    conn.close()
    return db_path


def record_event(event_type, source_ip=None, target_ip=None,
                 details="", severity="INFO", r1=None):
    """
    记录一条安全事件到 SQLite 数据库。

    参数:
        event_type: 事件类型 (ACL_DENY / PORT_SCAN / FLOOD / BAN / ...)
        source_ip:  源 IP
        target_ip:  目标 IP
        details:    事件详情
        severity:   严重级别 (INFO / WARNING / CRITICAL)
        r1:         路由器节点（用于数据库路径）
    """
    db_path = get_db_path(r1)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 确保表存在
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS security_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                source_ip TEXT,
                target_ip TEXT,
                details TEXT,
                severity TEXT DEFAULT 'INFO'
            )
        """)

        cursor.execute(
            "INSERT INTO security_events (timestamp, event_type, source_ip, "
            "target_ip, details, severity) VALUES (?, ?, ?, ?, ?, ?)",
            (timestamp, event_type, source_ip, target_ip, details, severity)
        )

        conn.commit()
        conn.close()
    except Exception as e:
        # 静默失败，不影响主流程
        pass


def query_events(event_type=None, limit=50, r1=None):
    """
    查询安全事件。

    参数:
        event_type: 过滤事件类型，None 返回所有
        limit:      返回记录数上限

    返回:
        list[dict]: 事件列表
    """
    db_path = get_db_path(r1)

    if not os.path.exists(db_path):
        return []

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if event_type:
            cursor.execute(
                "SELECT * FROM security_events WHERE event_type = ? "
                "ORDER BY id DESC LIMIT ?",
                (event_type, limit)
            )
        else:
            cursor.execute(
                "SELECT * FROM security_events ORDER BY id DESC LIMIT ?",
                (limit,)
            )

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]
    except Exception:
        return []


def get_statistics(r1=None):
    """
    获取安全事件统计摘要。

    返回:
        dict: 各类型事件计数
    """
    db_path = get_db_path(r1)

    if not os.path.exists(db_path):
        return {}

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT event_type, COUNT(*) FROM security_events "
            "GROUP BY event_type"
        )
        stats = dict(cursor.fetchall())

        cursor.execute("SELECT COUNT(*) FROM security_events")
        stats["total"] = cursor.fetchone()[0]

        conn.close()
        return stats
    except Exception:
        return {}


def clear_db(r1=None):
    """清空审计数据库。"""
    db_path = get_db_path(r1)
    try:
        if os.path.exists(db_path):
            os.remove(db_path)
    except Exception:
        pass
