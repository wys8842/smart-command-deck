# 架构与实现

本项目的实现分层与各层职责、关键类与调用关系。

## 1. 分层

```
接入层 app/api        FastAPI 路由 + 浏览器控制台 + uvicorn 启动
装配层 app/core       框架 Config/LLM/Capability/Tenancy/Tracing 的装配
领域层 app/domain     Ontology 对象/动作/关系/工作流/账务/战例/持久化
引擎层 app/engine     事件总线、图编排、HITL、事件泵、复盘
```

依赖方向：`api → engine → domain → core → agentorchestra`。领域层不依赖引擎层；
引擎层通过 `domain` 暴露的模型与能力工作。

## 2. 领域模型（`app/domain/schema.py`）

`create_engine(store=None, security_ctx=None, principal="staff", roles=None, permissions=None)`
注册对象类型与动作，并挂载 `run_workflow` 动作；`permissions` 为 `[(role, resource, action)]` 授权矩阵。

### 对象类型（ObjectType）

| api_name | 主键 | 属性 |
|---|---|---|
| `unit` | `unit_id` | `name` `side` `location` `status` `strength` |
| `target` | `target_id` | `name` `kind` `side` `threat` `location` |
| `order` | `order_id` | `kind` `unit_id` `target_id` `status` `approval` `params` |
| `stock` | `stock_id` | `kind` `qty` |
| `record` | `record_id` | `kind` `source` `round` `summary` `detail` |

### 链接类型（LinkType）

| 类型 | 方向 | 含义 |
|---|---|---|
| `adjacent_to` | unit → unit | 相邻 |
| `supports` | unit → unit | 支援 |
| `threatened_by` | unit → target | 受威胁 |
| `threatens` | target → unit | 威胁单位 |
| `near` | target → unit | 附近单位 |

### 动作（ActionType）

| 动作 | 参数 | 行为 |
|---|---|---|
| `scout` | `unit_id`, `area` | 读取单位并返回侦察报告 |
| `issue_order` | `order_id`, `kind`, `unit_id`, `target_id` | 写入 `order`（`status/approval=pending`） |
| `approve` | `order_id`, `approve` | 更新 `order.approval/status` |
| `execute_order` | `order_id` | 校验已批准后置 `status=executed` |
| `resupply` | `stock_id`, `qty` | 调整 `stock.qty` |
| `settle_round` | `round` | 写入 `record(kind=settle)` |
| `run_workflow` | `name`, `params_json` | 调用 `engine.workflow.run(name, initial_params, ctx)` |

动作经 `engine.mount(registry)` 生成工具：`QueryUnit/QueryTarget/QueryOrder/QueryStock/QueryRecord`
与各动作同名工具，供 Agent function-calling 使用。

### 工作流（`app/domain/workflows.py`）

- `strike_sequence`：`scout → issue_order → settle_round`
- `resupply_sequence`：`resupply → settle_round`

由 `build_workflows(engine)` 注册到 `engine.workflow`；`register_workflow_action(engine)` 注册
`run_workflow` 动作。

### 关系推理（`app/domain/relations.py`）

- `seed_scenario(store)`：写入 3 单位 + 2 目标 + 12 条双向链接与 1 条账目
- `ensure_scenario(store)`：对象或链接缺失时重建（图链接为进程内内存图）
- `situation(store, unit_id, depth)`：BFS 邻域，返回 `{unit, neighbors[], count}`
- `SituationQueryTool`：工具 `query_situation`（参数 `unit_id`、`depth`）

## 3. 引擎与编排（`app/engine/`）

### 事件总线 `event_bus.py`

`EventBus(path)`：append-only JSONL，每行 `{"_t":"e",...}` 或 `{"_t":"p","ev_id":...}`。
`enqueue/pending/mark_processed/receipt/list_receipts/is_processed/reset`；`enqueue` 用集合去重 O(1)，
写入复用文件句柄。

### 图与节点 `graphs.py` / `deck.py`

- `IntelAgentNode(Node)`：执行 Agent；支持 `recall_fn` 注入历史战例；把事件元数据传给下游。
- `build_intel_graph(factory, store)`：最小图 `entry → intel → record`。
- `build_deck_graph(factory, store, recall_fn=None)`：完整 DAG
  `entry → route(low/high) → record | intel → create → approve → execute/settle`。
- `route` 用 `NodeOutput.route` 驱动条件边；`approve` 在命令未批准时返回 `route=None` 停下。

### 事件泵 `service.py` / `background.py`

`process_pending(engine, bus, intel_agent_factory, thread_id, replay_store, state_store,
max_concurrency, experience, tenancy)`：

1. `_tenant_of(event)` 取 `tenant/tokens`；`TenantGovernor.charge` 超限则事件进入 `denied`。
2. 顺序模式复用单个 `GraphScheduler` 与 Agent；`max_concurrency>1` 时每事件独立图/调度器并发。
3. 每次执行记录 `deck_event_latency_seconds{kind}`；`state_store` 存在时 `ensure_interrupts` 生成
   HITL 中断；成功后 `_save_case` 沉淀战例。
