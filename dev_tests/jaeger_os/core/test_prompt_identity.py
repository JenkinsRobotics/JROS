"""System-prompt identity, Jaeger OS context, and terminal-output rules.

Three transcript bugs traced back to the prompt: the agent identified as its
base model (Qwen) instead of Erin Jaeger, did not know it runs on Jaeger OS,
and emitted ``**`` Markdown that renders badly in a terminal.
``load_identity_string`` is now model-agnostic, and ``build_system_prompt``
carries a Jaeger OS blurb, a plain-terminal output rule, and an
"answer the current message" directive against stale-task bleed.
"""

from __future__ import annotations

import pytest

from jaeger_os.core.instance.instance import InstanceLayout
from jaeger_os.core.memory.memory import load_identity_string
from jaeger_os.core.prompts.prompts import (
    JAEGER_OS_CONTEXT,
    OPERATING_DISCIPLINE,
    RUNTIME_TAIL_BASE,
    build_system_prompt,
)

_IDENTITY_YAML = """\
name: Erin Jaeger
role: general-purpose agentic assistant
personality: Capable and concise — honest about uncertainty.
voice_tone: clear, even-keeled
voice_id: am_adam
"""


@pytest.fixture()
def instance(tmp_path):
    layout = InstanceLayout(root=tmp_path / "inst")
    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    layout.identity_path.write_text(_IDENTITY_YAML, encoding="utf-8")
    return layout


# ── load_identity_string — model-agnostic ────────────────────────────


def test_identity_string_names_the_agent(instance):
    assert "Erin Jaeger" in load_identity_string(instance)


def test_identity_string_is_model_agnostic(instance):
    """It must not rebut one specific base model — the Gemma-era 'trained
    by Google' wording stopped applying once the model became Qwen."""
    out = load_identity_string(instance)
    assert "Google" not in out
    assert "Qwen" in out  # named as an example of what the agent is NOT
    assert "base model" in out.lower()


# ── prompt constants ─────────────────────────────────────────────────


def test_jaeger_os_context_describes_the_system():
    assert "Jaeger OS" in JAEGER_OS_CONTEXT
    assert "base model" in JAEGER_OS_CONTEXT.lower()


def test_operating_discipline_pins_to_the_current_message():
    text = OPERATING_DISCIPLINE.lower()
    assert "current message" in text
    assert "resumed" in text


def test_runtime_tail_forbids_markdown_bold():
    assert "**" in RUNTIME_TAIL_BASE  # the rule names the offending markup
    assert "plain terminal" in RUNTIME_TAIL_BASE.lower()


# ── build_system_prompt — end to end ─────────────────────────────────


def test_build_system_prompt_carries_identity_and_rules(instance):
    prompt = build_system_prompt(instance)
    assert "Erin Jaeger" in prompt                # identity
    assert "Jaeger OS" in prompt                  # system knowledge
    assert "current message" in prompt.lower()    # no stale-task execution
    assert "plain terminal" in prompt.lower()     # terminal-friendly output
    assert "Google" not in prompt                 # no stale model-specific text
