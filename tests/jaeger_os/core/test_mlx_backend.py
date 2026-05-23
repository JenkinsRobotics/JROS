"""MLX backend — discovery, model bridge, client.

mlx-lm is an optional Apple-Silicon dep, so most of this test file works
without it installed. The bridge tests mock the mlx_lm functions so the
suite runs anywhere; the discovery test exercises the real filesystem
scanner against a synthetic MLX-shaped directory.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import patch

from jaeger_os.core.model_discovery import discover_local_mlx


# ── on-disk MLX discovery ─────────────────────────────────────────────


def _make_fake_mlx_model(directory: Path, weight_bytes: int = 16) -> None:
    """A directory that looks exactly like an MLX checkpoint: config.json
    plus a small .safetensors weight file."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "config.json").write_text('{"model_type": "qwen3"}', encoding="utf-8")
    (directory / "model.safetensors").write_bytes(b"\x00" * weight_bytes)


def test_discover_local_mlx_finds_directory_with_config_and_safetensors(tmp_path):
    fake = tmp_path / "mlx-community" / "Qwen3.5-9B-MLX-4bit"
    _make_fake_mlx_model(fake)
    with patch("jaeger_os.core.model_discovery._LMSTUDIO_DIRS", (str(tmp_path),)):
        found = discover_local_mlx()
    names = {m["name"] for m in found}
    assert "Qwen3.5-9B-MLX-4bit" in names


def test_discover_local_mlx_skips_dirs_without_safetensors(tmp_path):
    """A bare config.json doesn't make a directory an MLX model — must
    have at least one .safetensors weight."""
    only_config = tmp_path / "broken"
    only_config.mkdir()
    (only_config / "config.json").write_text("{}", encoding="utf-8")
    with patch("jaeger_os.core.model_discovery._LMSTUDIO_DIRS", (str(tmp_path),)):
        found = discover_local_mlx()
    assert all(m["name"] != "broken" for m in found)


def test_discover_local_mlx_dedups_by_resolved_path(tmp_path):
    """Symlinked roots must not surface the same model twice."""
    real = tmp_path / "real" / "model"
    _make_fake_mlx_model(real)
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "real")
    with patch(
        "jaeger_os.core.model_discovery._LMSTUDIO_DIRS",
        (str(tmp_path / "real"), str(link)),
    ):
        found = discover_local_mlx()
    assert sum(1 for m in found if m["name"] == "model") == 1


# ── MlxModel bridge ───────────────────────────────────────────────────


class _FakeTokenizer:
    """Just enough surface for ``MlxModel.request`` to call into."""

    def __init__(self) -> None:
        self.last_messages: list = []
        self.last_kwargs: dict = {}

    def apply_chat_template(self, messages, *, tools=None,
                            add_generation_prompt=True, tokenize=False):
        del add_generation_prompt, tokenize
        self.last_messages = list(messages)
        self.last_kwargs = {"tools": tools}
        return "<rendered>"


def _install_fake_mlx_lm(generate_returns: str = "hello"):
    """Stub mlx_lm.generate so the bridge runs without the wheel."""
    fake = types.ModuleType("mlx_lm")
    fake.generate = lambda *a, **k: generate_returns          # type: ignore[attr-defined]
    fake.load = lambda path: (object(), _FakeTokenizer())     # type: ignore[attr-defined]
    sys.modules["mlx_lm"] = fake
    return fake


def test_mlx_model_renders_prompt_and_returns_pydantic_ai_response():
    """End-to-end: build an MlxModel, ask it to generate, get a
    ``ModelResponse`` back. Validates the bridge wiring, the chat-template
    plumbing, and the parent class's response synthesis are all live."""
    import asyncio

    from pydantic_ai.messages import (
        ModelRequest, SystemPromptPart, UserPromptPart,
    )
    from pydantic_ai.models import ModelRequestParameters

    from jaeger_os.core.mlx_model import MlxModel

    _install_fake_mlx_lm(generate_returns="Hi there.")
    tok = _FakeTokenizer()
    model = MlxModel(mlx_model=object(), tokenizer=tok, model_name="test-qwen")

    messages = [ModelRequest(parts=[
        SystemPromptPart(content="be brief"),
        UserPromptPart(content="hello"),
    ])]
    resp = asyncio.run(model.request(messages, None, ModelRequestParameters()))
    assert resp.parts                              # the response carries content
    # The chat template was actually applied with our messages.
    assert tok.last_messages
    # The text body produced by the fake generator surfaces as a TextPart.
    text_parts = [p for p in resp.parts if getattr(p, "part_kind", None) == "text"]
    assert text_parts
    assert "Hi there." in text_parts[0].content


def test_mlx_model_falls_back_when_tokenizer_rejects_tools_kwarg():
    """Some MLX tokenizers don't accept ``tools=`` — the bridge must
    retry without it rather than crashing the turn."""
    import asyncio

    from pydantic_ai.messages import ModelRequest, UserPromptPart
    from pydantic_ai.models import ModelRequestParameters

    from jaeger_os.core.mlx_model import MlxModel

    class _StrictTokenizer:
        def apply_chat_template(self, messages, **kwargs):
            if "tools" in kwargs:
                raise TypeError("unexpected keyword argument 'tools'")
            return "<rendered>"

    _install_fake_mlx_lm(generate_returns="ok")
    model = MlxModel(mlx_model=object(), tokenizer=_StrictTokenizer(),
                     model_name="strict-test")
    messages = [ModelRequest(parts=[UserPromptPart(content="hi")])]
    resp = asyncio.run(model.request(messages, None, ModelRequestParameters()))
    assert resp.parts
