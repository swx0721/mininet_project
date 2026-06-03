"""
experiments/run_qos_ablation.py — 实验一：QoS 消融实验

实验设计:
  Final（QoS + LB + Security） vs  Final − QoS（LB + Security）

对比指标:
  - 关键业务（财务处）吞吐量
  - 时延
  - 抖动
  - 丢包率

实现：基于原版 qos_test.py 的三组对比逻辑，适配模型驱动架构。
使用 popen() 确保多线程并发流量真实竞争。
"""

import time
import sys
import os
import random
import re as _re
import threading
import json as _json
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mininet.log import info
from utils import save_to_csv, save_to_json, print_separator, timestamp, ensure_dirs

from core.topology import create_fresh_network, SERVER1_IP, SERVER2_IP
from core.server_cluster import get_server_hosts, DEFAULT_STATIC_MAPPING
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

# QoS 消融实验使用 Round Robin LB，不使用静态映射
# 客户端列表（不含服务器 IP，由 LoadBalancer 动态分配）
COMPETING_CLIENTS = [
    ("finance1", "财务处 (关键业务-TCP)",  "RR动态", 5201, "tcp", 10),
    ("teach1",   "教学楼 (课件下载-TCP)",   "RR动态", 5202, "tcp", 20),
    ("office1",  "办公楼 (OA系统-TCP)",     "RR动态", 5203, "tcp", 15),
    ("dorm1",    "宿舍区 (视频流-UDP)",     "RR动态", 5201, "udp", 12),
    ("lib1",     "图书馆 (网页浏览-TCP)",   "RR动态", 5202, "tcp", 15),
    ("finance_probe", "财务处 (UDP探针)", "RR动态", 5204, "udp", 1),
]

# 主机别名：finance_probe 与 finance1 共用同一个 Mininet 节点
CLIENT_HOSTS = {
    "finance_probe": "finance1",
}

CLIENT_IPS = {
    "dorm1": "10.0.1.2", "teach1": "10.0.2.2", "lib1": "10.0.3.2",
    "office1": "10.0.4.2", "finance1": "10.0.5.2",
}

POISSON_LAMBDA = {}

# ==================== 场景定义 ====================

# 场景 A：S1/S2 双侧中等负载 — HTB 不触发（作为场景 B 的对照基线）
#   设计意图：S1 三区域和 S2 两区域都处于中等负载，链路不发生拥塞；
#             HTB 优先级调度无竞争可供仲裁，预期消融前后（pfifo vs HTB）差异极小；
#             这作为场景 B（S1 高负载）的对照，证明 HTB 仅在拥塞时才有效。
#
#   S1 λ 合计 = 0.2+0.15+0.1+0.15(probe) = 0.60  → ~33% 链路利用率（中等，无拥塞）
#   S2 λ 合计 = 0.15+0.1                 = 0.25  → ~14% 链路利用率（低，无拥塞）
QOS_SCENARIO_A = {
    "finance1": 0.2, "teach1": 0.15, "office1": 0.1,
    "dorm1": 0.15, "lib1": 0.1, "finance_probe": 0.15,
}

# 场景 B：Server1 高负载 — S1 明显高于 S2（默认，不变）
#   设计意图：S1 三区域 λ 较高，链路产生竞争拥塞；S2 中低负载；
#             HTB 对关键业务（财务处）的优先级保障在拥塞时才能体现。
#   S1 λ 合计 = 0.5+0.4+0.4+0.25(probe) = 1.55
#   S2 λ 合计 = 0.4+0.3                 = 0.70
QOS_SCENARIO_B = {
    "finance1": 0.5, "teach1": 0.4, "office1": 0.4,
    "dorm1": 0.4, "lib1": 0.3, "finance_probe": 0.25,
}

SCENARIO_LAMBDA_MAP = {"A": QOS_SCENARIO_A, "B": QOS_SCENARIO_B}


def _set_qos_scenario(scenario: str):
    """设置当前 QoS 消融实验场景并更新全局 POISSON_LAMBDA。"""
    global POISSON_LAMBDA
    POISSON_LAMBDA = SCENARIO_LAMBDA_MAP[scenario]
    return scenario

FLOW_DURATION = 5
TOTAL_EXPERIMENT_TIME = 60
PING_COUNT = 10
PING_INTERVAL = 0.2


# ==================== 输出解析 ====================



