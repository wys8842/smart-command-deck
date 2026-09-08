# -*- coding: utf-8 -*-
"""① /events 回执 与 常驻 pump 验收。"""
import asyncio

from fastapi.testclient import TestClient

from app.api.server import create_app
from app.domain.persist import close_engine, open_persistent_engine
from app.engine.background import PumpWorker
from app.engine.event_bus import EventBus, new_event


def _seed(store):
    store.insert("unit", {"unit_id": "u1", "name": "甲编队", "side": "friendly",
                          "location": "A1", "status": "idle", "strength": 80})
    store.insert("target", {"target_id": "t1", "name": "敌方雷达站", "kind": "radar",
                            "side": "enemy", "threat": 0.8, "location": "B2"})


def test_event_receipt(tmp_path):
    engine = open_persistent_engine(str(tmp_path / "games.db"))
    _seed(engine.object_store)
    bus = EventBus(path=str(tmp_path / "events.json"))
    client = TestClient(create_app(engine=engine, bus=bus))

    r = client.post("/events", json={"kind": "intel_report", "source": "radar",
                                     "payload": {"order_id": "o1", "threat": 0.9}})
    body = r.json()
    assert body["status"] == "queued"
    assert body["seq"] >= 1

    # 入队回执
    rec = client.get(f"/events/{body['ev_id']}").json()
    assert rec["status"] == "queued"

    # pump 处理后回执变为 processed
    client.post("/games/g1/pump")
    rec2 = client.get(f"/events/{body['ev_id']}").json()
    assert rec2["status"] == "processed"
    close_engine(engine)


async def _worker_scenario(tmp_path):
    engine = open_persistent_engine(str(tmp_path / "games.db"))
    _seed(engine.object_store)
    bus = EventBus(path=str(tmp_path / "events.json"))
    worker = PumpWorker(engine, bus, poll_interval=0.1)

    worker.start()
    try:
        # 入队后等待常驻 pump 自动消费
        bus.enqueue(new_event("intel_report", "radar",
                              {"order_id": "o5", "kind": "strike",
                               "unit_id": "u1", "target_id": "t1", "threat": 0.9}))
        for _ in range(50):
            if worker.processed_total >= 1:
                break
            await asyncio.sleep(0.05)
        assert worker.processed_total >= 1
        assert bus.pending() == []
        assert engine.object_store.count("order") == 1
    finally:
        await worker.stop()
        close_engine(engine)


def test_background_pump_consumes_automatically(tmp_path):
    asyncio.run(_worker_scenario(tmp_path))
