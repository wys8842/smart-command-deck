# -*- coding: utf-8 -*-
"""应用级 Capability：用框架 CapabilityRegistry 统一装配横切能力。

- BattleExperienceCapability：把战例库装入 agent 能力状态；若 agent 有 ToolRegistry，
  额外注册 `recall_battle_case` 工具（Agent 可主动召回历史战例）。
- TelemetryCapability：开启 Prometheus（可选 OTLP），幂等。
"""
from __future__ import annotations

from typing import Any, Optional

from agentorchestra.capability.tools.base import Tool, ToolParameter
from agentorchestra.capability.tools.response import ToolResponse
from agentorchestra.runtime.capabilities import (
    Capability,
    CapabilityContext,
    CapabilityRegistry,
)


class RecallBattleCaseTool(Tool):
    """召回相似历史战例的工具。"""

    def __init__(self, store: Any):
        self.store = store
        super().__init__(name="recall_battle_case", description="召回相似历史战例供研判参考",
                         expandable=False, read_only=True)

    def get_parameters(self):
        return [
            ToolParameter(name="query", type="string", description="事件/态势描述", required=True),
            ToolParameter(name="top_k", type="integer", description="返回条数", required=False),
        ]

    def run(self, parameters):
        query = parameters.get("query", "")
        top_k = int(parameters.get("top_k", 3) or 3)
        block = self.store.recall_block(query, top_k=top_k)
        return ToolResponse.success(text=block or "无相关历史战例")


class BattleExperienceCapability(Capability):
    """战例能力：装配战例库，并按需注册召回工具。"""

    name = "battle_experience"

    def __init__(self, store: Optional[Any]):
        self.store = store

    def is_enabled(self, ctx: CapabilityContext) -> bool:
        return self.store is not None

    def install(self, ctx: CapabilityContext) -> None:
        ctx.state["experience_store"] = self.store
        if ctx.tool_registry is not None:
            ctx.tool_registry.register_tool(RecallBattleCaseTool(self.store))


class TelemetryCapability(Capability):
    """可观测能力：开启 Prometheus 指标（可选 OTLP）。"""

    name = "telemetry"

    def __init__(self, enable_otel: bool = False, service_name: str = "smart-command-deck"):
        self.enable_otel = enable_otel
        self.service_name = service_name

    def is_enabled(self, ctx: CapabilityContext) -> bool:
        return True

    def install(self, ctx: CapabilityContext) -> None:
        try:
            from agentorchestra.components import Components

            Components.enable_prometheus()
            if self.enable_otel:
                from app.core.tracing import init_otel

                init_otel(self.service_name)
            ctx.state["telemetry_enabled"] = True
        except Exception:  # noqa: BLE001
            pass


def build_app_capabilities(experience: Optional[Any] = None,
                           telemetry: bool = True) -> CapabilityRegistry:
    """构建应用级 Capability 注册表。"""
    reg = CapabilityRegistry()
    reg.register(BattleExperienceCapability(experience))
    if telemetry:
        reg.register(TelemetryCapability())
    return reg


def install_app_capabilities(agent: Any, experience: Optional[Any] = None,
                             telemetry: bool = False) -> None:
    """把应用能力安装到某个 Agent（复用其 config/llm/registry/state）。"""
    try:
        state = getattr(agent, "_capability_state", None)
        if state is None:
            state = {}
        ctx = CapabilityContext(
            config=agent.config,
            llm=agent.llm,
            tool_registry=getattr(agent, "tool_registry", None),
            logger_name=f"app.{getattr(agent, 'name', 'agent')}.capability",
            name=getattr(agent, "name", "agent"),
            state=state,
        )
        build_app_capabilities(experience=experience, telemetry=telemetry).install_all(ctx)
    except Exception:  # noqa: BLE001
        pass


__all__ = [
    "RecallBattleCaseTool",
    "BattleExperienceCapability",
    "TelemetryCapability",
    "build_app_capabilities",
    "install_app_capabilities",
]
