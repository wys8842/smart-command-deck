# -*- coding: utf-8 -*-
"""API 启动入口（uvicorn）。

运行：
    D:/python/miniconda/envs/llm/python.exe -m app.api.launch
或
    D:/python/miniconda/envs/llm/python.exe -m uvicorn app.api.launch:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import os

from app.api.server import create_app
from app.core.env import load_env
from app.core.tenancy import build_tenancy
from app.domain.experience import ExperienceStore
from app.domain.persist import open_persistent_engine
from app.domain.relations import ensure_scenario
from app.domain.state_store import open_state_store
from app.engine.replay import ReplayStore

# 读取 .env（若存在）后再建应用，使真实 LLM 配置生效
load_env()

# 预置引擎：确保演示战场关系存在（幂等）
_engine = open_persistent_engine()
ensure_scenario(_engine.object_store)

# 默认：SQLite data/games.db + EventBus data/events.json + 复盘时序
#      + CheckpointStore data/state.db（图 Inbox/iteration 持久化）
#      + 战例库 data/experience.jsonl + 常驻 pump
app = create_app(
    engine=_engine,
    pump=True,
    poll_interval=1.0,
    replay_store=ReplayStore("data/replay.json"),
    state_store=open_state_store(),
    max_concurrency=int(os.getenv("DECK_MAX_CONCURRENCY", "1")),
    experience=ExperienceStore("data/experience.jsonl"),
    trace=os.getenv("TRACE_ENABLED", "1") not in ("0", "false", "False"),
    trace_dir=os.getenv("TRACE_DIR", "data/traces"),
    tenancy=build_tenancy(),
)


def main(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    import uvicorn

    uvicorn.run("app.api.launch:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
