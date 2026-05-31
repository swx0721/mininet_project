"""
load_balance_test.py - 负载均衡对比实验

实验定位：
  使用双服务入口系统架构，仅改变"请求调度层逻辑"，
  研究负载均衡策略对系统整体性能的影响。

系统模型：
  - 双服务器架构（Server1 + Server2）表示统一校园网络资源池的两个出口节点
  - 两台服务器相互独立，各自承载被分配到本机的请求
  - 模拟校园网晚高峰热点流量场景

实验对比两种调度策略：
  1. Baseline：统一静态入口绑定，无负载均衡，动态请求到达下自然失衡
  2. Round Robin（轮询）：请求依次分配至两个出口节点，目标为 50% / 50%

测量指标：
  - 平均响应时间
  - 总吞吐量
  - 服务器流量占比
  - 负载方差
  - Jain 公平指数
"""

import time
import sys
import os
import random
import threading
import subprocess

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mininet.log import info
from utils import (
    save_to_csv, save_to_json, print_separator,
    timestamp, ensure_dirs
)
from security import apply_all_security, cleanup_network
from topology import create_fresh_network
from services import start_dual_server_services, start_web_server
from experiments.network_baseline import (
    SERVER1_IP,
    SERVER2_IP,
    UNIFIED_STATIC_MAPPING,
    apply_unified_baseline_policy,
)


# ==================== 常量定义 ====================

LOAD_FILE_MB = 2
BIGFILE_URL = "/lbfile.bin"

# 客户端节点配置（客户端名, 中文描述）
# 请求数不再硬编码，而是在实验窗口内按泊松到达过程动态生成。
CLIENT_NODES = [
    ("dorm1",    "宿舍区 (热点)"),
    ("lib1",     "图书馆 (热点)"),
    ("office1",  "办公楼 (热点)"),
    ("finance1", "财务处 (普通)"),
    ("teach1",   "教学楼 (普通)"),
]

# 泊松到达率（λ = 每秒平均请求数）
LOAD_LAMBDA = {
    "finance1": 0.8,
    "teach1":   0.5,
    "office1":  0.4,
    "dorm1":    1.0,
    "lib1":     0.5,
}

CLIENT_DESC = {
    client_name: desc
    for client_name, desc in CLIENT_NODES
}

SERVER_LABELS = {
    SERVER1_IP: "Server1",
    SERVER2_IP: "Server2",
}

SERVERS = [SERVER1_IP, SERVER2_IP]

# Baseline 固定入口映射：复用两个实验共同的无负载均衡静态入口选择。
STATIC_MAPPING = UNIFIED_STATIC_MAPPING.copy()

# ==================== 负载均衡调度器 ====================

class LoadBalancer:
    """
    请求调度器 — 控制客户端请求分发至哪个服务入口。

    本调度器模拟"请求调度层"逻辑，决定每个请求应该发送到
    两个服务入口（Server1/Server2）中的哪一个。
    与 QoS 实验使用完全相同的系统架构，仅改变此调度逻辑。
    """

    def __init__(self, algorithm="static"):
        """
        初始化调度器。

        参数:
            algorithm: "static"       — 固定绑定（Baseline）
                       "round_robin"  — 轮询调度
        """
        self.algorithm = algorithm
        self.rr_index = 0   # Round Robin 计数器
        self.lock = threading.Lock()

    def get_server(self, client_name):
        """
        根据调度算法为请求选择目标服务入口 IP。

        参数:
            client_name: 客户端主机名

        返回:
            server_ip: 目标服务入口 IP 地址
        """
        if self.algorithm == "static":
            # 静态绑定：客户端与入口关系固定，不随负载变化
            return STATIC_MAPPING.get(client_name, SERVER1_IP)

        elif self.algorithm == "round_robin":
            # 轮询：请求依次分配到两个入口
            with self.lock:
                servers = [SERVER1_IP, SERVER2_IP]
                target = servers[self.rr_index % len(servers)]
                self.rr_index += 1
                return target

        else:
            # 默认回退到静态分配
            return STATIC_MAPPING.get(client_name, SERVER1_IP)

    def reset(self):
        """重置调度器状态（每次实验开始前调用）。"""
        with self.lock:
            self.rr_index = 0


