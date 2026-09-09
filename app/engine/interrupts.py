# -*- coding: utf-8 -*-
"""① HITL 统一到框架 state.Interrupt。

- 待批命令 → 生成 pending Interrupt（reason=order_approval）
- 指挥员批准 → resolve_interrupt(response={"approve": bool})
- InterruptResumer 轮询到 RESUMED → handler 更新 order 并入队续跑事件
"""
from __future__ import annotations

import uuid
from typing import Any, List, Optional

from agentorchestra.orchestration.state.interrupt import Interrupt

REASON_APPROVAL = "order_approval"


async def ensure_interrupts(store: Any, state_store: Any, thread_id: str) -> List[Interrupt]:
    """为所有 pending 命令补齐 Interrupt（幂等：同一 order 只建一个）。"""
    if state_store is None or not hasattr(state_store, "list_interrupts"):
        return []
    try:
        existing = await state_store.list_interrupts(status="pending", thread_id=thread_id)
    except Exception:  # noqa: BLE001
        existing = []
    have = {i.payload.get("order_id") for i in existing if i.reason == REASON_APPROVAL}

    created: List[Interrupt] = []
    for order in store.list_objects("order"):
        if order.get("approval") != "pending":
            continue
        oid = order.get("order_id")
        if oid in have:
            continue
        intr = Interrupt(
            token=f"appr-{uuid.uuid4().hex[:12]}",
            thread_id=thread_id,
            checkpoint_id="",
            reason=REASON_APPROVAL,
            payload={"order_id": oid},
        )
        await state_store.create_interrupt(intr)
        created.append(intr)
    return created


async def list_pending(state_store: Any, thread_id: Optional[str] = None) -> List[Interrupt]:
    if state_store is None or not hasattr(state_store, "list_interrupts"):
        return []
    try:
        return await state_store.list_interrupts(status="pending", thread_id=thread_id)
    except Exception:  # noqa: BLE001
        return []


async def find_pending_for_order(state_store: Any, order_id: str,
                                 thread_id: Optional[str] = None) -> Optional[Interrupt]:
    for intr in await list_pending(state_store, thread_id):
        if intr.reason == REASON_APPROVAL and intr.payload.get("order_id") == order_id:
            return intr
    return None


async def resolve_approval(state_store: Any, order_id: str, decision: bool,
                           thread_id: Optional[str] = None) -> Optional[str]:
    """按 order 找到 pending interrupt 并 resolve；返回 token 或 None。"""
    intr = await find_pending_for_order(state_store, order_id, thread_id)
    if intr is None:
        return None
    await state_store.resolve_interrupt(intr.token, {"approve": decision})
    # SLO：审批等待时长（从 interrupt 创建到人工决策）
    try:
        from datetime import datetime

        from app.core.tracing import observe

        wait = (datetime.now() - intr.created_at).total_seconds()
        observe("deck_approval_wait_seconds", max(wait, 0.0),
                {"decision": "approve" if decision else "reject"})
    except Exception:  # noqa: BLE001
        pass
    return intr.token


def approval_resume_handler(store: Any, bus: Any, thread_id: str = "default"):
    """InterruptResumer 的 handler：order 落审批 + 入队续跑事件。"""
    from app.engine.hitl import approval_event, approve_order

    async def _handler(token: str, response: dict, intr: Interrupt) -> None:
        order_id = intr.payload.get("order_id")
        decision = bool(response.get("approve", True))
        approve_order(store, order_id, decision)
        bus.enqueue(approval_event(order_id, decision))

    return _handler


__all__ = [
    "REASON_APPROVAL", "ensure_interrupts", "list_pending",
    "find_pending_for_order", "resolve_approval", "approval_resume_handler",
]
