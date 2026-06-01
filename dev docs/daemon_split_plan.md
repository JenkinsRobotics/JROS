# Daemon split — phase plan

**Decision (2026-05-24):** Option B from the persistence discussion. Build a
long-running daemon that holds the model + agent + cron + (future) voice
loops. The TUI becomes a thin client that attaches over a local Unix-domain
socket. Manual lifecycle (`jaeger start` / `jaeger stop`); no launchd/systemd
packaging yet. See [[project-agent-persistence-deferred]] memory for the
deferral history and the three options surfaced.

## Why this shape

Hermes spawns a fresh agent per TUI session and persists conversations to
disk for resume (see ``docs/remote_access.md`` and the upstream survey).
That's right for a chatbot. **Jaeger is a robot OS**, and a robot has to be
*alive* even when no operator is at the TUI: cron, scheduled goals, voice
listeners, hardware loops. The shape that fits is:

```
       ┌─────────────────────────────────────────────────┐
       │              jaeger daemon (1 process)          │
       │   model · agent · cron · voice · _pipeline      │
       │                                                 │
       │      ┌─── unix-domain socket ───┐               │
       └──────┤  <instance>/run/jaeger.sock              │
              │                          │               │
              ▼                          ▼               │
       jaeger attach                jaeger web           │
        (TUI client)              (ReactPy server)       │
```

Daemon owns state. Clients render and forward input. Multiple clients can
attach (one TUI + one web tab); we'll start with **one-active-client-at-a-time**
to avoid the consistency problem, and revisit broadcast later.

## Protocol

NDJSON over a Unix-domain socket. One JSON object per line. Same shape as
Hermes's ``tui_gateway`` uses internally — line-delimited JSON is the
simplest robust thing for Python↔Python local IPC, no protobuf toolchain,
no length-prefix framing bugs.

```
# Client → Daemon
{"id": 1, "op": "attach", "session_key": "tui-default"}
{"id": 2, "op": "submit_turn", "prompt": "what time is it?"}
{"id": 3, "op": "interrupt"}
{"id": 4, "op": "permission_response", "request_id": "req_abc", "granted": true}
{"id": 5, "op": "detach"}

# Daemon → Client (events; no id needed)
{"event": "status",         "phase": "thinking", "detail": ""}
{"event": "answer_chunk",   "text": "It's 3:14 PM..."}
{"event": "tool_called",    "name": "get_time", "args": {...}}
{"event": "tool_returned",  "name": "get_time", "result": {...}}
{"event": "permission_request", "request_id": "req_abc",
                            "tier": "PRIVILEGED",
                            "skill": "shell", "summary": "run echo hello"}
{"event": "answer_done",    "elapsed_s": 1.42}
{"event": "error",          "kind": "...", "message": "..."}
```

The `permission_request` event is the cross-process replacement for today's
``input()``-based confirmation flow. The daemon emits the request, blocks the
turn's permission gate, and waits for a matching `permission_response` from
the active client. Timeout → deny.

## Phase plan

Phases are sequenced so each one **ships green tests and a working `main`
branch**. We don't merge a phase that leaves the existing TUI broken.

### Phase 1 — Daemon scaffold + ping/pong  *(~1.5 days)*

Smallest possible standing-up of the lifecycle. No agent moved yet.

- `src/jaeger_os/runtime/daemon/server.py` — opens the socket, accepts
  connections, dispatches JSON ops. Echo-only for now.
- `src/jaeger_os/runtime/daemon/client.py` — connects, sends an op,
  reads a response.
- `src/jaeger_os/runtime/daemon/protocol.py` — message dataclasses + a
  thin codec; pure-data, no IO.
- CLI verbs: `jaeger start`, `jaeger stop`, `jaeger status`. Just enough
  to bring the daemon up, prove the socket works, bring it down. Uses a
  PID file at `<instance>/run/jaeger.pid` + the socket at
  `<instance>/run/jaeger.sock`.
- **Tests:** start → ping → stop, idempotent stop, stale PID file
  recovery, socket-already-bound error.

**Existing TUI is unchanged.** This phase adds a parallel surface that
exists but isn't wired to the agent yet.

### Phase 1.6 — macOS menu-bar tray icon  *(~1 day)*

Lands right after Phase 1 so "is Jaeger on?" is answerable at a glance,
even before the TUI client exists. The tray is a third client to the
daemon (alongside TUI and the future web dashboard), but a deliberately
*dumb* one — it only does lifecycle and launch, never agent ops.

- `src/jaeger_os/interfaces/tray/macos.py` — ``rumps``-based menu-bar
  app. Same pattern as Lilith's ``tray.py`` (see
  [[feedback-tray-no-pipeline-logic]]): GUI only, never imports the
  agent or pipeline. All actions exec `jaeger ...` subprocesses.
- `src/jaeger_os/interfaces/tray/base.py` — abstract `TrayBackend`
  protocol (icon, menu items, on_click handlers). The macOS rumps
  implementation backs it for now; a future ``linux_appindicator.py``
  or ``windows_pystray.py`` slots in without touching callers.
- Polls `jaeger status` every ~2s to update the icon glyph:
  green=running, dim=stopped, red=error. Hover tooltip shows daemon
  uptime + attached client count once Phase 2 surfaces them.
- Menu items:
  - **Status:** running / stopped / error (label, not a button)
  - Open TUI → spawns `osascript -e 'tell app "Terminal" to do script "jaeger attach"'`
  - Open Web Dashboard → opens default browser at the web URL (when web lands)
  - Start / Stop / Restart Daemon → `jaeger start` / `stop` / restart sequence
  - About / Quit Tray
