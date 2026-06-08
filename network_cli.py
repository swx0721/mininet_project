"""
network_cli.py — Interactive Network Communication Framework

在 Mininet CLI 中提供交互式网络通信命令：
  - send:  主机间文件传输（经过真实拓扑路由）
  - msg:   文本消息通信 (TCP/Netcat)
  - ls:    查看节点的收件箱/发件箱
  - trace: 路径追踪（显示完整路由路径）

设计原则:
  1. 文件从 resources/ 统一资源目录读取，禁止运行时创建随机文件
  2. 传输经过真实拓扑路由（ACL/QoS/NAT/VPN 逻辑生效）
  3. 结果写入 results/fs_topology/ 目录结构
  4. 传输过程记录到 results/runtime_transfer.json

用法:
  sudo python3 main.py --model final
  mininet> source network_cli.py          # 加载扩展命令
  mininet> send dorm1 dorm2 campus.jpg    # 文件传输
  mininet> msg office1 dorm1 "hello"      # 文本消息
  mininet> dorm1 ls                       # 查看文件
  mininet> trace dorm1 office1            # 路径追踪
"""

import os
import time
import json
import hashlib
import shutil
from datetime import datetime

# ============================================================
# 路径配置（__file__ 在 py exec() 中不可用，回退到 cwd）
# ============================================================

def _find_project_root():
    """向上搜索直到找到 main.py，确定项目根目录。"""
    import os as _os
    try:
        p = _os.path.dirname(_os.path.abspath(__file__))
    except NameError:
        p = _os.getcwd()
    for _ in range(10):
        if _os.path.exists(_os.path.join(p, "main.py")):
            return p
        parent = _os.path.dirname(p)
        if parent == p: break
        p = parent
    return _os.getcwd()

PROJECT_ROOT = _find_project_root()
RESOURCES_DIR = os.path.join(PROJECT_ROOT, "resources")
FS_TOPOLOGY_DIR = os.path.join(PROJECT_ROOT, "fs_topology")
RUNTIME_LOG = os.path.join(PROJECT_ROOT, "fs_topology", "runtime_transfer.json")
FILE_DIR = "files"  # 统一目录名，与 init_fs_topology() 一致

# 预置示例文件列表（拓扑构建时写入各主机 outbox）
FILE_DISTRIBUTION = {
    "dorm1":      ["campus.jpg", "poster.jpg"],
    "dorm2":      [],
    "teach1":     ["通知_2026.docx"],
    "teach2":     [],
    "lib1":       [],
    "lib2":       [],
    "office1":    ["通知_2026.docx", "财务数据报表..xlsx"],
    "office2":    [],
    "finance1":   ["财务数据报表..xlsx"],
    "finance2":   [],
    "hr1":        ["VPN测试文件.pdf"],
    "hr2":        [],
    "home_pc":    ["VPN测试文件.pdf"],
    "campusb_h1": [],
    "server1":    ["DMS_essay.zip"],
    "server2":    [],
}

# 文件名 → resources/ 子目录映射
_FILE_SOURCES = {
    "campus.jpg":         "images",
    "poster.jpg":         "images",
    "通知_2026.docx":    "docs",
    "财务数据报表..xlsx": "docs",
    "VPN测试文件.pdf":    "misc",
    "DMS_essay.zip":     "zip",
}

# ============================================================
# 路由路径知识库（基于当前拓扑，支持扩展至双校区）
# ============================================================

