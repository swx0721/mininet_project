"""
experiments/run_extended_experiments.py — 扩展实验体系

新增四大实验：
  1. VPN 功能实验  (--experiment vpn_test)
  2. ACL 防 VPN 绕过实验 (--experiment acl_vpn_test)
  3. NAT 实验 (--experiment nat_test)
  4. 双校区互联实验 (--experiment dual_campus_test)
"""

import time
import json as _json
from mininet.log import info, setLogLevel
from utils import print_separator, timestamp, save_to_json


# ==================== 实验 1: VPN 功能实验 ====================

def run_vpn_test():
    """验证 VPN 远程接入的基本功能。

    测试步骤：
      1. 构建含 VPN 网关的扩展拓扑
      2. 校外主机默认无法访问校园网 (ping 测试)
      3. 建立 VPN 后校外主机获得虚拟地址
      4. VPN 用户访问 HTTP/FTP 成功
      5. VPN 用户访问财务处/人事处被拒绝
      6. ACL 日志记录 VPN 访问事件
    """
    info("\n" + "=" * 60 + "\n")
    info("  实验: VPN 远程接入功能测试\n")
    info("=" * 60 + "\n")

    from core.extended_topology import create_fresh_extended_network
    from policies.vpn import (setup_vpn_gateway, apply_vpn_routing,
                             test_vpn_connectivity, print_vpn_test_results, list_vpn_users)
    from security.acl_vpn import apply_vpn_acl_policies, print_identity_matrix

    # 构建扩展拓扑（导出所有节点）
    net, r1, hosts, switches, extra = create_fresh_extended_network(
        include_vpn=True,
        include_nat=False,
        include_dual_campus=False
    )

    vpn_gw = extra["routers"]["vpn_gw"]
    home_pc = extra["hosts"]["home_pc"]

    # 1. 配置 VPN 网关
    setup_vpn_gateway(r1, vpn_gw)
    apply_vpn_routing(r1, vpn_gw)

    # 2. 部署防 VPN 绕过 ACL
    apply_vpn_acl_policies(r1)
    print_identity_matrix()

    # 3. 列出 VPN 用户
    users = list_vpn_users()
    for user, uinfo in users.items():
        info(f"  VPN 用户: {user} → 虚拟 IP: {uinfo['virtual_ip']}\n")

    # 4. 执行测试
    results = test_vpn_connectivity(net, r1, home_pc)
    print_vpn_test_results(results)

    # 5. 保存结果
    results["_metadata"] = {
        "experiment": "vpn_test",
        "timestamp": timestamp(),
    }
    save_to_json(f"vpn_test_{timestamp()}.json", results, subdir="vpn")

    net.stop()
    return results


# ==================== 实验 2: ACL 防 VPN 绕过实验 ====================

