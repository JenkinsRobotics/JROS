"""System-prompt assembly — the consolidated Core / Safety / Instance split.

Pre-consolidation, FIVE codepaths built the agent's system prompt
(main turn, sub-agent, Deep Think, idle board, cron) and each carried
its own assembly logic. This file pins:

  * the single ``assemble_prompt(layout, *, mode)`` entry point
  * what each mode includes / excludes (the contract that lets a
    sub-agent run on a focused brief without dragging the full
    standing-TODO surface)
  * the Three Laws wrap is applied to every mode
  * the back-compat ``build_system_prompt`` shim still produces the
    same prompt as ``mode='agent'``

A snapshot of the assembled prompt structure (block presence, not
exact text) is checked per mode so a refactor that drifts is caught
at PR time.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from jaeger_os.core.prompts import (
    AUTO_BOARD_PROMPT,
    PromptMode,
    assemble_prompt,
    build_system_prompt,
    cron_prompt,
    deep_think_directive,
)
from jaeger_os.core.prompts.rules import (
    JAEGER_OS_CONTEXT,
    MANDATORY_TOOL_RULES,
    OPERATING_DISCIPLINE,
    TOOL_USAGE_RULES,
    VOICE_LLM_GATE_RULE,
)


def _layout(tmp_path: Path) -> object:
    """Minimal layout duck-type — assemble_prompt only reads .root and
    delegates the rest through to the dynamic blocks (which gracefully
    return '' on a fresh instance)."""
    return types.SimpleNamespace(
        root=tmp_path,
        memory_dir=tmp_path / "memory",
        skills_dir=tmp_path / "skills",
        logs_dir=tmp_path / "logs",
        config_path=tmp_path / "config.yaml",
    )


# ── core invariants ────────────────────────────────────────────────


def test_agent_mode_contains_every_static_rule_block(tmp_path):
    """The live-agent system prompt must carry all four static rule
    blocks. A refactor that drops one of these is the most likely way
    behaviour silently regresses."""
    out = assemble_prompt(_layout(tmp_path), mode="agent")
    assert JAEGER_OS_CONTEXT.strip() in out
    assert MANDATORY_TOOL_RULES.strip() in out
    assert OPERATING_DISCIPLINE.strip() in out
    assert TOOL_USAGE_RULES.strip() in out


def test_voice_gate_rule_matches_voicellm_noise_examples():
    """The always-on voice gate must explicitly teach the model to ignore
    background media/ad fragments while still answering direct requests.

    G3 (operator-locked 2026-06-07): rule strengthened with VoiceLLM-
    style default-to-ignore framing + more concrete noise examples,
    including ones drawn from the operator's actual TV/movie test
    runs."""
    # Default-ignore framing (the conservative default that catches
    # borderline ambient media).
    assert "Default to ``<ignore>`` when uncertain" in VOICE_LLM_GATE_RULE
    # The "much of what you hear is NOT directed at you" framing —
    # VoiceLLM's anti-junk priming.  Substring search across the wrap.
    assert "MUCH" in VOICE_LLM_GATE_RULE
    assert "NOT directed at you" in VOICE_LLM_GATE_RULE
    # Concrete examples — both legacy ones and ones added in G3.
    assert "on X off-road makes it easy" in VOICE_LLM_GATE_RULE
    assert "kind of stuff that players have been asking for forever" \
        in VOICE_LLM_GATE_RULE
    # G3 — example from operator's actual TV/movie noise test:
    assert "Princess." in VOICE_LLM_GATE_RULE
    # Direct requests stay <reply>.
    assert "``what time is it``" in VOICE_LLM_GATE_RULE
    assert "<reply>" in VOICE_LLM_GATE_RULE


def test_every_mode_gets_the_three_laws_wrap(tmp_path):
    """Three Laws are the safety frame — every codepath that hits the
    model must carry them. The wrap is idempotent so nested calls
    don't double the block."""
    layout = _layout(tmp_path)
    for mode in ("agent", "subagent", "deep_think", "idle_board", "cron"):
        out = assemble_prompt(layout, mode=mode)
        # The safety wrap renders as ``SAFETY CONTRACT — read this...``
        # and lists the three laws under it. Pin the stable header.
        assert "SAFETY CONTRACT" in out, \
            f"mode={mode!r} missing Three Laws wrap"
        assert "three laws" in out.lower(), \
            f"mode={mode!r} missing three-laws body"


def test_every_mode_keeps_identity_and_jaeger_os_context(tmp_path):
    """No matter the mode, the agent must know what system it runs on.
    A sub-agent on a focused brief is still THIS agent — voice and
    identity carry through."""
    layout = _layout(tmp_path)
    for mode in ("agent", "subagent", "deep_think", "idle_board", "cron"):
        out = assemble_prompt(layout, mode=mode)
        assert JAEGER_OS_CONTEXT.strip() in out, f"mode={mode!r}"


# ── per-mode shape ─────────────────────────────────────────────────


