"""
experiments/run_lb_debug.py — 实验二调试版：纯 Round Robin 收益验证

目的：
  在纯净网络（无 QoS、无安全策略、无额外 HTB 瓶颈）上，
  仅对比 Static 绑定 vs Round Robin 是否带来吞吐/时延收益。

架构：
  CampusNet + 双服务器 + 双独立链路（对称，拓扑带宽各 100Mbps）

对比组：
  A: Static（按区域分工：S1←finance/teach/office, S2←dorm/lib）
  B: Round Robin（轮询均匀分配）
  C: Random（50% 随机选择，用于诊断：区分 RR 实现问题 vs 切换开销问题）

诊断逻辑：
  若 Random ≈ RR 且都差于 Static → 问题在"交替切换服务器"本身（TCP 慢启动惩罚）
  若 Random ≈ Static 且都好于 RR → RR 实现有问题
  若三者相近 → 负载均衡在此架构下无显著收益

已关闭：
  ✗ QoS（不调用 apply_htb_policy / apply_baseline_policy）
  ✗ 安全策略（iptables -F/-X，全部 ACCEPT）
  ✗ 服务器链路额外 HTB 瓶颈
  ✗ 所有额外 tc qdisc（TCLink 自带的拓扑级 HTB 保留，仅不叠加新策略）

注意：TCLink 在链路两端自动配置 HTB，用于实施拓扑定义的带宽/时延，
这些是拓扑的一部分，不属于"额外 QoS"。sch_htb quantum 警告可安全忽略。

验证逻辑：
  若 RR 在此纯净环境下表现优于 Static，说明 RR 机制本身正确；
  若仍表现异常，则问题在于拓扑/路由/调度器本身而非 QoS 或安全干扰。
"""

import time
import sys
import os
import random
import threading
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mininet.log import info

from utils import save_to_csv, save_to_json, print_separator, timestamp, ensure_dirs
from core.topology import (
    create_fresh_network,
    SERVER1_IP,
    SERVER2_IP,
    SERVER1_INTF,
    SERVER2_INTF,
    ZONE_UPLINKS,
    ROUTER_IPS,
)
from core.server_cluster import get_server_hosts, DEFAULT_STATIC_MAPPING
from services.web import start_web_server, create_test_file
from policies.load_balance import LoadBalancer


# ==================== 实验参数 ====================

LOAD_FILE_MB = 3            # 默认下载文件大小（小文件模式）
LARGE_FILE_MB = 15          # 大文件模式：减少慢启动占比
BIGFILE_URL = "/lbfile.bin"
EXPERIMENT_DURATION = 60    # 请求生成持续时间（秒）

# 静态映射（与 DEFAULT_STATIC_MAPPING 一致）：
#   Server1：财务处、教学楼、办公楼
#   Server2：宿舍区、图书馆
DEBUG_STATIC_MAPPING = {
    "finance1": SERVER1_IP,   # λ=0.8
    "teach1":   SERVER1_IP,   # λ=0.5
    "office1":  SERVER1_IP,   # λ=0.4
    "dorm1":    SERVER2_IP,   # λ=1.0
    "lib1":     SERVER2_IP,   # λ=0.5
}
# Server1 λ 合计 = 0.8 + 0.5 + 0.4 = 1.7 (53%)
# Server2 λ 合计 = 1.0 + 0.5       = 1.5 (47%)

CLIENT_NODES = [
    ("dorm1",    "宿舍区 (热点)"),
    ("lib1",     "图书馆 (热点)"),
    ("office1",  "办公楼 (热点)"),
    ("finance1", "财务处 (普通)"),
    ("teach1",   "教学楼 (普通)"),
]

LOAD_LAMBDA = {
    "finance1": 0.8, "teach1": 0.5, "office1": 0.4,
    "dorm1": 1.0, "lib1": 0.5,
}

SERVER_LABELS = {SERVER1_IP: "Server1", SERVER2_IP: "Server2"}


# ==================== 网络净化 ====================