ROUTING_PATHS = {
    # 宿舍区内部（二层，同交换机）
    ("dorm1", "dorm2"): ["dorm1", "s_dorm1", "dorm2"],
    ("dorm2", "dorm1"): ["dorm2", "s_dorm1", "dorm1"],
    # 教学楼内部
    ("teach1", "teach2"): ["teach1", "s_teach1", "teach2"],
    # 跨区域（三层，经核心路由器 r1）
    ("dorm1", "office1"): ["dorm1", "s_dorm1", "sd_agg", "r1", "s_office", "office1"],
    ("dorm1", "teach1"): ["dorm1", "s_dorm1", "sd_agg", "r1", "st_agg", "s_teach1", "teach1"],
    ("dorm1", "lib1"):    ["dorm1", "s_dorm1", "sd_agg", "r1", "s_lib", "lib1"],
    ("dorm1", "finance1"):["dorm1", "s_dorm1", "sd_agg", "r1", "s_finance", "finance1"],
    ("dorm1", "hr1"):     ["dorm1", "s_dorm1", "sd_agg", "r1", "s_hr", "hr1"],
    ("dorm1", "server1"): ["dorm1", "s_dorm1", "sd_agg", "r1", "s_server1", "server1"],
    ("dorm1", "server2"): ["dorm1", "s_dorm1", "sd_agg", "r1", "s_server2", "server2"],
    ("office1", "finance1"):["office1", "s_office", "r1", "s_finance", "finance1"],
    ("office1", "hr1"):   ["office1", "s_office", "r1", "s_hr", "hr1"],
    ("teach1", "server1"):["teach1", "s_teach1", "st_agg", "r1", "s_server1", "server1"],
    # 跨校区（Campus-A → Campus-B）
    ("dorm1", "campusb_h1"):  ["dorm1", "s_dorm1", "sd_agg", "r1", "wan_rt", "campusb_rt", "s_campusb", "campusb_h1"],
    ("office1", "campusb_h1"):["office1", "s_office", "r1", "wan_rt", "campusb_rt", "s_campusb", "campusb_h1"],
    ("teach1", "campusb_h1"): ["teach1", "s_teach1", "st_agg", "r1", "wan_rt", "campusb_rt", "s_campusb", "campusb_h1"],
    # 跨校区反向
    ("campusb_h1", "dorm1"):  ["campusb_h1", "s_campusb", "campusb_rt", "wan_rt", "r1", "sd_agg", "s_dorm1", "dorm1"],
    # VPN路径（home_pc → r1 经 s_home，VPN 由 iptables 控制）
    ("home_pc", "server1"):   ["home_pc", "s_home", "r1", "s_server1", "server1"],
    ("home_pc", "server2"):   ["home_pc", "s_home", "r1", "s_server2", "server2"],
    ("home_pc", "dorm1"):     ["home_pc", "s_home", "r1", "sd_agg", "s_dorm1", "dorm1"],
    ("home_pc", "dorm2"):     ["home_pc", "s_home", "r1", "sd_agg", "s_dorm1", "dorm2"],
    ("home_pc", "office1"):   ["home_pc", "s_home", "r1", "s_office", "office1"],
    ("home_pc", "teach1"):    ["home_pc", "s_home", "r1", "st_agg", "s_teach1", "teach1"],
    ("home_pc", "lib1"):      ["home_pc", "s_home", "r1", "s_lib", "lib1"],
    ("home_pc", "finance1"):  ["home_pc", "s_home", "r1", "s_finance", "finance1"],
    ("home_pc", "hr1"):       ["home_pc", "s_home", "r1", "s_hr", "hr1"],
    ("home_pc", "campusb_h1"):["home_pc", "s_home", "r1", "wan_rt", "campusb_rt", "s_campusb", "campusb_h1"],
    # 反向路径（校内 → home_pc）
    ("server1", "home_pc"):   ["server1", "s_server1", "r1", "s_home", "home_pc"],
    ("dorm1", "home_pc"):     ["dorm1", "s_dorm1", "sd_agg", "r1", "s_home", "home_pc"],
    # NAT路径（经inet_rt MASQUERADE）
    ("dorm1", "ext_server"):  ["dorm1", "s_dorm1", "sd_agg", "r1", "inet_rt(MASQ)", "s_inet", "ext_server"],
}


def _resolve_path(src, dst):
    """根据源主机和目标主机查找路由路径。"""
    key = (src, dst)
    if key in ROUTING_PATHS:
        return ROUTING_PATHS[key]
    # 泛化匹配：同区域 L2 通信
    for (s, d), path in ROUTING_PATHS.items():
        if s == src and len(path) <= 3:
            # L2: 尝试匹配同区域
            pass
    # 回退：生成默认路径
    return [src, "r1", dst]


# ============================================================
# 虚拟文件系统管理
# ============================================================

