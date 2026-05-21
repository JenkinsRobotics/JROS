"""Model discovery + the Ollama provider.

Discovery surveys three sources (JROS registry / Ollama / LM Studio) so
the TUI's /model command can show the full picture; a server that is
not running must report offline, never raise. Ollama is a new external
provider that rides the OpenAI-compatible path.
"""

from __future__ import annotations

from jaeger_os.core.external_model import _OPENAI_COMPATIBLE
from jaeger_os.core.model_discovery import (
    discover_all,
    discover_jaeger,
    discover_lmstudio,
    discover_ollama,
)
from jaeger_os.core.schemas import ExternalModelConfig


# ── Ollama provider ──────────────────────────────────────────────────


def test_ollama_is_a_valid_provider() -> None:
    cfg = ExternalModelConfig(provider="ollama")
    assert cfg.provider == "ollama"


def test_ollama_rides_the_openai_compatible_path() -> None:
    # Ollama speaks OpenAI-compatible HTTP — no separate client needed.
    assert "ollama" in _OPENAI_COMPATIBLE
    assert "lmstudio" in _OPENAI_COMPATIBLE


# ── discovery ────────────────────────────────────────────────────────


def test_discover_jaeger_lists_the_registry() -> None:
    models = discover_jaeger()
    assert isinstance(models, list)
    assert any(m.get("name") for m in models)        # gemma / qwen registered


def test_offline_server_probe_is_graceful() -> None:
    # A port nothing listens on — must report offline cleanly, not raise.
    r = discover_ollama("http://localhost:9")
    assert r["online"] is False and r["models"] == []
    r2 = discover_lmstudio("http://localhost:9")
    assert r2["online"] is False and r2["models"] == []


def test_discover_all_covers_three_sources() -> None:
    d = discover_all()
    assert set(d) == {"jaeger", "ollama", "lmstudio"}
    assert isinstance(d["jaeger"], list)
    for src in ("ollama", "lmstudio"):
        assert "online" in d[src] and "models" in d[src]
