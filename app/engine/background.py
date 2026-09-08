# -*- coding: utf-8 -*-
"""① 常驻 pump：后台定时消费 EventBus 并跑推演图。"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from app.engine.event_bus import EventBus
from app.engine.service import process_pending

logger = logging.getLogger("app.pump")


class PumpWorker:
    """轮询消费事件队列的后台任务。"""

    def __init__(
        self,
        engine: Any,
        bus: EventBus,
        poll_interval: float = 1.0,
        intel_agent_factory: Optional[Callable[[], Any]] = None,
        thread_id: str = "default",
    ):
        self.engine = engine
        self.bus = bus
        self.poll_interval = poll_interval
        self.intel_agent_factory = intel_agent_factory
        self.thread_id = thread_id
        self._stop = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self.processed_total = 0

    async def poll_once(self) -> int:
        """单次消费，返回处理条数。"""
        res = await process_pending(
            self.engine, self.bus,
            intel_agent_factory=self.intel_agent_factory,
            thread_id=self.thread_id,
        )
        n = res["processed_count"]
        self.processed_total += n
        return n

    async def run(self) -> None:
        self._stop.clear()
        while not self._stop.is_set():
            try:
                await self.poll_once()
            except Exception as e:  # noqa: BLE001
                logger.exception("pump 消费异常: %s", e)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval)
            except asyncio.TimeoutError:
                pass

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None


__all__ = ["PumpWorker"]
