---
name: computer_use
version: 2
kind: human_authored               # human_authored | agent_authored | learned | nn_trained
category: cognitive                # drives the host computer (software)
runtime: in_process                # in_process | mcp_subprocess
permission_tier: 2                 # EXTERNAL_EFFECT — the action tools manipulate the host
embodiment_requires: []            # runs on any embodiment with a macOS host
authored_at: 2026-05-20
description: Drive any macOS app — a self-verifying, name-based toolset plus an LLM plan/act/verify loop.
registers_tools:
  - computer_do(goal) -> {ok, goal, steps, result}
  - computer_look() -> {ok, screen, windows}
  - computer_windows() -> {ok, apps}
  - computer_open(app) -> {ok, screen}
  - computer_click(target) -> {ok, action, screen, verified}
  - computer_type(text) -> {ok, action, screen, verified}
  - computer_key(key) -> {ok, action, screen, verified}
  - computer_menu(menu, item) -> {ok, action, screen, verified}
  - computer_screenshot(path) -> {ok, path}
---

# computer_use_v2

## What
The ability to **use any application on the Mac** — rebuilt so the skill
itself plans, acts and verifies, instead of dumping that on the model.

v1 exposed raw primitives (`click(x, y)`) and the model clicked blind,
never checking the result. v2 fixes that **inside the skill**:

- **`computer_do(goal)` — the loop.** Give it a plain goal. The skill
  runs its OWN loop with the model: *look at the screen → decide the one
  next action → do it → verify the new screen → repeat* until the goal
  is met. This is the headline tool.
- **Name-based primitives.** `computer_click("5")` — you name the
  element; the skill reads the accessibility tree, finds it, clicks it.
  No pixel coordinates, no guessing.
- **Self-verifying.** Every action re-reads the screen afterwards and
  returns the new state plus a `verified` flag (did the screen actually
  change). Acting blind is structurally impossible.
- **Whole-desktop aware.** The skill sees *every* open window, not just
  the one in front — so it focuses the app it needs itself. Running the
  TUI inside VS Code never traps it. It never asks you to switch
  windows; it navigates the desktop on its own.

## When
Trigger when the task needs an app the agent has no API for — "compute
5+5 in Calculator", "play a song in the browser", "open Notes and write
this down", "click the export button".

**For anything multi-step, use `computer_do(goal)`** — it plans and
verifies for you. Reach for the primitives (`computer_look`,
`computer_click`, …) only for a single deliberate action.

## How — plan → act → verify
`computer_do` runs this loop internally; if you drive the primitives by
hand, follow the same discipline:

1. **PLAN** — state the steps before touching anything. "Compute 5+5 in
   Calculator" = open Calculator → click `5` → click `+` → click `5` →
   click `=` → read the result.
2. **LOOK** — `computer_look()` returns the front window's elements AND
   every open window. If what you need is a background app,
   `computer_open(app)` focuses it first. Act on names you can see;
   never guess, never ask the user to switch windows.
3. **ACT — one step at a time.** `computer_click(target)` takes an
   element NAME, not coordinates. It finds it, clicks it, and re-reads
   the screen for you.
4. **VERIFY** — every action returns the screen state AFTER it and a
   `verified` flag. Read it. Confirm the step worked before the next
   one. If `ok` is false, the result lists `available` element names —
   pick a real one and retry.
5. The loop will *think harder* on a failed step (it re-reasons about
   the cause before retrying), and stops on success, a step cap, or
   three failures in a row.

## How — permissions
- The action tools (`do`, `click`, `type`, `key`, `menu`) are
  EXTERNAL_EFFECT, all under the single `computer_use` skill — so **one
  grant covers the whole skill**. Answer *always* once and it never asks
  again. `computer_do` does its internal clicks itself, so a whole task
  is one confirmation, not one per click.

## Depends on
- **macOS** — `osascript` (AppleScript / System Events) and
  `screencapture`, both built in. No Python packages.
- **The LLM pipeline** — `computer_do` loops with the resident model
  (`jaeger_os.main._pipeline`); the primitives work without it.
- **Permissions** — the host process (Terminal / your IDE) must hold
  **Accessibility** (and **Screen Recording** for screenshots) in
  System Settings → Privacy & Security. The tools return a clear hint
  when a permission is missing.
