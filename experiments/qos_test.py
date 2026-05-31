"""
qos_test.py - QoS 对比实验（三组调度策略消融实验版）

======================================================================
实验设计——三种队列调度策略横向对比：

  ┌──────────────────────┬──────────────────────┬──────────────────────┬──────────────────────────────────┐
  │      维度            │     Baseline         │   QoS (prio)         │   QoS (HTB)                      │
  ├──────────────────────┼──────────────────────┼──────────────────────┼──────────────────────────────────┤
  │ 队列策略              │  pfifo (FIFO)        │  prio (严格优先级)   │  HTB 分层 + sfq（软优先级）       │
  │ 财务处流量            │  公平竞争             │  band 0 (最高优先)   │  保底 12Mbps, prio 0 (最高)       │
  │ 普通业务流量          │  公平竞争             │  band 1 (普通)       │  保底 15Mbps, prio 1 (普通)       │
  │ UDP/背景流            │  公平竞争             │  band 1 (普通)       │  保底 6Mbps,  prio 2 (最低)       │
  │ 队列内调度            │  pfifo 纯 FIFO        │  pfifo (每 band)     │  sfq 公平队列（防 TCP 踩踏）      │
  │ HTB 限速              │  rate=ceil=35Mbps    │  rate=30, ceil=35    │  三层 rate 合计 33Mbps < 35Mbps   │
  │ 出口瓶颈              │  35Mbps              │  35Mbps              │  35Mbps                          │
  └──────────────────────┴──────────────────────┴──────────────────────┴──────────────────────────────────┘

  三种策略的本质区别：
  - Baseline（pfifo）：纯 FIFO，无任何优先级或带宽控制
  - prio QoS：严格优先级抢占，band 0 有包时 band 1 完全不服务
  - HTB QoS：资源分配型调度，每类有保底带宽（rate）+ 优先级借用（prio）+ sfq 防踩踏

  拥塞条件：
    - r1-eth5 出口限制为 35Mbps
    - 各区域泊松到达，总需求约 38-42Mbps（轻度过载，拥塞率 ≈ 110-120%）
    - 所有流量在出口处自然排队竞争

  动态流量模型：
    - 泊松到达（Poisson arrival）：各区域按不同 λ 随机发起流量
    - 多协议混合：财务/教学/办公/图书馆为 TCP，宿舍区为 UDP 视频流
    - 宿舍区 UDP 流（10Mbps 接入限制）作为背景噪声

  测量四维指标（每个客户端）：
    1. 吞吐量 (Throughput) — iperf3 TCP/UDP 实际带宽 (Mbps)
    2. 时延 (Latency) — 拥塞状态下 ping 平均 RTT (ms)
    3. 抖动 (Jitter) — UDP 流量的时延变化 (ms)
    4. 丢包率 (Packet Loss) — UDP 流量丢包百分比 (%)

系统模型（保持不变）：
  - 双服务器架构（Server1 + Server2）作为统一校园网络服务系统的两个服务入口
  - 所有客户端在统一竞争环境中访问服务器资源
  - 路由器 r1-eth5 为服务器出口汇聚链路

======================================================================
"""

import time
import sys
import os
import random
import threading
import json as _json
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
from services import start_dual_server_services
from experiments.network_baseline import (
    BASELINE_BOTTLENECK_BW,
    UNIFIED_STATIC_MAPPING,
    apply_unified_baseline_policy,
)


# ==================== 常量定义 ====================

# 参与竞争的客户端
# (client_name, target_ip, display_name, entrance_label, iperf_port, protocol, target_bw)
# protocol: "tcp" 或 "udp"
# target_bw: 仅 UDP 使用的 iperf3 -b 参数 (Mbps)；TCP 不限速，由拥塞控制自然竞争
COMPETING_CLIENTS = [
    ("finance1", UNIFIED_STATIC_MAPPING["finance1"], "财务处 (关键业务-TCP)",  "入口1", 5201, "tcp", 10),
    ("teach1",   UNIFIED_STATIC_MAPPING["teach1"], "教学楼 (课件下载-TCP)",   "入口1", 5202, "tcp", 20),
    ("office1",  UNIFIED_STATIC_MAPPING["office1"], "办公楼 (OA系统-TCP)",     "入口1", 5203, "tcp", 15),
    ("dorm1",    UNIFIED_STATIC_MAPPING["dorm1"], "宿舍区 (视频流-UDP)",     "入口2", 5201, "udp", 12),
    ("lib1",     UNIFIED_STATIC_MAPPING["lib1"], "图书馆 (网页浏览-TCP)",   "入口2", 5202, "tcp", 15),
    ("finance_probe", UNIFIED_STATIC_MAPPING["finance_probe"], "财务处 (UDP探针)",   "入口1", 5204, "udp", 1),
]

CLIENT_HOSTS = {
    "finance_probe": "finance1",
}

CLIENT_IPS = {
    "dorm1": "10.0.1.2",
    "teach1": "10.0.2.2",
    "lib1": "10.0.3.2",
    "office1": "10.0.4.2",
    "finance1": "10.0.5.2",
}

# 泊松到达率（λ = 每秒平均发起请求次数）
# 值越大，流量越密集
POISSON_LAMBDA = {
    "finance1": 0.5,   # 平均每 2.0 秒一次 — 关键业务
    "teach1":   0.4,   # 平均每 2.5 秒一次 — 课件下载
    "office1":  0.4,   # 平均每 2.5 秒一次 — OA 系统
    "dorm1":    0.4,   # 平均每 2.5 秒一次 — 视频流背景噪声（轻调低，减少瞬时拥塞峰值）
    "lib1":     0.3,   # 平均每 3.3 秒一次 — 网页浏览
    "finance_probe": 0.25,  # 低速 UDP 探针，减少突发
}

