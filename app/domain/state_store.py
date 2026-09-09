# -*- coding: utf-8 -*-
"""图状态存储（1）：为 GraphScheduler 提供 CheckpointStore（Inbox/iteration 落库）。"""
from __future__ import annotations

from typing import Any, Optional

from agentorchestra.orchestration.state import get_default_store


def open_state_store(db_url: Optional[str] = None) -> Any:
    """打开持久化 CheckpointStore（默认 SQLite 文件 data/state.db）。"""
    return get_default_store(db_url or "sqlite+aiosqlite:///./data/state.db")


async def ensure_ready(store: Any) -> None:
    """确保 store 已 init（异步）。"""
    if store is None:
        return
    init = getattr(store, "init", None)
    if callable(init):
        try:
            await init()
        except Exception:  # noqa: BLE001
            pass


__all__ = ["open_state_store", "ensure_ready"]
