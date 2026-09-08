# -*- coding: utf-8 -*-
"""M2 回合时钟+事件泵验收：
- 注入 3 条不同类型事件，均产出研判记录（ontology record）
- 重启/重放不重复（EventBus processed 去重）
"""
import asyncio
import tempfile
from pathlib import Path

from agentorchestra.agents.simple_agent import SimpleAgent

from app.core.mock_llm import MockLLM
from app.domain.schema import create_engine
from app.engine.event_bus import EventBus, new_event
from app.engine.pump import run_pending


def _intel_factory():
    return SimpleAgent(name="intel", llm=MockLLM())


def _seed(store):
    store.insert("unit", {"unit_id": "u1", "name": "甲编队", "side": "friendly",
                          "location": "A1", "status": "idle", "strength": 80})
    store.insert("target", {"target_id": "t1", "name": "敌方雷达站", "kind": "radar",
                            "side": "enemy", "threat": 0.8, "location": "B2"})


def test_three_events_produce_records(tmp_path):
    engine = create_engine()
    _seed(engine.object_store)
    bus = EventBus(path=str(tmp_path / "events.json"))

    evs = [
        new_event("intel_report", "radar", {"text": "敌方雷达站附近出现装甲编队"}),
        new_event("alert", "supply", {"text": "甲编队弹药不足"}),
        new_event("intel_report", "signal", {"text": "拦截到异常通信"}),
    ]
    for e in evs:
        bus.enqueue(e)

    done = asyncio.run(run_pending(bus, _intel_factory, engine.object_store))

    assert len(done) == 3
    assert engine.object_store.count("record") == 3
    for e in evs:
        rec = engine.object_store.get("record", e.ev_id)
        assert rec is not None, e.ev_id
        assert "mock" in rec["summary"]


def test_replay_no_duplicate(tmp_path):
    engine = create_engine()
    _seed(engine.object_store)
    bus = EventBus(path=str(tmp_path / "events.json"))
    for _ in range(3):
        bus.enqueue(new_event("intel_report", "radar", {"text": "重复测试"}))

    asyncio.run(run_pending(bus, _intel_factory, engine.object_store))
    first = engine.object_store.count("record")

    # 模拟重启：新建 EventBus（同一文件）再消费一次 → 不重复
    bus2 = EventBus(path=str(tmp_path / "events.json"))
    again = asyncio.run(run_pending(bus2, _intel_factory, engine.object_store))

    assert again == []           # 没有新处理
    assert engine.object_store.count("record") == first == 3


def test_event_bus_persistence(tmp_path):
    bus = EventBus(path=str(tmp_path / "events.json"))
    e = new_event("intel_report", "radar", {"text": "x"})
    bus.enqueue(e)
    bus.mark_processed(e.ev_id)

    bus2 = EventBus(path=str(tmp_path / "events.json"))
    assert bus2.is_processed(e.ev_id)
    assert bus2.pending() == []