FLOW_DURATION = 5       # 每条 iperf3 流持续秒数
TOTAL_EXPERIMENT_TIME = 60  # 每轮总实验时长（秒）

# 出口瓶颈带宽（r1-eth5）
# 五个区域 + 财务 UDP 探针共同竞争；TCP 不限速，出口 35Mbps 制造温和拥塞
BOTTLENECK_BW = BASELINE_BOTTLENECK_BW  # Mbps

# 用于时延测量的 ping 参数
PING_COUNT = 10      # 每次 ping 发包数
PING_INTERVAL = 0.2   # ping 间隔（秒）


# ==================== 辅助函数 ====================

def get_iperf_port(client_spec):
    """获取客户端 iperf3 端口。"""
    return client_spec[4]


def get_protocol(client_spec):
    """获取客户端传输协议（"tcp" 或 "udp"）。"""
    return client_spec[5]


def get_target_bw(client_spec):
    """获取客户端目标带宽（Mbps）。"""
    return client_spec[6]


def generate_poisson_delays(lambda_rate, count=1):
    """
    生成泊松分布的时延序列。

    参数:
        lambda_rate: 泊松到达率（每秒事件数）
        count:       需要生成的时延数量

    返回:
        delays: 时延列表（秒）
    """
    delays = []
    for _ in range(count):
        delays.append(random.expovariate(lambda_rate))
    return delays


def parse_iperf_output(result):
    """
    从 iperf3 JSON 输出解析 TCP 吞吐量 (Mbps)。

    参数:
        result: iperf3 -J 命令的原始输出

    返回:
        throughput_mbps: 吞吐量数值，解析失败返回 None
    """
    try:
        start = result.find("{")
        end = result.rfind("}")
        if start < 0 or end < start:
            return None

        data = _json.loads(result[start:end + 1])
        if data.get("error"):
            return None

        end_data = data.get("end", {})
        candidates = [
            end_data.get("sum_received"),
            end_data.get("sum_sent"),
            end_data.get("sum"),
        ]
        for candidate in candidates:
            if candidate and candidate.get("bits_per_second") is not None:
                return candidate["bits_per_second"] / 1_000_000

        intervals = data.get("intervals", [])
        if intervals:
            interval_sum = intervals[-1].get("sum", {})
            if interval_sum.get("bits_per_second") is not None:
                return interval_sum["bits_per_second"] / 1_000_000
    except Exception:
        return None

    return None


def parse_udp_iperf_output(result):
    """
    从 iperf3 UDP JSON 输出解析吞吐量、抖动和丢包率。

    参数:
        result: iperf3 -u -J 命令的原始输出

    返回:
        dict: {"throughput_mbps": float, "jitter_ms": float, "lost_percent": float}
              解析失败返回 None
    """
    try:
        start = result.find("{")
        end = result.rfind("}")
        if start < 0 or end < start:
            return None

        data = _json.loads(result[start:end + 1])
        if data.get("error"):
            return None

        end_data = data.get("end", {})
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
            "sender_mbps": (
                end_data.get("sum_sent", {}).get("bits_per_second", 0) / 1_000_000
            ),
            "jitter_ms": sum_data.get("jitter_ms", 0),
            "lost_percent": sum_data.get("lost_percent", 0),
        }
    except Exception:
        return None


def parse_ping_output(result):
    """
    从 ping 输出解析平均 RTT (ms)。

    参数:
        result: ping 命令输出

    返回:
        avg_rtt_ms: 平均往返时延，解析失败返回 None
    """
    try:
        for line in result.split("\n"):
            if "avg" in line and "/" in line:
                # 格式: rtt min/avg/max/mdev = 10.123/20.456/30.789/5.012 ms
                parts = line.split("=")
                if len(parts) >= 2:
                    stats = parts[1].strip().split("/")
                    if stats:
                        return float(stats[1])  # avg 是第二个字段
    except Exception:
        return None
    return None


# ==================== QoS 策略配置 ====================

def apply_baseline_policy(r1):
    """
    Baseline：pfifo（先进先出队列）。

    在瓶颈链路 r1-eth5 上：
      1. 用 HTB 将出口限制为 BOTTLENECK_BW Mbps（制造拥塞）
      2. 在限速类上附加 pfifo 队列（纯 FIFO，无优先级）

    所有流量公平排队，无任何 QoS 调度。
    """
    apply_unified_baseline_policy(r1, label="QoS/LB 统一 Baseline")


def apply_qos_policy(r1):
    """
    QoS：prio（严格优先级队列）。

    在瓶颈链路 r1-eth5 上：
      1. 用 HTB 将出口限制为 BOTTLENECK_BW Mbps（制造拥塞）
      2. 在限速类上附加 prio 优先级队列
      3. 财务处（10.0.5.0/24）流量 → band 0（最高优先级）
      4. 其余流量 → band 1（普通优先级）

    严格优先级调度：只要 band 0 有数据包等待发送，band 1 不会被服务。
    这是 QoS 最核心的机制——保障关键业务获得低时延、低抖动、低丢包。
    """
    server_intf = "r1-eth5"

    info("[QOS] 配置 prio QoS: 严格优先级调度\n")

    r1.cmd(f"tc qdisc del dev {server_intf} root 2>/dev/null || true")

    # HTB 带缓冲带限速：rate < ceil 提供调度缓冲，减少瞬时排队爆炸
    r1.cmd(f"tc qdisc add dev {server_intf} root handle 1: htb default 1")
    QOS_RATE = BOTTLENECK_BW - 5  # buffer = 5Mbps
    r1.cmd(f"tc class add dev {server_intf} parent 1: classid 1:1 "
           f"htb rate {QOS_RATE}mbit ceil {BOTTLENECK_BW}mbit")

    # 在限速类上附加 prio 优先级队列（2 个 band，减少饥饿区）
    r1.cmd(f"tc qdisc add dev {server_intf} parent 1:1 handle 10: prio bands 2")

    # 财务处流量 → band 0（最高优先级）
    r1.cmd(f"tc filter add dev {server_intf} parent 10: protocol ip prio 1 u32 "
           f"match ip src 10.0.5.0/24 flowid 10:1")
    # 其余所有流量 → band 1（普通优先级）
    r1.cmd(f"tc filter add dev {server_intf} parent 10: protocol ip prio 10 u32 "
           f"match ip src 0.0.0.0/0 flowid 10:2")

    info(f"[QOS] prio QoS 已生效：r1-eth5 出口 ceil={BOTTLENECK_BW}Mbps "
         f"rate={QOS_RATE}Mbps（缓冲 5Mbps），"
         f"财务流量→band 0，其余流量→band 1\n")


