# -*- coding: utf-8 -*-
"""coordinator 账务（M4 扩展点整合）：以 governance/tx.TransactionCoordinator
运行账务事务（幂等 + 补偿 + DLQ），操作仍落在 ontology object_store。

使用：CoordinatorLedger 由 object_store 构建，所有事务在单个 CheckpointStore 上落账。
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.core.compat import install_asyncio_timeout_compat

install_asyncio_timeout_compat()  # Python 3.10：asyncio.timeout 兼容

from agentorchestra.governance.tx.context import TxReplay  # noqa: E402
from agentorchestra.governance.tx.coordinator import TransactionCoordinator  # noqa: E402
from agentorchestra.governance.tx.sync import run_sync  # noqa: E402
from agentorchestra.orchestration.state.backends.memory_backend import (  # noqa: E402
    InMemoryCheckpointStore,
)


def _read(store: Any, stock_id: str) -> float:
    rec = store.get("stock", stock_id)
    if rec is None:
        raise ValueError(f"账目不存在: {stock_id}")
    return float(rec.get("qty", 0))


class CoordinatorLedger:
    """Coordinator 账务门面。"""

    def __init__(self, object_store: Any, store: Any = None):
        self.object_store = object_store
        self.coordinator = TransactionCoordinator(store=store or InMemoryCheckpointStore())

    def register_actions(self) -> "CoordinatorLedger":
        c = self.coordinator
        ost = self.object_store

        def do_resupply(params, tx):
            sid, qty = params["stock_id"], float(params["qty"])
            ost.update("stock", sid, {"qty": _read(ost, sid) + qty})

        def undo_resupply(params, tx):
            sid, qty = params["stock_id"], float(params["qty"])
            ost.update("stock", sid, {"qty": _read(ost, sid) - qty})

        c.register_action("resupply_stock", do_resupply, undo_resupply, idempotent=True)

        # 演示：不可补偿的动作 —— 补偿必然失败，用于验证补偿重试后进 DLQ
        def do_touch(params, tx):
            ost.update("stock", params["stock_id"],
                       {"qty": _read(ost, params["stock_id"]) + 1})

        def undo_touch(params, tx):
            raise RuntimeError("无法撤销 touch")

        c.register_action("touch_uncompensable", do_touch, undo_touch, idempotent=True)
        c.register_action("boom", lambda p, tx: (_ for _ in ()).throw(RuntimeError("下游失败")), None)
        return self

    async def _run(self, steps: List[Dict[str, Any]], idempotency_key: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "success": False, "replayed": False, "completed": [],
            "failed": None, "compensated": [], "error": "",
        }
        try:
            async with self.coordinator.transaction(idempotency_key=idempotency_key) as tx:
                for step in steps:
                    await tx.execute(step["action"], step.get("params", {}))
            result.update(success=True, completed=list(tx.completed))
        except TxReplay as e:
            result.update(success=True, replayed=True)
            if e.result:
                result.update(completed=list(e.result.get("completed", [])))
        except Exception as e:  # noqa: BLE001
            result.update(success=False, failed=getattr(e, "name", None) or type(e).__name__)
            result["error"] = str(e)
            tx = locals().get("tx")
            if tx is not None:
                result["compensated"] = list(tx.completed)
        return result

    def run(self, steps: List[Dict[str, Any]], idempotency_key: str) -> Dict[str, Any]:
        """同步执行事务（幂等 key 防重放）。"""
        return run_sync(lambda: self._run(steps, idempotency_key))

    async def dlq_count(self, status: str = "open") -> int:
        return await self.coordinator.dlq.count(status=status)


__all__ = ["CoordinatorLedger"]
