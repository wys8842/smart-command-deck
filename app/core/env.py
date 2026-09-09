# -*- coding: utf-8 -*-
"""轻量 .env 加载（无第三方依赖）：把 KEY=VALUE 注入 os.environ（不覆盖已有）。"""
from __future__ import annotations

import os
from pathlib import Path


def load_env(path: str = ".env") -> int:
    """读取 .env 并 setdefault 到环境变量；返回加载条数。"""
    p = Path(path)
    if not p.exists():
        return 0
    count = 0
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, val)
            count += 1
    return count


__all__ = ["load_env"]
