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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mininet.log import info
from utils import save_to_csv, save_to_json, print_separator, timestamp, ensure_dirs

from core.topology import create_fresh_network
from core.server_cluster import get_server_hosts
from services.web import start_web_server
from services.iperf import start_iperf_server
from security.acl import (
    apply_stateful_firewall, apply_acl_policies, apply_default_accept
)
from security.intrusion import (
    apply_intrusion_detection, detect_port_scan, reset_scan_tracker
)
from security.firewall import ban_ip, unban_ip, is_banned, clear_all_bans
from security.audit_db import init_db, query_events, get_statistics, clear_db
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
    apply_htb_policy(r1)
    init_db(r1)

    return net, r1, hosts


# ==================== 3.1 ACL 访问控制验证 ====================

def test_acl(sub_net, sub_r1, sub_hosts):
    """
    验证 ACL 规则：
      - dorm1 → finance1: 应被阻断
      - office1 → finance1: 应被放行
      - dorm1 → hr1: 应被阻断
      - office1 → hr1: 应被放行
    """
    info("\n" + "=" * 60 + "\n")
    info("  子实验 3.1: ACL 访问控制验证\n")
    info("=" * 60 + "\n")

    results = []
    tests = [
        ("dorm1", "finance1", "10.0.5.2", False, "宿舍→财务处 (应阻断)"),
        ("office1", "finance1", "10.0.5.2", True, "办公→财务处 (应放行)"),
        ("dorm1", "hr1", "10.0.6.2", False, "宿舍→人事处 (应阻断)"),
        ("office1", "hr1", "10.0.6.2", True, "办公→人事处 (应放行)"),
    ]

    for src_name, dst_name, dst_ip, expect_pass, desc in tests:
        src = sub_hosts.get(src_name)
        if src is None:
            continue

        # ping 测试
        output = src.cmd(f"ping -c 3 -W 2 {dst_ip}")
        ping_ok = "0% packet loss" in output or " 0% packet loss" in output

        status = "✅ PASS" if (ping_ok == expect_pass) else "❌ FAIL"
        info(f"  {desc}: {status} (ping {'通' if ping_ok else '不通'})\n")
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

    src_ip = "10.0.1.2"
    dst_ip = "10.0.100.2"

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
    else:
        info("  ⚠ 未触发自动封禁\n")

    # 检查 SQLite 记录
    scan_events = query_events(event_type="PORT_SCAN", limit=5)
    ban_events = query_events(event_type="BAN", limit=5)

    info(f"  SQLite PORT_SCAN 事件: {len(scan_events)} 条\n")
    info(f"  SQLite BAN 事件: {len(ban_events)} 条\n")

    results.append({
        "test": "端口扫描检测",
        "scan_detected": scan_detected,
        "ban_applied": ban_applied,
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

    # ICMP Flood 测试：快速 ping
    info("  ICMP Flood 测试: 快速 ping 10 次...\n")
    output = dorm1.cmd("ping -c 10 -i 0.1 10.0.100.2")
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

    # 验证 iptables 限速规则存在即认为防护已部署
    rule_check = sub_r1.cmd("iptables -L FORWARD -n | grep -c 'icmp' || echo 0")
    icmp_rules_exist = int(rule_check.strip()) > 0 if rule_check.strip().isdigit() else False
    icmp_protected = icmp_rules_exist

    results.append({
        "test": "ICMP Flood 防护",
        "transmitted": transmitted, "received": received,
        "loss_pct": round(loss_pct, 1),
        "iptables_rules_exist": icmp_rules_exist,
        "protection_active": icmp_protected,
    })

    # TCP SYN Flood 测试
    info("  TCP SYN Flood 防护验证...\n")
    syn_rule_check = sub_r1.cmd("iptables -L FORWARD -n | grep -c 'tcp.*SYN' || echo 0")
    syn_rules_exist = int(syn_rule_check.strip()) > 0 if syn_rule_check.strip().isdigit() else False
    info(f"  TCP SYN 限速规则存在: {syn_rules_exist}\n")

    results.append({
        "test": "TCP SYN Flood 防护",
        "iptables_rules_exist": syn_rules_exist,
        "protection_active": syn_rules_exist,
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


# ==================== 主入口 ====================

def run_security_test():
    """
    运行全部四个安全子实验。
    """
    ensure_dirs()
    info("[SECURITY_TEST] 开始安全策略验证实验\n")

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

    # 汇总
    print_separator("安全策略验证结果汇总")
    total_tests = sum(len(v) for v in all_results.values())
    passed = 0
    for category, tests in all_results.items():
        for t in tests:
            status = t.get("status", "")
            if status == "PASS":
                passed += 1
    info(f"  总测试项: {total_tests}\n")
    info(f"  ACL 测试: {len(all_results['acl'])} 项\n")
    info(f"  端口扫描测试: {len(all_results['port_scan'])} 项\n")
    info(f"  Flood 测试: {len(all_results['flood'])} 项\n")
    info(f"  审计测试: {len(all_results['audit'])} 项\n")

    # 保存
    ts = timestamp()
    save_to_json(f"security_test_{ts}.json", all_results)

    info(f"\n[SECURITY_TEST] 安全策略验证实验完成！\n")

    net.stop()
    return all_results


if __name__ == "__main__":
    run_security_test()
