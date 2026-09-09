# -*- coding: utf-8 -*-
"""② 真实 LLM 工厂 + Config 注入。

- build_config：按需构建框架 Config（trace/目录等开关）。
- build_llm：按 env/参数构造 SymphonyLLM；未配置 key/base_url 时回退 Mock（离线可用）。
- build_intel_agent：组装研判 Agent（llm + config + 可选 ToolRegistry）。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from agentorchestra.agents.simple_agent import SimpleAgent
from agentorchestra.core.config import Config

from app.core.mock_llm import MockLLM

logger = logging.getLogger("app.llm_factory")


def build_config(**overrides: Any) -> Config:
    """构建框架 Config，可覆盖任意字段（如 trace_enabled / session_enabled）。"""
    cfg = Config()
    for k, v in overrides.items():
        if hasattr(cfg, k):
            setattr(cfg, k, v)
        else:
            logger.warning("Config 无字段 %s，忽略", k)
    return cfg


def llm_mode() -> tuple[str, Optional[str]]:
    """返回 (mode, model)：real=已配置 key+model；mock=回退离线。"""
    model = os.getenv("LLM_MODEL_ID")
    api_key = os.getenv("LLM_API_KEY")
    if model and api_key:
        return "real", model
    return "mock", None


def build_llm(
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Any:
    """构造 SymphonyLLM；缺 key/base_url 时回退 Mock（保证离线/未配置仍可启动）。"""
    from agentorchestra.core.llm import SymphonyLLM

    model = model or os.getenv("LLM_MODEL_ID")
    api_key = api_key if api_key is not None else os.getenv("LLM_API_KEY")
    base_url = base_url if base_url is not None else os.getenv("LLM_BASE_URL")

    if not (model and api_key):
        logger.warning("未配置 LLM_MODEL_ID/LLM_API_KEY，使用离线 MockLLM")
        return MockLLM()
    return SymphonyLLM(model=model, api_key=api_key, base_url=base_url)


def build_intel_agent(
    config: Optional[Config] = None,
    llm: Optional[Any] = None,
    tool_registry: Optional[Any] = None,
    name: str = "intel",
) -> SimpleAgent:
    """组装研判 Agent（支持注入 llm/config/tool_registry，便于测试与替换）。"""
    cfg = config or build_config()
    model = llm or build_llm()
    return SimpleAgent(name=name, llm=model, config=cfg, tool_registry=tool_registry)


__all__ = ["build_config", "build_llm", "build_intel_agent", "llm_mode"]
