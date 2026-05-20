"""External-model pipeline — schema, key resolution, model construction.

These tests build pydantic-ai models and the ExternalModelClient WITHOUT
contacting any server (construction is offline; only `.chat()` /
`.connectivity_check()` would hit the network, and those are not
exercised here). They lock in the local-first invariant: a default
config never enables an external brain.
"""

from __future__ import annotations

import pytest

from jaeger_os.core.external_model import (
    ExternalModelClient,
    ExternalModelError,
    build_external_model,
    resolve_api_key,
    _merge_consecutive,
)
from jaeger_os.core.schemas import Config, ExternalModelConfig, ModelConfig


# ── local-first invariant ───────────────────────────────────────────


def test_external_model_disabled_by_default():
    """A fresh ExternalModelConfig — and a Config that omits the
    section entirely — must NOT enable an external brain."""
    assert ExternalModelConfig().enabled is False
    cfg = Config(
        instance_name="t",
        model=ModelConfig(model_path="/tmp/x.gguf"),
    )
    assert cfg.external_model.enabled is False
    assert cfg.external_model.provider == "lmstudio"


def test_config_rejects_unknown_external_field():
    """extra='forbid' on ExternalModelConfig catches typo'd keys."""
    with pytest.raises(Exception):
        ExternalModelConfig(enabled=True, provdier="lmstudio")  # typo


# ── key resolution ──────────────────────────────────────────────────


def test_resolve_api_key_from_env(monkeypatch):
    ext = ExternalModelConfig(provider="openai", api_key_env="MY_KEY_VAR")
    monkeypatch.setenv("MY_KEY_VAR", "sk-from-env")
    assert resolve_api_key(ext, layout=None) == "sk-from-env"


def test_resolve_api_key_conventional_env(monkeypatch):
    ext = ExternalModelConfig(provider="anthropic", api_key_env="")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-conventional")
    assert resolve_api_key(ext, layout=None) == "sk-ant-conventional"


def test_resolve_api_key_absent_returns_empty(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ext = ExternalModelConfig(provider="lmstudio", api_key_env="")
    assert resolve_api_key(ext, layout=None) == ""


# ── model construction (offline) ────────────────────────────────────


def test_build_lmstudio_model_no_key_needed():
    ext = ExternalModelConfig(enabled=True, provider="lmstudio", model="m")
    model = build_external_model(ext, api_key="")
    assert type(model).__name__ == "OpenAIChatModel"


def test_build_anthropic_requires_key():
    ext = ExternalModelConfig(enabled=True, provider="anthropic", model="claude-x")
    with pytest.raises(ExternalModelError):
        build_external_model(ext, api_key="")


def test_build_anthropic_with_key():
    ext = ExternalModelConfig(enabled=True, provider="anthropic", model="claude-opus-4-7")
    model = build_external_model(ext, api_key="fake-key")
    assert type(model).__name__ == "AnthropicModel"


def test_external_client_surface():
    """The client must mirror LlamaCppPythonClient's surface so main.py
    never branches on backend: .model, .chat, .kind, .model_name."""
    ext = ExternalModelConfig(enabled=True, provider="lmstudio", model="local-model")
    client = ExternalModelClient(ext, layout=None)
    assert client.kind == "external"
    assert client.model_name == "local-model"
    assert client.llm is None
    assert hasattr(client, "chat") and hasattr(client, "connectivity_check")
    assert type(client.model).__name__ == "OpenAIChatModel"
    assert "lmstudio" in client.describe()


# ── anthropic message shaping ───────────────────────────────────────


def test_merge_consecutive_collapses_same_role():
    """Anthropic is strict about role alternation; the fast-finalize
    path sends two user turns in a row — they must merge into one."""
    merged = _merge_consecutive(
        [
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b"},
            {"role": "assistant", "content": "c"},
        ]
    )
    assert merged == [
        {"role": "user", "content": "a\n\nb"},
        {"role": "assistant", "content": "c"},
    ]
