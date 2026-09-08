# -*- coding: utf-8 -*-
"""M5 复盘/观测/加固验收：
- 一键剧本（3 命令：2 批准 1 驳回 + 低危归档）→ 导出 timeline 回放
- 观测：开启 Prometheus collector 且可重置
- 单机多局并发冒烟：asyncio.gather 多局同时跑，互不串扰
"""
import asyncio
import json

from agentorchestra.agents.simple_agent import SimpleAgent
from agentorchestra.components import Components

from app.core.mock_llm import MockLLM
from app.core.observability import init_metrics, reset_telemetry
from app.domain.schema import create_engine
from app.engine.replay import export_timeline, run_scripted_scenario, timeline_to_json


def _factory():
    return SimpleAgent(name="intel", llm=MockLLM())


def _seed(store):
    store.insert("unit", {"unit_id": "u1", "name": "甲编队", "side": "friendly",
                          "location": "A1", "status": "idle", "strength": 80})
    store.insert("target", {"target_id": "t1", "name": "敌方雷达站", "kind": "radar",
                            "side": "enemy", "threat": 0.8, "location": "B2"})


def test_scripted_scenario_and_replay():
    engine = create_engine()
    _seed(engine.object_store)
    summary = asyncio.run(run_scripted_scenario(engine.object_store, _factory, n_orders=3))

    assert summary["approved"] == ["o1", "o2"]
    assert summary["rejected"] == ["o3"]
    assert summary["orders_status"]["o1"] == "executed"
    assert summary["orders_status"]["o2"] == "executed"
    assert summary["orders_status"]["o3"] == "rejected"

    # 复盘导出
    timeline = export_timeline(engine.object_store)
    assert timeline["summary"]["orders"] == 3
    assert timeline["summary"]["settles"] >= 3      # 每条命令都有结算记录
    text = timeline_to_json(timeline)
    parsed = json.loads(text)
    assert parsed["summary"]["orders"] == 3


def test_metrics_observability():
    reset_telemetry()
    collector = init_metrics()
    assert collector is not None
    assert Components.metrics_collector() is collector
    reset_telemetry()


async def _run_game(name: str):
    engine = create_engine()
    _seed(engine.object_store)
    store = engine.object_store
    from app.engine.replay import run_scripted_scenario

    summary = await run_scripted_scenario(store, _factory, n_orders=2)
    return name, summary["orders_status"]["o1"]


async def _run_all():
    return await asyncio.gather(_run_game("g1"), _run_game("g2"), _run_game("g3"))


def test_concurrent_games_isolated():
    results = asyncio.run(_run_all())
    assert len(results) == 3
    for name, status in results:
        assert status == "executed", name
