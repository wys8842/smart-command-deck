# -*- coding: utf-8 -*-
"""服务层：把 EventBus 待处理事件交给 deck 推演图处理（供 API pump 端点调用）。"""
from __future__ import annotations

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


async def process_pending(
    engine: Any,
    bus: EventBus,
    intel_agent_factory: Callable[[], Any] | None = None,
    thread_id: str = "default",
    replay_store: Any = None,
) -> Dict[str, Any]:
    """消费 EventBus 中全部未处理事件并跑 deck 图。

    - 新事件（intel_report/alert…）：从入口执行整条 DAG；
    - 续跑事件（approval_result…）：从 approve 节点入口继续。
    - replay_store 非空时，记录每次执行的节点时序。
    """
    factory = intel_agent_factory or default_intel_factory
    store = engine.object_store
    graph = build_deck_graph(factory, store)

    processed: List[str] = []
    for event in bus.pending():
        entry = "approve" if event.kind == "approval_result" else None
        scheduler = GraphScheduler(store=None, max_iterations=8)
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

    return {
        "processed": processed,
        "processed_count": len(processed),
        "pending_left": len(bus.pending()),
    }


__all__ = ["default_intel_factory", "process_pending"]
