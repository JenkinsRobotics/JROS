"""System-prompt assembly for Jaeger.

Layered, in this order, so the result is deterministic at startup:

  [identity blurb from identity.yaml]
  [soul.md — optional free-form character/voice doc, if the instance
   has one; user-owned, complements the structured identity.yaml]
  [MANDATORY TOOL RULES — short, near the top, so a small local model
   doesn't gloss past them]
  [OPERATING DISCIPLINE — terse execute-don't-promise / keep-going
   directives; the agentic-reliability counterpart to the tool rules]
  [v2 self-improvement contract — OFF by default, gated behind
   skills.include_self_improvement_contract in the instance config]
  [runtime hints: workspace path, tool surface notes]

Mirrors python_pydantic_ai/core/prompts.py — four MANDATORY rules
(persist / recall / forget / narrate-files) plus a short runtime tail.
Larger surfaces (math, file delete, etc.) ride on tool docstrings, which
already say "MANDATORY for ANY ...". Bench data on Gemma 4 26B-A4B
showed that piling extra rules into the prompt actually hurt routing —
larger context dilutes the imperatives that get most attention.

The 115-line v2 self-improvement contract used to load every turn. It's
load-bearing when the agent is authoring skills (versioning, rollback,
smoke tests) but adds ~900 words otherwise and was costing 3/23 on the
routing bench. Now opt-in via the config flag.

Nothing here ever edits identity.yaml — the wizard owns it.
"""

from __future__ import annotations

from pathlib import Path

from .instance import InstanceLayout


# core/ lives one level deeper than the framework root, so reach up one.
CORE_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "agent_system_prompt.md"


MANDATORY_TOOL_RULES = """\
Mandatory tool rules — these are not suggestions:

1. PERSISTING FACTS. If the user states a preference, identity fact,
   plan, or anything they might want recalled later ("remember that…",
   "my favorite X is…", "I'm allergic to…", "I'll be in town on…"),
   you MUST call `remember(key, value)`. Acknowledging in free-text
   ("OK, I'll remember") without calling the tool is forbidden — it is
   lying.

2. RECALLING FACTS. If the user asks about something they told you in
   any prior turn or session ("what did I say my…", "do you remember…",
   "what's my favorite X?", "what video length do I prefer?"), you MUST
   call `recall(key)` or `list_facts()` BEFORE answering. The persisted
   store is the source of truth across sessions; short-term conversation
   context is not. Fall back to `search_memory` only if both miss.

3. FORGETTING FACTS. "Forget my X", "remove my X preference", "I changed
   my mind about X" all require calling `forget(key)`. Don't free-text
   acknowledge.

4. NARRATING FILES. "Read X out loud", "narrate X", "speak X as if for a
   video" with a NAMED FILE means: call `text_to_speech(path="X")`. Use
   `text_to_speech(text=...)` only when the user gives you literal text
   to say that isn't in a file.
"""


OPERATING_DISCIPLINE = """\
Operating discipline — how to actually get a task done:

- EXECUTE, don't promise. Never end a turn saying you "will" or "can" do
  something — call the tool now. A plan with no tool calls is a failed
  turn.
- One request often needs several tool calls. Keep going until the task
  is genuinely done; don't stop after the first step or hand a checklist
  back to the user.
- For a task with 3+ steps, make a brief internal plan, then call the
  real work tools. Use `todo` only when the user asks for task tracking
  or the task is long enough that a visible checklist materially helps.
- Independent tool calls in the same turn can be issued together —
  prefer that over a slow round-trip each.
- Before editing a file, read it first. Before importing a package,
  check it is installed.
- A failed tool call is information: read the error, fix the cause, then
  retry. Never repeat the exact same call unchanged.
"""


