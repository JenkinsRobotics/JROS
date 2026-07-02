# Agentic Skill/Tool Pipeline — Improvement Backlog

Captured 2026-07-01 from a design session. This is the tracking doc for how JROS
routes **tools ↔ tool-skills ↔ playbook skills**, so the threads don't get lost.
Status legend: **[idea]** discussed · **[approved]** agreed, not built · **[done]**.

Vocabulary (verified against the code):
- **Tool** — a callable function (`agent/tools/*.py`), in the one tool registry
  (`agent/schemas/tool_registry.py`, `get_tools()`). ~many.
- **Tool-skill** — a skill that *registers tools* (`computer_use`, `macos_computer`). 2 today.
- **Playbook skill** — a `SKILL.md` process doc, registers **no** tools; surfaced via
  the `skill` tool. 87 today. `PlaybookSkill` already parses name/category/**description**/
  **tags**/path/**fallback_for_tools**/platforms/requires_tools from the SKILL.md.

---

## Status snapshot

- **Confirmed (operator agreed):** P0 process loop · P1 push→pull · P2 enriched
  `skill(list)` · P3 skill-selection trace chip · P4 post-task gap→proposal · P6
  tier metadata · P7 archiving concept · P5 rename *approach*.
- **Mentioned, not yet confirmed:** reliability bench/regression-eval as a formal
  practice · hard enforcement (router/gate) for critical invariants · restore
  `skill_schema_v3.md`.
- **Open decisions (need to discuss):** see the "Open decisions" section at the end.
- **Done:** startup-log agentic-surface line.

---

## P0 — The task process loop (the backbone)

Everything else hangs off a standard task loop:
**`<research → plan → execute → verify → reflect>`**. The operator pictures the
agent following this whenever it performs a (non-trivial) task:
- **research** — check the skill registry (`skill(list)`), gather context.
- **plan** — decide the approach + tool/skill order.
- **execute** — do it.
- **verify** — confirm it worked (this is where reliability evals hook in).
- **reflect** — post-task: propose a new skill on a gap (P4), self-improve, summarize.

This loop is the *vehicle* for P1 (pull-based discovery lives in **research**) and
for process/tool-order adherence. It has to be reliably followed — soft-cued in the
base prompt and/or encoded as the standard process skill; the post-task step (P4)
catches misses. **[confirmed as the model]**

---

## ★ P1 — Skill discovery: push → pull (FIRST FOCUS)

**Problem.** The skill index is injected into the system prompt **every turn**
(`playbook_skills.build_skill_index` → `_format_skill_index`), even for "hey what's
up." Names-only, grouped by category. That's a per-turn token tax that fights the
lean-context philosophy scoping is built on.

**Change.** Flip push → pull. Skills only matter when performing a task, so make
discovery a **research-step action**, not a prompt tax:
- **Trim the always-on index to a one-line pointer**, e.g.: *"For any non-trivial
  task, run `skill(list)` in your research step before acting; follow a matching
  skill, else use tools directly and flag the gap."*
- **Enrich `skill(list)`** (the on-demand catalog, `agent/tools/skills.py`) with
  **description + tier + fallback** — richness costs tokens only when the agent
  actually looks. Conversational turns pay ~nothing.
- Base prompt stays lean.

**Reliability catch.** Pull only works if the agent reliably does the research
step. Scaffold it: the one-line cue (always present, cheap) + the
`<research→plan→execute→verify→reflect>` loop as the standard task process + the
post-task gap check (P4) as the safety net.

**Touches.** `playbook_skills.py` (trim index / repurpose to pointer),
`agent/tools/skills.py` (`skill(list)` output). **[approved]**

---

## P2 — Enriched `skill(list)` output (folds into P1)

`skill(list)` should render, per skill: **name · one-line description · tier ·
fallback** — all from SKILL.md metadata (already parsed). Optionally filter by
platform (`build_skill_index` already accepts `available_tools`). Single source of
truth = the SKILL.md; the catalog is generated, never hand-maintained. **[approved]**

## P3 — Surface skill selection in the trace

`skill(view/use)` **is already a traced tool call** — but it renders as a generic
tool chip. Give it a distinct **"skill: <name>"** chip so the operator can verify
*which* skill the agent consulted, like watching tool choice. Small UI/trace tweak.
(`skill(action="stats")` already gives usage telemetry.) **[idea]**