def init_fs_topology(host_list, force_rebuild=False):
    """
    初始化 fs_topology/ — 增量创建，不删除已有传输文件。

    - force_rebuild=True: 删除旧结构再重建（仅 main.py 首次启动时用）
    - force_rebuild=False: 只创建缺少的目录和预置文件，保留已有文件

    根据 FILE_DISTRIBUTION 从 resources/ 复制文件到各主机 files/ 目录。
    """
    # 1. 如果强制重建，删除旧 fs_topology
    if force_rebuild and os.path.exists(FS_TOPOLOGY_DIR):
        shutil.rmtree(FS_TOPOLOGY_DIR)
        print("[FS] fs_topology/ 已强制重建")

    nodes_dir = os.path.join(FS_TOPOLOGY_DIR, "nodes")
    os.makedirs(nodes_dir, exist_ok=True)

    created = 0
    copied = 0
    skipped = 0
    missing = []
    for host_name in host_list:
        host_dir = os.path.join(nodes_dir, host_name)
        files_dir = os.path.join(host_dir, "files")
        os.makedirs(files_dir, exist_ok=True)

        # 2. 根据 FILE_DISTRIBUTION 从 resources/ 复制预置文件（不覆盖已有文件）
        for filename in FILE_DISTRIBUTION.get(host_name, []):
            subdir = _FILE_SOURCES.get(filename, "")
            src_path = os.path.join(RESOURCES_DIR, subdir, filename) if subdir else os.path.join(RESOURCES_DIR, filename)
            dst_path = os.path.join(files_dir, filename)
            if os.path.exists(dst_path):
                skipped += 1  # 文件已存在，跳过（保留用户传输的文件）
                continue
            if os.path.exists(src_path):
                shutil.copy2(src_path, dst_path)
                copied += 1
            else:
                missing.append(f"{host_name}/{filename}")

    # 3. 初始化日志（如果不存在）
    if not os.path.exists(RUNTIME_LOG):
        with open(RUNTIME_LOG, "w") as f:
            json.dump({"transfers": [], "_generated": str(datetime.now())}, f, indent=2)

    msg = f"[FS] fs_topology/ 已就绪 ({len(host_list)} 个节点"
    if copied > 0:
        msg += f", 新增 {copied} 个预置文件"
    if skipped > 0:
        msg += f", 保留 {skipped} 个已有文件"
    msg += ")"
    print(msg)
    if missing:
        print(f"[FS] 缺失文件: {', '.join(missing[:5])}... (请补充 resources/)")
    return True


def check_resources():
    """检查 resources/ 目录是否存在且有文件（用户需手动准备）。"""
    if not os.path.exists(RESOURCES_DIR):
        print(f"[RESOURCES] resources/ 目录不存在，请手动创建并放入文件。")
        print(f"  路径: {RESOURCES_DIR}")
        print(f"  子目录: images/ docs/ zip/ misc/")
        return False
    file_count = 0
    for root, dirs, files in os.walk(RESOURCES_DIR):
        file_count += len(files)
    if file_count == 0:
        print(f"[RESOURCES] resources/ 目录为空，请手动放入资源文件。")
        print(f"  路径: {RESOURCES_DIR}")
        return False
    print(f"[RESOURCES] 已检测到 {file_count} 个资源文件")
    return True


def list_resources():
    """列出可用资源文件。"""
    print("\n  Available resources:")
    for root, dirs, files in os.walk(RESOURCES_DIR):
        for f in sorted(files):
            rel = os.path.relpath(os.path.join(root, f), RESOURCES_DIR)
            size = os.path.getsize(os.path.join(root, f))
            print(f"    {rel} ({size} bytes)")
    print()


# ============================================================
# 传输引擎
# ============================================================

