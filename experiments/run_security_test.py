"""
experiments/run_security_test.py — 实验三：安全策略验证实验

四个子实验：
  3.1 ACL 访问控制验证
  3.2 端口扫描检测与自动封禁
  3.3 Flood 攻击防护（ICMP + TCP SYN）
  3.4 SQLite 安全日志审计

所有子实验在 Final 模型（QoS + LB + Security）上运行。
"""

import time
import sys
import os
import re
import threading
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mininet.log import info, setLogLevel
from utils import save_to_csv, save_to_json, print_separator, timestamp, ensure_dirs

from core.topology import create_fresh_network
from core.server_cluster import get_server_hosts
from services.web import start_web_server
from services.iperf import start_iperf_server
from security.acl import (
    apply_stateful_firewall, apply_acl_policies, apply_default_accept,
    apply_server_accept,
)
from security.intrusion import (
    apply_intrusion_detection, detect_port_scan, reset_scan_tracker
)
from security.firewall import ban_ip, unban_ip, is_banned, clear_all_bans
from security.audit_db import init_db, query_events, get_statistics, clear_db, record_event, get_db_path
from policies.qos import apply_htb_policy


def setup_security_network():
    """创建带完整安全体系的网络。"""
    import os as _os
    _os.system("mn -c 2>/dev/null")

    net, r1, hosts, switches = create_fresh_network()
    server1, server2 = get_server_hosts(hosts)

    # 服务
    if server1:
        start_web_server(server1)
        start_iperf_server(server1)
    if server2:
        start_iperf_server(server2)

    # Final 模型全部安全模块
    apply_default_accept(r1)
    apply_stateful_firewall(r1)
    apply_acl_policies(r1)
    apply_intrusion_detection(r1)
    apply_server_accept(r1)   # Flood 防护之后才放通服务器区（避免 bypass）
    apply_htb_policy(r1)
    init_db(r1)

    return net, r1, hosts


# ==================== 3.1 ACL 访问控制验证 ====================

def test_acl(sub_net, sub_r1, sub_hosts):
    """
    验证 ACL 规则：
      - dorm1 → finance1: 应被阻断
      - office1 → finance1: 应被放行
    """
    info("\n" + "=" * 60 + "\n")
    info("  子实验 3.1: ACL 访问控制验证\n")
    info("=" * 60 + "\n")

    results = []
    tests = [
        ("dorm1", "finance1", "10.0.35.2", False, "宿舍→财务处 (应阻断)"),
        ("office1", "finance1", "10.0.35.2", True, "办公→财务处 (应放行)"),
    ]

    for src_name, dst_name, dst_ip, expect_pass, desc in tests:
        src = sub_hosts.get(src_name)
        if src is None:
            continue

        # ping 测试
        info(f"\n  >>> {desc}\n")
        output = src.cmd(f"ping -c 3 -W 2 {dst_ip}")

        # 用正则提取丢包率（避免 "0% packet loss" 误匹配 "100% packet loss"）
        loss_match = re.search(r'(\d+)% packet loss', output)
        loss_pct = int(loss_match.group(1)) if loss_match else 100
        ping_ok = (loss_pct == 0)

        # 打印原始 ping 输出（论文级证据）
        for line in output.strip().split("\n"):
            if line.strip():
                info(f"  [RAW] {line}\n")

        status = "✅ PASS" if (ping_ok == expect_pass) else "❌ FAIL"
        info(f"  => {desc}: {status} (loss={loss_pct}%, ping {'通' if ping_ok else '不通'})\n")

        # 写入 ACL 验证结果到 SQLite
        event = "ACL_DENY" if not expect_pass else "ACL_ALLOW"
        record_event(
            event_type=event,
            source_ip=src_name,
            target_ip=dst_ip,
            details=f"{desc}: {status}",
            severity="WARNING" if not expect_pass else "INFO",
            r1=sub_r1,
        )

        results.append({
            "test": desc, "expected_pass": expect_pass,
            "actual_pass": ping_ok, "status": "PASS" if ping_ok == expect_pass else "FAIL",
        })

    return results


# ==================== 3.2 端口扫描检测与自动封禁 ====================

