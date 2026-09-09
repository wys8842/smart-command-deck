# -*- coding: utf-8 -*-
"""pytest 共享配置：
- 安装 Python 3.10 asyncio.timeout 兼容垫片；
- 每个用例前后清理 LLM_* 环境变量，保证测试确定性（不误连真实模型）。
"""
import os

import pytest

from app.core.compat import install_asyncio_timeout_compat

install_asyncio_timeout_compat()

_LLM_KEYS = ("LLM_MODEL_ID", "LLM_API_KEY", "LLM_BASE_URL")


@pytest.fixture(autouse=True)
def _isolate_llm_env():
    for k in _LLM_KEYS:
        os.environ.pop(k, None)
    yield
    for k in _LLM_KEYS:
        os.environ.pop(k, None)