- **Tests:** the tray's *logic* (state → glyph mapping, menu enable/disable
  rules) is unit-testable without rumps. The rumps integration is a
  small adapter that wires the test-covered logic to the GUI.

Cross-platform deferred: macOS-first with rumps; Linux (pystray /
AppIndicator) when there's a Jaeger unit on Linux to use it.

### Phase 2 — Move the agent into the daemon  *(~3–4 days)*

The bulk of the lift. After this phase, `jaeger attach` opens a TUI client
that drives a daemon-resident agent.

- Daemon boot path: `boot_for_daemon()` next to `boot_for_tui()`, builds
  the same `_pipeline` but in the daemon process. Model loads once at
  daemon start; doesn't reload on `attach`.
- New protocol ops: `submit_turn`, `interrupt`, `permission_response`.
- TUI client mode: a new entry point that **does not** call
  `boot_for_tui` — it connects to the socket, forwards stdin lines as
  `submit_turn`, and renders incoming events through the existing
  Rich/PTK chrome.
- **Permission flow refactor (the risky bit):** today
  `ConsoleConfirmationProvider` calls `input()` directly. We replace it
  with a `RemoteConfirmationProvider` in daemon-mode that emits a
  `permission_request` event and blocks on a `permission_response`
  matched by `request_id`. The client renders the prompt with the same
  text the local provider used. Timeout (default 60s) → deny.
- **Interrupt across the boundary:** `Ctrl-C` in the client becomes a
  `{"op":"interrupt"}` message; daemon sets the existing process-wide
  `threading.Event` that ``tool_interrupt.py`` already polls. No tool
  changes.
- **Streaming:** the agent loop already emits status callbacks; we add a
  "broadcast to attached clients" callback that ships them as events.
- **Tests:** turn through the daemon matches turn through the TUI for
  the same prompt (same tools called, same answer). Permission prompt
  round-trips. Interrupt mid-tool exits the same way.
- **Backwards-compat:** standalone `jaeger` (no `start` first) still
  works as today — it just runs `boot_for_tui` in-process. So everyone
  who hasn't migrated keeps working.

### Phase 3 — One-active-client + state coherence  *(~1.5 days)*

- A second `jaeger attach` either (a) replaces the first ("kicked
  the previous client") or (b) gets `{"event":"error","kind":"session_busy"}`.
  Pick (b) for now — explicit is better than surprising.
- Conversation history lives in the daemon, not the client. A
  re-attaching client gets a `replay` event with the last N turns of
  history so the TUI can render context. Limit N to a configurable
  number (default 20) so re-attach is cheap.
- **Tests:** attach → detach → reattach renders the prior turns;
  second-client-while-first-attached is rejected.

### Phase 4 — Cron + background work in the daemon  *(~1.5 days)*

- The existing `CronRunner` already runs in CLI mode; wire it into the
  daemon boot path. Scheduled prompts now fire even with no client
  attached.
- Deep Think queue workers (currently `start_background()` subprocesses)
  stay as detached subprocesses but their lifecycle is managed by the
  daemon, not whichever TUI happened to be open when they started.
- **Tests:** a cron schedule fires while detached; the resulting turn
  shows up in episodic memory and is visible on next attach.

### Phase 5 — Polish & cleanup  *(~1 day)*

- `jaeger status` shows: daemon PID, uptime, attached client count,
  current `agent_status`, last turn elapsed, cron next-fire.
- Graceful shutdown on SIGTERM (`jaeger stop`): finish in-flight turn or
  cancel it, persist state, release lock, close socket, exit.
- Daemon log rotation (separate file from TUI log).
- Update `docs/remote_access.md`: the "agent persistence" caveat changes
  shape — TUI restart no longer kills the agent.

**Not in this plan, deliberately:**

- launchd/systemd packaging (deferred per user preference)
- Multi-client *broadcast* (Phase 3 leaves this as an explicit follow-up)
- Voice loop in the daemon (separate track once voice lands)
- Remote-over-network attach (SSH already covers the operator use case)

## Risks worth naming up front

1. **The permission flow is the highest-risk change.** Today it's a
   blocking `input()` in the same process. Moving it to a round-trip
   means every tier-gated tool has to wait on a network event. We need
   to make absolutely sure (a) the agent loop doesn't deadlock if the
   client disconnects mid-prompt and (b) the timeout-to-deny path is
   exercised in tests.

2. **Model state coherence.** The daemon holds the loaded model. If a
   long-running tool wedges the model state (we've seen this with MLX
   on Gemma 4 — see `feedback_mlx_over_llamacpp.md`), the daemon needs a
   recovery path that doesn't require `jaeger stop && jaeger start`.

3. **The bench harness.** `benchmark/levels/_runner.py` boots through
   `boot_for_tui` for parity with the TUI. We have two options: (a) keep
   bench using `boot_for_tui` (no daemon) so bench measures the
   in-process path the way it always has; (b) add a parallel
   `boot_for_daemon` bench mode to measure the new path's overhead.
   Recommend (a) for now — bench is measuring agent logic, not IPC.

## What I'm not doing yet

This doc is the plan, not the build. After you sign off (or push back on)
the phase shape, I'll start Phase 1 with tests-first per
[[feedback-working-style]]. I'll surface implementation questions as they
come up rather than guessing.
