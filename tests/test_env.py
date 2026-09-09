# -*- coding: utf-8 -*-
""".env 加载与 LLM 模式验收。"""
import os

from app.core.env import load_env
from app.core.llm_factory import llm_mode


def test_load_env_sets_vars(tmp_path, monkeypatch):
    envf = tmp_path / ".env"
    envf.write_text(
        "# comment\nLLM_MODEL_ID=deepseek-chat\nLLM_API_KEY=sk-test\nLLM_BASE_URL=https://api.deepseek.com/v1\n",
        encoding="utf-8",
    )
    for k in ("LLM_MODEL_ID", "LLM_API_KEY", "LLM_BASE_URL"):
        monkeypatch.delenv(k, raising=False)

    n = load_env(str(envf))
    assert n == 3
    assert os.environ["LLM_MODEL_ID"] == "deepseek-chat"
    assert llm_mode() == ("real", "deepseek-chat")


def test_llm_mode_mock_without_key(monkeypatch):
    for k in ("LLM_MODEL_ID", "LLM_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert llm_mode() == ("mock", None)


def test_load_env_missing_file(tmp_path):
    assert load_env(str(tmp_path / "nope.env")) == 0
