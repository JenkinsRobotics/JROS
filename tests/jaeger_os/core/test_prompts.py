"""System-prompt assembly — operating discipline + soul.md.

Covers the two agentic-reliability additions mined from hermes-agent:
the always-on OPERATING_DISCIPLINE block, and the optional per-instance
`soul.md` free-form character doc that complements identity.yaml.
"""

from __future__ import annotations

from jaeger_os.core.instance.instance import InstanceLayout
from jaeger_os.core.prompts.prompts import _load_soul, build_system_prompt


# ── operating discipline ────────────────────────────────────────────


def test_operating_discipline_in_system_prompt(tmp_path) -> None:
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    assert "Operating discipline" in sp
    assert "EXECUTE, don't promise" in sp


# ── soul.md ─────────────────────────────────────────────────────────


def test_load_soul_absent_is_empty(tmp_path) -> None:
    assert _load_soul(InstanceLayout(root=tmp_path)) == ""


def test_load_soul_reads_the_file(tmp_path) -> None:
    (tmp_path / "soul.md").write_text("## Voice\nWarm and direct.", encoding="utf-8")
    soul = _load_soul(InstanceLayout(root=tmp_path))
    assert "Warm and direct" in soul


def test_load_soul_caps_runaway_length(tmp_path) -> None:
    """A huge soul.md must not crowd out the routing imperatives."""
    (tmp_path / "soul.md").write_text("x" * 9000, encoding="utf-8")
    soul = _load_soul(InstanceLayout(root=tmp_path))
    assert len(soul) < 5000
    assert "truncated" in soul


def test_soul_md_folds_into_the_system_prompt(tmp_path) -> None:
    (tmp_path / "soul.md").write_text(
        "## Voice\nDistinctive-soul-marker.", encoding="utf-8"
    )
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    assert "Distinctive-soul-marker." in sp


def test_no_soul_md_still_builds_a_prompt(tmp_path) -> None:
    """soul.md is optional — absent, the prompt is still well-formed."""
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    assert "Mandatory tool rules" in sp


def test_prompt_defaults_to_unscoped_tool_surface(tmp_path, monkeypatch) -> None:
    """Default is UNSCOPED — full tool surface visible to the model.

    History: we briefly flipped this to SCOPED-by-default after adding
    ``describe_tool`` + the catalog, but a/b benching against v5 showed
    Gemma 4 26B-A4B routing accuracy dropped from 100% to 67.6% under
    the new default. Reverted to unscoped (opt-in via env) until
    auto-load-on-intent lands. See docs/lean_surface.md and the
    code_review_2026_05_24 disposition doc for context."""
    monkeypatch.delenv("JAEGER_TOOLSET_SCOPING", raising=False)
    monkeypatch.delenv("JAEGER_FULL_TOOLS", raising=False)
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    assert "full built-in tool surface is visible" in sp
    assert "focused CORE set of tools" not in sp
    assert "TOOL CATALOG" not in sp


def test_prompt_scoped_when_explicit_env(tmp_path, monkeypatch) -> None:
    """``JAEGER_TOOLSET_SCOPING=1`` opts into the lean surface — the
    model sees CORE + a one-line-per-category catalog, can peek at any
    schema via ``describe_tool``, and widen via ``load_toolset``.
    Useful for context-tight runs; not the default while routing
    regressions are open."""
    monkeypatch.setenv("JAEGER_TOOLSET_SCOPING", "1")
    monkeypatch.delenv("JAEGER_FULL_TOOLS", raising=False)
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    assert "focused CORE set of tools" in sp
    assert "TOOL CATALOG" in sp
    assert "describe_tool" in sp


def test_prompt_full_tools_env_overrides_explicit_scoping(tmp_path, monkeypatch) -> None:
    """``JAEGER_FULL_TOOLS=1`` is the kill-switch — wins even when
    ``JAEGER_TOOLSET_SCOPING=1`` asks for the lean surface. Used by
    bench harnesses that want guaranteed parity across env."""
    monkeypatch.setenv("JAEGER_FULL_TOOLS", "1")
    monkeypatch.setenv("JAEGER_TOOLSET_SCOPING", "1")
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    assert "full built-in tool surface is visible" in sp
    assert "TOOL CATALOG" not in sp


def test_prompt_unscoped_when_toolset_scoping_env_disabled(tmp_path, monkeypatch) -> None:
    """Explicit ``JAEGER_TOOLSET_SCOPING=0`` is the older way to opt out."""
    monkeypatch.setenv("JAEGER_TOOLSET_SCOPING", "0")
    monkeypatch.delenv("JAEGER_FULL_TOOLS", raising=False)
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    assert "full built-in tool surface is visible" in sp
