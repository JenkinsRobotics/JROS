# Jaeger-OS — Pipeline Runtime-Verification Status

**Date:** 2026-05-22
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

**Test suite: 533 passing.**
