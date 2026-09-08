"""事件泵（M2）：从 EventBus 取未处理事件 → GraphScheduler 跑研判图 → 落库/去重。"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agentorchestra.orchestration.orch.scheduler import GraphScheduler

from app.engine.event_bus import Event, EventBus
from app.engine.graphs import build_intel_graph


def event_message(event: Event) -> dict:
    """把事件转成 Graph 初始消息。"""
    return {"event": {
        "ev_id": event.ev_id,
        "kind": event.kind,
        "source": event.source,
        "ts": event.ts,
        "round": event.round,
        "payload": event.payload,
    }}


async def process_one(
    graph: Any,
    event: Event,
    thread_id: str = "default",
    max_iterations: int = 5,
) -> str:
    """处理单条事件，返回图执行状态。"""
    scheduler = GraphScheduler(store=None, max_iterations=max_iterations)
    res = await scheduler.execute(
        graph=graph,
        initial_message=event_message(event),
        thread_id=thread_id,
        on_node_error=lambda ev: print("[graph] error:", ev.error),
    )
    return res.status


async def run_pending(
    bus: EventBus,
    intel_agent_factory: Callable[[], Any],
    store: Any,
    thread_id: str = "default",
    on_event: Callable[[Event, str], None] | None = None,
) -> list[str]:
    """消费 EventBus 全部未处理事件：幂等（不重复处理已 processed）。"""
    graph = build_intel_graph(intel_agent_factory, store)
    done: list[str] = []
    for event in bus.pending():
        if bus.is_processed(event.ev_id):
            continue
        status = await process_one(graph, event, thread_id=thread_id)
        bus.mark_processed(event.ev_id)
        done.append(event.ev_id)
        if on_event:
            on_event(event, status)
    return done


async def run_pending_async_wrapper(
    bus: EventBus,
    intel_agent_factory: Callable[[], Any],
    store: Any,
    thread_id: str = "default",
) -> list[str]:
    return await run_pending(bus, intel_agent_factory, store, thread_id)


__all__ = ["event_message", "process_one", "run_pending"]
