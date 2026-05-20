# Jaeger-OS 0.1.0 — full verification benchmark

Run: 2026-05-20. Result: **all green.** Functional verification of every
tool and skill in the 0.1.0 build, plus package integrity.

## Summary

| Check | Result |
|---|---|
| pytest suite | **74 / 74 passed** |
| Skill smoke tests | **2 / 2 passed** |
| Skill benchmarks | **2 / 2 — score 1.0** |
| Package install (clean venv) | ✅ imports, console scripts present |
| Tool + skill registration | ✅ 54 builtin + 8 skill tools, 0 skipped |

## 1. pytest — functional tests (74)

Every framework subsystem and tool group has functional cover:

| Suite | Tests | Covers |
|---|---|---|
| `test_external_model.py` | 10 | external-model pipeline — LM Studio / OpenAI / Anthropic, key resolution, local-first fallback |
| `test_drift_parser.py` | 7 | Gemma drift tool-call parsing — the quote-aware `_parse_paren_args` fix |
| `test_permissions_confirm.py` | 5 | the 6-tier permission ladder + `ConsoleConfirmationProvider` |
| `test_tool_surface.py` | 5 | the consolidated tool surface (no retired names) |
| `test_file_tools.py` | 11 | `read_file` (paginated), `write_file`, `patch`, `search_files` |
| `test_board.py` | 13 | the kanban board model, the 4 board tools, Deep Think folded onto the board, legacy-queue migration |
| `test_computer_use.py` | 10 | the `computer_use` skill — accessibility-tree parsing, click-point maths, key chords, tool registration |
| `test_jaeger_tui.py` | 13 | the TUI — banner, boot panel, status bar, slash commands |

## 2. Skill smoke tests (2 / 2)

The skill loader runs each skill's `tests/smoke_test.py` before
registering it. Both pass:

- `example_v1` — the reference skill. ✅
- `computer_use_v1` — the flagship skill. ✅

## 3. Skill benchmarks (2 / 2 — score 1.0)

Each skill's scored `tests/benchmark.py` (the per-skill benchmark
mechanism — `benchmark_skill` / `core/skill_benchmark.py`):

| Skill | Score | Cases |
|---|---|---|
| `example_v1` | **1.0** | 3 / 3 — greeting cases |
| `computer_use_v1` | **1.0** | 8 / 8 — accessibility-tree parsing, centre-point maths, AppleScript escaping, key-chord resolution |

## 4. Package integrity

A clean throwaway venv install of the 0.1.0 wheel:

- `import jaeger_os` → `0.1.0`
- console scripts `jaeger` and `jaeger-os` installed
- the `computer_use_v1` skill (SKILL.md + module + tests) ships in the wheel
- earlier: a full clean-venv install resolved all 26 runtime dependencies

## 5. Tool + skill registration

- **54 built-in agent tools** registered by `_register_builtins`.
- **2 skills** discovered, smoke-tested, and registered — `computer_use`,
  `example` — **0 skipped**.
- **8 skill tools** wired onto the agent: the 7 `computer_*` tools plus
  `say_example_greeting`.
- Total agent tool surface: **62 tools**.

## Scope — what this covers, what it doesn't

This benchmark is **functional / integration verification** — every
tool, skill, and subsystem is exercised by code and confirmed to work,
the package builds and installs cleanly, and skills load end to end.

It does **not** include a live LLM **routing** run (does the model pick
the right tool for a prompt). The Level 1–4 routing suite now ships in
the repo at [`benchmark/`](../benchmark/) — run it locally with
`python benchmark/run_all_levels.py` once an instance is configured and
a model is resolvable. Add those numbers to this file after a run.