# ==================== 新增：HTB QoS 策略函数 ====================


def apply_htb_policy(r1):
    """
    QoS：HTB 分层 + 软优先级（保底带宽 + sfq 公平队列）。

    在瓶颈链路 r1-eth5 上：
      1. HTB 根类限制总出口为 BOTTLENECK_BW Mbps
      2. 三个子类各分配保底带宽（rate）和优先级（prio）：
         - 财务处（10.0.5.0/24）: rate=12Mbps, ceil=35Mbps, prio=0（最高，优先借用闲置带宽）
         - 普通业务（其余 TCP）:   rate=15Mbps, ceil=28Mbps, prio=1（普通）
         - UDP/背景流（10.0.1.0/24）: rate=6Mbps,  ceil=20Mbps, prio=2（最低）
      3. 每个子类附加 sfq（随机公平队列），防止同类别内 TCP 流互相踩踏
      4. 三层 rate 合计 33Mbps < 出口 35Mbps（欠分配），预留借用空间

    软优先级（Soft Priority）原理：
      - HTB 的 prio 参数决定**借用带宽的顺序**而非严格抢占
      - 每个类首先获得其 rate 保底带宽
      - 当总带宽有剩余时，prio 0 的类优先借用，但不会完全压制 prio 1/2
      - 这与 prio qdisc 的"band 0 有包就不服务 band 1"有本质区别
    """
    server_intf = "r1-eth5"

    info("[QOS] 配置 HTB QoS: 分层 + 软优先级（保底带宽 + sfq 公平队列）\n")

    r1.cmd(f"tc qdisc del dev {server_intf} root 2>/dev/null || true")

    # === 根 HTB：总出口限制 ===
    r1.cmd(f"tc qdisc add dev {server_intf} root handle 1: htb default 20")
    r1.cmd(f"tc class add dev {server_intf} parent 1: classid 1:1 "
           f"htb rate {BOTTLENECK_BW}mbit ceil {BOTTLENECK_BW}mbit")

    # === 子类 1：财务处（高优先级 + 保底带宽）===
    # prio=0：最高优先级，拥塞时优先借用闲置带宽
    # rate=12Mbps：保底带宽，确保关键业务最低吞吐
    # ceil=35Mbps：可借用上限，不超过总出口
    r1.cmd(f"tc class add dev {server_intf} parent 1:1 classid 1:10 htb "
           f"rate 12mbit ceil {BOTTLENECK_BW}mbit prio 0")
    r1.cmd(f"tc qdisc add dev {server_intf} parent 1:10 handle 10: sfq perturb 10")

    # === 子类 2：普通业务（中等优先级）===
    # rate=15Mbps：保底带宽；ceil=28Mbps：为财务处预留借用空间
    r1.cmd(f"tc class add dev {server_intf} parent 1:1 classid 1:20 htb "
           f"rate 15mbit ceil 28mbit prio 1")
    r1.cmd(f"tc qdisc add dev {server_intf} parent 1:20 handle 20: sfq perturb 10")

    # === 子类 3：UDP/背景流（最低优先级）===
    # rate=6Mbps：保底带宽；ceil=20Mbps：允许短时突发吸收
    r1.cmd(f"tc class add dev {server_intf} parent 1:1 classid 1:30 htb "
           f"rate 6mbit ceil 20mbit prio 2")
    r1.cmd(f"tc qdisc add dev {server_intf} parent 1:30 handle 30: sfq perturb 10")

    # === 过滤器：按源 IP 分类到对应 HTB 子类 ===
    r1.cmd(f"tc filter add dev {server_intf} parent 1: protocol ip prio 1 u32 "
           f"match ip src 10.0.5.0/24 flowid 1:10")
    r1.cmd(f"tc filter add dev {server_intf} parent 1: protocol ip prio 2 u32 "
           f"match ip src 10.0.1.0/24 flowid 1:30")
    r1.cmd(f"tc filter add dev {server_intf} parent 1: protocol ip prio 10 u32 "
           f"match ip src 0.0.0.0/0 flowid 1:20")

    info(f"[QOS] HTB QoS 已生效：r1-eth5 出口 {BOTTLENECK_BW}Mbps\n"
         f"      财务处→class 1:10 rate=12Mbps ceil=35Mbps prio=0（最高优先+保底）\n"
         f"      普通业务→class 1:20 rate=15Mbps ceil=28Mbps prio=1\n"
         f"      UDP/背景流→class 1:30 rate=6Mbps  ceil=20Mbps prio=2（最低优先）\n"
         f"      三层 rate 合计 33Mbps < 35Mbps（欠分配），各 class 内 sfq 防 TCP 踩踏\n")


# ==================== iperf3 服务管理 ====================

