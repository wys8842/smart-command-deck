# -*- coding: utf-8 -*-
"""性能相关回归：JSONL 持久化、/metrics 端点、Agent 实例复用。"""
import asyncio

from fastapi.testclient import TestClient

from agentorchestra.agents.simple_agent import SimpleAgent

from app.api.server import create_app
from app.core.mock_llm import MockLLM
from app.domain.persist import close_engine, open_persistent_engine
from app.engine.event_bus import EventBus, new_event
from app.engine.service import process_pending


def _seed(store):
    store.insert("unit", {"unit_id": "u1", "name": "甲", "side": "friendly",
                          "location": "A1", "status": "idle", "strength": 80})
    store.insert("target", {"target_id": "t1", "name": "雷达", "kind": "radar",
                            "side": "enemy", "threat": 0.8, "location": "B2"})


def test_event_bus_jsonl_append_only(tmp_path):
    p = tmp_path / "events.json"
    bus = EventBus(path=str(p))
    e = new_event("intel_report", "radar", {"x": 1})
    bus.enqueue(e)
    bus.mark_processed(e.ev_id)

    # 文件是逐行 JSONL（不是整文件重写）
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert '"_t": "e"' in lines[0]
    assert '"_t": "p"' in lines[1]

    # 重开仍能读到状态
    bus2 = EventBus(path=str(p))
    assert bus2.is_processed(e.ev_id)
    assert bus2.pending() == []


def test_metrics_endpoint_and_counter(tmp_path):
    engine = open_persistent_engine(str(tmp_path / "games.db"))
    _seed(engine.object_store)
    bus = EventBus(path=str(tmp_path / "events.json"))
    client = TestClient(create_app(engine=engine, bus=bus))

    bus.enqueue(new_event("intel_report", "radar",
                          {"order_id": "o1", "kind": "strike", "unit_id": "u1",
                           "target_id": "t1", "threat": 0.9}))
    client.post("/games/g1/pump")

    text = client.get("/metrics").text
    assert "deck_events_processed_total" in text
    assert "deck_pump_cycle_seconds" in text
    close_engine(engine)


def test_agent_reused_across_events(tmp_path):
    engine = open_persistent_engine(str(tmp_path / "games.db"))
    _seed(engine.object_store)
    bus = EventBus(path=str(tmp_path / "events.json"))

    creations = {"n": 0}

    def factory():
        creations["n"] += 1
        return SimpleAgent(name="intel", llm=MockLLM())

    for i in (1, 2, 3):
        bus.enqueue(new_event("intel_report", "radar",
                              {"order_id": f"o{i}", "kind": "strike", "unit_id": "u1",
                               "target_id": "t1", "threat": 0.9}))
    asyncio.run(process_pending(engine, bus, intel_agent_factory=factory))

    assert creations["n"] == 1, "应复用同一个 Agent 实例"
    assert engine.object_store.count("order") == 3
    close_engine(engine)
