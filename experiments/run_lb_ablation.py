"""
experiments/run_lb_ablation.py — 实验二：负载均衡消融实验

实验设计:
  Final（QoS + LB + Security） vs  Final − LB（QoS + Security）

实验场景——故意制造服务器负载失衡：
  静态绑定模式下，4/5 的客户端被绑定到 Server1，仅 1/5 绑定到 Server2。
  Server1 总请求率 λ=2.4（过载），Server2 总 λ=0.8（中等负载）。

  在此失衡场景下考察：
    1. 无 LB（静态绑定）：Server1 过载 → 响应时延高、吞吐受限
    2. 有 LB（Round Robin）：请求轮流分配 → 50:50 均衡 → 响应降低、吞吐提升

对比指标:
  - 服务器负载分布（预期 Static 75:25, RR 50:50）
  - 系统吞吐量
  - 响应时延
  - Jain 公平指数
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

from core.topology import create_fresh_network, SERVER1_IP, SERVER2_IP
from core.server_cluster import get_server_hosts
from services.web import start_web_server, create_test_file
from security.acl import (
    apply_stateful_firewall, apply_acl_policies, apply_default_accept
)
from security.intrusion import apply_intrusion_detection
from security.audit_db import init_db
from policies.qos import apply_baseline_policy
from policies.load_balance import LoadBalancer


LOAD_FILE_MB = 2
BIGFILE_URL = "/lbfile.bin"

# ==================== 负载均衡消融实验专用静态映射 ====================
#
# 设计意图：故意制造服务器负载失衡。
#   - 4 个客户端（dorm1/lib1/teach1/office1）绑到 Server1
#   - 1 个客户端（finance1）绑到 Server2
#   - Server1 总请求率 λ=2.4（过载），Server2 总 λ=0.8（中等）
#
# 在这个失衡场景下：
#   Static 模式 → Server1 严重过载，响应时延高
#   RR 模式    → 请求均匀分配，显著改善响应时延
#
LB_STATIC_MAPPING = {
    "dorm1": SERVER1_IP,      # λ=1.0  最高请求率，压到过载端
    "lib1": SERVER1_IP,       # λ=0.5
    "teach1": SERVER1_IP,     # λ=0.5
    "office1": SERVER1_IP,    # λ=0.4
    "finance1": SERVER2_IP,   # λ=0.8  唯一分到轻载端
}
# Server1 λ 合计 = 1.0 + 0.5 + 0.5 + 0.4 = 2.4 (75%)
# Server2 λ 合计 = 0.8 (25%)

CLIENT_NODES = [
    ("dorm1", "宿舍区 (热点)"),
    ("lib1", "图书馆 (热点)"),
    ("office1", "办公楼 (热点)"),
    ("finance1", "财务处 (普通)"),
    ("teach1", "教学楼 (普通)"),
]

LOAD_LAMBDA = {
    "finance1": 0.8, "teach1": 0.5, "office1": 0.4,
    "dorm1": 1.0, "lib1": 0.5,
}

SERVER_LABELS = {SERVER1_IP: "Server1", SERVER2_IP: "Server2"}
SERVERS = [SERVER1_IP, SERVER2_IP]


def parse_curl_output(output):
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
    """生成泊松到达的 HTTP 下载流量。"""
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
               f"-w '%{{http_code}}\\t%{{time_total}}\\t%{{size_download}}' '{url}'")
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
        info(f"[LB_ABLATION]   {desc} 生成 {generated} 个泊松请求\n")

    # 启动所有生成器
    generators = []
    for client_name, desc in CLIENT_NODES:
        t = threading.Thread(target=client_generator, args=(client_name, desc), daemon=True)
        generators.append(t)
        t.start()

    info(f"[LB_ABLATION]   动态请求生成中：持续 {duration}s\n")

    for t in generators:
        t.join()

    with lock:
        total_requests = len(processes)
        process_items = list(processes)
    info(f"[LB_ABLATION]   请求生成结束，共 {total_requests} 个，等待完成...\n")

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
            info(f"[LB_ABLATION]   完成收集: {completed}/{total_requests}\n")

    elapsed = time.time() - start_time
    return results, elapsed


def compute_statistics(results, elapsed, algo_name):
    """计算统计指标。"""
    total = len(results)
    successful = [r for r in results if r["success"]]

    resp_times = [r["resp_time"] for r in successful if r["resp_time"] is not None]
    avg_resp_time = sum(resp_times) / len(resp_times) if resp_times else 0.0

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
        "completed_requests": len(successful),
        "avg_resp_time": round(avg_resp_time, 4),
        "total_throughput": round(total_throughput, 2),
        "server1_count": s1_count,
        "server2_count": s2_count,
        "server1_traffic_pct": round(s1_share * 100, 1),
        "server2_traffic_pct": round(s2_share * 100, 1),
        "load_variance": round(variance, 4),
        "jain_index": round(jain, 4),
    }


def run_single_lb_experiment(algorithm, algo_label, duration=60):
    """运行单个负载均衡策略实验。"""
    import os as _os
    _os.system("mn -c 2>/dev/null")

    net, r1, hosts, switches = create_fresh_network()
    server1, server2 = get_server_hosts(hosts)

    # 准备测试文件
    if server1:
        start_web_server(server1)
        create_test_file(server1, "lbfile.bin", LOAD_FILE_MB)
    if server2:
        start_web_server(server2)
        create_test_file(server2, "lbfile.bin", LOAD_FILE_MB)

    # 安全 + 统一 Baseline 策略（无 QoS，纯 pfifo）
    apply_default_accept(r1)
    apply_stateful_firewall(r1)
    apply_acl_policies(r1)
    apply_intrusion_detection(r1)
    init_db(r1)
    apply_baseline_policy(r1)

    # 负载均衡器（Static 模式使用故意失衡的映射）
    static_map = LB_STATIC_MAPPING if algorithm == "static" else None
    balancer = LoadBalancer(algorithm=algorithm, static_mapping=static_map)

    info(f"[LB_ABLATION] 开始 {algo_label} 实验...\n")
    if algorithm == "static":
        info(f"[LB_ABLATION]   静态映射: Server1 ← dorm1/lib1/teach1/office1 (λ=2.4/过载), "
             f"Server2 ← finance1 (λ=0.8/中等)\n")
    results, elapsed = generate_traffic(net, hosts, balancer, duration=duration)
    stats = compute_statistics(results, elapsed, algo_label)

    net.stop()
    return stats


def run_lb_ablation(duration=60):
    """
    运行负载均衡消融实验。

    实验场景——故意制造服务器过载：
      Static 绑定将 4/5 客户端固定在 Server1（λ=2.4，过载），
      仅 finance1 分配到 Server2（λ=0.8，中等负载）。

    对比:
      1. Final − LB (Static):  静态绑定 → Server1 过载 → 响应高、吞吐受限
      2. Final (Round Robin):  轮询调度 → 50:50 均衡 → 响应降低、吞吐改善

    消融逻辑:
      去掉 LB → 服务器过载失衡 → 性能指标劣化
      加入 LB → 请求均匀分配 → 性能指标恢复
    """
    ensure_dirs()
    info("[LB_ABLATION] 开始负载均衡消融实验\n")
    info("[LB_ABLATION] 失衡场景: Server1 ← 4/5 客户端 (λ=2.4/过载), "
         "Server2 ← 1/5 客户端 (λ=0.8/中等)\n")

    # 实验组 1: Final − LB (Static) —— Server1 过载
    static_stats = run_single_lb_experiment("static", "Final − LB (静态绑定→过载)", duration)

    import os as _os
    _os.system("mn -c 2>/dev/null")
    time.sleep(2)

    # 实验组 2: Final (Round Robin)
    rr_stats = run_single_lb_experiment("round_robin", "Final (Round Robin)", duration)

    # 输出结果
    print_separator("负载均衡消融实验结果")
    header = (f"{'调度策略':<26} {'请求数':<8} {'平均响应(s)':<14} "
              f"{'吞吐量(Mbps)':<14} {'S1流量':<10} {'S2流量':<10} "
              f"{'负载方差':<12} {'Jain指数':<10}")
    info(header + "\n")
    info("-" * 110 + "\n")

    for s in [static_stats, rr_stats]:
        info(f"{s['algorithm']:<26} "
             f"{s['total_requests']:<8} "
             f"{s['avg_resp_time']:<14.4f} "
             f"{s['total_throughput']:<14.2f} "
             f"{s['server1_traffic_pct']}%{'':<6} "
             f"{s['server2_traffic_pct']}%{'':<6} "
             f"{s['load_variance']:<12.4f} "
             f"{s['jain_index']:<10.4f}\n")

    # 保存
    ts = timestamp()
    csv_rows = []
    for s in [static_stats, rr_stats]:
        csv_rows.append([
            s["algorithm"], s["total_requests"], s["avg_resp_time"],
            s["total_throughput"],
            f"{s['server1_traffic_pct']}%", f"{s['server2_traffic_pct']}%",
            s["load_variance"], s["jain_index"],
        ])

    save_to_csv(f"lb_ablation_{ts}.csv",
                ["调度策略", "请求数", "平均响应(s)", "吞吐量(Mbps)",
                 "S1流量", "S2流量", "负载方差", "Jain指数"],
                csv_rows)
    save_to_json(f"lb_ablation_{ts}.json",
                 {
                     "实验设计": "负载均衡消融实验：故意制造服务器过载场景",
                     "失衡场景": "Server1 ← dorm1/lib1/teach1/office1 (λ=2.4/过载), Server2 ← finance1 (λ=0.8/中等)",
                     "消融逻辑": "去掉LB→Server1过载性能劣化, 加入RR→50:50均衡性能恢复",
                     "static": static_stats, "round_robin": rr_stats,
                 },
                 subdir="load_balance")

    info(f"\n[LB_ABLATION] 实验完成！\n")
    return csv_rows


if __name__ == "__main__":
    run_lb_ablation()