4. 返回 `{processed, processed_count, denied, pending_left}`。

`PumpWorker(engine, bus, poll_interval, intel_agent_factory, thread_id, replay_store, state_store,
max_concurrency, experience, tenancy)`：`poll_once` 调用 `process_pending`，`run` 轮询直到 `stop`。

### HITL `hitl.py` / `interrupts.py`

- `approve_order(store, order_id, decision)` / `pending_orders(store)` / `approval_event(order_id, decision)`
- `ensure_interrupts(store, state_store, thread_id)`：为 pending 命令创建
  `Interrupt(reason="order_approval")`（同一 order 幂等）
- `resolve_approval(state_store, order_id, decision)`：`resolve_interrupt` 并记录
  `deck_approval_wait_seconds`
- `approval_resume_handler(store, bus, thread_id)`：Resumer 命中 RESUMED 后落审批 + 入队续跑事件

### 复盘 `replay.py`

- `ReplayStore(path)`：append-only JSONL 保存每次执行的 `NodeEvent` 时序
- `export_timeline(store, replay_store, thread_id, limit)`：`summary/orders/records/timeline`
- `run_scripted_scenario(store, factory, n_orders)`：脚本化端到端场景

## 4. 持久化与状态（`app/domain/`）

- `persist.open_persistent_engine(db_path)`：`ObjectStore(GraphStore, SQLiteBackend)`，注册全部对象类型
- `state_store.open_state_store(db_url)` / `ensure_ready(store)`：框架 `CheckpointStore`（SQLite），
  供 `GraphScheduler` 落 Inbox/iteration 与 HITL Interrupt
- `coord_ledger.CoordinatorLedger`：`TransactionCoordinator` 账务（幂等重放、补偿回滚、DLQ）
- `ledger.register_ledger(tm, store)`：`TransactionManager` 纯 Saga 账务补偿

## 5. 治理与多租户（`app/core/tenancy.py`）

`TenantGovernor(default_limit)`：`ensure/charge/record_usage/scope/snapshot`；
底层为框架 `TenantManager`（ContextVar）、`QuotaManager`（token 配额）、`UsageRecorder`。
`charge` 不足抛 `QuotaExceeded`，`service` 将其转为事件 `denied` 并计数 `deck_quota_denied_total`。

## 6. 可观测（`app/core/tracing.py`、`app/core/observability.py`）

- `build_trace_config(trace_dir)`：开启框架 `TraceLogger`（JSONL+HTML）
- `init_otel()`：`OTEL_ENDPOINT` 存在时 `Components.enable_otel_trace`
- 指标：`deck_events_processed_total`、`deck_event_latency_seconds{kind}`、
  `deck_pump_cycle_seconds`、`deck_approval_wait_seconds{decision}`、`deck_quota_denied_total{tenant}`

## 7. 装配与能力（`app/core/`）

- `config.make_config()` / `init_components()`：框架 `Config` 与数据目录
- `llm_factory.build_config/build_llm/build_intel_agent/llm_mode`：真实模型（含超时/重试/缓存）与
  Mock 回退
- `llm_resilience.CachedLLM`：LRU+TTL 响应缓存（同步/异步）
- `capabilities`：`BattleExperienceCapability`（战例库 + `recall_battle_case` 工具）、
  `SituationCapability`（`query_situation` 工具）、`TelemetryCapability`（Prometheus/OTLP）；
  `install_app_capabilities(agent, experience, situation_store)` 在新建 Agent 时安装

## 8. 接入层（`app/api/`）

- `server.create_app(engine, bus, db_path, events_path, intel_agent_factory, config, pump,
  poll_interval, replay_store, state_store, max_concurrency, experience, trace, trace_dir, tenancy)`：
  装配全部路由、lifespan 启停 `PumpWorker` 与 `InterruptResumer`
- `launch.py`：`load_env()` → 预置引擎并 `ensure_scenario` → `create_app(...)` → `uvicorn`
- `ui.py`：控制台单页，调用上述 HTTP 接口

## 9. 关键调用链

```
POST /events → EventBus.enqueue
PumpWorker.run → service.process_pending
  → _tenant_of → TenantGovernor.charge
  → GraphScheduler.execute(deck graph)
      entry → route → intel(IntelAgentNode → Agent.arun → SymphonyLLM/CachedLLM)
                    → create(order pending)
                    → approve(Interrupt 创建，停下)
  → _save_case(ExperienceStore)
POST /approvals/{id} → interrupts.resolve_approval → InterruptResumer
  → approval_resume_handler → approve_order + EventBus.enqueue(approval_result)
PumpWorker → service.process_pending(entry_node="approve")
  → approve → execute → settle(record)
GET /games/{id}/replay → ReplayStore.runs + ObjectStore orders/records
```