def test_port_scan(sub_net, sub_r1, sub_hosts):
    """
    模拟端口扫描：从 dorm1 对 server1 快速访问多个端口。
    验证：检测 + 自动封禁 + SQLite 记录。
    """
    info("\n" + "=" * 60 + "\n")
    info("  子实验 3.2: 端口扫描检测与自动封禁\n")
    info("=" * 60 + "\n")

    dorm1 = sub_hosts.get("dorm1")
    if dorm1 is None:
        info("  ⚠ dorm1 不存在，跳过\n")
        return []

    src_ip = "10.0.0.2"
    dst_ip = "10.0.60.2"

    reset_scan_tracker()

    results = []
    scan_detected = False
    ban_applied = False

    # 模拟对 25 个端口发起连接（超过 SCAN_PORT_THRESHOLD=20）
    for port in range(8001, 8026):
        time.sleep(0.05)
        detected = detect_port_scan(src_ip, dst_ip, port, r1=sub_r1)
        if detected:
            scan_detected = True

    if scan_detected:
        info("  ✅ 端口扫描行为已被检测\n")
    else:
        info("  ⚠ 端口扫描未被检测（可能阈值未触发）\n")

    ban_applied = is_banned(src_ip)
    if ban_applied:
        info("  ✅ 异常 IP 已被自动封禁\n")

        # ====== 封禁后验证：确认被封禁 IP 的流量确实被阻断 ======
        info("  >>> 封禁后验证: ping server1 应不通...\n")

        # 先查 iptables 规则中是否有对应 DROP 规则
        drop_check = sub_r1.cmd(
            f"iptables -L FORWARD -n -v 2>/dev/null | grep '{src_ip}' || echo 'NO_RULE'"
        )
        if "NO_RULE" not in drop_check:
            info(f"  [IPTABLES] DROP 规则已下发:\n")
            for line in drop_check.strip().split("\n"):
                if line.strip():
                    info(f"    {line.strip()}\n")
        else:
            info("  ⚠ iptables 中未找到对应 DROP 规则\n")

        post_ban_output = dorm1.cmd("ping -c 3 -W 2 10.0.60.2")
        loss_match = re.search(r'(\d+)% packet loss', post_ban_output)
        post_ban_loss = int(loss_match.group(1)) if loss_match else 100
        post_ban_ok = (post_ban_loss == 0)
        if not post_ban_ok:
            info(f"  ✅ 封禁生效: dorm1 → server1 已被阻断 (loss={post_ban_loss}%)\n")
        else:
            info("  ⚠ 封禁可能未生效: dorm1 → server1 仍然可达\n")
        # 打印封禁后 ping 原始输出
        for line in post_ban_output.strip().split("\n"):
            if line.strip() and ("packet" in line.lower() or "loss" in line.lower() or "avg" in line):
                info(f"  [POST-BAN] {line}\n")

        post_ban_blocked = not post_ban_ok
    else:
        info("  ⚠ 未触发自动封禁\n")
        post_ban_blocked = False

    # 检查 SQLite 记录
    scan_events = query_events(event_type="PORT_SCAN", limit=5)
    ban_events = query_events(event_type="BAN", limit=5)

    info(f"  SQLite PORT_SCAN 事件: {len(scan_events)} 条\n")
    info(f"  SQLite BAN 事件: {len(ban_events)} 条\n")

    results.append({
        "test": "端口扫描检测",
        "scan_detected": scan_detected,
        "ban_applied": ban_applied,
        "post_ban_blocked": post_ban_blocked,
        "sqlite_scan_records": len(scan_events),
        "sqlite_ban_records": len(ban_events),
    })

    # 解封以便后续测试
    unban_ip(src_ip, r1=sub_r1)
    clear_all_bans(sub_r1)

    return results


# ==================== 3.3 Flood 攻击防护 ====================

