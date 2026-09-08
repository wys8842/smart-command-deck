"""单机 Supervisor 入口（M0：骨架 + 离线冒烟）。

运行：
    python -m app.main --smoke
"""
import argparse
import sys

from app.core.config import init_components, make_config
from app.core.mock_llm import MockLLM


def run_smoke() -> str:
    """M0 冒烟：离线跑一个最小 Agent，验证『app → 框架 agentorchestra』通路。"""
    from agentorchestra.agents.simple_agent import SimpleAgent

    cfg = make_config()
    agent = SimpleAgent(name="smoke", llm=MockLLM(), config=cfg)

    result = agent.run("回合一：请确认推演引擎已就绪。")
    print(f"[smoke] agent 回复: {result}")
    assert result and "mock" in result, f"冒烟未得到预期回复: {result!r}"
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Smart Command Deck · 单机入口")
    parser.add_argument("--smoke", action="store_true", help="运行 M0 离线冒烟")
    parser.add_argument("--init", action="store_true", help="初始化数据目录（M0 预留）")
    args = parser.parse_args(argv)

    init_components()

    if args.smoke:
        run_smoke()
        print("[ok] M0 smoke passed: agentorchestra 接入正常")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