def parse_curl_output(output):
    """
    解析 curl 输出，提取 HTTP 状态码、响应时间和下载字节数。

    curl -o /dev/null -s -w '%{http_code}\\t%{time_total}\\t%{size_download}'
    输出格式: "200\t0.123\t2097152"

    参数:
        output: curl 命令的原始输出

    返回:
        (http_code, response_time_s, bytes_downloaded) 或 (None, None, 0) 表示失败
    """
    try:
        parts = output.strip().split("\t")
        if len(parts) >= 3:
            http_code = int(parts[0])
            resp_time = float(parts[1])
            bytes_downloaded = int(float(parts[2]))
            return http_code, resp_time, bytes_downloaded
        if len(parts) >= 2:
            http_code = int(parts[0])
            resp_time = float(parts[1])
            return http_code, resp_time, 0
    except (ValueError, IndexError):
        pass
    return None, None, 0


def generate_traffic(net, client_nodes, balancer, duration=60, max_wait=180):
    """
    按照调度策略生成动态到达的 HTTP 下载流量。

    流程：
      1. 每个客户端按泊松到达过程持续产生请求
      2. 每个请求到达时通过 LoadBalancer 分配目标服务入口
      3. curl 以后台进程运行，形成动态并发竞争
      4. 汇总统计结果

    关键改进：
      - 不再预设每个客户端请求数
      - 用泊松流模拟真实随机到达
      - 用实际下载字节数统计服务器流量占比

    参数:
        client_nodes:   CLIENT_NODES 格式的列表 [(client_name, desc), ...]
        balancer:       LoadBalancer 实例（决定请求调度策略）
        duration:       请求生成持续时间（秒）
        max_wait:       停止生成后等待请求完成的最长时间（秒）

    返回:
        results: [
            {
                "client":      客户端名,
                "desc":       客户端描述,
                "target_ip":  目标服务入口,
                "http_code":  HTTP 状态码,
                "resp_time":  响应时间(秒),
                "bytes":      下载字节数,
            },
            ...
        ]
        elapsed: 实验总耗时（秒）
    """
    balancer.reset()
    results = []
    processes = []
    lock = threading.Lock()
    request_counter = {"value": 0}

    start_time = time.time()
    end_time = start_time + duration

    def next_request_id():
        with lock:
            request_counter["value"] += 1
            return request_counter["value"]

    def spawn_request(client_name, desc):
        target_ip = balancer.get_server(client_name)
        req_id = next_request_id()
        client = net.get(client_name)
        url = f"http://{target_ip}{BIGFILE_URL}"

        cmd = (
            f"curl -o /dev/null -s "
            f"-w '%{{http_code}}\\t%{{time_total}}\\t%{{size_download}}' "
            f"'{url}'"
        )
        proc = client.popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        with lock:
            processes.append({
                "req_id": req_id,
                "client": client_name,
                "desc": desc,
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
        info(f"[LOADB]   {desc} 生成 {generated} 个泊松请求\n")

    generators = []
    for client_name, desc in client_nodes:
        t = threading.Thread(
            target=client_generator,
            args=(client_name, desc),
            daemon=True
        )
        generators.append(t)
        t.start()

    info(f"[LOADB]   动态请求生成中：持续 {duration}s，模型=泊松到达\n")

    for t in generators:
        t.join()

    with lock:
        total_requests = len(processes)
        process_items = list(processes)
    info(f"[LOADB]   请求生成结束，共到达 {total_requests} 个请求，等待完成...\n")

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
            "request_id":   item["req_id"],
            "client":       item["client"],
            "desc":         item["desc"],
            "target_ip":    item["target_ip"],
            "server":       item["server"],
            "arrival_time": item["arrival_time"],
            "http_code":    http_code,
            "success":      success,
            "resp_time":    resp_time if success else None,
            "bytes":        bytes_downloaded if success else 0,
        })
        completed += 1
        if completed % 50 == 0 or completed == total_requests:
            info(f"[LOADB]   完成收集: {completed}/{total_requests}\n")

    elapsed = time.time() - start_time

    return results, elapsed