def test_flood_protection(sub_net, sub_r1, sub_hosts):
    """
    验证 ICMP Flood 和 TCP SYN Flood 防护。
    """
    info("\n" + "=" * 60 + "\n")
    info("  子实验 3.3: Flood 攻击防护\n")
    info("=" * 60 + "\n")

    results = []

    dorm1 = sub_hosts.get("dorm1")
    if dorm1 is None:
        return results

    # ---- ICMP Flood 测试 ----
    info("  ICMP Flood 测试: 快速 ping 10 次 (间隔 0.1s)...\n")
    output = dorm1.cmd("ping -c 10 -i 0.1 10.0.60.2")
    received = 0
    transmitted = 0
    for line in output.split("\n"):
        if "packets transmitted" in line:
            parts = line.split(",")
            if len(parts) >= 2:
                try:
                    transmitted = int(parts[0].strip().split()[0])
                    received = int(parts[1].strip().split()[0])
                except (ValueError, IndexError):
                    pass

    loss_pct = ((transmitted - received) / transmitted * 100) if transmitted > 0 else 0
    info(f"  ICMP: 发送={transmitted}, 接收={received}, 丢包率={loss_pct:.1f}%\n")

    # 打印 ICMP 统计行
    for line in output.strip().split("\n"):
        if "packet" in line.lower() or "rtt" in line.lower():
            info(f"  [ICMP] {line}\n")

    icmp_protected = loss_pct > 0  # 有丢包说明限速生效
    if icmp_protected:
        info("  ✅ ICMP Flood 防护生效 (检测到限速丢包)\n")
        record_event("FLOOD", "10.0.0.2", "10.0.60.2",
                     f"ICMP Flood: {transmitted}发/{received}收, 丢包{loss_pct:.1f}%",
                     severity="WARNING", r1=sub_r1)
    else:
        info("  ⚠ ICMP Flood 未触发明显限速\n")

    results.append({
        "test": "ICMP Flood 防护",
        "transmitted": transmitted, "received": received,
        "loss_pct": round(loss_pct, 1),
        "protection_active": icmp_protected,
    })

    # ---- TCP SYN Flood 测试：真实并发连接 ----
    info("\n  TCP SYN Flood 测试: 并发 50 个短连接模拟 SYN 洪泛...\n")

    syn_count = {"success": 0, "fail": 0, "error": 0}
    syn_lock = threading.Lock()

    def syn_probe():
        """从 Mininet 节点发起一次 TCP 连接尝试。"""
        try:
            out = dorm1.cmd(
                "curl -s -o /dev/null -w '%{http_code}' "
                "--connect-timeout 0.5 --max-time 2 "
                "http://10.0.60.2/ 2>/dev/null || echo '000'"
            )
            code = out.strip()
            with syn_lock:
                if code == "200":
                    syn_count["success"] += 1
                elif code == "000":
                    syn_count["fail"] += 1
                else:
                    syn_count["success"] += 1
        except Exception:
            with syn_lock:
                syn_count["error"] += 1

    threads = []
    for _ in range(50):
        t = threading.Thread(target=syn_probe, daemon=True)
        threads.append(t)
        t.start()
        time.sleep(0.02)  # 微间隔模拟洪泛

    for t in threads:
        t.join(timeout=5)

    info(f"  SYN Flood 结果: 成功={syn_count['success']}, "
         f"失败/超时={syn_count['fail']}, 错误={syn_count['error']}\n")

    # 记录 FLOOD 事件
    record_event("FLOOD", "10.0.0.2", "10.0.60.2",
                 f"TCP SYN Flood模拟: 50并发, 成功{syn_count['success']}/失败{syn_count['fail']}",
                 severity="CRITICAL", r1=sub_r1)

    # 验证 iptables SYN 规则存在
    syn_rule_check = sub_r1.cmd("iptables -L FORWARD -n 2>/dev/null | grep -c 'tcp.*SYN' || echo 0")
    syn_rules_exist = int(syn_rule_check.strip()) > 0 if syn_rule_check.strip().isdigit() else False
    syn_protected = syn_rules_exist and syn_count["fail"] > 0

    if syn_protected:
        info("  ✅ TCP SYN Flood 防护生效 (规则存在 + 部分连接被限速)\n")
    elif syn_rules_exist:
        info("  ⚠ TCP SYN 规则存在但未触发明显限速 (可能阈值较高)\n")
    else:
        info("  ⚠ TCP SYN 防护规则未找到\n")

    results.append({
        "test": "TCP SYN Flood 防护",
        "syn_success": syn_count["success"],
        "syn_fail": syn_count["fail"],
        "iptables_rules_exist": syn_rules_exist,
        "protection_active": syn_protected,
    })

    return results


# ==================== 3.4 SQLite 安全审计 ====================

def test_audit(sub_net, sub_r1, sub_hosts):
    """
    验证 SQLite 安全审计中心四种事件记录。
    """
    info("\n" + "=" * 60 + "\n")
    info("  子实验 3.4: SQLite 安全日志审计\n")
    info("=" * 60 + "\n")

    stats = get_statistics(r1=sub_r1)
    info(f"  安全事件统计:\n")
    for event_type, count in stats.items():
        info(f"    {event_type}: {count}\n")

    # 查询各类事件
    for event_type in ["ACL_DENY", "PORT_SCAN", "FLOOD", "BAN"]:
        events = query_events(event_type=event_type, limit=5, r1=sub_r1)
        if events:
            info(f"  {event_type} 最近事件:\n")
            for e in events[:3]:
                info(f"    [{e['timestamp']}] {e['source_ip']} → {e['target_ip']}: "
                     f"{e['details']}\n")

    results = [{
        "test": "SQLite 审计",
        "total_events": stats.get("total", 0),
        "event_types": {k: v for k, v in stats.items() if k != "total"},
    }]

    return results


# ==================== 数据库导出与统计 ====================

