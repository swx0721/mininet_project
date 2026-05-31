"""
experiments/run_qos_ablation.py — 实验一：QoS 消融实验

实验设计:
  Final（QoS + LB + Security） vs  Final − QoS（LB + Security）

对比指标:
  - 关键业务（财务处/人事处）吞吐量
  - 时延
  - 抖动
  - 丢包率

实现：基于现有 qos_test.py 的三组对比逻辑，适配模型驱动架构。
"""

import time
import sys
import os
import random
import threading
import json as _json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mininet.log import info
from utils import save_to_csv, save_to_json, print_separator, timestamp, ensure_dirs

from core.topology import create_fresh_network, BOTTLENECK_BW, SERVER1_IP, SERVER2_IP
from core.server_cluster import get_server_hosts, DEFAULT_STATIC_MAPPING
from services.web import start_web_server
from services.iperf import start_dual_iperf
from security.acl import (
    apply_stateful_firewall, apply_acl_policies,
    apply_default_accept, clear_all_rules
)
from security.intrusion import apply_intrusion_detection
from security.audit_db import init_db
from policies.qos import apply_htb_policy, apply_baseline_policy, clear_qos
from policies.load_balance import LoadBalancer


# ==================== 实验常量 ====================

COMPETING_CLIENTS = [
    ("finance1", DEFAULT_STATIC_MAPPING["finance1"], "财务处 (关键业务-TCP)",  "入口1", 5201, "tcp", 10),
    ("teach1",   DEFAULT_STATIC_MAPPING["teach1"],   "教学楼 (课件下载-TCP)",   "入口1", 5202, "tcp", 20),
    ("office1",  DEFAULT_STATIC_MAPPING["office1"],  "办公楼 (OA系统-TCP)",     "入口1", 5203, "tcp", 15),
    ("dorm1",    DEFAULT_STATIC_MAPPING["dorm1"],    "宿舍区 (视频流-UDP)",     "入口2", 5201, "udp", 12),
    ("lib1",     DEFAULT_STATIC_MAPPING["lib1"],     "图书馆 (网页浏览-TCP)",   "入口2", 5202, "tcp", 15),
    ("finance_probe", DEFAULT_STATIC_MAPPING["finance_probe"], "财务处 (UDP探针)", "入口1", 5204, "udp", 1),
]

POISSON_LAMBDA = {
    "finance1": 0.5, "teach1": 0.4, "office1": 0.4,
    "dorm1": 0.4, "lib1": 0.3, "finance_probe": 0.25,
}

CLIENT_IPS = {
    "dorm1": "10.0.1.2", "teach1": "10.0.2.2", "lib1": "10.0.3.2",
    "office1": "10.0.4.2", "finance1": "10.0.5.2",
}

FLOW_DURATION = 5
TOTAL_EXPERIMENT_TIME = 60
PING_COUNT = 10
PING_INTERVAL = 0.2


def parse_iperf_output(result):
    try:
        start = result.find("{")
        end = result.rfind("}")
        if start < 0 or end < start:
            return None
        data = _json.loads(result[start:end + 1])
        if data.get("error"):
            return None
        end_data = data.get("end", {})
        for key in ("sum_received", "sum_sent", "sum"):
            c = end_data.get(key)
            if c and c.get("bits_per_second") is not None:
                return c["bits_per_second"] / 1_000_000
    except Exception:
        return None
    return None


def parse_udp_iperf_output(result):
    try:
        start = result.find("{")
        end = result.rfind("}")
        if start < 0 or end < start:
            return None
        data = _json.loads(result[start:end + 1])
        if data.get("error"):
            return None
        end_data = data.get("end", {})
        for key in ("sum_received", "sum", "sum_sent"):
            c = end_data.get(key)
            if c and c.get("bits_per_second") is not None:
                return {
                    "throughput_mbps": c["bits_per_second"] / 1_000_000,
                    "jitter_ms": c.get("jitter_ms", 0),
                    "lost_percent": c.get("lost_percent", 0),
                }
    except Exception:
        return None
    return None


def parse_ping_output(result):
    try:
        for line in result.split("\n"):
            if "avg" in line and "/" in line:
                parts = line.split("=")
                if len(parts) >= 2:
                    stats = parts[1].strip().split("/")
                    if stats:
                        return float(stats[1])
    except Exception:
        return None
    return None


