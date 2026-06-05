# Campus-Net 架构扩展方案

> VPN 远程接入 | 防 VPN 绕过 ACL | NAT 地址转换 | 双校区互联

---

## 扩展拓扑图

```
                              ┌──────────────────────────────────────────────┐
                              │                   Internet                     │
                              │                (203.0.113.0/28)                │
                              └──────┬───────────────────────┬───────────────┘
                                     │                       │
                         ┌───────────┴──┐        ┌───────────┴──────────────┐
                         │  inet_rt     │        │     Home Network          │
                         │ (NAT 网关)   │        │   (192.168.100.0/24)      │
                         └──────┬───────┘        └──────────┬───────────────┘
                                │ 10ms                      │ 20ms
                    ┌───────────┴───────────────────────────┴──────────────┐
                    │                                                        │
                    │              ┌──────────────────┐                      │
                    │              │   vpn_gw          │  VPN 网关            │
                    │              │ (10.0.80.0/24)    │  SNAT: 校外→虚拟地址  │
                    │              └────────┬─────────┘                      │
                    │                       │ (接入办公楼子网)                 │
                    │   ┌───────────────────┴─────────────────────────────┐  │
                    │   │                   Campus-A 核心路由器 r1          │  │
                    │   │              (HTB QoS + ACL + Round Robin)        │  │
                    │   └───┬───────┬───────┬───────┬───────┬──────┬───────┘  │
                    │       │       │       │       │       │      │          │
                    │   ┌───┴──┐┌───┴──┐┌───┴──┐┌───┴──┐┌───┴──┐┌──┴──┐     │
                    │   │Dorm ││Teach ││ Lib  ││Office││Finance││ HR  │     │
                    │   │/20  ││ /20  ││ /23  ││ /24  ││ /26  ││ /26 │     │
                    │   └─────┘└──────┘└──────┘└──────┘└──────┘└─────┘     │
                    │                                                        │
                    │   ┌──────────────────────────┐    ┌─────────────────┐  │
                    │   │  wan_rt                  │    │   WAN Router     │  │
                    │   │  (172.16.0.0/30)          │    │                 │  │
                    │   └────────┬─────────────────┘    └────────┬────────┘  │
                    │            │                                │           │
                    │   ┌────────┴─────────────────┐    ┌────────┴────────┐  │
                    │   │     Campus-B              │    │  campusb_rt     │  │
                    │   │   (10.1.0.0/16)           │    │  campusb_h1     │  │
                    │   └──────────────────────────┘    └─────────────────┘  │
                    │                                                        │
                    └────────────────────────────────────────────────────────┘
```

---

## 新增模块文件清单

| 文件 | 说明 | 大小 |
|------|------|------|
| `core/extended_topology.py` | 扩展拓扑（VPN网关+NAT路由器+Campus-B） | ~250 行 |
| `policies/vpn.py` | VPN 远程接入模块 | ~160 行 |
| `policies/nat.py` | NAT/MASQUERADE 模块 | ~140 行 |
| `security/acl_vpn.py` | 防VPN绕过增强ACL + 身份组 | ~180 行 |
| `core/dual_campus.py` | 双校区静态路由 + 通信测试 | ~180 行 |
| `experiments/run_extended_experiments.py` | 四大扩展实验统一入口 | ~300 行 |

**现有文件无需修改**，所有新功能以独立模块叠加，保持完全向后兼容。

---

## 各模块详细设计

### 1. VPN 远程接入模块 (`policies/vpn.py`)

**核心机制：**
- VPN 网关（LinuxRouter，双接口）模拟 OpenVPN 隧道端点
- 校外流量经 VPN 网关 SNAT 伪装为 10.0.80.0/24 虚拟地址池
- ACL 通过匹配 10.0.80.0/24 识别 VPN 用户身份

**技术路线（Mininet 环境 GPU 级模拟）：**
```
home_pc (192.168.100.10)
  → home_rt (家庭路由, 192.168.100.1)
  → [模拟公网, 20ms延迟]
  → vpn_gw (eth0: 公网侧, eth1: 校园网侧 10.0.34.10)
  → iptables SNAT: 192.168.100.0/24 → 10.0.80.10
  → r1 (FORWARD链 + VPN ACL规则)
  → 目标服务器 (10.0.60.2)
```

**地址分配表：**

| 节点 | IP | 角色 |
|------|-----|------|
| home_pc | 192.168.100.10 | 校外用户终端 |
| home_rt | 192.168.100.1 | 家庭路由器 |
| vpn_gw (公网侧) | 10.0.34.10 | VPN网关校园网接口 |
| vpn_gw (虚拟侧) | 10.0.80.1 | VPN网关虚拟接口 |
| 虚拟地址池 | 10.0.80.0/24 | VPN用户地址池 |

### 2. ACL 防 VPN 绕过模块 (`security/acl_vpn.py`)

**升级要点：**
- 原 ACL 仅基于源 IP 子网（10.0.34.0/24 → finance）
- 新 ACL 引入身份组概念，增加 VPN_USER 身份
- VPN 用户流量因 SNAT 后源地址变为 10.0.80.10，可被精确拦截

**ACL 决策矩阵：**

| 源身份 | → 财务处 | → 人事处 | → HTTP/FTP | → 教学楼 |
|--------|---------|---------|-----------|---------|
| VPN_USER | DENY | DENY | ALLOW | ALLOW |
| STAFF | ALLOW | ALLOW | ALLOW | ALLOW |
| STUDENT | DENY | DENY | ALLOW | ALLOW |
| FINANCE_ADMIN | ALLOW | — | ALLOW | ALLOW |

### 3. NAT 模块 (`policies/nat.py`)

**实现：** iptables MASQUERADE on inet_rt

