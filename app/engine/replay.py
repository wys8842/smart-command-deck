# -*- coding: utf-8 -*-
"""复盘（M5）：导出推演 timeline JSON + 一键剧本运行器。

- ReplayStore：按局持久化每次图执行的 NodeEvent 时序（node_start/finish/error…）。
- export_timeline(store, replay_store=None)：orders/records + 节点时序。
- run_scripted_scenario：端到端剧本，返回汇总供验收/复盘。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agentorchestra.orchestration.orch.scheduler import GraphScheduler

from app.engine.deck import build_deck_graph
from app.engine.event_bus import new_event
from app.engine.hitl import approval_event, approve_order
from app.engine.pump import event_message

THREAT_HIGH = 0.9


class ReplayStore:
    """节点时序持久化（单机 JSON，按 thread_id 归局）。"""

    def __init__(self, path: str = "data/replay.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: Dict[str, List] = self._load()

    def _load(self) -> Dict[str, List]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return {"runs": []}

    def _save(self) -> None:
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def append_run(self, thread_id: str, ev_id: str, events: List[Dict[str, Any]],
                   status: str = "completed") -> None:
        self._data["runs"].append({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "thread_id": thread_id,
            "ev_id": ev_id,
            "status": status,
            "events": events,
        })
        self._save()

    def runs(self, thread_id: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        runs = self._data.get("runs", [])
        if thread_id:
            runs = [r for r in runs if r.get("thread_id") == thread_id]
        return list(reversed(runs))[:limit]

    def reset(self) -> None:
        self._data = {"runs": []}
        self._save()


def export_timeline(
    store: Any,
    replay_store: Optional[ReplayStore] = None,
    thread_id: Optional[str] = None,
    limit: int = 200,
) -> Dict[str, Any]:
    """导出某局的 orders + records（+ 可选节点时序）成可回放 JSON。"""
    orders = store.list_objects("order")
    records = store.list_objects("record")
    out: Dict[str, Any] = {
        "summary": {
            "orders": len(orders),
            "records": len(records),
            "settles": sum(1 for r in records if r["kind"] == "settle"),
        },
        "orders": sorted(orders, key=lambda o: str(o.get("order_id", ""))),
        "records": sorted(records, key=lambda r: str(r.get("record_id", ""))),
    }
    if replay_store is not None:
        out["timeline"] = replay_store.runs(thread_id=thread_id, limit=limit)
    return out


def timeline_to_json(timeline: Dict[str, Any], indent: int = 2) -> str:
    return json.dumps(timeline, ensure_ascii=False, indent=indent, default=str)


async def _run_deck(graph: Any, store: Any, event: Any, entry_node: str | None = None):
    sched = GraphScheduler(store=None, max_iterations=8)
    errs: List[str] = []
    res = await sched.execute(
        graph, event_message(event), thread_id="game-scenario",
        entry_node=entry_node,
        on_node_error=lambda e: errs.append(str(e.error)),
    )
    if errs:
        raise RuntimeError(f"推演错误: {errs}")
    return res


async def run_scripted_scenario(
    store: Any,
    intel_agent_factory: Any,
    n_orders: int = 3,
) -> Dict[str, Any]:
    """一键剧本：注入 n 条高危 + 1 条低危事件 → 生成命令 → 批准/驳回 → 结算。

    规则：前 (n-1) 条批准，最后 1 条驳回，留 1 条待批命令用于演示 HITL 可暂停。
    """
    graph = build_deck_graph(intel_agent_factory, store)

    # ① 高危事件 → pending 命令
    for i in range(n_orders):
        ev = new_event("intel_report", "radar", {
            "kind": "strike",
            "order_id": f"o{i + 1}",
            "unit_id": "u1",
            "target_id": "t1",
            "threat": THREAT_HIGH,
        })
        await _run_deck(graph, store, ev)

    # ② 低危事件 → 归档
    low = new_event("intel_report", "sensor", {"text": "例行巡逻无异常", "threat": 0.1})
    await _run_deck(graph, store, low)

    # ③ 人工批准/驳回（前 n-1 批准，第 n 条驳回）
    approved: List[str] = []
    rejected: List[str] = []
    for i in range(1, n_orders + 1):
        oid = f"o{i}"
        decision = i < n_orders
        approve_order(store, oid, decision)
        (approved if decision else rejected).append(oid)
        await _run_deck(graph, store, approval_event(oid, decision), entry_node="approve")

    orders = store.list_objects("order")
    return {
        "approved": approved,
        "rejected": rejected,
        "orders_status": {o["order_id"]: o.get("status") for o in orders},
        "records": store.count("record"),
    }


__all__ = ["ReplayStore", "export_timeline", "timeline_to_json", "run_scripted_scenario"]
