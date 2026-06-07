"""
interactive/resource_access.py — HTTP/FTP 资源访问 & 资源权限系统

支持:
  - download_http(host, filename)    — HTTP 下载（自动保存到 inbox）
  - download_ftp(host, filename)     — FTP 下载
  - can_access(identity, resource)   — 权限检查

资源权限策略:
  - 普通课件 (课件_*.pdf, 实验指导.docx): STUDENT / STAFF / VPN_USER / FINANCE_ADMIN / HR_ADMIN
  - 财务报表 (财务*.xlsx): FINANCE_ADMIN only
  - 人事档案 (员工档案.pdf): HR_ADMIN only
  - VPN测试文件: VPN_USER / HOME_USER
  - 校区资源: STUDENT (Campus-B)
"""

import os
import time
import shutil
from interactive.identity_manager import get_identity


# 资源权限策略
RESOURCE_POLICY = {
    "课件_计算机网络.pdf":  {"allow": ["STUDENT", "STAFF", "VPN_USER", "FINANCE_ADMIN", "HR_ADMIN"]},
    "实验指导.docx":       {"allow": ["STUDENT", "STAFF", "VPN_USER", "FINANCE_ADMIN", "HR_ADMIN"]},
    "课件下载.zip":        {"allow": ["STUDENT", "STAFF", "VPN_USER", "FINANCE_ADMIN", "HR_ADMIN"]},
    "校园网使用手册.pdf":   {"allow": ["STUDENT", "STAFF", "VPN_USER", "FINANCE_ADMIN", "HR_ADMIN"]},
    "校园风景.jpg":        {"allow": ["STUDENT", "STAFF", "VPN_USER", "FINANCE_ADMIN", "HR_ADMIN"]},
    "通知_2026.docx":      {"allow": ["STUDENT", "STAFF", "VPN_USER", "FINANCE_ADMIN", "HR_ADMIN"]},

    "财务报告.xlsx":        {"allow": ["FINANCE_ADMIN"]},
    "财务数据报表.xlsx":     {"allow": ["FINANCE_ADMIN"]},
    "预算审批.docx":        {"allow": ["FINANCE_ADMIN"]},

    "员工档案.pdf":         {"allow": ["HR_ADMIN"]},
    "人事档案.pdf":         {"allow": ["HR_ADMIN"]},

    "VPN测试文件.pdf":      {"allow": ["HOME_USER", "VPN_USER"]},

    "校区B课件.pdf":        {"allow": ["STUDENT", "STAFF"]},
    "AI_book.zip":          {"allow": ["STUDENT", "STAFF"]},
    "meeting_notice.docx":  {"allow": ["STAFF", "FINANCE_ADMIN", "HR_ADMIN"]},
}


def can_access(host_name, filename):
    """
    检查主机是否有权访问指定文件。

    返回:
        (allowed: bool, reason: str, identity: str)
    """
    identity = get_identity(host_name)
    policy = RESOURCE_POLICY.get(filename)

    if policy is None:
        return True, "ALLOW (无限制资源)", identity

    if identity in policy["allow"]:
        return True, f"ALLOW ({identity} 有权访问)", identity
    else:
        allowed_list = ", ".join(policy["allow"])
        return False, f"DENY — {identity} 无权访问，仅允许: {allowed_list}", identity


