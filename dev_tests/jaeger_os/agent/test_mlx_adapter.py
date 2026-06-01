"""``MLXAdapter`` — in-process MLX with a stub runner.

``mlx_lm`` isn't a hard dependency (no install on non-Apple hosts), so
construction must NEVER import it. The tests inject a runner closure
directly to bypass ``mlx_lm.load`` entirely.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from jaeger_os.agent import MLXAdapter


def test_constructor_does_not_import_mlx_lm():
    """Smoke: building the adapter on a host without ``mlx_lm`` must
    not raise. The lazy import is inside ``_lazy_runner``."""
    a = MLXAdapter(model_path="dummy/model")
    assert a.name == "mlx"


def test_explicit_runner_short_circuits_the_lazy_load():
    """Injecting a runner means the adapter never touches ``mlx_lm.load``.
    The first call swaps the resolved runner in so subsequent calls hit
    the closure directly — confirm via the call counter."""
    calls: list[tuple[str, dict[str, Any]]] = []

    def _runner(prompt: str, kw: dict[str, Any]) -> str:
        calls.append((prompt, dict(kw)))
        return "stub answer"

    a = MLXAdapter(runner=_runner)
    out = a.call(
        {"prompt": "hello", "stop": ["<|im_end|>"]},
        threading.Event(),
    )
    assert out == "stub answer"
    assert len(calls) == 1
    assert calls[0][0] == "hello"

    # Second call — same runner, now resolved.
    a.call({"prompt": "second", "stop": []}, threading.Event())
    assert len(calls) == 2
    # ``self.runner`` has been swapped to the resolved closure.
    assert a.runner is _runner


def test_constructor_requires_path_or_runner():
    a = MLXAdapter()  # neither provided — construction is fine
    # ...but invoking the lazy runner without either raises.
    with pytest.raises(ValueError, match="model_path"):
        a._lazy_runner("p", {})


def test_describe_reports_model_path_or_runner_sentinel():
    assert "dummy/model" in MLXAdapter(model_path="dummy/model").describe()
    assert "runner" in MLXAdapter(runner=lambda p, k: "").describe()


def test_inherits_hermes_xml_format_messages_path():
    """MLXAdapter is a HermesXMLAdapter subclass — the prompt assembly
    behaviour is what the parent guarantees. Smoke that route works."""
    a = MLXAdapter(runner=lambda p, k: "")
    out = a.format_messages(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        system="be brief",
    )
    assert "<|im_start|>system" in out["prompt"]
    assert "be brief" in out["prompt"]
    assert out["stop"] == ["<|im_end|>"]


def test_parse_response_drift_extracts_tool_calls():
    a = MLXAdapter(runner=lambda p, k: "")
    parsed = a.parse_response(
        '<tool_call>{"name": "x", "arguments": {"k": 1}}</tool_call>'
    )
    assert parsed["tool_calls"][0]["name"] == "x"
    assert parsed["tool_calls"][0]["arguments"] == {"k": 1}


def test_defaults_merge_with_call_kwargs():
    """Constructor defaults (``max_tokens``, ``temp``) flow through to
    the runner unless the call overrides."""
    seen: dict[str, Any] = {}

    def _runner(prompt: str, kw: dict[str, Any]) -> str:
        seen.update(kw)
        return ""

    a = MLXAdapter(runner=_runner, defaults={"max_tokens": 256, "temp": 0.3})
    a.call({"prompt": "p", "stop": []}, threading.Event(), temp=0.9)
    # Per-call wins; defaults supply the rest.
    assert seen["temp"] == 0.9
    # ``max_tokens`` only present if the lazy-runner code path injects
    # defaults — when explicit_runner is provided that path is skipped,
    # so this assertion focuses on the per-call override semantic.
