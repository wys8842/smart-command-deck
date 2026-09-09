# 智能推演指挥台 · 验收与压测报告（自动生成）

- 生成时间：2026-09-09 10:50:07
- Python：3.10.20 · 平台：Windows-10-10.0.26100-SP0
- 结论：**11/11 项通过**

## 一、功能验收

| 项 | 结果 | 说明 |
|---|---|---|
| 关系推理（u1 二跳邻域） | ✅ | 9 条关系 |
| 顺序压测 300 事件 | ✅ | 94 events/s |
| 有界并发(max=4) 100 事件 | ✅ | 157 events/s |
| 事件时延采样 50 次 | ✅ | p50=14.8ms p95=17.2ms |
| 战例召回缓存命中 | ✅ | hits=70 misses=250 |
| HITL Interrupt 批准续跑 | ✅ | status=executed |
| 配额超限拒绝 | ✅ | denied=1 |
| 崩溃续跑无重复 | ✅ | first=20 second=0 total=20 |
| TraceLogger 落盘 | ✅ | 2 文件 |
| Prometheus 指标输出 | ✅ | 9 条指标行 |
| 复盘时间线 | ✅ | 5 条运行记录 |

## 二、性能

| 场景 | 吞吐 | 说明 |
|---|---:|---|
| 顺序推演 | 94 events/s | 200 高危 + 100 低危（MockLLM） |
| 有界并发(max=4) | 157 events/s | 70 高危 + 30 低危 |
| 单事件时延 | p50=14.8ms / p95=17.2ms | 50 次采样（MockLLM，含持久化/编排） |

## 三、真实 LLM 延迟（minimax-m3）

- 模型：minimax-m3 · 样本：5
- p50：2269 ms
- p95：5904 ms
- 首次调用：2171 ms；缓存命中：0 ms
- 缓存统计：{'hits': 1, 'misses': 6, 'size': 6, 'hit_rate': 0.14285714285714285}

## 四、可观测指标（摘录）

```
# HELP deck_events_processed_total deck_events_processed_total
# TYPE deck_events_processed_total counter
deck_events_processed_total 473
# HELP deck_quota_denied_total deck_quota_denied_total
# TYPE deck_quota_denied_total counter
deck_quota_denied_total{tenant="acme"} 1
deck_event_latency_seconds_count{kind="intel_report"} 472
deck_event_latency_seconds_count{kind="approval_result"} 1
deck_pump_cycle_seconds_count 58
```

## 五、回归测试

- `pytest tests`：62 passed（见仓库 CI）

> 说明：压测使用 MockLLM 以排除模型网络时延，衡量框架编排/持久化/治理开销；
> 真实模型延迟单独见 `docs/llm-perf-report.md`。
