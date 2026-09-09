# Smart Command Deck · 智能推演指挥台

回合制多智能体决策推演平台。以 [agentorchestra](https://github.com/wys8842/agentorchestra-v0.2.0)
（Symphony）作为底层库：Ontology 承载战场对象与动作，Graph 编排"研判→分级→建议→人工批准→执行→结算"，
事件泵驱动回合推进；单机、单进程、asyncio 协作。

- 运行环境：Python ≥ 3.10；框架 `agentorchestra` 0.2.0（editable 或 git 安装）
- 服务：FastAPI + uvicorn（`app/api/launch.py`）
- 存储：SQLite（`data/games.db`、`data/state.db`）、JSONL（事件/复盘/战例）
- 验证：`pytest tests`（62 用例）、`scripts/acceptance.py`（11 项端到端验收）

## 目录结构

```
app/
├── api/        接入层
│   ├── launch.py     uvicorn 启动入口（读取 .env、预置战场关系、create_app）
│   ├── server.py     FastAPI 应用与全部路由（create_app）
│   └── ui.py         浏览器控制台单页（HTML/JS）
├── core/       装配层（框架资源与横切能力）
│   ├── config.py        框架 Config 构建 / 数据目录
│   ├── env.py           .env 加载（KEY=VALUE，不覆盖已有环境变量）
│   ├── llm_factory.py   build_config / build_llm / build_intel_agent / llm_mode
│   ├── llm_resilience.py CachedLLM（LRU+TTL 响应缓存）
│   ├── mock_llm.py      离线 MockLLM
│   ├── capabilities.py  应用级 Capability（战例/态势/遥测）
│   ├── tenancy.py       TenantGovernor（租户上下文 + 配额 + 用量）
│   ├── tracing.py       TraceLogger 配置 / OTLP 开关 / 指标辅助
│   ├── observability.py Prometheus collector 初始化
│   └── compat.py        Python 3.10 的 asyncio.timeout 兼容垫片
├── domain/     领域层（Ontology 建模与业务能力）
│   ├── schema.py        ObjectType/LinkType/ActionType + create_engine
│   ├── workflows.py     Workflow（strike_sequence / resupply_sequence）+ run_workflow 动作
│   ├── relations.py     战场关系（seed_scenario/ensure_scenario/situation/SituationQueryTool）
│   ├── ledger.py        TransactionManager 账务补偿（纯 Saga）
│   ├── coord_ledger.py  TransactionCoordinator 账务（幂等/补偿/DLQ）
│   ├── experience.py    ExperienceStore（战例库：内存检索 + JSONL 持久化 + 召回缓存）
│   ├── persist.py       open_persistent_engine / close_engine（SQLite 对象存储）
│   ├── state_store.py   open_state_store / ensure_ready（CheckpointStore）
│   └── m3.py            预留模块
├── engine/     推演引擎
│   ├── event_bus.py     EventBus（append-only JSONL + 已处理去重）
│   ├── graphs.py        最小研判图（entry→intel→record）+ IntelAgentNode
│   ├── deck.py          完整推演 DAG（分级/建议/命令/HITL/执行/结算）
│   ├── pump.py          事件消息转换与单事件处理
│   ├── service.py       process_pending（顺序/有界并发；配额/战例/租户/指标）
│   ├── background.py    PumpWorker（常驻轮询消费）
│   ├── hitl.py          审批入口（approve_order/pending_orders/approval_event）
│   ├── interrupts.py    框架 Interrupt 封装（ensure/list/resolve + Resumer handler）
│   └── replay.py        ReplayStore + export_timeline + run_scripted_scenario
└── main.py     离线冒烟入口（python -m app.main --smoke）

scripts/
├── acceptance.py   端到端验收 + 压测 → docs/acceptance-report.md
├── capacity.py     容量压测（默认 2000 事件 / 8 局）→ docs/capacity-report.md
├── bench.py        框架组件基准 → docs/perf-report.md
├── bench_llm.py    真实模型延迟基准 → docs/llm-perf-report.md
├── llm_e2e.py      真实模型端到端压测 → docs/llm-e2e-report.md
└── check_secrets.py 密钥泄漏扫描（CI / pre-commit）

tests/            pytest 用例（62）
docs/             架构、运维、集成说明与自动生成的报告
```

## 安装与启动

```bash
LLM_PY="D:/python/miniconda/envs/llm/python.exe"

"$LLM_PY" -m pip install -e ../agentorchestra      # 框架（editable）
"$LLM_PY" -m pip install -e ".[dev]"               # 本项目 + 开发依赖
"$LLM_PY" -m pip install fastapi uvicorn           # 服务依赖

"$LLM_PY" -m app.api.launch                        # 启动 http://127.0.0.1:8000
"$LLM_PY" -m app.main --smoke                      # 离线冒烟
```

浏览器控制台：<http://127.0.0.1:8000/>（入队事件 / 待批批准 / 事件回执 / 复盘时间线）。

## HTTP 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 浏览器控制台（HTML） |
| GET | `/health` | 状态：订单数、pump、队列长度、LLM 模式/模型、capabilities |
| GET | `/metrics` | Prometheus 文本指标 |
| POST | `/events` | 事件入队。Body：`{kind, source, payload, round}`；返回 `{ev_id, seq, kind, status:"queued"}` |
| GET | `/events` | 事件回执列表（`limit`、`offset`） |
| GET | `/events/{ev_id}` | 单事件回执（`queued` / `processed`） |
| POST | `/games/{game_id}/pump` | 手动消费一次待处理事件（返回 `processed_count` / `denied` / `pending_left`） |
| GET | `/approvals` | 待批命令列表 |
| GET | `/interrupts` | 框架 Interrupt（HITL）待处理列表 |
| POST | `/approvals/{order_id}` | 批准/驳回。Body：`{approve: bool}`；返回 `interrupt_token`（走框架 Interrupt） |
| GET | `/games/{game_id}/replay` | 复盘：`orders` / `records` / `timeline`（节点时序） |
| GET | `/situation/{unit_id}` | 邻域态势（`depth` 默认 2），返回链接列表 |
| GET | `/experience/stats` | 战例库召回缓存统计 |
| GET | `/tenants` | 租户配额与用量快照 |

事件 `payload` 字段约定：`kind`、`order_id`、`unit_id`、`target_id`、`threat`(0–1)、`text`、
`tenant`（租户）、`tokens`（配额预估消耗）。

## 配置

`.env`（与 `.env.example` 同构，已被 `.gitignore` 忽略）：

```env
LLM_MODEL_ID=minimax-m3
LLM_BASE_URL=https://api.minimax.chat/v1
LLM_API_KEY=sk-xxx
```

| 环境变量 | 默认 | 作用 |
|---|---|---|
| `LLM_MODEL_ID` / `LLM_API_KEY` / `LLM_BASE_URL` | 空 | 真实模型；缺失则回退离线 `MockLLM` |
| `LLM_TIMEOUT` | 60 | 单次调用超时（秒） |
| `LLM_MAX_RETRIES` | 3 | 调用重试次数 |
| `LLM_RETRY_BASE_DELAY` | 1.0 | 重试退避基数（秒） |
| `LLM_CACHE_SIZE` | 256 | 响应缓存条数（0=关闭） |
| `LLM_CACHE_TTL` | 3600 | 缓存有效期（秒） |
| `DECK_MAX_CONCURRENCY` | 1 | 单批事件并发度 |
| `DECK_TENANT_QUOTA` | 100000 | 每租户 token 配额 |
| `TRACE_ENABLED` | 1 | 是否开启 TraceLogger |
| `TRACE_DIR` | data/traces | 轨迹输出目录 |
| `OTEL_ENDPOINT` | 空 | 配置后开启 OTLP trace 导出 |

## 核心流程（函数级）

1. 事件入队：`POST /events` → `EventBus.enqueue`（`app/engine/event_bus.py`），append-only JSONL。
2. 常驻消费：`PumpWorker.run` → `service.process_pending`（`app/engine/service.py`）。
3. 逐事件：`service._run_event` 取 `tenant/tokens`（`_tenant_of`）→ `TenantGovernor.charge`（超限进入
   `denied`）→ `GraphScheduler.execute` 跑 `deck.build_deck_graph`。
4. DAG：`entry → route(低/高) → record | intel(AgentNode) → create(待批命令) → approve(Interrupt) →
   execute / settle`（`app/engine/deck.py`）。
5. HITL：`approve` 节点停下 → `POST /approvals/{order_id}` 调 `interrupts.resolve_approval`
   （框架 `resolve_interrupt`）→ `InterruptResumer` 触发 `approval_resume_handler`（落审批 + 入队续跑）→
   泵从 `approve` 入口继续执行。
6. 观测：每事件记录 `deck_event_latency_seconds`；审批记录 `deck_approval_wait_seconds`；
   `TraceLogger` 输出每局 JSONL+HTML（`data/traces`）。
7. 战例：事件成功处置后 `service._save_case` 写入 `ExperienceStore`；下次研判前 `IntelAgentNode`
   调 `recall_fn` 把历史战例拼进任务。

## 数据与存储

| 路径 | 内容 |
|---|---|
| `data/games.db` | Ontology 对象存储（SQLite）：unit/target/order/stock/record |
| `data/state.db` | 框架 CheckpointStore：图 Inbox、iteration、Interrupt、锁、幂等、DLQ、审计 |
| `data/events.json` | EventBus 事件与已处理标记（每行一个 JSON） |
| `data/replay.json` | 每局节点时序（NodeEvent） |
| `data/experience.jsonl` | 战例库（内容/类型/标签/重要度） |
| `data/traces/` | TraceLogger 轨迹（JSONL + HTML） |

`data/`、`*.db`、`server.pid`、`.env` 均被 `.gitignore` 忽略。

## 测试与验收

```bash
"$LLM_PY" -m pytest tests -q          # 62 用例
"$LLM_PY" -m ruff check app           # 代码检查
"$LLM_PY" scripts/acceptance.py       # 11 项端到端验收 → docs/acceptance-report.md
"$LLM_PY" scripts/capacity.py         # 容量压测 → docs/capacity-report.md
"$LLM_PY" scripts/bench.py            # 组件基准 → docs/perf-report.md
"$LLM_PY" scripts/bench_llm.py        # 真实模型延迟 → docs/llm-perf-report.md
"$LLM_PY" scripts/llm_e2e.py          # 真实模型端到端 → docs/llm-e2e-report.md
"$LLM_PY" scripts/check_secrets.py    # 密钥扫描
```

- [架构与实现](docs/architecture.md)
- [运维手册](docs/operations.md)
- [框架集成说明](docs/integration.md)
- [单机容量与配置建议](docs/capacity-sizing.md)

## 密钥安全

- 密钥只放 `.env`（gitignore）；仓库仅保留占位模板 `.env.example`。
- 三层防护：`.gitignore` 忽略规则、`scripts/check_secrets.py` 扫描、`.githooks/pre-commit` 提交前拦截、
  CI 步骤拦截；`tests/test_no_secrets.py` 断言已跟踪文件中无密钥。
