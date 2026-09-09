# -*- coding: utf-8 -*-
"""Capability 注册表验收：战例能力装配 + 召回工具 + 遥测能力。"""
import json

from agentorchestra.agents.simple_agent import SimpleAgent
from agentorchestra.capability.tools.registry import ToolRegistry

from app.core.capabilities import (
    BattleExperienceCapability,
    build_app_capabilities,
    install_app_capabilities,
)
from app.core.mock_llm import MockLLM
from app.domain.experience import ExperienceStore


def _agent(registry):
    return SimpleAgent(name="intel", llm=MockLLM(), tool_registry=registry)


def test_capability_registers_recall_tool(tmp_path):
    exp = ExperienceStore(path=str(tmp_path / "exp.jsonl"))
    exp.remember_case("intel_report", "敌方雷达异常", "派无人机核实")
    registry = ToolRegistry()
    agent = _agent(registry)

    install_app_capabilities(agent, experience=exp)

    assert agent._capability_state.get("experience_store") is exp
    assert "recall_battle_case" in registry.list_tools()

    r = registry.execute_tool("recall_battle_case",
                              json.dumps({"query": "敌方雷达异常", "top_k": 3}))
    assert r.status.value == "success"
    assert "派无人机核实" in r.text


def test_capability_disabled_without_store():
    reg = build_app_capabilities(experience=None, telemetry=False)
    assert reg.get("battle_experience").store is None


def test_telemetry_capability_installs():
    from agentorchestra.runtime.capabilities import CapabilityContext

    from app.core.capabilities import TelemetryCapability
    from agentorchestra.core.config import Config

    ctx = CapabilityContext(config=Config(), llm=MockLLM(), tool_registry=None,
                            logger_name="t", name="t", state={})
    TelemetryCapability().install(ctx)
    assert ctx.state.get("telemetry_enabled") is True
