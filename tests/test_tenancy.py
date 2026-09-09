# -*- coding: utf-8 -*-
"""多租户/配额验收：配额扣减、租户上下文隔离、超限拒绝、用量记录。"""
import asyncio

from agentorchestra.governance.tenancy import QuotaExceeded, TenantManager

from app.core.tenancy import build_tenancy
from app.domain.persist import close_engine, open_persistent_engine
from app.engine.event_bus import EventBus, new_event
from app.engine.service import process_pending


def _seed(store):
    store.insert("unit", {"unit_id": "u1", "name": "甲", "side": "friendly",
                          "location": "A1", "status": "idle", "strength": 80})
    store.insert("target", {"target_id": "t1", "name": "雷达", "kind": "radar",
                            "side": "enemy", "threat": 0.8, "location": "B2"})


class TenantRecordingAgent:
    model = "tr"

    def __init__(self, seen):
        self.seen = seen

    async def arun(self, task):
        self.seen.append(TenantManager.tenant_id())
        return "研判建议：保持警戒"

    def clear_history(self):
        pass


def test_quota_charge_and_snapshot():
    gov = build_tenancy(default_limit=10)
    gov.ensure("acme")
    gov.charge("acme", 5)
    gov.record_usage("acme", "minimax-m3", 5)

    snap = gov.snapshot()
    assert snap["quotas"]["acme"]["used"] == 5
    assert snap["usage_by_tenant"]["acme"] == 5

    try:
        gov.charge("acme", 6)
        raise AssertionError("应触发 QuotaExceeded")
    except QuotaExceeded:
        pass


def test_service_tenant_context_and_usage(tmp_path):
    engine = open_persistent_engine(str(tmp_path / "games.db"))
    _seed(engine.object_store)
    bus = EventBus(path=str(tmp_path / "events.json"))
    gov = build_tenancy(default_limit=1000)
    seen = []

    bus.enqueue(new_event("intel_report", "radar",
                          {"order_id": "o1", "kind": "strike", "unit_id": "u1",
                           "target_id": "t1", "threat": 0.9,
                           "tenant": "acme", "tokens": 10}))
    res = asyncio.run(process_pending(
        engine, bus,
        intel_agent_factory=lambda: TenantRecordingAgent(seen),
        tenancy=gov,
    ))

    assert res["processed_count"] == 1
    assert seen and seen[0] == "acme"          # 租户上下文生效
    assert gov.snapshot()["usage_by_tenant"]["acme"] == 10
    close_engine(engine)


def test_quota_denied_event(tmp_path):
    engine = open_persistent_engine(str(tmp_path / "games.db"))
    _seed(engine.object_store)
    bus = EventBus(path=str(tmp_path / "events.json"))
    gov = build_tenancy(default_limit=5)

    ev = new_event("intel_report", "radar",
                   {"order_id": "o2", "kind": "strike", "unit_id": "u1",
                    "target_id": "t1", "threat": 0.9, "tenant": "acme", "tokens": 10})
    bus.enqueue(ev)
    res = asyncio.run(process_pending(engine, bus, tenancy=gov))

    assert res["processed_count"] == 0
    assert ev.ev_id in res["denied"]
    assert engine.object_store.count("order") == 0
    close_engine(engine)
