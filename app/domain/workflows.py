# -*- coding: utf-8 -*-
"""业务工作流（2）：用 Ontology WorkflowEngine 编排多步动作。

- strike_sequence：侦察 → 下达命令(待批) → 回合结算
- resupply_sequence：补给 → 回合结算

动作仍由 ontology ActionType 提供；工作流只负责"编排与顺序"。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from agentorchestra.ontology import ActionType, StepNode, Workflow
from agentorchestra.tools.base import ToolParameter

STRIKE_WORKFLOW = "strike_sequence"
RESUPPLY_WORKFLOW = "resupply_sequence"


def build_workflows(engine: Any) -> List[str]:
    """注册工作流到 engine.workflow，并返回名称列表。"""
    strike = Workflow(STRIKE_WORKFLOW, description="侦察→下达命令→回合结算")
    strike.add_node(StepNode("scout", "scout",
                             {"unit_id": "u1", "area": "A1"}), entry=True)
    strike.add_node(StepNode("issue", "issue_order",
                             {"order_id": "wf-order", "kind": "strike",
                              "unit_id": "u1", "target_id": "t1"},
                             depends_on=["scout"]))
    strike.add_node(StepNode("settle", "settle_round", {"round": 1},
                             depends_on=["issue"]))
    engine.workflow.register_workflow(strike)

    resupply = Workflow(RESUPPLY_WORKFLOW, description="补给→回合结算")
    resupply.add_node(StepNode("resupply", "resupply",
                               {"stock_id": "s1", "qty": 10}), entry=True)
    resupply.add_node(StepNode("settle", "settle_round", {"round": 1},
                               depends_on=["resupply"]))
    engine.workflow.register_workflow(resupply)

    return [STRIKE_WORKFLOW, RESUPPLY_WORKFLOW]


def register_workflow_action(engine: Any) -> None:
    """注册 `run_workflow` 动作工具：让 Agent 能触发工作流。"""

    def _run(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name", "")
        raw = params.get("params_json") or "{}"
        try:
            init = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"params_json 非法 JSON: {e}") from e
        return engine.workflow.run(name, initial_params=init, ctx=ctx)

    engine.register_action(ActionType(
        "run_workflow",
        parameters=[
            ToolParameter(name="name", type="string",
                          description="工作流名，如 strike_sequence / resupply_sequence",
                          required=True),
            ToolParameter(name="params_json", type="string",
                          description="初始参数 JSON（可选）", required=False),
        ],
        execute_fn=_run,
        description="触发一个 ontology 工作流（多步动作编排）",
    ))


__all__ = [
    "STRIKE_WORKFLOW", "RESUPPLY_WORKFLOW",
    "build_workflows", "register_workflow_action",
]