def run_acl_vpn_test():
    """验证防 VPN 绕过 ACL 的有效性。

    对照实验:
      - 实验组: 启用 VPN 专用 ACL
      - 对照组: 仅使用原始 ACL (无 VPN 身份识别)

    测试步骤：
      1. 对照组: VPN 用户可能绕过 ACL 访问敏感区
      2. 实验组: VPN 用户被精确拦截
      3. 对比拦截率与审计日志
    """
    info("\n" + "=" * 60 + "\n")
    info("  实验: ACL 防 VPN 绕过测试\n")
    info("=" * 60 + "\n")

    from core.extended_topology import create_fresh_extended_network
    from policies.vpn import setup_vpn_gateway, apply_vpn_routing
    from security.acl_vpn import apply_vpn_acl_policies
    from security.acl import apply_acl_policies, apply_stateful_firewall, clear_all_rules

    results_control = {}
    results_experiment = {}

    # ── 阶段 1: 对照组 (仅原始 ACL) ──
    info("\n=== 阶段 1: 对照组 (仅原始 ACL, 无 VPN 身份识别) ===\n")
    net1, r1, hosts1, sw1, extra1 = create_fresh_extended_network(
        include_vpn=True, include_nat=False, include_dual_campus=False
    )
    vpn_gw1 = extra1["routers"]["vpn_gw"]
    home_pc1 = extra1["hosts"]["home_pc"]

    setup_vpn_gateway(r1, vpn_gw1)
    apply_vpn_routing(r1, vpn_gw1)

    # 仅部署原始 ACL
    clear_all_rules(r1)
    apply_stateful_firewall(r1)
    apply_acl_policies(r1)

    # 测试: VPN用户绕过原始ACL访问财务处
    info("[ACL-VPN TEST] 对照组: VPN用户访问 finance1\n")
    out = home_pc1.cmd("ping -c 3 -W 2 10.0.35.2 2>&1")
    results_control["vpn_bypass_finance"] = {
        "description": "VPN用户绕过原始ACL访问财务处",
        "blocked": "100% packet loss" in out,
    }

    info("[ACL-VPN TEST] 对照组: VPN用户访问 Server1 HTTP\n")
    out = home_pc1.cmd("curl -s -o /dev/null -w '%{http_code}' --connect-timeout 5 http://10.0.60.2/ 2>&1")
    results_control["vpn_http_access"] = {
        "description": "VPN用户HTTP访问",
        "http_code": out.strip(),
    }

    net1.stop()
    time.sleep(1)

    # ── 阶段 2: 实验组 (VPN 增强 ACL) ──
    info("\n=== 阶段 2: 实验组 (VPN 增强 ACL) ===\n")
    net2, r2, hosts2, sw2, extra2 = create_fresh_extended_network(
        include_vpn=True, include_nat=False, include_dual_campus=False
    )
    vpn_gw2 = extra2["routers"]["vpn_gw"]
    home_pc2 = extra2["hosts"]["home_pc"]

    setup_vpn_gateway(r2, vpn_gw2)
    apply_vpn_routing(r2, vpn_gw2)

    # 部署 VPN 增强 ACL
    clear_all_rules(r2)
    apply_vpn_acl_policies(r2)

    # 测试: VPN增强ACL防御效果
    info("[ACL-VPN TEST] 实验组: VPN用户访问 finance1\n")
    out = home_pc2.cmd("ping -c 3 -W 2 10.0.35.2 2>&1")
    results_experiment["vpn_blocked_finance"] = {
        "description": "VPN增强ACL防御财务处访问",
        "blocked": "100% packet loss" in out,
    }

    info("[ACL-VPN TEST] 实验组: VPN用户访问 hr1\n")
    out = home_pc2.cmd("ping -c 3 -W 2 10.0.35.66 2>&1")
    results_experiment["vpn_blocked_hr"] = {
        "description": "VPN增强ACL防御人事处访问",
        "blocked": "100% packet loss" in out,
    }

    info("[ACL-VPN TEST] 实验组: VPN用户HTTP访问\n")
    out = home_pc2.cmd("curl -s -o /dev/null -w '%{http_code}' --connect-timeout 5 http://10.0.60.2/ 2>&1")
    results_experiment["vpn_http_allowed"] = {
        "description": "VPN用户HTTP正常访问",
        "http_code": out.strip(),
    }

    # 收集审计日志
    from security.audit_db import get_statistics
    audit_stats = get_statistics(r2)
    results_experiment["audit_events"] = dict(audit_stats)

    net2.stop()

    # ── 格式化输出 ──
    info("\n" + "=" * 60 + "\n")
    info("  ACL 防 VPN 绕过实验 — 对比结果\n")
    info("=" * 60 + "\n")
    info(f"  对照组 VPN→Finance: {'未拦截 (漏洞!)' if not results_control['vpn_bypass_finance']['blocked'] else '已拦截'}\n")
    info(f"  实验组 VPN→Finance: {'已拦截 ✓' if results_experiment['vpn_blocked_finance']['blocked'] else '未拦截 ✗'}\n")
    info(f"  实验组 VPN→HR:      {'已拦截 ✓' if results_experiment['vpn_blocked_hr']['blocked'] else '未拦截 ✗'}\n")
    info(f"  实验组 VPN→HTTP:    HTTP {results_experiment['vpn_http_allowed']['http_code']}\n")
    info(f"  审计事件总数:       {results_experiment['audit_events'].get('total', 0)}\n")

    combined = {
        "_metadata": {"experiment": "acl_vpn_test", "timestamp": timestamp()},
        "control": results_control,
        "experiment": results_experiment,
    }
    save_to_json(f"acl_vpn_test_{timestamp()}.json", combined, subdir="acl_vpn")

    return combined