def setup_network_for_policy(policy_type, bottleneck_bw):
    """创建网络并应用指定 QoS 策略 + 安全。"""
    import os as _os
    _os.system("mn -c 2>/dev/null")

    net, r1, hosts, switches = create_fresh_network()
    server1, server2 = get_server_hosts(hosts)

    # 服务
    if server1:
        start_web_server(server1)
    start_dual_iperf(server1, server2)

    # 安全（ACL + IDS）
    apply_default_accept(r1)
    apply_stateful_firewall(r1)
    apply_acl_policies(r1)
    apply_intrusion_detection(r1)
    init_db(r1)

    # QoS 策略
    if policy_type == "baseline":
        apply_baseline_policy(r1, bottleneck_bw=bottleneck_bw)
    elif policy_type == "htb":
        apply_htb_policy(r1, bottleneck_bw=bottleneck_bw)

    return net, r1, hosts


def run_client_traffic(net, hosts, client_spec, results, lock):
    """运行单个客户端流量生成。"""
    client_name = client_spec[0]
    target_ip = client_spec[1]
    protocol = client_spec[5]
    port = client_spec[4]
    target_bw = client_spec[6]

    client = hosts.get(client_name)
    CLIENT_HOSTS_MAP = {"finance_probe": "finance1"}
    actual_node = client or hosts.get(CLIENT_HOSTS_MAP.get(client_name))

    if actual_node is None:
        return

    end_time = time.time() + TOTAL_EXPERIMENT_TIME
    while time.time() < end_time:
        delay = random.expovariate(POISSON_LAMBDA.get(client_name, 0.3))
        if time.time() + delay >= end_time:
            break
        time.sleep(delay)

        if protocol == "tcp":
            cmd = f"iperf3 -c {target_ip} -p {port} -t {FLOW_DURATION} -J 2>/dev/null"
        else:
            cmd = f"iperf3 -c {target_ip} -p {port} -u -b {target_bw}M -t {FLOW_DURATION} -J 2>/dev/null"

        output = actual_node.cmd(cmd)

        if protocol == "tcp":
            tp = parse_iperf_output(output)
            if tp is not None:
                with lock:
                    results.append({"client": client_name, "protocol": "tcp",
                                    "throughput_mbps": tp})
        else:
            udp = parse_udp_iperf_output(output)
            if udp is not None:
                with lock:
                    results.append({
                        "client": client_name, "protocol": "udp",
                        "throughput_mbps": udp["throughput_mbps"],
                        "jitter_ms": udp["jitter_ms"],
                        "lost_percent": udp["lost_percent"],
                    })


