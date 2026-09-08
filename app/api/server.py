# -*- coding: utf-8 -*-
"""③ FastAPI API 层：事件注入/回执 · 待批/批准 · 复盘 · 常驻 pump。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Callable, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.core.llm_factory import build_intel_agent
from app.domain.persist import open_persistent_engine
from app.engine.background import PumpWorker
from app.engine.event_bus import EventBus, new_event
from app.engine.hitl import approve_order, pending_orders
from app.engine.replay import export_timeline
from app.engine.service import default_intel_factory, process_pending


class EventIn(BaseModel):
    kind: str
    source: str
    payload: Dict[str, Any] = {}
    round: int = 1


class ApproveIn(BaseModel):
    approve: bool = True


def create_app(
    engine: Any = None,
    bus: Optional[EventBus] = None,
    db_path: str = "data/games.db",
    events_path: str = "data/events.json",
    intel_agent_factory: Optional[Callable[[], Any]] = None,
    config: Optional[Any] = None,
    pump: bool = False,
    poll_interval: float = 1.0,
) -> FastAPI:
    """构造 API 应用。

    Args:
        engine: OntologyEngine；None → SQLite 持久化默认库。
        bus: EventBus；None → data/events.json。
        intel_agent_factory: 研判 Agent 工厂（优先）；None 且 config 给定时用真实 LLM，
            否则用离线 Mock。
        config: 框架 Config（trace/能力开关注入）。
        pump: 是否启动常驻后台 pump（定时消费事件队列）。
        poll_interval: pump 轮询间隔（秒）。
    """
    if engine is None:
        engine = open_persistent_engine(db_path)
    bus = bus or EventBus(events_path)
    store = engine.object_store

    if intel_agent_factory is not None:
        factory = intel_agent_factory
    elif config is not None:
        factory = lambda: build_intel_agent(config=config)  # noqa: E731
    else:
        factory = default_intel_factory

    worker = PumpWorker(engine, bus, poll_interval=poll_interval,
                        intel_agent_factory=factory) if pump else None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if worker is not None:
            worker.start()
        yield
        if worker is not None:
            await worker.stop()

    app = FastAPI(title="Smart Command Deck API", version="0.2.0", lifespan=lifespan)
    app.state.worker = worker

    @app.get("/health")
    def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "orders": store.count("order"),
            "pump": worker is not None,
            "queued": len(bus.pending()),
        }

    @app.post("/events", status_code=202)
    def ingest_event(body: EventIn) -> Dict[str, Any]:
        ev = new_event(body.kind, body.source, body.payload, round=body.round)
        bus.enqueue(ev)
        rec = bus.receipt(ev.ev_id)
        return {"ev_id": ev.ev_id, **rec, "status": "queued"}

    @app.get("/events/{ev_id}")
    def event_receipt(ev_id: str) -> Dict[str, Any]:
        rec = bus.receipt(ev_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="事件不存在")
        return rec

    @app.post("/games/{game_id}/pump")
    async def pump_once(game_id: str) -> Dict[str, Any]:
        """手动消费一次待处理事件。"""
        return await process_pending(
            engine, bus,
            intel_agent_factory=factory,
            thread_id=game_id,
        )

    @app.get("/approvals")
    def approvals() -> Dict[str, Any]:
        return {"pending": pending_orders(store)}

    @app.post("/approvals/{order_id}")
    def decision(order_id: str, body: ApproveIn) -> Dict[str, Any]:
        try:
            result = approve_order(store, order_id, body.approve)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return result

    @app.get("/games/{game_id}/replay")
    def replay(game_id: str) -> Dict[str, Any]:
        return export_timeline(store)

    return app


__all__ = ["create_app"]
