# -*- coding: utf-8 -*-
"""密钥防泄漏扫描：检查 git 已跟踪文件里是否出现疑似 API Key。

用法：
    python scripts/check_secrets.py        # 命中则退出码 1（供 CI/提交前校验）

规则（可扩展）：
    sk-[A-Za-z0-9_-]{20,}        常见 API Key
    api[_-]?key\\s*=\\s*["'][^"']{20,}  赋值式密钥
    AKIA[0-9A-Z]{16}             AWS Access Key
白名单：.env.example（仅占位符）
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"api[_-]?key\s*=\s*[\"'][^\"']{20,}", re.IGNORECASE),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]
ALLOW_FILES = {".env.example"}
MAX_BYTES = 2_000_000


def tracked_files() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files"], capture_output=True, text=True, check=True
        )
        return [f for f in out.stdout.splitlines() if f.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


def find_secrets() -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    for rel in tracked_files():
        name = Path(rel).name
        if name in ALLOW_FILES:
            continue
        p = Path(rel)
        try:
            if not p.is_file() or p.stat().st_size > MAX_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for pat in PATTERNS:
                m = pat.search(line)
                if m:
                    hits.append((rel, i, m.group(0)[:12] + "..."))
                    break
    return hits


def main() -> int:
    hits = find_secrets()
    if hits:
        print("[SECURITY] 检测到疑似密钥已进入版本库：")
        for rel, ln, snip in hits:
            print(f"  - {rel}:{ln}  {snip}")
        print("请从文件移除并把密钥放入 .env（已被 .gitignore 忽略）。")
        return 1
    print("[SECURITY] OK：已跟踪文件中未发现疑似密钥。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
