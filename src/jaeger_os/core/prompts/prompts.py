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

from jaeger_os.core.instance.instance import InstanceLayout


# core/prompts/ sits two levels deeper than the framework root; the
# prompts/ resource dir (with the .md file) is a sibling of core/ — confusingly
# also named ``prompts`` but at the jaeger_os/ level.
CORE_PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "agent_system_prompt.md"


JAEGER_OS_CONTEXT = """\
Your system — Jaeger OS (JROS): a local-first agentic assistant
framework. It hosts you as a persistent agent with your own instance on
this machine — your identity, a skill library, durable memory,
scheduling, and a local toolset (files, terminal, web, vision, and more).
The language model is only the engine that runs you; Jaeger OS is the
system you run on, and the name and persona above are who you are. When
asked what you are, the answer is Jaeger OS — never the base model.
"""


MANDATORY_TOOL_RULES = """\
Mandatory tool rules — these are not suggestions:

1. PERSISTING FACTS. If the user states a preference, identity fact,
   plan, or anything they might want recalled later ("remember that…",
   "my favorite X is…", "I'm allergic to…", "I'll be in town on…"),
   you MUST call `memory(action="remember", key=…, value=…)`.
   Acknowledging in free-text ("OK, I'll remember") without calling the
   tool is forbidden — it is lying.

2. RECALLING THE PAST. Each session starts with a CLEAN context —
   earlier sessions are NOT replayed into the conversation. Anything from
   before THIS session lives only in memory, so you must go get it rather
   than assume it or claim you don't have it:
   • A fact the user told you ("when's my birthday?", "what's my
     favorite X?", "do you remember…") → call `memory(action="recall",
     key=…)`, then `memory(action="search", query=…)` if recall misses.
   • A past CONVERSATION ("what did we discuss about…", "that thing I
     mentioned last week", picking an earlier topic back up) → call
     `search_memory(query=…)`.
   Do this BEFORE answering. The persisted store is the source of truth
   across sessions; never answer "I don't have that" without searching.

3. FORGETTING FACTS. "Forget my X", "remove my X preference", "I changed
   my mind about X" all require `memory(action="forget", key=…)`. Don't
   free-text acknowledge.

4. NARRATING FILES. "Read X out loud", "narrate X", "speak X as if for a
   video" with a NAMED FILE means: call `text_to_speech(path="X")`. Use
   `text_to_speech(text=...)` only when the user gives you literal text
   to say that isn't in a file.
"""


OPERATING_DISCIPLINE = """\
Operating discipline — how to actually get a task done:

- ANSWER THE CURRENT MESSAGE. Act only on what the user is asking right
  now. Earlier turns in the conversation are context for continuity —
  some may be resumed from a past session and are already finished.
  Never pick up, resume, or re-run a task from an earlier turn unless the
  user's current message explicitly asks for it. If a past turn left
  something open and you are unsure, ask — do not just do it.
- EXECUTE, don't promise. Never end a turn saying you "will" or "can" do
  something — call the tool now. A plan with no tool calls is a failed
  turn.
- One request often needs several tool calls. Keep going until the task
  is genuinely done; don't stop after the first step or hand a checklist
  back to the user.
- For a task with 3+ steps, make a brief internal plan, then call the
  real work tools. Use `todo` only when the user asks for task tracking
  or the task is long enough that a visible checklist materially helps.
- CHECK FOR A SKILL FIRST. Before improvising a non-trivial or
  specialized task with raw tools, call `skill(action="search",
  query="…")`. JROS ships a library of experienced playbooks — driving
  the Mac, making a video, inspecting a codebase, and many more. If one
  matches, `skill(action="view", name="…")` and FOLLOW its instructions
  and notes; they encode the right approach, the gotchas, and the safe
  order of steps. Blindly chaining tools when a skill exists wastes the
  turn and skips hard-won guidance.
- PROPOSE A SKILL afterwards. If you finished a non-trivial task that
  had NO matching skill and is worth repeating, call
  `propose_deep_think_task("…")` with a short description. It queues a
  skill-development task for the user to approve and Deep Think to build
  later — that is how the library grows. You propose; the user decides.
- Independent tool calls in the same turn can be issued together —
  prefer that over a slow round-trip each.
- Before editing a file, read it first. Before importing a package,
  check it is installed.
- A failed tool call is information: read the error, fix the cause, then
  retry. Never repeat the exact same call unchanged.
"""


