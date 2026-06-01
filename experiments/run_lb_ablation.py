"""
experiments/run_lb_ablation.py — 实验二：负载均衡消融实验

实验设计:
  Final（QoS + LB + Security） vs  Final − LB（QoS + Security）

实验场景——双服务器按区域分工：
  Server1（10.0.100.2）：财务处、教学楼、办公楼
  Server2（10.0.101.2）：宿舍区、图书馆

  Static 绑定下，各区域固定分配至对应服务器。
  Round Robin 下请求轮流分配 → 50:50 均衡。

  关键设计：使用 15MB 大文件（非小文件），降低 TCP 慢启动占传输时间的比重，
  使 RR 频繁切换服务器的慢启动惩罚可忽略，从而真实反映负载均衡的收益。

对比指标:
  - 服务器负载分布
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
from core.server_cluster import get_server_hosts, DEFAULT_STATIC_MAPPING
from services.web import start_web_server, create_test_file
from policies.load_balance import LoadBalancer

# 负载均衡实验：服务器链路瓶颈带宽 (Mbps)
# 设计意图：制造拥塞瓶颈，使负载均衡的价值得以体现。
# Static 模式下 S1 获得更多流量（λ=1.7 vs S2 λ=1.5），瓶颈处产生排队；
# RR 模式下负载均分（50:50），两侧瓶颈均摊，从而体现负载均衡优势。
#
# ⚠️ HTB 作用位置：服务器出口（server1-eth0 / server2-eth0），
#    而非路由器接口。因为下载流量方向是 服务器→客户端，
#    只有服务器 egress 才能整形到数据包。
LB_BOTTLENECK_MBPS = 20


LOAD_FILE_MB = 5   # 5MB: 20Mbps瓶颈下2s/文件，仍远大于TCP慢启动窗口建立时间
BIGFILE_URL = "/lbfile.bin"

# ==================== 负载均衡消融实验专用静态映射 ====================
#
# 映射规则（与 DEFAULT_STATIC_MAPPING 一致）：
#   Server1（10.0.100.2）：财务处、教学楼、办公楼
#   Server2（10.0.101.2）：宿舍区、图书馆
#
# 负载分布（中负载稳定区：避免排队主导区带来的非线性失真）：
#   Server1 λ 合计 = 0.18 + 0.12 + 0.10 = 0.40 (67%)
#   Server2 λ 合计 = 0.12 + 0.08       = 0.20 (33%)
#
# 需求分析（5MB 文件，20Mbps 瓶颈）：
#   单文件最低耗时 = 5×8÷20 = 2s
#   S1 需求: 0.40×60 = 24 请求 → 24×2=48s → 80% 利用率（中高负载，非过载）
#   S2 需求: 0.20×60 = 12 请求 → 12×2=24s → 40% 利用率（中低负载，有余量）
#   总请求 ≈ 36，总需求 24Mbps = 60% 总容量 → 中负载区，调度差异可观测
#
# Static 下 S1(80%) vs S2(40%) 负载不均；RR 下均摊至各约 60%。
#
LB_STATIC_MAPPING = {
    "finance1": SERVER1_IP,  # λ=0.18  财务处
    "teach1":   SERVER1_IP,  # λ=0.12  教学楼
    "office1":  SERVER1_IP,  # λ=0.10  办公楼
    "dorm1":    SERVER2_IP,  # λ=0.12  宿舍区
    "lib1":     SERVER2_IP,  # λ=0.08  图书馆
}
# S1 λ = 0.18 + 0.12 + 0.10 = 0.40 → 80%利用率（中高负载，非过载）
# S2 λ = 0.12 + 0.08       = 0.20 → 40%利用率（中低负载，有余量）

CLIENT_NODES = [
    ("dorm1", "宿舍区 (热点)"),
    ("lib1", "图书馆 (热点)"),
    ("office1", "办公楼 (热点)"),
    ("finance1", "财务处 (普通)"),
    ("teach1", "教学楼 (普通)"),
]

LOAD_LAMBDA = {}

# ==================== 场景定义 ====================

# 场景 A：中等均衡负载 — 两服务器负载接近
#   S1 λ 合计 = 0.10+0.10+0.05 = 0.25 → 50%利用率
#   S2 λ 合计 = 0.10+0.15       = 0.25 → 50%利用率
LB_SCENARIO_A = {
    "finance1": 0.10, "teach1": 0.10, "office1": 0.05,
    "dorm1": 0.10, "lib1": 0.15,
}

# 场景 B：Server1 高负载 — S1 明显高于 S2（默认）
#   S1 λ 合计 = 0.18+0.12+0.10 = 0.40 → 80%利用率（中高负载，非过载）
#   S2 λ 合计 = 0.12+0.08       = 0.20 → 40%利用率（中低负载，有余量）
LB_SCENARIO_B = {
    "finance1": 0.18, "teach1": 0.12, "office1": 0.10,
    "dorm1": 0.12, "lib1": 0.08,
}

SCENARIO_LAMBDA_MAP = {"A": LB_SCENARIO_A, "B": LB_SCENARIO_B}


def _set_lb_scenario(scenario: str):
    """设置当前 LB 消融实验场景并更新全局 LOAD_LAMBDA。"""
    global LOAD_LAMBDA
    LOAD_LAMBDA = SCENARIO_LAMBDA_MAP[scenario]
    return scenario

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
               f"-w '%{{http_code}}\\t%{{time_total}}\\t%{{size_download}}' "
               f"'{url}' --connect-timeout 10 --max-time 120")
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
    """计算统计指标（双独立链路架构）。

    双独立链路意味着每条服务器链路有各自独立的瓶颈容量，
    S1 和 S2 的利用率分别计算，不互斥（可同时达到 100%）。
    """
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

    # 各链路独立吞吐量（Mbps）
    s1_mbps = (s1_bytes * 8 / elapsed) / 1_000_000 if elapsed > 0 else 0.0
    s2_mbps = (s2_bytes * 8 / elapsed) / 1_000_000 if elapsed > 0 else 0.0

    # 各链路独立利用率（相对于自身瓶颈，互不依赖，可同时 100%）
    s1_util = s1_mbps / LB_BOTTLENECK_MBPS * 100 if LB_BOTTLENECK_MBPS > 0 else 0
    s2_util = s2_mbps / LB_BOTTLENECK_MBPS * 100 if LB_BOTTLENECK_MBPS > 0 else 0

    # 负载方差：基于利用率计算（双独立链路，理想情况下两者利用率相等）
    mean_util = (s1_util + s2_util) / 2
    variance = ((s1_util - mean_util) ** 2 + (s2_util - mean_util) ** 2) / 2

    # Jain 公平指数：基于各链路实际吞吐量（字节数）
    loads = [s1_bytes, s2_bytes]
    sq_sum = sum(x * x for x in loads)
    jain = (sum(loads) ** 2) / (len(loads) * sq_sum) if sq_sum > 0 else 0

    return {
        "algorithm": algo_name,
        "total_requests": total,
        "completed_requests": len(successful),
        "avg_resp_time": round(avg_resp_time, 4),
        "total_throughput": round(total_throughput, 2),
        "server1_mbps": round(s1_mbps, 2),
        "server2_mbps": round(s2_mbps, 2),
        "server1_util_pct": round(s1_util, 1),
        "server2_util_pct": round(s2_util, 1),
        "server1_count": s1_count,
        "server2_count": s2_count,
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

    # ====== LB 消融实验参数 ======
    # 实验设计：(1,1,1) vs (1,0,1) — 仅改变负载均衡，保留 QoS 和 Security
    # 
    # 关键：
    #   1. 保留所有 ACL 规则（不能 iptables -F/-X）
    #   2. 保留区域上行链路 QoS（apply_htb_policy）
    #   3. 仅在服务器出口增加瓶颈（不覆盖拓扑级 QoS）
    #   4. 算法在 Static（对照组） vs Round Robin（实验组）之间切换

    from security.acl import apply_stateful_firewall, apply_acl_policies, apply_default_accept
    from policies.qos import apply_htb_policy

    # 应用安全策略（保持 Security=1）
    apply_default_accept(r1)
    apply_stateful_firewall(r1)
    apply_acl_policies(r1)
    info("[LB_ABLATION] ACL 安全策略已启用（Security=1）\n")

    # 应用区域上行链路 QoS（保持 QoS=1）
    apply_htb_policy(r1)
    info("[LB_ABLATION] 区域上行链路 HTB QoS 已启用（QoS=1）\n")
    for server_node, ifname in [(server1, "server1-eth0"), (server2, "server2-eth0")]:
        if server_node:
            # 清除 TCLink 自带 qdisc，替换为实验用 HTB
            server_node.cmd(f"tc qdisc del dev {ifname} root 2>/dev/null || true")
            server_node.cmd(f"tc qdisc add dev {ifname} root handle 1: htb default 1")
            server_node.cmd(f"tc class add dev {ifname} parent 1: classid 1:1 "
                           f"htb rate {LB_BOTTLENECK_MBPS}mbit ceil {LB_BOTTLENECK_MBPS}mbit "
                           f"burst 32k")
            server_node.cmd(f"tc qdisc add dev {ifname} parent 1:1 handle 10: pfifo limit 1000")
    info(f"[LB_ABLATION] 服务器出口瓶颈已配置（server egress 方向）: "
         f"各 {LB_BOTTLENECK_MBPS}Mbps (对称)\n")

    # ====== 验证 HTB 已生效 ======
    info("[LB_ABLATION] === 验证服务器出口 HTB ===\n")
    for server_node, name in [(server1, "server1"), (server2, "server2")]:
        if server_node:
            ifname = f"{name}-eth0"
            out = server_node.cmd(f"tc qdisc show dev {ifname} 2>/dev/null").strip()
            info(f"[LB_ABLATION]   {name} ({ifname}): {out[:120]}\n")

    # ====== 连通性诊断：直接测试 S1 和 S2 是否可达 ======
    info("[LB_ABLATION] === S1/S2 连通性诊断 ===\n")
    r1.cmd("ip addr show r1-eth5 | grep inet || echo 'r1-eth5 NO IP'")
    r1.cmd("ip addr show r1-eth6 | grep inet || echo 'r1-eth6 NO IP'")
    
    test_client = hosts.get("dorm1")
    if test_client:
        # ping 测试
        for label, ip in [("S1", SERVER1_IP), ("S2", SERVER2_IP)]:
            out = test_client.cmd(f"ping -c 3 -W 2 {ip}")
            loss = "0% packet loss" in out or " 0% packet loss" in out
            info(f"[LB_ABLATION]   ping {label}({ip}): {'通' if loss else '不通'} | {out.split(chr(10))[-3] if out else 'N/A'}\n")
        
        # curl 计时测试
        for label, ip in [("S1", SERVER1_IP), ("S2", SERVER2_IP)]:
            t0 = time.time()
            out = test_client.cmd(f"curl -o /dev/null -s -w '%{{http_code}} %{{time_total}}s' http://{ip}/lbfile.bin --connect-timeout 5 --max-time 15")
            t1 = time.time()
            info(f"[LB_ABLATION]   curl {label}({ip}): {out.strip()} (wall={t1-t0:.2f}s)\n")
    info("[LB_ABLATION] === 诊断结束 ===\n")

    # 负载均衡器（Static 模式使用 DEFAULT_STATIC_MAPPING）
    static_map = DEFAULT_STATIC_MAPPING if algorithm == "static" else None
    balancer = LoadBalancer(algorithm=algorithm, static_mapping=static_map)

    info(f"[LB_ABLATION] 开始 {algo_label} 实验...\n")
    if algorithm == "static":
        info(f"[LB_ABLATION]   静态映射: Server1 ← finance1/teach1/office1 (λ=0.40), "
             f"Server2 ← dorm1/lib1 (λ=0.20)\n")
    results, elapsed = generate_traffic(net, hosts, balancer, duration=duration, max_wait=300)
    stats = compute_statistics(results, elapsed, algo_label)

    net.stop()
    return stats


def run_lb_ablation(duration=60, scenario="B"):
    """
    运行负载均衡消融实验。

    实验场景——双服务器按区域分工：
      Server1：财务处、教学楼、办公楼
      Server2：宿舍区、图书馆

    对比:
      1. Final − LB (Static):  静态绑定 → 各区域固定服务器
      2. Final (Round Robin):  轮询调度 → 50:50 均衡 → 响应降低、吞吐改善

    消融逻辑:
      去掉 LB → 泊松到达随机性 + 瓶颈处排队不均 → 性能劣化
      加入 LB → 请求均匀分配 → 瓶颈均摊 → 吞吐提升、时延下降

    参数:
        scenario: "A"=中等均衡负载, "B"=Server1 高负载不均 (默认 B)
    """
    scenario = scenario.upper()
    if scenario not in ("A", "B"):
        scenario = "B"
    _set_lb_scenario(scenario)

    # 计算场景参数
    s1_lambda = LOAD_LAMBDA.get("finance1", 0) + LOAD_LAMBDA.get("teach1", 0) + \
                LOAD_LAMBDA.get("office1", 0)
    s2_lambda = LOAD_LAMBDA.get("dorm1", 0) + LOAD_LAMBDA.get("lib1", 0)
    total_demand = (s1_lambda + s2_lambda) * LOAD_FILE_MB * 8  # Mbps
    capacity_pct = total_demand / (LB_BOTTLENECK_MBPS * 2) * 100

    ensure_dirs()
    info(f"[LB_ABLATION] ====== 场景 {scenario} ======\n")
    if scenario == "A":
        info("[LB_ABLATION] 负载模式: 中等均衡 — 两服务器负载接近\n")
    else:
        info("[LB_ABLATION] 负载模式: Server1 高负载不均 — S1 明显高于 S2\n")
    info(f"[LB_ABLATION] λ 参数: finance1={LOAD_LAMBDA['finance1']}, "
         f"teach1={LOAD_LAMBDA['teach1']}, office1={LOAD_LAMBDA['office1']}, "
         f"dorm1={LOAD_LAMBDA['dorm1']}, lib1={LOAD_LAMBDA['lib1']}\n")
    info(f"[LB_ABLATION] S1 λ 合计={s1_lambda:.2f} (Static→{s1_lambda*LOAD_FILE_MB*8/LB_BOTTLENECK_MBPS*100:.0f}%util), "
         f"S2 λ 合计={s2_lambda:.2f} (Static→{s2_lambda*LOAD_FILE_MB*8/LB_BOTTLENECK_MBPS*100:.0f}%util), "
         f"总 λ={s1_lambda+s2_lambda:.2f}\n")
    info(f"[LB_ABLATION] 区域分工: Server1 ← finance1/teach1/office1 (λ={s1_lambda:.2f}), "
         f"Server2 ← dorm1/lib1 (λ={s2_lambda:.2f})\n")
    info(f"[LB_ABLATION] 文件: {LOAD_FILE_MB}MB, 瓶颈: {LB_BOTTLENECK_MBPS}Mbps×2 "
         f"(总需求{total_demand:.0f}Mbps={capacity_pct:.0f}%容量)\n")

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
              f"{'总吞吐(Mbps)':<13} {'S1(Mbps)':<10} {'S2(Mbps)':<10} "
              f"{'S1利用率':<10} {'S2利用率':<10} "
              f"{'负载方差':<10} {'Jain指数':<10}")
    info(header + "\n")
    info("-" * 130 + "\n")

    for s in [static_stats, rr_stats]:
        info(f"{s['algorithm']:<26} "
             f"{s['total_requests']:<8} "
             f"{s['avg_resp_time']:<14.4f} "
             f"{s['total_throughput']:<13.2f} "
             f"{s['server1_mbps']:<10.2f} "
             f"{s['server2_mbps']:<10.2f} "
             f"{s['server1_util_pct']}%{'':<7} "
             f"{s['server2_util_pct']}%{'':<7} "
             f"{s['load_variance']:<10.4f} "
             f"{s['jain_index']:<10.4f}\n")

    # 瓶颈参考线
    info(f"  ※ 单链路瓶颈: {LB_BOTTLENECK_MBPS} Mbps, "
         f"双链路总容量: {LB_BOTTLENECK_MBPS * 2} Mbps "
         f"(利用率独立计算，不互斥)\n")

    # 保存
    ts = timestamp()
    csv_rows = []
    for s in [static_stats, rr_stats]:
        csv_rows.append([
            s["algorithm"], s["total_requests"], s["avg_resp_time"],
            s["total_throughput"],
            s["server1_mbps"], s["server2_mbps"],
            s["server1_util_pct"], s["server2_util_pct"],
            s["load_variance"], s["jain_index"],
        ])

    save_to_csv(f"lb_ablation_{ts}.csv",
                ["调度策略", "请求数", "平均响应(s)", "总吞吐量(Mbps)",
                 "S1吞吐(Mbps)", "S2吞吐(Mbps)", "S1利用率(%)", "S2利用率(%)",
                 "负载方差", "Jain指数"],
                csv_rows)
    save_to_json(f"lb_ablation_{ts}.json",
                 {
                     "实验设计": "负载均衡消融实验：中负载稳定区（60%总容量）",
                     "区域分工": "Server1←finance1/teach1/office1 (λ=0.40/80%util), Server2←dorm1/lib1 (λ=0.20/40%util)",
                     "消融逻辑": "去掉LB→S1(80%)vsS2(40%)不均衡, 加入RR→均摊至各60%→时延改善",
                     "static": static_stats, "round_robin": rr_stats,
                 },
                 subdir="load_balance")

    info(f"\n[LB_ABLATION] 实验完成！\n")
    return csv_rows


if __name__ == "__main__":
    run_lb_ablation()
