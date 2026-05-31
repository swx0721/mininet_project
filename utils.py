"""
utils.py - 公共工具函数模块

提供日志记录、结果保存、CSV 导出等通用功能，
供 topology、experiments、analysis 等模块复用。
"""

import os
import csv
import time
import json
from datetime import datetime
from mininet.log import info, error, debug


# ==================== 路径管理 ====================

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
RESULT_DIR = os.path.join(PROJECT_ROOT, "results")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")

# 实验子目录
EXPERIMENT_SUBDIRS = {
    "qos": "qos",
    "load_balance": "load_balance",
}


def ensure_dirs():
    """确保结果和日志目录存在，并创建实验子目录。"""
    os.makedirs(RESULT_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    for subdir in EXPERIMENT_SUBDIRS.values():
        os.makedirs(os.path.join(RESULT_DIR, subdir), exist_ok=True)


def result_path(filename, subdir=None):
    """
    返回结果文件的完整路径，可选子目录。

    参数:
        filename: 文件名
        subdir:   子目录名（如 "bandwidth", "delay"），None 表示 results/ 根目录
    """
    ensure_dirs()
    if subdir:
        sub_path = os.path.join(RESULT_DIR, subdir)
        os.makedirs(sub_path, exist_ok=True)
        return os.path.join(sub_path, filename)
    return os.path.join(RESULT_DIR, filename)


def log_path(filename):
    """返回日志文件的完整路径。"""
    ensure_dirs()
    return os.path.join(LOG_DIR, filename)


# ==================== CSV 导出 ====================

def save_to_csv(filename, headers, rows):
    """
    将数据保存为 CSV 文件。

    参数:
        filename: 文件名（自动放在 results/ 目录下）
        headers:  列标题列表，如 ["bw", "throughput"]
        rows:     数据行列表，如 [[10, 8.2], [20, 17.5]]
    """
    filepath = result_path(filename)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    info(f"[UTILS] 结果已保存到 {filepath}")
    return filepath


def append_to_csv(filename, headers, row):
    """
    追加一行数据到 CSV 文件（若文件不存在则先写表头）。

    参数:
        filename: 文件名
        headers:  列标题列表
        row:      数据行列表
    """
    filepath = result_path(filename)
    file_exists = os.path.isfile(filepath)
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(headers)
        writer.writerow(row)
    info(f"[UTILS] 数据追加到 {filepath}: {row}")


# ==================== JSON 导出 ====================

def save_to_json(filename, data, subdir=None):
    """
    将数据保存为 JSON 文件，便于程序化读取。

    参数:
        filename: 文件名
        data:     可序列化的 Python 对象
        subdir:   子目录名
    """
    filepath = result_path(filename, subdir)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    info(f"[UTILS] JSON 已保存到 {filepath}\n")
    return filepath


# ==================== 日志 ====================

def log_message(tag, message, level="info"):
    """
    统一日志输出，带时间戳和标签。

    参数:
        tag:     标签，如 "TOPOLOGY", "SECURITY", "BANDWIDTH"
        message: 日志内容
        level:   日志级别 (info/error/debug)
    """
    timestamp = datetime.now().strftime("%H:%M:%S")
    formatted = f"[{timestamp}][{tag}] {message}"

    # 同时写入日志文件
    log_file = log_path(f"session_{datetime.now().strftime('%Y%m%d')}.log")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(formatted + "\n")

    # 输出到 Mininet 控制台
    if level == "error":
        error(formatted + "\n")
    elif level == "debug":
        debug(formatted + "\n")
    else:
        info(formatted + "\n")


# ==================== 时间戳 ====================

def timestamp():
    """返回当前时间戳字符串，用于文件名。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def format_duration(seconds):
    """将秒数格式化为可读字符串。"""
    if seconds < 60:
        return f"{seconds:.2f}s"
    elif seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:.0f}s"
    else:
        return f"{seconds // 3600}h{(seconds % 3600) // 60}m"


# ==================== 网络工具 ====================

def get_host_by_ip(net, ip_prefix):
    """
    根据 IP 前缀查找网络中的主机（用于实验）。

    参数:
        net:      Mininet 网络对象
        ip_prefix: IP 前缀，如 "10.0.1."

    返回:
        匹配的主机列表
    """
    hosts = []
    for host in net.hosts:
        for intf in host.intfList():
            if intf.ip and intf.ip.startswith(ip_prefix):
                hosts.append(host)
                break
    return hosts


def print_separator(title=None, width=60):
    """打印分隔线。"""
    if title:
        info("=" * width + "\n")
        info(f"  {title}\n")
        info("=" * width + "\n")
    else:
        info("=" * width + "\n")


# ==================== 网络信息打印 ====================

def print_subnet_info():
    """打印子网划分信息。"""
    info("子网划分方案：\n")
    info("  - 宿舍区: 10.0.1.0/24 (预留: 10.0.11.0/24)\n")
    info("  - 教学楼: 10.0.2.0/24 (预留: 10.0.12.0/24)\n")
    info("  - 图书馆: 10.0.3.0/24 (预留: 10.0.13.0/24)\n")
    info("  - 办公楼: 10.0.4.0/24 (预留: 10.0.14.0/24)\n")
    info("  - 财务处: 10.0.5.0/24 (预留: 10.0.15.0/24)\n")
    info("  - 人事处: 10.0.6.0/24 (预留: 10.0.16.0/24)\n")
    info("  - 服务器区1: 10.0.100.0/24 (预留: 10.0.110.0/24) — r1-eth5\n")
    info("  - 服务器区2: 10.0.101.0/24 (预留: 10.0.111.0/24) — r1-eth6\n")


def print_service_help(server_ip="10.0.100.2"):
    """打印可用服务测试命令。"""
    info("可用服务测试命令：\n")
    info(f"  - Web: 任意主机执行 'curl http://{server_ip}'\n")
    info(f"  - FTP: 任意主机执行 'curl ftp://{server_ip}/README.txt' (如果支持)\n")
    info(f"  - Ping: 任意主机执行 'ping {server_ip}'\n")
    info(f"  - iperf3: 任意主机执行 'iperf3 -c {server_ip}'\n")