def start_dual_server_iperf(net, server1, server2, clients=COMPETING_CLIENTS):
    """
    在两个服务入口上启动 iperf3 服务。
    """
    info("[QOS] 在两个服务入口启动 iperf3 服务...\n")
    servers_by_ip = {
        "10.0.100.2": server1,
        "10.0.100.3": server2,
    }
    ports_by_server = {}
    for client_spec in clients:
        _, target_ip, *_ = client_spec
        ports_by_server.setdefault(target_ip, set()).add(get_iperf_port(client_spec))

    for srv in [server1, server2]:
        srv.cmd("pkill -f iperf3 2>/dev/null || true")
    for target_ip, ports in ports_by_server.items():
        srv = servers_by_ip.get(target_ip)
        if srv is None:
            continue
        for port in sorted(ports):
            srv.cmd(f"iperf3 -s -p {port} -D")
    time.sleep(1)
    info("[QOS] 双入口 iperf3 已就绪\n")


# ==================== 动态流量生成（泊松到达）====================

def run_competitive_measurement(net, clients, duration, mode="baseline"):
    """
    使用泊松到达模型进行动态竞争流量测试。

    每个客户端在泊松分布的随机时刻发起 iperf3 流，
    形成动态的、不可预测的竞争模式，更接近真实校园网场景。

    参数:
        net:      Mininet 网络对象
        clients:  客户端配置列表（7 元组格式）
        duration: 每轮测试时长（秒）
        mode:     "baseline" 或 "qos"（仅用于日志显示）

    返回:
        dict: {
            client_name: {
                "throughput_mbps": float,
                "jitter_ms": float | None,     # 仅 UDP
                "lost_percent": float | None,   # 仅 UDP
            }
        }
    """
    # 重新启动两个服务入口的 iperf3（确保干净状态）
    server1 = net.get("server1")
    server2 = net.get("server2")
    start_dual_server_iperf(net, server1, server2, clients)

    results_lock = threading.Lock()
    flow_samples = {client_spec[0]: [] for client_spec in clients}
    end_time = time.time() + duration

    def run_iperf(client, cmd):
        """用 popen 运行 iperf，允许同一主机上 TCP 业务和 UDP 探针并发。"""
        proc = client.popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        output, _ = proc.communicate()
        return output or ""

    def build_iperf_cmd(target_ip, port, protocol, target_bw):
        if protocol == "udp":
            # UDP 使用随机带宽 6-9 Mbps，避免持续压满 HTB 上限
            bw = random.randint(6, 9)
            return (f"iperf3 -c {target_ip} -p {port} "
                    f"-t {FLOW_DURATION} -u -b {bw}M -J")

        # TCP 不使用 -b：让拥塞控制在瓶颈链路上自然竞争，避免“软写死”带宽。
        return f"iperf3 -c {target_ip} -p {port} -t {FLOW_DURATION} -J"

    def parse_flow_result(result, protocol):
        if protocol == "udp":
            return parse_udp_iperf_output(result)

        tp = parse_iperf_output(result)
        return {"throughput_mbps": tp} if tp is not None else None

    def run_client_poisson(client_name, target_ip, port, description, protocol, target_bw):
        """持续泊松到达：实验窗口内反复产生短流。"""
        host_name = CLIENT_HOSTS.get(client_name, client_name)
        client = net.get(host_name)
        flow_index = 0

        while time.time() < end_time:
            delay = random.expovariate(POISSON_LAMBDA[client_name])
            if time.time() + delay >= end_time:
                break

            info(f"  [POISSON] {description} 下一条流 {delay:.2f}s 后到达\n")
            time.sleep(delay)

            cmd = build_iperf_cmd(target_ip, port, protocol, target_bw)
            flow_index += 1
            if protocol == "udp":
                flow_desc = f"{protocol.upper()} {target_bw}Mbps"
            else:
                flow_desc = "TCP 自适应"
            info(f"  [FLOW] {description} #{flow_index} 开始 ({flow_desc}, {FLOW_DURATION}s)\n")

            result = run_iperf(client, cmd)
            parsed = parse_flow_result(result, protocol)

            with results_lock:
                if parsed:
                    flow_samples[client_name].append(parsed)
                    if protocol == "udp":
                        info(f"  [DONE] {description} #{flow_index}: "
                             f"{parsed['throughput_mbps']:.2f} Mbps, "
                             f"抖动 {parsed['jitter_ms']:.2f} ms, "
                             f"丢包 {parsed['lost_percent']:.2f}%\n")
                    else:
                        info(f"  [DONE] {description} #{flow_index}: "
                             f"{parsed['throughput_mbps']:.2f} Mbps\n")
                else:
                    debug_info = result[:200].replace('\n', ' | ')
                    info(f"  [DONE] {description} #{flow_index}: 解析失败 ({debug_info})\n")

    threads = []
    for client_spec in clients:
        client_name, target_ip, description, entrance = client_spec[:4]
        port = get_iperf_port(client_spec)
        protocol = get_protocol(client_spec)
        target_bw = get_target_bw(client_spec)

        t = threading.Thread(
            target=run_client_poisson,
            args=(client_name, target_ip, port, description, protocol, target_bw),
            daemon=True
        )
        threads.append(t)

    # 随机打乱启动顺序，避免固定顺序的系统性偏差
    random.shuffle(threads)

    info(f"[QOS] 启动 {len(threads)} 个客户端泊松流生成器，持续 {duration}s...\n")
    for t in threads:
        t.start()

    # 等待所有线程完成
    for t in threads:
        t.join()

    results = {}
    for client_spec in clients:
        client_name = client_spec[0]
        protocol = get_protocol(client_spec)
        samples = flow_samples.get(client_name, [])
        if not samples:
            results[client_name] = None
            continue

        results[client_name] = {
            "throughput_mbps": (
                sum(s["throughput_mbps"] for s in samples) / len(samples)
            ),
            "flow_count": len(samples),
        }
        if protocol == "udp":
            results[client_name]["jitter_ms"] = (
                sum(s["jitter_ms"] for s in samples) / len(samples)
            )
            results[client_name]["lost_percent"] = (
                sum(s["lost_percent"] for s in samples) / len(samples)
            )
            results[client_name]["sender_mbps"] = (
                sum(s.get("sender_mbps", 0) for s in samples) / len(samples)
            )

    info(f"[QOS]   所有客户端泊松流测试完成\n")
    return results