def _md5_file(filepath):
    """计算文件 MD5。"""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_acl(src_name, dst_name, hosts, r1=None):
    """
    模拟 ACL 检查：判断源主机是否有权访问目标主机。

    两层 ACL 体系：
      Layer 1 — 校外隔离：home_pc 默认完全隔离（VPN 关闭时禁止访问任何校内主机）
      Layer 2 — 校内 ACL：敏感区域（财务处/人事处）仅白名单可访问

    支持真实 VPN 模式：当 home_pc 已通过 WireGuard 连接时，
    其身份切换为 VPN_USER，且拥有 10.0.80.x 虚拟 IP。

    返回:
        (allowed: bool, reason: str)
    """
    # 敏感区域列表
    sensitive_hosts = {"finance1", "finance2", "hr1", "hr2"}
    authorized_sources = {"office1", "office2", "finance1", "finance2", "hr1", "hr2"}
    external_hosts = {"home_pc"}

    # ────────────────────────────────────────────────
    # Layer 1 — 校外隔离（双重 ACL 第一层）
    # ────────────────────────────────────────────────
    if src_name in external_hosts:
        # 通过 identity_manager 查询 VPN 状态（运行时动态身份）
        try:
            from interactive.identity_manager import get_identity
            current_identity = get_identity(src_name)
        except (ImportError, ModuleNotFoundError):
            current_identity = "HOME_USER"  # 默认：VPN 关闭

        if current_identity == "VPN_USER":
            # VPN 已连接 → 进入 Layer 2 校内 ACL 判断
            # 注意：VPN 用户即使在虚拟 IP 层面也不可访问敏感区域
            if dst_name in sensitive_hosts:
                return False, ("ACL_VPN_DENY (VPN用户禁止访问敏感区域 — "
                               "iptables 规则基于 wg0 接口拦截)")
            else:
                return True, ("ACL_VPN_ALLOW (VPN已连接, 虚拟IP访问普通区域 "
                               "— 隧道: WireGuard)")
        else:
            # VPN 未连接 → 完全隔离，禁止访问任何校内主机
            return False, "ACL_EXTERNAL_BLOCK (校外主机未接入VPN，禁止访问校园网)"

    # ────────────────────────────────────────────────
    # Layer 2 — 校内 ACL（双重 ACL 第二层）
    # ────────────────────────────────────────────────
    if dst_name in sensitive_hosts:
        if src_name in authorized_sources:
            return True, "ACL_ALLOW (白名单放行)"
        else:
            return False, "ACL_DENY (非授权区域禁止访问敏感区域)"

    return True, "ACL_ALLOW"