def dump_security_db(r1=None):
    """导出 SQLite 安全审计数据库最近 30 条记录。"""
    db_path = get_db_path(r1)
    if not os.path.exists(db_path):
        info("[SECURITY] 审计数据库不存在，跳过导出\n")
        return

    info("\n" + "=" * 70 + "\n")
    info("  SQLite 安全审计数据库 — 最近事件记录\n")
    info("=" * 70 + "\n")

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, timestamp, event_type, source_ip, target_ip, details, severity "
            "FROM security_events ORDER BY id DESC LIMIT 30"
        )
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            info("  (数据库为空，无安全事件记录)\n")
        else:
            info(f"{'ID':<5} {'时间':<22} {'事件类型':<14} {'源':<18} {'目标':<18} {'详情'}\n")
            info("-" * 120 + "\n")
            for row in rows:
                info(f"{row['id']:<5} {row['timestamp']:<22} {row['event_type']:<14} "
                     f"{row['source_ip'] or 'N/A':<18} {row['target_ip'] or 'N/A':<18} "
                     f"{row['details'] or ''}\n")
        info("=" * 70 + "\n")
    except Exception as e:
        info(f"[SECURITY] 数据库导出失败: {e}\n")


def print_security_summary(r1=None):
    """打印安全事件类型统计汇总。"""
    db_path = get_db_path(r1)
    if not os.path.exists(db_path):
        return

    info("\n" + "=" * 70 + "\n")
    info("  安全事件统计汇总 (Security Event Summary)\n")
    info("=" * 70 + "\n")

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT event_type, COUNT(*) as cnt FROM security_events "
            "GROUP BY event_type ORDER BY cnt DESC"
        )
        stats = cursor.fetchall()

        cursor.execute("SELECT COUNT(*) FROM security_events")
        total = cursor.fetchone()[0]
        conn.close()

        info(f"  总事件数: {total}\n")
        info(f"  {'事件类型':<20} {'数量':<8} {'占比'}\n")
        info("  " + "-" * 40 + "\n")
        for event_type, count in stats:
            pct = count / total * 100 if total > 0 else 0
            bar = "█" * int(pct / 5)
            info(f"  {event_type:<20} {count:<8} {pct:5.1f}% {bar}\n")
        info("=" * 70 + "\n")
    except Exception as e:
        info(f"[SECURITY] 统计汇总失败: {e}\n")


# ==================== 主入口 ====================

def run_security_test():
    """
    运行全部四个安全子实验。

    执行流程:
      攻击生成 → 防御触发 → SQLite 记录 → DB 导出 → 统计汇总
    """
    setLogLevel('info')
    ensure_dirs()

    # 清空旧审计数据，确保本轮实验数据干净
    clear_db()

    info("[SECURITY_TEST] ====== 开始安全策略验证实验 ======\n")

    # 1. 创建网络（Final 模型的安全部分）
    net, r1, hosts = setup_security_network()

    all_results = {}

    # 3.1 ACL 验证
    acl_results = test_acl(net, r1, hosts)
    all_results["acl"] = acl_results

    # 3.2 端口扫描检测与自动封禁
    scan_results = test_port_scan(net, r1, hosts)
    all_results["port_scan"] = scan_results

    # 3.3 Flood 攻击防护
    flood_results = test_flood_protection(net, r1, hosts)
    all_results["flood"] = flood_results

    # 3.4 SQLite 审计
    audit_results = test_audit(net, r1, hosts)
    all_results["audit"] = audit_results

    # ---- 汇总 ----
    print_separator("安全策略验证结果汇总")
    total_tests = sum(len(v) for v in all_results.values())
    passed = 0
    for category, tests in all_results.items():
        for t in tests:
            status = t.get("status", "")
            if status == "PASS":
                passed += 1
    info(f"  总测试项: {total_tests}\n")
    info(f"  通过: {passed} / 失败: {total_tests - passed}\n")
    info(f"  ACL 测试: {len(all_results['acl'])} 项\n")
    info(f"  端口扫描测试: {len(all_results['port_scan'])} 项\n")
    info(f"  Flood 测试: {len(all_results['flood'])} 项\n")
    info(f"  审计测试: {len(all_results['audit'])} 项\n")

    # ---- DB 导出与统计（攻击→防御→记录→统计 闭环） ----
    dump_security_db(r1=r1)
    print_security_summary(r1=r1)

    # 保存 JSON
    ts = timestamp()
    save_to_json(f"security_test_{ts}.json", all_results)

    info(f"\n[SECURITY_TEST] 安全策略验证实验完成！\n")

    net.stop()
    return all_results


if __name__ == "__main__":
    run_security_test()
