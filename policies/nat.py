"""
policies/nat.py — NAT 模块（SNAT/MASQUERADE）

功能：
  - 在公网路由器 (inet_rt) 上配置 MASQUERADE
  - 将校园网内部私网地址转换后访问外部网络
  - 支持 NAT 开启/关闭实验对照

NAT 规则设计：
  - SNAT: 10.0.0.0/16 出站时源地址转换为公网 IP
  - 仅转换出站流量，外网无法主动访问校园内网
"""

from mininet.log import info


# NAT 配置参数
NAT_EXTERNAL_IFACE = "inet_rt-eth2"    # 公网路由器连接 Campus-A 的接口
CAMPUS_A_SUBNET = "10.0.0.0/16"
INTERNET_IP_START = "203.0.113.0/28"


def enable_nat(inet_rt):
    """
    在公网路由器上启用 SNAT/MASQUERADE。
    
    校园网主机访问外网时，源地址自动转换为公网路由器的公网接口地址。
    
    参数:
        inet_rt: 公网路由器节点
    """
    info("[NAT] 启用 SNAT/MASQUERADE...\n")
    
    # 清除旧规则
    inet_rt.cmd("iptables -t nat -F")
    inet_rt.cmd("iptables -F FORWARD")
    
    # MASQUERADE: 将校园网出站流量的源地址转换为公网接口地址
    inet_rt.cmd(
        f"iptables -t nat -A POSTROUTING "
        f"-s {CAMPUS_A_SUBNET} -o {NAT_EXTERNAL_IFACE} "
        f"-j MASQUERADE"
    )
    
    # 允许转发
    inet_rt.cmd("iptables -A FORWARD -i inet_rt-eth1 -o inet_rt-eth2 -j ACCEPT")
    inet_rt.cmd("iptables -A FORWARD -i inet_rt-eth2 -o inet_rt-eth1 -j ACCEPT")
    inet_rt.cmd("iptables -A FORWARD -m state --state ESTABLISHED,RELATED -j ACCEPT")
    
    # 启用 IP 转发
    inet_rt.cmd("sysctl -w net.ipv4.ip_forward=1")
    
    info("[NAT] MASQUERADE 已启用: {CAMPUS_A_SUBNET} → {NAT_EXTERNAL_IFACE}\n")


def disable_nat(inet_rt):
    """关闭 NAT，清除所有 iptables NAT 规则。"""
    info("[NAT] 关闭 NAT...\n")
    inet_rt.cmd("iptables -t nat -F")
    inet_rt.cmd("iptables -F FORWARD")
    info("[NAT] NAT 已关闭\n")


def get_nat_statistics(inet_rt):
    """获取 NAT 转换统计信息。"""
    stats = {}
    
    # 获取 NAT 表规则计数
    nat_rules = inet_rt.cmd("iptables -t nat -L -n -v 2>/dev/null")
    stats["nat_rules"] = nat_rules.strip()
    
    # 获取连接追踪信息
    conntrack = inet_rt.cmd("cat /proc/net/nf_conntrack 2>/dev/null | head -20 || echo 'N/A'")
    stats["connections"] = conntrack.strip()
    
    return stats


def test_nat_connectivity(net, hosts, inet_rt, ext_server):
    """
    NAT 功能验证实验：
    1. NAT 关闭时，校园网主机能否访问外网（预期：失败）
    2. NAT 开启时，校园网主机能否访问外网（预期：成功）
    
    参数:
        net:        Mininet 网络
        hosts:      主机字典
        inet_rt:    公网路由器
        ext_server: 外网服务器
    
    返回:
        dict: 两项测试结果
    """
    results = {}
    dorm1 = hosts.get("dorm1")
    
    # ── 测试 1: NAT 关闭 ──
    info("\n[NAT TEST] === 测试 1: NAT 关闭状态 ===\n")
    disable_nat(inet_rt)
    
    info("[NAT TEST] dorm1 → ext_server ping (NAT OFF, 预期失败)...\n")
    out = dorm1.cmd("ping -c 3 -W 2 203.0.113.10 2>&1")
    results["nat_off_ping"] = {
        "expected": "fail",
        "result": "fail" if "100% packet loss" in out else "success (unexpected!)",
        "output_preview": out.strip()[:200],
    }
    
    # ── 测试 2: NAT 开启 ──
    info("\n[NAT TEST] === 测试 2: NAT 开启状态 ===\n")
    enable_nat(inet_rt)
    
    info("[NAT TEST] dorm1 → ext_server ping (NAT ON, 预期成功)...\n")
    out = dorm1.cmd("ping -c 3 -W 2 203.0.113.10 2>&1")
    results["nat_on_ping"] = {
        "expected": "success",
        "result": "success" if " 0% packet loss" in out else "fail (unexpected!)",
        "output_preview": out.strip()[:200],
    }
    
    # 获取 NAT 统计
    results["nat_stats"] = get_nat_statistics(inet_rt)
    
    info("[NAT TEST] NAT 功能测试完成\n")
    return results


def print_nat_test_results(results):
    """格式化输出 NAT 测试结果。"""
    info("\n" + "=" * 60 + "\n")
    info("  NAT 功能测试结果\n")
    info("=" * 60 + "\n")
    
    for test, result in results.items():
        if test == "nat_stats":
            continue
        expected = result["expected"]
        actual = result["result"]
        status = "✓ 通过" if expected in actual else "✗ 异常"
        info(f"  {test}: {status} (预期{expected}, 实际{actual})\n")
        info(f"    输出: {result.get('output_preview', 'N/A')[:100]}\n")
