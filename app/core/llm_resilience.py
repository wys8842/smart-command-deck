# -*- coding: utf-8 -*-
"""LLM 性能与韧性（3）：响应缓存 + 统计（超时/重试由 SymphonyLLM 负责）。

- 缓存键 = model + messages + kwargs（sha256），带 TTL 与 LRU 容量上限。
- 命中直接返回，避免重复调用真实模型（显著降本、降延迟）。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from collections import OrderedDict
from types import SimpleNamespace
from typing import Any, Dict, Optional, Tuple


class CachedLLM:
    """为任意 LLM 增加线程安全 LRU+TTL 响应缓存（同步/异步）。"""

    def __init__(self, inner: Any, max_size: int = 256, ttl: float = 3600.0):
        self._inner = inner
        self.max_size = max_size
        self.ttl = ttl
        self._cache: "OrderedDict[str, Tuple[float, str]]" = OrderedDict()
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    @property
    def model(self) -> Any:
        return getattr(self._inner, "model", None)

    def _key(self, messages: Any, kwargs: Dict[str, Any]) -> str:
        payload = json.dumps(
            {"model": self.model, "messages": messages, "kwargs": kwargs},
            ensure_ascii=False, sort_keys=True, default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _get(self, key: str) -> Optional[str]:
        with self._lock:
            item = self._cache.get(key)
            if item is None:
                return None
            ts, content = item
            if self.ttl > 0 and (time.monotonic() - ts) > self.ttl:
                self._cache.pop(key, None)
                return None
            self._cache.move_to_end(key)
            return content

    def _put(self, key: str, content: str) -> None:
        with self._lock:
            self._cache[key] = (time.monotonic(), content)
            self._cache.move_to_end(key)
            while len(self._cache) > self.max_size:
                self._cache.popitem(last=False)

    def _response(self, content: str, cached: bool) -> Any:
        return SimpleNamespace(content=content, usage=None, cached=cached, latency_ms=0)

    def invoke(self, messages: Any, **kwargs: Any) -> Any:
        key = self._key(messages, kwargs)
        hit = self._get(key)
        if hit is not None:
            self.hits += 1
            return self._response(hit, cached=True)
        self.misses += 1
        resp = self._inner.invoke(messages, **kwargs)
        content = getattr(resp, "content", None)
        if isinstance(content, str):
            self._put(key, content)
        return resp

    async def ainvoke(self, messages: Any, **kwargs: Any) -> Any:
        ainvoke = getattr(self._inner, "ainvoke", None)
        if callable(ainvoke):
            key = self._key(messages, kwargs)
            hit = self._get(key)
            if hit is not None:
                self.hits += 1
                return self._response(hit, cached=True)
            self.misses += 1
            resp = await ainvoke(messages, **kwargs)
            content = getattr(resp, "content", None)
            if isinstance(content, str):
                self._put(key, content)
            return resp
        return await asyncio.to_thread(self.invoke, messages, **kwargs)

    def stats(self) -> Dict[str, Any]:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "size": len(self._cache),
            "hit_rate": (self.hits / total) if total else 0.0,
        }

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()


__all__ = ["CachedLLM"]
