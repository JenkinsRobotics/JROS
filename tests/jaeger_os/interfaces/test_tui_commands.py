"""TUI port — the new session-info slash commands.

`/status` `/statusbar` `/stop` `/save` were added in the prompt_toolkit
TUI port. The interactive input layer needs a real terminal, but these
command handlers are testable against a model-less JaegerTUI.
"""

from __future__ import annotations

import pytest
from rich.console import Console

from jaeger_os.interfaces.tui import slash_commands as slash
from jaeger_os.interfaces.tui.app import JaegerTUI


@pytest.fixture()
def ctx(tmp_path):
    tui = JaegerTUI(skip_model=True)
    return slash.SlashContext(
        console=Console(file=open("/dev/null", "w"), width=100),
        instance_dir=tmp_path,
        tui=tui,
    )


def test_new_commands_are_registered() -> None:
    for name in ("status", "statusbar", "stop", "save"):
        assert name in slash._BY_NAME, name


def test_statusbar_toggles_the_flag(ctx) -> None:
    ctx.tui._statusbar_on = True
    slash.dispatch("/statusbar", ctx)
    assert ctx.tui._statusbar_on is False
    slash.dispatch("/statusbar", ctx)
    assert ctx.tui._statusbar_on is True


def test_status_runs_clean(ctx) -> None:
    assert slash.dispatch("/status", ctx).quit is False


def test_stop_runs_clean_with_no_processes(ctx) -> None:
    # No tools bound / no processes — must not raise, just report.
    assert slash.dispatch("/stop", ctx).quit is False


def test_save_runs_clean(ctx) -> None:
    # Empty conversation — must not raise.
    assert slash.dispatch("/save", ctx).quit is False


# ── /model use <cloud provider> ──────────────────────────────────────


def test_cloud_provider_maps_are_consistent() -> None:
    """Every cloud provider must carry a base URL, a credential name, a
    key hint and an example model — so /model use <provider> never
    half-works for one of them."""
    for prov in slash._CLOUD_PROVIDERS:
        assert prov in slash._CLOUD_BASE_URL, prov
        assert prov in slash._CLOUD_CRED, prov
        assert prov in slash._CLOUD_KEY_HINT, prov
        assert prov in slash._CLOUD_EXAMPLE, prov
    # Each provider keeps its key under its OWN credential name — a
    # collision would mean switching providers clobbers a stored key.
    assert len(set(slash._CLOUD_CRED.values())) == len(slash._CLOUD_CRED)


def test_cloud_providers_are_valid_schema_providers() -> None:
    """The TUI's cloud list must stay in sync with the config schema's
    accepted providers."""
    from jaeger_os.core.schemas import ExternalModelConfig
    for prov in slash._CLOUD_PROVIDERS:
        assert ExternalModelConfig(provider=prov, model="x").provider == prov


def test_gemini_uses_openai_compatible_endpoint() -> None:
    """Gemini must point at Google's OpenAI-compatible surface so it
    rides external_model's openai path — no native adapter."""
    url = slash._CLOUD_BASE_URL["gemini"]
    assert "generativelanguage.googleapis.com" in url
    assert "openai" in url


def test_cloud_aliases_resolve_to_real_providers() -> None:
    """Every alias must resolve to a provider in _CLOUD_PROVIDERS."""
    for alias, prov in slash._CLOUD_ALIASES.items():
        assert prov in slash._CLOUD_PROVIDERS, alias