def cmd_send(net, src_name, dst_name, filename):
    """
    文件传输命令。
    
    mininet> send dorm1 dorm2 campus.jpg
    
    流程:
      1. 从 resources/ 读取源文件
      2. 检查 ACL 权限
      3. 通过 TCP netcat 传输文件到目标主机
      4. 写入目标主机的 inbox/ 目录
      5. 记录传输日志到 runtime_transfer.json
    """
    src_host = net.get(src_name)
    dst_host = net.get(dst_name)

    if not src_host or not dst_host:
        print(f"[ERROR] 主机不存在: {src_name if not src_host else dst_name}")
        return

    # 1. 定位资源文件
    res_path = None
    for root, dirs, files in os.walk(RESOURCES_DIR):
        if filename in files:
            res_path = os.path.join(root, filename)
            break

    if not res_path:
        print(f"[ERROR] 资源文件不存在: resources/{filename}")
        print(f"  提示: 可用资源请查看 resources/ 目录")
        return

    file_size = os.path.getsize(res_path)
    file_size_mb = round(file_size / (1024 * 1024), 3)

    # 2. ACL 检查
    allowed, acl_reason = _check_acl(src_name, dst_name, None)
    if not allowed:
        print(f"[ACL] {acl_reason}  — 传输被拦截")
        _log_transfer(src_name, dst_name, filename, file_size_mb,
                      _resolve_path(src_name, dst_name), acl_reason, 0, False)
        return

    print(f"[SEND] {src_name} → {dst_name}: {filename} ({file_size_mb} MB)")

    path = _resolve_path(src_name, dst_name)
    print(f"[ROUTE] 路径: {' → '.join(path)}")
    print(f"[ACL] {acl_reason}")
    print(f"[PROTOCOL] TCP/Netcat — 经真实网络拓扑传输 (iptables/QoS/IDS 生效)")

    # ── 真实网络传输 (nc)：数据经 Mininet 拓扑路由 ──
    dst_ip = _get_ip(dst_host)
    tmp_send = f"/tmp/_send_{src_name}_{filename}"
    tmp_recv = f"/tmp/_recv_{dst_name}_{filename}"

    # 将源文件复制到 /tmp（所有命名空间共享文件系统，但 nc 连接走各自网络栈）
    shutil.copy2(res_path, tmp_send)
    if os.path.exists(tmp_recv):
        os.remove(tmp_recv)

    # 接收方：在其网络命名空间中启动 nc 监听
    dst_host.cmd("kill $(pgrep -f 'nc.*9999') 2>/dev/null; true")
    time.sleep(0.1)
    dst_host.cmd(f"nc -l 9999 > {tmp_recv} &")
    time.sleep(0.5)

    # 验证监听器已启动（ss 检查端口 9999）
    listener = dst_host.cmd(
        "ss -tlnp 2>/dev/null | grep 9999 || echo NOT_LISTENING"
    ).strip()
    if "NOT_LISTENING" in listener:
        # openbsd nc 备用语法
        dst_host.cmd(f"nc -l -p 9999 > {tmp_recv} &")
        time.sleep(0.5)

    # 发送方：通过真实网络拓扑发送文件
    # TCP 连接路径: src → s_src → [agg] → r1(iptables) → [agg] → s_dst → dst
    md5_src = _md5_file(res_path)
    start_time = time.time()
    nc_out = src_host.cmd(
        f"timeout 15 nc -w 10 {dst_ip} 9999 < {tmp_send} 2>&1"
    ).strip()
    elapsed = round(time.time() - start_time, 3)
    time.sleep(0.3)

    # 验证传输结果（MD5 校验确认数据完整性）
    dst_files = os.path.join(FS_TOPOLOGY_DIR, "nodes", dst_name, FILE_DIR)
    os.makedirs(dst_files, exist_ok=True)
    dst_file = os.path.join(dst_files, filename)
    transfer_ok = False

    if os.path.exists(tmp_recv) and os.path.getsize(tmp_recv) > 0:
        md5_recv = _md5_file(tmp_recv)
        if md5_src == md5_recv:
            transfer_ok = True
            shutil.copy2(tmp_recv, dst_file)

    # 发送方 files/ 写入副本（发送记录）
    src_files = os.path.join(FS_TOPOLOGY_DIR, "nodes", src_name, FILE_DIR)
    os.makedirs(src_files, exist_ok=True)
    shutil.copy2(res_path, os.path.join(src_files, filename))

    # 输出结果
    throughput = round(file_size_mb * 8 / elapsed, 2) if elapsed > 0 and file_size_mb > 0 else 0
    if transfer_ok:
        print(f"[OK] 传输完成! 耗时: {elapsed}s, 吞吐: {throughput} Mbps, MD5: ✓ 一致")
        print(f"[NETWORK] ✓ 数据经真实 TCP/IP 栈传输")
    else:
        recv_size = os.path.getsize(tmp_recv) if os.path.exists(tmp_recv) else 0
        if recv_size == 0:
            print(f"[FAIL] 网络拦截! 0 bytes received")
            if nc_out:
                print(f"[DIAG] nc 发送端输出: {nc_out[:200]}")
            from interactive import get_net
            net = get_net()
            if net:
                r1 = net.get("r1")
                if r1:
                    # ── r1 内核参数（rp_filter / ip_forward）──
                    sysctl_out = r1.cmd(
                        "sysctl net.ipv4.conf.all.rp_filter "
                        "net.ipv4.ip_forward 2>/dev/null"
                    ).strip()
                    print(f"[DIAG] r1 内核参数:")
                    print(f"  {sysctl_out}")

                    # ── r1 wg0 路由 ──
                    wg_route = r1.cmd(
                        "ip route show dev wg0 2>/dev/null"
                    ).strip()
                    print(f"[DIAG] r1 wg0 路由: {wg_route}")

                    # ── wg0 规则及计数器 ──
                    wg_rules = r1.cmd(
                        "iptables -L FORWARD -n -v 2>&1 | grep -i wg0"
                    ).strip()
                    print(f"[DIAG] wg0 规则 (含收发包计数):")
                    if wg_rules:
                        for line in wg_rules.split('\n'):
                            print(f"  {line}")
                    else:
                        print(f"  (无 wg0 规则! VPN ACL 未正确加载)")

                # ── 接收方 nc 监听状态 ──
                listener = dst_host.cmd(
                    "ss -tlnp 2>/dev/null | grep -E '9999|State' "
                    "|| echo NOT_LISTENING"
                ).strip()
                print(f"[DIAG] 接收方 {dst_name} 端口 9999 状态:")
                print(f"  {listener}")

                # ── VPN 路由 + 连通性诊断 ──
                if src_name == "home_pc":
                    route = src_host.cmd(
                        "ip route show 2>/dev/null"
                    ).strip()
                    if route:
                        print(f"[DIAG] home_pc 路由表:")
                        for line in route.split('\n')[:10]:
                            print(f"  {line}")

                    # 快速 ping 测试 VPN 隧道是否工作
                    ping_result = src_host.cmd(
                        f"timeout 3 ping -c 1 -W 2 {dst_ip} 2>&1"
                    ).strip()
                    print(f"[DIAG] VPN ping {dst_ip}:")
                    print(f"  {ping_result[:300]}")
        else:
            print(f"[FAIL] 传输不完整! 接收: {recv_size}/{file_size} bytes")

    # 清理临时文件
    for p in [tmp_send, tmp_recv]:
        try:
            os.remove(p)
        except OSError:
            pass

    # 记录日志
    _log_transfer(src_name, dst_name, filename, file_size_mb, path, acl_reason, elapsed, transfer_ok)


