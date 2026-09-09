# -*- coding: utf-8 -*-
"""API 启动入口（uvicorn）。

运行：
    D:/python/miniconda/envs/llm/python.exe -m app.api.launch
或
    D:/python/miniconda/envs/llm/python.exe -m uvicorn app.api.launch:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

from app.api.server import create_app
from app.engine.replay import ReplayStore

# 默认：SQLite data/games.db + EventBus data/events.json + 复盘时序 + 常驻 pump（可关）
app = create_app(
    pump=True,
    poll_interval=1.0,
    replay_store=ReplayStore("data/replay.json"),
)


def main(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    import uvicorn

    uvicorn.run("app.api.launch:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
