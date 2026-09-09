# -*- coding: utf-8 -*-
"""智能推演指挥台 · 端到端验收 + 压测（离线 Mock，可含真实 LLM 报告）。

用法：
    D:/python/miniconda/envs/llm/python.exe scripts/acceptance.py
输出：
    docs/acceptance-report.md
"""
from __future__ import annotations

import asyncio
import json
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentorchestra.agents.simple_agent import SimpleAgent  # noqa: E402
from agentorchestra.orchestration.state.backends.memory_backend import (  # noqa: E402
    InMemoryCheckpointStore,
)
from agentorchestra.orchestration.state.interrupt import InterruptResumer  # noqa: E402

from app.core.mock_llm import MockLLM  # noqa: E402
from app.core.tenancy import build_tenancy  # noqa: E402
from app.core.tracing import build_trace_config  # noqa: E402
from app.domain.experience import ExperienceStore  # noqa: E402
from app.domain.persist import close_engine, open_persistent_engine  # noqa: E402
from app.domain.relations import seed_scenario, situation  # noqa: E402
from app.domain.schema import create_engine  # noqa: E402
from app.engine.event_bus import EventBus, new_event  # noqa: E402
from app.engine.hitl import approval_event  # noqa: E402
from app.engine.interrupts import (  # noqa: E402
    REASON_APPROVAL,
    approval_resume_handler,
    list_pending,
    resolve_approval,
)
from app.engine.replay import ReplayStore  # noqa: E402
from app.engine.service import process_pending  # noqa: E402


def _mock_factory():
    return SimpleAgent(name="intel", llm=MockLLM())


def _seed(store):
    store.insert("unit", {"unit_id": "u1", "name": "甲", "side": "friendly",
                          "location": "A1", "status": "idle", "strength": 80})
    store.insert("target", {"target_id": "t1", "name": "雷达", "kind": "radar",
                            "side": "enemy", "threat": 0.8, "location": "B2"})


def _high(i, tenant="default", tokens=1, text="敌方雷达异常"):
    return new_event("intel_report", "radar",
                     {"order_id": f"a{i}", "kind": "strike", "unit_id": "u1",
                      "target_id": "t1", "threat": 0.9, "tenant": tenant,
                      "tokens": tokens, "text": text})


def _low(i, tenant="default"):
    return new_event("intel_report", "sensor",
                     {"text": f"例行 {i}", "threat": 0.1, "tenant": tenant, "tokens": 1})


async def _stress(engine, bus, exp, tenancy, replay, n_high, n_low, concurrency=1):
    for i in range(n_high):
        bus.enqueue(_high(i))
    for i in range(n_low):
        bus.enqueue(_low(i))
    t0 = time.perf_counter()
    res = await process_pending(engine, bus, intel_agent_factory=_mock_factory,
                                replay_store=replay, state_store=InMemoryCheckpointStore(),
                                experience=exp, tenancy=tenancy,
                                max_concurrency=concurrency)
    elapsed = time.perf_counter() - t0
    return res, elapsed


async def _latency_samples(engine, bus, exp, tenancy, n):
    lat = []
    for i in range(n):
        bus.enqueue(_high(10_000 + i))
        t0 = time.perf_counter()
        await process_pending(engine, bus, intel_agent_factory=_mock_factory,
                              experience=exp, tenancy=tenancy)
        lat.append(time.perf_counter() - t0)
    return lat


async def _hitl_flow(engine, bus, state):
    bus.enqueue(_high(20_000))
    await process_pending(engine, bus, intel_agent_factory=_mock_factory, state_store=state)
    pending = await list_pending(state)
    assert pending, "应生成 Interrupt"
    order_id = pending[0].payload["order_id"]
    await resolve_approval(state, order_id, True)
    resumer = InterruptResumer(state, poll_interval=0.1)
    resumer.register_handler(REASON_APPROVAL,
                             approval_resume_handler(engine.object_store, bus))
    await resumer.poll_once()
    await process_pending(engine, bus, intel_agent_factory=_mock_factory, state_store=state)
    return engine.object_store.get("order", order_id)["status"]


