---
name: computer_use
version: 1
kind: human_authored               # human_authored | agent_authored | learned | nn_trained
category: cognitive                # drives the host computer (software)
runtime: in_process                # in_process | mcp_subprocess
permission_tier: 2                 # EXTERNAL_EFFECT — the action tools manipulate the host
embodiment_requires: []            # runs on any embodiment with a macOS host
authored_at: 2026-05-20
description: Drive any macOS app through the accessibility tree — see the screen, find elements, click, type.
registers_tools:
  - computer_screenshot(path) -> {ok, path}
  - computer_read_screen() -> {ok, app, window, elements}
  - computer_open_app(name) -> {ok, app}
  - computer_click(x, y) -> {ok, clicked}
  - computer_type_text(text) -> {ok, typed}
  - computer_press_key(key) -> {ok, pressed}
  - computer_menu_select(menu, item) -> {ok, selected}
---

# computer_use_v1

## What
Jaeger-OS's flagship skill — the ability to **use any application on the
Mac**. "Using a computer" is a composed capability (perceive → find →
act → verify), not a primitive, which is exactly why it is a skill and
not a built-in tool.

It registers seven tools across two halves:

- **Perceive** — `computer_screenshot` (capture the screen),
  `computer_read_screen` (the accessibility tree: every on-screen UI
  element with its role, name and a click point), `computer_open_app`.
- **Act** — `computer_click(x, y)`, `computer_type_text`,
  `computer_press_key`, `computer_menu_select`.

Grounding is **accessibility-tree first**: `computer_read_screen` returns
real element coordinates from macOS System Events, so the agent clicks a
known point — no vision model guessing pixels.

## When
Trigger when the task needs an app the agent has no API for — "play Daft
Punk in the browser", "open Notes and write this down", "click the
export button". The loop is:

1. `computer_open_app` to bring the app up.
2. `computer_read_screen` to see the elements and their x/y points.
3. `computer_click` / `computer_type_text` / `computer_press_key` to act.
4. `computer_read_screen` again to verify the result.

Prefer `computer_menu_select` when the action is in a menu (File → New,
Edit → Copy) — menu names are stable, so it is the most reliable path.

## How
- The act tools (`click`, `type_text`, `press_key`, `menu_select`) are
  EXTERNAL_EFFECT — every call is confirmation-gated. The user is asked
  before the agent manipulates their computer.
- Coordinates come from `computer_read_screen` — each element's `x`/`y`
  is its centre point, ready to pass to `computer_click`.

## Depends on
- **macOS** — uses `osascript` (AppleScript / System Events) and
  `screencapture`, both built into macOS. No Python packages.
- **Permissions** — the host process (Terminal / your IDE) must be
  granted **Accessibility** (and **Screen Recording** for screenshots)
  in System Settings → Privacy & Security. The tools return a clear
  hint if the permission is missing.