def download_http(host_name, filename, server_ip="10.0.60.2"):
    """
    从 HTTP 服务器下载文件（真实 curl HTTP 请求，经 Mininet 网络拓扑路由）。

    用法:
        mininet> py download_http("dorm1", "bigfile.bin")
        mininet> py download_http("home_pc", "index.html")

    流程:
        1. 权限检查 (can_access)
        2. 真实 HTTP GET 请求（curl，经 r1 路由）
        3. 保存到 fs_topology/nodes/<host>/files/
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if "__file__" in dir() else os.getcwd()
    files_dir = os.path.join(root, "fs_topology", "nodes", host_name, "files")
    os.makedirs(files_dir, exist_ok=True)

    # 1. 双层 ACL 检查 (Perimeter → Internal)
    from security.perimeter_acl import access_resource, print_access_result
    result = access_resource(host_name, filename)

    print()
    print("=" * 50)
    print(f"  HTTP Download: {filename}")

    if not result["allowed"]:
        print_access_result(result)
        return

    # 2. 真实 HTTP 下载（curl 经 Mininet 网络拓扑）
    from interactive import get_net
    net = get_net()
    if not net:
        print("  ERROR: Mininet 网络不可用")
        print("=" * 50)
        return

    host = net.get(host_name)
    if not host:
        print(f"  ERROR: 主机 {host_name} 不存在")
        print("=" * 50)
        return

    url = f"http://{server_ip}/{filename}"
    tmp_remote = f"/tmp/_http_{host_name}_{filename}"
    dst_local = os.path.join(files_dir, filename)

    print(f"  Source:     {server_ip}")
    print(f"  URL:        {url}")
    print(f"  Protocol:   HTTP GET (curl, real network)")
    t0 = time.time()
    host.cmd(f"timeout 15 curl -s -o {tmp_remote} '{url}' 2>&1")
    elapsed = round(time.time() - t0, 3)

    # 检查 Mininet 命名空间中的下载结果
    remote_size_str = host.cmd(f"stat -c '%s' {tmp_remote} 2>/dev/null || echo 0").strip()
    try:
        remote_size = int(remote_size_str)
    except ValueError:
        remote_size = 0

    if remote_size > 0:
        # 从命名空间的 /tmp 复制到宿主 fs_topology
        host.cmd(f"cp {tmp_remote} {dst_local} 2>/dev/null || true")
        size = os.path.getsize(dst_local) if os.path.exists(dst_local) else 0
        throughput = round(size * 8 / (1024 * 1024) / elapsed, 2) if elapsed > 0 and size > 0 else 0
        print(f"  Status:     OK")
        print(f"  Size:       {round(size/1024, 1)} KB ({size} bytes)")
        print(f"  Time:       {elapsed} s")
        print(f"  Throughput: {throughput} Mbps")
        print(f"  Saved to:   fs_topology/nodes/{host_name}/files/")
    else:
        print(f"  Status:     FAILED (0 bytes — ACL/防火墙可能在数据平面拦截)")

    # 清理远程临时文件
    host.cmd(f"rm -f {tmp_remote} 2>/dev/null; true")

    print("=" * 50)
    print()


def download_ftp(host_name, filename, server_ip="10.0.60.2"):
    """
    从 FTP 服务器下载文件（真实 curl FTP 请求，经 Mininet 网络拓扑路由）。

    用法:
        mininet> py download_ftp("dorm1", "README.txt")
        mininet> py download_ftp("office1", "share_doc.txt")

    流程:
        1. 权限检查 (can_access)
        2. 真实 FTP 下载（curl ftp://，vsftpd 匿名访问）
        3. 保存到 fs_topology/nodes/<host>/files/
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if "__file__" in dir() else os.getcwd()
    files_dir = os.path.join(root, "fs_topology", "nodes", host_name, "files")
    os.makedirs(files_dir, exist_ok=True)

    # 1. 双层 ACL 检查
    from security.perimeter_acl import access_resource, print_access_result
    result = access_resource(host_name, filename)

    print()
    print("=" * 50)
    print(f"  FTP Download: {filename}")

    if not result["allowed"]:
        print_access_result(result)
        return

    # 2. 真实 FTP 下载（curl ftp:// 经 Mininet 网络拓扑）
    from interactive import get_net
    net = get_net()
    if not net:
        print("  ERROR: Mininet 网络不可用")
        print("=" * 50)
        return

    host = net.get(host_name)
    if not host:
        print(f"  ERROR: 主机 {host_name} 不存在")
        print("=" * 50)
        return

    url = f"ftp://{server_ip}/{filename}"
    tmp_remote = f"/tmp/_ftp_{host_name}_{filename}"
    dst_local = os.path.join(files_dir, filename)

    print(f"  Source:     {server_ip}")
    print(f"  URL:        {url}")
    print(f"  Protocol:   FTP (curl, vsftpd anonymous)")
    t0 = time.time()
    host.cmd(f"timeout 15 curl -s -o {tmp_remote} '{url}' 2>&1")
    elapsed = round(time.time() - t0, 3)

    # 检查下载结果
    remote_size_str = host.cmd(f"stat -c '%s' {tmp_remote} 2>/dev/null || echo 0").strip()
    try:
        remote_size = int(remote_size_str)
    except ValueError:
        remote_size = 0

    if remote_size > 0:
        host.cmd(f"cp {tmp_remote} {dst_local} 2>/dev/null || true")
        size = os.path.getsize(dst_local) if os.path.exists(dst_local) else 0
        throughput = round(size * 8 / (1024 * 1024) / elapsed, 2) if elapsed > 0 and size > 0 else 0
        print(f"  Status:     OK")
        print(f"  Size:       {round(size/1024, 1)} KB ({size} bytes)")
        print(f"  Time:       {elapsed} s")
        print(f"  Throughput: {throughput} Mbps")
        print(f"  Saved to:   fs_topology/nodes/{host_name}/files/")
    else:
        print(f"  Status:     FAILED (0 bytes — 可能文件不存在或网络拦截)")

    # 清理
    host.cmd(f"rm -f {tmp_remote} 2>/dev/null; true")

    print("=" * 50)
    print()
