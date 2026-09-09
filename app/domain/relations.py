# -*- coding: utf-8 -*-
"""GraphStore 关系推理：敌我/相邻/威胁链接 + 邻域态势查询。

- seed_scenario：写入演示单位/目标并建立链接（双向，便于查询）。
- situation：BFS 邻域态势（含链路与深度）。
- SituationQueryTool：把态势查询暴露为 Agent 工具。
"""
from __future__ import annotations

from typing import Any, Dict, List

from agentorchestra.capability.tools.base import Tool, ToolParameter
from agentorchestra.capability.tools.response import ToolResponse


def seed_scenario(store: Any) -> Dict[str, int]:
    """写入演示数据 + 关系链接。"""
    units = [
        {"unit_id": "u1", "name": "甲编队", "side": "friendly", "location": "A1",
         "status": "idle", "strength": 80},
        {"unit_id": "u2", "name": "乙编队", "side": "friendly", "location": "A2",
         "status": "idle", "strength": 90},
        {"unit_id": "u3", "name": "丙编队", "side": "friendly", "location": "A3",
         "status": "idle", "strength": 70},
    ]
    targets = [
        {"target_id": "t1", "name": "敌方雷达站", "kind": "radar", "side": "enemy",
         "threat": 0.8, "location": "B1"},
        {"target_id": "t2", "name": "敌方导弹阵地", "kind": "missile", "side": "enemy",
         "threat": 0.9, "location": "B2"},
    ]
    for u in units:
        store.insert("unit", u)
    for t in targets:
        store.insert("target", t)
    store.insert("stock", {"stock_id": "s1", "kind": "ammo", "qty": 100.0})

    links = [
        ("unit", "u1", "adjacent_to", "unit", "u2"),
        ("unit", "u2", "adjacent_to", "unit", "u1"),
        ("unit", "u2", "adjacent_to", "unit", "u3"),
        ("unit", "u3", "adjacent_to", "unit", "u2"),
        ("unit", "u1", "supports", "unit", "u2"),
        ("target", "t1", "threatens", "unit", "u1"),
        ("unit", "u1", "threatened_by", "target", "t1"),
        ("target", "t1", "threatens", "unit", "u2"),
        ("unit", "u2", "threatened_by", "target", "t1"),
        ("target", "t2", "threatens", "unit", "u3"),
        ("unit", "u3", "threatened_by", "target", "t2"),
        ("target", "t1", "near", "unit", "u2"),
    ]
    for from_type, from_pk, link, to_type, to_pk in links:
        store.create_link(from_type, from_pk, link, to_type, to_pk)
    return {"units": len(units), "targets": len(targets), "links": len(links)}


def situation(store: Any, unit_id: str, depth: int = 2) -> Dict[str, Any]:
    """从某单位出发的邻域态势（BFS，按链接类型）。"""
    start = ("unit", unit_id)
    seen = {start: 0}
    frontier: List[tuple] = [(*start, 0)]
    neighbors: List[Dict[str, Any]] = []

    while frontier:
        node_type, pk, d = frontier.pop(0)
        if d >= depth:
            continue
        for link in store.get_links(node_type, pk):
            key = (link["to_type"], link["to_pk"])
            neighbors.append({
                "from": f"{node_type}:{pk}",
                "link": link["link_name"],
                "to_type": link["to_type"],
                "to_pk": link["to_pk"],
                "depth": d + 1,
            })
            if key not in seen:
                seen[key] = d + 1
                frontier.append((*key, d + 1))

    return {
        "unit": store.get("unit", unit_id),
        "neighbors": neighbors,
        "count": len(neighbors),
    }


def format_situation(data: Dict[str, Any]) -> str:
    unit = data.get("unit") or {}
    lines = [f"单位 {unit.get('unit_id')}({unit.get('name')}) 邻域态势："]
    for n in data.get("neighbors", []):
        lines.append(f"  [{n['link']}] {n['from']} -> {n['to_type']}:{n['to_pk']} (d={n['depth']})")
    if not data.get("neighbors"):
        lines.append("  （无关联）")
    return "\n".join(lines)


class SituationQueryTool(Tool):
    """邻域态势查询工具。"""

    def __init__(self, store: Any):
        self.store = store
        super().__init__(name="query_situation", description="查询某单位的邻域态势（相邻/威胁等）",
                         expandable=False, read_only=True)

    def get_parameters(self):
        return [
            ToolParameter(name="unit_id", type="string", description="单位ID", required=True),
            ToolParameter(name="depth", type="integer", description="查询深度(默认2)", required=False),
        ]

    def run(self, parameters):
        unit_id = parameters.get("unit_id", "")
        depth = int(parameters.get("depth", 2) or 2)
        data = situation(self.store, unit_id, depth=depth)
        return ToolResponse.success(text=format_situation(data), data=data)


def ensure_scenario(store: Any) -> Dict[str, int]:
    """幂等：对象缺失或链接为空时重建演示战场（图链接为进程内内存图）。"""
    try:
        if store.count("unit") > 0 and store.get_links("unit", "u1"):
            return {"skipped": 1}
    except Exception:  # noqa: BLE001
        pass
    return seed_scenario(store)


__all__ = ["seed_scenario", "ensure_scenario", "situation", "format_situation",
           "SituationQueryTool"]
