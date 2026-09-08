# -*- coding: utf-8 -*-
"""② 真实 LLM 工厂 + Config 注入（离线注入 llm 验证装配与参数透传）。"""
from app.core.llm_factory import build_config, build_intel_agent
from app.core.mock_llm import MockLLM


def test_build_config_overrides():
    cfg = build_config(trace_enabled=True, session_enabled=False)
    assert cfg.trace_enabled is True
    assert cfg.session_enabled is False


def test_build_intel_agent_injects_llm_and_config():
    cfg = build_config(trace_enabled=False)
    agent = build_intel_agent(config=cfg, llm=MockLLM(), name="intel-x")
    assert agent.name == "intel-x"
    assert isinstance(agent.llm, MockLLM)
    assert agent.config.trace_enabled is False


def test_build_llm_falls_back_offline_without_key():
    llm = build_config()  # 无 env/参数
    from app.core.llm_factory import build_llm
    import os

    saved = {k: os.environ.pop(k, None) for k in ("LLM_MODEL_ID", "LLM_API_KEY", "LLM_BASE_URL")}
    try:
        m = build_llm()
        assert isinstance(m, MockLLM)
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
    assert llm is not None
