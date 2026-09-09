# -*- coding: utf-8 -*-
"""② 战例召回：用框架 capability/memory 存"成功处置案例"，同类事件召回参考。

性能：
- 关键词检索（关闭 embedding，避免外部调用）；
- 召回结果 LRU + TTL 缓存，重复 query 不再检索。
"""
from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import List, Optional, Tuple

from agentorchestra.capability.memory import MemoryManager, MemoryType

from app.core.llm_factory import build_config


class ExperienceStore:
    """战例库：内存检索 + append-only JSONL 持久化（O(1) 写入）。"""

    def __init__(
        self,
        path: str = "data/experience.jsonl",
        namespace: str = "battle",
        cache_size: int = 256,
        cache_ttl: float = 300.0,
    ):
        cfg = build_config(
            memory_backend="memory",          # 内存检索（快）
            memory_embedding_enabled=False,
            memory_namespace=namespace,
        )
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.namespace = namespace
        self.manager = MemoryManager.from_config(cfg, default_namespace=namespace)
        self.cache_size = cache_size
        self.cache_ttl = cache_ttl
        self._cache: "OrderedDict[str, Tuple[float, List[str]]]" = OrderedDict()
        self._lock = threading.RLock()
        self._fh = None
        self.hits = 0
        self.misses = 0
        self._load_file()

    # ---------------- 持久化 ----------------

    def _load_file(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                self.manager.remember(
                    rec.get("content", ""),
                    type=MemoryType(rec.get("type", "episode")),
                    tags=rec.get("tags") or [],
                    importance=float(rec.get("importance", 0.7)),
                    namespace=self.namespace,
                )
            except Exception:  # noqa: BLE001
                continue

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            finally:
                self._fh = None

    # ---------------- 写入 ----------------

    def remember_case(self, kind: str, summary: str, advice: str,
                      tags: Optional[List[str]] = None, importance: float = 0.7) -> str:
        content = f"[{kind}] 事件: {summary} | 处置: {advice}"
        entry_id = self.manager.remember(
            content, type=MemoryType.EPISODE,
            tags=tags or [kind], importance=importance, namespace=self.namespace,
        )
        # O(1) 追加到 JSONL（不经过 JsonlBackend 的逐条开/关文件）
        if self._fh is None:
            self._fh = self.path.open("a", encoding="utf-8")
        self._fh.write(json.dumps({
            "content": content, "type": MemoryType.EPISODE.value,
            "tags": tags or [kind], "importance": importance,
        }, ensure_ascii=False) + "\n")
        self._fh.flush()
        return entry_id

    # ---------------- 召回 ----------------

    def recall(self, query: str, top_k: int = 3) -> List[str]:
        key = f"{top_k}:{query}"
        with self._lock:
            item = self._cache.get(key)
            if item is not None:
                ts, val = item
                if self.cache_ttl <= 0 or (time.monotonic() - ts) <= self.cache_ttl:
                    self._cache.move_to_end(key)
                    self.hits += 1
                    return list(val)
                self._cache.pop(key, None)
        self.misses += 1
        entries = self.manager.recall(query, top_k=top_k, namespace=self.namespace)
        out = [e.content for e in entries]
        with self._lock:
            self._cache[key] = (time.monotonic(), list(out))
            self._cache.move_to_end(key)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
        return out

    def recall_block(self, query: str, top_k: int = 3) -> str:
        items = self.recall(query, top_k=top_k)
        if not items:
            return ""
        return "【历史战例参考】\n" + "\n".join(f"- {c}" for c in items)

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": (self.hits / total) if total else 0.0,
            "size": len(self._cache),
        }


def advice_from_order(order: Optional[dict]) -> str:
    """从命令 params 里取研判结论。"""
    if not order:
        return ""
    raw = order.get("params") or "{}"
    try:
        data = json.loads(raw)
        return str(data.get("advice", ""))
    except (json.JSONDecodeError, TypeError):
        return ""


__all__ = ["ExperienceStore", "advice_from_order"]
