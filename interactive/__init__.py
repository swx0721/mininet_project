"""
interactive/ — 交互式校园网络演示子系统

提供面向答辩演示的实时交互函数，支持在 Mininet CLI 中自由操作：
  - transfer_file()    任意主机间文件传输（MD5 + 吞吐统计）
  - download_http()    HTTP 资源下载
  - download_ftp()     FTP 资源下载
  - show_identity()    查看主机身份
  - switch_identity()  切换主机身份（VPN 场景）
  - show_blacklist()   端口扫描黑名单
  - show_conntrack()   状态防火墙连接追踪
  - scan()             端口扫描攻击触发 IDS
  - flood()            Flood 攻击演示

所有功能保留现有 QoS / RR / ACL / IDS / Firewall / VPN / NAT / 双校区。
"""

from interactive.file_transfer import transfer_file
from interactive.resource_access import download_http, download_ftp
from interactive.identity_manager import show_identity, switch_identity, enable_vpn, disable_vpn
from interactive.demo_commands import show_blacklist, show_conntrack, scan, flood
from security.perimeter_acl import access_resource, check_perimeter_acl, print_access_result