# ==================== 时延测量 ====================

def run_latency_measurement(net, clients, target_ip, measure_after=2):
    """
    在拥塞期间测量各客户端到服务器的时延。

    在流量已经开始竞争后，通过 ping 测量各区域的 RTT，
    反映不同调度策略下关键业务的时延表现。

    参数:
        net:           Mininet 网络对象
        clients:       客户端配置列表
        target_ip:     目标服务器 IP
        measure_after: 开始测量前的等待时间（秒），确保拥塞已形成

    返回:
        dict: {client_name: avg_rtt_ms}
    """
    info("[QOS] 等待拥塞稳定后测量时延...\n")
    time.sleep(measure_after)

    results_lock = threading.Lock()
    latencies = {}

    def ping_one(client_name, description):
        host_name = CLIENT_HOSTS.get(client_name, client_name)
        client = net.get(host_name)
        result = client.cmd(f"ping -c {PING_COUNT} -i {PING_INTERVAL} {target_ip}")
        rtt = parse_ping_output(result)
        with results_lock:
            latencies[client_name] = rtt
        if rtt is not None:
            info(f"  [PING] {description}: 平均 {rtt:.2f} ms\n")
        else:
            info(f"  [PING] {description}: 解析失败\n")

    threads = []
    measured_hosts = set()
    alias_clients = []
    for client_spec in clients:
        client_name, _, description, _ = client_spec[:4]
        host_name = CLIENT_HOSTS.get(client_name, client_name)
        if host_name in measured_hosts:
            alias_clients.append((client_name, host_name, description))
            continue
        measured_hosts.add(host_name)
        t = threading.Thread(
            target=ping_one,
            args=(client_name, description),
            daemon=True
        )
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    for client_name, host_name, description in alias_clients:
        latencies[client_name] = latencies.get(host_name)
        if latencies[client_name] is not None:
            info(f"  [PING] {description}: 复用 {host_name} RTT "
                 f"{latencies[client_name]:.2f} ms\n")

    return latencies


def run_competition_with_latency(net, clients, duration, mode, ping_target_ip,
                                 stats_callback=None):
    """
    同时运行竞争流量和 ping，确保 RTT 测到的是拥塞期而非空闲网络。
    """
    traffic_results = {}

    def traffic_worker():
        nonlocal traffic_results
        traffic_results = run_competitive_measurement(net, clients, duration, mode)

    traffic_thread = threading.Thread(target=traffic_worker, daemon=True)
    traffic_thread.start()

    latency_results = run_latency_measurement(
        net, clients, ping_target_ip, measure_after=2
    )

    qdisc_stats = stats_callback() if stats_callback else ""

    traffic_thread.join()
    return traffic_results, latency_results, qdisc_stats


def collect_qdisc_stats(r1, label, server_intf="r1-eth5"):
    """采集瓶颈出口队列、HTB 类和过滤器统计，用于定位限速/分类是否生效。"""
    stats = {
        "qdisc": r1.cmd(f"tc -s qdisc show dev {server_intf}"),
        "class": r1.cmd(f"tc -s class show dev {server_intf}"),
        "filter": r1.cmd(f"tc filter show dev {server_intf}"),
        "route_to_server1": r1.cmd("ip route get 10.0.100.2"),
        "route_to_server2": r1.cmd("ip route get 10.0.100.3"),
    }
    info(f"\n[QOS] {label} 队列统计 ({server_intf}):\n{stats['qdisc']}\n")
    info(f"[QOS] {label} HTB 类统计 ({server_intf}):\n{stats['class']}\n")
    info(f"[QOS] {label} 过滤器配置 ({server_intf}):\n{stats['filter']}\n")
    info(f"[QOS] {label} 到 server1/server2 路由:\n"
         f"{stats['route_to_server1']}{stats['route_to_server2']}\n")
    return stats


# ==================== 主实验函数 ====================

