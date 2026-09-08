# -*- coding: utf-8 -*-
"""观测（M5）：装配 metrics/trace。"""
from __future__ import annotations

from typing import Any

from agentorchestra.components import Components


def init_metrics(force: bool = False) -> Any:
    """开启 Prometheus 文本指标收集器（幂等），返回 collector。"""
    Components.enable_prometheus()
    return Components.metrics_collector()


def reset_telemetry() -> None:
    """测试清理：还原默认收集器/组件。"""
    Components.reset()


__all__ = ["init_metrics", "reset_telemetry"]
