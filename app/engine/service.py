# -*- coding: utf-8 -*-
"""服务层：把 EventBus 待处理事件交给 deck 推演图处理（供 API pump 端点调用）。"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, List

from agentorchestra.agents.simple_agent import SimpleAgent
from agentorchestra.orchestration.orch.scheduler import GraphScheduler

from app.core.mock_llm import MockLLM
from app.engine.deck import build_deck_graph
from app.engine.event_bus import EventBus
from app.engine.pump import event_message


def default_intel_factory() -> Any:
    """离线可用的研判 Agent（接入真实 LLM 时替换此工厂）。"""
    return SimpleAgent(name="intel", llm=MockLLM())


def _reuse_factory(base_factory: Callable[[], Any]) -> Callable[[], Any]:
    """把“每次新建 Agent”包装为“复用单实例 + 每次清空历史”。

    避免每个节点执行都重新构造 Agent（配置/历史/客户端），显著降低开销。
    """
    cache: dict = {}

    def _factory() -> Any:
        agent = cache.get("agent")
        if agent is None:
            agent = base_factory()
            cache["agent"] = agent
        else:
            clear = getattr(agent, "clear_history", None)
            if callable(clear):
                clear()
        return agent

    return _factory


async def process_pending(
    engine: Any,
    bus: EventBus,
    intel_agent_factory: Callable[[], Any] | None = None,
    thread_id: str = "default",
    replay_store: Any = None,
    state_store: Any = None,
    max_concurrency: int = 1,
) -> Dict[str, Any]:
    """消费 EventBus 中全部未处理事件并跑 deck 图。

    - 新事件（intel_report/alert…）：从入口执行整条 DAG；
    - 续跑事件（approval_result…）：从 approve 节点入口继续。
    - replay_store 非空时，记录每次执行的节点时序。
    - state_store 非空时，Inbox/iteration 落 CheckpointStore（崩溃续跑更稳）。
    - max_concurrency>1 时，对独立事件做有界并发（默认 1=顺序）。
    """
    base_factory = intel_agent_factory or default_intel_factory
    store = engine.object_store
    scheduler = GraphScheduler(store=state_store, max_iterations=8)
    graph = build_deck_graph(_reuse_factory(base_factory), store)

    _t0 = time.monotonic()
    processed: List[str] = []

    async def _run_event(event) -> None:
        entry = "approve" if event.kind == "approval_result" else None
        errors: List[str] = []
        res = await scheduler.execute(
            graph,
            event_message(event),
            thread_id=thread_id,
            entry_node=entry,
            on_node_error=lambda e: errors.append(str(e.error)),
        )
        if errors:
            raise RuntimeError(f"事件 {event.ev_id} 推演失败: {errors}")
        if replay_store is not None:
            replay_store.append_run(
                thread_id, event.ev_id,
                [ev.to_dict() for ev in res.events],
                status=res.status,
            )
        bus.mark_processed(event.ev_id)
        processed.append(event.ev_id)

    pending = bus.pending()
    if max_concurrency > 1 and len(pending) > 1:
        sem = asyncio.Semaphore(max_concurrency)

        async def _bounded(ev):
            async with sem:
                # 并发下不复用 Agent/Scheduler 内部可变状态：各自独立图
                local_graph = build_deck_graph(_reuse_factory(base_factory), store)
                local_sched = GraphScheduler(store=state_store, max_iterations=8)
                entry = "approve" if ev.kind == "approval_result" else None
                res = await local_sched.execute(
                    local_graph, event_message(ev), thread_id=thread_id,
                    entry_node=entry,
                )
                if replay_store is not None:
                    replay_store.append_run(
                        thread_id, ev.ev_id,
                        [e.to_dict() for e in res.events], status=res.status,
                    )
                bus.mark_processed(ev.ev_id)
                processed.append(ev.ev_id)

        await asyncio.gather(*[_bounded(ev) for ev in pending])
    else:
        for event in pending:
            await _run_event(event)

    if state_store is not None:
        try:
            from app.engine.interrupts import ensure_interrupts

            await ensure_interrupts(store, state_store, thread_id)
        except Exception:  # noqa: BLE001
            pass

    _record_metrics(len(processed), time.monotonic() - _t0)
    return {
        "processed": processed,
        "processed_count": len(processed),
        "pending_left": len(bus.pending()),
    }


def _record_metrics(count: int, elapsed: float) -> None:
    """埋点（默认 NoOp；启用 Prometheus 后可在 /metrics 查看）。"""
    try:
        from agentorchestra.observability.metrics import get_default_collector

        col = get_default_collector()
        if count:
            col.increment("deck_events_processed_total", count)
        col.observe("deck_pump_cycle_seconds", elapsed)
    except Exception:  # noqa: BLE001
        pass


__all__ = ["default_intel_factory", "process_pending"]
