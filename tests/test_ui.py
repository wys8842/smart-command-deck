# -*- coding: utf-8 -*-
"""浏览器控制台 + 事件列表接口验收。"""
from fastapi.testclient import TestClient

from app.api.server import create_app
from app.domain.persist import close_engine, open_persistent_engine
from app.engine.event_bus import EventBus, new_event


def test_ui_page_and_events_list(tmp_path):
    engine = open_persistent_engine(str(tmp_path / "games.db"))
    bus = EventBus(path=str(tmp_path / "events.json"))
    client = TestClient(create_app(engine=engine, bus=bus))

    # 控制台页面
    r = client.get("/")
    assert r.status_code == 200
    assert "智能推演指挥台" in r.text
    assert "待批命令" in r.text

    # 事件列表
    bus.enqueue(new_event("intel_report", "radar", {"text": "x"}))
    evs = client.get("/events").json()["events"]
    assert len(evs) == 1
    assert evs[0]["status"] == "queued"

    close_engine(engine)
