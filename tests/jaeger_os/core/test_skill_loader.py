from __future__ import annotations

from jaeger_os.core.skill_loader import _ToolCapturingAgent


class _FakeAgent:
    def __init__(self) -> None:
        self.registered: list[str] = []

    def tool_plain(self, *args, **kwargs):
        if len(args) == 1 and callable(args[0]) and not kwargs:
            self.registered.append(args[0].__name__)
            return args[0]

        def deco(fn):
            self.registered.append(fn.__name__)
            return fn

        return deco


def test_tool_capture_handles_parameterized_tool_plain() -> None:
    agent = _FakeAgent()
    capturing = _ToolCapturingAgent(agent)

    @capturing.tool_plain(retries=1)
    def demo_tool() -> dict:
        return {"ok": True}

    assert demo_tool() == {"ok": True}
    assert capturing.captured == ["demo_tool"]
    assert agent.registered == ["demo_tool"]