def run_qos_test(server_ip="10.0.100.2", duration=TOTAL_EXPERIMENT_TIME):
    """
    运行 QoS 对比实验（优先级队列消融实验版）。

    ============================================================
    实验架构（三个独立 Mininet 实例，严格隔离）：
    ============================================================

    实例1 — Baseline（pfifo）:
      出口链路 r1-eth5: 35Mbps（制造拥塞）
      队列策略: pfifo（先进先出）
      所有流量公平排队，无优先级

    实例2 — prio QoS（严格优先级抢占）:
      出口链路 r1-eth5: 35Mbps（与 Baseline 相同）
      队列策略: prio（严格优先级）
      财务处流量 → band 0（最高优先），其余 → band 1（普通）
      band 0 有包时 band 1 完全不服务

    实例3 — HTB QoS（资源分配型调度）:
      出口链路 r1-eth5: 35Mbps（与 Baseline 相同）
      队列策略: HTB 三层类（财务 prio=0 / 普通 prio=1 / UDP prio=2）+ sfq
      财务处: 保底 12Mbps，拥塞时优先借用闲置带宽
      普通业务: 保底 15Mbps，中等优先级
      UDP/背景流: 保底 6Mbps，最低优先级
      每类内部 sfq 防 TCP 踩踏

    三个实例使用完全相同的拓扑和客户端映射，
    仅调度策略不同——这是标准的**消融实验**设计。

    ============================================================
    测量指标（每个客户端）：
    ============================================================
    1. 吞吐量 (Throughput): iperf3 TCP/UDP 实测带宽 (Mbps)
    2. 时延 (Latency):      ping 平均 RTT (ms)
    3. 抖动 (Jitter):       UDP iperf3 jitter_ms（宿舍区 + 财务 UDP 探针）
    4. 丢包率 (Packet Loss): UDP iperf3 lost_percent（宿舍区 + 财务 UDP 探针）

    ============================================================

    参数:
        server_ip: 兼容旧接口，保留参数
        duration:  每轮总实验时长（秒）

    返回:
        results: CSV 格式的结果列表
    """
    ts = timestamp()
    print_separator(f"QoS 对比实验 — 优先级队列消融实验 ({ts})")

    # ---- CSV 表头（四维指标）----
    headers = [
        "实验组", "客户端", "测试区域", "服务入口",
        "协议", "吞吐量(Mbps)", "时延(ms)",
        "抖动(ms)", "丢包率(%)"
    ]
    results = []
    raw_data = {
        "实验时间": ts,
        "实验时长(s)": duration,
        "瓶颈带宽(Mbps)": BOTTLENECK_BW,
        "流量模型": "泊松到达",
        "说明": "三组对比：1)Baseline=pfifo无优先级; 2)prio QoS=严格优先级(财务→band0); 3)HTB QoS=软优先级(财务12Mbps/普通15Mbps/UDP3Mbps)+sfq",
        "QoS策略说明": {
            "Baseline": "pfifo 先进先出，无优先级调度",
            "prio QoS": "prio 严格优先级，财务→band 0，其余→band 1",
            "HTB QoS": "HTB 分层：财务rate=12Mbps ceil=35Mbps prio=0; 普通rate=15Mbps ceil=28Mbps prio=1; UDP rate=6Mbps ceil=20Mbps prio=2; 各class内sfq",
        },
        "统一静态入口映射": UNIFIED_STATIC_MAPPING,
        "参数": {
            "FLOW_DURATION": FLOW_DURATION,
            "TOTAL_EXPERIMENT_TIME": TOTAL_EXPERIMENT_TIME,
            "POISSON_LAMBDA": POISSON_LAMBDA,
            "UDP发送端速率说明": "UDP 吞吐量优先采用 iperf3 end.sum_received；sender_mbps 仅用于诊断",
        },
        "数据": []
    }

    # ============================================================
    # 第一阶段：Baseline（pfifo — 独立 Mininet 实例）
    # ============================================================
    info("\n" + "=" * 60 + "\n")
    info("  [阶段 1/3] Baseline：pfifo 先进先出队列\n")
    info("  队列策略：所有流量公平排队，无优先级调度\n")
    info(f"  出口瓶颈：r1-eth5 = {BOTTLENECK_BW}Mbps（适度拥塞）\n")
    info("=" * 60 + "\n")

    net1, r1, server1a, server2a = create_fresh_network()
    start_dual_server_services(server1a, server2a)
    apply_all_security(r1, with_qos=False)
    apply_baseline_policy(r1)
    time.sleep(2)

    baseline_tps = {}
    baseline_latencies = {}
    baseline_qdisc_stats = {}
    try:
        # 动态竞争测试 + 拥塞期时延测量（并发）
        info("[QOS] 启动 Baseline 动态竞争流量（泊松到达模型）...\n")
        baseline_tps, baseline_latencies, baseline_qdisc_stats = run_competition_with_latency(
            net1, COMPETING_CLIENTS, duration, "baseline", "10.0.100.2",
            stats_callback=lambda: collect_qdisc_stats(r1, "Baseline 拥塞期")
        )
    finally:
        cleanup_network(r1)
        net1.stop()
        info("[QOS] Baseline 实例已清理\n")

    time.sleep(2)

    # ============================================================
    # 第二阶段：prio QoS（严格优先级 — 独立 Mininet 实例）
    # ============================================================
    info("\n" + "=" * 60 + "\n")
    info("  [阶段 2/3] prio QoS：严格优先级调度\n")
    info("  队列策略：财务处流量→band 0（最高优先），其余→band 1\n")
    info(f"  出口瓶颈：r1-eth5 = {BOTTLENECK_BW}Mbps（与 Baseline 一致）\n")
    info("=" * 60 + "\n")

    net2, r2, server1b, server2b = create_fresh_network()
    start_dual_server_services(server1b, server2b)
    apply_all_security(r2, with_qos=False)
    apply_qos_policy(r2)
    time.sleep(2)

    prio_tps = {}
    prio_latencies = {}
    prio_qdisc_stats = {}
    try:
        # 动态竞争测试 + 拥塞期时延测量（并发）
        info("[QOS] 启动 prio QoS 动态竞争流量（泊松到达模型）...\n")
        prio_tps, prio_latencies, prio_qdisc_stats = run_competition_with_latency(
            net2, COMPETING_CLIENTS, duration, "prio_qos", "10.0.100.2",
            stats_callback=lambda: collect_qdisc_stats(r2, "prio QoS 拥塞期")
        )
    finally:
        cleanup_network(r2)
        net2.stop()
        info("[QOS] prio QoS 实例已清理\n")

    time.sleep(2)

    # ============================================================
    # 第三阶段：HTB QoS（资源分配型 — 独立 Mininet 实例）
    # ============================================================
    info("\n" + "=" * 60 + "\n")
    info("  [阶段 3/3] HTB QoS：分层 + 软优先级（保底带宽 + sfq）\n")
    info("  队列策略：财务prio=0保底12Mbps / 普通prio=1保底15Mbps / UDP prio=2保底6Mbps\n")
    info("  每类内部 sfq 公平队列，防止 TCP 流间踩踏\n")
    info(f"  出口瓶颈：r1-eth5 = {BOTTLENECK_BW}Mbps（与 Baseline 一致）\n")
    info("=" * 60 + "\n")

    net3, r3, server1c, server2c = create_fresh_network()
    start_dual_server_services(server1c, server2c)
    apply_all_security(r3, with_qos=False)
    apply_htb_policy(r3)
    time.sleep(2)

    htb_tps = {}
    htb_latencies = {}
    htb_qdisc_stats = {}
    try:
        # 动态竞争测试 + 拥塞期时延测量（并发）
        info("[QOS] 启动 HTB QoS 动态竞争流量（泊松到达模型）...\n")
        htb_tps, htb_latencies, htb_qdisc_stats = run_competition_with_latency(
            net3, COMPETING_CLIENTS, duration, "htb_qos", "10.0.100.2",
            stats_callback=lambda: collect_qdisc_stats(r3, "HTB QoS 拥塞期")
        )
    finally:
        cleanup_network(r3)
        net3.stop()
        info("[QOS] HTB QoS 实例已清理\n")

    # ============================================================
    # 结果汇总
    # ============================================================

    # ---- 构造 CSV 行 ----
    for client_spec in COMPETING_CLIENTS:
        client_name, _, description, entrance = client_spec[:4]
        protocol = get_protocol(client_spec)

        # 无 QoS 数据
        tp = baseline_tps.get(client_name)
        lat = baseline_latencies.get(client_name)
        if tp is not None:
            jitter = tp.get("jitter_ms") if isinstance(tp, dict) else None
            loss = tp.get("lost_percent") if isinstance(tp, dict) else None
            tp_val = tp.get("throughput_mbps") if isinstance(tp, dict) else tp
        else:
            jitter = loss = tp_val = None

        results.append([
            "无 QoS", client_name, description, entrance, protocol,
            round(tp_val, 2) if tp_val is not None else "N/A",
            round(lat, 2) if lat is not None else "N/A",
            round(jitter, 2) if jitter is not None else "N/A",
            round(loss, 2) if loss is not None else "N/A",
        ])

    for client_spec in COMPETING_CLIENTS:
        client_name, _, description, entrance = client_spec[:4]
        protocol = get_protocol(client_spec)

        # prio QoS 数据
        tp = prio_tps.get(client_name)
        lat = prio_latencies.get(client_name)
        if tp is not None:
            jitter = tp.get("jitter_ms") if isinstance(tp, dict) else None
            loss = tp.get("lost_percent") if isinstance(tp, dict) else None
            tp_val = tp.get("throughput_mbps") if isinstance(tp, dict) else tp
        else:
            jitter = loss = tp_val = None

        results.append([
            "prio QoS", client_name, description, entrance, protocol,
            round(tp_val, 2) if tp_val is not None else "N/A",
            round(lat, 2) if lat is not None else "N/A",
            round(jitter, 2) if jitter is not None else "N/A",
            round(loss, 2) if loss is not None else "N/A",
        ])

    for client_spec in COMPETING_CLIENTS:
        client_name, _, description, entrance = client_spec[:4]
        protocol = get_protocol(client_spec)

        # HTB QoS 数据
        tp = htb_tps.get(client_name)
        lat = htb_latencies.get(client_name)
        if tp is not None:
            jitter = tp.get("jitter_ms") if isinstance(tp, dict) else None
            loss = tp.get("lost_percent") if isinstance(tp, dict) else None
            tp_val = tp.get("throughput_mbps") if isinstance(tp, dict) else tp
        else:
            jitter = loss = tp_val = None

        results.append([
            "HTB QoS", client_name, description, entrance, protocol,
            round(tp_val, 2) if tp_val is not None else "N/A",
            round(lat, 2) if lat is not None else "N/A",
            round(jitter, 2) if jitter is not None else "N/A",
            round(loss, 2) if loss is not None else "N/A",
        ])

    # ---- 打印对比结果表格 ----
    print_separator("QoS 对比结果 — 四维指标")
    header_line = (f"{'区域':<28} {'协议':<6} {'入口':<6} "
                   f"{'吞吐量(Mbps)':<16} {'时延(ms)':<12} "
                   f"{'抖动(ms)':<12} {'丢包率(%)':<10}")
    info(header_line + "\n")
    info("-" * 90 + "\n")

    for client_spec in COMPETING_CLIENTS:
        client_name, _, description, entrance = client_spec[:4]
        protocol = get_protocol(client_spec)

        # Baseline 数据
        tp = baseline_tps.get(client_name)
        lat = baseline_latencies.get(client_name)
        if tp is not None:
            j = tp.get("jitter_ms") if isinstance(tp, dict) else None
            l = tp.get("lost_percent") if isinstance(tp, dict) else None
            t = tp.get("throughput_mbps") if isinstance(tp, dict) else tp
        else:
            j = l = t = None

        tp_q = prio_tps.get(client_name)
        lat_q = prio_latencies.get(client_name)
        if tp_q is not None:
            j_q = tp_q.get("jitter_ms") if isinstance(tp_q, dict) else None
            l_q = tp_q.get("lost_percent") if isinstance(tp_q, dict) else None
            t_q = tp_q.get("throughput_mbps") if isinstance(tp_q, dict) else tp_q
        else:
            j_q = l_q = t_q = None

        tp_h = htb_tps.get(client_name)
        lat_h = htb_latencies.get(client_name)
        if tp_h is not None:
            j_h = tp_h.get("jitter_ms") if isinstance(tp_h, dict) else None
            l_h = tp_h.get("lost_percent") if isinstance(tp_h, dict) else None
            t_h = tp_h.get("throughput_mbps") if isinstance(tp_h, dict) else tp_h
        else:
            j_h = l_h = t_h = None

        # 打印 Baseline 行
        t_str = f"{t:.2f}" if t is not None else "N/A"
        lat_str = f"{lat:.2f}" if lat is not None else "N/A"
        j_str = f"{j:.2f}" if j is not None else "N/A"
        l_str = f"{l:.2f}" if l is not None else "N/A"
        info(f"[Baseline] {description:<24} {protocol:<6} {entrance:<6} "
             f"{t_str:<16} {lat_str:<12} {j_str:<12} {l_str:<10}\n")

        # 打印 prio QoS 行
        t_q_str = f"{t_q:.2f}" if t_q is not None else "N/A"
        lat_q_str = f"{lat_q:.2f}" if lat_q is not None else "N/A"
        j_q_str = f"{j_q:.2f}" if j_q is not None else "N/A"
        l_q_str = f"{l_q:.2f}" if l_q is not None else "N/A"
        info(f"[prio QoS] {description:<22} {protocol:<6} {entrance:<6} "
             f"{t_q_str:<16} {lat_q_str:<12} {j_q_str:<12} {l_q_str:<10}\n")

        # 打印 HTB QoS 行
        t_h_str = f"{t_h:.2f}" if t_h is not None else "N/A"
        lat_h_str = f"{lat_h:.2f}" if lat_h is not None else "N/A"
        j_h_str = f"{j_h:.2f}" if j_h is not None else "N/A"
        l_h_str = f"{l_h:.2f}" if l_h is not None else "N/A"
        info(f"[HTB QoS]  {description:<22} {protocol:<6} {entrance:<6} "
             f"{t_h_str:<16} {lat_h_str:<12} {j_h_str:<12} {l_h_str:<10}\n")

        info("-" * 90 + "\n")

    # ---- 保存结果 ----
    csv_name = f"qos_test_{ts}.csv"
    save_to_csv(csv_name, headers, results)

    raw_data["数据"] = {
        "baseline": {
            "吞吐量": {
                k: (round(v["throughput_mbps"], 2) if isinstance(v, dict) and v else
                    round(v, 2) if v else None)
                for k, v in baseline_tps.items()
            },
            "时延_ms": {
                k: (round(v, 2) if v else None)
                for k, v in baseline_latencies.items()
            },
            "抖动_ms": {
                k: (round(v["jitter_ms"], 2) if isinstance(v, dict) and v
                    and v.get("jitter_ms") is not None else None)
                for k, v in baseline_tps.items()
            },
            "丢包率_percent": {
                k: (round(v["lost_percent"], 2) if isinstance(v, dict) and v
                    and v.get("lost_percent") is not None else None)
                for k, v in baseline_tps.items()
            },
            "UDP发送端速率_Mbps": {
                k: (round(v["sender_mbps"], 2) if isinstance(v, dict) and v
                    and v.get("sender_mbps") is not None else None)
                for k, v in baseline_tps.items()
            },
            "qdisc_stats": baseline_qdisc_stats,
        },
        "prio_qos": {
            "吞吐量": {
                k: (round(v["throughput_mbps"], 2) if isinstance(v, dict) and v else
                    round(v, 2) if v else None)
                for k, v in prio_tps.items()
            },
            "时延_ms": {
                k: (round(v, 2) if v else None)
                for k, v in prio_latencies.items()
            },
            "抖动_ms": {
                k: (round(v["jitter_ms"], 2) if isinstance(v, dict) and v
                    and v.get("jitter_ms") is not None else None)
                for k, v in prio_tps.items()
            },
            "丢包率_percent": {
                k: (round(v["lost_percent"], 2) if isinstance(v, dict) and v
                    and v.get("lost_percent") is not None else None)
                for k, v in prio_tps.items()
            },
            "UDP发送端速率_Mbps": {
                k: (round(v["sender_mbps"], 2) if isinstance(v, dict) and v
                    and v.get("sender_mbps") is not None else None)
                for k, v in prio_tps.items()
            },
            "qdisc_stats": prio_qdisc_stats,
        },
        "htb_qos": {
            "吞吐量": {
                k: (round(v["throughput_mbps"], 2) if isinstance(v, dict) and v else
                    round(v, 2) if v else None)
                for k, v in htb_tps.items()
            },
            "时延_ms": {
                k: (round(v, 2) if v else None)
                for k, v in htb_latencies.items()
            },
            "抖动_ms": {
                k: (round(v["jitter_ms"], 2) if isinstance(v, dict) and v
                    and v.get("jitter_ms") is not None else None)
                for k, v in htb_tps.items()
            },
            "丢包率_percent": {
                k: (round(v["lost_percent"], 2) if isinstance(v, dict) and v
                    and v.get("lost_percent") is not None else None)
                for k, v in htb_tps.items()
            },
            "UDP发送端速率_Mbps": {
                k: (round(v["sender_mbps"], 2) if isinstance(v, dict) and v
                    and v.get("sender_mbps") is not None else None)
                for k, v in htb_tps.items()
            },
            "qdisc_stats": htb_qdisc_stats,
        },
    }

    json_name = f"qos_test_{ts}.json"
    save_to_json(json_name, raw_data)

    info(f"\n[QOS] 实验完成！结果已保存到 {csv_name} 和 {json_name}\n")
    info("[QOS] 四维指标：吞吐量(Mbps) | 时延(ms) | 抖动(ms) | 丢包率(%)\n")

    return results


if __name__ == "__main__":
    info("请通过 main.py 运行此实验\n")
