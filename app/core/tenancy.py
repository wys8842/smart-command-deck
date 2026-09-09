# -*- coding: utf-8 -*-
"""多租户与配额：用框架 governance/tenancy 做多局隔离 + token 配额 + 用量计费。

- TenantManager：ContextVar 租户上下文（namespace 隔离）
- QuotaManager：按租户的 token 配额（超限抛 QuotaExceeded）
- UsageRecorder：用量记录与导出
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from agentorchestra.governance.tenancy import (
    QuotaExceeded,
    QuotaManager,
    TenantManager,
    UsageRecorder,
)

DEFAULT_TENANT = "default"


class TenantGovernor:
    """租户治理门面（进程内单例即可）。"""

    def __init__(self, default_limit: int = 100000):
        self.manager = TenantManager()
        self.quotas = QuotaManager()
        self.usage = UsageRecorder()
        self.default_limit = default_limit

    def ensure(self, tenant_id: str, limit: Optional[int] = None) -> None:
        self.quotas.set_limit(tenant_id, limit if limit is not None else self.default_limit)

    def charge(self, tenant_id: str, tokens: int) -> None:
        """扣配额；不足抛 QuotaExceeded。"""
        self.quotas.charge(tenant_id, tokens)

    def record_usage(self, tenant_id: str, model: str, tokens: int,
                     latency_ms: float = 0.0) -> None:
        self.usage.record(tenant_id, model, tokens, latency_ms=latency_ms)

    def scope(self, tenant_id: str):
        """异步租户上下文（async with governor.scope(t): ...）。"""
        return self.manager.run_as(tenant_id)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "quotas": self.quotas.snapshot(),
            "usage_by_tenant": self.usage.by_tenant(),
        }


def build_tenancy(default_limit: Optional[int] = None) -> TenantGovernor:
    limit = default_limit
    if limit is None:
        limit = int(os.getenv("DECK_TENANT_QUOTA", "100000"))
    return TenantGovernor(default_limit=limit)


__all__ = ["TenantGovernor", "build_tenancy", "QuotaExceeded", "DEFAULT_TENANT"]
