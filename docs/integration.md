# 框架集成说明（agentorchestra）

本项目对 `agentorchestra` 的使用点，按框架能力逐项对应到代码位置。

## 1. 能力映射

| 框架能力 | 框架 API | 本项目使用位置 | 用途 |
|---|---|---|---|
| Ontology 语义 | `ObjectType` / `LinkType` / `ActionType` | `app/domain/schema.py` | 单位/目标/命令/账目/记录建模与动作 |
| Ontology 引擎 | `OntologyEngine` / `engine.mount` | `app/domain/schema.py::create_engine` | 注册对象/动作，生成工具挂载到 Agent |
| Ontology 存储 | `ObjectStore` / `GraphStore` / `SQLiteBackend` | `app/domain/persist.py` | 对象持久化；关系图 |
| Ontology 关系 | `store.create_link` / `get_links` | `app/domain/relations.py` | 战场关系与邻域态势 |
| Ontology 工作流 | `Workflow` / `StepNode` / `WorkflowEngine` | `app/domain/workflows.py` | `strike_sequence`、`resupply_sequence` |
| 事务（Saga） | `TransactionManager` | `app/domain/ledger.py` | 账务补偿（纯内存） |
| 事务运行时 | `TransactionCoordinator` / `TxReplay` | `app/domain/coord_ledger.py` | 幂等重放、补偿回滚、DLQ |
| 图编排 | `Graph` / `GraphScheduler` / `Node` / `NodeOutput` | `app/engine/deck.py`、`app/engine/graphs.py` | 研判→分级→建议→批准→执行→结算 |
| 图节点 | `FunctionalNode` / `RouterNode`（条件边） | `app/engine/deck.py` | 路由与函数节点；`route` 驱动 `when` |
| 状态持久化 | `CheckpointStore` / `get_default_store` | `app/domain/state_store.py` | 图 Inbox/iteration、Interrupt |
| HITL | `Interrupt` / `InterruptResumer` | `app/engine/interrupts.py` | 人工批准与续跑 |
| 治理 RBAC/审计 | `SecurityManager` / `AuditManager` / `PermissionChecker` | `app/domain/schema.py`（engine 内置） | 动作权限校验与审计留痕 |
| 多租户/配额 | `TenantManager` / `QuotaManager` / `UsageRecorder` | `app/core/tenancy.py` | 租户上下文、token 配额、用量 |
| 跨会话记忆 | `MemoryManager` / `MemoryType` / `KeywordIndex` | `app/domain/experience.py` | 战例召回（关键词检索 + 缓存） |
| 能力注册 | `Capability` / `CapabilityRegistry` / `CapabilityContext` | `app/core/capabilities.py` | 战例/态势/遥测能力装配 |
| LLM 客户端 | `SymphonyLLM` | `app/core/llm_factory.py` | 真实模型（超时/重试） |
| 观测原语 | `Components.enable_prometheus` / `metrics_collector` | `app/core/observability.py`、`app/api/server.py` | 指标收集与 `/metrics` |
| 轨迹 | `TraceLogger` | `app/core/tracing.py` | 每局 JSONL+HTML |
| OTLP | `Components.enable_otel_trace` | `app/core/tracing.py` | 可选 trace 导出 |
| 装配门面 | `Components` | `app/api/server.py`、`app/core/observability.py` | 全局组件读取/替换 |
| 兼容垫片 | `asyncio.timeout`（3.11+） | `app/core/compat.py` | Python 3.10 兼容 |

## 2. 典型代码路径

### 2.1 Ontology 建模与工具挂载（`app/domain/schema.py`）

```python
engine = OntologyEngine(object_store=store, security_ctx=sec)
for t in (Unit, Target, Order, Stock, Record):
    engine.register_object_type(t)
for action in build_actions().values():
    engine.register_action(action)
build_workflows(engine)
register_workflow_action(engine)
engine.allow(roles or [principal], resource="*", action="*")
names = engine.mount(registry)   # QueryUnit / scout / issue_order / run_workflow ...
```

### 2.2 图编排（`app/engine/deck.py`）

```python
g = Graph()
g.add_node("entry", FunctionalNode(passthrough_entry))
g.add_node("route", FunctionalNode(route_fn(store)))
g.add_node("intel", IntelAgentNode(factory, input_key="task", recall_fn=recall_fn))
g.add_node("create", FunctionalNode(order_creator(store)))
g.add_node("approve", FunctionalNode(approval_gate(store)))
g.add_node("execute", FunctionalNode(executor(store)))
g.add_node("settle", FunctionalNode(settler(store)))
g.add_edge("entry", "route")
g.add_edge("route", "record", when="low")
g.add_edge("route", "intel", when="high")
g.add_edge("intel", "create")
g.add_edge("create", "approve")
g.add_edge("approve", "execute", when="approved")
g.add_edge("approve", "settle", when="rejected")
```

### 2.3 HITL（`app/engine/interrupts.py`）

```python
intr = Interrupt(token=f"appr-{uuid4().hex[:12]}", thread_id=thread_id,
                 checkpoint_id="", reason=REASON_APPROVAL,
                 payload={"order_id": order_id})
await state_store.create_interrupt(intr)          # 生成待批中断
await state_store.resolve_interrupt(token, {"approve": decision})  # 人工决策
resumer.register_handler(REASON_APPROVAL, approval_resume_handler(store, bus))
await resumer.poll_once()                         # RESUMED → 落审批 + 入队续跑
```

### 2.4 多租户与配额（`app/core/tenancy.py` + `app/engine/service.py`）

```python
tenancy.ensure(tenant)
tenancy.charge(tenant, tokens)                    # 超限抛 QuotaExceeded → 事件 denied
async with tenancy.scope(tenant):                 # TenantManager.run_as
    await scheduler.execute(graph, ...)
tenancy.record_usage(tenant, "intel", tokens, latency_ms=...)
```

### 2.5 战例召回（`app/domain/experience.py`）

```python
cfg = build_config(memory_backend="memory", memory_embedding_enabled=False,
                   memory_namespace=namespace)
manager = MemoryManager.from_config(cfg, default_namespace=namespace)
manager.remember(content, type=MemoryType.EPISODE, tags=[...], importance=0.7,
                 namespace=namespace)
entries = manager.recall(query, top_k=3, namespace=namespace)   # 关键词检索
# 召回结果 LRU+TTL 缓存；写入同时 append 到 data/experience.jsonl
```

### 2.6 可观测（`app/core/tracing.py` + `app/engine/service.py`）

```python
cfg = build_trace_config(trace_dir)               # 开启 TraceLogger
Components.enable_prometheus()                    # /metrics 渲染
observe("deck_event_latency_seconds", dt, {"kind": event.kind})
observe("deck_approval_wait_seconds", wait, {"decision": "approve"})
```

## 3. 使用约定

1. **只通过框架公共 API 编程**：`agentorchestra.components`、各模块 `__init__` 导出、`OntologyEngine`、
   `Graph/GraphScheduler`、`CheckpointStore`、`Capability*`、`governance.tenancy` 等。
2. **业务不持有全局组件**：store/tracer/metrics 经 `Components` 获取或在 `create_app` 注入。
3. **持久化只依赖抽象**：`CheckpointStore` 可在 SQLite/内存间切换；对象存储经 `ObjectStore`。
4. **框架升级隔离**：`app/core/` 承担全部框架装配；领域/引擎层只依赖 `app.domain` 与 `app.core` 暴露的接口。
5. **Python 3.10 兼容**：`app/core/compat.py` 为框架用到的 `asyncio.timeout` 提供垫片。
