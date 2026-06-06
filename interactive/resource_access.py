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
    从 HTTP 服务器下载文件到指定主机的 inbox。

    用法:
        mininet> py download_http("dorm1", "课件下载.zip")
        mininet> py download_http("home_pc", "财务数据报表.xlsx")

    流程:
        1. 权限检查 (can_access)
        2. curl 下载
        3. 保存到 fs_topology/nodes/<host>/inbox/
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if "__file__" in dir() else os.getcwd()
    inbox = os.path.join(root, "fs_topology", "nodes", host_name, "inbox")
    os.makedirs(inbox, exist_ok=True)

    # 1. 双层 ACL 检查 (Perimeter → Internal)
    from security.perimeter_acl import access_resource, print_access_result
    result = access_resource(host_name, filename)

    print()
    print("=" * 50)
    print(f"  HTTP Download: {filename}")

    if not result["allowed"]:
        print_access_result(result)
        return

    # 2. curl 下载
    import __main__
    net = getattr(__main__, "net", None)
    if net:
        host = net.get(host_name)
        if host:
            url = f"http://{server_ip}/{filename}"
            print(f"  Source:     {server_ip}")
            print(f"  URL:        {url}")
            t0 = time.time()
            host.cmd(f"curl -s -o '/tmp/{filename}' '{url}'")
            elapsed = round(time.time() - t0, 3)
            # 复制到 inbox
            dst = os.path.join(inbox, filename)
            host.cmd(f"cp '/tmp/{filename}' '{dst}' 2>/dev/null || true")
            size = os.path.getsize(dst) if os.path.exists(dst) else 0
            print(f"  Status:     {'OK' if size > 0 else 'FAILED'}")
            print(f"  Size:       {round(size/1024, 1)} KB")
            print(f"  Time:       {elapsed} s")
            print(f"  Saved to:   fs_topology/nodes/{host_name}/inbox/")
        else:
            print(f"  ERROR: 主机 {host_name} 不存在")
    else:
        print(f"  ERROR: Mininet 网络未连接")

    print("=" * 50)
    print()


def download_ftp():
    """FTP 下载（与 HTTP 一致的模式，使用 curl ftp:// 协议）。"""
    pass  # 如需实现，与 download_http 结构相同，切换为 ftp:// URL
