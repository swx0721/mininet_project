"""
plot.py - 实验数据可视化模块

使用 matplotlib 将实验数据绘制成专业图表。
支持以下图表类型：
  1. 带宽 vs 实际吞吐量（折线图）
  2. 区域时延对比（柱状图）
  3. 并发用户数 vs 成功率（折线图）
  4. QoS 前后对比（分组柱状图）
  5. 安全策略有效性（对比图）

所有图表自动保存到 results/plots/ 目录。
"""

import os
import csv
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import RESULT_DIR, ensure_dirs
from mininet.log import info


# 图表输出目录
PLOT_DIR = os.path.join(RESULT_DIR, "plots")


def ensure_plot_dir():
    """确保图表目录存在。"""
    os.makedirs(PLOT_DIR, exist_ok=True)


def read_csv(filename):
    """
    读取 results/ 目录下的 CSV 文件。
    返回 (headers, rows)。
    """
    filepath = os.path.join(RESULT_DIR, filename)
    if not os.path.exists(filepath):
        info(f"[PLOT] 文件不存在: {filepath}\n")
        return None, None

    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        headers = next(reader)
        rows = [row for row in reader]

    return headers, rows


def plot_bandwidth_test(csv_file=None):
    """
    绘制带宽 vs 实际吞吐量折线图。

    参数:
        csv_file: CSV 文件名，None 则自动查找最新的带宽测试结果
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["SimHei", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
    except ImportError:
        info("[PLOT] 错误: 需要安装 matplotlib (pip install matplotlib)\n")
        return

    # 查找或使用指定的 CSV 文件
    if csv_file is None:
        csv_files = [f for f in os.listdir(RESULT_DIR)
                     if f.startswith("bandwidth_test_") and f.endswith(".csv")]
        if not csv_files:
            info("[PLOT] 未找到带宽测试结果文件，请先运行实验\n")
            return
        csv_file = sorted(csv_files)[-1]  # 最新的文件

    headers, rows = read_csv(csv_file)
    if not rows:
        return

    info(f"[PLOT] 绘制带宽测试图表: {csv_file}\n")

    # 解析数据（新格式: 配置带宽, 测试场景, 平均吞吐, 标准差, 测量次数）
    data = {}
    for row in rows:
        if len(row) < 3 or row[2] == "N/A":
            continue
        bw = float(row[0])
        scene = row[1]
        tp = float(row[2])
        std = float(row[3]) if len(row) > 3 and row[3] != "N/A" else 0
        if scene not in data:
            data[scene] = {"bw": [], "tp": [], "std": []}
        data[scene]["bw"].append(bw)
        data[scene]["tp"].append(tp)
        data[scene]["std"].append(std)

    # 绘图
    fig, ax = plt.subplots(figsize=(10, 6))

    colors = ["#1565C0", "#E53935", "#43A047", "#FB8C00", "#8E24AA"]
    for i, (scene, vals) in enumerate(data.items()):
        # 按带宽排序
        pairs = sorted(zip(vals["bw"], vals["tp"], vals["std"]))
        bws, tps, stds = zip(*pairs)
        ax.errorbar(bws, tps, yerr=stds, fmt="o-",
                    color=colors[i % len(colors)],
                    label=scene, linewidth=2, markersize=6,
                    capsize=4, capthick=1)

    ax.set_xlabel("链路带宽 (Mbps)", fontsize=12)
    ax.set_ylabel("实际吞吐量 (Mbps)", fontsize=12)
    ax.set_title("带宽 vs 实际吞吐量 (含标准差)", fontsize=14, fontweight="bold")
    ax.legend(loc="best", fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_xscale("log")
    ax.set_xticks([10, 20, 50, 100, 200, 500, 1000])
    ax.get_xaxis().set_major_formatter(
        plt.FuncFormatter(lambda x, _: f"{int(x)}"))

    # 添加理想线（y=x）
    all_tps = [t for v in data.values() for t in v["tp"]]
    all_bws = [b for v in data.values() for b in v["bw"]]
    if all_tps and all_bws:
        max_val = max(max(all_tps), max(all_bws))
        ax.plot([0, max_val], [0, max_val], "k--", alpha=0.3,
                label="理想吞吐量 (y=x)")

    plt.tight_layout()
    filepath = os.path.join(PLOT_DIR, "bandwidth_test.png")
    plt.savefig(filepath, dpi=150)
    info(f"[PLOT] 图表已保存: {filepath}\n")
    plt.close()


def plot_delay_test(csv_file=None):
    """
    绘制各区域时延对比柱状图。
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["SimHei", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
    except ImportError:
        info("[PLOT] 错误: 需要安装 matplotlib\n")
        return

    if csv_file is None:
        csv_files = [f for f in os.listdir(RESULT_DIR)
                     if f.startswith("delay_test_") and f.endswith(".csv")]
        if not csv_files:
            info("[PLOT] 未找到时延测试结果文件\n")
            return
        csv_file = sorted(csv_files)[-1]

    headers, rows = read_csv(csv_file)
    if not rows:
        return

    info(f"[PLOT] 绘制时延测试图表: {csv_file}\n")

    # 解析数据（新格式: 配置时延, 测试场景, 平均RTT, 丢包率, 测量次数）
    # 对每个测试场景，收集不同时延下的 RTT
    data_by_scene = {}
    for row in rows:
        if len(row) < 3 or row[2] == "超时":
            continue
        delay = float(row[0])
        scene = row[1]
        rtt = float(row[2])
        loss = float(row[3]) if row[3] not in ("N/A", "None") else 0
        if scene not in data_by_scene:
            data_by_scene[scene] = {"delay": [], "rtt": [], "loss": []}
        data_by_scene[scene]["delay"].append(delay)
        data_by_scene[scene]["rtt"].append(rtt)
        data_by_scene[scene]["loss"].append(loss)

    if not data_by_scene:
        info("[PLOT] 时延测试数据为空\n")
        return

    # 绘制折线图：RTT vs 配置时延
    fig, ax = plt.subplots(figsize=(10, 6))
    colors = ["#1565C0", "#E53935", "#43A047", "#FB8C00"]

    for i, (scene, vals) in enumerate(data_by_scene.items()):
        pairs = sorted(zip(vals["delay"], vals["rtt"]))
        delays, rtts = zip(*pairs)
        ax.plot(delays, rtts, "o-", color=colors[i % len(colors)],
                label=scene, linewidth=2, markersize=6)

    # 添加理论线 (RTT ≈ 2 × delay)
    all_delays = sorted(set(d for v in data_by_scene.values() for d in v["delay"]))
    if all_delays:
        ax.plot(all_delays, [2 * d for d in all_delays], "k--", alpha=0.3,
                label="理论 RTT (2×delay)")

    ax.set_xlabel("链路时延 (ms)", fontsize=12)
    ax.set_ylabel("平均 RTT (ms)", fontsize=12)
    ax.set_title("RTT vs 链路时延", fontsize=14, fontweight="bold")
    ax.legend(loc="best", fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_xscale("log")
    ax.set_xticks(all_delays)

    plt.tight_layout()
    filepath = os.path.join(PLOT_DIR, "delay_test.png")
    plt.savefig(filepath, dpi=150)
    info(f"[PLOT] 图表已保存: {filepath}\n")
    plt.close()


def plot_concurrency_test(csv_file=None):
    """
    绘制并发用户数 vs 成功率折线图。
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["SimHei", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
    except ImportError:
        info("[PLOT] 错误: 需要安装 matplotlib\n")
        return

    if csv_file is None:
        csv_files = [f for f in os.listdir(RESULT_DIR)
                     if f.startswith("concurrency_test_") and f.endswith(".csv")]
        if not csv_files:
            info("[PLOT] 未找到并发测试结果文件\n")
            return
        csv_file = sorted(csv_files)[-1]

    headers, rows = read_csv(csv_file)
    if not rows:
        return

    info(f"[PLOT] 绘制并发测试图表: {csv_file}\n")

    # 新格式: [并发用户数, 总请求数, 成功数, 成功率(%), 失败详情]
    users = []
    success_rates = []
    total_counts = []
    success_counts = []

    for row in rows:
        if len(row) < 4:
            continue
        users.append(int(row[0]))
        total_counts.append(int(row[1]))
        success_counts.append(int(row[2]))
        success_rates.append(float(row[3]))

    # 绘图
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # 左图：并发用户数 vs 成功率
    ax1.plot(users, success_rates, "o-", color="#1565C0",
             linewidth=2, markersize=8)
    ax1.set_xlabel("并发用户数", fontsize=12)
    ax1.set_ylabel("成功率 (%)", fontsize=12)
    ax1.set_title("并发用户数 vs 请求成功率", fontsize=13, fontweight="bold")
    ax1.set_ylim(0, 105)
    ax1.grid(True, alpha=0.3)
    ax1.set_xticks(users)

    for x, y in zip(users, success_rates):
        ax1.text(x, y + 2, f"{y:.1f}%", ha="center", fontsize=9)

    # 右图：并发用户数 vs 请求总数/成功数
    ax2.plot(users, total_counts, "s--", color="#FB8C00",
             label="总请求数", linewidth=2, markersize=6)
    ax2.plot(users, success_counts, "o-", color="#43A047",
             label="成功请求数", linewidth=2, markersize=6)
    ax2.set_xlabel("并发用户数", fontsize=12)
    ax2.set_ylabel("请求数", fontsize=12)
    ax2.set_title("并发用户数 vs 请求数", fontsize=13, fontweight="bold")
    ax2.grid(True, alpha=0.3)
    ax2.set_xticks(users)
    ax2.legend(fontsize=10)

    plt.tight_layout()
    filepath = os.path.join(PLOT_DIR, "concurrency_test.png")
    plt.savefig(filepath, dpi=150)
    info(f"[PLOT] 图表已保存: {filepath}\n")
    plt.close()


def plot_qos_comparison(csv_file=None):
    """
    绘制 QoS 四维指标对比图表。

    新 CSV 格式:
      实验组, 客户端, 测试区域, 服务入口, 协议,
      吞吐量(Mbps), 时延(ms), 抖动(ms), 丢包率(%)

    生成 2 张图:
      1. qos_throughput_latency.png — 吞吐量 + 时延对比
      2. qos_jitter_loss.png — 抖动 + 丢包率对比（仅 UDP 客户端）
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["SimHei", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
    except ImportError:
        info("[PLOT] 错误: 需要安装 matplotlib\n")
        return

    if csv_file is None:
        csv_files = [f for f in os.listdir(RESULT_DIR)
                     if f.startswith("qos_test_") and f.endswith(".csv")]
        if not csv_files:
            info("[PLOT] 未找到 QoS 测试结果文件\n")
            return
        csv_file = sorted(csv_files)[-1]

    headers, rows = read_csv(csv_file)
    if not rows:
        return

    info(f"[PLOT] 绘制 QoS 对比图表: {csv_file}\n")

    # 新格式索引:
    # 0:实验组 1:客户端 2:测试区域 3:服务入口 4:协议
    # 5:吞吐量(Mbps) 6:时延(ms) 7:抖动(ms) 8:丢包率(%)
    COL_GROUP = 0
    COL_SCENE = 2
    COL_PROTO = 4
    COL_TP = 5
    COL_LAT = 6
    COL_JIT = 7
    COL_LOSS = 8

    # 解析数据
    scenes_ordered = []
    scene_set = set()
    baseline = {}  # scene -> {tp, lat, jitter, loss}
    qos = {}       # scene -> {tp, lat, jitter, loss}

    for row in rows:
        if len(row) < 9:
            continue
        group = row[COL_GROUP]
        scene = row[COL_SCENE]
        if scene not in scene_set:
            scene_set.add(scene)
            scenes_ordered.append(scene)

        def safe_float(val):
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        entry = {
            "tp": safe_float(row[COL_TP]),
            "lat": safe_float(row[COL_LAT]),
            "jitter": safe_float(row[COL_JIT]),
            "loss": safe_float(row[COL_LOSS]),
        }

        if group == "无 QoS":
            baseline[scene] = entry
        elif group == "有 QoS":
            qos[scene] = entry

    if not scenes_ordered:
        info("[PLOT] QoS 数据为空\n")
        return

    # ========================================
    # 图1：吞吐量 + 时延对比（2 个子图）
    # ========================================
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    scenes = scenes_ordered
    x = range(len(scenes))
    width = 0.35

    # 短标签（去掉括号内的详细说明）
    short_labels = [s.split("(")[0].strip() for s in scenes]

    # --- 子图1：吞吐量对比 ---
    tp_base = [baseline[s]["tp"] if s in baseline and baseline[s]["tp"] is not None else 0
               for s in scenes]
    tp_qos = [qos[s]["tp"] if s in qos and qos[s]["tp"] is not None else 0
              for s in scenes]

    bars1 = ax1.bar([i - width / 2 for i in x], tp_base, width,
                    label="Baseline (pfifo)", color="#E53935", alpha=0.8)
    bars2 = ax1.bar([i + width / 2 for i in x], tp_qos, width,
                    label="QoS (prio)", color="#1565C0", alpha=0.8)

    ax1.set_ylabel("吞吐量 (Mbps)", fontsize=12)
    ax1.set_title("吞吐量对比", fontsize=13, fontweight="bold")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(short_labels, fontsize=9, rotation=15)
    ax1.legend(fontsize=10)
    ax1.grid(True, alpha=0.3, axis="y")

    for bar, val in zip(bars1, tp_base):
        if val > 0:
            ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                     f"{val:.1f}", ha="center", fontsize=8)
    for bar, val in zip(bars2, tp_qos):
        if val > 0:
            ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                     f"{val:.1f}", ha="center", fontsize=8)

    # --- 子图2：时延对比 ---
    lat_base = [baseline[s]["lat"] if s in baseline and baseline[s]["lat"] is not None else 0
                for s in scenes]
    lat_qos = [qos[s]["lat"] if s in qos and qos[s]["lat"] is not None else 0
               for s in scenes]

    bars3 = ax2.bar([i - width / 2 for i in x], lat_base, width,
                    label="Baseline (pfifo)", color="#E53935", alpha=0.8)
    bars4 = ax2.bar([i + width / 2 for i in x], lat_qos, width,
                    label="QoS (prio)", color="#1565C0", alpha=0.8)

    ax2.set_ylabel("平均 RTT (ms)", fontsize=12)
    ax2.set_title("时延对比", fontsize=13, fontweight="bold")
    ax2.set_xticks(list(x))
    ax2.set_xticklabels(short_labels, fontsize=9, rotation=15)
    ax2.legend(fontsize=10)
    ax2.grid(True, alpha=0.3, axis="y")

    for bar, val in zip(bars3, lat_base):
        if val > 0:
            ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                     f"{val:.1f}", ha="center", fontsize=8)
    for bar, val in zip(bars4, lat_qos):
        if val > 0:
            ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                     f"{val:.1f}", ha="center", fontsize=8)

    plt.tight_layout()
    filepath = os.path.join(PLOT_DIR, "qos_throughput_latency.png")
    plt.savefig(filepath, dpi=150)
    info(f"[PLOT] 图表已保存: {filepath}\n")
    plt.close()

    # ========================================
    # 图2：抖动 + 丢包率对比（仅 UDP 客户端）
    # ========================================
    # 找出有 UDP 抖动/丢包数据的客户端
    udp_scenes = []
    for s in scenes:
        b_jitter = baseline.get(s, {}).get("jitter")
        q_jitter = qos.get(s, {}).get("jitter")
        if b_jitter is not None or q_jitter is not None:
            udp_scenes.append(s)

    if udp_scenes:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))

        ux = range(len(udp_scenes))
        u_short = [s.split("(")[0].strip() for s in udp_scenes]

        # 抖动
        jit_base = [baseline[s]["jitter"] if s in baseline
                    and baseline[s]["jitter"] is not None else 0 for s in udp_scenes]
        jit_qos = [qos[s]["jitter"] if s in qos
                   and qos[s]["jitter"] is not None else 0 for s in udp_scenes]

        ax1.bar([i - width / 2 for i in ux], jit_base, width,
                label="Baseline (pfifo)", color="#E53935", alpha=0.8)
        ax1.bar([i + width / 2 for i in ux], jit_qos, width,
                label="QoS (prio)", color="#1565C0", alpha=0.8)
        ax1.set_ylabel("抖动 (ms)", fontsize=12)
        ax1.set_title("抖动对比 (UDP)", fontsize=13, fontweight="bold")
        ax1.set_xticks(list(ux))
        ax1.set_xticklabels(u_short, fontsize=10)
        ax1.legend(fontsize=10)
        ax1.grid(True, alpha=0.3, axis="y")

        # 丢包率
        loss_base = [baseline[s]["loss"] if s in baseline
                     and baseline[s]["loss"] is not None else 0 for s in udp_scenes]
        loss_qos = [qos[s]["loss"] if s in qos
                    and qos[s]["loss"] is not None else 0 for s in udp_scenes]

        ax2.bar([i - width / 2 for i in ux], loss_base, width,
                label="Baseline (pfifo)", color="#E53935", alpha=0.8)
        ax2.bar([i + width / 2 for i in ux], loss_qos, width,
                label="QoS (prio)", color="#1565C0", alpha=0.8)
        ax2.set_ylabel("丢包率 (%)", fontsize=12)
        ax2.set_title("丢包率对比 (UDP)", fontsize=13, fontweight="bold")
        ax2.set_xticks(list(ux))
        ax2.set_xticklabels(u_short, fontsize=10)
        ax2.legend(fontsize=10)
        ax2.grid(True, alpha=0.3, axis="y")

        plt.tight_layout()
        filepath = os.path.join(PLOT_DIR, "qos_jitter_loss.png")
        plt.savefig(filepath, dpi=150)
        info(f"[PLOT] 图表已保存: {filepath}\n")
        plt.close()
    else:
        info("[PLOT] 无 UDP 抖动/丢包数据，跳过抖动丢包图\n")


def plot_all():
    """一键绘制所有图表。"""
    ensure_plot_dir()
    info("[PLOT] 开始绘制所有图表...\n")
    plot_bandwidth_test()
    plot_delay_test()
    plot_concurrency_test()
    plot_qos_comparison()
    info(f"[PLOT] 所有图表已保存到 {PLOT_DIR}\n")


if __name__ == "__main__":
    plot_all()
