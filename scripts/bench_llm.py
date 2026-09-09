# -*- coding: utf-8 -*-
"""真实 LLM 延迟基准（p50/p95 + 缓存命中对比）。

用法：python scripts/bench_llm.py [--n 5]
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.env import load_env  # noqa: E402
from app.core.llm_factory import build_llm, llm_mode  # noqa: E402
from app.core.mock_llm import MockLLM  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5)
    args = ap.parse_args()

    load_env()
    mode, model = llm_mode()
    print(f"mode={mode} model={model}")
    if mode != "real":
        print("未配置真实 LLM（LLM_MODEL_ID/LLM_API_KEY），跳过。")
        return 0

    llm = build_llm()
    if isinstance(llm, MockLLM):
        print("回退 Mock，跳过。")
        return 0

    lat = []
    for i in range(args.n):
        msgs = [{"role": "user", "content": f"用一句话回答第 {i} 个测试问题。"}]
        t0 = time.perf_counter()
        llm.invoke(msgs)
        lat.append(time.perf_counter() - t0)
        print(f"  call {i + 1}: {lat[-1] * 1000:.0f} ms")

    lat_sorted = sorted(lat)
    p50 = statistics.median(lat_sorted)
    p95 = lat_sorted[min(len(lat_sorted) - 1, int(round(0.95 * (len(lat_sorted) - 1))))]

    # 缓存命中对比（同一条 prompt 第二次）
    msgs = [{"role": "user", "content": "缓存命中测试：只回复 OK"}]
    t0 = time.perf_counter(); llm.invoke(msgs); first = time.perf_counter() - t0
    t0 = time.perf_counter(); llm.invoke(msgs); second = time.perf_counter() - t0
    stats = llm.stats() if hasattr(llm, "stats") else {}

    lines = [
        "# 真实 LLM 延迟基准（自动生成）",
        "",
        f"- 模型：{model} · 样本：{args.n}",
        f"- p50：{p50 * 1000:.0f} ms",
        f"- p95：{p95 * 1000:.0f} ms",
        f"- 首次调用：{first * 1000:.0f} ms；缓存命中：{second * 1000:.0f} ms",
        f"- 缓存统计：{stats}",
    ]
    out = ROOT / "docs" / "llm-perf-report.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\np50={p50 * 1000:.0f}ms p95={p95 * 1000:.0f}ms cache_hit={second * 1000:.1f}ms")
    print(f"报告已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
