# -*- coding: utf-8 -*-
"""兼容垫片：为 Python 3.10 提供 asyncio.timeout（3.11+ 才内建）。

框架 governance/tx.coordinator 在 `async with asyncio.timeout(...)` 使用；
在 3.10 下安装一个等价的退出时超时检查（尽力而为，不做抢占式取消）。
"""
from __future__ import annotations

import asyncio
import time as _time
from typing import Optional


class _TimeoutCM:
    def __init__(self, delay: float):
        self.delay = delay
        self._deadline: Optional[float] = None

    async def __aenter__(self):
        self._deadline = _time.monotonic() + self.delay
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None and _time.monotonic() > self._deadline:
            raise TimeoutError("timeout")
        return False


def install_asyncio_timeout_compat() -> None:
    """幂等：3.11+ 已有 asyncio.timeout 则跳过。"""
    if hasattr(asyncio, "timeout"):
        return
    asyncio.timeout = lambda delay: _TimeoutCM(delay)


install_asyncio_timeout_compat()

__all__ = ["install_asyncio_timeout_compat"]
