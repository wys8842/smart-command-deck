# -*- coding: utf-8 -*-
"""② 战例召回验收：写入/召回 + 缓存命中 + 二次事件注入历史战例。"""
import asyncio

from app.domain.experience import ExperienceStore
from app.domain.persist import close_engine, open_persistent_engine
from app.engine.event_bus import EventBus, new_event
from app.engine.service import process_pending


def _seed(store):
    store.insert("unit", {"unit_id": "u1", "name": "甲", "side": "friendly",
                          "location": "A1", "status": "idle", "strength": 80})
    store.insert("target", {"target_id": "t1", "name": "雷达", "kind": "radar",
                            "side": "enemy", "threat": 0.8, "location": "B2"})


class RecordingAgent:
    """记录收到的 task，并返回固定研判结论。"""

    model = "recording"

    def __init__(self):
        self.tasks = []

    async def arun(self, task):
        self.tasks.append(task)
        return "研判建议：保持警戒并核实目标"

    def clear_history(self):
        pass


def test_experience_remember_and_cache(tmp_path):
    exp = ExperienceStore(path=str(tmp_path / "exp.jsonl"), cache_ttl=60)
    exp.remember_case("intel_report", "敌方雷达异常", "派无人机核实", tags=["radar"])

    calls = {"n": 0}
    orig = exp.manager.recall

    def counting(*a, **k):
        calls["n"] += 1
        return orig(*a, **k)

    exp.manager.recall = counting  # type: ignore[assignment]

    r1 = exp.recall("敌方雷达异常", top_k=3)
    r2 = exp.recall("敌方雷达异常", top_k=3)
    assert r1 and r1 == r2
    assert calls["n"] == 1          # 第二次命中缓存
    assert exp.stats()["hits"] == 1


def test_experience_injected_into_second_event(tmp_path):
    engine = open_persistent_engine(str(tmp_path / "games.db"))
    _seed(engine.object_store)
    bus = EventBus(path=str(tmp_path / "events.json"))
    exp = ExperienceStore(path=str(tmp_path / "exp.jsonl"))
    agent = RecordingAgent()

    def factory():
        return agent

    # 第一次事件：沉淀战例
    bus.enqueue(new_event("intel_report", "radar",
                          {"order_id": "e1", "kind": "strike", "unit_id": "u1",
                           "target_id": "t1", "threat": 0.9, "text": "敌方雷达异常"}))
    asyncio.run(process_pending(engine, bus, intel_agent_factory=factory, experience=exp))

    # 第二次同类事件：研判任务应包含历史战例参考
    bus.enqueue(new_event("intel_report", "radar",
                          {"order_id": "e2", "kind": "strike", "unit_id": "u1",
                           "target_id": "t1", "threat": 0.9, "text": "敌方雷达异常"}))
    asyncio.run(process_pending(engine, bus, intel_agent_factory=factory, experience=exp))

    assert "历史战例参考" in agent.tasks[-1]
    assert "保持警戒" in agent.tasks[-1]
    close_engine(engine)
