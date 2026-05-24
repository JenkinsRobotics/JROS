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


def test_prompt_matches_default_unscoped_tool_surface(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("JAEGER_TOOLSET_SCOPING", raising=False)
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    assert "The full built-in tool surface is visible" in sp
    assert "You see a focused CORE set of tools" not in sp


def test_prompt_mentions_load_toolset_when_scoping_enabled(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JAEGER_TOOLSET_SCOPING", "1")
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    assert "You see a focused CORE set of tools" in sp
    assert "call `load_toolset`" in sp
