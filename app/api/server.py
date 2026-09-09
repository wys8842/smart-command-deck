# -*- coding: utf-8 -*-
"""③ FastAPI API 层：事件注入/回执 · 待批/批准 · 复盘 · 常驻 pump。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Callable, Dict, Optional

from agentorchestra.components import Components
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from app.api.ui import ui_html
from app.core.llm_factory import build_intel_agent, llm_mode
from app.domain.persist import open_persistent_engine
from app.domain.state_store import ensure_ready
from app.engine.background import PumpWorker
from app.engine.event_bus import EventBus, new_event
from app.engine.hitl import approval_event, approve_order, pending_orders
from app.engine.replay import ReplayStore, export_timeline
from app.engine.service import process_pending


class EventIn(BaseModel):
    kind: str
    source: str
    payload: Dict[str, Any] = {}
    round: int = 1


class ApproveIn(BaseModel):
    approve: bool = True


DEFAULT_GAME = "default"


def create_app(
    engine: Any = None,
    bus: Optional[EventBus] = None,
    db_path: str = "data/games.db",
    events_path: str = "data/events.json",
    intel_agent_factory: Optional[Callable[[], Any]] = None,
    config: Optional[Any] = None,
    pump: bool = False,
    poll_interval: float = 1.0,
    replay_store: Optional[ReplayStore] = None,
    state_store: Optional[Any] = None,
    max_concurrency: int = 1,
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

    # 启用 Prometheus 文本指标收集器（幂等），供 /metrics 输出
    try:
        Components.enable_prometheus()
    except Exception:  # noqa: BLE001
        pass

    if intel_agent_factory is not None:
        factory = intel_agent_factory
    elif config is not None:
        factory = lambda: build_intel_agent(config=config)  # noqa: E731
    else:
        # 无显式工厂/配置：build_intel_agent 会读 .env/环境变量，
        # 配好 LLM 则用真实模型，否则自动回退 MockLLM。
        factory = build_intel_agent

    worker = PumpWorker(engine, bus, poll_interval=poll_interval,
                        intel_agent_factory=factory, thread_id=DEFAULT_GAME,
                        replay_store=replay_store, state_store=state_store,
                        max_concurrency=max_concurrency) if pump else None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if state_store is not None:
            await ensure_ready(state_store)
        if worker is not None:
            worker.start()
        yield
        if worker is not None:
            await worker.stop()

    app = FastAPI(title="Smart Command Deck API", version="0.2.0", lifespan=lifespan)
    app.state.worker = worker

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        """浏览器控制台（入队/待批/批准/复盘）。"""
        return ui_html()

    @app.get("/health")
    def health() -> Dict[str, Any]:
        mode, model = llm_mode()
        return {
            "status": "ok",
            "orders": store.count("order"),
            "pump": worker is not None,
            "queued": len(bus.pending()),
            "llm_mode": mode,
            "llm_model": model,
        }

    @app.get("/metrics")
    def metrics() -> PlainTextResponse:
        """Prometheus 文本指标。"""
        try:
            text = Components.metrics_collector().render()
        except Exception as e:  # noqa: BLE001
            text = f"# metrics unavailable: {e}\n"
        return PlainTextResponse(text)

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

    @app.get("/events")
    def list_events(limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        return {"events": bus.list_receipts(limit=limit, offset=offset)}

    @app.post("/games/{game_id}/pump")
    async def pump_once(game_id: str) -> Dict[str, Any]:
        """手动消费一次待处理事件。"""
        return await process_pending(
            engine, bus,
            intel_agent_factory=factory,
            thread_id=game_id,
            replay_store=replay_store,
            state_store=state_store,
            max_concurrency=max_concurrency,
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
        # 自动入队“批准续跑”事件 → 常驻 pump 会执行 execute/settle
        cont = approval_event(order_id, body.approve)
        bus.enqueue(cont)
        return {**result, "continuation_ev_id": cont.ev_id}

    @app.get("/games/{game_id}/replay")
    def replay(game_id: str) -> Dict[str, Any]:
        return export_timeline(store, replay_store=replay_store, thread_id=game_id)

    return app


__all__ = ["create_app"]