def sanitize_network(r1):
    """
    将网络恢复为最纯净状态（不破坏 TCLink 自带的 qdisc）：
      1. 仅查看 tc qdisc 状态（只读，不删除——TCLink 依赖自带 HTB 维持链路）
      2. 清除 iptables 所有规则
      3. 确保 IP 转发开启

    注意：TCLink 在链路两端自动配置 HTB qdisc 用于拓扑带宽/时延整形，
    这些是拓扑的一部分，不应删除。本实验的"无 QoS"指的是不在此之上
    叠加额外的 HTB/prio/sfq 策略。
    """
    info("[DEBUG] === 网络净化开始 ===\n")

    # --- 查看 TC 状态（只读，不修改）---
    all_intfs = list(ROUTER_IPS.keys())
    info("[DEBUG]   === 当前 tc qdisc 状态（TCLink 自带，保留） ===\n")
    for intf in all_intfs:
        out = r1.cmd(f"tc qdisc show dev {intf} 2>/dev/null").strip()
        if out:
            # 截断过长的输出
            info(f"[DEBUG]     {intf}: {out[:120]}{'...' if len(out) > 120 else ''}\n")

    # --- 清除 iptables ---
    r1.cmd("iptables -F 2>/dev/null || true")
    r1.cmd("iptables -X 2>/dev/null || true")
    r1.cmd("iptables -t nat -F 2>/dev/null || true")
    r1.cmd("iptables -t mangle -F 2>/dev/null || true")
    r1.cmd("iptables -P INPUT ACCEPT")
    r1.cmd("iptables -P OUTPUT ACCEPT")
    r1.cmd("iptables -P FORWARD ACCEPT")
    info("[DEBUG]   iptables 已清空，所有链默认 ACCEPT\n")

    # --- 确保 IP 转发 ---
    r1.cmd("sysctl -w net.ipv4.ip_forward=1 2>/dev/null || true")
    info("[DEBUG]   ip_forward 已启用\n")

    info("[DEBUG] === 网络净化完成（TCLink qdisc 保留不动） ===\n")


# ==================== 流量生成 ====================

def parse_curl_output(output):
    """解析 curl -w 输出。"""
    try:
        parts = output.strip().split("\t")
        if len(parts) >= 3:
            return int(parts[0]), float(parts[1]), int(float(parts[2]))
        if len(parts) >= 2:
            return int(parts[0]), float(parts[1]), 0
    except (ValueError, IndexError):
        pass
    return None, None, 0


