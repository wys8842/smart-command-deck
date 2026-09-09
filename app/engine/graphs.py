"""Graph 蓝图（M2）：最小研判图 entry → intel(Agent) → record。"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from agentorchestra.orchestration.orch.graph import Graph, Node, NodeContext, NodeOutput
from agentorchestra.orchestration.orch.nodes import FunctionalNode


class IntelAgentNode(Node):
    """研判 Agent 节点：执行 Agent 并把事件元数据传给下游（record 需要）。"""

    def __init__(self, agent_factory: Callable[[], Any], input_key: str = "task"):
        self._agent_factory = agent_factory
        self._input_key = input_key

    async def run(self, message: dict[str, Any], ctx: NodeContext) -> NodeOutput:
        agent = self._agent_factory()
        task = message.get(self._input_key, message)
        if hasattr(agent, "arun"):
            result = await agent.arun(str(task) if not isinstance(task, str) else task)
        else:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: agent.run(str(task) if not isinstance(task, str) else task)
            )
        return NodeOutput(
            result=result,
            data={
                "event": message.get("event", {}),
                "ev_id": message.get("ev_id"),
                "kind": message.get("kind"),
                "agent_type": type(agent).__name__,
            },
        )


def _fmt_task(event: Any) -> str:
    if isinstance(event, dict):
        kind = event.get("kind", "")
        source = event.get("source", "")
        payload = event.get("payload") or {}
    else:
        kind = event.kind
        source = event.source
        payload = event.payload or {}
    return (f"请研判以下事件并给出简要处置建议（1-3 句）。"
            f"类型={kind}，来源={source}，详情={payload}")


def passthrough_entry(message: dict, ctx: Any) -> NodeOutput:
    """事件入口：把消息转成可读任务串 + 保留事件元数据。"""
    ev = message.get("event", message)
    return NodeOutput.ok(
        result=_fmt_task(ev),
        event=ev,
        ev_id=ev.get("ev_id"),
        kind=ev.get("kind"),
        round=ev.get("round", 1),
    )


def record_event(store: Any) -> Callable[[dict, Any], NodeOutput]:
    """记录节点：把研判结论落 ontology record 对象。"""

    def _record(message: dict, ctx: Any) -> NodeOutput:
        event = message.get("event") or message
        store.insert("record", {
            "record_id": event.get("ev_id", "unknown"),
            "kind": event.get("kind") or "unknown",
            "source": event.get("source") or "unknown",
            "round": event.get("round", 1),
            "summary": message.get("task", ""),
            "detail": str(event),
        })
        return NodeOutput.ok(result=message.get("task", ""))

    return _record


def build_intel_graph(
    intel_agent_factory: Callable[[], Any],
    store: Any,
) -> Graph:
    """构造研判图：entry(事件) → intel(Agent 研判) → record(落库)。"""
    g = Graph()
    g.add_node("entry", FunctionalNode(passthrough_entry))
    g.add_node("intel", IntelAgentNode(agent_factory=intel_agent_factory, input_key="task"))
    g.add_node("record", FunctionalNode(record_event(store)))
    g.add_edge("entry", "intel")
    g.add_edge("intel", "record")
    return g


__all__ = ["IntelAgentNode", "build_intel_graph", "passthrough_entry", "record_event"]
