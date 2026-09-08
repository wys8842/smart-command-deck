# -*- coding: utf-8 -*-
"""API pump 端点：入队 → pump 消费 → 待批命令出现。"""
from fastapi.testclient import TestClient

from app.api.server import create_app
from app.domain.persist import close_engine, open_persistent_engine
from app.engine.event_bus import EventBus


def _seed(store):
    store.insert("unit", {"unit_id": "u1", "name": "甲编队", "side": "friendly",
                          "location": "A1", "status": "idle", "strength": 80})
    store.insert("target", {"target_id": "t1", "name": "敌方雷达站", "kind": "radar",
                            "side": "enemy", "threat": 0.8, "location": "B2"})


def test_pump_consumes_queued_events(tmp_path):
    engine = open_persistent_engine(str(tmp_path / "games.db"))
    _seed(engine.object_store)
    bus = EventBus(path=str(tmp_path / "events.json"))
    client = TestClient(create_app(engine=engine, bus=bus))

    # 入队：1 条高危（应产出待批命令）+ 1 条低危（应归档）
    client.post("/events", json={"kind": "intel_report", "source": "radar",
                                 "payload": {"order_id": "o1", "kind": "strike",
                                             "unit_id": "u1", "target_id": "t1",
                                             "threat": 0.9}})
    client.post("/events", json={"kind": "intel_report", "source": "sensor",
                                 "payload": {"text": "例行巡逻无异常", "threat": 0.1}})
    assert len(bus.pending()) == 2

    # pump 消费
    r = client.post("/games/g1/pump")
    assert r.status_code == 200
    body = r.json()
    assert body["processed_count"] == 2
    assert body["pending_left"] == 0

    # 高危 → 出现待批命令；低危 → 归档不产生命令
    pending = client.get("/approvals").json()["pending"]
    assert any(o["order_id"] == "o1" for o in pending)
    assert engine.object_store.count("order") == 1

    close_engine(engine)


def test_pump_after_approval_continues(tmp_path):
    engine = open_persistent_engine(str(tmp_path / "games.db"))
    _seed(engine.object_store)
    bus = EventBus(path=str(tmp_path / "events.json"))
    client = TestClient(create_app(engine=engine, bus=bus))

    client.post("/events", json={"kind": "intel_report", "source": "radar",
                                 "payload": {"order_id": "o9", "kind": "strike",
                                             "unit_id": "u1", "target_id": "t1",
                                             "threat": 0.95}})
    client.post("/games/g1/pump")
    assert client.get("/approvals").json()["pending"]

    # 人工批准后，再入队一条 approval_result 续跑事件并 pump
    client.post("/approvals/o9", json={"approve": True})
    client.post("/events", json={"kind": "approval_result", "source": "commander",
                                 "payload": {"order_id": "o9", "decision": True}})
    client.post("/games/g1/pump")

    assert engine.object_store.get("order", "o9")["status"] == "executed"
    close_engine(engine)
