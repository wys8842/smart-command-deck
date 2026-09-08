# -*- coding: utf-8 -*-
"""② SQLite 持久化 + 崩溃续跑验收：
- 会话1 跑剧本并留下 pending 命令 → close
- 会话2 重开同一库：数据仍在；批准剩余 pending 命令续跑 → executed 落库
"""
import asyncio

from agentorchestra.agents.simple_agent import SimpleAgent

from app.core.mock_llm import MockLLM
from app.engine.deck import build_deck_graph
from app.engine.event_bus import new_event
from app.engine.hitl import approve_order, approval_event
from app.engine.pump import event_message
from app.domain.persist import close_engine, open_persistent_engine
from app.engine.replay import export_timeline


def _factory():
    return SimpleAgent(name="intel", llm=MockLLM())


def _seed(store):
    store.insert("unit", {"unit_id": "u1", "name": "甲编队", "side": "friendly",
                          "location": "A1", "status": "idle", "strength": 80})
    store.insert("target", {"target_id": "t1", "name": "敌方雷达站", "kind": "radar",
                            "side": "enemy", "threat": 0.8, "location": "B2"})


async def _run(engine, graph, event, entry=None):
    from agentorchestra.orchestration.orch.scheduler import GraphScheduler

    sched = GraphScheduler(store=None, max_iterations=8)
    errs = []
    await sched.execute(graph, event_message(event), thread_id="g-persist",
                        entry_node=entry,
                        on_node_error=lambda e: errs.append(str(e.error)))
    assert not errs, errs


def test_persist_and_resume(tmp_path):
    db = str(tmp_path / "games.db")

    # ---- 会话 1：跑出 2 条命令，批准 1 条，留 1 条 pending 后“宕机” ----
    e1 = open_persistent_engine(db)
    _seed(e1.object_store)
    g1 = build_deck_graph(_factory, e1.object_store)
    for i in (1, 2):
        ev = new_event("intel_report", "radar",
                       {"kind": "strike", "order_id": f"o{i}",
                        "unit_id": "u1", "target_id": "t1", "threat": 0.9})
        asyncio.run(_run(e1, g1, ev))
    approve_order(e1.object_store, "o1", True)
    asyncio.run(_run(e1, g1, approval_event("o1", True), entry="approve"))
    assert e1.object_store.get("order", "o1")["status"] == "executed"
    assert e1.object_store.get("order", "o2")["approval"] == "pending"
    close_engine(e1)  # 模拟宕机/重启

    # ---- 会话 2：重开同一库续跑 ----
    e2 = open_persistent_engine(db)
    assert e2.object_store.count("order") == 2          # 数据仍在
    assert e2.object_store.count("record") >= 1

    approve_order(e2.object_store, "o2", True)
    g2 = build_deck_graph(_factory, e2.object_store)
    asyncio.run(_run(e2, g2, approval_event("o2", True), entry="approve"))
    assert e2.object_store.get("order", "o2")["status"] == "executed"
    assert export_timeline(e2.object_store)["summary"]["orders"] == 2
    close_engine(e2)
