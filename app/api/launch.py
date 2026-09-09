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
from app.domain.state_store import open_state_store
from app.engine.replay import ReplayStore

# 读取 .env（若存在）后再建应用，使真实 LLM 配置生效
load_env()

# 默认：SQLite data/games.db + EventBus data/events.json + 复盘时序
#      + CheckpointStore data/state.db（图 Inbox/iteration 持久化）+ 常驻 pump
app = create_app(
    pump=True,
    poll_interval=1.0,
    replay_store=ReplayStore("data/replay.json"),
    state_store=open_state_store(),
    max_concurrency=int(os.getenv("DECK_MAX_CONCURRENCY", "1")),
)


def main(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    import uvicorn

    uvicorn.run("app.api.launch:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
