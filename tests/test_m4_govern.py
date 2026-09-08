# -*- coding: utf-8 -*-
"""M4 账目+权限+审计验收：
- 事务补偿：resupply_stock 后 fail → 库存自动回滚
- RBAC：operator 不能 approve（ACCESS_DENIED），commander 可以
- 审计：通过 ontology 动作工具执行 approve，AuditManager 可查
"""
import json

from agentorchestra.ontology import SecurityContext
from agentorchestra.capability.tools.registry import ToolRegistry

from app.domain.ledger import read_qty, register_ledger, set_qty, run_transaction
from app.domain.schema import create_engine


def _seed(store):
    store.insert("stock", {"stock_id": "s1", "kind": "ammo", "qty": 100.0})
    store.insert("order", {"order_id": "o1", "kind": "strike", "status": "pending",
                           "approval": "pending", "params": "{}"})


# ---------- 1) 事务补偿 ----------

def test_resupply_rollback_on_failure():
    engine = create_engine()
    store = engine.object_store
    _seed(store)
    register_ledger(engine.transaction, store)

    before = read_qty(store, "s1")
    result = run_transaction(engine.transaction, [
        {"action": "resupply_stock", "params": {"stock_id": "s1", "qty": 10}},
        {"action": "fail_ledger", "params": {"reason": "调度下游失败"}},
    ])

    assert result["success"] is False
    assert "fail_ledger" in result["failed"]
    assert "resupply_stock" in result["compensated"]
    assert read_qty(store, "s1") == before  # 已自动回滚


def test_resupply_commit_when_all_ok():
    engine = create_engine()
    store = engine.object_store
    _seed(store)
    register_ledger(engine.transaction, store)

    before = read_qty(store, "s1")
    result = run_transaction(engine.transaction, [
        {"action": "resupply_stock", "params": {"stock_id": "s1", "qty": 10}},
    ])
    assert result["success"] is True
    assert read_qty(store, "s1") == before + 10


# ---------- 2) RBAC ----------

def _mount_approve(engine):
    reg = ToolRegistry()
    names = engine.mount(reg)
    assert "approve" in names
    return reg


def test_operator_cannot_approve():
    engine = create_engine(
        security_ctx=SecurityContext(principal="op1", roles=["operator"]),
        permissions=[("operator", "*", "scout"),
                     ("operator", "*", "issue_order")],
    )
    store = engine.object_store
    _seed(store)
    reg = _mount_approve(engine)

    r = reg.execute_tool("approve", json.dumps({"order_id": "o1", "approve": True}))
    assert r.status.value == "error"
    assert r.error_info.get("code") == "ACCESS_DENIED"


def test_commander_can_approve_and_audited():
    engine = create_engine(
        security_ctx=SecurityContext(principal="cmd1", roles=["commander"]),
        permissions=[("commander", "*", "*")],
    )
    store = engine.object_store
    _seed(store)
    reg = _mount_approve(engine)

    r = reg.execute_tool("approve", json.dumps({"order_id": "o1", "approve": True}))
    assert r.status.value == "success", r.error_info
    assert store.get("order", "o1")["approval"] == "approved"

    # 审计可查
    entries = engine.audit.query(resource="approve", principal="cmd1")
    assert entries, "approve 应写入审计"
    assert engine.audit.count() >= 1
    assert engine.stats()["audit_entries"] >= 1


def test_audit_records_denied_too():
    engine = create_engine(
        security_ctx=SecurityContext(principal="op1", roles=["operator"]),
        permissions=[("operator", "*", "scout")],
    )
    store = engine.object_store
    _seed(store)
    reg = _mount_approve(engine)
    reg.execute_tool("approve", json.dumps({"order_id": "o1", "approve": True}))

    denied = engine.audit.query(resource="approve")
    assert any(not e["success"] for e in denied), "被拒的尝试也要留痕"
