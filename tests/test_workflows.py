# -*- coding: utf-8 -*-
"""2) Ontology WorkflowEngine 验收：多步工作流编排 + run_workflow 工具。"""
import json

from agentorchestra.capability.tools.registry import ToolRegistry

from app.domain.schema import create_engine
from app.domain.workflows import RESUPPLY_WORKFLOW, STRIKE_WORKFLOW


def _seed(store):
    store.insert("unit", {"unit_id": "u1", "name": "甲编队", "side": "friendly",
                          "location": "A1", "status": "idle", "strength": 80})
    store.insert("target", {"target_id": "t1", "name": "敌方雷达站", "kind": "radar",
                            "side": "enemy", "threat": 0.8, "location": "B2"})
    store.insert("stock", {"stock_id": "s1", "kind": "ammo", "qty": 100.0})


def test_workflows_registered():
    engine = create_engine()
    names = engine.workflow.list_workflows()
    assert STRIKE_WORKFLOW in names
    assert RESUPPLY_WORKFLOW in names


def test_strike_workflow_creates_order_and_settles():
    engine = create_engine()
    store = engine.object_store
    _seed(store)

    res = engine.workflow.run(STRIKE_WORKFLOW, ctx={"object_store": store})
    assert res["success"] is True, res.get("errors")
    assert store.get("order", "wf-order") is not None
    assert any(r["kind"] == "settle" for r in store.list_objects("record"))


def test_resupply_workflow_updates_stock():
    engine = create_engine()
    store = engine.object_store
    _seed(store)

    res = engine.workflow.run(RESUPPLY_WORKFLOW, ctx={"object_store": store})
    assert res["success"] is True, res.get("errors")
    assert store.get("stock", "s1")["qty"] == 110.0


def test_run_workflow_tool():
    engine = create_engine()
    store = engine.object_store
    _seed(store)
    reg = ToolRegistry()
    names = engine.mount(reg)
    assert "run_workflow" in names

    r = reg.execute_tool("run_workflow", json.dumps(
        {"name": RESUPPLY_WORKFLOW, "params_json": "{}"}))
    assert r.status.value == "success", r.error_info
    assert store.get("stock", "s1")["qty"] == 110.0