def cmd_msg(src_host, dst_host, message):
    """
    文本消息通信 — 通过真实 nc 经网络拓扑发送。

    mininet> msg office1 dorm1 "Meeting at 3pm"

    消息内容经 TCP/Netcat 从发送方网络命名空间传输到接收方网络命名空间，
    经过真实路由路径（交换机→路由器→iptables→交换机）。
    """
    print(f"[MSG] {src_host.name} → {dst_host.name}: \"{message}\"")

    path = _resolve_path(src_host.name, dst_host.name)
    print(f"[ROUTE] 路径: {' → '.join(path)}")

    # ── 真实网络传输：消息内容经 nc 发送 ──
    dst_ip = _get_ip(dst_host)
    msg_ts = datetime.now().strftime("%H%M%S_%f")[:-3]
    msg_content = f"From: {src_host.name}\nTo: {dst_host.name}\nTime: {datetime.now()}\n---\n{message}\n"

    tmp_send = f"/tmp/_msg_send_{src_host.name}_{msg_ts}.txt"
    tmp_recv = f"/tmp/_msg_recv_{dst_host.name}_{msg_ts}.txt"

    # 写入发送方临时文件（共享文件系统，但 nc 连接走各自网络栈）
    with open(tmp_send, "w", encoding="utf-8") as f:
        f.write(msg_content)

    # 接收方监听（在其网络命名空间中绑定 IP）
    dst_host.cmd("kill $(pgrep -f 'nc.*9998') 2>/dev/null; true")
    time.sleep(0.1)
    dst_host.cmd(f"nc -l 9998 > {tmp_recv} &")
    time.sleep(0.5)

    # 发送方通过真实网络拓扑发送消息内容
    src_host.cmd(f"timeout 10 nc -w 5 {dst_ip} 9998 < {tmp_send} 2>&1")
    time.sleep(0.5)

    # 将接收到的消息复制到 fs_topology（模拟接收方保存）
    dst_files = os.path.join(FS_TOPOLOGY_DIR, "nodes", dst_host.name, "files")
    os.makedirs(dst_files, exist_ok=True)
    msg_file = os.path.join(dst_files, f"msg_{src_host.name}_{msg_ts}.txt")

    if os.path.exists(tmp_recv) and os.path.getsize(tmp_recv) > 0:
        shutil.copy2(tmp_recv, msg_file)
        print(f"[MSG] 网络传输完成 ✓ ({os.path.getsize(tmp_recv)} bytes)")
        print(f"[NETWORK] ✓ 消息经真实 TCP/IP 栈传输")
    else:
        print(f"[MSG] 网络传输失败 — 消息未送达 (ACL/防火墙可能拦截)")

    # 清理临时文件
    for p in [tmp_send, tmp_recv]:
        try:
            os.remove(p)
        except OSError:
            pass


