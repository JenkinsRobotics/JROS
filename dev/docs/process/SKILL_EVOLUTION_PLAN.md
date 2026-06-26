# Skill self-improvement — notes-journal + Deep Think loop (PLAN)

**Status:** PLANNED (0.6). Phase 1 in progress; phases 2–4 not built. This doc
is a plan — it describes intended behavior, not what the runtime does today.
Each phase ships behind its own verification; nothing auto-applies until phase 2.

## The idea

JROS already has the *machinery* for skill self-improvement (versioned instance
skills, a smoke-test gate, `benchmark_skill` with per-version deltas, the Deep
Think background runner, the skill tree) — but no *loop* that drives it. Hermes
has the loop but does it crudely: every N tool-iterations it forks the live
agent and re-reads the raw turn transcript, then rewrites skills with no
approval, mid-conversation.

We adopt the loop but in a JROS-native, **measured** form:

```
FOREGROUND  (live turns, e4b, voice)
  use a skill  →  agent jots a short post-use note (smooth/slow/issues/failed)
                  → appends to <instance>/memory/skill_notes.jsonl   (cheap, no model)
  notes pile up / a skill keeps misbehaving
                  → agent calls propose_deep_think_task("improve skill X — see its notes")

DEEP THINK / DEEP-SLEEP  (idle or asleep, 26b-a4b-qat — the strong model)
  runner picks up the task when the machine is free
  → reads skill X's accumulated notes → rewrites the recipe (new _vN)
  → RE-MEASURE vs the prior version:
        smoke test       (correctness gate — already in the loader)
        benchmark_skill  (improvement delta — already records to benchmark_history.jsonl)
        next real uses   (does it hold up live? fresh notes)
  → better → keep (new version wins)   |   worse → revert (free; append-only)
  → note the outcome → loop
  apply-vs-propose is governed by the AUTONOMY MODE:
        auto        → auto-approve the task + apply on a passing gate
        scoped/ask  → leave it proposed in the board for operator approval
```

## Why this shape

- **No live impact.** The heavy rewrite runs idle/asleep, never mid voice-turn
  (Hermes forks mid-turn). Foreground stays e4b/fast; the rewrite uses the
  strong deep-think model.
- **Sees cross-use patterns.** Hermes reviews one turn at a time; accumulated
  notes catch "this skill failed the *same way* 3 times" — the best fix signal.
- **Measured, not trusted.** A rewrite only sticks if it passes smoke AND shows
  a positive `benchmark_skill` delta AND holds up in the next uses. This is the
  agent's own "verify, don't confabulate" rule applied to itself; regressions
  roll back for free (append-only versions).
- **Scope = recipe-skills only.** The `nodes/` subsystems and the skill *tree*
  (node-capability XP/mastery) are a separate, longer-term track — not this loop.

## Reuse (most of it already exists)

| Need | Reuse |
|---|---|
| Background work period | Deep Think runner + deep-sleep mode |
| "Agent queues work when it feels it" | `propose_deep_think_task` |
| Approve-vs-auto | board backlog→ready gate, gated by the autonomy mode |
| Write / version / smoke / reload a skill | `file_write` → `<instance>/skills/`, smoke-gate, `reload_skills` |
| "Did it actually improve?" | `benchmark_skill` (score + delta + `benchmark_history.jsonl`) |
| Strong model for the rewrite | deep-sleep already swaps to `26b-a4b-qat` |

**Genuinely new:** (1) the `skill_note` journal, (2) a prompt nudge to journal
notable uses, (3) the threshold/agent-deemed trigger → `propose_deep_think_task`,
(4) the "review notes → rewrite → re-measure → keep/revert" Deep Think task type.

## Safety rails (mostly free)

Sandboxed to `<instance>/skills/` (core is read-only) · append-only `_vN`
versions (revert = stop activating a folder) · smoke-gated (a broken rewrite
never activates) · benchmark-gated (a regression rolls back) · never touches
core/config/identity/memory-internals/credentials. One new bit: run the
guard/exfil scan **before** activating a rewrite, not after.

## Phases

1. **Notes** (this phase) — `skill_note(skill, outcome, note)` write tool +
   `skill_notes(skill="")` read tool + a per-skill journal at
   `<instance>/memory/skill_notes.jsonl` + a prompt nudge. Pure additive; just
   starts capturing signal. Nothing fires yet.
2. **Trigger** — when a skill's notes cross a threshold (count / repeated
   `failed`/`issues`) or the agent deems it, propose a Deep Think skill task.
3. **The Deep Think skill task** — read notes → rewrite `_vN` → smoke +
   `benchmark_skill` re-measure → keep-if-better / revert-if-worse → journal the
   result. Apply-vs-propose by autonomy mode.
4. **Surface** — `jaeger skills notes` / `jaeger skills reviews` so the operator
   sees what was journaled + changed.

## Open decisions (revisit at phase 2)

- Exact trigger threshold (N notes? K repeated failures? both?).
- Phase 2 ships default-OFF + propose-only until watched, then enable `auto`.
- In `auto`: always emit a dimmed "drafted/updated skill X (benchmark +Δ)" notice.
