# -*- coding: utf-8 -*-
"""① HITL 走框架 Interrupt + InterruptResumer 验收。"""
import asyncio

from agentorchestra.orchestration.state.backends.memory_backend import InMemoryCheckpointStore
from agentorchestra.orchestration.state.interrupt import InterruptResumer

from app.domain.persist import close_engine, open_persistent_engine
from app.engine.event_bus import EventBus, new_event
from app.engine.interrupts import (
    REASON_APPROVAL,
    approval_resume_handler,
    list_pending,
    resolve_approval,
)
from app.engine.service import process_pending


def _seed(store):
    store.insert("unit", {"unit_id": "u1", "name": "甲", "side": "friendly",
                          "location": "A1", "status": "idle", "strength": 80})
    store.insert("target", {"target_id": "t1", "name": "雷达", "kind": "radar",
                            "side": "enemy", "threat": 0.8, "location": "B2"})


async def _scenario(tmp_path):
    engine = open_persistent_engine(str(tmp_path / "games.db"))
    _seed(engine.object_store)
    bus = EventBus(path=str(tmp_path / "events.json"))
    state = InMemoryCheckpointStore()

    bus.enqueue(new_event("intel_report", "radar",
                          {"order_id": "o1", "kind": "strike", "unit_id": "u1",
                           "target_id": "t1", "threat": 0.9}))
    await process_pending(engine, bus, state_store=state)

    # 高危 → pending 命令 + 框架 Interrupt
    pending = await list_pending(state)
    assert pending and pending[0].reason == REASON_APPROVAL
    assert pending[0].payload["order_id"] == "o1"

    # 指挥员批准 → resolve interrupt
    token = await resolve_approval(state, "o1", True)
    assert token == pending[0].token

    # InterruptResumer 消费 RESUMED → handler 落审批 + 入队续跑
    resumer = InterruptResumer(state, poll_interval=0.1)
    resumer.register_handler(REASON_APPROVAL, approval_resume_handler(engine.object_store, bus))
    processed = await resumer.poll_once()
    assert processed == 1
    assert engine.object_store.get("order", "o1")["approval"] == "approved"

    # 常驻/手动 pump 续跑 → execute
    await process_pending(engine, bus, state_store=state)
    assert engine.object_store.get("order", "o1")["status"] == "executed"
    close_engine(engine)


def test_hitl_interrupt_resumer_flow(tmp_path):
    asyncio.run(_scenario(tmp_path))
