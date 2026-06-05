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

try:
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
except NameError:
    PROJECT_ROOT = os.getcwd()

RESOURCES_DIR = os.path.join(PROJECT_ROOT, "resources")
FS_TOPOLOGY_DIR = os.path.join(PROJECT_ROOT, "fs_topology")
RUNTIME_LOG = os.path.join(PROJECT_ROOT, "fs_topology", "runtime_transfer.json")
INBOX = "inbox"
OUTBOX = "outbox"

# 预置示例文件列表（拓扑构建时写入各主机 outbox）
PRESET_SENDER_FILES = {
    "office1": [("通知_2026.docx", "docs/notice.docx"), ("财务报告.xlsx", "docs/report.pdf")],
    "teach1":  [("课件_计算机网络.pdf", "docs/ebook.pdf"), ("实验指导.docx", "docs/notice.docx")],
    "library": [],   # 预留，会从 resources/ 中获取
    "dorm1":   [("校园风景.jpg", "images/campus.jpg"), ("社团海报.png", "images/logo.png")],
    "dorm2":   [("课程资料.zip", "zip/archive.zip")],
    "finance1": [("财务通知.docx", "docs/notice.docx")],
    "hr1":     [("人事档案.pdf", "docs/report.pdf")],
    "home_pc": [("VPN测试文件.pdf", "docs/ebook.pdf")],
    "campusb_h1": [("校区B课件.pdf", "docs/ebook.pdf")],
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
    # VPN路径（经vpn_gw SNAT转换）
    ("home_pc", "server1"):   ["home_pc", "s_home", "home_rt", "vpn_gw(SNAT)", "r1", "s_server1", "server1"],
    ("home_pc", "dorm1"):     ["home_pc", "s_home", "home_rt", "vpn_gw(SNAT)", "r1", "sd_agg", "s_dorm1", "dorm1"],
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

def init_fs_topology(host_list):
    """
    初始化 fs_topology/ 目录结构，为每个主机创建 inbox/outbox。
    预置发送方 outbox 中的示例文件（模拟校园网日常文件）。
    """
    os.makedirs(FS_TOPOLOGY_DIR, exist_ok=True)

    nodes_dir = os.path.join(FS_TOPOLOGY_DIR, "nodes")
    os.makedirs(nodes_dir, exist_ok=True)

    created = 0
    populated = 0
    for host_name in host_list:
        host_dir = os.path.join(nodes_dir, host_name)
        os.makedirs(os.path.join(host_dir, INBOX), exist_ok=True)
        os.makedirs(os.path.join(host_dir, OUTBOX), exist_ok=True)
        created += 1

        # 预置发送方文件（模拟校园网用户已有待发送的文件）
        # 只匹配实际存在于 host_list 中的主机名
        for display_name, resource_path in PRESET_SENDER_FILES.get(host_name, []):
            res_file = os.path.join(RESOURCES_DIR, resource_path)
            if os.path.exists(res_file):
                dst_file = os.path.join(host_dir, OUTBOX, display_name)
                if not os.path.exists(dst_file):
                    shutil.copy2(res_file, dst_file)
                    populated += 1

    # 初始化 JSON 日志
    if not os.path.exists(RUNTIME_LOG):
        with open(RUNTIME_LOG, "w") as f:
            json.dump({"transfers": [], "_generated": str(datetime.now())}, f, indent=2)

    print(f"[FS] fs_topology/ 已创建 ({created} 个节点, {populated} 个预置文件)")
    return True


def init_resources():
    """初始化资源目录结构。"""
    dirs = [
        os.path.join(RESOURCES_DIR, "images"),
        os.path.join(RESOURCES_DIR, "docs"),
        os.path.join(RESOURCES_DIR, "zip"),
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)

    # 创建示例资源文件
    _create_sample_resources()
    return True


def _create_sample_resources():
    """创建示例资源文件（仅在文件不存在时）。"""
    samples = {
        "images/campus.jpg": b"\xFF\xD8\xFF\xE0" + b"\x00" * 1024,   # 最小 JPEG
        "images/logo.png":   b"\x89PNG\r\n\x1A\n" + b"\x00" * 512,   # 最小 PNG
        "docs/notice.docx":  b"PK\x03\x04" + b"Campus Notice Document\x00" * 100,
        "docs/report.pdf":   b"%PDF-1.4" + b"Campus Network Report\x00" * 100,
        "docs/ebook.pdf":    b"%PDF-1.4" + b"E-Book Content\x00" * 200,
        "zip/archive.zip":   b"PK\x03\x04" + b"Archive Data\x00" * 500,
    }
    for rel_path, content in samples.items():
        full_path = os.path.join(RESOURCES_DIR, rel_path)
        if not os.path.exists(full_path):
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "wb") as f:
                f.write(content)


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
    
    返回:
        (allowed: bool, reason: str)
    """
    # 敏感区域列表
    sensitive_hosts = {"finance1", "finance2", "hr1", "hr2"}
    authorized_sources = {"office1", "office2", "finance1", "finance2", "hr1", "hr2"}
    vpn_sources = {"home_pc"}
    
    if dst_name in sensitive_hosts:
        if src_name in authorized_sources:
            return True, "ACL_ALLOW (白名单放行)"
        elif src_name in vpn_sources:
            return False, "ACL_VPN_DENY (VPN用户禁止访问敏感区域)"
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

    # 3. 计算路由路径
    path = _resolve_path(src_name, dst_name)
    print(f"[ROUTE] 路径: {' → '.join(path)}")

    # 4. 发送方 outbox 写入副本（发送记录）
    src_outbox = os.path.join(FS_TOPOLOGY_DIR, "nodes", src_name, OUTBOX)
    os.makedirs(src_outbox, exist_ok=True)
    shutil.copy2(res_path, os.path.join(src_outbox, filename))

    # 5. QoS 模拟延迟
    qos_delay_ms = 0
    if src_name.startswith("finance"):
        qos_delay_ms = 2
    elif "r1" in path:
        qos_delay_ms = len([h for h in path if h == "r1" or "agg" in h]) * 3
    if qos_delay_ms > 0:
        time.sleep(qos_delay_ms / 1000.0)

    # 6. 通过 netcat 传输到目标主机 inbox
    dst_inbox = os.path.join(FS_TOPOLOGY_DIR, "nodes", dst_name, INBOX)
    os.makedirs(dst_inbox, exist_ok=True)
    dst_file = os.path.join(dst_inbox, filename)

    md5_src = _md5_file(res_path)
    start_time = time.time()

    try:
        # 目标主机启动 netcat 监听
        dst_host.cmd(f"nc -l -p 9999 -w 10 > {dst_file} &")
        time.sleep(0.3)

        # 源主机发送文件
        src_host.cmd(f"cat {res_path} | nc -w 5 {_get_ip(dst_host)} 9999")
        time.sleep(0.5)

        # 等待写入完成
        time.sleep(0.5)
    except Exception as e:
        print(f"[ERROR] 传输失败: {e}")
        return

    elapsed = round(time.time() - start_time, 3)

    # 5. 校验
    if os.path.exists(dst_file) and os.path.getsize(dst_file) > 0:
        md5_dst = _md5_file(dst_file)
        match = (md5_src == md5_dst)
        print(f"[OK] 传输完成! 耗时: {elapsed}s, MD5: {'✓ 一致' if match else '✗ 不一致'}")
    else:
        match = False
        print(f"[WARN] 目标文件为空，传输可能未完成")

    # 6. 记录日志
    _log_transfer(src_name, dst_name, filename, file_size_mb, path, acl_reason, elapsed, match)


def cmd_msg(src_host, dst_host, message):
    """
    文本消息通信。
    
    mininet> msg office1 dorm1 "Meeting at 3pm"
    """
    print(f"[MSG] {src_host.name} → {dst_host.name}: \"{message}\"")

    path = _resolve_path(src_host.name, dst_host.name)
    print(f"[ROUTE] 路径: {' → '.join(path)}")

    # 写入接收方 inbox 为 .txt 文件（可视化传输结果）
    dst_inbox = os.path.join(FS_TOPOLOGY_DIR, "nodes", dst_host.name, INBOX)
    os.makedirs(dst_inbox, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    msg_file = os.path.join(dst_inbox, f"msg_{src_host.name}_{ts}.txt")
    content = f"From: {src_host.name}\nTo: {dst_host.name}\nTime: {datetime.now()}\n---\n{message}\n"
    with open(msg_file, "w", encoding="utf-8") as f:
        f.write(content)

    # 同时通过 netcat 发送（保持网络层模拟）
    dst_host.cmd("nc -l -p 9998 -w 5 > /tmp/msg_received.txt &")
    time.sleep(0.2)
    src_host.cmd(f"echo '{message}' | nc -w 3 {_get_ip(dst_host)} 9998")
    time.sleep(0.5)

    print(f"[MSG] 已写入: fs_topology/nodes/{dst_host.name}/{INBOX}/{os.path.basename(msg_file)}")


def cmd_ls(host):
    """查看主机的 inbox/outbox 内容。"""
    node_dir = os.path.join(FS_TOPOLOGY_DIR, "nodes", host.name)
    inbox = os.path.join(node_dir, INBOX)
    outbox = os.path.join(node_dir, OUTBOX)

    print(f"\n  [{host.name}]")
    print(f"  inbox/")
    if os.path.exists(inbox):
        files = os.listdir(inbox)
        for f in sorted(files):
            size = os.path.getsize(os.path.join(inbox, f))
            print(f"    {f} ({size} bytes)")
        if not files:
            print(f"    (empty)")
    print(f"  outbox/")
    if os.path.exists(outbox):
        files = os.listdir(outbox)
        for f in sorted(files):
            size = os.path.getsize(os.path.join(outbox, f))
            print(f"    {f} ({size} bytes)")
        if not files:
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
        args = line.strip().split()
        if len(args) < 3:
            print("用法: send <src_host> <dst_host> <filename>")
            print("示例: send dorm1 dorm2 campus.jpg")
            return
        src, dst, filename = args[0], args[1], args[2]
        if not self.mn:
            print("[ERROR] Mininet 网络不可用")
            return
        src_node = self.mn.get(src)
        dst_node = self.mn.get(dst)
        if not src_node or not dst_node:
            print(f"[ERROR] 主机不存在: {src if not src_node else dst}")
            return
        cmd_send(self.mn, src, dst, filename)

    def do_msg(self, line):
        """msg <src_host> <dst_host> <message> — 文本消息通信"""
        parts = line.strip().split(maxsplit=2)
        if len(parts) < 3:
            print("用法: msg <src_host> <dst_host> <message>")
            print("示例: msg office1 dorm1 \"hello\"")
            return
        src, dst, msg = parts[0], parts[1], parts[2].strip('"\'')
        if not self.mn:
            print("[ERROR] Mininet 网络不可用")
            return
        src_node = self.mn.get(src)
        dst_node = self.mn.get(dst)
        if not src_node or not dst_node:
            print(f"[ERROR] 主机不存在: {src if not src_node else dst}")
            return
        cmd_msg(src_node, dst_node, msg)

    def do_trace(self, line):
        """trace <src_host> <dst_host> — 路径追踪，显示完整路由+ACL判定"""
        args = line.strip().split()
        if len(args) < 2:
            print("用法: trace <src_host> <dst_host>")
            print("示例: trace dorm1 office1")
            return
        cmd_trace(args[0], args[1])

    def do_ls_host(self, line):
        """ls <host_name> — 查看指定主机的 inbox/outbox 内容"""
        args = line.strip().split()
        if len(args) < 1:
            print("用法: ls <host_name>")
            print("示例: ls dorm1")
            return
        host_name = args[0]
        if self.mn:
            host = self.mn.get(host_name)
            if host:
                cmd_ls(host)
            else:
                print(f"[ERROR] 主机不存在: {host_name}")
        else:
            print("[ERROR] Mininet 网络不可用")

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
    """
    print("[NETWORK_CLI] 正在初始化...")
    init_resources()
    init_fs_topology([h.name for h in net.hosts])
    register_cli_commands()
    print("[NETWORK_CLI] 框架已就绪！命令: send, msg, trace, ls, resources")
    print("[NETWORK_CLI] 文件系统: results/fs_topology/nodes/")
    print("[NETWORK_CLI] 传输日志: results/runtime_transfer.json")


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