def generate_traffic(net, hosts, balancer, duration=60, max_wait=180):
    """生成泊松到达 HTTP 下载流量。"""
    balancer.reset()
    results = []
    processes = []
    lock = threading.Lock()
    request_counter = {"value": 0}

    start_time = time.time()
    end_time = start_time + duration

    def spawn_request(client_name, desc):
        target_ip = balancer.get_server(client_name)
        with lock:
            request_counter["value"] += 1
            req_id = request_counter["value"]

        client = hosts.get(client_name)
        if client is None:
            return

        url = f"http://{target_ip}{BIGFILE_URL}"
        cmd = (f"curl -o /dev/null -s "
               f"-w '%{{http_code}}\\t%{{time_total}}\\t%{{size_download}}' "
               f"'{url}' --connect-timeout 10 --max-time 60")
        proc = client.popen(cmd, shell=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
        with lock:
            processes.append({
                "req_id": req_id, "client": client_name, "desc": desc,
                "target_ip": target_ip,
                "server": SERVER_LABELS.get(target_ip, target_ip),
                "proc": proc,
                "arrival_time": time.time() - start_time,
            })

    def client_generator(client_name, desc):
        lambda_rate = LOAD_LAMBDA[client_name]
        generated = 0
        while time.time() < end_time:
            delay = random.expovariate(lambda_rate)
            if time.time() + delay >= end_time:
                break
            time.sleep(delay)
            spawn_request(client_name, desc)
            generated += 1
        info(f"[DEBUG]   {desc} 生成 {generated} 个泊松请求 (λ={lambda_rate})\n")

    # 启动所有生成器线程
    generators = []
    for client_name, desc in CLIENT_NODES:
        t = threading.Thread(target=client_generator, args=(client_name, desc), daemon=True)
        generators.append(t)
        t.start()

    info(f"[DEBUG]   动态请求生成中：持续 {duration}s\n")

    for t in generators:
        t.join()

    with lock:
        total_requests = len(processes)
        process_items = list(processes)
    info(f"[DEBUG]   请求生成结束，共 {total_requests} 个，等待完成...\n")

    # 收集结果
    deadline = time.time() + max_wait
    completed = 0
    for item in process_items:
        proc = item["proc"]
        timeout = max(0.1, deadline - time.time())
        try:
            output, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            output, _ = proc.communicate()

        http_code, resp_time, bytes_downloaded = parse_curl_output(output or "")
        success = (http_code == 200)
        results.append({
            "request_id": item["req_id"], "client": item["client"],
            "desc": item["desc"], "target_ip": item["target_ip"],
            "server": item["server"], "arrival_time": item["arrival_time"],
            "http_code": http_code, "success": success,
            "resp_time": resp_time if success else None,
            "bytes": bytes_downloaded if success else 0,
        })
        completed += 1
        if completed % 50 == 0 or completed == total_requests:
            info(f"[DEBUG]   完成收集: {completed}/{total_requests}\n")

    elapsed = time.time() - start_time
    return results, elapsed


# ==================== 统计计算 ====================

def compute_statistics(results, elapsed, algo_name):
    """计算统计指标。"""
    total = len(results)
    successful = [r for r in results if r["success"]]
    failed = total - len(successful)

    resp_times = [r["resp_time"] for r in successful if r["resp_time"] is not None]
    avg_resp_time = sum(resp_times) / len(resp_times) if resp_times else 0.0
    # P50 / P95 更能反映尾延迟
    sorted_times = sorted(resp_times) if resp_times else [0]
    p50 = sorted_times[len(sorted_times) // 2] if sorted_times else 0
    p95_idx = int(len(sorted_times) * 0.95)
    p95 = sorted_times[min(p95_idx, len(sorted_times) - 1)] if sorted_times else 0

    total_bytes = sum(r["bytes"] for r in successful)
    total_throughput = (total_bytes * 8 / elapsed) / 1_000_000 if elapsed > 0 else 0.0

    s1_count = sum(1 for r in results if r["target_ip"] == SERVER1_IP)
    s2_count = sum(1 for r in results if r["target_ip"] == SERVER2_IP)
    s1_bytes = sum(r["bytes"] for r in successful if r["target_ip"] == SERVER1_IP)
    s2_bytes = sum(r["bytes"] for r in successful if r["target_ip"] == SERVER2_IP)

    s1_share = s1_bytes / total_bytes if total_bytes > 0 else 0
    s2_share = s2_bytes / total_bytes if total_bytes > 0 else 0
    mean = (s1_share + s2_share) / 2
    variance = ((s1_share - mean) ** 2 + (s2_share - mean) ** 2) / 2

    loads = [s1_bytes, s2_bytes]
    sq_sum = sum(x * x for x in loads)
    jain = (sum(loads) ** 2) / (len(loads) * sq_sum) if sq_sum > 0 else 0

    return {
        "algorithm": algo_name,
        "total_requests": total,
        "successful": len(successful),
        "failed": failed,
        "avg_resp_time": round(avg_resp_time, 4),
        "p50_resp_time": round(p50, 4),
        "p95_resp_time": round(p95, 4),
        "total_throughput": round(total_throughput, 2),
        "server1_count": s1_count,
        "server2_count": s2_count,
        "server1_traffic_pct": round(s1_share * 100, 1),
        "server2_traffic_pct": round(s2_share * 100, 1),
        "load_variance": round(variance, 4),
        "jain_index": round(jain, 4),
    }


# ==================== 单次实验运行 ====================

def run_single_experiment(algorithm, algo_label, duration=60, file_size_mb=LOAD_FILE_MB):
    """在独立 Mininet 实例中运行一种调度策略。"""
    import os as _os
    _os.system("mn -c 2>/dev/null")

    net, r1, hosts, switches = create_fresh_network()
    server1, server2 = get_server_hosts(hosts)

    # --- 网络净化 ---
    sanitize_network(r1)

    # --- 连通性快速诊断 ---
    info("[DEBUG] === S1/S2 连通性诊断 ===\n")
    test_client = hosts.get("dorm1")
    if test_client:
        for label, ip in [("S1", SERVER1_IP), ("S2", SERVER2_IP)]:
            out = test_client.cmd(f"ping -c 2 -W 2 {ip}")
            loss = "0% packet loss" in out or " 0% packet loss" in out
            info(f"[DEBUG]   ping {label}({ip}): {'通' if loss else '不通'}\n")
    info("[DEBUG] === 诊断结束 ===\n")

    # --- 启动 Web 服务 ---
    if server1:
        start_web_server(server1)
        create_test_file(server1, "lbfile.bin", file_size_mb)
    if server2:
        start_web_server(server2)
        create_test_file(server2, "lbfile.bin", file_size_mb)

    # --- 调度器 ---
    static_map = DEBUG_STATIC_MAPPING if algorithm == "static" else None
    balancer = LoadBalancer(algorithm=algorithm, static_mapping=static_map)

    info(f"\n[DEBUG] === 开始 {algo_label} (文件={file_size_mb}MB) ===\n")
    if algorithm == "static":
        info(f"[DEBUG]   静态映射: S1 ← finance1/teach1/office1 (λ=1.7), "
             f"S2 ← dorm1/lib1 (λ=1.5)\n")

    results, elapsed = generate_traffic(net, hosts, balancer, duration=duration)
    stats = compute_statistics(results, elapsed, algo_label)

    info(f"[DEBUG] {algo_label} 完成: 耗时 {elapsed:.1f}s, "
         f"成功 {stats['successful']}/{stats['total_requests']}\n")

    net.stop()
    return stats


# ==================== 主实验入口 ====================

def run_lb_debug(duration=60):
    """
    调试实验：仅对比 Static vs Round Robin，无 QoS、无安全策略。

    两组实验在完全相同的纯净网络条件下运行，唯一变量是调度策略。
    """
    ensure_dirs()
    print_separator("负载均衡调试实验 — Static vs Round Robin（纯净网络）", 70)

    info("[DEBUG] 实验条件:\n")
    info("[DEBUG]   - 双服务器 + 双独立链路（拓扑带宽各 100Mbps，无额外 HTB）\n")
    info("[DEBUG]   - 无 QoS 策略\n")
    info("[DEBUG]   - 无安全策略（iptables 清空）\n")
    info("[DEBUG]   - Static: S1←finance/teach/office(λ=1.7), S2←dorm/lib(λ=1.5) 区域分工\n")
    info("[DEBUG]   - Round Robin: 轮询均匀分配\n")
    info(f"[DEBUG]   - 文件大小: {LOAD_FILE_MB}MB, 持续时间: {duration}s\n\n")

    # === 实验 A: Static ===
    static_stats = run_single_experiment("static", "Static(区域分工)", duration)

    import os as _os
    _os.system("mn -c 2>/dev/null")
    time.sleep(2)

    # === 实验 B: Round Robin ===
    rr_stats = run_single_experiment("round_robin", "Round Robin", duration)

    _os.system("mn -c 2>/dev/null")
    time.sleep(2)

    # === 实验 C: Random (50% 随机) ===
    random_stats = run_single_experiment("random", "Random(50%随机)", duration)

    # === 输出对比 ===
    print_separator("调试实验结果", 70)

    header = (f"{'调度策略':<24} {'请求数':<8} {'成功':<6} {'失败':<6} "
              f"{'平均响应(s)':<14} {'P50(s)':<10} {'P95(s)':<10} "
              f"{'吞吐量(Mbps)':<14} {'S1流量':<10} {'S2流量':<10} "
              f"{'Jain指数':<10}")
    info(header + "\n")
    info("-" * 130 + "\n")

    for s in [static_stats, rr_stats, random_stats]:
        info(f"{s['algorithm']:<24} "
             f"{s['total_requests']:<8} "
             f"{s['successful']:<6} "
             f"{s['failed']:<6} "
             f"{s['avg_resp_time']:<14.4f} "
             f"{s['p50_resp_time']:<10.4f} "
             f"{s['p95_resp_time']:<10.4f} "
             f"{s['total_throughput']:<14.2f} "
             f"{s['server1_traffic_pct']}%{'':<6} "
             f"{s['server2_traffic_pct']}%{'':<6} "
             f"{s['jain_index']:<10.4f}\n")

    # === 收益分析 ===
    print_separator("收益分析", 70)
    if static_stats["successful"] > 0 and rr_stats["successful"] > 0 and random_stats["successful"] > 0:
        info(f"  Static:     {static_stats['avg_resp_time']:.4f}s / {static_stats['total_throughput']:.2f} Mbps\n")
        info(f"  RoundRobin: {rr_stats['avg_resp_time']:.4f}s / {rr_stats['total_throughput']:.2f} Mbps\n")
        info(f"  Random:     {random_stats['avg_resp_time']:.4f}s / {random_stats['total_throughput']:.2f} Mbps\n\n")

        # 诊断逻辑
        rr_worse_than_static = rr_stats["avg_resp_time"] > static_stats["avg_resp_time"]
        random_worse_than_static = random_stats["avg_resp_time"] > static_stats["avg_resp_time"]
        rr_close_to_random = abs(rr_stats["avg_resp_time"] - random_stats["avg_resp_time"]) < 2.0

        if rr_close_to_random and rr_worse_than_static and random_worse_than_static:
            info("  📌 诊断结论: Random ≈ RR，且都差于 Static\n")
            info("     → 问题不在 RR 实现，在「交替切换目标服务器」本身\n")
            info("     → 根因推测: 每次切换 IP 触发新 TCP 连接 + 慢启动惩罚\n")
        elif rr_worse_than_static and not random_worse_than_static:
            info("  📌 诊断结论: Random ≈ Static，但 RR 更差\n")
            info("     → RR 实现可能有问题（虽然线程安全但调度模式不佳）\n")
        elif not rr_worse_than_static:
            info("  📌 诊断结论: RR 不差于 Static\n")
            info("     → 之前的问题可能已修复，或与特定实验条件相关\n")
        else:
            info("  📌 诊断结论: 无明确模式，需进一步分析\n")
    else:
        info("  ❌ 实验数据不足，无法分析\n")

    # === 保存结果 ===
    ts = timestamp()
    csv_rows = []
    for s in [static_stats, rr_stats, random_stats]:
        csv_rows.append([
            s["algorithm"], s["total_requests"], s["successful"], s["failed"],
            s["avg_resp_time"], s["p50_resp_time"], s["p95_resp_time"],
            s["total_throughput"],
            f"{s['server1_traffic_pct']}%", f"{s['server2_traffic_pct']}%",
            s["load_variance"], s["jain_index"],
        ])

    save_to_csv(
        f"lb_debug_{ts}.csv",
        ["调度策略", "请求数", "成功", "失败",
         "平均响应(s)", "P50(s)", "P95(s)", "吞吐量(Mbps)",
         "S1流量", "S2流量", "负载方差", "Jain指数"],
        csv_rows,
    )
    save_to_json(
        f"lb_debug_{ts}.json",
        {
            "实验类型": "负载均衡调试实验 — 纯净网络 Static vs RR",
            "架构": "双服务器 + 双独立链路（拓扑带宽各100Mbps，无额外HTB瓶颈）",
            "网络状态": "无QoS、无安全策略、tc qdisc已清除",
            "Static映射": {k: SERVER_LABELS.get(v, v) for k, v in DEBUG_STATIC_MAPPING.items()},
            "区域分工": "Server1←finance/teach/office, Server2←dorm/lib",
            "到达率": LOAD_LAMBDA,
            "文件大小_MB": LOAD_FILE_MB,
            "持续时间_s": duration,
            "static": static_stats,
            "round_robin": rr_stats,
            "random": random_stats,
        },
        subdir="load_balance",
    )

    info(f"\n[DEBUG] 实验完成！结果已保存\n")
    return csv_rows


def run_lb_debug_large(duration=60):
    """
    大文件版调试实验：15MB 文件替换 3MB。

    目的：验证 TCP 慢启动假说。
      - 小文件（3MB）：慢启动占传输时间比重大 → RR 频繁切换惩罚明显
      - 大文件（15MB）：慢启动占比小 → 若 RR 与 Static 差距缩小，
        则证实慢启动是根因；若差距不变，则问题在其他地方。

    仅对比 Static vs RR（两组，节省时间）。
    """
    ensure_dirs()
    print_separator("负载均衡调试实验 — 大文件模式 Static vs RR（15MB）", 70)

    info("[DEBUG-LARGE] 实验条件:\n")
    info("[DEBUG-LARGE]   - 双服务器 + 双独立链路（拓扑带宽各 100Mbps）\n")
    info("[DEBUG-LARGE]   - 无 QoS、无安全策略\n")
    info(f"[DEBUG-LARGE]   - 文件大小: {LARGE_FILE_MB}MB（vs 默认 {LOAD_FILE_MB}MB）\n")
    info("[DEBUG-LARGE]   - 假设: 大文件使慢启动占比下降 → RR/Static 差距应缩小\n")
    info(f"[DEBUG-LARGE]   - 持续时间: {duration}s\n\n")

    # === 实验 A: Static ===
    static_stats = run_single_experiment("static", "Static(区域分工)", duration, LARGE_FILE_MB)

    import os as _os
    _os.system("mn -c 2>/dev/null")
    time.sleep(2)

    # === 实验 B: Round Robin ===
    rr_stats = run_single_experiment("round_robin", "Round Robin", duration, LARGE_FILE_MB)

    # === 输出对比 ===
    print_separator("大文件模式实验结果", 70)

    header = (f"{'调度策略':<24} {'请求数':<8} {'成功':<6} {'失败':<6} "
              f"{'平均响应(s)':<14} {'P50(s)':<10} {'P95(s)':<10} "
              f"{'吞吐量(Mbps)':<14} {'S1流量':<10} {'S2流量':<10} "
              f"{'Jain指数':<10}")
    info(header + "\n")
    info("-" * 130 + "\n")

    for s in [static_stats, rr_stats]:
        info(f"{s['algorithm']:<24} "
             f"{s['total_requests']:<8} "
             f"{s['successful']:<6} "
             f"{s['failed']:<6} "
             f"{s['avg_resp_time']:<14.4f} "
             f"{s['p50_resp_time']:<10.4f} "
             f"{s['p95_resp_time']:<10.4f} "
             f"{s['total_throughput']:<14.2f} "
             f"{s['server1_traffic_pct']}%{'':<6} "
             f"{s['server2_traffic_pct']}%{'':<6} "
             f"{s['jain_index']:<10.4f}\n")

    # === 收益分析 ===
    print_separator("收益分析（大文件模式）", 70)
    if static_stats["successful"] > 0 and rr_stats["successful"] > 0:
        resp_diff_pct = (
            (rr_stats["avg_resp_time"] - static_stats["avg_resp_time"])
            / static_stats["avg_resp_time"] * 100
        )
        tp_diff_pct = (
            (rr_stats["total_throughput"] - static_stats["total_throughput"])
            / static_stats["total_throughput"] * 100
        )
        info(f"  Static:       {static_stats['avg_resp_time']:.4f}s / {static_stats['total_throughput']:.2f} Mbps\n")
        info(f"  Round Robin:  {rr_stats['avg_resp_time']:.4f}s / {rr_stats['total_throughput']:.2f} Mbps\n")
        info(f"  响应时延差异: {'+' if resp_diff_pct > 0 else ''}{resp_diff_pct:.1f}%\n")
        info(f"  吞吐量差异:   {'+' if tp_diff_pct > 0 else ''}{tp_diff_pct:.1f}%\n\n")

        # 对比之前 3MB 的结果给出判断
        info("  📌 与之前 3MB 实验对比:\n")
        info("     3MB 结果: RR 响应 +37%、吞吐 -6%\n")
        info(f"     15MB 结果: RR 响应 {'+' if resp_diff_pct > 0 else ''}{resp_diff_pct:.1f}%、吞吐 {'+' if tp_diff_pct > 0 else ''}{tp_diff_pct:.1f}%\n")
        if resp_diff_pct < 20:
            info("     → 差距大幅缩小！证实 TCP 慢启动是主因 ✅\n")
        elif resp_diff_pct < 30:
            info("     → 差距有所缩小，慢启动是部分原因\n")
        else:
            info("     → 差距未缩小，慢启动假说不成立，需排查其他原因\n")
    else:
        info("  ❌ 实验数据不足\n")

    # === 保存 ===
    ts = timestamp()
    csv_rows = []
    for s in [static_stats, rr_stats]:
        csv_rows.append([
            s["algorithm"], s["total_requests"], s["successful"], s["failed"],
            s["avg_resp_time"], s["p50_resp_time"], s["p95_resp_time"],
            s["total_throughput"],
            f"{s['server1_traffic_pct']}%", f"{s['server2_traffic_pct']}%",
            s["load_variance"], s["jain_index"],
        ])

    save_to_csv(
        f"lb_debug_large_{ts}.csv",
        ["调度策略", "请求数", "成功", "失败",
         "平均响应(s)", "P50(s)", "P95(s)", "吞吐量(Mbps)",
         "S1流量", "S2流量", "负载方差", "Jain指数"],
        csv_rows,
    )
    save_to_json(
        f"lb_debug_large_{ts}.json",
        {
            "实验类型": "负载均衡调试实验 — 大文件模式 Static vs RR",
            "架构": "双服务器 + 双独立链路（拓扑带宽各100Mbps）",
            "文件大小_MB": LARGE_FILE_MB,
            "对比基线": "3MB 实验中 RR 响应 +37%、吞吐 -6%",
            "static": static_stats,
            "round_robin": rr_stats,
        },
        subdir="load_balance",
    )

    info(f"\n[DEBUG-LARGE] 大文件实验完成！结果已保存\n")
    return csv_rows


if __name__ == "__main__":
    import sys
    if "--large" in sys.argv:
        run_lb_debug_large()
    else:
        run_lb_debug()
