# -*- coding: utf-8 -*-
"""② SQLite 持久化（M 扩展）：ontology 数据落 SQLite；重开引擎即“续跑”。"""
from __future__ import annotations

from typing import Optional

from agentorchestra.ontology import GraphStore, ObjectStore, OntologyEngine, SQLiteBackend

from app.domain.schema import create_engine


def open_persistent_engine(db_path: str, principal: str = "staff") -> OntologyEngine:
    """打开/创建 SQLite 持久化引擎（对象/动作注册幂等）。"""
    store = ObjectStore(graph=GraphStore(), backend=SQLiteBackend(db_path))
    engine = create_engine(store=store, principal=principal, roles=[principal])
    return engine


def close_engine(engine: Optional[OntologyEngine]) -> None:
    """关闭引擎（释放 SQLite）。"""
    if engine is not None:
        try:
            engine.object_store.close()
        except Exception:  # noqa: BLE001
            pass


__all__ = ["open_persistent_engine", "close_engine"]
