"""
main.py — CampusNet 模型调度器

模型驱动的校园网络仿真系统入口。

用法:
    # 模型驱动模式（启动网络 + CLI）
    python main.py --model baseline
    python main.py --model qos
    python main.py --model lb
    python main.py --model security
    python main.py --model final

    # YAML 配置模式
    python main.py --config configs/final.yaml

    # 实验模式
    python main.py --experiment qos_ablation
    python main.py --experiment lb_ablation
    python main.py --experiment security_test

    # 一键运行全部实验
    python main.py --auto

    # 辅助功能
    python main.py --plot          # 绘制图表
    python main.py --report        # 生成报告
    python main.py --strict        # 严格安全模式
    python main.py --no-cli        # 不进入 CLI

    # 调试参数
    python main.py --model final --bw 100 --delay 5ms
"""

import sys
import argparse
from mininet.log import info, setLogLevel


def parse_args():
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="CampusNet-Final — 模型驱动校园网络仿真系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
模型选项:
  baseline    基础网络（拓扑+服务+基础ACL）
  qos         Baseline + HTB QoS
  lb          Baseline + Round Robin
  security    Baseline + 完整安全体系
  final       CampusNet-Final（全部模块）

实验选项:
  qos_ablation     QoS 消融实验
  lb_ablation      负载均衡消融实验
  security_test    安全策略验证实验

