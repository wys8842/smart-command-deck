# 智能推演指挥台 · 详细技术路线（M0 → M5）

> 版本 v0.1（草案）· 单机部署 · 非并行 · 以 agentorchestra v0.2.0 为第三方库
> 本文是实施主线：读完即可照做。每阶段都有「目标 / 具体任务 / 验收」，按顺序推进，不并行。

---

## 1. 目标与硬约束

- **做**：一套回合制、多角色多智能体的“态势研判—方案建议—人工批准—执行—结算—复盘”推演闭环。
- **不做（范围外，明确外挂，不进入本路线）**：
  - 毫秒级实时链路（不接传感器/硬实时）
  - GIS / 时空索引引擎
  - 海量非结构化文档 RAG（仅保留记忆型召回与少量知识 Tool）
  - 分布式 / 多机扩容
  - 与真实指挥系统的 IAM/加密对接（安全加固是后续专项）
- **技术约束**：
  - Python ≥ 3.10，单机、单进程（内部用 asyncio 协作，不引入多进程并行）。
  - 存储默认 SQLite；`agentorchestra` 的 `state`/`tx` 经由 `CheckpointStore` 抽象落库。
  - 模型调用可离线 Mock（开发/测试），生产接统一 LLM 网关。

---

## 2. 总体架构

```
┌────────────────────────── 单机进程（supervisor = app/main.py） ──────────────────────────┐
│                                                                                          │
│  [接入层 api]   事件API(注入事件)   批准API(HITL)   查询API   复盘导出API                   │
│        │             │                │            │            │                        │
│  [装配层 core]   Config · Components(state_store/tracer/metrics) · Capability 装配          │
│        │                                                                                  │
│  [推演引擎 engine]                                                                        │
│     回合时钟(回合/事件泵)──► Inbox 事件 ──► GraphScheduler ──► Graph(研判/路由/建议/批准/执行) │
│        │                                        │ 节点内 = Agent(参谋/研判…)                 │
│        ▼                                        ▼                                         │
│  [领域层 domain]   ontology：Unit/Formation/Target/Event/Order/Stock + ActionType           │
│                    （engine.mount 生成工具挂给各 Agent）                                     │
│        │                                                                                  │
│  [底座]  agentorchestra 作为第三方库                                                        │
│     orchestration/state(CheckpointStore→SQLite) · governance/tx(平账) · govern(权限/审计)   │
│     observability(TraceLogger/Prometheus) · capability/memory(经验记忆)                    │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

**非并行含义**：一个事件循环驱动“多个局（thread_id）”的任务；同一局内严格串行推进回合。
不同局之间只是 asyncio 上的多个 task 交错，不引入进程/线程并行。

### 技术选型（应用侧自选，最小集）
| 层 | 选型 |
|---|---|
| 语言/运行时 | Python 3.11+、asyncio |
| Web/API | FastAPI（仅事件/批准/查询/导出，轻量） |
| DB | SQLite（每局一个库文件或单库多 thread，二选一，建议单库多 thread 便于统计） |
| 前端/复盘 | 先用 TraceLogger 导出的 HTML + 自定义 JSON 导出；不做重型前端 |
| 模型 | 统一 `SymphonyLLM`；测试用框架内 MockLLM 思路离线跑 |
| 消息 | 外部事件先进应用自建的“事件注入适配器”，转成框架 `Inbox` 消息 |

---

## 3. 以“第三方库”接入框架的约定

### 3.1 依赖安装
```bash
# 同一级目录的框架仓库（开发期）
pip install -e ../agentorchestra
# 或按 tag 安装
pip install "agentorchestra @ git+https://github.com/wys8842/agentorchestra-v0.2.0.git"
```

### 3.2 使用纪律（重要，避免把业务绑死到框架内部）
1. **只通过公共入口编程**：`agentorchestra.components` 门面、各模块 `__init__` 的公共导出、经典或规范导入均可（二选一并在仓库内统一，推荐规范路径）。
2. **业务不 new 全局组件**：store/tracer/metrics 一律 `Components.xxx()` 或注入。
3. **模型/存储可替换**：所有持久化只依赖 `CheckpointStore` 抽象；上线前可把 SQLite 换成 PostgreSQL 而不改业务。
4. **框架升版本隔离**：在 `app/core/adapters/` 留薄适配层（时钟桥、事件转换、审批门），升级框架时只改适配层。

### 3.3 应用内模块职责
```
app/core/   装配与依赖注入（Config 构建、Components 注册、Capability 装配）
app/domain/ ontology 模型注册、ActionType 与 rules、账目动作封装
app/engine/ 回合时钟、事件泵、Graph 蓝图构造器、HITL 状态机、复盘记录器
app/api/    FastAPI 路由：/events /approvals /games/{id}/state /replay
```

---

## 4. 领域模型草案（app/domain，基于 ontology）

> 建议先只做 4 个对象类型 + 6 个动作，跑通后再扩展。

| 对象类型 | 主键 | 关键属性 |
|---|---|---|
| `unit`（单位/编队） | `unit_id` | `name` `side` `location`(文本/简化坐标) `status` `strength` |
| `target`（目标） | `target_id` | `name` `kind` `side` `threat`(0-1) `location` |
| `order`（命令） | `order_id` | `type` `target_id` `params` `approval`(pending/approved/rejected/executed) |
| `stock`（弹药/油料账目） | `stock_id` | `kind` `qty` |

| 动作 | 说明 | 校验/副作用 |
|---|---|---|
| `scout(unit, area)` | 侦察，更新态势/产生情报事件 | rules：单位在战场、可侦察 |
| `issue_order(...)` | 生成命令对象（先 pending，不直接执行） | rules：权限足够；审计 |
| `approve(order)` | 指挥员批准 → 交执行 | 仅指定角色；审计 |
| `execute_order(order)` | 真正执行（改 strength/目标 status） | 事务：扣 stock |
| `resupply(unit, kind, qty)` | 补给 | 事务：stock 增减平账 |
| `settle_round(round)` | 回合结算（战果/损耗汇总） | 生成结算对象供复盘 |

实现形态：

```python
from agentorchestra.ontology import ObjectType, ActionType, OntologyEngine, SecurityContext