RUNTIME_TAIL_BASE = """\
File access — you read widely, you write narrowly:
- READING is unrestricted. `read_file`, `list_skill_dir` and
  `search_files` can view ANY file or directory on this machine — your
  own source code, the whole repository you run from, the wider system.
  Pass an absolute path (or `~/...`) to read or browse outside your
  instance. You have full visibility — use it.
- WRITING is sandboxed. `write_file`, `append_file`, `patch` and
  `delete_file` only write inside your instance's `skills/` directory;
  their `path` arguments are relative to that root, with no `skills/`,
  `~`, or absolute prefix. If the user asks to save elsewhere, save to
  skills/ and say where it went — unless you have been granted
  permission to write to that other location.

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
- Write for a plain terminal. Do NOT use Markdown emphasis — no
  **double-asterisk bold** and no *italics*; the asterisks render
  literally and look broken. Plain sentences, short plain-text headings,
  and simple `|`-column tables are fine — just never the `**`.
"""

RUNTIME_TOOLSET_SCOPED = """\
- You see a focused CORE set of tools. The categories below list every
  OTHER tool that's installed but not currently in your active set.
  Two ways to reach them:
    • `describe_tool("name")` — peek at one tool's exact schema
      without loading anything. Cheap. Use this when you just need to
      know "can I call X?" or "what args does X take?"
    • `load_toolset("category")` — add a whole category to your
      active set for the rest of the session. Use this when you'll
      need several tools from the same area.
  Tools you don't see do NOT mean a capability is missing — it just
  means it's one `describe_tool` or `load_toolset` call away.
"""


def _build_toolset_catalog() -> str:
    """A compact tool catalog: every loadable toolset → one-line summary.

    Lives at the end of the runtime tail so the model has a stable
    answer to "what capabilities exist?" without us shipping all 70+
    tool schemas every turn. Built-in classes appear first; runtime-
    registered skill toolsets follow. Empty string if no scoping is
    on (full surface visible — the catalog would just duplicate the
    schemas the adapter already sends)."""
    try:
        from jaeger_os.core.skills.toolsets import (
            _scoping_enabled, all_toolsets, TOOLSET_SUMMARY,
        )
    except Exception:
        return ""
    if not _scoping_enabled():
        return ""
    rows = all_toolsets()
    if not rows:
        return ""
    # Built-in classes first (stable order), then skill toolsets.
    builtin = [(k, rows[k]) for k in TOOLSET_SUMMARY if k in rows]
    skills = [(k, v) for k, v in rows.items() if k not in TOOLSET_SUMMARY]
    lines = ["TOOL CATALOG — categories you can describe_tool / load_toolset:"]
    for name, summary in builtin + skills:
        lines.append(f"  • {name:<14} — {summary}")
    return "\n".join(lines)

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
        from jaeger_os.core.skills.toolsets import _scoping_enabled
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
        from jaeger_os.core.memory import memory as mem
        ident_blurb = mem.load_identity_string(layout)
    except Exception:
        ident_blurb = ""
    if ident_blurb:
        parts.append(ident_blurb)

    # What system the agent runs on — so it can answer "what are you" with
    # Jaeger OS, not the base model, even on a model with strong self-identity.
    parts.append(JAEGER_OS_CONTEXT.strip())

    # soul.md — optional free-form character/voice doc, right after the
    # structured identity so it reads as "and here is how I speak".
    soul = _load_soul(layout)
    if soul:
        parts.append(soul)

    parts.append(MANDATORY_TOOL_RULES.strip())
    parts.append(OPERATING_DISCIPLINE.strip())

    # A compact index of the available playbook skills, so the model knows
    # what specialized procedures exist without a discovery round-trip.
    # Platform-filtered + config-disabled skills are already excluded.
    try:
        from jaeger_os.core.skills.playbook_skills import build_skill_index
        skill_index = build_skill_index()
        if skill_index:
            parts.append(skill_index)
    except Exception:  # noqa: BLE001 — skill discovery must never break boot
        pass

    include_v2 = False
    try:
        from jaeger_os.core.instance.schemas import Config, load_yaml
        cfg = load_yaml(layout.config_path, Config)
        include_v2 = cfg.skills.include_self_improvement_contract
    except Exception:
        include_v2 = False

    if include_v2 and CORE_PROMPT_PATH.exists():
        parts.append(CORE_PROMPT_PATH.read_text(encoding="utf-8").strip())

    parts.append(_runtime_tail())

    # Tool catalog — only appears when scoping is on; tells the model
    # which categories exist beyond its current visible set so it can
    # describe_tool / load_toolset deliberately.
    catalog = _build_toolset_catalog()
    if catalog:
        parts.append(catalog)

    assembled = "\n\n".join(parts)

    # Three Laws — prepended as the very first block in the system
    # prompt so the model sees the safety frame before identity, rules,
    # tool instructions, or anything else. ``with_three_laws`` is
    # idempotent, so a caller that has already wrapped its own prompt
    # (e.g. a delegated sub-agent) doesn't double the block.
    try:
        from jaeger_os.core.safety.safety_rules import with_three_laws
        assembled = with_three_laws(assembled)
    except Exception:  # noqa: BLE001 — never break boot over a safety wrap
        pass
    return assembled
