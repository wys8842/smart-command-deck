# -*- coding: utf-8 -*-
"""M3 完整 DAG + HITL 验收：
- 高危事件 → 命令 pending（停在人工批准）
- 批准续跑 → execute → settle
- 驳回续跑 → settle(rejected)
- 低危事件 → 归档，不生成命令
"""
import asyncio

from agentorchestra.agents.simple_agent import SimpleAgent
from agentorchestra.orchestration.orch.scheduler import GraphScheduler

from app.core.mock_llm import MockLLM
from app.domain.schema import create_engine
from app.engine.deck import build_deck_graph
from app.engine.event_bus import new_event
from app.engine.hitl import approve_order, approval_event
from app.engine.pump import event_message


def _factory():
    return SimpleAgent(name="intel", llm=MockLLM())


def _seed(store):
    store.insert("unit", {"unit_id": "u1", "name": "甲编队", "side": "friendly",
                          "location": "A1", "status": "idle", "strength": 80})
    store.insert("target", {"target_id": "t1", "name": "敌方雷达站", "kind": "radar",
                            "side": "enemy", "threat": 0.8, "location": "B2"})


async def _run(graph, event, entry_node=None):
    sched = GraphScheduler(store=None, max_iterations=8)
    errs = []
    res = await sched.execute(graph, event_message(event), thread_id="game-1",
                              entry_node=entry_node,
                              on_node_error=lambda e: errs.append(e.error))
    return res, errs


def test_high_event_waits_for_approval_then_executes():
    engine = create_engine()
    store = engine.object_store
    _seed(store)
    graph = build_deck_graph(_factory, store)

    ev = new_event("intel_report", "radar",
                   {"kind": "strike", "order_id": "o1", "unit_id": "u1",
                    "target_id": "t1", "threat": 0.9})
    res, errs = asyncio.run(_run(graph, ev))
    assert not errs, errs

    order = store.get("order", "o1")
    assert order is not None and order["approval"] == "pending"
    assert "advice" in order["params"]  # 研判结论已随命令保存

    # 人工批准 → 续跑
    approve_order(store, "o1", True)
    cont = approval_event("o1", True)
    res2, errs2 = asyncio.run(_run(graph, cont, entry_node="approve"))
    assert not errs2, errs2

    assert store.get("order", "o1")["status"] == "executed"
    settles = [r for r in store.list_objects("record") if r["kind"] == "settle"]
    assert any("executed" in s["summary"] for s in settles)


def test_reject_flow():
    engine = create_engine()
    store = engine.object_store
    _seed(store)
    graph = build_deck_graph(_factory, store)

    ev = new_event("intel_report", "radar",
                   {"kind": "strike", "order_id": "o2", "unit_id": "u1",
                    "target_id": "t1", "threat": 0.95})
    asyncio.run(_run(graph, ev))
    assert store.get("order", "o2")["approval"] == "pending"

    approve_order(store, "o2", False)
    cont = approval_event("o2", False)
    res, errs = asyncio.run(_run(graph, cont, entry_node="approve"))
    assert not errs, errs

    assert store.get("order", "o2")["approval"] == "rejected"
    settles = [r for r in store.list_objects("record") if r["kind"] == "settle"]
    assert any("rejected" in s["summary"] for s in settles)


def test_low_event_archived_no_order():
    engine = create_engine()
    store = engine.object_store
    _seed(store)
    graph = build_deck_graph(_factory, store)

    ev = new_event("intel_report", "sensor", {"text": "例行巡逻无异常", "threat": 0.1})
    res, errs = asyncio.run(_run(graph, ev))
    assert not errs, errs
    assert store.count("order") == 0
    assert store.count("record") >= 1
