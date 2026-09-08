# -*- coding: utf-8 -*-
"""③ FastAPI API 层验收：事件 → 待批 → 批准 → 复盘。"""
import asyncio

from fastapi.testclient import TestClient

from agentorchestra.agents.simple_agent import SimpleAgent

from app.api.server import create_app
from app.core.mock_llm import MockLLM
from app.domain.persist import close_engine, open_persistent_engine
from app.engine.deck import build_deck_graph
from app.engine.event_bus import EventBus, new_event
from app.engine.hitl import approval_event
from app.engine.pump import event_message


def _factory():
    return SimpleAgent(name="intel", llm=MockLLM())


def _seed(store):
    store.insert("unit", {"unit_id": "u1", "name": "甲编队", "side": "friendly",
                          "location": "A1", "status": "idle", "strength": 80})
    store.insert("target", {"target_id": "t1", "name": "敌方雷达站", "kind": "radar",
                            "side": "enemy", "threat": 0.8, "location": "B2"})


async def _run_event(engine, event, entry=None):
    from agentorchestra.orchestration.orch.scheduler import GraphScheduler

    graph = build_deck_graph(_factory, engine.object_store)
    sched = GraphScheduler(store=None, max_iterations=8)
    await sched.execute(graph, event_message(event), thread_id="api-1",
                        entry_node=entry)


def test_api_flow(tmp_path):
    db = str(tmp_path / "games.db")
    engine = open_persistent_engine(db)
    _seed(engine.object_store)
    bus = EventBus(path=str(tmp_path / "events.json"))
    client = TestClient(create_app(engine=engine, bus=bus))

    # 事件入队
    r = client.post("/events", json={"kind": "intel_report", "source": "radar",
                                     "payload": {"order_id": "o1", "kind": "strike",
                                                 "unit_id": "u1", "target_id": "t1",
                                                 "threat": 0.9}})
    assert r.status_code == 202
    assert bus.pending()

    # 泵处理高危事件 → 出现待批命令
    asyncio.run(_run_event(engine, new_event(
        "intel_report", "radar", {"kind": "strike", "order_id": "o1",
                                  "unit_id": "u1", "target_id": "t1", "threat": 0.9})))
    pending = client.get("/approvals").json()["pending"]
    assert any(o["order_id"] == "o1" for o in pending)

    # 批准 → 续跑执行
    resp = client.post("/approvals/o1", json={"approve": True})
    assert resp.status_code == 200
    asyncio.run(_run_event(engine, approval_event("o1", True), entry="approve"))
    assert engine.object_store.get("order", "o1")["status"] == "executed"

    # 复盘
    replay = client.get("/games/g1/replay").json()
    assert replay["summary"]["orders"] == 1

    close_engine(engine)
