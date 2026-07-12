# 0.9 step 4 — the four-way split file map

> Written BEFORE any `git filter-repo` run, per the operator's staging
> order. Source: JROS branch `0.9.0`, head `0388e67` (steps 1-3 landed:
> contract package, CI layering rule, mind-as-module). Every top-level
> path in the repo is assigned a destination repo + destination path +
> rationale below. Mixed directories get a sub-rule instead of a blanket
> call. Hard calls the operator flagged by name get their own section
> with reasoning. Anything this agent could not resolve with the
> evidence in-repo is marked **OPERATOR-DECISION** — staging works
> around those with the stated default and does not block on them,
> but they need the operator's word before a real push.

Four destination repos (GitHub names as already created per
`.superpowers/sdd/progress.md`'s "OPERATOR AUTHORIZED THE SPLIT" entry):

| repo | role |
|---|---|
| **JaegerOS** | the framework — Bus/Node/modules/slots/supervisor/safety/contract/capability layer. Libraries + standards + tooling; other repos pin it, never fork it. |
| **JaegerAI** | the turnkey product (the Mind) — loop, tools, skills, memory, persona, local inference, AND its own faces (chat app, TUI, voice, protocol). Ships `main.py` + the `jaeger` command. |
| **JaegerKokoroTTS** | the TTS engine module — 2 real consumers now (JaegerAI product + JP01 non-AI console), slot contract frozen. Pins JaegerOS only. |
| **JaegerWhisperSTT** | the STT engine module — same trigger, same pin rule. |

**Naming note (flag, not blocking):** `Jaeger-Template`'s README
Ecosystem-links section writes the product repo as `Jaeger-AI` (hyphen);
`progress.md`'s "OPERATOR AUTHORIZED THE SPLIT" entry and this task's
brief both write `JaegerAI` (no hyphen) as the name already created on
GitHub. This map uses `JaegerAI` (matches what's actually created) and
flags the template's README link text as needing a one-line fix during
the overlay in Phase B. **OPERATOR-DECISION** only if the actual GitHub
repo turns out to be named `Jaeger-AI` — confirm before push.

---

## 1. Top-level path map

| source path | destination | dest path | rationale |
|---|---|---|---|
| `jaeger_os/contract/` | JaegerOS | `jaeger_os/contract/` | the one wire truth; imports nothing (AST-enforced). Named explicitly. |
| `jaeger_os/transport/` | JaegerOS | `jaeger_os/transport/` | Bus/broker/codec — framework substrate. Named explicitly. |
| `jaeger_os/nodes/base.py`, `nodes/runtime.py`, `nodes/testing.py`, `nodes/__init__.py`, `nodes/README.md` | JaegerOS | `jaeger_os/nodes/` | the Node base class + module/slot runtime singleton — framework. Named explicitly ("nodes/base+runtime+module system"). |
| `jaeger_os/nodes/motor/`, `nodes/light/`, `nodes/vision/` | JaegerOS | `jaeger_os/nodes/{motor,light,vision}/` | **not named explicitly by the operator brief — resolved by evidence.** Each `__init__.py` states "JROS library stays vague/universal... hardware-specific wire formats land at INSTANCE level" — same generic-body-abstraction shape as `hardware/`, zero agent coupling, zero product-specific content. These are framework node *types*, not shipped product modules (unlike animation/media/kokoro/whisper, none of which are generic — they're one concrete implementation each). Placed with `hardware/`. |
| `jaeger_os/nodes/kokoro_tts/` | JaegerKokoroTTS | `jaeger_kokoro_tts/` (repo-named package, see Phase B packaging) | named explicitly; 2-consumer trigger fired. |
| `jaeger_os/nodes/whisper_stt/` | JaegerWhisperSTT | `jaeger_whisper_stt/` | named explicitly; same trigger. |
| `jaeger_os/nodes/animation/`, `nodes/animation_dev/`, `nodes/media/` | JaegerAI | `jaeger_ai/nodes/{animation,animation_dev,media}/` | named explicitly ("product-shipped modules" — one consumer, not yet split-triggered per `THREE_TIER_STRUCTURE.md`'s split triggers). |
| `jaeger_os/hardware/` (incl. `packages/jp01/`) | JaegerOS | `jaeger_os/hardware/` | named explicitly. `hardware/packages/jp01/` is the reference hardware package shape (boot/capabilities/topology.yaml) — stays here as the in-tree reference until JP01_Firmware goes fully out-of-tree (0.9 step 5, not this step). |
| `jaeger_os/app/` | JaegerOS | `jaeger_os/app/` | named explicitly — the manifest/supervisor/surfaces framework (`jaeger.toml` schema: "what this app IS MADE OF"). |
| `jaeger_os/core/` | **SPLIT** | — | see §2, the largest mixed directory. |
| `jaeger_os/cli/` | **SPLIT** | — | see §3. |
| `jaeger_os/agent/` | JaegerAI | `jaeger_ai/agent/` | named explicitly — the Mind. |
| `jaeger_os/interfaces/` (all of `avatar/`, `avatar_chat/`, `avatar_player/`, `pyside6/`, `swift/`, `tui/`) | JaegerAI | `jaeger_ai/interfaces/` | named explicitly — "all faces." |
| `jaeger_os/plugins/` (discord/, imessage/, telegram/, homeassistant/, mcp/, ai_gen/, `messaging_gateway.py`, `registry.py`, `manifest.py`, `voice_loop.py`, `_messaging.py`) | JaegerAI | `jaeger_ai/plugins/` | named explicitly. Each is a Mind-consumed capability (messaging channels, HA control, MCP client, AI-gen) — none are generic framework substrate. |
| `jaeger_os/personality/` | JaegerAI | `jaeger_ai/personality/` | named explicitly — characters are the Mind's souls. |
| `jaeger_os/skill_tree/` | JaegerAI | `jaeger_ai/skill_tree/` | **not named explicitly — resolved.** Persists to `<instance>/skill_tree.json`, awards XP for agent skill use — instance-scoped Mind state, same bucket as `agent/skills`. No framework code reads it. |
| `jaeger_os/timeline/` | JaegerAI | `jaeger_ai/timeline/` | **not named explicitly — resolved.** Persists to `<instance>/timelines/*.json`, is the MScript scene-sequencing schema consumed by the avatar/animation faces — those are already JaegerAI ("all faces"), and `nodes/animation` (its other consumer) is JaegerAI too (product-shipped, one consumer). |
| `jaeger_os/migrations/` | JaegerOS | `jaeger_os/migrations/` | **not named explicitly — resolved, low-confidence.** Currently empty (`__init__.py` + README only) but the README's own tier label reads "Modification tier C: Framework core" and the mechanism (versioned migration scripts against instance-directory schema) is framework-generic. **Soft flag:** once real migration scripts land and touch AI-owned schema fields (identity/persona/memory), re-litigate whether the *mechanism* should move with `core/instance/` to JaegerAI — empty today, so no data to move, low stakes either way. |
| `jaeger_os/models/` (top-level, `README.md` only — not `core/models/`) | JaegerOS | `jaeger_os/models/` | just a placeholder README today (`jaeger_os/models/README.md`); the real GGUF-weight-cache directory shape it documents is where any project stores model weights. Framework-generic, near-empty — trivial move. |
| `jaeger_os/skill_tree`, `timeline` covered above | — | — | — |
| `jaeger_os/assets/` | JaegerAI | `jaeger_ai/assets/` | app icons + agent portrait — product branding, used by the faces (tray icon, Swift app icon). No framework code references these. |
| `jaeger_os/docs/agent_contract.md` | JaegerAI | `jaeger_ai/docs/agent_contract.md` | describes the agent's own contract surface (generated by `dev/scripts/generate_agent_contract.py`, an AI-facing doc) — content-verified, not just path-guessed. |
| `jaeger_os/main.py`, `jaeger_os/__init__.py`, `jaeger_os/__main__.py` | JaegerAI | `jaeger_ai/main.py` etc. | named explicitly ("main.py + jaeger launcher"). `main.py` is the agent's boot/turn-loop entry — genuinely product, not framework (progress.md step 2+3 entry: "bringup code in main.py is project-tier and exempt by definition"). **Package rename note:** since the top-level Python package is literally named `jaeger_os` today, JaegerAI's copy needs a package rename (`jaeger_ai` or similar) during Phase B's template overlay to avoid two unrelated PyPI-shaped packages both claiming the `jaeger_os` import name — see Phase B packaging notes. |
| `jaeger` (root wrapper script), `install.sh`, `scripts/install.sh`, `scripts/README.md` | JaegerAI | repo root | named explicitly ("jaeger launcher + install.sh"). The installer builds a product-only install (`scripts/install.sh`'s own header: "one-line installer (builds a CLEAN, product-only install)") — it is provisioning the AI product, not the framework library. `jaeger` wrapper delegates to `cli/entry.py`, which is JaegerAI (see §3). |
| `run.sh`, `jaeger.toml`, `jaeger.windowed.toml` | JaegerAI | repo root | project-tier bringup config for *this* instance (the desktop-companion project folded into JaegerAI today per `THREE_TIER_STRUCTURE.md` "Where we are vs the model") — these are the manifest/launch files for the shipped product, not framework library config. |
| `clients/` | JaegerAI | `clients/` | named explicitly — the product's SDK. Confirmed by content read: `jros_client.py` drives an *existing JROS install* by spawning `jaeger bridge` (a JaegerAI CLI verb) over NDJSON — it is a client of the product, not the framework. |
| `dev/benchmark/` (incl. `results/`, `scenarios.py`, `bench.py`, `persona_eval.py`, etc.) | JaegerAI | `dev/benchmark/` | named explicitly ("benchmarks/evals"). The routing/scenario/persona benches all drive the live agent loop — meaningless without the Mind. |
| `dev/docs/` | **SPLIT** | — | see §4. |
| `dev/tests/` | **SPLIT** | — | see §5. |
| `dev/infographic/`, `dev/reference_ui/` | JaegerAI | `dev/{infographic,reference_ui}/` | pipeline diagrams (STT/LLM/TTS, avatar 2D/3D, lip sync) and UI mood-board references — all describe the product's voice/avatar faces, not the framework. |
| `dev/pipelines/` (the doc-generator scripts: `plugins.py`, `tracing.py`, `media.py`, `tts.py`, `avatar.py`, `nodes.py`, `gui.py`, `stt.py`) | JaegerAI | `dev/pipelines/` | these render the `dev/docs/pipelines/*.md` live-reference docs, all of which describe agent/product pipelines (verified: turn loop, skill discovery, memory, persona, voice, model inference) — the doc-generation tooling follows its output. |
| `dev/scripts/` | **SPLIT** | — | `run_tests.sh`, `dev_env.sh`, `check_wheel.py` are generic dev-loop tooling → **duplicated** into both JaegerOS and JaegerAI (each repo needs its own test-runner/wheel-check; these are thin enough that a fork-and-diverge is cheaper than a shared dep). `node_verification.py`, `generate_agent_contract.py`, `lilith_demo.py`, `tts_node_test.py` are agent/product-specific (contract doc generator, demo script, node smoke test against the live agent) → JaegerAI. |
| `dev/tools/audio_smoke/` | JaegerAI | `dev/tools/audio_smoke/` | live voice-assistant smoke scripts — exercise the full agent+voice loop, not the framework in isolation. |
| `.superpowers/` | JROS (stays) | — | named explicitly — stays in JROS, the working/dev repo. Not part of the split; each of the 4 new repos starts its own `.superpowers/` fresh if they adopt the skill later (out of scope here). |
| `.claude/`, `.run/` | JROS (stays) | — | local dev-session state (settings, child-process registry) — not source, not shipped, gitignored-adjacent. Does not travel. |
| `.github/` | n/a | — | does not exist in JROS today (confirmed: no workflows). Each of the 4 new repos gets `.github/workflows/ci.yml` fresh from the `Jaeger-Template` overlay in Phase B, not filtered from JROS. |
| `pyproject.toml`, `requirements.txt` | **SPLIT** | — | see Phase B packaging — each repo gets its own, hand-written against the template's `pyproject.toml.example`, not filter-repo'd (the source file mixes all four repos' deps today). |
| `README.md`, `CHANGELOG.md`, `LICENSE`, `VERSION` (no VERSION file exists at JROS root today — versions are read from `jaeger_os/__init__.py`) | **SPLIT/rewrite** | — | each repo authors its own README from the template (see Phase B); `CHANGELOG.md` is JROS's own release history — **not filter-repo'd verbatim** (it's one merged product+framework changelog). Each new repo starts a fresh `CHANGELOG.md` at the split commit; JROS's existing `CHANGELOG.md` stays in JROS as the historical record. `LICENSE` (Apache-2.0) copies to all four unchanged (template default already matches). |
| `.gitignore`, `.gitattributes` | **SPLIT/rewrite** | — | each repo gets the template's `.gitignore`/starting point, hand-adjusted per repo's actual build artifacts (Swift `.build/`, Python `__pycache__`, model caches for JaegerOS/engine repos, `.jaeger_os/` instance state for JaegerAI). Not mechanically split from JROS's merged one. |
| `.jaeger_os/` (instance runtime state — models cache, `.jaeger_os/instances/jros-dev/`) | n/a | — | **gitignored, not tracked in git.** Confirmed via `.gitignore` (`.jaeger_os/` entry). Excluded from every clone/filter-repo run already — it's the live operator state, never in history. This is what Phase C's instance-boot-identical gate operates on (a COPY of this dir, never the original). |
| `dev/docs/roadmap/SPLIT_FILE_MAP.md` (this file) | JROS (stays) | — | the staging plan itself is JROS/process history, not code any of the 4 repos ship. |

---

## 2. `jaeger_os/core/` split (the hard call named explicitly)

`core/` is NOT monolithically framework, despite the directory name. The
operator's brief resolves `core/audio` and `core/tools` explicitly and
flags `core/voice` as a hard call; everything else in `core/` needed
per-file content verification (docstrings read for all ~50 files) because
`THREE_TIER_STRUCTURE.md`'s Refinement #1 is explicit that "memory, model
loading, persona, sessions" are Mind-owned even when they physically sit
under `jaeger_os/core/` today (a historical accident of the monolith, not
a designed boundary).

**Stays JaegerOS** (framework substrate — read every file's header to confirm zero agent-identity/persona coupling):

| path | why |
|---|---|
| `core/audio/` (`session.py`, `aec.py`, `chimes.py`, `reference_buffer.py`) | **named explicitly by the operator.** Confirmed: this is the audio I/O session library (mic/speaker session, echo cancellation, chimes) — both engine repos (Kokoro/Whisper) AND JaegerAI depend on it, so it must sit below all three, i.e. in JaegerOS. |
| `core/tools/` (`tool_registry.py`, `arg_coercion.py`) | **named explicitly by the operator** — moved here in 0.9 step 2 for exactly this reason (see the module's own docstring: "the registry is a shared substrate multiple producers write into... hardware capabilities register as tools without importing agent/"). It is the tool CONTRACT, confirmed by content, not just by the step-2 changelog line. |
| `core/voice/` (`voice_resolution.py`, `farewell.py`, `reply_cleaner.py`, `non_speech.py`) | **flagged as a hard call by the operator — resolved JaegerOS.** `voice_resolution.py` was moved out of `agent/tools/speak.py` in the *same* 0.9 step-2/3 CI-dependency-rule pass as `core/tools`, for the identical reason: `nodes/runtime.py` (framework) needed to resolve which voice/engine module serves a slot WITHOUT importing `agent/`. It is the framework's slot-resolution helper for the voice path, called from `nodes/runtime.py`, not from `agent/`. |
| `core/modules.py` | **not separately named, but unambiguous.** `discover_modules()` — the module/slot loader — is literally "the module system," which the operator's brief names as a JaegerOS target alongside `nodes/base+runtime`. |
| `core/context.py` | Shared tool-dispatch infrastructure (path sandboxing, audit logger, git auto-commit helper) used across all tool categories. Content-verified generic — no persona/identity coupling — but it IS consumed almost entirely by agent tools today. **Soft flag:** if JaegerAI's tool files turn out to be the only real caller after staging's suite gate runs, this should move with them; kept here provisionally because the audit-log + sandbox mechanism is described as framework-tier safety substrate ("Anything used by 2+ tool files"), matching `core/safety/`'s placement below. Re-verify against Phase C's layering-assert gate output. |
| `core/safety/` (`command_guard.py`, `file_safety.py`, `permissions.py`, `redact.py`, `safety_rules.py`, `session_trust.py`, `osv_check.py`) | Confirmed by content: the 6-tier permission decorator, the hardline command blocklist, credential-path blocklist, redaction, and per-session trust model are all described as protecting the **capability dispatcher** ("the e-stop lives below the Mind... EStopLatch at the capability dispatcher + transport chokepoint" — `THREE_TIER_STRUCTURE.md` law 2) — i.e., they must be enforceable even for hardware capability calls that never touch `agent/`. This is the nervous-system safety floor, framework-tier by design. |
| `core/safety/skills_guard.py` | **exception inside `core/safety/`** — moves to JaegerAI instead. It scans *skill* files (playbook `SKILL.md` / code skills) specifically, and skills are agent-owned (`agent/skills/`, `agent/skill_registry/`) — this guard has no meaning without the Mind's skill loader as a caller. Placed with `agent/skill_registry/` in JaegerAI. |
| `core/diagnostics/probe.py` | The lean substrate probe (layout, file sandbox, memory round-trip, `tool_registry` resolution, time, calculate) checks framework-level plumbing, callable with no model loaded. Stays JaegerOS. |
| `core/diagnostics/doctor.py` | **exception** — moves to JaegerAI. Its own docstring: merges the framework probe with an "optional deep agent-loop" check and is the engine behind `jaeger --doctor`/`jaeger health`, both CLI-product surfaces (§3). Depends on `core/runtime/preflight.py` (below, also JaegerAI) for config/dep checks that are model/voice-specific. |

**Moves to JaegerAI** (Mind-owned state/behavior, content-verified — every file below persists to `<instance>/...` or is read/written only by `agent/`):

| path | why |
|---|---|
| `core/instance/` (`instance.py`, `identity.py`, `persona.py`, `personas.py`, `schemas.py`, `setting_meta.py`, `setup_wizard.py`, `subprocess_env.py`, `procshape.py`) | **the "instance/character data conventions" hard call, resolved.** `instance.py`'s own docstring: "An *instance* is a writable per-robot directory that holds identity, config, memory, logs, skills, credentials" — this is the Mind's own bring-up state, not a generic project-bringup mechanism (compare `THREE_TIER_STRUCTURE.md`: "Projects... own their bringup (topology, config, instance)" — today JaegerAI **is** the project, per Refinement #1, so instance-of-a-Mind lives with the Mind). `identity.py` and `persona.py` are explicitly the character/persona system (persona = "id/ego" per Refinement #1, explicitly Mind-owned). |
| `core/memory/` (`memory.py`, `sqlite_store.py`) | named in Refinement #1 ("memory... AND its own faces") as a core JaegerAI component. Confirmed: `<instance>/memory/state.db`, agent-only reader/writer. |
| `core/models/` (`model_resolver.py`, `llm_client.py`, `mlx_client.py`, `mlx_vlm_client.py`, `engine_registry.py`, `external_model.py`, `external_model_history.py`, `host_recommendation.py`, `lazy_deps.py`, `local_discovery.py`, `model_discovery.py`, `runtimes.py`, `aux_lane.py`) | "local inference" per Refinement #1. Confirmed: GGUF/MLX weight resolution and LLM client wrappers exist only to serve the Mind's inference calls. |
| `core/messages.py` | Bus vocabulary for "the chat path" — confirmed by docstring, this is the surfaces↔agent chat message schema, not a generic transport concern (that's `contract/` + `transport/`). |
| `core/people.py` | Person index the agent builds about who it talks to — explicitly agent-owned per docstring ("profiles of the people the agent INTERACTS with"). |
| `core/sessions.py` | Conversation persistence (`<instance>/memory/sessions.db`) — agent turn history. |
| `core/credentials.py` | `<instance>/credentials/` — instance-scoped, travels with `core/instance/`. |
| `core/runtime/` (`modes.py`, `autonomy.py`, `readiness.py`, `trajectory.py`, `preflight.py`, `cloud_errors.py`, `env_detector.py`, `log_rotation.py`, `process_slot.py`, `tool_interrupt.py`, `usage_stats.py`, `venv.py`, `_shakedown.py`) | Every file content-checked: agent conversational modes (model+voice switching), autonomy/confirmation policy, trajectory export for fine-tuning, readiness warm/probe for LLM/TTS/STT/vision/avatar backends, preflight dep/config checks for the agent's own deps — all Mind-operational, not generic process supervision (that's `app/supervisor.py`, staying JaegerOS). |
| `core/settings/catalog.py` | Walks the `Config` Pydantic model (in `core/instance/schemas.py`, JaegerAI) to render the settings catalog every surface reads/writes — mechanism is generic-shaped but its ONLY schema is the agent's Config; moves with its schema. |
| `core/skill_improvement/` | Skill lifecycle (archive/score/retire) — instance-scoped skill data, agent-owned. |
| `core/bench/` (`runner.py`, `cases.py`, `cases_b.py`, `scenarios.py`) | "drives every case through the live agent loop" per its own docstring — pairs with `dev/benchmark/` (already JaegerAI). |

---

## 3. `jaeger_os/cli/` split

Not named as a single block — the operator's brief names only "cli
runtime verbs" for JaegerOS, implying the rest is elsewhere (consistent
with "main.py + jaeger launcher" being named for JaegerAI). Content
read for every file in `cli/` and `cli/verbs/`.

**JaegerOS** (framework verb *implementations*, importable as a library — see the entry-point note below):
`status_cmd.py` (process/model/voice snapshot), `config_cmd.py` (generic settings-catalog rendering — though its only schema today is agent Config, the renderer itself is schema-agnostic), `runtime_cmd.py` (inference-engine format→backend selection — host capability, not persona), `devtools.py` (the windowed dev-shell/`.app` builder), `verbs/kill_verb.py`, `verbs/launcher_verb.py`, `verbs/autostart_verb.py`, `verbs/update_verb.py`, `verbs/uninstall_verb.py`, `verbs/backup_restore.py`, `verbs/settings_verb.py`, `verbs/dispatch.py` (the verb-dispatch machinery itself).

**JaegerAI** (product/persona-facing verbs, content-confirmed agent-only): `personality_cmd.py`, `prompt_cmd.py` (renders `agent/prompts/assemble.py` output), `roadmap_cmd.py`, `skills_cmd.py`, `instances_cmd.py` (instance = Mind state, follows `core/instance/`), `avatar_cmd.py`, `verbs/memory_verbs.py`, `verbs/skill_verbs.py`, `verbs/bench_compare_verb.py`, `verbs/bench_history_verb.py`, `verbs/instance_verbs.py`, plus `cli/entry.py` and `cli/run.py`/`__main__.py` — **the single dispatcher and the `jaeger` console-script registration itself are JaegerAI's**, matching "jaeger launcher" being named explicitly for JaegerAI and Refinement #1 ("Jaeger AI... ships... its own faces").

**OPERATOR-DECISION:** this means `cli/` cannot be filter-repo'd as one directory — it's the one place a straight path-based split produces a *broken* JaegerOS (a library with a dangling verb-dispatch table) unless JaegerAI's `entry.py` is written to `import jaeger_os.cli.{status_cmd,config_cmd,runtime_cmd,devtools}` (as a pinned dependency, same as any other JaegerOS import) and registers those alongside its own verbs. That's a real design decision (how the dispatch table composes across the pin boundary), not a mechanical move. **Default used for staging** (so Phase B isn't blocked): JaegerOS ships `cli/` as an importable module with NO console-script entry of its own (no `[project.scripts]` in its `pyproject.toml`) — it's a library, per "libraries + standards + tooling," not an end-user command; JaegerAI's `entry.py` is the only place `[project.scripts] jaeger = ...` is declared, and it imports the JaegerOS verb modules directly. Confirm this composition shape with the operator before treating it as final — an alternative (JaegerOS ships its own minimal `jaeger-os` command too, for framework-only ops on a non-AI body) is equally defensible and was not ruled out by anything in-repo.

---

## 4. `dev/docs/` split (by tier, per the operator's instruction)

The four narrative sections (confirmed via `dev/docs/README.md`) split
by which repo the doc's *subject* lives in, not mechanically by folder
name — a "reality" doc about the agent loop is JaegerAI's reality, not
JaegerOS's:

- **reality/** — per-doc: `STATUS.md`, `agentic_runners.md`, `memory_architecture.md`, `persona_compiler.md`, `skill_standard.md`, `scenario_bench.md`, `scenario_test_suite.md` → JaegerAI (all describe agent/persona/skill/memory/bench behavior). `naming_conventions.md`, `pipeline_health.md` → **duplicate-and-prune** (both currently describe the whole monolith; each repo keeps the slice that applies, drops the rest, during the Phase B template overlay — not a filter-repo path move). `STRUCTURE.md`, `system_runtime_user.md` → **rewrite, not move.** Both are already stale (STRUCTURE.md self-dates to branch `0.5.0`) and describe the pre-split monolith's layout end to end; each of the 4 repos needs its OWN authored `STRUCTURE.md`/state-boundary doc post-split, using this file as source material. Flagging so nobody filter-repo's a doc that would just be wrong the moment it lands.
- **history/** — append-only log entries stay attached to whichever repo the shipped work belongs to (e.g. `JROS_0.8_M1_KOKORO_TTS_PLAN.md` → JaegerKokoroTTS's own early history if useful, or just stays in JROS as the record — **OPERATOR-DECISION**: does history/ get copied forward into the new repos at all, or does JROS stay the sole historical record and the new repos start clean per the template's "seed STATUS.md with today's date and truth"? Nothing in-repo answers this; the template's replace-checklist implies a clean start. **Default used for staging:** new repos start history-free (template default); JROS keeps 100% of `history/` as-is, uncopied.
- **roadmap/** — `future_backlog.md`, `agentic_skill_pipeline_backlog.md` → JaegerAI (skill pipeline, agent backlog items). `JROS_0.8_CAPABILITY_LAYER_DESIGN.md` → JaegerOS (capability layer is the Mind↔Body connection mechanism, framework-owned per `THREE_TIER_STRUCTURE.md` "the connection rule"). This file itself (`SPLIT_FILE_MAP.md`) stays in JROS.
- **vision/** — `THREE_TIER_STRUCTURE.md` and `framework_vision.md` → **duplicate into all four** (read-only ecosystem context every repo's contributors need) OR stays JROS-only with each repo linking to it — matches `Jaeger-Template/CONVENTIONS.md`'s own pattern ("condensed from `JaegerOS/dev/docs/vision/THREE_TIER_STRUCTURE.md`... read that doc for the full reasoning"), i.e. **JaegerOS is the canonical home**, other repos link out rather than duplicate. Used as the default.

**Engineering areas** (`core/`, `audio/`, `avatar/`, `hardware/`, `infra/`, `skills/`, `pipelines/`, `revision_summaries/`, `archive/`, `library_review/`, `skill_template/` — 74 files total) split by area-owner, same logic as the code split: `hardware/`, `infra/` → JaegerOS; `audio/` → split further per-doc between JaegerKokoroTTS/JaegerWhisperSTT/JaegerOS (voice pipeline shared substrate vs. one engine's own notes); `avatar/`, `skills/`, `pipelines/` → JaegerAI; `core/` docs → split exactly like `jaeger_os/core/` code in §2 (per-doc, by subject: a doc about `core/audio` follows `core/audio`'s JaegerOS placement, a doc about memory/persona follows JaegerAI). `revision_summaries/` (9 files, one per release 0.1.0→0.7.0) and `library_review/` (Hermes/VoiceLLM/JP01/Mochi value reviews) describe the pre-split monolith's whole history — **stay in JROS**, not copied forward (same reasoning as `history/`). `skill_template/` → JaegerAI (skill authoring is agent-owned). `archive/` (1 file, deferred/shelved briefs) → stays JROS.

**This section is intentionally directional, not a literal per-file table** — 74 engineering-area doc files plus ~40 reality/history/roadmap/vision files is a lot of individual judgment calls for a staging pass; Phase B applies the directional rule above and any doc landing in the wrong repo is a cheap `git mv` later, unlike code (which the suite/bench gates will actually catch if misplaced).

---

## 5. `dev/tests/jaeger_os/` split

Mirrors the source split exactly (each test dir mirrors its `jaeger_os/` counterpart), with the same per-file resolution applied where the source was mixed:

| test dir | destination | note |
|---|---|---|
| `contract/`, `transport/`, `hardware/`, `app/`, `migrations/` | JaegerOS | mirrors §1 |
| `nodes/` | **split** | tests for `base.py`/`runtime.py`/motor/light/vision → JaegerOS; tests for `animation`/`animation_dev`/`media` → JaegerAI; tests for `kokoro_tts` → JaegerKokoroTTS; tests for `whisper_stt` → JaegerWhisperSTT (19 files total, split by which node dir they import) |
| `core/` (85 files — the biggest bucket) | **split exactly per §2's file table** | e.g. `test_audio_session.py`-shaped tests → JaegerOS, `test_memory*.py`/`test_instance*.py`/`test_model*.py`-shaped tests → JaegerAI. Requires a per-file pass at filter-repo time (import-grep against §2's table, not manual). |
| `cli/` (14 files) | **split per §3's table** | same import-grep approach. |
| `agent/`, `personas/`, `personality/`, `plugins/`, `skills/`, `skill_tree/`, `timeline/`, `interfaces/`, `main/` | JaegerAI | mirrors §1/§2. |

**Gate implication (Phase C #1):** JaegerOS's test subset after this split must be runnable standalone with NO agent/ import reachable — that's exactly what the layering-assert gate (Phase C #4) checks from the other direction. If any test file resists clean classification (imports both a JaegerOS-only and JaegerAI-only symbol), that test itself is evidence of a layering leak worth fixing before or during staging, not just a mapping problem — flag it rather than force a side.

---

## 6. Packaging cross-reference (detail in Phase B, summarized here)

- JaegerOS: `pyproject.toml` name `jaeger-os`, no path/version dependency on anything else (contract imports nothing; framework imports nothing above it).
- JaegerAI: depends on `jaeger-os` (path dep for local staging, per the template's `pyproject.toml.example` comment: "jaeger-os is not on PyPI yet; until it is, pin via requirements.txt... rather than here").
- JaegerKokoroTTS / JaegerWhisperSTT: depend on `jaeger-os` ONLY — **never** `jaeger-ai`, named explicitly by the operator ("a robot must speak without the AI product"). This is enforced by the same layering-assert pattern as the in-repo CI rule, applied at the packaging-manifest level: neither engine repo's `pyproject.toml`/`requirements.txt` may name `jaeger-ai`.

---

## Summary — OPERATOR-DECISION items (not guessed, need the operator's word)

1. **`cli/entry.py` composition shape** (§3): JaegerAI imports JaegerOS's verb modules directly and owns the sole `jaeger` console-script (used as staging default) vs. JaegerOS also shipping its own minimal command for non-AI bodies. Both defensible; nothing in-repo picks one.
2. **`history/`, `revision_summaries/`, `library_review/`, `archive/` copy-forward** (§4): default used is "stays JROS-only, new repos start clean" (matches the template's replace-checklist framing) — confirm this is intended, since it means 0.1.0–0.8.1's development narrative doesn't travel with the code it describes.
3. **`vision/` duplication vs. link-out** (§4): default is JaegerOS-canonical + other repos link out (matches `CONVENTIONS.md`'s own citation pattern) rather than copying `THREE_TIER_STRUCTURE.md` into all four.
4. **Repo name `JaegerAI` vs `Jaeger-AI`**: `Jaeger-Template`'s README uses the hyphenated form in its Ecosystem-links section; `progress.md` and this task's brief both use the unhyphenated form for the repo already created on GitHub. Confirm the real name before Phase B sets remotes (staging uses `JaegerAI`, matching what's documented as already-created).
5. **`core/instance/migrations.py` / top-level `jaeger_os/migrations/`** (§1, §2): currently empty; low-stakes placement in JaegerOS today, may need to follow `core/instance/` to JaegerAI once real migration scripts touch AI-owned schema. Noted, not blocking.