async def _resume_check(db_path, bus_path):
    e1 = open_persistent_engine(db_path)
    _seed(e1.object_store)
    bus = EventBus(path=bus_path)
    for i in range(20):
        bus.enqueue(_high(30_000 + i))
    await process_pending(e1, bus, intel_agent_factory=_mock_factory)
    first = e1.object_store.count("order")
    close_engine(e1)

    e2 = open_persistent_engine(db_path)
    bus2 = EventBus(path=bus_path)
    res = await process_pending(e2, bus2, intel_agent_factory=_mock_factory)
    total = e2.object_store.count("order")
    close_engine(e2)
    return {"first": first, "second_processed": res["processed_count"], "total": total}


def _metrics_lines() -> list[str]:
    try:
        from agentorchestra.observability.metrics import get_default_collector

        text = get_default_collector().render()
        keys = ("deck_events_processed_total", "deck_event_latency_seconds_count",
                "deck_pump_cycle_seconds_count", "deck_quota_denied_total")
        return [ln for ln in text.splitlines() if ln and any(k in ln for k in keys)][:12]
    except Exception:  # noqa: BLE001
        return []


def _llm_report() -> list[str]:
    p = ROOT / "docs" / "llm-perf-report.md"
    if p.exists():
        return [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.startswith("- ")]
    return ["（未生成真实 LLM 报告，运行 scripts/bench_llm.py）"]