Unit   = ObjectType("unit",   "unit_id",   properties=[...])
Target = ObjectType("target", "target_id", properties=[...])
...

def do_execute_order(params, ctx):
    # 校验 order.approval == "approved"；扣弹药账目（事务）
    ...

engine = OntologyEngine(object_store=..., security_ctx=SecurityContext(...))
engine.register_object_type(Unit).register_object_type(Target) ...
engine.register_action(ActionType("execute_order", parameters=..., rules=[...], execute_fn=do_execute_order))
engine.mount(registry)          # 工具挂给 Agent
```

---

## 5. 推演运行时核心设计（app/engine）

### 5.1 回合时钟与事件泵
用框架 `ontology/process.scheduler.Scheduler` 或自行 asyncio 循环，**二选一**：
- 起步推荐自行 `asyncio.create_task(round_loop(game_id))`，更贴近“回合时钟可快进/暂停”；
- 或直接用框架 `Scheduler.add_interval(...)` 驱动“每回合结算”等定时动作。

回合循环伪代码：

```python
async def round_loop(game_id: str, dt: float):
    round_no = 0
    while not stopped[game_id]:
        round_no += 1
        # 1) 推动本回合：结算、按计划触发事件
        await settle_round(game_id, round_no)
        # 2) 把本回合产生的"事件"投进 Inbox，由 Graph 处理
        for ev in new_events:
            await inbox.send(graph_id, thread_id=game_id, to_node="entry",
                             content=to_message(ev), from_node=None)
        # 3) 交给 GraphScheduler 消费（见 5.2）
        await consume_once(game_id)
        await asyncio.sleep(dt)
```

> 事件契约（应用层定义，给 Agent 解析）：
> `{"kind": "intel_report"|"alert"|"approval_result"|"order_result", "ts": iso, "source": "...", "payload": {...}}`

### 5.2 Graph 蓝图（研判 → 分流 → 建议 → 批准 → 执行）

每局一张图（可复用模板），用框架类构造：

```python
from agentorchestra.orchestration.orch.graph import Graph
from agentorchestra.orchestration.orch.nodes import (
    AgentNode, RouterNode, MergeNode, FunctionalNode,
)
from agentorchestra.orchestration.orch.scheduler import GraphScheduler

