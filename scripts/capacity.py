# -*- coding: utf-8 -*-
"""容量压测：2000 事件 + 8 局并发（可调）。

用法：
    python scripts/capacity.py [--events 2000] [--games 8]
输出：
    docs/capacity-report.md
"""
from __future__ import annotations

import argparse
import asyncio
import platform
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentorchestra.agents.simple_agent import SimpleAgent  # noqa: E402
from agentorchestra.components import Components  # noqa: E402
from agentorchestra.orchestration.state.backends.memory_backend import (  # noqa: E402
    InMemoryCheckpointStore,
)

from app.core.mock_llm import MockLLM  # noqa: E402
from app.core.tenancy import build_tenancy  # noqa: E402
from app.domain.experience import ExperienceStore  # noqa: E402
from app.domain.schema import create_engine  # noqa: E402
from app.engine.event_bus import EventBus, new_event  # noqa: E402
from app.engine.service import process_pending  # noqa: E402


def _seed(store):
    store.insert("unit", {"unit_id": "u1", "name": "甲", "side": "friendly",
                          "location": "A1", "status": "idle", "strength": 80})
    store.insert("target", {"target_id": "t1", "name": "雷达", "kind": "radar",
                            "side": "enemy", "threat": 0.8, "location": "B2"})


def _factory():
    return SimpleAgent(name="intel", llm=MockLLM())


def _fill(bus, n_high, n_low, prefix):
    for i in range(n_high):
        bus.enqueue(new_event("intel_report", "radar",
                              {"order_id": f"{prefix}-h{i}", "kind": "strike",
                               "unit_id": "u1", "target_id": "t1", "threat": 0.9,
                               "text": "敌方雷达异常"}))
    for i in range(n_low):
        bus.enqueue(new_event("intel_report", "sensor",
                              {"text": f"例行{prefix}-{i}", "threat": 0.1}))


async def _run_batch(engine, bus, exp, tenancy, state, n_high, n_low, concurrency):
    _fill(bus, n_high, n_low, "b")
    t0 = time.perf_counter()
    res = await process_pending(engine, bus, intel_agent_factory=_factory,
                                experience=exp, tenancy=tenancy, state_store=state,
                                max_concurrency=concurrency)
    return res, time.perf_counter() - t0


async def _run_game(gid, n_events, base: Path):
    engine = create_engine()
    _seed(engine.object_store)
    bus = EventBus(path=str(base / f"{gid}.json"))
    exp = ExperienceStore(path=str(base / f"{gid}.exp.jsonl"))
    tenancy = build_tenancy(default_limit=10_000_000)
    state = InMemoryCheckpointStore()
    n_high = int(n_events * 0.7)
    _fill(bus, n_high, n_events - n_high, gid)
    t0 = time.perf_counter()
    res = await process_pending(engine, bus, intel_agent_factory=_factory,
                                experience=exp, tenancy=tenancy, state_store=state,
                                max_concurrency=4)
    elapsed = time.perf_counter() - t0
    return {
        "game": gid,
        "processed": res["processed_count"],
        "orders": engine.object_store.count("order"),
        "records": engine.object_store.count("record"),
        "elapsed_s": elapsed,
    }


async def _all_games(games, events_per_game, base: Path):
    return await asyncio.gather(
        *[_run_game(f"g{i}", events_per_game, base) for i in range(games)])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", type=int, default=2000)
    ap.add_argument("--games", type=int, default=8)
    args = ap.parse_args()

    Components.enable_prometheus()
    events = args.events
    games = args.games
    per_game = max(10, events // games)

    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="deck-capacity-"))

    # ---------- 单批（顺序 vs 并发）----------
    engine = create_engine()
    _seed(engine.object_store)
    bus = EventBus(path=str(tmp / "single.json"))
    exp = ExperienceStore(path=str(tmp / "single.exp.jsonl"))
    tenancy = build_tenancy(default_limit=10_000_000)
    state = InMemoryCheckpointStore()

    res_seq, t_seq = asyncio.run(_run_batch(
        engine, bus, exp, tenancy, state, int(events * 0.7), events - int(events * 0.7), 1))

    bus2 = EventBus(path=str(tmp / "single2.json"))
    exp2 = ExperienceStore(path=str(tmp / "single2.exp.jsonl"))
    res_conc, t_conc = asyncio.run(_run_batch(
        engine, bus2, exp2, tenancy, InMemoryCheckpointStore(),
        int(events * 0.7), events - int(events * 0.7), 8))

    # ---------- 峰值内存（单独小批，避免 tracemalloc 影响计时）----------
    engine_m = create_engine()
    _seed(engine_m.object_store)
    bus_m = EventBus(path=str(tmp / "mem.json"))
    exp_m = ExperienceStore(path=str(tmp / "mem.exp.jsonl"))
    tracemalloc.start()
    asyncio.run(_run_batch(engine_m, bus_m, exp_m, tenancy, InMemoryCheckpointStore(),
                           70, 30, 1))
    _, peak_seq = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # ---------- 8 局并发 ----------
    t0 = time.perf_counter()
    game_results = asyncio.run(_all_games(games, per_game, tmp / "games"))
    t_games = time.perf_counter() - t0
    total_game_events = sum(g["processed"] for g in game_results)

    # ---------- 报告 ----------
    lines = [
        "# 智能推演指挥台 · 容量压测报告（自动生成）",
        "",
        f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Python：{platform.python_version()} · 平台：{platform.platform()}",
        f"- 规模：单批 {events} 事件；{games} 局 × {per_game} 事件",
        "",
        "## 一、单批吞吐",
        "",
        "| 场景 | 事件 | 耗时(s) | 吞吐(events/s) |",
        "|---|---:|---:|---:|",
        f"| 顺序(max=1) | {events} | {t_seq:.2f} | {events / t_seq:.0f} |",
        f"| 有界并发(max=8) | {events} | {t_conc:.2f} | {events / t_conc:.0f} |",
        "",
        f"- 顺序模式峰值内存：{peak_seq / 1024 / 1024:.1f} MB（tracemalloc）",
        f"- 顺序处理订单：{res_seq['processed_count']}；并发处理订单：{res_conc['processed_count']}",
        "",
        "## 二、多局并发（隔离性）",
        "",
        f"- {games} 局并发总耗时：{t_games:.2f}s，聚合吞吐：{total_game_events / t_games:.0f} events/s",
        "",
        "| 局 | 处理事件 | 订单 | 记录 | 耗时(s) |",
        "|---|---:|---:|---:|---:|",
    ]
    for g in game_results:
        lines.append(f"| {g['game']} | {g['processed']} | {g['orders']} | {g['records']} | {g['elapsed_s']:.2f} |")

    expected_orders = int(per_game * 0.7)
    ok = (res_seq["processed_count"] == events
          and res_conc["processed_count"] == events
          and total_game_events == games * per_game
          and all(g["orders"] == expected_orders for g in game_results))
    lines += [
        "",
        "## 三、结论",
        "",
        f"- 数据一致性：{'✅ 通过' if ok else '❌ 失败'}（单批处理数、订单数、各局隔离计数）",
        "- 单批并发受共享经验库/对象存储与 GIL 限制，收益有限；**多局并发可横向扩展**（见聚合吞吐）。",
        "- 压测使用 MockLLM 以衡量框架编排/持久化/治理开销；真实模型延迟见 `docs/llm-perf-report.md`。",
    ]

    out = ROOT / "docs" / "capacity-report.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n报告已写入 {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