## P4 — Post-task gap → skill proposal

No such flow exists today (curator only *assesses existing* skills). Add: after a
task, if a **multi-step process** ran **without a matching skill** (no `skill(list)`
hit / N tool calls, no skill), a post-task step proposes *"reusable process, no
skill — draft one?"* — mirroring the self-improvement + post-task summary. Doubles
as the safety net for P1's pull model. Building blocks exist: `skill(action=stats)`,
the curator, skill creation. Missing piece = the gap detector + proposal trigger.
**[idea]**

---

## P5 — Tool-skill rename (NOT a v3 migration)  **[decided 2026-07-01]**

Correction: the two tool-skills **already have real v3 manifests** (`manifest.yaml`,
`schema: jros.skill/v3`, id/version/description). They are **not** legacy stubs
(that warning never fired — `is_legacy_stub` = "manifest synthesised", theirs are
read). The **only** legacy artifact is the folder name `_v1`. So there's **nothing
to migrate** — just rename. No back-compat concern (pre-1.0, no users).
- `git mv computer_use_v1 → computer_use`, `macos_computer_v1 → macos_computer`.
- Fix the **internal absolute imports** (`…skills.macos_computer_v1.engines…` →
  `…skills.macos_computer.engines…`) in planner/macos_computer/engines/tests;
  verify with imports + the smoke tests. (Nothing *outside* imports them — dynamic
  load.)
- **De-overload the naming:** `computer_use` is a skill folder *and* a tool name
  (registered by the macos skill) *and* referenced in the apple playbook. Write the
  native-vs-fallback + primitives-vs-planner relationship in one place (feeds P6/P2).
- Leave `apple/macos-computer-use` as the playbook; point it at the renamed tools.
**[approved — rename + import fixups]**

## P6 — Tier metadata (steers routing)

Add a **`tier`** field to SKILL.md metadata so `skill(list)` (P2) can steer the
pick: `macos_computer` = **native** (high — tailored for macOS), `computer_use` =
**fallback**. Encourages the agent to prefer the native skill over the generic one.
Must be a live consumer (rendered in `skill(list)` + a routing hint), not a dead
field. **[approved]**

## P7 — Skill lifecycle + retirement  **[decided 2026-07-01]**

Three lifecycles, now resolved:
1. **Old packaging** → migrate (P5), NOT archive.
2. **Old *versions* of a live skill** → **git is the history** (pre-1.0, no need
   for a physical per-skill version-archive). A snapshot folder is optional/deferred.
3. **Retired skills** → **`archived: true` in the skill's manifest/frontmatter**;
   discovery **skips archived skills** (like it already skips config-disabled ones
   via `skills.disabled_playbooks`/`enabled_base_skills`). **No folder moves** —
   reversible, travels with the skill, no import breakage. *Drop the earlier
   archive-folder idea.*
- **Enabler (small):** discovery/loader honor an `archived` flag → skip.
- **Curator-driven:** curator can propose retirement (set `archived`). Mirror of
  P4: *gap → create, staleness → retire.*

---

## Reliability / how-we-know (cross-cutting)

The model doesn't "remember" agreed routing — reliability comes from **where the
knowledge lives + enforcement + measurement**:
- **Soft (preferred here):** enrich descriptions/tier/fallback so the right choice
  is the obvious one; encode process in skills/playbooks.
