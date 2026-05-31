"""
automation.py - 自动化实验脚本（严格隔离版）

核心架构变更：
  每个实验使用独立的 Mininet 实例，实验之间物理隔离。
  不存在共享的 net/r1/server 对象。

实验生命周期（每个实验）：
  1. cleanup_all()     — 全局清理残留（mn -c + iptables flush）
  2. create_fresh_network() — 创建全新 Mininet 实例
  3. 启动服务 + 安全策略
  4. 执行测试
  5. cleanup_network() — 清理路由器残留
  6. net.stop()        — 关闭 Mininet 实例

使用方式：
    python main.py --auto             # 运行所有实验
    python main.py --auto --experiment qos  # 仅运行 QoS 实验
"""

import time
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mininet.log import info
from utils import (
    print_separator, timestamp, format_duration, ensure_dirs,
    save_to_csv
)
from experiments.qos_test import run_qos_test
from experiments.load_balance_test import run_load_balance_test


AVAILABLE_EXPERIMENTS = {
    "qos":          "QoS 对比实验 (财务处优先)",
    "load_balance": "负载均衡对比实验 (热点流量)",
}

# 每个实验的默认参数
EXPERIMENT_CONFIG = {
    "qos":         {"duration": 20},
    "load_balance": {"duration": 60},
}


def run_all_experiments(selected=None):
    """
    运行所有（或选定的）实验。

    所有实验均为自包含模式，各自管理独立的 Mininet 实例。

    参数:
        selected: 要运行的实验名称列表，None 表示全部
    """
    if selected is None:
        selected = list(AVAILABLE_EXPERIMENTS.keys())

    server_ip = "10.0.100.2"
    start_time = time.time()

    print_separator("自动化实验套件（严格隔离模式）", 70)
    info(f"开始时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    info(f"计划运行的实验: {', '.join(selected)}\n")
    info("隔离策略: 每个实验使用独立 Mininet 实例\n")
    info("          实验间自动执行 mn -c + iptables flush\n")
    print_separator()

    results_summary = []

    # QoS 对比实验（自包含，双实例隔离）
    if "qos" in selected:
        info(f"\n{'='*60}\n")
        info(f"  实验 1: QoS 对比实验（双独立实例）\n")
        info(f"{'='*60}\n")
        try:
            qos_results = run_qos_test(
                server_ip=server_ip,
                duration=EXPERIMENT_CONFIG["qos"]["duration"],
            )
            results_summary.append(
                ("QoS 对比实验", "完成", f"{len(qos_results)} 条记录")
            )
        except Exception as e:
            info(f"[AUTO] QoS 对比实验失败: {e}\n")
            results_summary.append(("QoS 对比实验", "失败", str(e)))
        time.sleep(2)

    # 负载均衡对比实验（自包含，双实例隔离）
    if "load_balance" in selected:
        info(f"\n{'='*60}\n")
        info(f"  实验 2: 负载均衡对比实验（双独立实例）\n")
        info(f"{'='*60}\n")
        try:
            lb_results = run_load_balance_test(
                duration=EXPERIMENT_CONFIG["load_balance"]["duration"],
            )
            results_summary.append(
                ("负载均衡对比实验", "完成", f"{len(lb_results)} 条记录")
            )
        except Exception as e:
            info(f"[AUTO] 负载均衡对比实验失败: {e}\n")
            results_summary.append(("负载均衡对比实验", "失败", str(e)))
        time.sleep(2)

    # ---- 实验总结 ----
    elapsed = time.time() - start_time
    print_separator("实验完成总结", 60)
    info(f"总耗时: {format_duration(elapsed)}\n")
    info(f"\n{'实验名称':<20} {'状态':<8} {'详情':<20}\n")
    info("-" * 48 + "\n")
    for name, status, detail in results_summary:
        info(f"{name:<20} {status:<8} {str(detail):<20}\n")
    info("\n")

    # 生成实验结果 CSV 汇总
    summary_file = f"experiment_summary_{timestamp()}.csv"
    save_to_csv(summary_file,
                ["实验名称", "状态", "详情"],
                [[n, s, str(d)] for n, s, d in results_summary])
    info(f"[AUTO] 实验汇总已保存到 {summary_file}\n")

    return results_summary


def run_automation(experiments=None):
    """
    自动化入口：依次运行各实验，每个实验使用独立网络。

    参数:
        experiments: 要运行的实验名称列表，None 表示全部
    """
    ensure_dirs()

    if experiments is None:
        experiments = list(AVAILABLE_EXPERIMENTS.keys())

    info("[AUTO] 启动自动化实验（严格隔离模式）\n")
    info("[AUTO] 每个实验使用独立的 Mininet 实例\n")
    info("[AUTO] 实验之间自动执行全局清理（mn -c）\n")

    try:
        run_all_experiments(selected=experiments)
        info("[AUTO] 所有实验已完成。\n")
    except KeyboardInterrupt:
        info("[AUTO] 用户中断\n")
    except Exception as e:
        info(f"[AUTO] 自动化脚本出错: {e}\n")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_automation()
