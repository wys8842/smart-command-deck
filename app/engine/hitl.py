"""HITL 人工批准入口（M3）：批准/驳回待决命令，并支持“续跑事件”驱动下游。"""
from __future__ import annotations

import json
from typing import Any

from app.engine.event_bus import Event, new_event


def approve_order(store: Any, order_id: str, decision: bool) -> dict[str, Any]:
    """人工批准/驳回命令（更新 store 中 order.approval）。"""
    order = store.get("order", order_id)
    if order is None:
        raise ValueError(f"命令不存在: {order_id}")
    approval = "approved" if decision else "rejected"
    store.update("order", order_id, {"approval": approval, "status": approval})
    return {"order_id": order_id, "approval": approval}


def pending_orders(store: Any) -> list[dict[str, Any]]:
    """列出待人工审批的命令。"""
    return [o for o in store.list_objects("order") if o.get("approval") == "pending"]


def approval_event(order_id: str, decision: bool, source: str = "commander") -> Event:
    """构造批准续跑事件（投回 EventBus，由 deck 从 approve 节点继续）。"""
    return new_event(
        kind="approval_result",
        source=source,
        payload={"order_id": order_id, "decision": decision},
    )


def payload_to_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


__all__ = ["approval_event", "approve_order", "pending_orders"]
