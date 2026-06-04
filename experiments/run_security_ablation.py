"""
experiments/run_security_ablation.py — 安全策略消融实验

实验设计:
  Final（ACL + Flood + 端口扫描 + 审计） vs  Final − Security（无安全策略）

三大子实验（顺序执行）：
  1. ACL 消融：dorm1→finance1 ping (黑名单阻断) + office1→finance1 ping (白名单放行)
  2. ICMP Flood 消融：快速 ping 洪水，对比速率限制效果
  3. 端口扫描消融：对比扫描检出率和自动封禁效果

对比指标:
  ping 丢包率、洪水 ping 成功率、扫描检出率、SQLite 审计事件数
"""

import time
import sys
import os
import re as _re
import threading
import json as _json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mininet.log import info
from utils import save_to_csv, save_to_json, print_separator, timestamp, ensure_dirs

from core.topology import create_fresh_network, SERVER1_IP
from core.server_cluster import get_server_hosts
from services.iperf import start_dual_iperf
from security.acl import (
    apply_stateful_firewall, apply_acl_policies,
    apply_default_accept, clear_all_rules,
)
from security.intrusion import (
    apply_intrusion_detection, detect_port_scan, reset_scan_tracker,
)
from security.firewall import ban_ip, unban_ip, is_banned, clear_all_bans
from security.audit_db import init_db, query_events, get_statistics, clear_db
from policies.qos import apply_htb_policy


# ==================== 实验常量 ====================

PING_COUNT = 10
FLOOD_PING_COUNT = 40     # flood 快速 ping 数量
SCAN_PORTS = range(8001, 8031)  # 30 个端口，阈值 20


# ==================== 辅助函数 ====================

def _run_ping(client, target_ip, count=PING_COUNT):
    """ping 目标 IP，返回 (丢包率%, avg_rtt_ms)。"""
    cmd = f"ping -c {count} {target_ip}"
    out = client.cmd(cmd)
    if not out:
        return 100, 0
    loss_match = _re.search(r'(\d+)% packet loss', out)
    loss = int(loss_match.group(1)) if loss_match else 100
    rtt_match = _re.search(
        r'rtt min/avg/max/mdev = [\d.]+/([\d.]+)/[\d.]+/[\d.]+ ms', out)
    avg_rtt = float(rtt_match.group(1)) if rtt_match else 0
    return loss, avg_rtt


def _run_flood_pings(client, target_ip, count=FLOOD_PING_COUNT):
    """
    快速 ping 洪水：-i 0.02 间隔（50 pps）。
    解析输出得到成功数。
    iptables ICMP 限速 = 1/s burst 5 → 有安全时预期成功 ≈ 5。
    """
    cmd = f"ping -c {count} -i 0.02 -W 1 {target_ip}"
    out = client.cmd(cmd)
    if not out:
        return 0, count
    tx_match = _re.search(r'(\d+) packets transmitted', out)
    rx_match = _re.search(r'(\d+) received', out)
    tx = int(tx_match.group(1)) if tx_match else count
    rx = int(rx_match.group(1)) if rx_match else 0
    return rx, tx


def _run_curl(client, target_ip, port=80, timeout=2):
    """HTTP GET，返回 (success, response_time_s)。"""
    cmd = (f"curl -s -o /dev/null -w '%{{http_code}} %{{time_total}}' "
           f"--connect-timeout {timeout} http://{target_ip}:{port}/")
    try:
        out = client.cmd(cmd)
        parts = out.strip().split()
        if len(parts) >= 2:
            return parts[0] == "200", float(parts[1])
    except Exception:
        pass
    return False, timeout


# ==================== 网络搭建 ====================

def _setup_network(with_security=True):
    """创建网络。with_security=False 时无安全策略（对照组）。"""
    import os as _os
    _os.system("mn -c 2>/dev/null")

    net, r1, hosts, switches = create_fresh_network()
    server1, server2 = get_server_hosts(hosts)

    # 基础服务
    if server1 and server2:
        server1.cmd("pkill -f iperf3 2>/dev/null || true")
        server2.cmd("pkill -f iperf3 2>/dev/null || true")
        time.sleep(1)
        start_dual_iperf(server1, server2)
        time.sleep(2)

    # ACL 消融测试需要 finance1 上运行 iperf3 服务器（UDP 模式绕过限速器）
    finance = hosts.get("finance1")
    if finance:
        finance.cmd("pkill -f iperf3 2>/dev/null || true")
        time.sleep(0.5)
        finance.cmd("iperf3 -s -p 5207 -D 2>/dev/null &")
        time.sleep(1)

    # HTB QoS（两组都用）
    apply_htb_policy(r1)

    if with_security:
        apply_default_accept(r1)
        apply_stateful_firewall(r1)
        apply_acl_policies(r1)
        apply_intrusion_detection(r1)
        init_db(r1)
        reset_scan_tracker()
        clear_all_bans()
    else:
        clear_all_rules(r1)
        apply_default_accept(r1)
        reset_scan_tracker()
        clear_all_bans()
        db_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "security_audit.db")
        if os.path.exists(db_path):
            os.remove(db_path)

    return net, r1, hosts


