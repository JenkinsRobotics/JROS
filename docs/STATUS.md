# Jaeger-OS — Pipeline Runtime-Verification Status

**Date:** 2026-05-24 *(baselined for `0.1.0`)*
**Why this doc:** the two hermes-parity audits
(`hermes_tool_skill_audit.md`, `hermes_internals_audit.md`) compare
*features and architecture* — "does JROS have a 6-tier permission
system?" They do **not** verify *runtime correctness* — whether the
wiring actually works end to end. The permission-prompt bug proved the
gap: every audit said permissions = MATCH, but the confirmation flow was
broken because a code-reading audit cannot see a cross-thread wiring
defect. This doc tracks the **runtime** status of each pipeline — what
has actually been exercised and works.

---

## Pipeline matrix

| Pipeline | Audited vs hermes | Runtime-verified | Status |
|---|---|---|---|
| **Permissions** | ✅ tool/skill #1 | ✅ 2026-05-22 | **Fixed.** Two runtime bugs found + fixed: (1) `install_policy` set a `contextvar` the worker thread never inherited → default `DenyAllProvider`; (2) the TUI confirmation read stdin from the worker thread → answers never captured. Now uses hermes's Event pattern. 11 regression tests. |
| **Tools** | ✅ tool/skill audit | ✅ 2026-05-22 | 62 tools register; read-only tools exercised directly; file / memory / shell paths exercised by the shakedown. |
| **Agentic loop** | ✅ internals A1/#5/#6 | ✅ 2026-05-22 | `_run_via_iter` ran 11 turns through the shakedown — tool calls, skip-final, free-text all worked. Mid-tool interrupt (#6) shipped. The R4–R8 rebuild (A1 + A10 + #5 + #11) is still pending. |
| **Security** | ✅ internals A3/A5/A9, #2/#12 | ✅ 2026-05-22 | Tier gating, the hash-chained audit log, and the credential-read guard all verified live by the shakedown (`file_read_denied` on `credentials/`). Redaction / hardline / file-safety unit-tested. |
| **Skills** | ✅ tool/skill #8/#9, A2 | ✅ 2026-05-22 | `computer_use` registered; `reload_skills` ran; the agent authored `note_v1/SKILL.md`, it was written, audited, and git-committed (`agent: write skills/note_v1/SKILL.md`). |
| **Models** | ✅ this session (llama.cpp) | ✅ 2026-05-22 | In-process llama-cpp (Gemma-4 26B-A4B) loads in ~5s and runs turns. ⚠️ see finding F1 (exit teardown). |
| **TUI / interfaces / commands** | ✅ prior session (hermes parity) | ◑ partial | Slash commands unit-tested; the permission prompt fixed + tested. The live REPL needs a real terminal — not auto-verifiable; the user runs it. |
| **Plugins** | ✅ internals Part C | ◑ partial | MCP client + messaging bridges have import smoke tests; not deeply runtime-exercised. |

---

## Findings & fixes — 2026-05-22 runtime sweep

**Fixed:**
- **Permission flow** — `core/permissions.py` (process-global policy fallback so worker threads resolve it) + `interfaces/tui/app.py` (`_TuiConfirmationProvider` rewritten to hermes's Event pattern: the worker posts a request and blocks on a `threading.Event`; the REPL routes the user's next typed line back as the answer). This is *the* bug behind every "confirmation refused" the user hit.
- **`_shakedown.py`** — the runtime harness was itself out of date: it installed no permission policy (so `write_file` and every tier-gated path hit `DenyAllProvider`), carried stale tool-name expectations, and aborted at exit. Now installs an allow-all policy, expectations corrected, and `os._exit`s cleanly.

**Noted — not JROS bugs:**
- **F1 — ggml-metal teardown abort.** The in-process llama-cpp model's Metal context aborts (`GGML_ASSERT` in `ggml_metal_device_free`) if torn down by C++ static destructors at interpreter exit — a known upstream llama.cpp issue (PR #17869). The shakedown now `os._exit`s past it; the long-lived TUI frees the client in `JaegerTUI._shutdown` while the interpreter is alive. **If the TUI is ever seen to exit with code 134, apply the same `os._exit(0)`-after-cleanup mitigation in `main.main()`.**
- **F2 — model routing.** The shakedown's local Gemma-4 prefers `execute_code` over the dedicated `get_time` / `calculate` tools and declined `schedule_prompt`. Model behaviour / prompt-tuning, not a broken pipeline — the tools themselves work.

**Cross-thread bug class — contained.** The permission and mid-tool-interrupt bugs were the same class: the concurrent-TUI rebuild moved turns to a worker thread, and state set on the main thread didn't cross. A sweep for `ContextVar` / `threading.local` found **`permissions._current_policy` was the only `ContextVar` in the codebase** — now fixed with a process-global fallback. `_delegate_depth` is intentionally per-thread. No other landmines of this class remain.

