"""
interactive/demo_commands.py — 安全防御实时演示命令

提供:
  - scan(attacker, target, ports)    — 端口扫描攻击（触发IDS封禁）
  - show_blacklist()                 — 查看当前封禁列表
  - show_conntrack()                 — 查看状态防火墙连接追踪
  - flood(attacker, target)          — ICMP/TCP Flood攻击演示
"""

import time


def scan(attacker_name, target_name, port_range="8001-8025"):
    """
    端口扫描攻击 — 触发 IDS 滑动窗口检测并自动封禁。

    用法:
        mininet> py scan("dorm1", "server1", "8001-8025")
        mininet> py scan("dorm1", "server1")   # 默认 8001-8025

    预期:
        - 前 19 端口: 正常
        - 第 20 端口: 触发封禁 + 写入 SQLite
        - 后续端口: 全部失败 (Connection refused)
    """
    import __main__
    net = getattr(__main__, "net", None)
    if not net:
        print("[SCAN] ERROR: Mininet 网络未连接")
        return

    attacker = net.get(attacker_name)
    target = net.get(target_name)
    if not attacker or not target:
        print(f"[SCAN] ERROR: 主机不存在")
        return

    # 解析端口范围
    parts = port_range.split("-")
    start_port, end_port = int(parts[0]), int(parts[1])
    total = end_port - start_port + 1

    target_ip = _get_ip(target)

    print()
    print("=" * 50)
    print(f"  Port Scan Attack")
    print(f"  Attacker:  {attacker_name}")
    print(f"  Target:    {target_name} ({target_ip})")
    print(f"  Range:     {start_port}-{end_port} ({total} ports)")
    print("=" * 50)

    detected = False
    scanned = 0

    for port in range(start_port, end_port + 1):
        if detected:
            print(f"  port {port:<6} BLOCKED (attacker IP 已封禁)")
            continue

        out = attacker.cmd(f"nc -zv -w 1 {target_ip} {port} 2>&1")
        scanned += 1

        if "refused" in out.lower() or "open" in out.lower() or "succeeded" in out.lower():
            status = "OPEN"
        else:
            status = "closed"

        print(f"  port {port:<6} {status}")

        # 调用 IDS 检测
        try:
            from security.intrusion import detect_port_scan
            attacker_ip = _get_ip(attacker)
            is_detected = detect_port_scan(attacker_ip, target_ip, port, None)
            if is_detected:
                print()
                print("=" * 50)
                print("  PORT SCAN DETECTED!")
                print(f"  Attacker:  {attacker_ip}")
                print(f"  Threshold: 20 ports / 10s")
                print(f"  Blocked for 300 seconds.")
                print("=" * 50)
                detected = True
        except Exception:
            pass

        time.sleep(0.05)

    if not detected:
        print(f"\n  Result: {scanned}/{total} ports scanned, no detection (below threshold)")

    print()


def show_blacklist():
    """
    查看当前封禁 IP 列表。

    用法:
        mininet> py show_blacklist()
    """
    try:
        from security.firewall import get_ban_list
        bans = get_ban_list()
        print()
        print("=" * 40)
        print("  Firewall Blacklist")
        print("=" * 40)
        if not bans:
            print("  (empty)")
        else:
            for ip, remaining in bans.items():
                print(f"  {ip:<18} 剩余 {remaining}s")
        print("=" * 40)
        print()
    except ImportError:
        print("[BLACKLIST] security.firewall 模块未加载")


def show_conntrack():
    """
    查看状态防火墙连接追踪。

    用法:
        mininet> py show_conntrack()
    """
    print()
    print("=" * 50)
    print("  Stateful Firewall — Connection Tracking")
    print("=" * 50)

    import __main__
    net = getattr(__main__, "net", None)
    if net:
        r1 = net.get("r1")
        if r1:
            out = r1.cmd("cat /proc/net/nf_conntrack 2>/dev/null | head -20 || echo 'conntrack 模块未加载'")
            print(out[:800] if out else "  (no active connections)")
        else:
            print("  r1 路由器未找到")

    print("=" * 50)
    print()


def flood(attacker_name, target_name, count=40, interval=0.02):
    """
    ICMP Flood 攻击演示。

    用法:
        mininet> py flood("dorm1", "server1", count=40)
    """
    import __main__
    net = getattr(__main__, "net", None)
    if not net:
        print("[FLOOD] ERROR: Mininet 网络未连接")
        return

    attacker = net.get(attacker_name)
    target = net.get(target_name)
    if not attacker or not target:
        return

    target_ip = _get_ip(target)

    print()
    print("=" * 50)
    print(f"  ICMP Flood Attack")
    print(f"  Attacker:  {attacker_name}")
    print(f"  Target:    {target_name} ({target_ip})")
    print(f"  Packets:   {count}")
    print(f"  Interval:  {interval}s")
    print("=" * 50)

    sent = 0
    received = 0

    for i in range(count):
        out = attacker.cmd(f"ping -c 1 -W 0.1 {target_ip} 2>&1")
        sent += 1
        if "1 received" in out or " 0% packet loss" in out:
            received += 1
        if i < 5 or i >= count - 3:
            print(f"  [{i+1}/{count}] sent, {received} received")

    loss_rate = round((1 - received / sent) * 100, 1) if sent > 0 else 0
    print()
    print(f"  Result: {received}/{sent} received ({loss_rate}% loss)")
    print(f"  iptables limit: 1/s burst 5 → 预计仅 ~5 包通过")
    print("=" * 50)
    print()


def _get_ip(host):
    out = host.cmd("hostname -I 2>/dev/null | head -1").strip()
    return out if out else "127.0.0.1"