# ==================== 子实验 1: ACL 消融 ====================

def _run_acl_ablation(hosts, with_security):
    """
    ACL 访问控制消融 — 使用 UDP iperf3（绕过 ICMP/TCP SYN 限速器）。
    dorm1 → finance1:5207 UDP：黑名单，应被 DROP → 0 Mbps
    office1 → finance1:5207 UDP：白名单，应被 ACCEPT → >0 Mbps
    对照组（无安全）：两者均通。
    """
    info("\n  [ACL消融] 跨区域访问控制 (UDP iperf3)...\n")

    dorm = hosts.get("dorm1")
    office = hosts.get("office1")
    if not dorm or not office:
        return {"dorm_mbps": -1, "office_mbps": -1, "dorm_success": -1, "office_success": -1}

    finance_ip = "10.0.35.2"
    port = 5207

    def _udp_throughput(client, target, desc):
        """UDP iperf3 单次测试，返回 (成功的Mbps, 是否成功)。"""
        cmd = f"iperf3 -c {target} -p {port} -u -b 5M -t 3 -J 2>/dev/null"
        out = client.cmd(cmd)
        if not out or not isinstance(out, str):
            return 0, False
        idx = out.find('{')
        if idx < 0:
            return 0, False
        try:
            data = _json.loads(out[idx:])
            if data.get("error"):
                return 0, False
            end = data.get("end", {})
            s = end.get("sum", {}) or end.get("sum_received", {})
            bps = s.get("bits_per_second", 0)
            return round(bps / 1_000_000, 2), bps > 0
        except Exception:
            return 0, False

    # 多次采样取均值（避免单次波动）
    dorm_results = []
    office_results = []
    for _ in range(3):
        time.sleep(0.5)
        dm, ds = _udp_throughput(dorm, finance_ip, "dorm→finance")
        dorm_results.append((dm, ds))
        time.sleep(0.5)
        om, os_ = _udp_throughput(office, finance_ip, "office→finance")
        office_results.append((om, os_))

    dorm_mbps = round(sum(r[0] for r in dorm_results) / 3, 2)
    dorm_success = sum(1 for r in dorm_results if r[1])
    office_mbps = round(sum(r[0] for r in office_results) / 3, 2)
    office_success = sum(1 for r in office_results if r[1])

    label = "有安全" if with_security else "无安全"
    info(f"    [{label}] dorm→finance: {dorm_mbps} Mbps ({dorm_success}/3 次成功)"
         f"{' [应0, ACL阻断]' if with_security else ' [应>0]'}\n")
    info(f"    [{label}] office→finance: {office_mbps} Mbps ({office_success}/3 次成功)"
         f"{' [应>0, 白名单]' if with_security else ' [应>0]'}\n")

    return {
        "dorm_mbps": dorm_mbps,
        "dorm_success": dorm_success,
        "office_mbps": office_mbps,
        "office_success": office_success,
    }


# ==================== 子实验 2: ICMP Flood 消融 ====================

def _run_flood_ablation(hosts, with_security):
    """
    ICMP Flood 防护消融。
    dorm1 向 server1 快速 ping（-i 0.02 = 50 pps）。
    iptables ICMP 限速: 1/s, burst 5。
    对照组（无安全）：几乎全部成功。
    实验组（有安全）：仅 ~5 个成功（burst），其余被 DROP。
    """
    info("\n  [Flood消融] ICMP Ping 洪水...\n")

    dorm = hosts.get("dorm1")
    if not dorm:
        return {"flood_success": -1, "flood_total": -1}

    rx, tx = _run_flood_pings(dorm, SERVER1_IP, FLOOD_PING_COUNT)

    label = "有安全" if with_security else "无安全"
    info(f"    [{label}] ping 成功率: {rx}/{tx}"
         f"{' (限速1/s生效)' if with_security else ' (无限速)'}\n")

    return {"flood_success": rx, "flood_total": tx}


# ==================== 子实验 3: 端口扫描消融 ====================

def _run_scan_ablation(hosts, with_security):
    """
    端口扫描检测消融。
    dorm1 扫描 server1 端口 8001-8030（30 个，阈值 20）。
    对照组：不检测，全部成功。
    实验组：≥20 端口后触发检测+自动封禁。
    """
    info("\n  [扫描消融] 端口扫描检测 + 自动封禁...\n")

    dorm = hosts.get("dorm1")
    if not dorm:
        return {"scan_success": 0, "scan_total": 0, "detected": False, "banned": False, "ban_port": -1}

    target_ip = SERVER1_IP
    scan_success = 0
    detected = False
    banned = False
    ban_port = -1

    for port in SCAN_PORTS:
        _run_curl(dorm, target_ip, port=port, timeout=0.5)
        scan_success += 1

        if with_security:
            result = detect_port_scan(dorm.IP(), target_ip, port)
            if result and not detected:
                detected = True
                ban_port = port - 8000

            if is_banned(dorm.IP()):
                banned = True
                if ban_port < 0:
                    ban_port = port - 8000
                break

        time.sleep(0.05)

    label = "有安全" if with_security else "无安全"
    info(f"    [{label}] 扫描 {scan_success}/{len(list(SCAN_PORTS))} 端口"
         f"{', 检测/封禁于第' + str(ban_port) + '端口' if banned else ''}\n")

    return {
        "scan_success": scan_success,
        "scan_total": len(list(SCAN_PORTS)),
        "detected": detected,
        "banned": banned,
        "ban_port": ban_port,
    }


