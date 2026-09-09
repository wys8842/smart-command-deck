# -*- coding: utf-8 -*-
"""安全回归：确保 API Key 不会进入版本库（.env 必须被忽略）。"""
from pathlib import Path

from scripts.check_secrets import find_secrets, tracked_files


def test_no_secrets_in_tracked_files():
    hits = find_secrets()
    assert hits == [], f"检测到疑似密钥：{hits}"


def test_env_not_tracked():
    tracked = tracked_files()
    assert not any(Path(f).name == ".env" for f in tracked), ".env 不应被 git 跟踪"
    assert any(Path(f).name == ".env.example" for f in tracked), ".env.example 应保留"
