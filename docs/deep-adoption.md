# 深度应用 agentorchestra 与性能路线

> 目标：不只是"能跑"，而是**把框架能力用透 + 性能可度量、可持续优化**。
> 本文记录：当前用到哪些框架能力、下一步如何更深、性能基线与守则。

## 1. 当前已深度使用的框架能力

| 框架能力 | 在本项目的用法 | 位置 |
|---|---|---|
| Ontology 语义建模 | `ObjectType`/`ActionType` + rules，`engine.mount(registry)` 自动生成 Tool | `app/domain/schema.py` |
| Ontology 存储 | `ObjectStore`（内存 / SQLite 后端）+ 索引/查询工具 | `app/domain/persist.py` |
| 图编排 | `Graph` + `GraphScheduler` + `AgentNode/FunctionalNode/RouterNode` + 条件边 | `app/engine/deck.py` |
| 事件与节点事件 | `Inbox`（经 scheduler）、`NodeEvent` 时序 | `app/engine/service.py` |
| 事务运行时 | `TransactionCoordinator`（幂等/补偿/DLQ）+ 兼容垫片 | `app/domain/coord_ledger.py` |
| 状态持久化 | `CheckpointStore` / SQLite 持久化与续跑 | `app/domain/persist.py` |
| 装配门面 | `Components.enable_prometheus/metrics_collector` | `app/api/server.py` |
| 配置/LLM | `Config` 注入 + `SymphonyLLM`（.env 真实模型） | `app/core/llm_factory.py` |
| 可观测 | Prometheus 文本指标 + `/metrics` 端点 | `app/engine/service.py` |

## 2. 待深化的方向（按价值排序）

1. **capability/memory 战例召回**：沉淀成功处置案例；性能上用 TTL + 懒加载 + 向量缓存。
2. **Capability 注册表**：用 `runtime/capabilities` 统一装配 trace/memory/checkpoint 等特性。
3. **可观测深化**：`TraceLogger` 每局 JSONL/HTML + 可选 OTLP；SLO 指标（回合耗时、审批时长）。
4. **GraphStore 关系**：把敌我/隶属/相邻建成链接，供态势推理。
5. **多租户/配额**：多局隔离与资源配额（`governance/tenancy`）。

## 3. 性能基线（`python scripts/bench.py`）

第一轮优化前后（MockLLM，单机）：

| 指标 | 优化前 | 优化后 | 变化 |
|---|---:|---:|---:|
| EventBus enqueue ops/s | ~723 | ~11,700 | ×16 |
| EventBus mark_processed ops/s | ~1,120 | ~42,600 | ×38 |
| Deck 推演 events/s | ~116 | ~175 | +50% |
| Coordinator 事务 ops/s | ~376 | ~501 | +33% |

优化点：
- **EventBus/ReplayStore 改 append-only JSONL**：去掉每次操作整文件重写（O(n)→O(1)），
  并复用文件句柄；`enqueue` 去重改哈希集合。
- **复用 Agent 与 Scheduler**：`process_pending` 单实例复用 + 每次清空历史，避免重复构造。
- **指标埋点**：`deck_events_processed_total` / `deck_pump_cycle_seconds` 暴露在 `/metrics`。

## 4. 性能守则（改代码前请对照）

1. **禁止整文件重写**：状态类持久化一律 append-only / 批量提交。
2. **复用重对象**：Agent、Scheduler、LLM 客户端、DB 连接池；每次调用只重置必要状态。
3. **单机非并行前提下**：用异步 I/O 与批处理提升吞吐；如需并发，先测 p95 再引入有界并发。
4. **先量后调**：任何优化先跑 `scripts/bench.py` 记录基线，再对比。
5. **外呼隔离**：真实 LLM/外部系统的时延与框架开销分开度量（bench 用 Mock）。
6. **可观测常开**：`/metrics` 与复盘时间线用于定位热点（节点耗时、错误、回退）。

## 5. 运行

```bash
D:/python/miniconda/envs/llm/python.exe scripts/bench.py            # 生成 docs/perf-report.md
D:/python/miniconda/envs/llm/python.exe scripts/bench_llm.py        # 生成 docs/llm-perf-report.md
D:/python/miniconda/envs/llm/python.exe -m pytest tests -q          # 回归
```

## 6. 本轮已落地（1/2/3）

1. **持久化图状态**：`GraphScheduler(store=CheckpointStore)`（`app/domain/state_store.py`）
   —— Inbox/iteration 落 SQLite（`data/state.db`），`process_pending(state_store=...)` 接入。
2. **Ontology WorkflowEngine**：`app/domain/workflows.py` 注册
   `strike_sequence`（侦察→命令→结算）与 `resupply_sequence`（补给→结算），
   并暴露 `run_workflow` 工具供 Agent 触发。
3. **真实模型性能**：`app/core/llm_resilience.py::CachedLLM`（LRU+TTL 响应缓存）
   + `SymphonyLLM` 超时/重试（`LLM_TIMEOUT`/`LLM_MAX_RETRIES`）+ 有界并发
   （`process_pending(max_concurrency=...)`，`DECK_MAX_CONCURRENCY`）。

实测（minimax-m3）：**p50 ≈ 2.3s，p95 ≈ 5.9s，缓存命中 ≈ 0.1ms**（见 `docs/llm-perf-report.md`）。

4. **HITL 统一到框架 Interrupt**：`app/engine/interrupts.py`
   —— 待批命令生成 `Interrupt(reason=order_approval)`；`POST /approvals/{id}` 走
   `resolve_interrupt`，`InterruptResumer` 轮询 RESUMED 触发 handler（落审批 + 入队续跑）；
   `GET /interrupts` 查看待处理。已实测 o8：批准 → 续跑 → `executed` + 结算记录。