# ==================== 主实验流程 ====================

def run_security_ablation():
    """安全策略综合消融实验。"""
    ensure_dirs()
    info("\n" + "=" * 70 + "\n")
    info("  安全策略消融实验 — Final vs Final − Security\n")
    info("=" * 70 + "\n")

    all_results = {}

    for group_name, with_sec in [("对照组 (无安全)", False), ("实验组 (有安全)", True)]:
        info(f"\n{'─' * 60}\n")
        info(f"  {group_name}\n")
        info(f"{'─' * 60}\n")

        net, r1, hosts = _setup_network(with_security=with_sec)
        try:
            acl = _run_acl_ablation(hosts, with_sec)
            flood = _run_flood_ablation(hosts, with_sec)
            scan = _run_scan_ablation(hosts, with_sec)

            # SQLite 审计事件
            audit_events = 0
            if with_sec:
                try:
                    stats = get_statistics(r1)
                    audit_events = sum(stats.values()) if stats else 0
                except Exception:
                    pass

            all_results[group_name] = {
                "acl": acl, "flood": flood, "scan": scan,
                "audit_events": audit_events,
            }
        finally:
            net.stop()
            time.sleep(1)

    # 输出对比表
    _print_comparison_table(all_results)
    ensure_dirs()
    save_to_json("security_ablation", all_results)


def _print_comparison_table(results):
    """输出安全消融对比表。"""
    ctrl = results.get("对照组 (无安全)", {})
    exp = results.get("实验组 (有安全)", {})

    if not ctrl or not exp:
        info("\n[ERROR] 结果不完整\n")
        return

    ca, ea = ctrl.get("acl", {}), exp.get("acl", {})
    cf, ef = ctrl.get("flood", {}), exp.get("flood", {})
    cs, es = ctrl.get("scan", {}), exp.get("scan", {})

    print_separator("安全策略消融实验结果")
    header = f"{'指标':<36} {'对照组(无安全)':<18} {'实验组(有安全)':<18} {'效果'}"
    info(header + "\n")
    info("-" * 88 + "\n")

    rows = [
        ("[ACL] dorm→finance UDP成功率",
         f"{ca.get('dorm_success', '?')}/3",
         f"{ea.get('dorm_success', '?')}/3",
         ("✅ 已阻断" if ea.get('dorm_success', 3) == 0 else "⚠ 异常") if ca.get('dorm_success', 0) > 0
         else "无安全应>0/有安全应0"),
        ("[ACL] dorm→finance UDP吞吐(Mbps)",
         f"{ca.get('dorm_mbps', 0):.2f}",
         f"{ea.get('dorm_mbps', 0):.2f}",
         "有安全应降至 0"),
        ("[ACL] office→finance UDP(白名单)",
         f"{ca.get('office_success', '?')}/3",
         f"{ea.get('office_success', '?')}/3",
         "白名单应 3/3"),
        ("[Flood] ICMP洪水成功率",
         f"{cf.get('flood_success', '?')}/{cf.get('flood_total', '?')}",
         f"{ef.get('flood_success', '?')}/{ef.get('flood_total', '?')}",
         "限速 1/s → ~5/40"),
        ("[扫描] 成功探测端点数",
         f"{cs.get('scan_success', '?')}/{cs.get('scan_total', '?')}",
         f"{es.get('scan_success', '?')}/{es.get('scan_total', '?')}",
         "有安全 ≤ 阈值(20)"),
        ("[扫描] 扫描检测",
         "❌ 不检测" if not cs.get("detected") else "✅",
         "✅ 检测" if es.get("detected") else "❌",
         "无→有"),
        ("[扫描] 自动封禁",
         "❌ 不封禁" if not cs.get("banned") else "✅",
         f"✅ 第{es.get('ban_port', '?')}端口" if es.get("banned") else "❌",
         f"阈值20端口触发" if es.get("banned") else ""),
        ("[审计] SQLite事件总数",
         str(ctrl.get("audit_events", 0)),
         str(exp.get("audit_events", 0)),
         "0→>0"),
    ]

    for label, c_val, e_val, effect in rows:
        info(f"{label:<36} {c_val:<18} {e_val:<18} {effect}\n")

    info("-" * 88 + "\n")
    info("  ※ 对照组: Final − Security (仅 HTB QoS，无安全策略)\n")
    info("  ※ 实验组: Final (ACL + ICMP Flood防护 + 端口扫描 + SQLite审计)\n")


if __name__ == "__main__":
    run_security_ablation()
