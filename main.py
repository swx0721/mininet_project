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
  qos_ablation      QoS 消融实验
  lb_ablation       负载均衡消融实验
  security_test     安全策略验证实验
  security_ablation 安全策略消融实验

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
                        choices=["qos_ablation", "lb_ablation", "security_test",
                                 "security_ablation", "vpn_test", "acl_vpn_test",
                                 "nat_test", "dual_campus_test"],
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
    所有 deploy 逻辑内联实现，直接调用 core/policies/security 模块，无需 models/ 目录。
    """
    from utils import print_separator
    from core.topology import create_fresh_network
    from core.server_cluster import get_server_hosts, DEFAULT_STATIC_MAPPING
    from services.web import start_web_server
    from services.ftp import start_ftp_server
    from services.iperf import start_dual_iperf

    print_separator(f"CampusNet 模型驱动模式 — {model_name.upper()}")

    with_cli = not args.no_cli
    bottleneck_bw = args.bottleneck_bw

    # 构建基础网络拓扑
    net, r1, hosts, switches = create_fresh_network(
        access_bw=args.bw,
        access_delay=args.delay,
        core_bw=None,
    )

    server1, server2 = get_server_hosts(hosts)

    # 启动 Web/FTP/iperf3 服务（所有模型都需要）
    start_web_server(server1)
    start_web_server(server2)
    start_ftp_server(server1)
    start_ftp_server(server2)
    start_dual_iperf(server1, server2)

    # 根据模型名称叠加策略
    if model_name in ("qos", "final"):
        from policies.qos import apply_htb_policy
        apply_htb_policy(r1, bottleneck_bw=bottleneck_bw)

    if model_name in ("lb", "final"):
        from policies.load_balance import LoadBalancer
        lb = LoadBalancer(algorithm="round_robin")
        info(f"[DEPLOY] 负载均衡已启用 (Round Robin)\n")

    if model_name in ("security", "final"):
        from security.acl import (clear_all_rules, apply_stateful_firewall,
                                 apply_acl_policies, apply_default_drop,
                                 apply_external_isolation)
        from security.intrusion import apply_intrusion_detection
        from security.audit_db import init_db
        clear_all_rules(r1)          # 清除 Mininet 默认 NAT 规则（否则 ACCEPT 优先于 DROP）
        apply_stateful_firewall(r1)
        apply_external_isolation(r1) # 校外 home_pc 默认完全隔离（VPN 关闭时无法访问任何校内主机）
        apply_acl_policies(r1)
        apply_default_drop(r1)
        apply_intrusion_detection(r1)
        init_db(r1)
        info("[DEPLOY] 安全策略已部署 (ACL + IDS + SQLite)\n")

    # 初始化交互式文件系统（拓扑文件系统，与 Mininet 节点同构）
    # force_rebuild=True: main.py 启动时强制重建，保证实验可重复
    try:
        from network_cli import init_fs_topology
        init_fs_topology([h.name for h in net.hosts], force_rebuild=True)
        info("[DEPLOY] fs_topology/ 文件系统已初始化\n")
    except ImportError:
        pass

    # 可选 CLI
    if with_cli:
        from mininet.cli import CLI
        CLI(net)

    net.stop()


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

    elif experiment_name == "security_ablation":
        from experiments.run_security_ablation import run_security_ablation
        run_security_ablation()

    elif experiment_name in ("vpn_test", "acl_vpn_test", "nat_test", "dual_campus_test"):
        from experiments.run_extended_experiments import run_extended_experiment
        run_extended_experiment(experiment_name)


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
