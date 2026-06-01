# CampusNet-Final 统一实验参数表

## 拓扑定义（固定不变）

### 业务区域映射
| 区域 | 交换机 | 主机 | IP 段 | 访问 |
|------|--------|------|-------|------|
| dorm | s_dorm | dorm1, dorm2 | 10.0.1.0/24 | Server2 |
| teach | s_teach | teach1, teach2 | 10.0.2.0/24 | Server1 |
| lib | s_lib | lib1, lib2 | 10.0.3.0/24 | Server2 |
| office | s_office | office1, office2 | 10.0.4.0/24 | Server1 |
| finance | s_finance | finance1, finance2 | 10.0.5.0/24 | Server1 |

### 核心路由器与服务器链路
| 接口 | 连接 | 用途 |
|------|------|------|
| r1-eth0 | s_dorm | 宿舍区上行 |
| r1-eth1 | s_teach | 教学楼上行 |
| r1-eth2 | s_lib | 图书馆上行 |
| r1-eth3 | s_office | 办公楼上行 |
| r1-eth4 | s_finance | 财务处上行 |
| r1-eth5 | s_server1 | Server1 独立链路 |
| r1-eth6 | s_server2 | Server2 独立链路 |

### 区域上行链路拓扑参数（不变）
| 区域 | 接口 | 拓扑带宽 | 延迟 | 用途 |
|------|------|---------|------|------|
| dorm | r1-eth0 | 10 Mbps | 5ms | 低速区域 |
| teach | r1-eth1 | 20 Mbps | 10ms | 低速区域 |
| lib | r1-eth2 | 30 Mbps | 5ms | 中速区域 |
| office | r1-eth3 | 50 Mbps | 2ms | 高速区域 |
| finance | r1-eth4 | 50 Mbps | 2ms | 关键业务 |

### 服务器链路拓扑参数（对称配置）
| 接口 | 拓扑带宽 | 延迟 | 用途 |
|------|---------|------|------|
| r1-eth5 (Server1) | 100 Mbps | 1ms | 高容量服务器链路 |
| r1-eth6 (Server2) | 100 Mbps | 1ms | 高容量服务器链路（对称） |

### 静态服务器映射（DEFAULT_STATIC_MAPPING）
```python
DEFAULT_STATIC_MAPPING = {
    "finance1": SERVER1_IP,    # 10.0.100.2
    "finance2": SERVER1_IP,
    "teach1": SERVER1_IP,
    "teach2": SERVER1_IP,
    "office1": SERVER1_IP,
    "office2": SERVER1_IP,
    "dorm1": SERVER2_IP,       # 10.0.101.2
    "dorm2": SERVER2_IP,
    "lib1": SERVER2_IP,
    "lib2": SERVER2_IP,
}
```

---

## QoS 消融实验参数

### 实验类型：(0,1,1) vs (1,1,1)

| 参数 | 实验组 (1,1,1) | 对照组 (0,1,1) |
|------|-----------------|-----------------|
| QoS | 启用（HTB） | 禁用（pfifo） |
| LB | 启用（Round Robin） | 启用（Round Robin） |
| Security | 启用（ACL+Intrusion+Audit） | 启用（ACL+Intrusion+Audit） |
| **QoS 策略** | apply_htb_policy() | apply_baseline_policy() |
| **LB 算法** | round_robin | round_robin |
| **ACL 规则** | 全部保留 | 全部保留 |

### QoS 配置（实验组）
```
区域 | rate (% 拓扑) | ceil (% 拓扑) | 队列
-----|---------------|--------------|------
dorm | 6 Mbps (60%)  | 10 Mbps      | sfq
teach | 14 Mbps (70%) | 20 Mbps      | sfq
lib | 21 Mbps (70%)  | 30 Mbps      | sfq
office | 35 Mbps (70%) | 50 Mbps      | sfq
finance | 35 Mbps (70%) | 50 Mbps      | sfq
```

### 实验场景

#### 场景 A（两服务器中等负载）
```
λ_total = 1.8 请求/秒
区域分布：
  - finance1: λ=0.4
  - teach1: λ=0.3
  - office1: λ=0.2
  - dorm1: λ=0.3
  - lib1: λ=0.2
预期结果：
  Server1: 0.9 req/s
  Server2: 0.9 req/s
```

#### 场景 B（Server1 高负载，Server2 中低负载）
```
λ_total = 1.8 请求/秒
区域分布：
  - finance1: λ=0.5
  - teach1: λ=0.4
  - office1: λ=0.3
  - dorm1: λ=0.2
  - lib1: λ=0.1
预期结果：
  Server1: 1.2 req/s（高负载但不过载）
  Server2: 0.6 req/s（中低负载）
```

### 关键参数
- Flow Duration: 5 秒
- 实验总时长: 60 秒
- Ping 间隔: 0.2 秒
- 重复次数: 3 次（消融对比）

