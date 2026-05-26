# JROS 0.2.0 — roadmap

**Status:** open · **Branched:** 2026-05-25 off `0.1.0` (commit `d31b703`)
**Theme:** **make `jaeger start` actually start Jaeger.** Headless
agent in the daemon, menu-bar icon as the "she's alive" indicator,
CLI / TUI / GUI as interchangeable clients. Plus the floating GUI
chat window ported from Lilith.

The 0.1.0 release proved the framework works end-to-end. 0.2.0 is
about making it FEEL like a product: one mental model, not five
flags.

---

## What 0.1.0 taught us (the user-facing rough edges)

These came out of the first real boot of Lilith on a clean install:

1. **`jaeger start` doesn't start Jaeger.** It forks a lifecycle
   scaffold but the agent only lives in the TUI process. The name
   lies; this is the headline confusion.
2. **`JAEGER_INSTANCE_DIR` is a load-bearing env var with no UI.**
   New shell, no env var, suddenly you're talking to "Jarvis" in
   the bundled placeholder instance instead of your Lilith.
3. **Default ctx (16K) + full tool surface = guaranteed overflow.**
   Tool schemas alone eat 14K. Every first message refuses with a
   ContextOverflow.
4. **Always-on voice mic grabs background audio.** Without
   `speexdsp`, the mic listens during agent idle and pulls in
   podcast/youtube playing nearby.
5. **Setup wizard chains into the TUI with a stale `--setup`
   flag**, hits the TUI's argparse, error-exits despite a
   successful instance creation.
6. **Role field has a silent 256-char limit.** Long roles crash
   with a pydantic ValidationError.
7. **Banner footer still says "pydantic-ai core."** Stale since
   Phase 9; nothing in the agent loop uses it.

Every one of these is a fixable 0.2.0 item.

---

## The 0.2.0 model — "one mental model, not five flags"

```
   ┌──────────────────────────────────────────────────────┐
   │   jaeger start    ← the only command you usually need │
   └────────────────────────┬─────────────────────────────┘
                            │ forks
                            ▼
          ┌──────────────────────────────────┐
          │  daemon — hosts the agent loop   │
          │  + Unix-domain socket            │
          │  + menu-bar tray (🤖)             │
          │  + model loaded ONCE             │
          └──────────────────────────────────┘
                ▲          ▲          ▲
                │          │          │ NDJSON over UDS
                │          │          │
        ┌───────┴───┐ ┌────┴────┐ ┌───┴────────┐
        │ jaeger    │ │ jaeger  │ │ jaeger     │
        │ tui       │ │ chat    │ │ gui        │
        │ (Rich)    │ │ (CLI)   │ │ (PyQt6)    │
        └───────────┘ └─────────┘ └────────────┘

   pick any client; quit it; open another; all the same agent
```

`jaeger start` runs the daemon, loads the model, lights up the
menu bar. The agent is **autonomous from that moment** — picks up
kanban cards, fires cron prompts, runs idle Deep Think — without
any client window open. The user opens a client (TUI / CLI / GUI)
when they want to chat or watch. Quit the client; the agent keeps
running.

