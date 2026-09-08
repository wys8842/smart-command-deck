# -*- coding: utf-8 -*-
"""M0 冒烟测试：验证 app → agentorchestra 通路可跑。"""
from app.core.mock_llm import MockLLM
from app.main import run_smoke


def test_run_smoke():
    result = run_smoke()
    assert isinstance(result, str) and result


def test_mock_llm_basic():
    llm = MockLLM()
    out = llm.invoke([{"role": "user", "content": "hi"}])
    assert "hi" in out.content