def _extract_iperf_json(output):
    """
    从混杂了 stderr / shell 日志的输出中安全提取 JSON。

    iperf3 在连接失败时会在 JSON 后面追加错误信息：
      {...json...}\niperf3: error - unable to send control message: Bad file descriptor

    只用 JSON 部分，忽略后面的错误日志。
    """
    if not output:
        return None
    # 找到第一个 { 和最后一个 } 之间的内容
    match = _re.search(r'\{.*\}', output, _re.DOTALL)
    if not match:
        return None
    try:
        return _json.loads(match.group())
    except (_json.JSONDecodeError, ValueError):
        return None


def parse_iperf_output(result):
    """从 iperf3 JSON 解析 TCP 吞吐量 (Mbps)。"""
    data = _extract_iperf_json(result)
    if data is None:
        return None

    if data.get("error"):
        return None

    end_data = data.get("end")
    if not end_data:
        return None

    # 尝试多个可能的吞吐量字段
    for key in ("sum_received", "sum_sent", "sum"):
        c = end_data.get(key)
        if c and c.get("bits_per_second") is not None:
            return c["bits_per_second"] / 1_000_000

    # 回退：使用最后一个 interval 的 sum
    intervals = data.get("intervals", [])
    if intervals:
        last = intervals[-1].get("sum", {})
        if last.get("bits_per_second") is not None:
            return last["bits_per_second"] / 1_000_000

    return None


def parse_udp_iperf_output(result):
    """从 iperf3 UDP JSON 解析吞吐量、抖动和丢包率。"""
    data = _extract_iperf_json(result)
    if data is None:
        return None

    if data.get("error"):
        return None

    end_data = data.get("end")
    if not end_data:
        return None

    sum_data = None
    for candidate_key in ("sum_received", "sum", "sum_sent"):
        candidate = end_data.get(candidate_key)
        if candidate and candidate.get("bits_per_second") is not None:
            sum_data = candidate
            break

    if not sum_data:
        return None

    return {
        "throughput_mbps": sum_data["bits_per_second"] / 1_000_000,
        "jitter_ms": sum_data.get("jitter_ms", 0),
        "lost_percent": sum_data.get("lost_percent", 0),
    }


def parse_ping_output(result):
    """从 ping 输出解析平均 RTT (ms)。"""
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


# ==================== 网络搭建 ====================

def setup_network_for_policy(policy_type):
    """创建网络并应用指定 QoS 策略 + 安全（不启动 iperf3）。"""
    import os as _os
    _os.system("mn -c 2>/dev/null")

    net, r1, hosts, switches = create_fresh_network()

    # 安全（Final 模型的安全体系）
    apply_default_accept(r1)
    apply_stateful_firewall(r1)
    apply_acl_policies(r1)
    apply_intrusion_detection(r1)
    init_db(r1)

    # QoS 策略（各区域上行链路独立调度）
    clear_qos(r1)
    if policy_type == "baseline":
        apply_baseline_policy(r1)
    elif policy_type == "htb":
        apply_htb_policy(r1)

    return net, r1, hosts


# ==================== 动态流量生成（popen 并发模式）====================