def cmd_ls(host):
    """查看主机的 files/ 目录内容。"""
    node_dir = os.path.join(FS_TOPOLOGY_DIR, "nodes", host.name)
    files_dir = os.path.join(node_dir, "files")

    print(f"\n  [{host.name}] files/")
    if os.path.exists(files_dir):
        flist = os.listdir(files_dir)
        if flist:
            for f in sorted(flist):
                fp = os.path.join(files_dir, f)
                size = os.path.getsize(fp)
                md5 = _md5_file(fp)[:8] if os.path.isfile(fp) else ""
                print(f"    {f:<30s} {size:>8d} B  MD5:{md5}")
        else:
            print(f"    (empty)")


def cmd_trace(src_name, dst_name):
    """路径追踪：显示完整路由路径。"""
    path = _resolve_path(src_name, dst_name)
    print(f"\n  Trace: {src_name} → {dst_name}")

    # ACL 检查
    allowed, reason = _check_acl(src_name, dst_name, None)

    for i, hop in enumerate(path):
        marker = "★" if i == 0 else ("→" if i < len(path) - 1 else "→")
        hop_type = ""
        if hop.startswith("s_"):
            hop_type = "[SWITCH]"
        elif hop == "r1":
            hop_type = "[ROUTER]  (ACL/QoS)"
        elif hop in ("wan_rt", "campusb_rt"):
            hop_type = "[WAN]"
        print(f"  {i+1}. {marker} {hop} {hop_type}")

    if not allowed:
        print(f"\n  [ACL] {reason} — 传输将被拦截")
    else:
        print(f"\n  [ACL] {reason}")


# ============================================================
# 传输日志
# ============================================================

