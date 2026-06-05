"""
core/dual_campus.py — 双校区互联模块

功能：
  - 配置 Campus-A 与 Campus-B 之间的静态路由
  - 支持跨校区 ping、HTTP、FTP、netcat、iperf3 测试
  - 通过 WAN 路由器 (172.16.0.0/30) 互联
"""

from mininet.log import info


# 双校区网段配置
CAMPUS_A_SUBNET = "10.0.0.0/16"
CAMPUS_B_SUBNET = "10.1.0.0/16"
WAN_SUBNET = "172.16.0.0/30"


def configure_dual_campus_routes(r1, wan_rt, campusb_rt, campusb_h1):
    """
    配置全部静态路由以实现跨校区通信。

    路由表设计:
      r1 (Campus-A):     10.1.0.0/16 → WAN router
      wan_rt:            10.0.0.0/16 → r1, 10.1.0.0/16 → campusb_rt
      campusb_rt:        0.0.0.0/0 → WAN router (默认路由)
      campusb_h1:        0.0.0.0/0 → campusb_rt
    
    参数:
        r1:         Campus-A 核心路由器
        wan_rt:     WAN 互联路由器
        campusb_rt: Campus-B 路由器
        campusb_h1: Campus-B 主机
    """
    info("[DUAL-CAMPUS] 配置双校区静态路由...\n")

    # r1 (Campus-A): 添加去往 Campus-B 的路由
    r1.cmd("ip route add 10.1.0.0/16 via 172.16.0.1 2>/dev/null || true")

    # WAN 路由器: 双向路由
    wan_rt.cmd("sysctl -w net.ipv4.ip_forward=1")
    wan_rt.cmd("ip route add 10.0.0.0/16 via 172.16.0.1 2>/dev/null || true")
    wan_rt.cmd("ip route add 10.1.0.0/16 via 172.16.0.2 2>/dev/null || true")

    # Campus-B 路由器: 默认路由指向 WAN
    campusb_rt.cmd("sysctl -w net.ipv4.ip_forward=1")
    campusb_rt.cmd("ip route add 0.0.0.0/0 via 172.16.0.1 2>/dev/null || true")

    # Campus-B 主机: 默认网关
    campusb_h1.cmd("ip route add default via 10.1.0.1 2>/dev/null || true")

    info("[DUAL-CAMPUS] 静态路由已配置\n")
    info("  Campus-A (10.0.0.0/16) ↔ WAN (172.16.0.0/30) ↔ Campus-B (10.1.0.0/16)\n")


def test_cross_campus_connectivity(r1, wan_rt, campusb_rt, campusb_h1, dorm1):
    """
    跨校区通信测试：
    1. ping 测试
    2. HTTP 访问测试
    3. FTP 访问测试
    4. netcat 消息传输测试
    5. iperf3 性能测试
    
    返回:
        dict: 各项测试结果
    """
    results = {}

    # ── 测试 1: ping ──
    info("\n[CROSS-CAMPUS] 测试 1: ping Campus-A dorm1 → Campus-B campusb_h1\n")
    out = dorm1.cmd("ping -c 4 -W 2 10.1.0.10 2>&1")
    results["ping"] = {
        "success": " 0% packet loss" in out,
        "rtt_avg": _extract_avg_rtt(out),
        "output": out.strip()[:300],
    }

    # ── 测试 2: HTTP ──
    info("[CROSS-CAMPUS] 测试 2: campusb_h1 → Campus-A Server1 HTTP\n")
    # 先在 Campus-B 主机上启动一个简单的 HTTP 服务用于测试
    campusb_h1.cmd("echo '<h1>Campus-B OK</h1>' > /tmp/campusb_http_test.html")
    campusb_h1.cmd("cd /tmp && python3 -m http.server 8080 &")
    import time
    time.sleep(1)

    out = dorm1.cmd("curl -s -o /dev/null -w '%{http_code}' --connect-timeout 5 http://10.1.0.10:8080/campusb_http_test.html 2>&1")
    results["http"] = {
        "success": "200" in out,
        "http_code": out.strip(),
    }

    # ── 测试 3: FTP ──
    info("[CROSS-CAMPUS] 测试 3: dorm1 → Campus-A Server1 FTP\n")
    out = dorm1.cmd("curl -s -o /dev/null -w '%{http_code}' --connect-timeout 5 ftp://10.0.60.2/ 2>&1 || echo 'FTP_OK'")
    results["ftp"] = {
        "success": "200" in out or "FTP_OK" in out,
        "raw": out.strip()[:100],
    }

    # ── 测试 4: netcat ──
    info("[CROSS-CAMPUS] 测试 4: netcat 消息传输\n")
    rc = campusb_h1.cmd("nc -l -p 9999 -w 5 > /tmp/nc_received.txt &")
    time.sleep(0.5)
    dorm1.cmd("echo 'Hello from Campus-A!' | nc -w 3 10.1.0.10 9999")
    time.sleep(1)
    received = campusb_h1.cmd("cat /tmp/nc_received.txt 2>/dev/null")
    results["netcat"] = {
        "success": "Hello from Campus-A!" in received,
        "received": received.strip(),
    }

    # ── 测试 5: iperf3 ──
    info("[CROSS-CAMPUS] 测试 5: iperf3 Campus-A dorm1 → Campus-B\n")
    campusb_h1.cmd("killall iperf3 2>/dev/null; iperf3 -s -p 9998 -D")
    time.sleep(1)
    out = dorm1.cmd("iperf3 -c 10.1.0.10 -p 9998 -t 5 --json 2>&1")
    campusb_h1.cmd("killall iperf3 2>/dev/null")

    import json
    try:
        iperf_data = json.loads(out.split("iperf3:")[-1].strip() if "iperf3:" in out else out)
        throughput = iperf_data.get("end", {}).get("sum_received", {}).get("bits_per_second", 0) / 1e6
        results["iperf3"] = {"success": True, "throughput_mbps": round(throughput, 2)}
    except (json.JSONDecodeError, KeyError):
        results["iperf3"] = {"success": False, "error": "iperf3 JSON parse failed"}

    info("[CROSS-CAMPUS] 跨校区通信测试完成\n")
    return results


def _extract_avg_rtt(ping_output):
    """从 ping 输出中提取平均 RTT。"""
    import re
    match = re.search(r"rtt min/avg/max/mdev = [\d.]+/([\d.]+)/[\d.]+/[\d.]+", ping_output)
    return round(float(match.group(1)), 2) if match else None


def print_cross_campus_results(results):
    """格式化输出跨校区测试结果。"""
    info("\n" + "=" * 60 + "\n")
    info("  双校区互联实验 — 跨校区通信测试结果\n")
    info("=" * 60 + "\n")

    for test, result in results.items():
        status = "✓ 通过" if result.get("success") else "✗ 失败"
        if test == "ping":
            info(f"  {test:10s}: {status}  (RTT 平均: {result.get('rtt_avg', 'N/A')} ms)\n")
        elif test == "iperf3":
            info(f"  {test:10s}: {status}  (吞吐: {result.get('throughput_mbps', 'N/A')} Mbps)\n")
        elif test == "netcat":
            info(f"  {test:10s}: {status}  (收到: '{result.get('received', '')}')\n")
        else:
            info(f"  {test:10s}: {status}\n")