This is the model real LLM products converged on (Claude Desktop,
Cursor's agent mode, ChatGPT on Mac all do versions of this).
JROS 0.1.0 has all the pieces (daemon, tray, TUI) but doesn't
connect them; 0.2.0 connects them.

---

## TODO — 0.2.0

Grouped by sequence. Items inside a group can be parallel;
groups should land in order so each one builds on the last.

### Group 1 — Daemon hosts the agent (BG-4 from prior roadmap)

The blocking item. **Done 2026-05-25.** `jaeger start` actually
starts Jaeger now — the daemon owns the model + agent, and clients
attach via NDJSON over the Unix socket.

- [x] **DAEMON-A** — `boot_for_daemon` in `main.py` mirrors
      `boot_for_tui`; daemon's child process owns the LLM lock,
      the agent registry, the tool dispatch. Required a side fix:
      switched spawn model from `os.fork()` to `subprocess.Popen`
      because macOS aborts a forked child the first time it
      touches an Obj-C class the parent initialized — Metal's
      `ggml_metal_device_init` was dying silently. Subprocess
      starts a fresh interpreter with
      `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` pre-set in env.
- [x] **DAEMON-B** — `chat.send(text, session_key=None)`,
      `chat.subscribe()` (streaming Events through the same
      socket), `chat.history(session_key, limit)`,
      `status.snapshot()`. Streaming required extending the
      server with `register(op, fn, streaming=True)` — the
      handler gets an `emit(name, **payload)` callback. The
      per-daemon `EventBus` fans out tool-progress / turn events
      to every subscriber (bounded queues, drop-oldest on full
      so a slow client can't stall the agent).
- [x] **DAEMON-C** — `jaeger attach` in `daemon/attach.py`. Two
      connections per session: one for `chat.subscribe`, one
      per-turn for `chat.send`. Quit attach (Ctrl-D); daemon
      keeps running. Tested end-to-end against a real Gemma
      model — Kokoro TTS spoke a response out loud.
- [x] **DAEMON-D** — **NEW** `jaeger rich-tui` in
      `interfaces/rich_tui/`. The existing `jaeger tui` (0.1.0
      surface) is **untouched** — `rich-tui` lives alongside as
      a separate Rich+prompt-toolkit client that requires a
      running daemon. No in-process fallback; if no daemon is
      up, prints a clear error and exits 1. See the
      "preserve 0.1.0 surfaces" feedback memory for the
      additive-not-replace policy. Slash commands: `/help`,
      `/status`, `/history`, `/clear`, `/quit`.
- [x] **DAEMON-E** — `Server.on_connect` / `on_disconnect`
      callbacks; `chat_ops` wires audit writers that append
      JSON lines (`daemon.client.connect` /
      `daemon.client.disconnect`) to `<instance>/logs/audit.log`
      with `client_id`, `duration_s`, `ops_called`.

**Result:** 77 daemon tests + 9 rich-tui tests added (was 13);
1088 default-tier tests still pass (was 1049 pre-Group 1).

**Live-tested commands:**
```sh
jaeger start --no-tray     # boots daemon (subprocess, model loaded)
jaeger status              # running (pid=…, uptime=…)
jaeger attach              # headless CLI; type, send, see tool events
jaeger rich-tui            # Rich UI; same daemon, banner + boot panel
jaeger stop                # clean shutdown
```

### Group 2 — Wizard + first-run UX

User-facing polish. The bugs that made the first-run dance painful.

- [ ] **WIZ-1** — Wizard auto-boot strips `--setup` from
      `sys.argv` before chain-calling the TUI/daemon (the
      argparse error we hit at end of setup).
- [ ] **WIZ-2** — `Identity.role` 256-char limit surfaced in
      the prompt as `[≤256 chars]`. Or accept long roles and
      split into `identity.role` + `soul.md` automatically.
- [ ] **WIZ-3** — **NEW QUESTION**: default interaction mode.
      ```
      How do you want to talk to {name} by default?
        › 1. Type — open a TUI when I run `jaeger`     (recommended)
          2. Floating window — PyQt6 chat bubble
          3. Voice — always-on mic + spoken responses
                     (requires speexdsp for AEC)
      ```
      Writes to `config.yaml:interaction.default_mode`. For 0.2.0,
      option 3 is gated behind "voice is experimental" warning.
- [ ] **WIZ-4** — Wizard's final line prints the env-var the user
      needs to set OR (better) writes a `~/.jaeger/jaeger.env`
      file the shell can `source`. Stop the silent
      `JAEGER_INSTANCE_DIR` surprise.
- [ ] **WIZ-5** — Default `model.ctx` raised to **32768** (was
      16384). The model trained at 262K; 32K is comfortable on
      Apple Silicon and avoids the every-first-message overflow.

Cost: half-day. All small.

### Group 3 — PyQt6 floating GUI (port from Lilith)

The Claude-style floating chat window. Live text conversation —
no permanent terminal, no Dock entry, just a small window you
pop open with a hotkey.

Salvage path: Lilith already has the PyQt6 code at
`Lilith-AI/src/jaeger_os/instance/lilith/gui/`:
- `chat_window.py` — the floating chat bubble
- `tray.py` — Qt-side tray (we already have a rumps tray in JROS;
  pick one — keeping rumps since it's lighter)
- `_brand.py` — brand styling helpers
- `studio_window.py` — Persona Studio (defer to 0.3+)
- `radar_chart.py` — analytics (defer)

The chat_window is the only piece needed for 0.2.0.

- [ ] **GUI-A** — Move `chat_window.py` + `_brand.py` into JROS
      under `src/jaeger_os/interfaces/gui/`. Strip the
      Persona-Studio entry points; keep the chat window only.
- [ ] **GUI-B** — Connect the chat window to the daemon (Group 1's
      NDJSON protocol) — sends user input, subscribes to streamed
      events. Same shape as the TUI's bind.
- [ ] **GUI-C** — Visual parity with the TUI's response panel —
      "thinking" indicator while she ruminates, response body in
      a soft panel, tool-activity dots at the bottom. Reuse
      TUI's status-string format so users don't relearn.
- [ ] **GUI-D** — Voice **OUTPUT** on by default (she speaks her
      response via Kokoro); voice **INPUT** off by default (no
      always-on mic). Both togglable in the window.
- [ ] **GUI-E** — `jaeger gui` CLI command — launches the window
      against the running daemon. Hotkey to summon/hide is
      Option+Space (Lilith's pattern); writable in config.
- [ ] **GUI-F** — Tests: chat-window unit tests, paste handling,
      streaming-event rendering, mic toggle.

Cost: ~2 days. The biggest chunk after Group 1.

### Group 4 — Voice defaults & robustness

The mic-grabs-podcast bug + the install-time AEC question.

- [ ] **VOICE-1** — `voice.enabled: false` is the wizard default.
      User opts in explicitly.
- [ ] **VOICE-2** — When `voice.enabled: true` AND `speexdsp` is
      not installed: the wizard offers `pip install speexdsp` as
      a one-tap install, OR writes a clear note that always-on
      mic will grab background audio without AEC.
- [ ] **VOICE-3** — Wake-word gate tightened: require the wake
      phrase to be the FIRST 2 tokens of a transcript, not just
      appear anywhere in it.
- [ ] **VOICE-4** — Pre-wake transcripts shown as `[mic heard X
      — not sent]` rather than submitted to the agent.

Cost: half-day.

### Group 5 — Bug + polish sweep

The small ones from 0.1.0's first boot.

- [ ] **POLISH-1** — Drop "pydantic-ai core" from the banner
      footer. Replace with "framework-free Phase-9 loop" or just
      remove the tag entirely.
- [ ] **POLISH-2** — Boot panel's "Available Tools" listing
      respects `JAEGER_TOOLSET_SCOPING` — show what the model
      actually sees, not the full registry.
- [ ] **POLISH-3** — Flip lean-surface default to ON
      (was the original QW-1; now reinforced by the ctx-overflow
      experience). The bench held 96% at the new CORE — safe.
- [ ] **POLISH-4** — `requires_toolsets` auto-load when viewing
      a skill (carried from prior plan).
- [ ] **POLISH-5** — `docs/agent_contract.md` auto-generated
      from `rules.py` (carried over).
- [ ] **POLISH-6** — Tool docstring behavioural-text sweep
      (carried over).

Cost: half-day.

### Group 6 — Release hygiene (urgent — 0.1.0 ship bug)

The `src/jaeger_os/instance/default/` directory in the JROS repo
is currently a dev playground. It got bundled into the 0.1.0
wheel — every `pip install jaeger-os` ships ~2.7 MB of stale memory,
agent-test artifacts, dev logs, and leftover credentials placeholder
slots. New installs find this writable site-packages location FIRST
in the path resolver, so they unknowingly load OUR dev junk instead
of their own fresh state.

What needs to happen:

- [x] **HYGIENE-1** — Clean `src/jaeger_os/instance/default/` to a
      minimal skeleton. **Done 2026-05-25** — dev state moved to
      `sandbox/jros-dev/`; bundled tree now holds only
      `default/{memory,logs,skills,credentials}/.gitkeep`. The wizard
      writes `config.yaml` / `identity.yaml` / `soul.md` /
      `manifest.json` on first run, so no template files are needed
      in the skeleton.
- [x] **HYGIENE-2** — `.gitignore` rules so runtime-writable
      subdirs don't accumulate. **Done 2026-05-25** — extended
      `src/jaeger_os/instance/.gitignore` with `*/run/` (PID + socket
      + log scratch). The existing `*/memory/*`, `*/logs/*`,
      `*/skills/*`, `*/credentials/*`, `*/.git/` rules already covered
      the rest; only `run/` was missing.
- [x] **HYGIENE-3** — `sandbox/` directory + dev shim. **Done
      2026-05-25** — `sandbox/` added to the root `.gitignore`;
      `scripts/dev_env.sh` exports `JAEGER_INSTANCE_DIR=$REPO/sandbox/jros-dev`
      (sourced) or runs a subcommand with the var set. The dev
      instance now lives at `sandbox/jros-dev/` (including its
      `.git/` skills-audit history).
- [x] **HYGIENE-4** — Instance-dir resolver priority. **Done
      2026-05-25** — `is_pip_installed()` checks for a
      `site-packages` / `dist-packages` ancestor on `PACKAGE_ROOT`;
      `resolve_instance_dir()` picks `~/.jaeger/<name>/` over the
      bundled location whenever that's true. Editable installs
      (`pip install -e .`) still resolve to the source checkout, so
      they correctly stay in DEV mode.
- [x] **HYGIENE-5** — Wheel manifest audit. **Done 2026-05-25** —
      `scripts/check_wheel.py` enforces an ALLOWED_INSTANCE_FILES
      list (parent .gitignore + README + four `.gitkeep`s); refuses
      anything else under `jaeger_os/instance/`. Covered by 11 unit
      tests under `tests/jaeger_os/core/test_instance_resolver.py`.
      The 0.1.0 wheel is flagged with 7 known leaks; the fresh build
      is clean.

      Adjacent fix: `pyproject.toml`'s `setuptools.packages.find`
      now excludes `python_hermes_agent*` (the vendored Hermes
      reference clone). 0.1.0 didn't ship that dir; it was about to
      sneak into 0.2.0's wheel (+~8 MB).

Cost: half day total. **Should land in 0.2.0 first item** so all
subsequent dev work lands in the sandbox, not the bundled tree.

### Group 7 — Future-Lilith / future-Jaeger (deferred again)

These stay deferred for after 0.2.0 ships:

- BG-1: Three Laws + safeguard hardening (gating before
  Jaeger physical-port)
- BG-2: Move 67 wrappers out of `main.py`
- BG-3: `.app` bundling with py2app for Launchpad
- macos_computer per-app dispatch expansion
- `--doctor-deep` live API probes
- Unify `agent/schemas/toolsets.py` + `core/skills/toolsets.py`

---

## What 0.2.0 looks like when done

The new-user flow becomes:

```bash
pip install jaeger-os                  # one command
jaeger --setup                         # interactive wizard, picks
                                       # interaction mode + model
jaeger start                           # boots the agent in background
                                       # — 🤖 in menu bar
                                       # — model loaded once
                                       # — autonomous from now on
```

From here the user can:
- **Click the menu-bar 🤖** → Open TUI / Open GUI / Quit
- **Run `jaeger gui`** for the floating chat window
- **Run `jaeger tui`** for the terminal interface
- **Run `jaeger attach`** for a headless CLI tail
- **Run `jaeger chat "hi"`** for one-shot exchanges

The agent runs autonomously the whole time — works the kanban,
fires cron, deep-thinks when idle, persists what matters. The
client is "how I talk to her right now," not "the thing that
contains her."

That's the 0.2.0 promise.

---

## Bench bar for 0.2.0

Same as before — 0.1.0 numbers held or improved on every suite,
hermetic mode. Adding one new gate for the daemon path:
**connect-disconnect cycles must not regress agent state** (run
the bench against the daemon-hosted agent and confirm hermetic
mode still works when the test client is `jaeger attach` instead
of in-process).

---

## Receipts

Append SHA / PR / bench reference as items land. Same shape as
the 0.1.0 commit history we just put together.
