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


def _with_capabilities(base_factory: Callable[[], Any], experience: Any,
                       situation_store: Any = None) -> Callable[[], Any]:
    """用框架 Capability 把应用能力装配到新建 Agent 上。"""

    def _factory() -> Any:
        agent = base_factory()
        try:
            from app.core.capabilities import install_app_capabilities

            install_app_capabilities(agent, experience=experience,
                                     situation_store=situation_store)
        except Exception:  # noqa: BLE001
            pass
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
    experience: Any = None,
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
    recall_fn = (lambda q: experience.recall_block(q, top_k=3)) if experience is not None else None
    agent_factory = _reuse_factory(_with_capabilities(base_factory, experience, store))
    graph = build_deck_graph(agent_factory, store, recall_fn=recall_fn)

    _t0 = time.monotonic()
    processed: List[str] = []

    async def _run_event(event) -> None:
        entry = "approve" if event.kind == "approval_result" else None
        errors: List[str] = []
        _t = time.monotonic()
        res = await scheduler.execute(
            graph,
            event_message(event),
            thread_id=thread_id,
            entry_node=entry,
            on_node_error=lambda e: errors.append(str(e.error)),
        )
        from app.core.tracing import observe

        observe("deck_event_latency_seconds", time.monotonic() - _t,
                {"kind": event.kind})
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
        _save_case(experience, event, store)

    pending = bus.pending()
    if max_concurrency > 1 and len(pending) > 1:
        sem = asyncio.Semaphore(max_concurrency)

        async def _bounded(ev):
            async with sem:
                # 并发下不复用 Agent/Scheduler 内部可变状态：各自独立图
                local_graph = build_deck_graph(
                    _reuse_factory(_with_capabilities(base_factory, experience, store)),
                    store, recall_fn=recall_fn)
                local_sched = GraphScheduler(store=state_store, max_iterations=8)
                entry = "approve" if ev.kind == "approval_result" else None
                _t = time.monotonic()
                res = await local_sched.execute(
                    local_graph, event_message(ev), thread_id=thread_id,
                    entry_node=entry,
                )
                from app.core.tracing import observe

                observe("deck_event_latency_seconds", time.monotonic() - _t,
                        {"kind": ev.kind})
                if replay_store is not None:
                    replay_store.append_run(
                        thread_id, ev.ev_id,
                        [e.to_dict() for e in res.events], status=res.status,
                    )
                bus.mark_processed(ev.ev_id)
                processed.append(ev.ev_id)
                _save_case(experience, ev, store)

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


def _save_case(experience: Any, event: Any, store: Any) -> None:
    """事件处置成功后，把"事件+研判结论"沉淀为战例（供后续召回）。"""
    if experience is None or getattr(event, "kind", "") == "approval_result":
        return
    try:
        from app.domain.experience import advice_from_order

        payload = getattr(event, "payload", {}) or {}
        order_id = payload.get("order_id")
        order = store.get("order", order_id) if order_id else None
        advice = advice_from_order(order)
        if not advice:
            return
        summary = str(payload.get("text") or payload)
        experience.remember_case(event.kind, summary, advice, tags=[event.kind])
    except Exception:  # noqa: BLE001
        pass


__all__ = ["default_intel_factory", "process_pending"]