```
dorm1 (10.0.0.2)
  → r1 (路由: 0.0.0.0/0 → inet_rt)
  → inet_rt (iptables MASQUERADE: SNAT to 203.0.113.14)
  → ext_server (203.0.113.10)
```

**实验设计：**
- NAT OFF: 校园网主机 ping 203.0.113.10 → 100% loss
- NAT ON:  校园网主机 ping 203.0.113.10 → 0% loss

### 4. 双校区互联模块 (`core/dual_campus.py`)

**路由设计：**

| 路由器 | 目标网络 | 下一跳 | 接口 |
|--------|---------|--------|------|
| r1 (Campus-A) | 10.1.0.0/16 | 172.16.0.1 | r1-eth9 |
| r1 (Campus-A) | 0.0.0.0/0 | inet_rt | r1-eth8 |
| wan_rt | 10.0.0.0/16 | 172.16.0.1 | wan_rt-eth0 |
| wan_rt | 10.1.0.0/16 | 172.16.0.2 | wan_rt-eth1 |
| campusb_rt | 0.0.0.0/0 | 172.16.0.1 | campusb_rt-eth1 |

---

## 集成到 main.py

在 `main.py` 的 `mode_experiment()` 函数中添加以下注册：

```python
# 在 mode_experiment() 中的 experiments 字典中添加:
"vpn_test":       lambda: run_extended_experiment("vpn_test"),
"acl_vpn_test":   lambda: run_extended_experiment("acl_vpn_test"),
"nat_test":       lambda: run_extended_experiment("nat_test"),
"dual_campus_test": lambda: run_extended_experiment("dual_campus_test"),
```

完整的注册代码（追加到 main.py 末尾 mode_experiment 函数中）：

```python
_extended = {
    "vpn_test":       ("experiments.run_extended_experiments", "vpn_test"),
    "acl_vpn_test":   ("experiments.run_extended_experiments", "acl_vpn_test"),
    "nat_test":       ("experiments.run_extended_experiments", "nat_test"),
    "dual_campus_test": ("experiments.run_extended_experiments", "dual_campus_test"),
}
if experiment_name in _extended:
    mod_name, func_name = _extended[experiment_name]
    import importlib
    mod = importlib.import_module(mod_name)
    getattr(mod, f"run_{func_name}")()
    return
```

**添加依赖目录：**
```python
# 在 utils.py 的 EXPERIMENT_SUBDIRS 中添加:
"vpn",
"acl_vpn",
"nat",
"dual_campus",
```

---

## 实验运行指令

```bash
# VPN 功能测试
sudo python3 main.py --experiment vpn_test

# ACL 防 VPN 绕过测试（含对照组vs实验组对比）
sudo python3 main.py --experiment acl_vpn_test

# NAT 功能验证
sudo python3 main.py --experiment nat_test

# 双校区互联测试
sudo python3 main.py --experiment dual_campus_test

# 一键运行全部扩展实验
sudo python3 main.py --experiment vpn_test && \
  sudo python3 main.py --experiment acl_vpn_test && \
  sudo python3 main.py --experiment nat_test && \
  sudo python3 main.py --experiment dual_campus_test
```

---

## 实验结果记录格式

### VPN 实验 (`results/vpn/vpn_test_YYYYMMDD_HHMMSS.json`)
```json
{
  "_metadata": {"experiment": "vpn_test", "timestamp": "20260605_210000"},
  "vpn_to_http": {"success": true, "http_code": "200"},
  "vpn_to_finance": {"expected_denied": true, "actual_result": "blocked"},
  "vpn_to_hr": {"expected_denied": true, "actual_result": "blocked"}
}
```

### NAT 实验 (`results/nat/nat_test_YYYYMMDD_HHMMSS.json`)
```json
{
  "_metadata": {"experiment": "nat_test"},
  "nat_off_ping": {"expected": "fail", "result": "fail"},
  "nat_on_ping": {"expected": "success", "result": "success"}
}
```

### 跨校区实验 (`results/dual_campus/dual_campus_YYYYMMDD_HHMMSS.json`)
```json
{
  "_metadata": {"experiment": "dual_campus_test"},
  "ping": {"success": true, "rtt_avg": 20.5},
  "http": {"success": true, "http_code": "200"},
  "netcat": {"success": true, "received": "Hello from Campus-A!"},
  "iperf3": {"success": true, "throughput_mbps": 85.3}
}
```

---

## 报告新增章节建议

建议在现有报告 `项目总结报告.md` 中新增以下章节：

### 7. VPN 远程接入与 ACL 联动

（章节内容：VPN 网关设计、虚拟地址分配、ACL 身份组升级、防 VPN 绕过实验）

### 8. NAT 地址转换与外网访问

（章节内容：MASQUERADE 实现、NAT 消融对照实验、转换日志）

### 9. 双校区互联与跨校区通信

（章节内容：静态路由配置、ping/HTTP/FTP/netcat/iperf3 五维测试、性能评估）

### 10. 扩展实验体系总览

（实验列表、评估指标、消融对照逻辑更新）

---

## 兼容性保证

- **QoS（HTB）**：不变，继续作用于 r1-eth5/r1-eth6 服务器出口链路
- **Round Robin LB**：不变，`LoadBalancer` 类不受影响
- **ACL**：`security/acl_vpn.py` 替代 `security/acl.py` 的规则部署（`acl.py` 保留用于原业务）
- **IDS/Flood 防护/审计**：安全模块无需修改，VPN ACL 事件自动通过 `event_logger` 写入 SQLite
- **实验脚本**：原有三大实验（QoS/LB/Security）不受影响，新增实验独立运行

---

*扩展方案版本：v1.0 | 日期：2026-06-05*
