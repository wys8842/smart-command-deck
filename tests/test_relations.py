# -*- coding: utf-8 -*-
"""GraphStore 关系推理验收：链接写入 / 邻域态势 / 工具化查询。"""
import json

from agentorchestra.agents.simple_agent import SimpleAgent
from agentorchestra.capability.tools.registry import ToolRegistry

from app.core.capabilities import install_app_capabilities
from app.core.mock_llm import MockLLM
from app.domain.relations import situation
from app.domain.schema import create_engine


def test_seed_and_neighborhood():
    engine = create_engine()
    store = engine.object_store
    from app.domain.relations import seed_scenario

    seed_scenario(store)

    # 直接链接
    links = store.get_links("unit", "u1")
    targets = {(l["link_name"], l["to_type"], l["to_pk"]) for l in links}
    assert ("adjacent_to", "unit", "u2") in targets
    assert ("threatened_by", "target", "t1") in targets

    # 二跳邻域（u1 → u2 → u3）
    data = situation(store, "u1", depth=2)
    reachable = {(n["to_type"], n["to_pk"]) for n in data["neighbors"]}
    assert ("unit", "u2") in reachable
    assert ("unit", "u3") in reachable
    assert ("target", "t1") in reachable


def test_query_unit_links_mode():
    engine = create_engine()
    store = engine.object_store
    from app.domain.relations import seed_scenario

    seed_scenario(store)
    reg = ToolRegistry()
    engine.mount(reg)

    r = reg.execute_tool("QueryUnit", json.dumps({"mode": "links", "pk": "u1"}))
    assert r.status.value == "success", r.error_info
    assert "u2" in r.text


def test_situation_capability_tool():
    engine = create_engine()
    store = engine.object_store
    from app.domain.relations import seed_scenario

    seed_scenario(store)
    reg = ToolRegistry()
    agent = SimpleAgent(name="intel", llm=MockLLM(), tool_registry=reg)
    install_app_capabilities(agent, situation_store=store)

    assert "query_situation" in reg.list_tools()
    r = reg.execute_tool("query_situation", json.dumps({"unit_id": "u1", "depth": 2}))
    assert r.status.value == "success"
    assert "t1" in r.text
