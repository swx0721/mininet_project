"""
demo_load.py — 单行加载交互式演示子系统

Mininet CLI 的 py 命令不支持 "from xxx import *" 语法。
使用此文件实现单行加载:

    mininet> py exec(open('demo_load.py').read(), globals())

加载后，以下函数直接可用:
    transfer_file  show_identity  enable_vpn  disable_vpn  switch_identity
    download_http  scan  show_blacklist  show_conntrack  flood
    access_resource  print_access_result
"""

# 通过 __import__ 逐模块加载
_interactive = __import__("interactive")
_file_transfer = __import__("interactive.file_transfer", fromlist=["transfer_file"])
_resource_access = __import__("interactive.resource_access", fromlist=["download_http"])
_identity_mgr = __import__("interactive.identity_manager", fromlist=["show_identity", "switch_identity", "enable_vpn", "disable_vpn"])
_demo = __import__("interactive.demo_commands", fromlist=["scan", "show_blacklist", "show_conntrack", "flood"])
_perimeter = __import__("security.perimeter_acl", fromlist=["access_resource", "check_perimeter_acl", "print_access_result"])

# 注入全局命名空间
transfer_file = _file_transfer.transfer_file
download_http = _resource_access.download_http
show_identity = _identity_mgr.show_identity
switch_identity = _identity_mgr.switch_identity
enable_vpn = _identity_mgr.enable_vpn
disable_vpn = _identity_mgr.disable_vpn
scan = _demo.scan
show_blacklist = _demo.show_blacklist
show_conntrack = _demo.show_conntrack
flood = _demo.flood
access_resource = _perimeter.access_resource
check_perimeter_acl = _perimeter.check_perimeter_acl
print_access_result = _perimeter.print_access_result

print("[DEMO] 交互式演示子系统已加载")
print("[DEMO] 可用: transfer_file, show_identity, enable_vpn, download_http, scan, flood, access_resource, ...")