def build_deck_graph(ctx):                      # ctx 提供各 Agent 工厂
    g = Graph()
    g.add_node("entry",    FunctionalNode(passthrough))            # 事件入口
    g.add_node("intel",    AgentNode(ctx.intel_agent_factory))     # 情报研判
    g.add_node("route",    RouterNode(route_by_threat))            # 分级
    g.add_node("record",   AgentNode(ctx.record_agent_factory))    # 低危：记录归档
    g.add_node("advise",   AgentNode(ctx.advise_agent_factory))    # 高危：出建议/命令
    g.add_node("approve",  FunctionalNode(request_approval))       # HITL：挂起等待批准
    g.add_node("execute",  AgentNode(ctx.execute_agent_factory))   # 批准后执行
    g.add_node("settle",   FunctionalNode(mark_settled))           # 结算落账
    g.add_edge("entry", "intel")
    g.add_edge("intel", "route")
    g.add_edge("route", "record",   when="low")
    g.add_edge("route", "advise",   when="high")
    g.add_edge("advise", "approve")
    g.add_edge("approve", "execute", when="approved")   # 由批准事件续跑触发
    g.add_edge("approve", "settle",  when="rejected")
    g.add_edge("execute", "settle")
    return g
```

### 5.3 HITL（人工批准）如何落地（关键设计）
- “批准”不是普通 Agent 行为，而是**挂起 + 续跑**：
  1. `approve` 节点（FunctionalNode）把命令落成 ontology `order`（status=pending）并返回 `route=None` 结束当前分支；
  2. 系统把 `pending_approval` 也记入自有“审批待办表”（可按 order 对象实现）；
  3. 指挥员在 API `/approvals` 批准/驳回；
  4. 批准动作：更新 order → 以 `{"kind":"approval_result", payload: order}` 事件重新投递到该局图，从 `approve` 下游续跑（`when="approved"/"rejected"`）。
- 好处：推演进程不阻塞；批准动作天然可审计、可恢复；断点续跑与 state 一致。

### 5.4 每局持久化 / 续跑
- 每局固定一个 `thread_id = f"game-{game_id}"`；
- `GraphScheduler(store=store, max_iterations=...)`，`store` 来自 `Components.state_store()`（SQLite）；
- 崩溃恢复：应用启动时按局重建 Graph 模板并继续投递未处理事件（幂等由事件 `ev_id` 去重）。

---

## 6. 一致性与治理

### 6.1 账目平账（gov/tx + ontology 事务）
- `execute_order`/`resupply` 的库存/弹药增减包进事务：注册可补偿动作（扣→加回），失败自动补偿；
- 使用 `TransactionManager.set_coordinator(coordinator)` 获得幂等 + WAL + DLQ，重放不双扣；
- coordinator 的 store 与 Graph 共用同一 `CheckpointStore`（保持单库一致性）。

### 6.2 权限与审计（govern）
- 角色：`commander / staff / operator / viewer`；
- 动作前 `PermissionChecker`：只 `commander/staff` 能 `approve/issue_order`；
- 每个动作（侦察/命令/批准/执行/补给/结算）经 ontology 审计写 `AuditEntry`，复盘与合规可查。

### 6.3 记忆（可选，M5）
- `memory_enabled/auto_recall/auto_summarize`：沉淀“处置成功的案例”；同类事件到达时可召回供参谋参考；
- 文档/条令知识 → 后续用自建 `search_regulations` Tool 外挂，不在本路线主线。

---

## 7. 复盘与可观测

- 每局产出：
  - `GraphResult.events`（NodeEvent 序列：start/finish/error/skipped）
  - 态势快照（回合结算对象 / 物化）
  - `TraceLogger`（JSONL+HTML）用于参谋日志
- 复盘导出：`/games/{id}/replay` → 返回 timeline JSON（事件 + 各节点输入输出 + 审批节点），可按回合回放讲评。
- 指标：`Components.metrics_collector()` 记录回合耗时、审批平均时长、动作失败率；Prometheus 文本导出。

---

## 8. 单机部署设计

- 单一 supervisor：`app/main.py` 启动 asyncio 事件循环，注册 FastAPI、启动若干局 task。
- 进程内无多进程并行；如需水平扩展（未来）再把“事件泵 + store”换成共享队列，但**当前不实现**。
- 存储文件布局：
  ```
  data/
    games.db            # 全局：units/targets/orders/stock/审计/thread 快照
    traces/             # TraceLogger 输出（每局 JSONL/HTML）
    replay/             # 复盘 JSON
  ```
- 运行：`python -m app.main`；`systemd`/计划任务启动均可。
- 备份：SQLite 在线备份 + 复盘导出归档；升级前全量备份。

---

## 9. 分阶段实施路线（严格串行）

### M0 · 工程骨架与框架接入
- 目标：应用目录可运行，能 import 框架、能读写默认 store、能跑一个离线“最小 Agent”。
- 任务：
  1. `pyproject.toml` 依赖（见 §3.1）+ 目录结构；
  2. `app/core/config.py`：构建框架 `Config`（feature 开关：trace/checkpoint/ontology/memory 先关或部分开）；
  3. `app/core/components.py`：注册 `state_store`（SQLite），`enable_prometheus()`；
  4. 写一个离线冒烟：`SimpleAgent(llm=MockLLM, registry)` 调用一个自定义 Tool。
- 验收：`python -m app.main --smoke` 通过；`pytest tests/` 空跑绿；一次事件能落 store。

### M1 · 领域建模（ontology）
- 目标：4 对象 + 6 动作注册成功，Agent 能“查态势 + 下命令”。
- 任务：实现 §4 schema/动作/rules；`engine.mount(registry)`；为“参谋 Agent”挂 registry。
- 验收：
  - 单测断言工具存在（`QueryUnit/QueryTarget/scout/issue_order/...`）；
  - 一个剧本测试：Agent 用 MockLLM 完成“侦察→生成待批准命令”并落 ontology。

### M2 · 回合时钟 + 事件泵 + 最小研判图
- 目标：外部事件注入 → Inbox → 单 Agent 研判 → 记录，闭环能跑。
- 任务：事件契约、事件注入适配器、round_loop、最小 Graph（entry→intel→record）。
- 验收：脚本注入 3 条不同类型事件，均产出研判记录；重启后未处理事件可重放不重复。

### M3 · 完整 DAG 与人工批准（HITL）
- 目标：§5.2/5.3 的分级路由 + 审批续跑跑通。
- 任务：route 分级、approve 挂起、`/approvals` API、approval_result 续跑；order 全生命周期状态。
- 验收：
  - 高危事件 → 生成命令 pending；批准 → execute→settle；驳回 → settle(rejected)；
  - 审批动作在审计中可查；同一事件重放不双执行（幂等）。

### M4 · 账目一致 + 权限 + 审计加固
- 目标：动作事务化、角色权限、全动作审计。
- 任务：execute_order/resupply 上 tx（补偿/幂等/DLQ）；PermissionChecker 接入；审计写 AuditEntry。
- 验收：
  - 人为让补给失败 → 库存/弹药自动回滚（补偿）→ 测试断言库存回到原值；
  - 越权 approve 被拒并记录；审计可导出。

### M5 · 复盘、观测与运行加固
- 目标：可回放、可监控、可备份，交付操作手册。
- 任务：replay 导出 API；TraceLogger/指标接上；单机 N 局并发的稳定性冒烟（如 20 局同时跑 30 回合）；备份脚本与操作手册。
- 验收：完整剧本“注入 10 条事件→产出 3 条命令→批准 2 驳回 1→结算→导出 timeline 回放”一键通过；文档就绪。

---

## 10. 风险与检查清单

| 风险 | 缓解 |
|---|---|
| LLM 输出不稳定导致推演漂移 | 关键决策用 rules/确定性动作兜底，LLM 只做研判与建议；固定 seed/示例注入 |
| 回合循环里 Agent 调用阻塞 | 统一 async（`agent.arun`）；必要时 executor 包裹同步 run |
| 审批挂起后忘续跑 | 每局维护 pending 清单；启动时扫描未决 order 提醒 |
| 事件重放导致双执行 | 每事件 `ev_id` 幂等；tx 幂等键兜底 |
| 单库锁竞争 | SQLite WAL 模式；同局内串行，跨局异步交错即可 |
| 框架升级破坏 API | app/core/adapters 隔离；升级只动适配层 |
| 安全合规 | 本路线不含真实 IAM/加密；上线前专项评估（明确范围外） |

**上线前检查清单**：全剧本一键通过 · 审计可查 · 备份可用 · 观察指标在 · 无外部实时依赖 · 已知降级路径（模型不可用时回退规则）说明。

---

## 11. 后续演进（当前明确不做）

- 事件泵换真消息队列、多机并行（仅当数据/负载需要）
- GIS/时空可视化
- 文档级 RAG 服务
- 真实指挥系统的 IAM/密码体系对接

以上演进都不改变 M0–M5 已交付的核心，只增加适配层或新组件。
