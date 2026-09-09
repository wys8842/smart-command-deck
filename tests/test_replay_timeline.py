# -*- coding: utf-8 -*-
"""复盘时间线 + 事件分页验收。"""
from fastapi.testclient import TestClient

from app.api.server import create_app
from app.domain.persist import close_engine, open_persistent_engine
from app.engine.event_bus import EventBus
from app.engine.replay import ReplayStore


def _seed(store):
    store.insert("unit", {"unit_id": "u1", "name": "甲编队", "side": "friendly",
                          "location": "A1", "status": "idle", "strength": 80})
    store.insert("target", {"target_id": "t1", "name": "敌方雷达站", "kind": "radar",
                            "side": "enemy", "threat": 0.8, "location": "B2"})


def test_replay_timeline_and_event_pagination(tmp_path):
    engine = open_persistent_engine(str(tmp_path / "games.db"))
    _seed(engine.object_store)
    bus = EventBus(path=str(tmp_path / "events.json"))
    replay = ReplayStore(path=str(tmp_path / "replay.json"))
    client = TestClient(create_app(engine=engine, bus=bus, replay_store=replay))

    # 入队并 pump
    client.post("/events", json={"kind": "intel_report", "source": "radar",
                                 "payload": {"order_id": "o1", "kind": "strike",
                                             "unit_id": "u1", "target_id": "t1",
                                             "threat": 0.9}})
    client.post("/games/g1/pump")

    # 复盘 timeline：包含节点时序（node_start/finish）
    data = client.get("/games/g1/replay").json()
    assert "timeline" in data
    assert data["timeline"], "应有节点时序"
    events = data["timeline"][0]["events"]
    types = {e["event_type"] for e in events}
    assert "node_start" in types and "node_finish" in types
    nodes = {e["node_name"] for e in events}
    assert {"entry", "route", "intel", "create", "approve"} <= nodes

    # 事件分页
    page1 = client.get("/events?limit=1&offset=0").json()["events"]
    page2 = client.get("/events?limit=1&offset=1").json()["events"]
    assert len(page1) == 1
    assert len(page2) == 0  # 只有 1 条事件

    close_engine(engine)