RUNTIME_TAIL_BASE = """\
The only writable area is the sandboxed `skills/` directory of your
instance. All "path" arguments to file tools are relative to that root.
Do NOT prefix paths with "skills/", "~", or any absolute path. If the
user asks to save somewhere else (Desktop, Downloads, etc.), still save
to skills/ and explain where it actually went.

Behavior:
- Use tools to fulfill requests. Each tool has a typed signature; pass
  arguments that match.
- If the request is genuinely beyond every toolset, say so honestly —
  don't invent a tool error or pretend a tool ran when it didn't.
- After a tool returns, decide whether the user's request is fully
  answered. If yes, write the SHORTEST possible reply — often just one
  sentence, sometimes just the value. Never restate the question. Bare
  facts only.
- If the user explicitly asked for a follow-up action ("and speak it",
  "then save it"), call the next tool.
- After authoring or modifying skill files, call `reload_skills()` so
  the loader registers your new code.
"""

RUNTIME_TOOLSET_SCOPED = """\
- You see a focused CORE set of tools. If a task needs a capability you
  don't see a tool for, call `load_toolset` to make the right group
  visible BEFORE concluding you can't do it — the tools you need are
  one `load_toolset` call away.
"""

RUNTIME_TOOLSET_UNSCOPED = """\
- The full built-in tool surface is visible. Pick the specific tool that
  matches the request; do not call `load_toolset` unless you are explicitly
  asked to inspect or widen toolsets.
"""


_SOUL_MAX_CHARS = 4000


def _load_soul(layout: InstanceLayout) -> str:
    """Read the optional per-instance ``soul.md`` — a free-form character
    / voice document the user hand-writes. It complements identity.yaml:
    identity.yaml carries the structured facts (name, role, voice_id),
    soul.md carries the prose voice and character. Absent ⇒ ``""``.

    User-owned and read-only to the agent (same posture as identity.yaml);
    capped so a long file can't crowd out the routing imperatives."""
    try:
        path = layout.root / "soul.md"
        if not path.is_file():
            return ""
        text = path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
    if len(text) > _SOUL_MAX_CHARS:
        text = text[:_SOUL_MAX_CHARS].rstrip() + "\n…(soul.md truncated)"
    return text


def _runtime_tail() -> str:
    try:
        from .toolsets import _scoping_enabled
        scoped = _scoping_enabled()
    except Exception:
        scoped = False
    toolset_note = RUNTIME_TOOLSET_SCOPED if scoped else RUNTIME_TOOLSET_UNSCOPED
    return RUNTIME_TAIL_BASE.strip().replace(
        "Behavior:\n",
        "Behavior:\n" + toolset_note.strip() + "\n",
        1,
    )


def build_system_prompt(layout: InstanceLayout) -> str:
    """Assemble the agent's system prompt.

    Default is lean — identity + 4 MANDATORY rules + runtime tail. The
    115-line v2 self-improvement contract is OFF by default because it
    tripled prompt size and was diluting routing accuracy on Gemma 4 in
    benchmarks. Flip `skills.include_self_improvement_contract: true` in
    the instance config when the agent is actively authoring skills.
    """
    parts: list[str] = []
    try:
        from . import memory as mem
        ident_blurb = mem.load_identity_string(layout)
    except Exception:
        ident_blurb = ""
    if ident_blurb:
        parts.append(ident_blurb)

    # soul.md — optional free-form character/voice doc, right after the
    # structured identity so it reads as "and here is how I speak".
    soul = _load_soul(layout)
    if soul:
        parts.append(soul)

    parts.append(MANDATORY_TOOL_RULES.strip())
    parts.append(OPERATING_DISCIPLINE.strip())

    include_v2 = False
    try:
        from .schemas import Config, load_yaml
        cfg = load_yaml(layout.config_path, Config)
        include_v2 = cfg.skills.include_self_improvement_contract
    except Exception:
        include_v2 = False

    if include_v2 and CORE_PROMPT_PATH.exists():
        parts.append(CORE_PROMPT_PATH.read_text(encoding="utf-8").strip())

    parts.append(_runtime_tail())
    return "\n\n".join(parts)
