"""
report.py - 实验报告自动生成模块

读取实验结果 CSV 文件，自动生成格式化的实验报告。
支持 Markdown 和 HTML 两种输出格式。
"""

import os
import csv
from datetime import datetime
from analysis.plot import read_csv, PLOT_DIR
from mininet.log import info
from utils import RESULT_DIR, result_path, ensure_dirs, timestamp


REPORT_DIR = os.path.join(RESULT_DIR, "reports")


def ensure_report_dir():
    """确保报告目录存在。"""
    os.makedirs(REPORT_DIR, exist_ok=True)


def generate_markdown_report():
    """
    自动生成 Markdown 格式的实验报告。
    将所有实验结果汇总到一个报告中。
    """
    ensure_report_dir()
    ts = timestamp()
    filepath = os.path.join(REPORT_DIR, f"experiment_report_{ts}.md")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("# 校园网络仿真实验报告\n\n")
        f.write(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("---\n\n")

        # ---- 1. 网络拓扑概述 ----
        f.write("## 一、网络拓扑概述\n\n")
        f.write("本实验使用 Mininet 搭建了一个包含多子网的校园网络仿真系统。\n\n")
        f.write("### 子网划分\n\n")
        f.write("| 区域 | 网段 | 预留网段 |\n")
        f.write("|------|------|----------|\n")
        f.write("| 宿舍区 | 10.0.1.0/24 | 10.0.11.0/24 |\n")
        f.write("| 教学楼 | 10.0.2.0/24 | 10.0.12.0/24 |\n")
        f.write("| 图书馆 | 10.0.3.0/24 | 10.0.13.0/24 |\n")
        f.write("| 办公楼 | 10.0.4.0/24 | 10.0.14.0/24 |\n")
        f.write("| 财务处 | 10.0.5.0/24 | 10.0.15.0/24 |\n")
        f.write("| 人事处 | 10.0.6.0/24 | 10.0.16.0/24 |\n")
        f.write("| 服务器区 | 10.0.100.0/24 | 10.0.110.0/24 |\n\n")

        f.write("### 安全策略\n\n")
        f.write("- 状态防火墙：已启用 (ESTABLISHED,RELATED)\n")
        f.write("- ACL 访问控制：白名单+黑名单策略\n")
        f.write("- ICMP Flood 防护：1/s 限速\n")
        f.write("- QoS 流量控制：财务处流量在服务器出口优先保障\n")
        f.write("- ACL 日志审计：记录到 /var/log/campus_acl.log\n\n")

        f.write("### 网络服务\n\n")
        f.write("- Web 服务器 (端口 80, 线程化支持并发)\n")
        f.write("- FTP 服务器 (端口 21, 匿名访问)\n")
        f.write("- iperf3 性能测试服务器 (端口 5201)\n")
        f.write("- 50MB 大文件下载 (bigfile.bin)\n\n")

        f.write("---\n\n")

        # ---- 2. 实验结果 ----
        f.write("## 二、实验结果\n\n")

        # 自动检测并包含所有实验结果
        csv_files = sorted([f for f in os.listdir(RESULT_DIR)
                           if f.endswith(".csv") and not f.startswith("experiment_summary")])

        for csv_file in csv_files:
            headers, rows = read_csv(csv_file)
            if not headers or not rows:
                continue

            # 从文件名推断实验名称
            experiment_name = csv_file.replace(".csv", "").replace("_", " ").title()
            f.write(f"### {experiment_name}\n\n")
            f.write(f"**数据来源**: `{csv_file}`\n\n")

            # 写入表格
            f.write("| " + " | ".join(headers) + " |\n")
            f.write("| " + " | ".join(["---"] * len(headers)) + " |\n")
            for row in rows:
                f.write("| " + " | ".join(row) + " |\n")
            f.write("\n")

        # ---- 3. 图表 ----
        f.write("## 三、实验图表\n\n")
        plot_images = sorted([f for f in os.listdir(PLOT_DIR)
                            if f.endswith(".png")], key=lambda x: x)

        for img in plot_images:
            img_path = os.path.join(PLOT_DIR, img)
            rel_path = os.path.relpath(img_path, os.path.dirname(filepath))
            f.write(f"### {img.replace('_', ' ').replace('.png', '').title()}\n\n")
            f.write(f"![{img}]({rel_path})\n\n")

        # ---- 4. 结论 ----
        f.write("---\n\n")
        f.write("## 四、实验结论\n\n")
        f.write("（请根据实验结果在此补充分析结论）\n\n")
        f.write("1. **带宽性能**: ...\n\n")
        f.write("2. **网络时延**: ...\n\n")
        f.write("3. **并发能力**: ...\n\n")
        f.write("4. **QoS 效果**: ...\n\n")
        f.write("5. **安全策略有效性**: ...\n\n")

    info(f"[REPORT] 报告已生成: {filepath}\n")
    return filepath


def generate_html_report():
    """
    生成 HTML 格式的实验报告（更美观）。
    """
    ensure_report_dir()
    ts = timestamp()
    filepath = os.path.join(REPORT_DIR, f"experiment_report_{ts}.html")

    # 先获取 Markdown 内容
    md_file = generate_markdown_report()

    # 简单转换为 HTML
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>校园网络仿真实验报告</title>
    <style>
        body {
            font-family: 'Microsoft YaHei', Arial, sans-serif;
            line-height: 1.8;
            max-width: 900px;
            margin: 0 auto;
            padding: 30px;
            color: #333;
        }
        h1 { color: #1565C0; border-bottom: 3px solid #1565C0; padding-bottom: 10px; }
        h2 { color: #1565C0; border-bottom: 1px solid #ddd; padding-bottom: 5px; margin-top: 30px; }
        h3 { color: #333; margin-top: 20px; }
        table {
            border-collapse: collapse;
            width: 100%;
            margin: 15px 0;
        }
        th, td {
            border: 1px solid #ddd;
            padding: 8px 12px;
            text-align: left;
        }
        th { background-color: #1565C0; color: white; }
        tr:nth-child(even) { background-color: #f5f5f5; }
        img { max-width: 100%; border: 1px solid #ddd; border-radius: 5px; margin: 15px 0; }
        .meta { color: #666; font-size: 0.9em; }
        hr { border: none; border-top: 1px solid #ddd; margin: 25px 0; }
    </style>
</head>
<body>
""")

        # 读取 md 内容并转换为简单 HTML
        with open(md_file, "r", encoding="utf-8") as md:
            md_content = md.read()

        # 简单转换
        lines = md_content.split("\n")
        in_table = False
        for line in lines:
            if line.startswith("# "):
                f.write(f"<h1>{line[2:]}</h1>\n")
            elif line.startswith("## "):
                f.write(f"<h2>{line[3:]}</h2>\n")
            elif line.startswith("### "):
                f.write(f"<h3>{line[4:]}</h3>\n")
            elif line.startswith("| "):
                if not in_table:
                    in_table = True
                    f.write("<table>\n")
                cells = [c.strip() for c in line.split("|")[1:-1]]
                if "---" in line:
                    continue  # skip separator
                # Check if it's header (previous line was also | )
                f.write("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>\n")
            else:
                if in_table:
                    f.write("</table>\n")
                    in_table = False
                if line.startswith("![") and "](" in line:
                    alt = line[2:line.index("]")]
                    src = line[line.index("(")+1:line.index(")")]
                    f.write(f'<img src="{src}" alt="{alt}">\n')
                elif line.startswith("**") and line.endswith("**"):
                    f.write(f"<p class='meta'>{line.strip('*')}</p>\n")
                elif line.strip():
                    f.write(f"<p>{line}</p>\n")

        if in_table:
            f.write("</table>\n")

        f.write("""</body>
</html>""")

    info(f"[REPORT] HTML 报告已生成: {filepath}\n")
    return filepath


def generate_report():
    """生成所有格式的报告。"""
    md_file = generate_markdown_report()
    html_file = generate_html_report()
    info(f"[REPORT] 报告生成完成！\n")
    info(f"  Markdown: {md_file}\n")
    info(f"  HTML:     {html_file}\n")
    return md_file, html_file


if __name__ == "__main__":
    generate_report()
