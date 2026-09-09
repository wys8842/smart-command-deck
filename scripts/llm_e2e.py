# -*- coding: utf-8 -*-
"""真实模型端到端小规模压测：验证单机容量建议（4 局 × 5 事件）。

用法：
    D:/python/miniconda/envs/llm/python.exe scripts/llm_e2e.py [--games 4] [--events 5]
输出：
    docs/llm-e2e-report.md
"""
from __future__ import annotations

import argparse
import asyncio
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentorchestra.orchestration.state.backends.memory_backend import (  # noqa: E402
    InMemoryCheckpointStore,
)

from app.core.env import load_env  # noqa: E402
from app.core.llm_factory import build_intel_agent, llm_mode  # noqa: E402
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


def _high(gid, i):
    return new_event("intel_report", "radar",
                     {"order_id": f"{gid}-o{i}", "kind": "strike", "unit_id": "u1",
                      "target_id": "t1", "threat": 0.9,
                      "text": f"雷达异常 {gid}-{i}"})


def _low(gid, i):
    return new_event("intel_report", "sensor",
                     {"text": f"例行 {gid}-{i}", "threat": 0.1})


async def _run_game(gid: str, events: int, tmp: Path):
    engine = create_engine()
    _seed(engine.object_store)
    bus = EventBus(path=str(tmp / f"{gid}.json"))
    exp = ExperienceStore(path=str(tmp / f"{gid}.exp.jsonl"))
    tenancy = build_tenancy(default_limit=1_000_000)
    state = InMemoryCheckpointStore()

    n_high = max(1, int(events * 0.6))
    evs = [_high(gid, i) for i in range(n_high)] + \
          [_low(gid, i) for i in range(events - n_high)]

    lat_high, lat_low = [], []
    t0 = time.perf_counter()
    for ev in evs:
        bus.enqueue(ev)
        t = time.perf_counter()
        await process_pending(engine, bus, intel_agent_factory=build_intel_agent,
                              experience=exp, tenancy=tenancy, state_store=state)
        dt = time.perf_counter() - t
        (lat_high if ev.kind == "intel_report" and ev.payload.get("threat", 0) >= 0.6
         else lat_low).append(dt)
    elapsed = time.perf_counter() - t0
    return {
        "game": gid,
        "events": len(evs),
        "orders": engine.object_store.count("order"),
        "elapsed_s": elapsed,
        "lat_high": lat_high,
        "lat_low": lat_low,
        "exp_stats": exp.stats(),
    }


async def _all(games: int, events: int, tmp: Path):
    return await asyncio.gather(
        *[_run_game(f"g{i}", events, tmp) for i in range(games)])


def _pct(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int(p * (len(s) - 1)))] * 1000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=4)
    ap.add_argument("--events", type=int, default=5)
    args = ap.parse_args()

    load_env()
    mode, model = llm_mode()
    print(f"llm mode={mode} model={model}")
    if mode != "real":
        print("未配置真实 LLM，跳过。")
        return 0

    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="deck-llm-e2e-"))
    t0 = time.perf_counter()
    results = asyncio.run(_all(args.games, args.events, tmp))
    wall = time.perf_counter() - t0

    total_events = sum(r["events"] for r in results)
    total_high = sum(len(r["lat_high"]) for r in results)
    all_high = [x for r in results for x in r["lat_high"]]
    all_low = [x for r in results for x in r["lat_low"]]
    agg_rate = total_events / wall
    high_p50 = statistics.median(all_high) * 1000 if all_high else 0
    high_p95 = _pct(all_high, 0.95)
    low_p95 = _pct(all_low, 0.95)

    # 预测校验：单局吞吐 ≈ 1/平均高危时延；聚合 ≈ K × 单局 × 重叠系数
    single_game_rate = (1.0 / statistics.mean(all_high)) if all_high else 0
    predicted_agg = args.games * single_game_rate
    overlap = (agg_rate / predicted_agg) if predicted_agg else 0

    lines = [
        "# 真实模型端到端压测报告（自动生成）",
        "",
        f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Python：{platform.python_version()} · 平台：{platform.platform()}",
        f"- 模型：{model} · 规模：{args.games} 局 × {args.events} 事件（高危 {total_high} 次调用）",
        "",
        "## 一、结果",
        "",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| 总事件 | {total_events} |",
        f"| 墙钟耗时 | {wall:.2f}s |",
        f"| 聚合吞吐 | {agg_rate:.2f} events/s |",
        f"| 高危事件时延 p50 | {high_p50:.0f} ms |",
        f"| 高危事件时延 p95 | {high_p95:.0f} ms |",
        f"| 低危事件时延 p95（无 LLM） | {low_p95:.0f} ms |",
        "",
        "## 二、逐局",
        "",
        "| 局 | 事件 | 订单 | 耗时(s) | 高危p50(ms) | 缓存hits/misses |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for r in results:
        p50 = statistics.median(r["lat_high"]) * 1000 if r["lat_high"] else 0
        st = r["exp_stats"]
        lines.append(f"| {r['game']} | {r['events']} | {r['orders']} | {r['elapsed_s']:.2f} "
                     f"| {p50:.0f} | {st['hits']}/{st['misses']} |")

    lines += [
        "",
        "## 三、与容量模型对照",
        "",
        f"- 单局理论吞吐（1/平均高危时延）：{single_game_rate:.2f} events/s",
        f"- 预测聚合吞吐（{args.games} 局）：{predicted_agg:.2f} events/s",
        f"- 实测聚合吞吐：{agg_rate:.2f} events/s",
        f"- 重叠系数（实测/预测）：{overlap:.2f}",
        "",
        f"> 结论：{'✅ 实测与容量模型一致' if 0.6 <= overlap <= 1.5 else '⚠️ 与模型有偏差，检查模型侧限流/网络'}",
        "> （重叠系数 ≈0.8 表示多局并发有效重叠；真实模型吞吐由模型延迟主导。）",
    ]

    out = ROOT / "docs" / "llm-e2e-report.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n报告已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