def compute_statistics(results, elapsed, algo_name):
    """
    从原始请求结果计算实验统计指标。

    指标说明：
      - 平均响应时间：所有请求的平均完成时间
      - 系统总吞吐量：总传输字节数 / 实验总耗时（正确计算方式）
      - 服务器流量占比：按实际下载字节数计算
      - 负载方差：两个服务器流量占比的方差
      - Jain 公平指数：按服务器实际承载字节数计算

    参数:
        results:   generate_traffic 返回的结果列表
        elapsed:   实验总耗时（秒）
        algo_name: 算法名称

    返回:
        stats: {
            "algorithm":         调度算法名称,
            "total_requests":    总请求数,
            "avg_resp_time":     平均响应时间(秒),
            "total_throughput":  系统总吞吐量(Mbps),
            "server1_count":     入口1 处理的请求数,
            "server2_count":     入口2 处理的请求数,
            "server1_traffic_pct": 入口1流量占比(%),
            "server2_traffic_pct": 入口2流量占比(%),
            "load_variance":     流量占比方差,
            "jain_index":        Jain公平指数,
        }
    """
    total = len(results)
    successful = [r for r in results if r["success"]]
    completed_count = len(successful)

    # 平均响应时间
    resp_times = [r["resp_time"] for r in successful if r["resp_time"] is not None]
    avg_resp_time = (sum(resp_times) / len(resp_times)) if resp_times else 0.0

    # 总吞吐量 = 总传输字节数 × 8 / 总耗时（秒） → 得到 bps → 除以 1M 得 Mbps
    total_bytes = sum(r["bytes"] for r in successful)
    total_throughput_mbps = (total_bytes * 8 / elapsed) / 1_000_000 if elapsed > 0 else 0.0

    # 两台服务器的请求分布和实际字节负载
    server1_count = sum(1 for r in results if r["target_ip"] == SERVER1_IP)
    server2_count = sum(1 for r in results if r["target_ip"] == SERVER2_IP)
    server1_bytes = sum(r["bytes"] for r in successful if r["target_ip"] == SERVER1_IP)
    server2_bytes = sum(r["bytes"] for r in successful if r["target_ip"] == SERVER2_IP)

    server1_share = (server1_bytes / total_bytes) if total_bytes > 0 else 0.0
    server2_share = (server2_bytes / total_bytes) if total_bytes > 0 else 0.0
    mean_share = (server1_share + server2_share) / 2
    load_variance = (
        ((server1_share - mean_share) ** 2 + (server2_share - mean_share) ** 2) / 2
    )

    loads = [server1_bytes, server2_bytes]
    squared_sum = sum(x * x for x in loads)
    jain_index = (
        (sum(loads) ** 2) / (len(loads) * squared_sum)
        if squared_sum > 0 else 0.0
    )

    stats = {
        "algorithm":           algo_name,
        "total_requests":      total,
        "completed_requests":  completed_count,
        "avg_resp_time":       round(avg_resp_time, 4),
        "total_throughput":    round(total_throughput_mbps, 2),
        "server1_count":       server1_count,
        "server2_count":       server2_count,
        "server1_bytes":       server1_bytes,
        "server2_bytes":       server2_bytes,
        "server1_traffic_pct": round(server1_share * 100, 1),
        "server2_traffic_pct": round(server2_share * 100, 1),
        "load_variance":       round(load_variance, 4),
        "jain_index":          round(jain_index, 4),
    }

    return stats


