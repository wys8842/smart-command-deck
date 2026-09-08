"""app.domain.schema —— ontology 领域模型（M1）。

对象：unit / target / order / stock
动作：scout / issue_order / approve / execute_order / resupply / settle_round
"""
from __future__ import annotations

from typing import Any, List, Optional

from agentorchestra.ontology import (
    ActionType,
    GraphStore,
    ObjectStore,
    ObjectType,
    OntologyEngine,
    SecurityContext,
)
from agentorchestra.tools.base import ToolParameter

# ==================== 对象类型 ====================

Unit = ObjectType(
    "unit", "unit_id",
    properties=[
        ToolParameter(name="unit_id", type="string", description="单位ID", required=True),
        ToolParameter(name="name", type="string", description="名称", required=True),
        ToolParameter(name="side", type="string", description="阵营 friendly/enemy", required=True),
        ToolParameter(name="location", type="string", description="位置/区域", required=True),
        ToolParameter(name="status", type="string", description="状态 idle/moving/scouted", required=False, default="idle"),
        ToolParameter(name="strength", type="number", description="兵力/完整度 0-100", required=False, default=100.0),
    ],
    display_name="单位",
)

Target = ObjectType(
    "target", "target_id",
    properties=[
        ToolParameter(name="target_id", type="string", description="目标ID", required=True),
        ToolParameter(name="name", type="string", description="名称", required=True),
        ToolParameter(name="kind", type="string", description="目标类型", required=True),
        ToolParameter(name="side", type="string", description="阵营", required=True),
        ToolParameter(name="threat", type="number", description="威胁度 0-1", required=False, default=0.5),
        ToolParameter(name="location", type="string", description="位置", required=False),
    ],
    display_name="目标",
)

Order = ObjectType(
    "order", "order_id",
    properties=[
        ToolParameter(name="order_id", type="string", description="命令ID", required=True),
        ToolParameter(name="kind", type="string", description="命令类型 strike/move/resupply", required=True),
        ToolParameter(name="unit_id", type="string", description="执行单位", required=False),
        ToolParameter(name="target_id", type="string", description="目标", required=False),
        ToolParameter(name="status", type="string", description="状态 pending/approved/executed", required=False, default="pending"),
        ToolParameter(name="approval", type="string", description="审批状态 pending/approved/rejected", required=False, default="pending"),
        ToolParameter(name="params", type="string", description="附加参数(JSON)", required=False),
    ],
    display_name="命令",
)

Stock = ObjectType(
    "stock", "stock_id",
    properties=[
        ToolParameter(name="stock_id", type="string", description="账目ID", required=True),
        ToolParameter(name="kind", type="string", description="弹药/油料类型", required=True),
        ToolParameter(name="qty", type="number", description="数量", required=True),
    ],
    display_name="账目",
)

Record = ObjectType(
    "record", "record_id",
    properties=[
        ToolParameter(name="record_id", type="string", description="记录ID(=ev_id)", required=True),
        ToolParameter(name="kind", type="string", description="事件类型", required=True),
        ToolParameter(name="source", type="string", description="事件来源", required=False),
        ToolParameter(name="round", type="integer", description="回合号", required=False, default=1),
        ToolParameter(name="summary", type="string", description="研判结论", required=False),
        ToolParameter(name="detail", type="string", description="原始载荷(JSON)", required=False),
    ],
    display_name="研判记录",
)


# ==================== 执行函数（M1 基础版；事务/权限在 M4 接入） ====================

def _store(ctx: dict[str, Any]) -> ObjectStore:
    store = (ctx or {}).get("object_store")
    if store is None:
        raise RuntimeError("ctx 缺少 object_store")
    return store


