# -*- coding: utf-8 -*-
"""3/1 验收：LLM 缓存、有界并发、图状态 CheckpointStore。"""
import asyncio
from types import SimpleNamespace

from agentorchestra.agents.simple_agent import SimpleAgent
from agentorchestra.orchestration.state.backends.memory_backend import InMemoryCheckpointStore

from app.core.llm_resilience import CachedLLM
from app.core.mock_llm import MockLLM
from app.domain.persist import close_engine, open_persistent_engine
from app.engine.event_bus import EventBus, new_event
from app.engine.service import process_pending


class _CountingLLM:
    model = "counting"

    def __init__(self):
        self.calls = 0

    def invoke(self, messages, **kwargs):
        self.calls += 1
        return SimpleNamespace(content=f"answer-{self.calls}", usage=None)


def test_cached_llm_hits_and_misses():
    inner = _CountingLLM()
    llm = CachedLLM(inner, max_size=8, ttl=60)
    m = [{"role": "user", "content": "hi"}]

    r1 = llm.invoke(m)
    r2 = llm.invoke(m)
    assert inner.calls == 1
    assert r2.cached is True
    assert r1.content == r2.content

    llm.invoke([{"role": "user", "content": "other"}])
    assert inner.calls == 2
    assert llm.stats()["hits"] == 1


def _seed(store):
    store.insert("unit", {"unit_id": "u1", "name": "甲", "side": "friendly",
                          "location": "A1", "status": "idle", "strength": 80})
    store.insert("target", {"target_id": "t1", "name": "雷达", "kind": "radar",
                            "side": "enemy", "threat": 0.8, "location": "B2"})


def test_bounded_concurrency_processes_all(tmp_path):
    engine = open_persistent_engine(str(tmp_path / "games.db"))
    _seed(engine.object_store)
    bus = EventBus(path=str(tmp_path / "events.json"))
    for i in range(5):
        bus.enqueue(new_event("intel_report", "radar",
                              {"order_id": f"c{i}", "kind": "strike", "unit_id": "u1",
                               "target_id": "t1", "threat": 0.9}))
    creations = {"n": 0}

    def factory():
        creations["n"] += 1
        return SimpleAgent(name="intel", llm=MockLLM())

    res = asyncio.run(process_pending(engine, bus, intel_agent_factory=factory,
                                      max_concurrency=3))
    assert res["processed_count"] == 5
    assert engine.object_store.count("order") == 5
    assert creations["n"] == 5  # 并发下每个任务独立 Agent
    close_engine(engine)


def test_state_store_used_by_scheduler(tmp_path):
    engine = open_persistent_engine(str(tmp_path / "games.db"))
    _seed(engine.object_store)
    bus = EventBus(path=str(tmp_path / "events.json"))
    state = InMemoryCheckpointStore()
    bus.enqueue(new_event("intel_report", "radar",
                          {"order_id": "o1", "kind": "strike", "unit_id": "u1",
                           "target_id": "t1", "threat": 0.9}))
    res = asyncio.run(process_pending(engine, bus, state_store=state))
    assert res["processed_count"] == 1
    # scheduler 使用该 store 落 Inbox（证明图状态已接入 CheckpointStore）
    assert getattr(state, "_inbox_messages", {})
    close_engine(engine)
