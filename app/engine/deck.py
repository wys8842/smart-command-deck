"""完整推演 DAG（M3）：entry → route(分级) → 低危归档 / 高危 建议→命令→人工批准→执行→结算。

HITL 续跑：高危事件首跑到 approve 后停下（order 保持 pending）；
指挥员批准后，投回 approval_result 事件并从 approve 节点重新进入，按 order.approval 决定执行/驳回。
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from agentorchestra.orchestration.orch.graph import Graph, NodeContext, NodeOutput
from agentorchestra.orchestration.orch.nodes import FunctionalNode

from app.engine.graphs import IntelAgentNode, passthrough_entry

THREAT_HIGH = 0.6


def _ev(message: dict[str, Any]) -> dict[str, Any]:
    return message.get("event") or {}


def nd(result: Any, **data: Any) -> NodeOutput:
    return NodeOutput.ok(result=result, **data)


def threat_of(store: Any, event: dict[str, Any]) -> float:
    payload = event.get("payload") or {}
    threat = payload.get("threat")
    if threat is None:
        target_id = payload.get("target_id")
        if target_id:
            target = store.get("target", target_id)
            if target is not None:
                threat = target.get("threat")
    return float(threat) if threat is not None else 0.5


def route_fn(store: Any) -> Callable[[dict, NodeContext], NodeOutput]:
    """分级路由：低危→record，高危→intel；结果以 route 字段驱动条件边。"""

    def _route(message: dict, ctx: NodeContext) -> NodeOutput:
        event = _ev(message)
        if event.get("kind") == "approval_result":
            label = "skip"
        else:
            label = "high" if threat_of(store, event) >= THREAT_HIGH else "low"
        return NodeOutput(result=label, route=label, data={"event": event})

    return _route


def archiver(store: Any) -> Callable[[dict, NodeContext], NodeOutput]:
    """低危事件归档。"""

    def _record(message: dict, ctx: NodeContext) -> NodeOutput:
        event = _ev(message)
        store.insert("record", {
            "record_id": event.get("ev_id", f"rec-{uuid.uuid4().hex[:8]}"),
            "kind": event.get("kind") or "low",
            "source": event.get("source") or "unknown",
            "round": event.get("round", 1),
            "summary": "低危事件已归档",
            "detail": str(event),
        })
        return nd("archived", event=event)

    return _record


def order_creator(store: Any) -> Callable[[dict, NodeContext], NodeOutput]:
    """高危研判后：生成一条待批准命令。"""

    def _create(message: dict, ctx: NodeContext) -> NodeOutput:
        event = _ev(message)
        payload = event.get("payload") or {}
        oid = payload.get("order_id") or f"ord-{uuid.uuid4().hex[:8]}"
        store.insert("order", {
            "order_id": oid,
            "kind": payload.get("kind", "strike"),
            "unit_id": payload.get("unit_id"),
            "target_id": payload.get("target_id"),
            "status": "pending",
            "approval": "pending",
            "params": str(payload),
        })
        return nd("order_created", order_id=oid, event=event)

    return _create


def approval_gate(store: Any) -> Callable[[dict, NodeContext], NodeOutput]:
    """审批门（HITL）：首跑待批则停；批准/驳回续跑时路由到执行或结算。"""

    def _gate(message: dict, ctx: NodeContext) -> NodeOutput:
        order_id = message.get("order_id") or _ev(message).get("payload", {}).get("order_id")
        order = store.get("order", order_id or "")
        if order is None:
            return NodeOutput(result="unknown_order", route=None, data={"event": _ev(message)})
        approval = order.get("approval")
        if approval == "approved":
            return NodeOutput(result="approved", route="approved",
                              data={"order_id": order_id, "event": _ev(message)})
        if approval == "rejected":
            return NodeOutput(result="rejected", route="rejected",
                              data={"order_id": order_id, "event": _ev(message)})
        return NodeOutput(result="pending_wait", route=None,
                          data={"order_id": order_id, "event": _ev(message)})

    return _gate


def executor(store: Any) -> Callable[[dict, NodeContext], NodeOutput]:
    """执行已批准命令，并直接结算落账（避免额外一跳）。"""

    def _exec(message: dict, ctx: NodeContext) -> NodeOutput:
        order_id = message.get("order_id")
        order = store.get("order", order_id or "")
        if order is None:
            return NodeOutput.fail("命令不存在")
        if order.get("approval") != "approved":
            return NodeOutput.fail("命令未批准，禁止执行")
        store.update("order", order_id, {"status": "executed"})
        store.insert("record", {
            "record_id": f"set-{order_id}",
            "kind": "settle",
            "source": "deck",
            "round": _ev(message).get("round", 1),
            "summary": f"order {order_id} executed",
            "detail": str(order),
        })
        return nd("executed", order_id=order_id)

    return _exec


def settler(store: Any) -> Callable[[dict, NodeContext], NodeOutput]:
    """结算：记录命令最终结果。"""

    def _settle(message: dict, ctx: NodeContext) -> NodeOutput:
        order_id = message.get("order_id")
        order = store.get("order", order_id or "")
        status = (order or {}).get("status", "unknown")
        store.insert("record", {
            "record_id": f"set-{order_id or uuid.uuid4().hex[:8]}",
            "kind": "settle",
            "source": "deck",
            "round": _ev(message).get("round", 1),
            "summary": f"order {order_id} {status}",
            "detail": str(order),
        })
        return nd("settled", order_id=order_id)

    return _settle


def build_deck_graph(
    intel_agent_factory: Callable[[], Any],
    store: Any,
) -> Graph:
    """构造完整推演图。

    approve 节点是 HITL 停顿点：
      - 高危首跑：order 保持 pending → approve 返回 route=None → 图正常结束；
      - 批准后：以 entry_node="approve" + approval_result 事件续跑 → approved 分支。
    """
    g = Graph()
    g.add_node("entry", FunctionalNode(passthrough_entry))
    g.add_node("route", FunctionalNode(route_fn(store)))
    g.add_node("record", FunctionalNode(archiver(store)))
    g.add_node("intel", IntelAgentNode(intel_agent_factory, input_key="task"))
    g.add_node("create", FunctionalNode(order_creator(store)))
    g.add_node("approve", FunctionalNode(approval_gate(store)))
    g.add_node("execute", FunctionalNode(executor(store)))
    g.add_node("settle", FunctionalNode(settler(store)))

    g.add_edge("entry", "route")
    g.add_edge("route", "record", when="low")
    g.add_edge("route", "intel", when="high")
    g.add_edge("intel", "create")
    g.add_edge("create", "approve")
    g.add_edge("approve", "execute", when="approved")
    g.add_edge("approve", "settle", when="rejected")
    return g


__all__ = [
    "approval_gate",
    "archiver",
    "build_deck_graph",
    "executor",
    "order_creator",
    "route_fn",
    "settler",
    "threat_of",
]
