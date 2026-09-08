# -*- coding: utf-8 -*-
"""复盘（M5）：导出推演 timeline JSON + 一键剧本运行器。

- export_timeline(store)：从 ontology 导出 orders/records（按回合归纳）。
- run_scripted_scenario(store, ...)：跑一次端到端剧本，返回汇总供验收/复盘。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from agentorchestra.orchestration.orch.scheduler import GraphScheduler

from app.engine.deck import build_deck_graph
from app.engine.event_bus import new_event
from app.engine.hitl import approval_event, approve_order
from app.engine.pump import event_message

THREAT_HIGH = 0.9


def export_timeline(store: Any) -> Dict[str, Any]:
    """导出某局的 orders + records 成可回放 JSON。"""
    orders = store.list_objects("order")
    records = store.list_objects("record")
    return {
        "summary": {
            "orders": len(orders),
            "records": len(records),
            "settles": sum(1 for r in records if r["kind"] == "settle"),
        },
        "orders": sorted(orders, key=lambda o: str(o.get("order_id", ""))),
        "records": sorted(records, key=lambda r: str(r.get("record_id", ""))),
    }


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


__all__ = ["export_timeline", "timeline_to_json", "run_scripted_scenario"]
