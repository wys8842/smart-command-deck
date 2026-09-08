# -*- coding: utf-8 -*-
"""④ Coordinator 事务整合验收：
- 幂等：同 key 重放不重复扣/加
- 补偿：成功后接失败 → 自动逆序补偿回滚
- DLQ：补偿失败重试耗尽 → 进 DLQ
"""
import asyncio

from app.domain.coord_ledger import CoordinatorLedger
from app.domain.ledger import set_qty
from app.domain.schema import create_engine


def _setup():
    engine = create_engine()
    engine.object_store.insert("stock", {"stock_id": "s1", "kind": "ammo", "qty": 100.0})
    ledger = CoordinatorLedger(engine.object_store).register_actions()
    return engine, ledger


def test_idempotent_replay_no_double():
    engine, ledger = _setup()
    store = engine.object_store

    r1 = ledger.run([{"action": "resupply_stock", "params": {"stock_id": "s1", "qty": 10}}],
                    idempotency_key="idem-1")
    assert r1["success"] and not r1["replayed"]
    after1 = store.get("stock", "s1")["qty"]

    r2 = ledger.run([{"action": "resupply_stock", "params": {"stock_id": "s1", "qty": 10}}],
                    idempotency_key="idem-1")
    assert r2["replayed"]
    assert store.get("stock", "s1")["qty"] == after1 == 110.0


def test_coordinator_compensation_rolls_back():
    engine, ledger = _setup()
    store = engine.object_store
    before = store.get("stock", "s1")["qty"]

    result = ledger.run([
        {"action": "resupply_stock", "params": {"stock_id": "s1", "qty": 5}},
        {"action": "boom", "params": {}},
    ], idempotency_key="idem-2")

    assert result["success"] is False
    assert "resupply_stock" in result["compensated"]
    assert store.get("stock", "s1")["qty"] == before


def test_compensation_failure_goes_to_dlq():
    engine, ledger = _setup()
    store = engine.object_store
    before = store.get("stock", "s1")["qty"]

    result = ledger.run([
        {"action": "touch_uncompensable", "params": {"stock_id": "s1"}},  # 补偿必失败
        {"action": "boom", "params": {}},
    ], idempotency_key="idem-3")

    assert result["success"] is False
    count = asyncio.run(ledger.dlq_count(status="open"))
    assert count >= 1, "补偿失败重试耗尽应进 DLQ"
    # 说明：touch 成功过 1 次、但补偿失败，账目留脏 → 由 DLQ 人工处理
    assert store.get("stock", "s1")["qty"] == before + 1
