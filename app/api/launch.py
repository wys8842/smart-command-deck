# -*- coding: utf-8 -*-
"""API 启动入口（uvicorn）。

运行：
    D:/python/miniconda/envs/llm/python.exe -m app.api.launch
或
    D:/python/miniconda/envs/llm/python.exe -m uvicorn app.api.launch:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

from app.api.server import create_app

# 默认：SQLite data/games.db + EventBus data/events.json + 常驻 pump（可关）
app = create_app(pump=True, poll_interval=1.0)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.api.launch:app", host="127.0.0.1", port=8000, reload=False)