示例:
  python main.py --model final
  python main.py --config configs/final.yaml
  python main.py --experiment qos_ablation
  python main.py --auto --plot --report
        """
    )

    # ---- 模型选择 ----
    parser.add_argument("--model", type=str, default=None,
                        choices=["baseline", "qos", "lb", "security", "final"],
                        help="选择要部署的模型")
    parser.add_argument("--config", type=str, default=None,
                        help="YAML 配置文件路径")

    # ---- 实验选择 ----
    parser.add_argument("--experiment", type=str, default=None,
                        choices=["qos_ablation", "lb_ablation", "security_test"],
                        help="运行指定实验")
    parser.add_argument("--auto", action="store_true",
                        help="一键运行全部实验")

    # ---- 辅助功能 ----
    parser.add_argument("--plot", action="store_true",
                        help="绘制实验图表")
    parser.add_argument("--report", action="store_true",
                        help="生成实验报告")

    # ---- 网络参数 ----
    parser.add_argument("--bw", type=int, default=None,
                        help="统一接入链路带宽 (Mbps)")
    parser.add_argument("--delay", type=str, default=None,
                        help="统一接入链路时延 (如 '5ms')")
    parser.add_argument("--bottleneck-bw", type=int, default=None,
                        dest="bottleneck_bw",
                        help="瓶颈带宽 (Mbps), 默认 35")

    # ---- 安全选项 ----
    parser.add_argument("--strict", action="store_true",
                        help="启用严格安全模式（默认 DROP）")
    parser.add_argument("--no-cli", action="store_true",
                        help="不进入 CLI 交互模式")

    # ---- 实验参数 ----
    parser.add_argument("--duration", type=int, default=None,
                        help="实验持续时长（秒）")
    parser.add_argument("--scenario", type=str, default="B", choices=["A", "B"],
                        help="消融实验负载场景: A=中等均衡, B=高负载不均 (默认 B)")
    parser.add_argument("--repeat", type=int, default=3,
                        help="实验重复次数（默认 3）")

    # ---- 兼容旧参数 ----
    parser.add_argument("--enable-qos", dest="enable_qos", action="store_true",
                        help="[兼容] 等同于 --model qos")
    parser.add_argument("--qos", action="store_true",
                        help="[兼容] 等同于 --experiment qos_ablation")
    parser.add_argument("--load-balance", dest="load_balance", action="store_true",
                        help="[兼容] 等同于 --experiment lb_ablation")

    return parser.parse_args()


def _load_yaml_config(config_path):
    """加载 YAML 配置文件。"""
    try:
        import yaml
    except ImportError:
        info("[ERROR] 需要安装 pyyaml: pip install pyyaml\n")
        return None

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        info(f"[ERROR] 配置文件不存在: {config_path}\n")
        return None
    except Exception as e:
        info(f"[ERROR] 配置文件解析失败: {e}\n")
        return None


def _resolve_model(config):
    """从配置字典中解析模型名称。"""
    if config is None:
        return None
    return config.get("model")


def mode_model(model_name, args, config=None):
    """
    模型驱动模式：部署指定模型并启动网络。
    """
    from utils import print_separator

    print_separator(f"CampusNet 模型驱动模式 — {model_name.upper()}")

    with_cli = not args.no_cli
    strict = args.strict
    bottleneck_bw = args.bottleneck_bw

    if model_name == "baseline":
        from models.baseline import deploy_baseline
        deploy_baseline(
            with_cli=with_cli,
            access_bw=args.bw,
            access_delay=args.delay,
            strict=strict,
        )

    elif model_name == "qos":
        from models.qos_model import deploy_qos_model
        deploy_qos_model(
            with_cli=with_cli,
            access_bw=args.bw,
            access_delay=args.delay,
            bottleneck_bw=bottleneck_bw,
            strict=strict,
        )

    elif model_name == "lb":
        from models.lb_model import deploy_lb_model
        deploy_lb_model(
            with_cli=with_cli,
            access_bw=args.bw,
            access_delay=args.delay,
            strict=strict,
        )

    elif model_name == "security":
        from models.security_model import deploy_security_model
        deploy_security_model(
            with_cli=with_cli,
            access_bw=args.bw,
            access_delay=args.delay,
            strict=strict,
        )

    elif model_name == "final":
        from models.final import deploy_final
        deploy_final(
            with_cli=with_cli,
            access_bw=args.bw,
            access_delay=args.delay,
            bottleneck_bw=bottleneck_bw,
            strict=strict,
        )


def mode_experiment(experiment_name, args):
    """实验模式：运行指定实验。"""
    from utils import print_separator

    print_separator(f"实验模式 — {experiment_name}")

    if experiment_name == "qos_ablation":
        from experiments.run_qos_ablation import run_qos_ablation
        run_qos_ablation(duration=args.duration, scenario=args.scenario)

    elif experiment_name == "lb_ablation":
        from experiments.run_lb_ablation import run_lb_ablation
        run_lb_ablation(duration=args.duration or 60, scenario=args.scenario)

    elif experiment_name == "security_test":
        from experiments.run_security_test import run_security_test
        run_security_test()


def mode_auto(args):
    """一键运行全部实验。"""
    from utils import print_separator, ensure_dirs, timestamp, save_to_csv

    ensure_dirs()

    print_separator("CampusNet 自动化实验套件", 70)

    all_results = []

    # 实验一：QoS 消融
    info("\n[实验 1/3] QoS 消融实验\n")
    try:
        from experiments.run_qos_ablation import run_qos_ablation
        run_qos_ablation(duration=args.duration, scenario=args.scenario)
        all_results.append(("QoS 消融实验", "完成", ""))
    except Exception as e:
        info(f"[AUTO] QoS 实验失败: {e}\n")
        all_results.append(("QoS 消融实验", "失败", str(e)))

    # 实验二：负载均衡消融
    info("\n[实验 2/3] 负载均衡消融实验\n")
    try:
        from experiments.run_lb_ablation import run_lb_ablation
        run_lb_ablation(duration=args.duration or 60, scenario=args.scenario)
        all_results.append(("负载均衡消融实验", "完成", ""))
    except Exception as e:
        info(f"[AUTO] 负载均衡实验失败: {e}\n")
        all_results.append(("负载均衡消融实验", "失败", str(e)))

    # 实验三：安全策略验证
    info("\n[实验 3/3] 安全策略验证实验\n")
    try:
        from experiments.run_security_test import run_security_test
        run_security_test()
        all_results.append(("安全策略验证实验", "完成", ""))
    except Exception as e:
        info(f"[AUTO] 安全实验失败: {e}\n")
        all_results.append(("安全策略验证实验", "失败", str(e)))

    # 汇总
    print_separator("实验汇总")
    summary_file = f"experiment_summary_{timestamp()}.csv"
    save_to_csv(summary_file,
                ["实验名称", "状态", "详情"],
                [[n, s, d] for n, s, d in all_results])
    info(f"[AUTO] 汇总已保存到 {summary_file}\n")


def mode_plot():
    """绘制图表模式。"""
    from analysis.plot import plot_all
    plot_all()


def mode_report():
    """生成报告模式。"""
    from analysis.report import generate_report
    generate_report()


def main():
    """主入口。"""
    setLogLevel("info")
    args = parse_args()

    # ---- 兼容旧参数 ----
    if args.enable_qos:
        args.model = "qos"
    if args.qos:
        args.experiment = "qos_ablation"
    if args.load_balance:
        args.experiment = "lb_ablation"

    # ---- 路由逻辑 ----
    if args.experiment:
        mode_experiment(args.experiment, args)

    elif args.auto:
        mode_auto(args)
        if args.plot:
            mode_plot()
        if args.report:
            mode_report()

    elif args.plot:
        mode_plot()

    elif args.report:
        mode_report()

    elif args.config:
        config = _load_yaml_config(args.config)
        model_name = _resolve_model(config)
        if model_name:
            mode_model(model_name, args, config)
        else:
            info("[ERROR] 无法从配置文件解析模型名称\n")

    elif args.model:
        mode_model(args.model, args)

    else:
        # 默认：进入 Final 模型
        info("[MAIN] 未指定模型，默认使用 CampusNet-Final\n")
        mode_model("final", args)


if __name__ == "__main__":
    main()