def run_single_algorithm(algo_name, algo_label, duration=60):
    """
    在独立 Mininet 实例中运行一种调度策略的完整实验。

    与 QoS 实验使用完全相同的双入口系统架构，仅改变请求调度层逻辑。
    每种策略使用独立的 Mininet 实例，避免状态污染。

    参数:
        algo_name:  算法标识（"static"/"round_robin"）
        algo_label: 算法中文标签（用于输出显示）
        duration:   实验总体超时时间（秒）

    返回:
        stats: compute_statistics 返回的统计字典
    """
    info("\n" + "=" * 60 + "\n")
    info(f"  调度策略: {algo_label}\n")
    info("=" * 60 + "\n")

    # 1. 创建全新拓扑（双服务入口，与 QoS 实验相同架构）
    net, r1, server1, server2 = create_fresh_network()

    # 2. 启动双服务入口服务，并确保两台服务器都提供 HTTP 下载服务
    start_dual_server_services(server1, server2)
    start_web_server(server2)

    # 3. 应用安全策略与统一 baseline 网络策略（不启用 QoS）
    apply_all_security(r1, with_qos=False)
    apply_unified_baseline_policy(r1, label="负载均衡实验统一 Baseline")

    time.sleep(2)

    # 4. 创建负载均衡实验专用文件。文件不宜过大，保证动态请求流可在超时时间内完成。
    for server in [server1, server2]:
        server.cmd("mkdir -p /tmp/www")
        server.cmd(f"dd if=/dev/zero of=/tmp/www/lbfile.bin bs=1M count={LOAD_FILE_MB} 2>/dev/null")
    info(f"[LOADB] 已在两个入口创建 {LOAD_FILE_MB}MB 负载测试文件\n")

    try:
        # 5. 创建请求调度器
        balancer = LoadBalancer(algorithm=algo_name)

        # 6. 生成动态到达的下载流量（模拟晚高峰热点场景）
        info(f"[LOADB] 开始生成动态泊松流量（{algo_label}）...\n")

        raw_results, elapsed = generate_traffic(
            net, CLIENT_NODES, balancer, duration=duration, max_wait=duration * 2
        )

        info(f"[LOADB] 流量生成完成，耗时 {elapsed:.2f}s\n")

        # 7. 计算统计指标（使用正确计算的 throughput = total_bytes / elapsed）
        stats = compute_statistics(raw_results, elapsed, algo_label)

        return stats, raw_results

    finally:
        cleanup_network(r1)
        net.stop()
        info(f"[LOADB] {algo_label} 实例已清理\n")


