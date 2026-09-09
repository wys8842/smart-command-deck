# -*- coding: utf-8 -*-
"""性能基准：EventBus / ontology / deck 推演 / coordinator 事务。

用法：
    python scripts/bench.py            # 默认规模
    python scripts/bench.py --scale 2  # 放大 2 倍
输出：
    控制台表格 + docs/perf-report.md
"""
from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentorchestra.agents.simple_agent import SimpleAgent  # noqa: E402

from app.core.mock_llm import MockLLM  # noqa: E402
from app.domain.coord_ledger import CoordinatorLedger  # noqa: E402
from app.domain.schema import create_engine  # noqa: E402
from app.engine.event_bus import EventBus, new_event  # noqa: E402
from app.engine.service import process_pending  # noqa: E402


def _timeit(fn, *args, **kwargs):
    t0 = time.perf_counter()
    out = fn(*args, **kwargs)
    return out, time.perf_counter() - t0


def bench_event_bus(n: int, tmp: Path) -> dict:
    bus = EventBus(path=str(tmp / "bench_events.json"))
    t0 = time.perf_counter()
    events = [new_event("intel_report", "bench", {"i": i}) for i in range(n)]
    for e in events:
        bus.enqueue(e)
    t_enq = time.perf_counter() - t0

    t0 = time.perf_counter()
    _ = bus.pending()
    t_pend = time.perf_counter() - t0

    t0 = time.perf_counter()
    for e in events:
        bus.mark_processed(e.ev_id)
    t_mark = time.perf_counter() - t0
    return {
        "enqueue_ops": n / t_enq,
        "pending_ops": n / t_pend,
        "mark_ops": n / t_mark,
    }


def bench_ontology(n: int) -> dict:
    engine = create_engine()
    store = engine.object_store
    store.insert("unit", {"unit_id": "u1", "name": "甲", "side": "friendly",
                          "location": "A1", "status": "idle", "strength": 80})
    t0 = time.perf_counter()
    for i in range(n):
        store.insert("target", {"target_id": f"t{i}", "name": f"目标{i}", "kind": "radar",
                                "side": "enemy", "threat": 0.5, "location": "B"})
    t_ins = time.perf_counter() - t0
    t0 = time.perf_counter()
    for i in range(n):
        store.get("target", f"t{i}")
    t_get = time.perf_counter() - t0
    return {"insert_ops": n / t_ins, "get_ops": n / t_get}


def bench_deck(n: int, tmp: Path) -> dict:
    engine = create_engine()
    engine.object_store.insert("target", {"target_id": "t1", "name": "雷达", "kind": "radar",
                                          "side": "enemy", "threat": 0.8, "location": "B"})
    bus = EventBus(path=str(tmp / "bench_deck_events.json"))
    for i in range(n):
        bus.enqueue(new_event("intel_report", "bench",
                              {"order_id": f"o{i}", "kind": "strike", "unit_id": "u1",
                               "target_id": "t1", "threat": 0.9}))

    def factory():
        return SimpleAgent(name="intel", llm=MockLLM())

    async def run():
        return await process_pending(engine, bus, intel_agent_factory=factory)

    res, elapsed = _timeit(asyncio.run, run())
    return {
        "events": n,
        "elapsed_s": elapsed,
        "events_per_s": n / elapsed,
        "orders": res["processed_count"],
    }


def bench_tx(n: int) -> dict:
    engine = create_engine()
    engine.object_store.insert("stock", {"stock_id": "s1", "kind": "ammo", "qty": 0.0})
    ledger = CoordinatorLedger(engine.object_store).register_actions()
    t0 = time.perf_counter()
    for i in range(n):
        ledger.run([{"action": "resupply_stock", "params": {"stock_id": "s1", "qty": 1}}],
                   idempotency_key=f"bench-{i}")
    elapsed = time.perf_counter() - t0
    return {"tx_ops": n / elapsed, "elapsed_s": elapsed}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--out", default="docs/perf-report.md")
    args = ap.parse_args()

    import tempfile

    n = lambda base: max(10, int(base * args.scale))  # noqa: E731
    tmp = Path(tempfile.mkdtemp(prefix="deck-bench-"))

    print("=== Smart Command Deck benchmark ===")
    results = {
        "event_bus": bench_event_bus(n(2000), tmp),
        "ontology": bench_ontology(n(2000)),
        "deck": bench_deck(n(200), tmp),
        "tx": bench_tx(n(200)),
    }
    print(json.dumps(results, ensure_ascii=False, indent=2))

    lines = [
        "# 性能基准报告（自动生成）",
        "",
        f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Python：{platform.python_version()} · 平台：{platform.platform()}",
        f"- 规模系数：{args.scale}",
        "",
        "| 项目 | 指标 | 数值 |",
        "|---|---|---:|",
        f"| EventBus | enqueue ops/s | {results['event_bus']['enqueue_ops']:.0f} |",
        f"| EventBus | pending ops/s | {results['event_bus']['pending_ops']:.0f} |",
        f"| EventBus | mark_processed ops/s | {results['event_bus']['mark_ops']:.0f} |",
        f"| Ontology | insert ops/s | {results['ontology']['insert_ops']:.0f} |",
        f"| Ontology | get ops/s | {results['ontology']['get_ops']:.0f} |",
        f"| Deck 推演 | events/s | {results['deck']['events_per_s']:.0f} |",
        f"| Coordinator 事务 | tx ops/s | {results['tx']['tx_ops']:.0f} |",
        "",
        "> 说明：Deck 使用 MockLLM（排除真实模型网络时延），用于衡量框架编排/持久化开销。",
    ]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n报告已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