def do_scout(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    store = _store(ctx)
    unit = store.get("unit", params.get("unit_id", ""))
    if unit is None:
        raise ValueError(f"单位不存在: {params.get('unit_id')}")
    report = {
        "report": f"侦察完成：{unit.get('name')} @ {params.get('area', unit.get('location'))}",
        "unit": unit,
    }
    return report


def do_issue_order(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    store = _store(ctx)
    oid = params.get("order_id", "")
    if not oid:
        raise ValueError("缺少 order_id")
    obj: dict[str, Any] = {
        "order_id": oid,
        "kind": params.get("kind", "strike"),
        "unit_id": params.get("unit_id"),
        "target_id": params.get("target_id"),
        "status": "pending",
        "approval": "pending",
        "params": str({k: v for k, v in params.items() if k not in ("order_id", "kind", "unit_id", "target_id")}),
    }
    store.insert("order", obj)
    return obj


def do_approve(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    store = _store(ctx)
    oid = params.get("order_id", "")
    order = store.get("order", oid)
    if order is None:
        raise ValueError(f"命令不存在: {oid}")
    decision = params.get("approve", True)
    approval = "approved" if decision in (True, "true", "yes") else "rejected"
    store.update("order", oid, {"approval": approval, "status": approval})
    return {"order_id": oid, "approval": approval}


def do_execute_order(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    store = _store(ctx)
    oid = params.get("order_id", "")
    order = store.get("order", oid)
    if order is None:
        raise ValueError(f"命令不存在: {oid}")
    if order.get("approval") != "approved":
        raise ValueError("命令未获批准，禁止执行")
    store.update("order", oid, {"status": "executed"})
    return {"order_id": oid, "status": "executed"}


def do_resupply(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    store = _store(ctx)
    sid = params.get("stock_id", "")
    qty = float(params.get("qty", 0))
    rec = store.get("stock", sid)
    if rec is None:
        raise ValueError(f"账目不存在: {sid}")
    store.update("stock", sid, {"qty": float(rec.get("qty", 0)) + qty})
    return {"stock_id": sid, "qty": float(rec.get("qty", 0)) + qty}


def do_settle_round(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    store = _store(ctx)
    round_no = params.get("round", 1)
    return {"round": round_no, "summary": f"第 {round_no} 回合结算完成", "orders": store.count("order")}


# ==================== 动作类型 ====================

def _param(name: str, typ: str, desc: str, required: bool = False) -> ToolParameter:
    return ToolParameter(name=name, type=typ, description=desc, required=required)


def build_actions() -> dict[str, ActionType]:
    actions = [
        ActionType(
            "scout",
            parameters=[_param("unit_id", "string", "要侦察的单位ID", True),
                        _param("area", "string", "侦察区域", False)],
            execute_fn=do_scout,
            display_name="侦察",
        ),
        ActionType(
            "issue_order",
            parameters=[_param("order_id", "string", "命令ID", True),
                        _param("kind", "string", "命令类型", True),
                        _param("unit_id", "string", "执行单位ID", True),
                        _param("target_id", "string", "目标ID", True)],
            execute_fn=do_issue_order,
            display_name="下达命令（待批准）",
        ),
        ActionType(
            "approve",
            parameters=[_param("order_id", "string", "命令ID", True),
                        _param("approve", "boolean", "批准/驳回", False)],
            execute_fn=do_approve,
            display_name="批准/驳回命令",
        ),
        ActionType(
            "execute_order",
            parameters=[_param("order_id", "string", "命令ID", True)],
            execute_fn=do_execute_order,
            display_name="执行命令",
        ),
        ActionType(
            "resupply",
            parameters=[_param("stock_id", "string", "账目ID", True),
                        _param("qty", "number", "补给数量", True)],
            execute_fn=do_resupply,
            display_name="补给",
        ),
        ActionType(
            "settle_round",
            parameters=[_param("round", "integer", "回合号", True)],
            execute_fn=do_settle_round,
            display_name="回合结算",
        ),
    ]
    return {a.api_name: a for a in actions}


def create_engine(
    store: Optional[ObjectStore] = None,
    security_ctx: Optional[SecurityContext] = None,
    principal: str = "staff",
    roles: Optional[List[str]] = None,
    permissions: Optional[List[tuple]] = None,
) -> OntologyEngine:
    """构建领域引擎：注册全部对象类型与动作。

    Args:
        store: 复用外部 ObjectStore（测试注入）；None 时自建内存 store。
        security_ctx: 安全上下文；None 时按 principal/roles 构造。
        permissions: 显式授权列表 [(role, resource, action), ...]；
            None 时默认对 roles 全放行（M1–M3 兼容；M4 起用显式矩阵收紧）。
    """
    object_store = store or ObjectStore(graph=GraphStore())
    sec = security_ctx or SecurityContext(principal=principal, roles=roles or ["staff"])
    engine = OntologyEngine(object_store=object_store, security_ctx=sec)
    for t in (Unit, Target, Order, Stock, Record):
        engine.register_object_type(t)
    for action in build_actions().values():
        engine.register_action(action)
    if permissions is None:
        engine.allow(roles or [principal], resource="*", action="*")
    else:
        for role, resource, action in permissions:
            engine.allow([role], resource=resource, action=action)
    return engine


__all__ = [
    "Order",
    "Record",
    "Stock",
    "Target",
    "Unit",
    "build_actions",
    "create_engine",
]