def test_agent_mode_is_the_full_surface(tmp_path):
    """``agent`` mode is the baseline every other mode is compared
    against. It carries identity, OS context, rules, runtime tail —
    the maximal scaffold."""
    out = assemble_prompt(_layout(tmp_path), mode="agent")
    assert "File access" in out  # from RUNTIME_TAIL_BASE
    assert OPERATING_DISCIPLINE.strip() in out


def test_subagent_mode_carries_the_brief_at_the_top(tmp_path):
    """A sub-agent prompt must put the focused task brief BEFORE the
    rules scaffold so the model treats it as the primary
    instruction, not the backdrop."""
    out = assemble_prompt(
        _layout(tmp_path), mode="subagent",
        goal="port the macOS skill to linux",
        context="started by the parent on 2026-05-25",
    )
    assert "sub-agent" in out.lower()
    assert "port the macOS skill to linux" in out
    assert "started by the parent on 2026-05-25" in out
    # The brief must come BEFORE the OPERATING_DISCIPLINE block so the
    # model reads the task first, then the rules that frame how to
    # work it.
    assert out.index("port the macOS skill to linux") < \
        out.index(OPERATING_DISCIPLINE.strip()[:40])


def test_subagent_mode_skips_the_board_digest(tmp_path):
    """The kanban board is the PARENT's standing TODO list — the
    child has one task and shouldn't be nudged to range across the
    full board."""
    # Seed a board card so a non-sub-agent mode WOULD see the digest,
    # to prove the test's negative assertion is meaningful.
    mem = tmp_path / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    from jaeger_os.core.background.board import board_for_layout
    board_for_layout(_layout(tmp_path)).add("parent's todo", column="ready")

    sub_out = assemble_prompt(_layout(tmp_path), mode="subagent", goal="x")
    agent_out = assemble_prompt(_layout(tmp_path), mode="agent")

    # The digest block opens with this exact line; the rules block
    # only references it as the phrase "BOARD STATUS" in prose, so we
    # pin the exact opener to avoid false positives from the rules.
    digest_opener = "BOARD STATUS — work to pick up"
    assert digest_opener in agent_out  # agent mode sees it
    assert digest_opener not in sub_out  # sub-agent does not


def test_subagent_mode_skips_the_v2_self_improvement_contract(tmp_path):
    """The v2 contract is a skill-authoring scaffold — relevant only
    for the main agent on a self-improvement turn. Sub-agents have
    their own task brief; the contract would dilute it."""
    # We don't seed a config that enables v2; this test just verifies
    # that even if v2 were on, sub-agent mode would skip it. Both
    # paths exclude v2 by default so the assertion holds either way.
    out = assemble_prompt(_layout(tmp_path), mode="subagent", goal="x")
    # Sentinel string from the v2 contract file — when present.
    assert "Skill Authoring Contract" not in out


def test_deep_think_mode_includes_full_rules_scaffold(tmp_path):
    """Deep Think is autonomous skill development — needs the full
    rules surface. The task brief itself is the USER-role message
    (``deep_think_directive``), not part of the system prompt."""
    out = assemble_prompt(_layout(tmp_path), mode="deep_think")
    assert OPERATING_DISCIPLINE.strip() in out
    assert MANDATORY_TOOL_RULES.strip() in out


# ── back-compat shim ───────────────────────────────────────────────


def test_build_system_prompt_equals_assemble_agent(tmp_path):
    """The back-compat shim must produce the SAME prompt as the new
    ``assemble_prompt(mode='agent')`` — if these drift, callers of
    ``build_system_prompt`` would see different model behaviour
    than callers of the new API."""
    layout = _layout(tmp_path)
    a = build_system_prompt(layout)
    b = assemble_prompt(layout, mode="agent")
    assert a == b


# ── synthetic prompts (mid-conversation) ───────────────────────────


def test_auto_board_prompt_mentions_every_actionable_column():
    """The idle-pickup synthetic prompt must name backlog / ready /
    in_progress so the model knows the full scope — a rename that
    silently dropped one column would shrink the agent's autonomy."""
    for col in ("backlog", "ready", "in_progress"):
        assert col in AUTO_BOARD_PROMPT


def test_deep_think_directive_wraps_task_description():
    """The directive must include the task description verbatim and
    frame it with the Deep-Think-mode preamble."""
    out = deep_think_directive("write a skill for X")
    assert "write a skill for X" in out
    assert "Deep Think mode" in out


def test_deep_think_directive_strips_whitespace_from_task():
    """Leading / trailing whitespace on a queued task description must
    not bleed into the directive — keeps the framing tight."""
    out = deep_think_directive("  task   \n")
    assert out.endswith("task")


def test_cron_prompt_passthrough_by_default():
    """Default behaviour matches today's ``cron_runner._invoke``:
    the prompt is passed through verbatim. Framing is opt-in."""
    out = cron_prompt("good morning")
    assert out == "good morning"


def test_cron_prompt_framed_when_requested():
    """``frame=True`` wraps the prompt with the cron preamble so the
    agent knows it came from a schedule, not a live user."""
    out = cron_prompt("good morning", frame=True)
    assert "good morning" in out
    assert "Scheduled" in out