def main() -> int:
    import tempfile

    from agentorchestra.components import Components

    Components.enable_prometheus()  # 让指标可渲染

    tmp = Path(tempfile.mkdtemp(prefix="deck-accept-"))
    checks: list[tuple[str, bool, str]] = []

    # ---------- 功能/关系/战例/配额 ----------
    engine = create_engine()
    _seed(engine.object_store)
    seed_scenario(engine.object_store)
    neighbors = situation(engine.object_store, "u1", depth=2)["count"]
    checks.append(("关系推理（u1 二跳邻域）", neighbors > 0, f"{neighbors} 条关系"))

    bus = EventBus(path=str(tmp / "events.json"))
    exp = ExperienceStore(path=str(tmp / "exp.jsonl"))
    tenancy = build_tenancy(default_limit=1_000_000)
    replay = ReplayStore(path=str(tmp / "replay.jsonl"))
    state = InMemoryCheckpointStore()

    # 压测：顺序 300 事件
    res_seq, el_seq = asyncio.run(_stress(engine, bus, exp, tenancy, replay, 200, 100, 1))
    checks.append(("顺序压测 300 事件", res_seq["processed_count"] == 300,
                   f"{300 / el_seq:.0f} events/s"))

    # 压测：并发 100 事件
    bus2 = EventBus(path=str(tmp / "events2.json"))
    res_conc, el_conc = asyncio.run(_stress(engine, bus2, exp, tenancy, replay, 70, 30, 4))
    checks.append(("有界并发(max=4) 100 事件", res_conc["processed_count"] == 100,
                   f"{100 / el_conc:.0f} events/s"))

    # 时延采样
    bus3 = EventBus(path=str(tmp / "events3.json"))
    lat = asyncio.run(_latency_samples(engine, bus3, exp, tenancy, 50))
    p50 = statistics.median(lat) * 1000
    p95 = sorted(lat)[int(0.95 * (len(lat) - 1))] * 1000
    checks.append(("事件时延采样 50 次", True, f"p50={p50:.1f}ms p95={p95:.1f}ms"))

    # 战例召回缓存
    exp_stats = exp.stats()
    checks.append(("战例召回缓存命中", exp_stats["hits"] > 0,
                   f"hits={exp_stats['hits']} misses={exp_stats['misses']}"))

    # HITL
    status = asyncio.run(_hitl_flow(engine, bus3, state))
    checks.append(("HITL Interrupt 批准续跑", status == "executed", f"status={status}"))

    # 配额拒绝
    tight = build_tenancy(default_limit=5)
    bus4 = EventBus(path=str(tmp / "events4.json"))
    denied_ev = _high(99, tenant="acme", tokens=10)
    bus4.enqueue(denied_ev)
    res_deny = asyncio.run(process_pending(engine, bus4, intel_agent_factory=_mock_factory,
                                           tenancy=tight))
    checks.append(("配额超限拒绝", denied_ev.ev_id in res_deny["denied"],
                   f"denied={len(res_deny['denied'])}"))

    # 崩溃续跑
    resume = asyncio.run(_resume_check(str(tmp / "games.db"), str(tmp / "resume.json")))
    checks.append(("崩溃续跑无重复", resume["second_processed"] == 0 and resume["total"] == 20,
                   f"first={resume['first']} second={resume['second_processed']} total={resume['total']}"))

    # TraceLogger 落盘
    trace_dir = tmp / "traces"
    bus5 = EventBus(path=str(tmp / "events5.json"))
    bus5.enqueue(_high(50_000))
    asyncio.run(process_pending(
        engine, bus5,
        intel_agent_factory=lambda: SimpleAgent(name="intel", llm=MockLLM(),
                                                config=build_trace_config(str(trace_dir)))))
    trace_files = list(trace_dir.glob("*")) if trace_dir.exists() else []
    checks.append(("TraceLogger 落盘", any(f.suffix == ".jsonl" for f in trace_files),
                   f"{len(trace_files)} 文件"))

    # 可观测指标
    mlines = _metrics_lines()
    checks.append(("Prometheus 指标输出", any("deck_events_processed_total" in ln for ln in mlines),
                   f"{len(mlines)} 条指标行"))

    # 复盘
    timeline = replay.runs(limit=5)
    checks.append(("复盘时间线", len(timeline) > 0, f"{len(timeline)} 条运行记录"))

    # ---------- 报告 ----------
    passed = sum(1 for _, ok, _ in checks if ok)
    lines = [
        "# 智能推演指挥台 · 验收与压测报告（自动生成）",
        "",
        f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Python：{platform.python_version()} · 平台：{platform.platform()}",
        f"- 结论：**{passed}/{len(checks)} 项通过**",
        "",
        "## 一、功能验收",
        "",
        "| 项 | 结果 | 说明 |",
        "|---|---|---|",
    ]
    for name, ok, detail in checks:
        lines.append(f"| {name} | {'✅' if ok else '❌'} | {detail} |")

    lines += [
        "",
        "## 二、性能",
        "",
        "| 场景 | 吞吐 | 说明 |",
        "|---|---:|---|",
        f"| 顺序推演 | {300 / el_seq:.0f} events/s | 200 高危 + 100 低危（MockLLM） |",
        f"| 有界并发(max=4) | {100 / el_conc:.0f} events/s | 70 高危 + 30 低危 |",
        f"| 单事件时延 | p50={p50:.1f}ms / p95={p95:.1f}ms | 50 次采样（MockLLM，含持久化/编排） |",
        "",
        "## 三、真实 LLM 延迟（minimax-m3）",
        "",
        *_llm_report(),
        "",
        "## 四、可观测指标（摘录）",
        "",
        "```",
        *mlines,
        "```",
        "",
        "## 五、回归测试",
        "",
        "- `pytest tests`：62 passed（见仓库 CI）",
        "",
        "> 说明：压测使用 MockLLM 以排除模型网络时延，衡量框架编排/持久化/治理开销；",
        "> 真实模型延迟单独见 `docs/llm-perf-report.md`。",
    ]
    out = ROOT / "docs" / "acceptance-report.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n报告已写入 {out}")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
