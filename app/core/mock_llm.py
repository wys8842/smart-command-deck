"""离线用 Mock LLM（M0 冒烟/单测；不触网）。"""
from types import SimpleNamespace


class MockLLM:
    """最小可用的假 LLM：同步 invoke 即可支撑 SimpleAgent 的纯对话路径。"""

    model = "mock-model"

    def invoke(self, messages, **kwargs):
        """返回一个含 content 的响应对象。"""
        last = messages[-1].get("content") if messages else ""
        return SimpleNamespace(
            content=f"[mock] 已收到：{last}",
            usage=None,
        )

    def stream_invoke(self, messages, **kwargs):
        yield "mock chunk"

    async def astream_invoke(self, messages, **kwargs):
        yield "mock chunk"

    async def ainvoke(self, messages, **kwargs):
        return self.invoke(messages, **kwargs)
