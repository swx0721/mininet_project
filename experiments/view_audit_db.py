"""
experiments/view_audit_db.py — 查看 SQLite 审计数据库前 N 条记录

用法:
    # 在 Mininet CLI 中
    py experiments.view_audit_db.show_recent(5)

    # 或在 Linux 终端直接运行
    python3 experiments/view_audit_db.py

    # 查看指定条数
    python3 experiments/view_audit_db.py 10
"""

import sqlite3
import os
import sys


# 项目根目录（脚本位于 experiments/ 子目录）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_PATH = os.path.join(_PROJECT_ROOT, "campus_security_audit.db")


def show_recent(limit=5, db_path=None):
    """
    从 SQLite 审计数据库读取并打印最近 N 条记录。

    用法（Mininet CLI）:
        py experiments.view_audit_db.show_recent(5)
        py experiments.view_audit_db.show_recent(10)
    """
    if db_path is None:
        db_path = _DB_PATH

    if not os.path.exists(db_path):
        print(f"\n  数据库文件不存在: {db_path}")
        print("  请先运行安全策略实验以生成审计数据。\n")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 检查表是否存在
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='security_events'"
    )
    if not cursor.fetchone():
        print("\n  security_events 表不存在，请先运行 init_db()。\n")
        conn.close()
        return

    # 查询前 N 条记录
    cursor.execute(
        "SELECT id, timestamp, event_type, source_ip, target_ip, "
        "details, severity FROM security_events ORDER BY id ASC LIMIT ?",
        (limit,)
    )
    rows = cursor.fetchall()

    # 查询总数
    cursor.execute("SELECT COUNT(*) FROM security_events")
    total = cursor.fetchone()[0]
    conn.close()

    # 打印结果
    print(f"\n{'=' * 90}")
    print(f"  SQLite 安全审计数据库 — 前 {min(limit, len(rows))} 条 / 共 {total} 条")
    print(f"{'=' * 90}")

    if not rows:
        print("  (无记录)\n")
        return

    for row_id, ts, etype, src, dst, details, sev in rows:
        print(f"\n  ID:       {row_id}")
        print(f"  时间:     {ts}")
        print(f"  类型:     {etype}")
        print(f"  源 IP:    {src or '—'}")
        print(f"  目标 IP:  {dst or '—'}")
        print(f"  详情:     {details or '—'}")
        print(f"  严重级别: {sev or '—'}")
        print(f"  {'-' * 60}")

    # 按类型汇总
    print(f"\n{'─' * 90}")
    print(f"  事件类型分布")
    print(f"{'─' * 90}")

    conn2 = sqlite3.connect(db_path)
    c2 = conn2.cursor()
    c2.execute(
        "SELECT event_type, COUNT(*) FROM security_events GROUP BY event_type"
    )
    for etype, cnt in c2.fetchall():
        print(f"    {etype:<24} {cnt} 条")
    conn2.close()

    print(f"\n  ══════════════════════════════════════════════════")
    print(f"  Mininet CLI 快速调用: py experiments.view_audit_db.show_recent(5)")
    print(f"  ══════════════════════════════════════════════════\n")


# ==================== 命令行入口 ====================

if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    show_recent(limit)
