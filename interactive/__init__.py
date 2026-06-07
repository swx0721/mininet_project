"""
interactive/ — 交互式校园网络演示子系统

提供面向答辩演示的实时交互函数，支持在 Mininet CLI 中自由操作：
  - transfer_file()    任意主机间文件传输（MD5 + 吞吐统计）
  - download_http()    HTTP 资源下载
  - download_ftp()     FTP 资源下载
  - show_identity()    查看主机身份
  - switch_identity()  切换主机身份（VPN 场景）
  - enable_vpn()       开启 VPN（修改 iptables）
  - disable_vpn()      关闭 VPN（恢复隔离）
  - show_blacklist()   端口扫描黑名单
  - show_conntrack()   状态防火墙连接追踪
  - scan()             端口扫描攻击触发 IDS
  - flood()            Flood 攻击演示
  - access_resource()  双层 ACL 检查入口

加载方式（在 Mininet> 提示符下）:
    py import interactive

所有功能保留现有 QoS / RR / ACL / IDS / Firewall / VPN / 双校区。
"""

import sys


# ================================================================
# 共享工具函数（必须在所有 import 之前定义，供各子模块使用）
# ================================================================

def _find_mininet_cli_dict():
    """
    找到 Mininet CLI 的全局命名空间（py 命令在此执行）。

    Mininet 的 do_py() 使用 globals() —— 即定义 do_py 的模块的 __dict__，
    也就是 mininet.cli 模块的 __dict__。

    返回:
        dict | None: mininet.cli 的 __dict__，找不到则返回 None
    """
    cli_mod = sys.modules.get('mininet.cli')
    if cli_mod is not None:
        return cli_mod.__dict__

    for name, mod in sys.modules.items():
        if name.startswith('mininet') and hasattr(mod, 'CLI'):
            return mod.__dict__

    return None


def _find_main_dict():
    """
    找到 __main__ 的全局命名空间（main.py 的 globals）。
    作为 fallback，防止极端情况。
    """
    import __main__
    return __main__.__dict__


def get_net():
    """
    获取 Mininet 网络对象（供所有交互模块使用）。

    Mininet CLI 的 do_py() 方法执行代码时，net 存在 eval() 的 locals 字典里
    （{'net': self.mn, ...}），不是 sys.modules 或 __main__ 的模块属性。
    因此必须通过 inspect 回溯调用栈，在 CLI 执行帧的 f_locals 中找到 net。

    Returns:
        Mininet 对象 or None
    """
    import inspect

    # ── 方法 1: 回溯调用栈，在 frame locals/globals 中查找 net ──
    # 当 "py enable_vpn('home_pc')" 执行时：
    #   do_py() 的 eval(code, globals(), {'net': self.mn}) 把 net 放在 locals
    #   我们从 get_net() 一路回溯到 do_py() 的帧，就能找到它
    frame = inspect.currentframe()
    try:
        f = frame.f_back
        depth = 0
        while f is not None and depth < 30:
            # 先查 f_locals（CLI eval 的 locals）
            net = f.f_locals.get('net')
            if net is not None and hasattr(net, 'get'):
                return net
            # 再查 f_globals（模块级全局变量）
            net = f.f_globals.get('net')
            if net is not None and hasattr(net, 'get'):
                return net
            f = f.f_back
            depth += 1
    finally:
        del frame

    # ── 方法 2: __main__ 兜底 ──
    import __main__
    net = getattr(__main__, 'net', None)
    if net is not None and hasattr(net, 'get'):
        return net

    return None


# ================================================================
# 导入各子模块的函数
# ================================================================

from interactive.file_transfer import transfer_file
from interactive.resource_access import download_http, download_ftp
from interactive.identity_manager import show_identity, switch_identity, enable_vpn, disable_vpn
from interactive.demo_commands import show_blacklist, show_conntrack, scan, flood
from security.perimeter_acl import access_resource, check_perimeter_acl, print_access_result

# 所有交互函数字典（统一注入目标）
_INTERACTIVE_FUNCS = {
    'get_net': get_net,
    'transfer_file': transfer_file,
    'download_http': download_http,
    'download_ftp': download_ftp,
    'show_identity': show_identity,
    'switch_identity': switch_identity,
    'enable_vpn': enable_vpn,
    'disable_vpn': disable_vpn,
    'show_blacklist': show_blacklist,
    'show_conntrack': show_conntrack,
    'scan': scan,
    'flood': flood,
    'access_resource': access_resource,
    'check_perimeter_acl': check_perimeter_acl,
    'print_access_result': print_access_result,
}


def setup():
    """
    一键加载所有交互函数到 Mininet CLI 全局作用域。

    用法:
        mininet> py import interactive
        （__init__.py 底部自动调用 setup()）

    注入目标（按优先级）:
        1. mininet.cli.__dict__  —— py 命令的实际执行命名空间
        2. __main__.__dict__    —— main.py 的命名空间（fallback）
    """
    cli_dict = _find_mininet_cli_dict()
    main_dict = _find_main_dict()

    injected = set()
    targets = []
    if cli_dict is not None:
        targets.append(('mininet.cli', cli_dict))
    targets.append(('__main__', main_dict))

    for label, g in targets:
        gid = id(g)
        if gid in injected:
            continue
        injected.add(gid)
        g.update(_INTERACTIVE_FUNCS)

    print("[INTERACTIVE] 15 个交互函数已就绪")
    print("  get_net (net object locator)")
    print("  transfer_file, download_http, download_ftp")
    print("  show_identity, switch_identity, enable_vpn, disable_vpn")
    print("  show_blacklist, show_conntrack, scan, flood")
    print("  access_resource, check_perimeter_acl, print_access_result")


# ── 自动注册：当 Mininet CLI 通过 "py import interactive" 加载时立即 setup ──
setup()
