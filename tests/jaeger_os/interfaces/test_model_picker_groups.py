"""``_build_providers_list`` shapes the stage-1 list for the /model picker.

The previous flat-list picker exposed all models in one pane; the
Hermes-style two-stage picker takes a list of *providers*, each with its
own ``models`` (or ``type_a_model=True`` for cloud APIs with no catalogue).
These tests pin the data the picker sees — the picker UI itself is covered
by ``test_grouped_picker.py``.
"""

from __future__ import annotations

from types import SimpleNamespace

from jaeger_os.interfaces.tui.slash_commands import _build_providers_list


def _ext(provider: str = "lmstudio", model: str = "gemma-4-26b",
         enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(provider=provider, model=model, enabled=enabled)


def _all_runtimes() -> dict:
    return {
        "jaeger":       [{"name": "gemma-jaeger", "path": "/p/g.gguf"}],
        "local_gguf":   [{"name": "qwen3-7b", "path": "/p/q.gguf",
                          "size_gb": 4.1, "source": "lmstudio"}],
        "ollama":       {"online": True, "models": [{"name": "llama3.2"}]},
        "lmstudio":     {"online": True, "models": [{"name": "qwen3-7b"}]},
        "ollama_cloud": {"online": False, "models": []},
    }


def _by_slug(providers, slug):
    return next(p for p in providers if p["slug"] == slug)


# ── shape ─────────────────────────────────────────────────────────────


def test_provider_list_includes_local_ollama_lmstudio_and_cloud():
    providers = _build_providers_list(_all_runtimes(), _ext())
    slugs = [p["slug"] for p in providers]
    assert slugs[0] == "local"
    assert "ollama" in slugs
    assert "lmstudio" in slugs
    # Cloud APIs always present (type_a_model only).
    for slug in ("ollama-cloud", "openai", "anthropic", "gemini"):
        assert slug in slugs


def test_local_provider_carries_every_loadable_gguf():
    """The user wanted LM Studio's downloaded GGUFs to appear under
    llama.cpp too — they're loadable in-process."""
    providers = _build_providers_list(_all_runtimes(), _ext())
    local = _by_slug(providers, "local")
    assert "gemma-jaeger" in local["models"]
    assert "qwen3-7b" in local["models"]


def test_local_dedups_jaeger_registry_against_local_gguf():
    found = {
        "jaeger":       [{"name": "shared", "path": "/p/a.gguf"}],
        "local_gguf":   [{"name": "shared", "path": "/p/b.gguf"}],
        "ollama":       {"online": False, "models": []},
        "lmstudio":     {"online": False, "models": []},
        "ollama_cloud": {"online": False, "models": []},
    }
    providers = _build_providers_list(found, None)
    local = _by_slug(providers, "local")
    assert local["models"].count("shared") == 1


# ── current-provider marking ─────────────────────────────────────────


def test_is_current_marks_the_active_external_provider():
    providers = _build_providers_list(_all_runtimes(), _ext(provider="lmstudio"))
    assert _by_slug(providers, "lmstudio")["is_current"] is True
    assert _by_slug(providers, "local")["is_current"] is False


def test_is_current_falls_back_to_local_when_external_disabled():
    providers = _build_providers_list(_all_runtimes(), _ext(enabled=False))
    assert _by_slug(providers, "local")["is_current"] is True


# ── offline servers + type-a-model providers ─────────────────────────


def test_offline_servers_are_excluded():
    found = {
        "jaeger":       [{"name": "g", "path": "/p"}],
        "local_gguf":   [],
        "ollama":       {"online": False, "models": []},
        "lmstudio":     {"online": False, "models": []},
        "ollama_cloud": {"online": False, "models": []},
    }
    slugs = [p["slug"] for p in _build_providers_list(found, None)]
    assert "ollama" not in slugs
    assert "lmstudio" not in slugs


def test_cloud_apis_are_type_a_model():
    providers = _build_providers_list(_all_runtimes(), None)
    for slug in ("openai", "anthropic", "gemini"):
        assert _by_slug(providers, slug).get("type_a_model") is True


def test_ollama_cloud_is_catalogue_when_models_present():
    found = _all_runtimes()
    found["ollama_cloud"] = {"online": True, "models": [{"name": "qwen3.5:397b"}]}
    cloud = _by_slug(_build_providers_list(found, None), "ollama-cloud")
    assert cloud.get("type_a_model") is not True
    assert "qwen3.5:397b" in cloud["models"]


def test_ollama_cloud_falls_back_to_type_a_model_when_empty():
    cloud = _by_slug(_build_providers_list(_all_runtimes(), None), "ollama-cloud")
    assert cloud.get("type_a_model") is True