def run_load_balance_test(duration=60):
    """
    运行负载均衡对比实验（两个独立 Mininet 实例）。

    实验架构：
      使用双服务入口系统架构（Server1 + Server2），
      仅改变请求调度层逻辑，对比不同调度策略的性能差异。

    实验流程（两个独立实例）：
      实例1 — Baseline：统一静态入口绑定，动态到达下自然失衡
      实例2 — Round Robin：请求轮询分配至两个入口

    场景设定：
      请求数由泊松到达过程自然产生。Baseline 下静态入口绑定导致负载倾斜；
      Round Robin 下请求动态轮询分配，目标为 Server1≈50%、Server2≈50%。

    参数:
        duration: 每个调度策略的实验超时时间（秒）

    返回:
        all_stats: 两种策略的统计结果列表
    """
    ts = timestamp()
    print_separator(f"负载均衡对比实验 — Baseline vs Round Robin ({ts})", 70)

    # 实验组定义：动态失衡 Baseline 与轮询改进版
    algorithms = [
        ("static",      "Baseline(统一静态绑定)"),
        ("round_robin", "轮询(Round Robin)"),
    ]

    all_stats = []
    all_raw = {}

    for algo_name, algo_label in algorithms:
        try:
            stats, raw = run_single_algorithm(algo_name, algo_label, duration)
            all_stats.append(stats)
            all_raw[algo_name] = {"stats": stats, "raw": raw}
            time.sleep(2)  # 实例间间隔
        except Exception as e:
            info(f"[LOADB] {algo_label} 实验失败: {e}\n")
            all_stats.append({
                "algorithm":           algo_label,
                "total_requests":      0,
                "completed_requests":  0,
                "avg_resp_time":       0.0,
                "total_throughput":    0.0,
                "server1_count":       0,
                "server2_count":       0,
                "server1_bytes":       0,
                "server2_bytes":       0,
                "server1_traffic_pct": 0.0,
                "server2_traffic_pct": 0.0,
                "load_variance":       0.0,
                "jain_index":          0.0,
            })

    # ========== 打印对比结果 ==========
    print_separator("负载均衡对比结果 — 请求调度策略", 70)
    header = (f"{'调度策略':<24} {'请求数':<8} {'平均响应(s)':<14} "
              f"{'吞吐量(Mbps)':<14} {'S1流量':<10} {'S2流量':<10} "
              f"{'负载方差':<10} {'Jain指数':<10}")
    info(header + "\n")
    info("-" * 108 + "\n")

    for s in all_stats:
        info(
            f"{s['algorithm']:<24} "
            f"{s['total_requests']:<8} "
            f"{s['avg_resp_time']:<14.4f} "
            f"{s['total_throughput']:<14.2f} "
            f"{s['server1_traffic_pct']:<8.1f}% "
            f"{s['server2_traffic_pct']:<8.1f}% "
            f"{s['load_variance']:<10.4f} "
            f"{s['jain_index']:<10.4f}\n"
        )

    # ========== 保存 CSV ==========
    csv_headers = [
        "调度策略", "总请求数", "完成请求数",
        "平均响应时间(s)", "总吞吐量(Mbps)",
        "入口1请求数", "入口2请求数",
        "入口1字节数", "入口2字节数",
        "入口1流量占比(%)", "入口2流量占比(%)",
        "负载方差", "Jain公平指数"
    ]
    csv_rows = []
    for s in all_stats:
        csv_rows.append([
            s["algorithm"],
            s["total_requests"],
            s["completed_requests"],
            s["avg_resp_time"],
            s["total_throughput"],
            s["server1_count"],
            s["server2_count"],
            s["server1_bytes"],
            s["server2_bytes"],
            s["server1_traffic_pct"],
            s["server2_traffic_pct"],
            s["load_variance"],
            s["jain_index"],
        ])

    csv_name = f"load_balance_{ts}.csv"
    save_to_csv(csv_name, csv_headers, csv_rows)
    info(f"[LOADB] CSV 已保存\n")

    # ========== 保存 JSON（仅汇总统计，不保存原始请求详情）==========
    json_data = {
        "实验时间": ts,
        "实验说明": "负载均衡对比实验 — 统一静态 baseline vs Round Robin",
        "系统架构": "双服务入口，双服务器相互独立，仅改变请求调度层逻辑",
        "预期现象": {
            "Baseline": "复用统一静态入口绑定，Server1/Server2 流量占比受客户端到达率影响，负载方差较大，Jain 指数较低",
            "Round Robin": "请求轮流分配，Server1≈50%、Server2≈50%，负载方差较小，Jain 指数接近 1"
        },
        "负载文件大小(MB)": LOAD_FILE_MB,
        "流量模型": "泊松到达",
        "实验时长(s)": duration,
        "到达率lambda": LOAD_LAMBDA,
        "静态映射": STATIC_MAPPING,
        "客户端配置": [
            {"主机": h, "描述": d}
            for h, d in CLIENT_NODES
        ],
        "结果": all_stats,
    }

    json_name = f"load_balance_{ts}.json"
    save_to_json(json_name, json_data)
    info(f"[LOADB] JSON 已保存\n")

    info(f"\n[LOADB] 负载均衡实验完成！结果已保存到 {csv_name} 和 {json_name}\n")

    return all_stats


if __name__ == "__main__":
    info("请通过 main.py 运行此实验\n")
    run_load_balance_test()