---

## LB 消融实验参数

### 实验类型：(1,0,1) vs (1,1,1)

| 参数 | 实验组 (1,1,1) | 对照组 (1,0,1) |
|------|-----------------|-----------------|
| QoS | 启用（HTB） | 启用（HTB） |
| LB | 启用（Round Robin） | 禁用（Static） |
| Security | 启用（ACL+Intrusion+Audit） | 启用（ACL+Intrusion+Audit） |
| **QoS 策略** | apply_htb_policy() | apply_htb_policy() |
| **LB 算法** | round_robin | static |
| **服务器映射** | 动态轮询 50:50 | DEFAULT_STATIC_MAPPING |
| **ACL 规则** | 全部保留 | 全部保留 |

### 服务器出口瓶颈配置（两实验均相同）
```
每台服务器出口 HTB：20 Mbps
位置：server1-eth0, server2-eth0
队列：pfifo limit 1000
```

### 实验场景

#### 场景 A（两服务器中等负载）
```
λ_total = 0.5 请求/秒
区域分布：
  - finance1: λ=0.10
  - teach1: λ=0.10
  - office1: λ=0.05
  - dorm1: λ=0.10
  - lib1: λ=0.15
```

#### 场景 B（Server1 高负载，Server2 中低负载）
```
λ_total = 0.5 请求/秒
区域分布：
  - finance1: λ=0.18
  - teach1: λ=0.12
  - office1: λ=0.10
  - dorm1: λ=0.07
  - lib1: λ=0.03
```

### 关键参数
- 下载文件大小: 5 MB
- 服务器出口瓶颈: 20 Mbps（对称）
- Flow Duration: 基于文件大小自动（~2-3秒/文件）
- 实验总时长: 60 秒

---

## Security 验证实验参数

### 实验类型：功能验证（非消融）

| 参数 | 值 |
|------|-----|
| QoS | 启用（HTB） |
| LB | 启用（Round Robin） |
| Security | 启用（ACL+Intrusion+Audit） |

### 子实验清单
1. **ACL 访问控制验证**
   - dorm1 → finance1: 应阻断
   - office1 → finance1: 应放行

2. **端口扫描检测**
   - 扫描 Server1 端口 22, 23, 80, 443
   - 验证检测率 ≥ 90%

3. **Flood 防护**
   - ICMP Flood: rate-limit ≤ 100/s
   - TCP SYN Flood: rate-limit ≤ 10/s

4. **自动封禁机制**
   - 扫描后自动封禁源 IP
   - 验证被封禁 IP 无法访问

5. **SQLite 审计**
   - 查询审计日志表
   - 验证所有事件正确记录

---

## 实验流程规范

### 每个实验的启动流程
1. 清理旧 Mininet 网络：`mn -c`
2. 创建拓扑：`create_fresh_network()`
3. 启动服务（Web/FTP/iperf）
4. 应用安全策略：ACL + Intrusion + Audit
5. 应用 QoS 策略（根据实验类型）
6. 应用负载均衡算法（根据实验类型）
7. 运行流量生成
8. 收集数据 + 统计分析
9. 保存结果到 JSON/CSV

### 数据收集规范
- 每个请求记录：[req_id, client, target_ip, response_code, latency, size]
- 吞吐量统计：总字节数 / 总时间
- 公平性指数（Jain）：衡量服务器负载均衡程度
- 丢包率、抖动：对 UDP 流采样统计

### 结果输出规范
```
results/
├── qos_ablation_scene_A.json
├── qos_ablation_scene_B.json
├── lb_ablation_scene_A.json
├── lb_ablation_scene_B.json
├── security_test_acl.json
├── security_test_portscan.json
└── unified_summary.md
```

---

## 参数一致性检查清单

- [ ] 所有实验使用相同的 DEFAULT_STATIC_MAPPING
- [ ] 区域上行链路拓扑参数（bw, delay）不变
- [ ] 两个实验的场景定义相同（λ_total 一致）
- [ ] Security 模块在所有实验中保持启用
- [ ] HTB 配置在 apply_htb_policy() 中一致定义
- [ ] QoS 仅作用于区域上行链路，不作用于服务器链路
- [ ] LB 仅作用于服务器链路（轮询算法）
- [ ] 所有实验使用相同的 Flow Duration 和实验总时长

---

## 修改检查清单

- [ ] 删除所有 HR 区域定义
- [ ] 修复 LB 消融实验保留 QoS 和 Security
- [ ] 增加场景选择参数 --scenario A/B
- [ ] 统一使用 DEFAULT_STATIC_MAPPING，删除 LB_STATIC_MAPPING
- [ ] 明确 QoS 消融实验为 (0,1,1)
- [ ] 验证所有 YAML 配置已更新
