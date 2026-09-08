# -*- coding: utf-8 -*-
"""M1 领域建模验收：
- 工具已挂载（QueryUnit/QueryTarget/QueryOrder/QueryStock + 6 个动作）
- 剧本：scout（侦察）→ issue_order（生成待批准命令），均落 ontology
- 同一批工具能挂进 Agent 的 ToolRegistry
"""
import json

from agentorchestra.agents.simple_agent import SimpleAgent
from agentorchestra.capability.tools.registry import ToolRegistry

from app.core.mock_llm import MockLLM
from app.domain.schema import create_engine


def _seed(store):
    store.insert("unit", {"unit_id": "u1", "name": "甲编队", "side": "friendly",
                          "location": "A1", "status": "idle", "strength": 80})
    store.insert("target", {"target_id": "t1", "name": "敌方雷达站", "kind": "radar",
                            "side": "enemy", "threat": 0.8, "location": "B2"})


def _build():
    engine = create_engine()
    _seed(engine.object_store)
    registry = ToolRegistry()
    names = engine.mount(registry)
    return engine, registry, names


def test_tools_mounted():
    _, _, names = _build()
    expect = {"QueryUnit", "QueryTarget", "QueryOrder", "QueryStock",
              "scout", "issue_order", "approve", "execute_order",
              "resupply", "settle_round"}
    missing = expect - set(names)
    assert not missing, f"缺失工具: {missing}"


def test_scout_then_issue_order_scenario():
    engine, registry, _ = _build()

    # 1) 侦察
    r1 = registry.execute_tool("scout", json.dumps({"unit_id": "u1", "area": "A1"}))
    assert r1.status.value == "success", r1.error_info
    assert "甲编队" in r1.text

    # 2) 下达命令 → 生成待批准命令并落 ontology
    r2 = registry.execute_tool(
        "issue_order",
        json.dumps({"order_id": "o1", "kind": "strike", "unit_id": "u1", "target_id": "t1"}),
    )
    assert r2.status.value == "success", r2.error_info
    order = engine.object_store.get("order", "o1")
    assert order is not None
    assert order["approval"] == "pending"
    assert order["status"] == "pending"

    # 3) 未批准不能执行（规则在动作层拦截）
    r3 = registry.execute_tool("execute_order", json.dumps({"order_id": "o1"}))
    assert r3.status.value == "error"


def test_tools_visible_to_agent():
    engine, registry, _ = _build()
    agent = SimpleAgent(name="staff-agent", llm=MockLLM(), tool_registry=registry)
    tools = agent.list_tools()
    assert "scout" in tools and "issue_order" in tools
    assert "QueryUnit" in tools