def run_competitive_measurement(net, hosts, duration):
    """
    使用 popen() 实现真正的多线程并发 iperf3 流量竞争。
    使用 Round Robin LoadBalancer 动态分配目标服务器。
    """
    # 启动两个服务入口的 iperf3
    server1, server2 = get_server_hosts(hosts)
    if server1 and server2:
        # 统一清理残留进程（在先启动服务器之前做一次）
        server1.cmd("pkill -f iperf3 2>/dev/null || true")
        server2.cmd("pkill -f iperf3 2>/dev/null || true")
        time.sleep(1.5)

        # 启动 iperf3 服务（start_dual_iperf 内部已处理 skip_kill 逻辑）
        start_dual_iperf(server1, server2)
        # 充分等待服务就绪
        time.sleep(3)

    # 创建 Round Robin 负载均衡器（QoS 消融实验中必须使用 RR）
    load_balancer = LoadBalancer(algorithm="round_robin")

    # 打印端口分配信息
    info("[QOS_ABLATION] iperf3 端口分配（Server1/Server2 均开放 5201-5204）:\n")
    for spec in COMPETING_CLIENTS:
        info(f"  {spec[0]:<16} {spec[4]:<5} port={spec[3]} (由 LB 动态分配目标)\n")

    results_lock = threading.Lock()
    flow_samples = {client_spec[0]: [] for client_spec in COMPETING_CLIENTS}
    end_time = time.time() + duration

    def run_iperf(client, cmd):
        """用 popen 运行 iperf，允许同一主机上多流并发。"""
        proc = client.popen(
            cmd, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        output, _ = proc.communicate()
        return output or ""

    def build_iperf_cmd(target_ip, port, protocol, target_bw):
        if protocol == "udp":
            # 不限速：让 UDP 与 TCP 公平竞争，由 HTB/pfifo 决定实际分配
            return f"iperf3 -c {target_ip} -p {port} -t {FLOW_DURATION} -u -b 0 -J 2>/dev/null"
        # TCP 不限速；stderr 重定向到 /dev/null，只保留 JSON stdout
        return f"iperf3 -c {target_ip} -p {port} -t {FLOW_DURATION} -J 2>/dev/null"

    def parse_flow_result(result, protocol):
        if protocol == "udp":
            return parse_udp_iperf_output(result)
        tp = parse_iperf_output(result)
        return {"throughput_mbps": tp} if tp is not None else None

    def run_client_poisson(client_name, desc, port, protocol, target_bw):
        """
        持续泊松到达：实验窗口内反复产生短流。
        使用 LoadBalancer 动态获取目标服务器。
        """
        host_name = CLIENT_HOSTS.get(client_name, client_name)
        client = hosts.get(host_name)
        if client is None:
            return
        flow_index = 0

        while time.time() < end_time:
            delay = random.expovariate(POISSON_LAMBDA[client_name])
            if time.time() + delay >= end_time:
                break
            time.sleep(delay)

            # 通过 LoadBalancer 动态获取目标服务器
            target_ip = load_balancer.get_server(client_name)
            cmd = build_iperf_cmd(target_ip, port, protocol, target_bw)
            flow_index += 1

            result = run_iperf(client, cmd)
            parsed = parse_flow_result(result, protocol)

            # 连接失败时重试一次（短暂等待后）
            if not parsed and (not result or "error" in result.lower()):
                time.sleep(1)
                result = run_iperf(client, cmd)
                parsed = parse_flow_result(result, protocol)

            with results_lock:
                if parsed:
                    flow_samples[client_name].append(parsed)
                    if protocol == "udp":
                        info(f"  [DONE] {desc} #{flow_index}: "
                             f"{parsed['throughput_mbps']:.2f} Mbps, "
                             f"抖动 {parsed['jitter_ms']:.2f} ms, "
                             f"丢包 {parsed['lost_percent']:.2f}%\n")
                    else:
                        info(f"  [DONE] {desc} #{flow_index}: "
                             f"{parsed['throughput_mbps']:.2f} Mbps\n")
                else:
                    info(f"  [DONE] {desc} #{flow_index}: 解析失败 "
                         f"(目标={target_ip}:{port}, 协议={protocol})\n")

    threads = []
    for client_spec in COMPETING_CLIENTS:
        client_name = client_spec[0]
        desc = client_spec[1]
        port = client_spec[3]
        protocol = client_spec[4]
        target_bw = client_spec[5]

        t = threading.Thread(
            target=run_client_poisson,
            args=(client_name, desc, port, protocol, target_bw),
            daemon=True
        )
        threads.append(t)

    random.shuffle(threads)

    info(f"[QOS_ABLATION] 启动 {len(threads)} 个客户端泊松流生成器，持续 {duration}s...\n")
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 汇总结果
    results = {}
    for client_spec in COMPETING_CLIENTS:
        client_name = client_spec[0]
        protocol = client_spec[4]
        samples = flow_samples.get(client_name, [])
        if not samples:
            results[client_name] = None
            continue

        results[client_name] = {
            "throughput_mbps": round(
                sum(s["throughput_mbps"] for s in samples) / len(samples), 2
            ),
            "flow_count": len(samples),
        }
        if protocol == "udp":
            results[client_name]["jitter_ms"] = round(
                sum(s["jitter_ms"] for s in samples) / len(samples), 2
            )
            results[client_name]["lost_percent"] = round(
                sum(s["lost_percent"] for s in samples) / len(samples), 2
            )

    info(f"[QOS_ABLATION] 所有客户端泊松流测试完成\n")
    return results


# ==================== 时延测量（拥塞期并发）====================

def run_latency_measurement(net, hosts, measure_after=2):
    """
    在拥塞期间测量各客户端到服务器的时延。
    使用 CLIENT_HOSTS 别名映射，确保 finance_probe 正确测到 finance1 的 RTT。
    """
    info("[QOS_ABLATION] 等待拥塞稳定后测量时延...\n")
    time.sleep(measure_after)

    results_lock = threading.Lock()
    latencies = {}

    def ping_one(client_name, desc):
        host_name = CLIENT_HOSTS.get(client_name, client_name)
        client = hosts.get(host_name)
        if client is None:
            return
        result = client.cmd(f"ping -c {PING_COUNT} -i {PING_INTERVAL} {SERVER1_IP}")
        rtt = parse_ping_output(result)
        with results_lock:
            latencies[client_name] = rtt
        if rtt is not None:
            info(f"  [PING] {desc}: 平均 {rtt:.2f} ms\n")
        else:
            info(f"  [PING] {desc}: 解析失败\n")

    threads = []
    measured_hosts = set()
    alias_clients = []

    for client_spec in COMPETING_CLIENTS:
        client_name = client_spec[0]
        desc = client_spec[1]
        host_name = CLIENT_HOSTS.get(client_name, client_name)
        if host_name in measured_hosts:
            alias_clients.append((client_name, host_name, desc))
            continue
        measured_hosts.add(host_name)
        t = threading.Thread(target=ping_one, args=(client_name, desc), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # 别名客户端复用同一主机的 RTT
    for client_name, host_name, desc in alias_clients:
        latencies[client_name] = latencies.get(host_name)
        if latencies[client_name] is not None:
            info(f"  [PING] {desc}: 复用 {host_name} RTT {latencies[client_name]:.2f} ms\n")

    return latencies


def run_competition_with_latency(net, hosts, duration):
    """同时运行竞争流量和 ping，确保 RTT 测到的是拥塞期数据。"""
    traffic_results = {}

    # 在开始之前检查网络连通性
    server1, server2 = get_server_hosts(hosts)
    if server1 and server2:
        # 从任意客户端主机 ping 服务器，确保路由正常
        test_client = hosts.get("dorm1")
        if test_client:
            info("[QOS_ABLATION] 检查网络连通性...\n")
            result = test_client.cmd(f"ping -c 2 {SERVER1_IP} 2>&1")
            if "0% packet loss" in result or "0 packets lost" in result:
                info("[QOS_ABLATION] ✓ 网络连通性正常\n")
            else:
                info("[QOS_ABLATION] ⚠ 网络连通性异常，可能导致 iperf3 失败\n")
                info(f"[QOS_ABLATION] Ping 结果: {result[:200]}\n")

    def traffic_worker():
        nonlocal traffic_results
        traffic_results = run_competitive_measurement(net, hosts, duration)

    traffic_thread = threading.Thread(target=traffic_worker, daemon=True)
    traffic_thread.start()

    latency_results = run_latency_measurement(net, hosts, measure_after=2)
    traffic_thread.join()

    return traffic_results, latency_results


# ==================== 单策略实验 ====================

def run_single_policy_experiment(policy_type, label):
    """运行单个 QoS 策略实验。"""
    info(f"\n{'='*60}\n")
    info(f"  实验: {label}\n")
    info(f"{'='*60}\n")

    net, r1, hosts = setup_network_for_policy(policy_type)

    try:
        traffic_results, latency_results = run_competition_with_latency(
            net, hosts, TOTAL_EXPERIMENT_TIME
        )
    finally:
        net.stop()

    # 汇总为聚合格式
    aggregated = {}
    for client_spec in COMPETING_CLIENTS:
        client_name = client_spec[0]
        tp = traffic_results.get(client_name)
        lat = latency_results.get(client_name)

        if tp is not None:
            aggregated[client_name] = {
                "throughput_mbps": tp["throughput_mbps"],
                "rtt_ms": round(lat, 2) if lat is not None else 0,
                "jitter_ms": tp.get("jitter_ms"),
                "lost_percent": tp.get("lost_percent"),
            }
        else:
            aggregated[client_name] = {
                "throughput_mbps": 0,
                "rtt_ms": round(lat, 2) if lat is not None else 0,
                "jitter_ms": None,
                "lost_percent": None,
            }

    return aggregated, label


# ==================== 主入口 ====================

def run_qos_ablation(server_ip="10.0.100.2", duration=None, scenario="B"):
    """
    运行 QoS 消融实验。

    对比:
      1. Baseline (pfifo) — 代表 Final − QoS
      2. HTB QoS — 代表 Final

    参数:
        scenario: "A"=中等均衡负载, "B"=Server1 高负载不均 (默认 B)
    """
    scenario = scenario.upper()
    if scenario not in ("A", "B"):
        scenario = "B"
    _set_qos_scenario(scenario)

    if duration is not None:
        global TOTAL_EXPERIMENT_TIME
        TOTAL_EXPERIMENT_TIME = duration

    ensure_dirs()

    # 打印场景信息
    s1_lambda = POISSON_LAMBDA.get("finance1", 0) + POISSON_LAMBDA.get("teach1", 0) + \
                POISSON_LAMBDA.get("office1", 0) + POISSON_LAMBDA.get("finance_probe", 0)
    s2_lambda = POISSON_LAMBDA.get("dorm1", 0) + POISSON_LAMBDA.get("lib1", 0)
    info(f"[QOS_ABLATION] ====== 场景 {scenario} ======\n")
    if scenario == "A":
        info("[QOS_ABLATION] 负载模式: S1/S2 双侧中等负载 — HTB 不触发，消融前后差异应极小（对照基线）\n")
    else:
        info("[QOS_ABLATION] 负载模式: Server1 高负载 — S1 产生拥塞，HTB 保障财务处关键业务\n")
    info(f"[QOS_ABLATION] λ 参数: finance1={POISSON_LAMBDA['finance1']}, "
         f"teach1={POISSON_LAMBDA['teach1']}, office1={POISSON_LAMBDA['office1']}, "
         f"dorm1={POISSON_LAMBDA['dorm1']}, lib1={POISSON_LAMBDA['lib1']}, "
         f"probe={POISSON_LAMBDA['finance_probe']}\n")
    info(f"[QOS_ABLATION] S1 λ 合计={s1_lambda:.2f}, S2 λ 合计={s2_lambda:.2f}, "
         f"总 λ={s1_lambda+s2_lambda:.2f}\n")
    info(f"[QOS_ABLATION] 流持续时间={FLOW_DURATION}s, 实验时长={TOTAL_EXPERIMENT_TIME}s\n")

    # 实验组 1: Final − QoS (Baseline)
    baseline_data, baseline_label = run_single_policy_experiment(
        "baseline", "Final − QoS (Baseline/pfifo)"
    )

    # 清理
    import os as _os
    _os.system("mn -c 2>/dev/null")
    time.sleep(2)

    # 实验组 2: Final (HTB QoS)
    htb_data, htb_label = run_single_policy_experiment(
        "htb", "Final (HTB QoS)"
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

        b_tp = b.get("throughput_mbps", 0) if b else 0
        b_rtt = b.get("rtt_ms", 0) if b else 0
        b_jit = b.get("jitter_ms") if b else None
        b_loss = b.get("lost_percent") if b else None

        h_tp = h.get("throughput_mbps", 0) if h else 0
        h_rtt = h.get("rtt_ms", 0) if h else 0
        h_jit = h.get("jitter_ms") if h else None
        h_loss = h.get("lost_percent") if h else None

        protocol = "tcp"
        for spec in COMPETING_CLIENTS:
            if spec[0] == client_key:
                protocol = spec[5]
                break

        info(f"[Final HTB消融] {label:<20} {protocol:<6} "
             f"{b_tp:<14.2f} {b_rtt:<12.2f} "
             f"{b_jit if b_jit is not None else 'N/A':<12} "
             f"{b_loss if b_loss is not None else 'N/A':<12}\n")

        info(f"[Final]        {label:<20} {protocol:<6} "
             f"{h_tp:<14.2f} {h_rtt:<12.2f} "
             f"{h_jit if h_jit is not None else 'N/A':<12} "
             f"{h_loss if h_loss is not None else 'N/A':<12}\n")
        info("-" * 90 + "\n")

        csv_rows.append([
            f"[Final HTB消融] {label}", protocol,
            b_tp, b_rtt,
            b_jit if b_jit is not None else "N/A",
            b_loss if b_loss is not None else "N/A",
        ])
        csv_rows.append([
            f"[Final] {label}", protocol,
            h_tp, h_rtt,
            h_jit if h_jit is not None else "N/A",
            h_loss if h_loss is not None else "N/A",
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