# ==================== 实验 3: NAT 实验 ====================

def run_nat_test():
    """验证 NAT 功能。

    实验设计:
      - NAT 关闭时：校园网主机无法访问外网
      - NAT 开启时：校园网主机成功访问外网，源地址被转换
    """
    info("\n" + "=" * 60 + "\n")
    info("  实验: NAT 功能验证\n")
    info("=" * 60 + "\n")

    from core.extended_topology import create_fresh_extended_network
    from policies.nat import enable_nat, disable_nat, test_nat_connectivity, print_nat_test_results

    net, r1, hosts, switches, extra = create_fresh_extended_network(
        include_vpn=False,
        include_nat=True,
        include_dual_campus=False
    )

    inet_rt = extra["routers"]["inet_rt"]
    ext_server = extra["hosts"]["ext_server"]

    # 执行 NAT 实验
    results = test_nat_connectivity(net, hosts, inet_rt, ext_server)
    print_nat_test_results(results)

    results["_metadata"] = {
        "experiment": "nat_test",
        "timestamp": timestamp(),
    }
    save_to_json(f"nat_test_{timestamp()}.json", results, subdir="nat")

    net.stop()
    return results


# ==================== 实验 4: 双校区互联实验 ====================

def run_dual_campus_test():
    """验证双校区互联功能。

    测试内容:
      - ping: Campus-A dorm1 → Campus-B campusb_h1
      - HTTP: 跨校区 Web 访问
      - FTP: 跨校区文件传输
      - netcat: 跨校区文本消息
      - iperf3: 跨校区性能测试
    """
    info("\n" + "=" * 60 + "\n")
    info("  实验: 双校区互联测试\n")
    info("=" * 60 + "\n")

    from core.extended_topology import create_fresh_extended_network
    from core.dual_campus import (configure_dual_campus_routes,
                                  test_cross_campus_connectivity,
                                  print_cross_campus_results)

    net, r1, hosts, switches, extra = create_fresh_extended_network(
        include_vpn=False,
        include_nat=False,
        include_dual_campus=True
    )

    wan_rt = extra["routers"]["wan_rt"]
    campusb_rt = extra["routers"]["campusb_rt"]
    campusb_h1 = extra["hosts"]["campusb_h1"]
    dorm1 = hosts["dorm1"]

    # 配置路由
    configure_dual_campus_routes(r1, wan_rt, campusb_rt, campusb_h1)

    # 执行测试
    results = test_cross_campus_connectivity(r1, wan_rt, campusb_rt, campusb_h1, dorm1)
    print_cross_campus_results(results)

    results["_metadata"] = {
        "experiment": "dual_campus_test",
        "timestamp": timestamp(),
    }
    save_to_json(f"dual_campus_{timestamp()}.json", results, subdir="dual_campus")

    net.stop()
    return results


# ==================== 主入口 ====================

EXPERIMENT_MAP = {
    "vpn_test":       run_vpn_test,
    "acl_vpn_test":   run_acl_vpn_test,
    "nat_test":       run_nat_test,
    "dual_campus_test": run_dual_campus_test,
}


def run_extended_experiment(name):
    """运行指定的扩展实验。"""
    if name not in EXPERIMENT_MAP:
        info(f"[ERROR] 未知实验: {name}. 可选: {list(EXPERIMENT_MAP.keys())}\n")
        return
    print_separator(f"扩展实验 — {name}")
    EXPERIMENT_MAP[name]()
