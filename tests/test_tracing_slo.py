# -*- coding: utf-8 -*-
"""③ 可观测验收：TraceLogger 落盘 + SLO 指标（事件时延 / 审批等待）。"""
import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from agentorchestra.agents.simple_agent import SimpleAgent
from agentorchestra.orchestration.state.backends.memory_backend import InMemoryCheckpointStore

from app.api.server import create_app
from app.core.mock_llm import MockLLM
from app.core.tracing import build_trace_config
from app.domain.persist import close_engine, open_persistent_engine
from app.engine.event_bus import EventBus, new_event
from app.engine.service import process_pending


def _seed(store):
    store.insert("unit", {"unit_id": "u1", "name": "甲", "side": "friendly",
                          "location": "A1", "status": "idle", "strength": 80})
    store.insert("target", {"target_id": "t1", "name": "雷达", "kind": "radar",
                            "side": "enemy", "threat": 0.8, "location": "B2"})


def test_trace_logger_writes_files(tmp_path):
    engine = open_persistent_engine(str(tmp_path / "games.db"))
    _seed(engine.object_store)
    bus = EventBus(path=str(tmp_path / "events.json"))
    trace_dir = tmp_path / "traces"

    def factory():
        return SimpleAgent(name="intel", llm=MockLLM(),
                           config=build_trace_config(str(trace_dir)))

    bus.enqueue(new_event("intel_report", "radar",
                          {"order_id": "o1", "kind": "strike", "unit_id": "u1",
                           "target_id": "t1", "threat": 0.9}))
    asyncio.run(process_pending(engine, bus, intel_agent_factory=factory))

    files = list(Path(trace_dir).glob("*"))
    assert any(f.suffix == ".jsonl" for f in files), f"未生成 trace: {files}"
    close_engine(engine)


def test_slo_metrics_recorded(tmp_path):
    engine = open_persistent_engine(str(tmp_path / "games.db"))
    _seed(engine.object_store)
    bus = EventBus(path=str(tmp_path / "events.json"))
    state = InMemoryCheckpointStore()

    with TestClient(create_app(engine=engine, bus=bus, state_store=state)) as client:
        client.post("/events", json={"kind": "intel_report", "source": "radar",
                                     "payload": {"order_id": "o2", "kind": "strike",
                                                 "unit_id": "u1", "target_id": "t1",
                                                 "threat": 0.9}})
        client.post("/games/g1/pump")

        # 事件时延
        text = client.get("/metrics").text
        assert "deck_event_latency_seconds" in text

        # 审批等待
        client.post("/approvals/o2", json={"approve": True})
        text = client.get("/metrics").text
        assert "deck_approval_wait_seconds" in text

    close_engine(engine)