---

## Open work (feature-level, tracked in the audits)

- Main-loop R4–R8 rebuild — internals **A1** (context compression) + **A10** (memory pipeline) + tool/skill **#5** (result formatter) + **#11** (result budget).
- tool/skill **#7** (MCP OAuth), **#10** (tool registry).
- **Daemon split — Phase 2** (move agent into daemon). Phase 1 scaffold (protocol, server, client, lifecycle, tray) shipped in 0.1.0. See `docs/daemon_split_plan.md`.
- **Tool guardrail controller** (review finding #4 — deferred). Loop-backstop still catches the worst case.
- **Parallel tool execution** (review finding #5 — deferred). Read-only / path-disjoint batches.
- **L2 / L3 / L4 bench coverage** with the corrected umbrella-aware scorer. L1 is baselined; deeper levels need a re-run after the scorer's `_UMBRELLA_EQUIVALENTS` map is applied to L2/L3/L4 modules.

---

## 0.1.0 ship-state — what landed this cycle

**Tests:** 997 passing. (Was ~533 at the prior STATUS snapshot.)

**Major adds:**
- **Daemon scaffold + macOS tray** (`src/jaeger_os/daemon/`, `src/jaeger_os/interfaces/tray/`). Lifecycle CLI: `jaeger start | stop | status | restart`. Phase 1.6 tray icon talks to the daemon via the same socket. **Agent still lives in the TUI process** — Phase 2 of the daemon split moves it.
- **Pre-flight context guardrail** (`src/jaeger_os/agent/util/context_guard.py`). Prevents the "Requested tokens exceed context window" hard fail by trimming history before the call; raises typed `ContextOverflow` when even max trim won't fit. Per-tool-result truncator caps oversized payloads. Group-aware trim preserves tool-call/result pairs.
- **Lean tool surface** (`describe_tool`, catalog injection in system prompt) — **opt-in via `JAEGER_TOOLSET_SCOPING=1`**, default OFF per the 0.1.0 bench data. Infrastructure ready, default revert documented in `docs/lean_surface.md`.
- **Kanban grid view** for `/board` — Rich `Columns` + `Panel`, 5-column layout. Replaces the prior vertical list.
- **`remote_terminal` SSH tool** — Tier-4 wrapper around `ssh user@host -- <cmd>` with `BatchMode=yes` + `ConnectTimeout=10` pinned. Inbound covered by plain sshd + tmux (see `docs/remote_access.md`).

**Bug fixes from the 2026-05-24 code review** (see `docs/code_review_2026_05_24.md`):
- `reset_read_tracker()` called at the top of every `run_turn` (was leaking across turns).
- `AgentInterrupted` now sets `last_halt_reason="interrupted"` at both interrupt sites (was empty assistant message with no halt_reason).
- Tool-name normalization runs at the loop boundary against the registered set (was raw drift names landing in dispatch).
- Skip-final short-circuit suppressed when the user prompt has multi-step intent (was prematurely ending chained tasks).
- Permission / safety errors now tag `error_type` + `retryable` + (optional) `required_tier` (was generic stringified exception).
- Three Laws block wraps every system prompt via `with_three_laws()`.
- Tool-time and loop-time captured in `LatencyReport` (was both 0.0).

**TUI status-bar fixes:**
- Loaded ctx (from `client.loaded_ctx`) shown instead of just config ctx.
- `/runtime` surfaces "model trained for up to N tokens — bump config.model.ctx" when loaded < native.
- 0%-gauge bug fixed: estimator now walks both the Phase-9 dict message shape AND the legacy pydantic-ai `msg.parts[].content`.

**Drift parser:**
- Loose `<function=…>` form (Qwen3-Coder emits this without the `<tool_call>` wrapper) is now salvaged. Was leaking tool-call XML into chat text.

**Bench infrastructure:**
- `benchmark/run_model_sweep.py` drives multi-model comparisons; YAML-aware config-swap; multi-level row parser.
- Scorer in `level1_routing.py` accepts umbrella forms (`memory` for the five fine-grained memory verbs, `execute_code` for `run_python`).
- L1 baseline in `benchmark/levels/history/BENCHMARK_v0.1.0_baseline.md`.

**Model recommendation (from `BENCHMARK_v0.1.0_baseline.md`):**

| Use case | Model |
|---|---|
| **Default / voice-interactive** | gemma-4-E4B-it-Q4_K_M (97.1% routing, 1.6s p50, 5.3 GB) |
| Conservative default | gemma-4-26B-A4B-it-Q4_K_M (97.1%, 3.0s p50, 15.7 GB) — current JROS default |
| Deep Think coder | Qwen3-Coder-30B-A3B (94.1%, 3.2s p50, 18.6 GB) — already the configured coder |
| Smallest viable | gemma-4-E2B-it-Q4_K_M (94.1%, 1.2s p50, 3.4 GB) |