def measure_latency(net, hosts, client_spec, results, lock):
    """测量时延。"""
    client_name = client_spec[0]
    ip = CLIENT_IPS.get(client_name)
    if ip is None:
        return

    client = hosts.get(client_name)
    if client is None:
        return

    time.sleep(TOTAL_EXPERIMENT_TIME // 2)
    output = client.cmd(f"ping -c {PING_COUNT} -i {PING_INTERVAL} {SERVER1_IP}")
    rtt = parse_ping_output(output)
    if rtt is not None:
        with lock:
            results.append({"client": client_name, "protocol": "ping", "rtt_ms": rtt})


def run_single_policy_experiment(policy_type, label, bottleneck_bw):
    """运行单个 QoS 策略实验。"""
    info(f"\n{'='*60}\n")
    info(f"  实验: {label}\n")
    info(f"{'='*60}\n")

    net, r1, hosts = setup_network_for_policy(policy_type, bottleneck_bw)

    traffic_results = []
    latency_results = []
    lock = threading.Lock()

    threads = []
    for spec in COMPETING_CLIENTS:
        t = threading.Thread(target=run_client_traffic,
                             args=(net, hosts, spec, traffic_results, lock))
        threads.append(t)
        t2 = threading.Thread(target=measure_latency,
                              args=(net, hosts, spec, latency_results, lock))
        threads.append(t2)

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    net.stop()

    # 汇总
    summary = {}
    for r in traffic_results:
        key = r["client"]
        if key not in summary:
            summary[key] = {"throughputs": [], "jitters": [], "losses": []}
        summary[key]["throughputs"].append(r.get("throughput_mbps", 0))
        if r.get("jitter_ms") is not None:
            summary[key]["jitters"].append(r["jitter_ms"])
        if r.get("lost_percent") is not None:
            summary[key]["losses"].append(r["lost_percent"])

    for r in latency_results:
        key = r["client"]
        if key not in summary:
            summary[key] = {"throughputs": [], "jitters": [], "losses", "rtts": []}
        if "rtts" not in summary[key]:
            summary[key]["rtts"] = []
        summary[key]["rtts"].append(r["rtt_ms"])

    # 计算平均值
    aggregated = {}
    for client, vals in summary.items():
        tps = vals["throughputs"]
        rtts = vals.get("rtts", [])
        jitters = vals.get("jitters", [])
        losses = vals.get("losses", [])

        aggregated[client] = {
            "throughput_mbps": round(sum(tps) / len(tps), 2) if tps else 0,
            "rtt_ms": round(sum(rtts) / len(rtts), 2) if rtts else 0,
            "jitter_ms": round(sum(jitters) / len(jitters), 2) if jitters else None,
            "lost_percent": round(sum(losses) / len(losses), 2) if losses else None,
        }

    return aggregated, label


def run_qos_ablation(server_ip="10.0.100.2", duration=None):
    """
    运行 QoS 消融实验。

    对比:
      1. Baseline (pfifo) — 代表 Final − QoS
      2. HTB QoS — 代表 Final
    """
    if duration is not None:
        global TOTAL_EXPERIMENT_TIME
        TOTAL_EXPERIMENT_TIME = duration

    ensure_dirs()
    info("[QOS_ABLATION] 开始 QoS 消融实验\n")

    bw = BOTTLENECK_BW

    # 实验组 1: Final − QoS (Baseline)
    baseline_data, baseline_label = run_single_policy_experiment(
        "baseline", "Final − QoS (Baseline/pfifo)", bw
    )

    # 清理
    import os as _os
    _os.system("mn -c 2>/dev/null")
    time.sleep(2)

    # 实验组 2: Final (HTB QoS)
    htb_data, htb_label = run_single_policy_experiment(
        "htb", "Final (HTB QoS)", bw
    )

    # 输出对比结果
    print_separator("QoS 消融实验结果 — 四维指标")
    header = f"{'区域':<28} {'协议':<6} {'吞吐量(Mbps)':<14} {'时延(ms)':<12} {'抖动(ms)':<12} {'丢包率(%)':<12}"
    info(header + "\n")
    info("-" * 90 + "\n")

    client_labels = {
        "finance1": "财务处 (关键业务-TCP)",
        "teach1": "教学楼 (课件下载-TCP)",
        "office1": "办公楼 (OA系统-TCP)",
        "dorm1": "宿舍区 (视频流-UDP)",
        "lib1": "图书馆 (网页浏览-TCP)",
        "finance_probe": "财务处 (UDP探针)",
    }

    csv_rows = []
    for client_key, label in client_labels.items():
        b = baseline_data.get(client_key, {})
        h = htb_data.get(client_key, {})

        info(f"[Baseline] {label:<20} tcp     "
             f"{b.get('throughput_mbps', 0):<14.2f} "
             f"{b.get('rtt_ms', 0):<12.2f} "
             f"{b.get('jitter_ms') or 'N/A':<12} "
             f"{b.get('lost_percent') or 'N/A':<12}\n")

        info(f"[HTB QoS]  {label:<20} tcp     "
             f"{h.get('throughput_mbps', 0):<14.2f} "
             f"{h.get('rtt_ms', 0):<12.2f} "
             f"{h.get('jitter_ms') or 'N/A':<12} "
             f"{h.get('lost_percent') or 'N/A':<12}\n")
        info("-" * 90 + "\n")

        csv_rows.append([
            f"[Baseline] {label}", "tcp",
            b.get("throughput_mbps", 0), b.get("rtt_ms", 0),
            b.get("jitter_ms") or "N/A", b.get("lost_percent") or "N/A",
        ])
        csv_rows.append([
            f"[HTB QoS] {label}", "tcp",
            h.get("throughput_mbps", 0), h.get("rtt_ms", 0),
            h.get("jitter_ms") or "N/A", h.get("lost_percent") or "N/A",
        ])

    # 保存
    ts = timestamp()
    csv_file = f"qos_ablation_{ts}.csv"
    save_to_csv(csv_file,
                ["区域", "协议", "吞吐量(Mbps)", "时延(ms)", "抖动(ms)", "丢包率(%)"],
                csv_rows)
    save_to_json(f"qos_ablation_{ts}.json",
                 {"baseline": baseline_data, "htb": htb_data},
                 subdir="qos")

    info(f"\n[QOS_ABLATION] 实验完成！结果已保存\n")
    return csv_rows


if __name__ == "__main__":
    run_qos_ablation()
