# -*- coding: utf-8 -*-
"""③ 可观测装配：TraceLogger 配置 + 可选 OTLP 导出 + SLO 指标辅助。"""
from __future__ import annotations

import os
from typing import Any

from agentorchestra.components import Components
from agentorchestra.core.config import Config


def build_trace_config(trace_dir: str = "data/traces", sanitize: bool = True) -> Config:
    """构建开启 TraceLogger 的框架 Config（JSONL + HTML 轨迹）。"""
    cfg = Config()
    cfg.trace_enabled = True
    cfg.trace_dir = trace_dir
    cfg.trace_sanitize = sanitize
    return cfg


def init_otel(service_name: str = "smart-command-deck") -> Any:
    """若配置 OTEL_ENDPOINT 则开启 OTLP trace 导出（默认关）。"""
    endpoint = os.getenv("OTEL_ENDPOINT")
    if not endpoint:
        return None
    try:
        return Components.enable_otel_trace(endpoint=endpoint, service_name=service_name)
    except Exception:  # noqa: BLE001
        return None


def observe(name: str, value: float, labels: dict | None = None) -> None:
    """记录直方图（NoOp 安全）。"""
    try:
        from agentorchestra.observability.metrics import get_default_collector

        get_default_collector().observe(name, value, labels or {})
    except Exception:  # noqa: BLE001
        pass


def increment(name: str, value: float = 1.0, labels: dict | None = None) -> None:
    """记录计数器（NoOp 安全）。"""
    try:
        from agentorchestra.observability.metrics import get_default_collector

        get_default_collector().increment(name, value, labels or {})
    except Exception:  # noqa: BLE001
        pass


__all__ = ["build_trace_config", "init_otel", "observe", "increment"]