def _log_transfer(src, dst, filename, size_mb, path, acl_result, elapsed, md5_match):
    """记录传输事件到 runtime_transfer.json。"""
    entry = {
        "timestamp": str(datetime.now()),
        "src": src,
        "dst": dst,
        "file": filename,
        "size_mb": size_mb,
        "path": path,
        "acl_result": acl_result,
        "qos_delay_ms": round(elapsed * 1000, 1),
        "transfer_time_s": elapsed,
        "md5_match": md5_match,
    }

    try:
        with open(RUNTIME_LOG, "r") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {"transfers": [], "_generated": str(datetime.now())}

    data["transfers"].append(entry)

    os.makedirs(os.path.dirname(RUNTIME_LOG), exist_ok=True)
    with open(RUNTIME_LOG, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ============================================================
# 辅助函数
# ============================================================

def _get_ip(host):
    """获取主机 IP 地址。"""
    out = host.cmd("hostname -I 2>/dev/null || ip addr show | grep 'inet ' | awk '{print $2}' | cut -d/ -f1 | head -1")
    return out.strip().split()[0] if out.strip() else "127.0.0.1"


# ============================================================
# Mininet CLI 扩展注册
# ============================================================

def register_cli_commands():
    """
    在 Mininet CLI 中注册自定义命令。
    
    在 Mininet CLI (mininet>) 中运行:
        py exec(open('network_cli.py').read())
        register()
    
    之后即可使用:
        send dorm1 dorm2 campus.jpg
        msg office1 dorm1 "hello"
        dorm1 ls
        trace dorm1 office1
    """
    from mininet.cli import CLI
    from mininet.net import Mininet

    _net = Mininet._instance if hasattr(Mininet, '_instance') else None

    # 保存原始 do_help
    _orig_help = CLI.do_help if hasattr(CLI, 'do_help') else None

    def do_send(self, line):
        """send <src_host> <dst_host> <filename> — 主机间文件传输"""
        try:
            args = line.strip().split()
            if len(args) < 3:
                print("用法: send <src_host> <dst_host> <filename>")
                return
            src, dst, filename = args[0].strip("<>"), args[1].strip("<>"), args[2].strip("<>")
            if not self.mn:
                print("[ERROR] Mininet 网络不可用")
                return
            cmd_send(self.mn, src, dst, filename)
        except Exception as e:
            print(f"[ERROR] send 命令失败: {e}")

    def do_msg(self, line):
        """msg <src_host> <dst_host> <message> — 文本消息通信"""
        try:
            parts = line.strip().split(maxsplit=2)
            if len(parts) < 3:
                print("用法: msg <src_host> <dst_host> <message>")
                return
            src, dst, msg = parts[0].strip("<>"), parts[1].strip("<>"), parts[2].strip('"\'')
            if not self.mn:
                print("[ERROR] Mininet 网络不可用")
                return
            src_node = self.mn.get(src)
            dst_node = self.mn.get(dst)
            if not src_node or not dst_node:
                print(f"[ERROR] 主机不存在: {src if not src_node else dst}")
                return
            cmd_msg(src_node, dst_node, msg)
        except Exception as e:
            print(f"[ERROR] msg 命令失败: {e} (CLI 仍然可用)")

    def do_trace(self, line):
        """trace <src_host> <dst_host> — 路径追踪，显示完整路由+ACL判定"""
        try:
            args = line.strip().split()
            if len(args) < 2:
                print("用法: trace <src_host> <dst_host>")
                return
            cmd_trace(args[0].strip("<>"), args[1].strip("<>"))
        except Exception as e:
            print(f"[ERROR] trace 命令失败: {e} (CLI 仍然可用)")

    def do_ls_host(self, line):
        """ls <host_name> — 查看指定主机的 inbox/outbox 内容"""
        args = line.strip().split()
        if len(args) < 1:
            print("用法: ls <host_name>")
            print("示例: ls dorm1")
            return
        host_name = args[0].strip("<>")  # 容错：去掉用户误输入的尖括号
        try:
            if self.mn:
                host = self.mn.get(host_name)
                if host:
                    cmd_ls(host)
                else:
                    print(f"[ERROR] 主机不存在: {host_name}")
            else:
                print("[ERROR] Mininet 网络不可用")
        except Exception as e:
            print(f"[ERROR] ls 命令执行失败: {e} (不会退出 CLI)")

    def do_resources(self, line):
        """resources — 列出可发送的资源文件"""
        list_resources()

    # 注册命令 — Mininet CLI 命令以 "do_" 前缀自动识别
    CLI.do_send = do_send
    CLI.do_msg = do_msg
    CLI.do_trace = do_trace
    CLI.do_ls = do_ls_host     # 注册为 "ls" 命令
    CLI.do_resources = do_resources

    print("[CLI] 交互式网络通信框架已加载")
    print("[CLI] 命令: send <src> <dst> <file>  |  msg <src> <dst> <msg>")
    print("[CLI]        trace <src> <dst>        |  ls <host>")
    print("[CLI]        resources")
    print("[CLI] 示例: send dorm1 dorm2 campus.jpg")
    print("[CLI] 示例: msg office1 dorm1 \"hello\"")
    print("[CLI] 示例: trace dorm1 office1")


def register(net):
    """
    在 Mininet CLI 中加载并注册框架命令。

    Mininet CLI 中执行（单条命令，用 globals() 确保 exec 定义可见）:
        py (exec(open('network_cli.py').read(), globals()), register(net))[1]

    之后即可使用: send / msg / trace / ls / resources
    交互函数（enable_vpn 等）也同时加载。
    """
    print("[NETWORK_CLI] 正在初始化...")
    check_resources()
    # 增量初始化（不删除已有传输文件）
    init_fs_topology([h.name for h in net.hosts])
    register_cli_commands()
    print(f"[NETWORK_CLI] 框架已就绪！命令: send, msg, trace, ls, resources")
    print(f"[NETWORK_CLI] 文件系统: {FS_TOPOLOGY_DIR}/nodes/")
    print(f"[NETWORK_CLI] 传输日志: {RUNTIME_LOG}")

    # 自动加载交互式演示函数（enable_vpn / disable_vpn 等）
    try:
        import interactive
        # __init__.py 底部的 setup() 已自动调用，
        # 此处 import 确保交互函数已注入 Mininet CLI 命名空间。
        print("[NETWORK_CLI] 交互式演示函数已就绪"
              "（enable_vpn / disable_vpn / transfer_file ...）")
    except Exception as e:
        print(f"[NETWORK_CLI] 警告: 无法加载交互式演示函数: {e}")


print("[NETWORK_CLI] network_cli.py 已加载")


if __name__ == "__main__":
    print("Interactive Network Communication Framework")
    print("=" * 50)
    print("在 Mininet CLI 中运行:")
    print("  py exec(open('network_cli.py').read()); register(net)")
    print()
    print("可用命令:")
    print("  send <src> <dst> <filename>")
    print("  msg <src> <dst> <message>")
    print("  trace <src> <dst>")
    print("  resources")