- **Hard (for invariants):** deterministic router / pre-tool gate.
- **Know it sticks:** a **bench case** ("for task X, did it consult skill Y + use
  tools in order Z?") re-run after every self-improvement. Pair self-improvement
  with a **locked regression eval** so it can improve *and* keep agreed behavior.
- **macos vs generic computer-use** specifically: disambiguate the two tool
  descriptions + P6 tier + a preference rule; verify with a bench case.

## P8 — Flatten discovery depth (hardening, post-baseline)  **[idea 2026-07-01]**

The agent shouldn't wade through many layers before it can start a task. Today
the pull path is: lean hint → `skill(list)` → `skill(view)` → *then* work — up to
3 tool round-trips before the first real action. Reduce the depth:
- **Combine layers** where possible — e.g. `skill(search)` could return the recipe
  inline (list+view in one hop), or `skill(list)` could return enough to act, or
  the lean hint could name the few most-relevant skills directly.
- **Merge playbook + skill discovery** into one surface so the agent asks once.
- Goal: fewest hops from "user asks" → "agent acts", without hiding what it needs.
Test the agent AS-IS first (v1.3 baseline) — the skill/workflow failures tell us
where the depth actually hurts — THEN flatten. Pairs with the reliability work
(P4). *Do not implement before the baseline.* **[idea]**

## Housekeeping

- ~~`dev/docs/skill_schema_v3.md`~~ — **[done]** written.

---

## Done this session
- **[done]** Startup log prints the full agentic surface in one line
  (`skill_loader.py`).
- **[done] Phase A — push→pull.** `build_skill_index` → lean always-on hint
  (count + categories + cue; ~349→~136 tokens, complete not truncated).
  `skill(list)` entries enriched with `tier · tools · fallback_for` +
  description. `PlaybookSkill.tier` added (parsed from frontmatter). `tier:
  native` + `fallback_for_tools:[computer_use]` on `apple/macos-computer-use`.
  Data verified in Python; **live agent behaviour test still owed** (does it
  research + route native?).
- **Follow-ups from Phase A:** populate `requires_tools` in each SKILL.md so the
  `tools` field fills in (metadata quality, P2); the **reflect-check** ("skill
  existed and was ignored → flag") for anti-reinvention (P4); tool-skill rename
  (P5).

## Open decisions (need to discuss before building)

1. **P1 pointer wording** — exact one-liner that replaces the always-on index; and
   is the process loop **soft-cued** (prompt) or **soft-enforced** (a checkpoint)?
   *(still open)*
2. ~~**P6 tier scheme**~~ — **RESOLVED:** `tier` + `fallback` live in skill metadata
   (manifest/SKILL.md; `PlaybookSkill` already has `fallback_for_tools`), rendered as
   a **hint** in `skill(list)` — NOT a router (routing stays soft, decision #5).
3. ~~**P5 depth**~~ — **RESOLVED:** no v3 migration (already v3); just rename +
   fix imports.
4. ~~**P7 archiving folder**~~ — **RESOLVED:** `archived: true` metadata flag, not
   folder moves; git holds old versions. (Curator auto-propose-retirement still open.)
5. ~~**Enforcement policy**~~ — **RESOLVED:** everything soft (descriptions/skills/
   tier hints). Hard only per concrete edge case. Precedent for "when hard is right"
   = the existing safety gates (credentials-via-tool, permission tiers).
6. **Reliability practice** — **partly exists:** per-skill `smoke_test.py` +
   `benchmark.py` + keep-better + curator rollback already implement "test → keep
   better / fall back." Open: extend to a **routing/order-level** regression eval?
7. **Curator auto-proposes retirement** vs manual-only? *(still open)*

## Implementation plan (proposed order)

- **Phase A — P1 + P2 (the token win).** Trim `_format_skill_index` → one-line
  pointer; enrich `skill(list)` (`agent/tools/skills.py`) with description + tier +
  fallback (data already parsed). Add the research-step cue. *Contained, 2 files.*
- **Phase B — P7 enabler.** Discovery/loader skip any `archive/` path segment
  (unblocks all archiving). *Small.*
- **Phase C — P6 tier.** Add `tier` to the two tool-skills' metadata; render in
  `skill(list)` (live consumer). *Small; pairs with A.*
- **Phase D — P5 cleanup.** Rename `computer_use_v1`/`macos_computer_v1` → drop
  `_v1` (fix absolute imports; run smoke tests), de-overload naming, point the
  apple playbook at the renamed tools. Decide v3-migration depth first. *Contained
  but import-touching; spec first.*
- **Phase E — P3 + P4.** Trace chip for `skill(view)`; post-task gap→proposal flow.
  *P4 is the biggest (new flow).*
- **Phase F — housekeeping.** Restore `skill_schema_v3.md`; add reliability bench
  cases alongside A–E.

> Separate track (not in this doc): the Swift UI parity work lives in
> `jaeger_os/interfaces/swift/PARITY_PLAN.md`.
