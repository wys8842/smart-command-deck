"""账务层（M4）：弹药/油料等账目用事务包装（正序执行 + 失败逆序补偿）。

演示对象：ontology/process 的 TransactionManager（纯 Saga，内存、零 DB）。
更严格的 coordinator 版（幂等+WAL+DLQ）见路线图 M4 扩展点，可 set_coordinator 切换。
"""
from __future__ import annotations

from typing import Any

from agentorchestra.ontology.process.transaction import TransactionManager


def read_qty(store: Any, stock_id: str) -> float:
    rec = store.get("stock", stock_id)
    if rec is None:
        raise ValueError(f"账目不存在: {stock_id}")
    return float(rec.get("qty", 0))


def set_qty(store: Any, stock_id: str, qty: float) -> None:
    store.update("stock", stock_id, {"qty": qty})


def register_ledger(tm: TransactionManager, store: Any) -> None:
    """注册账务相关补偿动作到事务管理器。

    动作执行/补偿都直接操作 store（此处捕获 engine.object_store）。
    """

    def _do_resupply(params: dict, ctx: Any) -> None:
        sid = params.get("stock_id", "")
        qty = float(params.get("qty", 0))
        set_qty(store, sid, read_qty(store, sid) + qty)

    def _undo_resupply(params: dict, ctx: Any) -> None:
        sid = params.get("stock_id", "")
        qty = float(params.get("qty", 0))
        set_qty(store, sid, read_qty(store, sid) - qty)

    def _do_fail(params: dict, ctx: Any) -> None:
        raise RuntimeError(params.get("reason", "下游失败"))

    tm.register("resupply_stock", _do_resupply, _undo_resupply)
    tm.register("fail_ledger", _do_fail, None)


def run_transaction(tm: TransactionManager, steps: list[dict[str, Any]]) -> dict[str, Any]:
    """同步执行事务（纯 Saga），返回结果 dict。"""
    return tm.execute(steps)


__all__ = ["read_qty", "register_ledger", "run_transaction", "set_qty"]
