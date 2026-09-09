# 单机容量与配置建议

> 依据：`docs/capacity-report.md`（2000 事件 / 8 局并发）、`docs/acceptance-report.md`、
> `docs/llm-perf-report.md`（minimax-m3 真实延迟）。环境：Windows 10 · Python 3.10.20。

## 1. 实测基线（先记住这几个数）

| 指标 | 数值 | 含义 |
|---|---:|---|
| 单引擎顺序吞吐 | **48 events/s** | 纯框架开销（MockLLM）≈ 21 ms/event |
| 单引擎并发(max=8) | 45 events/s | 单引擎受共享经验库/对象存储与 GIL 限制，收益有限 |
| **多局并发聚合** | **199 events/s** | 8 局 × 250 事件，10.1s 完成，≈ 4× 单局 |
| 单事件时延（Mock） | p50 ≈ 15 ms / p95 ≈ 17 ms | 编排 + 持久化 + 治理 |
| 单批峰值内存 | ≈ 1.7 MB / 200 事件 | 内存线性增长，8 局 2000 事件量级 < 20 MB |
| 真实 LLM 延迟 | p50 ≈ 2.3 s / p95 ≈ 5.9 s | **含真实模型时，瓶颈是模型，不是框架** |
| LLM 缓存命中 | ≈ 0.1 ms | 重复 prompt 直接命中，节省调用 |

**结论**：框架本身开销 ~20 ms/event；接真实模型后，单局吞吐 ≈ `1 / LLM时延`
（p50 2.3s → ~0.43 events/s；p95 5.9s → ~0.17 events/s）。要提吞吐，**优先并发局数 + 有界并发**，
而不是单局串行堆事件。

## 2. 吞吐估算模型

```
单机总吞吐 ≈ min( CPU/框架上限 , 并发能力 / 平均单事件耗时 )

框架上限（Mock）        ≈ 200 events/s（8 局聚合，实测）
真实模型单事件耗时        ≈ LLM时延 + 20ms（框架）
单局吞吐（串行）          = 1 / 单事件耗时
单机吞吐（K 局并发）      ≈ K × 单局吞吐 × 重叠系数(0.6~0.9)
```

示例（p50=2.3s，重叠系数 0.8）：

| 并发局数 K | 理论吞吐(events/s) | 每小时 |
|---:|---:|---:|
| 1 | 0.43 | ~1.5k |
| 4 | 1.4 | ~5.0k |
| 8 | 2.8 | ~10k |
| 16 | 5.5 | ~20k |

> 若事件可批量合并（一次 LLM 处理多条）或使用缓存命中，吞吐可显著高于上表。

## 3. 推荐配置（按规模）

### A. 演示 / 开发（单局、低频）
- 事件量：≤ 200/局；并发局数：1
- `DECK_MAX_CONCURRENCY=1`，`poll_interval=1.0`
- 存储：SQLite（`data/games.db`、`data/state.db`）——保留断点续跑
- 战例库：JSONL（默认）；`TRACE_ENABLED=1`（便于复盘）
- 适用：验收、单机演示、调试

### B. 常规推演（推荐生产基线）
- 事件量：每局 200~1000；并发局数：**4~8**
- `DECK_MAX_CONCURRENCY=2~4`（单局内对有依赖的步骤仍串行，独立事件可并发）
- 存储：SQLite（WAL 模式）；`poll_interval=1.0`
- 战例库：`LLM_CACHE_SIZE=256`、`LLM_CACHE_TTL=3600`
- 配额：`DECK_TENANT_QUOTA=100000`（按局/租户）
- 观测：`/metrics` 常开；OTLP 仅在需要时 `OTEL_ENDPOINT=...`
- 预期：聚合 ~150~250 events/s（Mock）/ ~3~6 events/s（真实模型，取决于局数与并发）

### C. 高并发单机（压满）
- 并发局数：**8~16**（每局独立引擎/事件队列/战例库）
- `DECK_MAX_CONCURRENCY=4~8`
- 存储：**PostgreSQL**（`state_db_url=postgresql+asyncpg://...`）——避免 SQLite 写锁成为瓶颈
- 经验库：内存检索 + 分文件 JSONL；或改为外部向量库（超出当前范围）
- 观测：指标常开，OTLP 采样（避免导出本身成为瓶颈）
- 预期：Mock 聚合 200+ events/s；真实模型取决于外部模型配额/并发上限

## 4. 扩容/降级阈值（触发即调整）

| 信号 | 阈值 | 动作 |
|---|---|---|
| `deck_event_latency_seconds` p95（Mock） | > 50 ms | 检查经验库规模/对象存储后端；考虑分片或换 PG |
| 经验库条目数 | > 5000 | 开启向量库/分片；或缩短召回 top_k、加 TTL 淘汰 |
| 单引擎 `max_concurrency` 提升收益 | < 10% | 停止加并发（GIL/共享锁）；改为**多局/多进程** |
| SQLite 写入等待/锁冲突 | 持续出现 | 切 PostgreSQL；`state_db_url` 指向共享库 |
| 真实模型 p95 | 接近 `LLM_TIMEOUT` | 提高超时/降并发/加缓存；或限流排队 |
| `deck_quota_denied_total` 上升 | 业务可接受？ | 调整 `DECK_TENANT_QUOTA` 或限流策略 |
| 单机 CPU 持续 > 80% | 持续 5 min | 减少并发局数，或横向扩到多机（超当前范围） |
| 内存 RSS | > 70% 机器内存 | 缩短战例库/复盘保留；分片到多进程 |

## 5. 关键调优参数速查

| 环境变量 | 默认 | 作用 |
|---|---|---|
| `DECK_MAX_CONCURRENCY` | 1 | 单批事件并发度（>1 用于独立事件） |
| `DECK_TENANT_QUOTA` | 100000 | 每租户 token 配额 |
| `LLM_TIMEOUT` | 60 | 单次模型调用超时（秒） |
| `LLM_MAX_RETRIES` | 3 | 模型调用重试次数 |
| `LLM_CACHE_SIZE` | 256 | 响应缓存条数（0=关闭） |
| `LLM_CACHE_TTL` | 3600 | 缓存有效期（秒） |
| `TRACE_ENABLED` / `TRACE_DIR` | 1 / data/traces | TraceLogger 开关与目录 |
| `OTEL_ENDPOINT` | 空 | 配置后开启 OTLP 导出 |

## 6. 部署形态建议（当前单机、非并行）

1. **一局一引擎**：每个推演局使用独立 `ObjectStore/EventBus/ExperienceStore`，互不干扰（已验证 8 局隔离）。
2. **同进程多局**：asyncio 并发，进程内不启多进程；单机 CPU 是天花板。
3. **持久化**：默认 SQLite；多局高写入时切 PostgreSQL。
4. **模型**：真实模型是外部依赖，建议在模型侧限并发/排队，应用侧用 `max_concurrency` 对齐。
5. **观测**：`/metrics` + 复盘时间线用于定位热点；OTLP 仅在需要分布式追踪时开启。

## 7. 一句话结论

> **单机推荐：4~8 个并发局、每局 200~1000 事件、`DECK_MAX_CONCURRENCY=2~4`、SQLite(WAL)；
> Mock 下可跑 150~250 events/s，接真实模型后吞吐由模型延迟主导（每局 ≈ 1/时延）。
> 当经验库 >5000 条或 SQLite 出现写锁，切 PostgreSQL / 分片；CPU 持续 >80% 时考虑多机。**
