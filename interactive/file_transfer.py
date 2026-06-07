"""
interactive/file_transfer.py — 统一文件传输接口

提供 transfer_file(src, dst, filename) 函数，支持在 Mininet CLI 中
通过 py 命令直接调用，输出完整的传输统计信息。
"""

import os
import time
import hashlib
import shutil
from datetime import datetime


def _md5(filepath):
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_project_root():
    """向上搜索直到找到 main.py。"""
    import os as _os
    try:
        p = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    except NameError:
        p = _os.getcwd()
    for _ in range(10):
        if _os.path.exists(_os.path.join(p, "main.py")):
            return p
        parent = _os.path.dirname(p)
        if parent == p: break
        p = parent
    return _os.getcwd()


def transfer_file(src_name, dst_name, filename):
    """
    主机间文件传输 — 通过真实 TCP/Netcat 经 Mininet 拓扑路由。

    数据流: sender → s_sender → [agg] → r1(iptables/QoS) → [agg] → s_dst → receiver
    所有策略（ACL、QoS、IDS、VPN）对传输数据包真实生效。

    用法（Mininet CLI 中）:
        mininet> py transfer_file("dorm1", "dorm2", "校园风景.jpg")
        mininet> py transfer_file("office1", "dorm1", "通知_2026.docx")
        mininet> py transfer_file("finance1", "office1", "财务数据报表.xlsx")

    自动完成: MD5校验 / 吞吐量 / 耗时统计。
    """
    root = _get_project_root()
    fs_nodes = os.path.join(root, "fs_topology", "nodes")
    resources_dir = os.path.join(root, "resources")

    # 1. 定位源文件：发送方 files/ 或 resources/
    src_file = None
    src_files = os.path.join(fs_nodes, src_name, "files")
    if os.path.isdir(src_files):
        candidate = os.path.join(src_files, filename)
        if os.path.exists(candidate):
            src_file = candidate

    if not src_file:
        for rdir in ["docs", "images", "zip", "misc", ""]:
            search = os.path.join(resources_dir, rdir, filename)
            if os.path.exists(search):
                src_file = search
                break

    if not src_file:
        print(f"[TRANSFER] ERROR: 文件不存在 — {filename}")
        print(f"  提示: 发送方 files/ 和 resources/ 均未找到该文件")
        return

    file_size = os.path.getsize(src_file)
    file_size_mb = round(file_size / (1024 * 1024), 3)

    # 2. ACL pre-check (Python-level，instant feedback)
    try:
        from network_cli import _check_acl
        allowed, acl_reason = _check_acl(src_name, dst_name, None)
        if not allowed:
            print(f"[TRANSFER] {src_name} → {dst_name}: {filename} ({file_size_mb} MB)")
            print(f"[ACL] {acl_reason} — 传输被拦截")
            _log_transfer(src_name, dst_name, filename, file_size_mb,
                          0, False)
            return
    except ImportError:
        pass

    # 3. 真实网络传输 (TCP/Netcat)
    from interactive import get_net
    net = get_net()
    if not net:
        print("[TRANSFER] ERROR: Mininet 网络不可用")
        return

    src_host = net.get(src_name)
    dst_host = net.get(dst_name)
    if not src_host or not dst_host:
        print(f"[TRANSFER] ERROR: 主机不存在: {src_name if not src_host else dst_name}")
        return

    dst_ip = _get_ip(dst_host)
    tmp_send = f"/tmp/_transfer_send_{src_name}_{filename}"
    tmp_recv = f"/tmp/_transfer_recv_{dst_name}_{filename}"

    shutil.copy2(src_file, tmp_send)
    if os.path.exists(tmp_recv):
        os.remove(tmp_recv)

    print(f"\n{'=' * 50}")
    print(f"  Transfer: {src_name} → {dst_name}")
    print(f"  File:    {filename} ({file_size_mb} MB)")
    print(f"  Protocol: TCP/Netcat (real network)")
    print(f"{'=' * 50}")

    # 接收方监听（在其网络命名空间中绑定 IP）
    dst_host.cmd("kill $(pgrep -f 'nc -l -p 9999') 2>/dev/null; true")
    time.sleep(0.1)
    dst_host.cmd(f"nc -l -p 9999 > {tmp_recv} &")
    time.sleep(0.3)

    # 发送方通过真实网络拓扑发送
    md5_before = _md5(src_file)
    t0 = time.time()
    src_host.cmd(f"timeout 15 nc -w 10 {dst_ip} 9999 < {tmp_send} 2>&1")
    elapsed = round(time.time() - t0, 3)
    time.sleep(0.3)

    # 4. MD5 校验
    transfer_ok = False
    dst_files = os.path.join(fs_nodes, dst_name, "files")
    os.makedirs(dst_files, exist_ok=True)
    dst_file = os.path.join(dst_files, filename)

    if os.path.exists(tmp_recv) and os.path.getsize(tmp_recv) > 0:
        md5_after = _md5(tmp_recv)
        if md5_before == md5_after:
            transfer_ok = True
            shutil.copy2(tmp_recv, dst_file)

    # 5. 吞吐量计算
    throughput = round(file_size_mb * 8 / elapsed, 2) if elapsed > 0 and file_size_mb > 0 else 0

    # 6. 终端输出
    print(f"  Transfer time:  {elapsed} s")
    print(f"  Throughput:     {throughput} Mbps")
    print(f"  MD5 verify:     {'PASS' if transfer_ok else 'FAIL'}")
    if not transfer_ok:
        recv_size = os.path.getsize(tmp_recv) if os.path.exists(tmp_recv) else 0
        print(f"  Received:       {recv_size}/{file_size} bytes")
        print(f"  Network:        连接超时 (iptables/ACL 数据平面拦截)")
    print(f"{'=' * 50}\n")

    # 清理临时文件
    for p in [tmp_send, tmp_recv]:
        try:
            os.remove(p)
        except OSError:
            pass

    # 7. 写入日志
    _log_transfer(src_name, dst_name, filename, file_size_mb, elapsed, throughput, transfer_ok)


def _get_ip(host):
    out = host.cmd("hostname -I 2>/dev/null | head -1").strip()
    return out if out else "127.0.0.1"


def _log_transfer(src, dst, file, size_mb, elapsed, throughput, md5_ok):
    root = _get_project_root()
    log_path = os.path.join(root, "fs_topology", "runtime_transfer.json")
    import json
    entry = {
        "timestamp": str(datetime.now()),
        "src": src, "dst": dst, "file": file,
        "size_mb": size_mb,
        "transfer_time_s": elapsed,
        "avg_throughput_mbps": throughput,
        "md5_match": md5_ok,
    }
    try:
        with open(log_path, "r") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {"transfers": [], "_generated": str(datetime.now())}
    data["transfers"].append(entry)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
