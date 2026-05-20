# Deep Think — autonomous skill-development mode

## Concept

The robot runs one of two modes, never both (so only one model is RAM-resident):

- **Realtime** — fast conversational model (Gemma 4 26B-A4B). Responsive to the
  user; handles conversation, routing, physical-skill decisions.
- **Deep Think** — heavy coding model (Qwen3-Coder class). Works a queue of
  skill-development jobs while the user doesn't need the robot. The "dreaming"
  state: the robot consolidates and builds capability.

The robot enters Deep Think when idle, swaps the resident model, works the
queue, and swaps back the moment the user wants attention. Skills finished
during Deep Think become immediately usable by the Realtime model.

## Why this design

- **Solves the RAM constraint.** Two models co-loaded (~15GB Gemma + ~18GB
  coder) needs a 64GB machine. Mode-swap means only one is resident — works on
  a 32GB robot.
- **No quality compromise on coding.** Skill authoring escalates to a
  coding-specialized model instead of asking fast-Gemma to write integration
  code it's weak at.
- **Responsiveness is preserved.** Deep Think yields instantly on a wake
  signal; the robot is never "stuck thinking" when the user needs it.

## Locked design decisions (2026-05-19)

1. **Task source: BOTH.** The Deep Think queue is fed by (a) user-queued jobs
   ("when idle, build a Discord skill") and (b) agent-proposed jobs from gaps
   it noticed (failed tasks, missing skills, broken files). Agent-proposed
   jobs require a lightweight approval before they run.
2. **Activation: BOTH.** `/deepthink` (or a voice command) enters it on
   demand; it ALSO auto-enters after N minutes of no interaction. Auto-idle
   is opt-in via instance config (`deep_think.auto_idle_minutes`, default off
   until the user enables it).

## Architecture

```
                  ┌─────────────────┐
   idle timer ──▶ │  Mode Manager   │ ◀── wake (voice / keypress)
   /deepthink ──▶ │                 │
                  └────────┬────────┘
              ┌────────────┴────────────┐
       REALTIME mode               DEEP THINK mode
   ┌──────────────────┐        ┌──────────────────────┐
   │ Gemma 4 26B-A4B  │        │ Qwen3-Coder (heavy)  │
   │ conversation,    │        │ works skill-dev      │
   │ routing, physical│        │ queue, file-write    │
   │ skills           │        │ checkpoints          │
   └──────────────────┘        └──────────────────────┘
```

### Components

| Component | Responsibility | Builds on |
|---|---|---|
| **Mode Manager** | Owns current mode; performs `switch_model` | `switch_instance` teardown/reload logic |
| **Deep Think queue** | Pending skill-dev jobs; status `pending → in_progress → done/failed` | new — small JSONL store under `<instance>/memory/` |
| **Idle detector** | N min no input → enter Deep Think | new — timer in the REPL / runtime loop |
| **Wake interrupt** | Voice/keypress → checkpoint job → swap to Realtime | whisper_stt wake-word; TUI keypress |
| **Resumability** | Each `file_write` into a skill folder is a durable checkpoint; interrupt sets job back to `pending` | existing file tools |
| **Handoff** | On swap to Realtime, auto-`reload_skills` so finished skills go live | existing `reload_skills` |

### Build phases

- **Phase 0** — `switch_model(name)`: model-swap primitive (this doc's first
  build target). Register a coder model in `MODEL_REGISTRY`.
- **Phase 1** — per-instance venv (`<instance>/venv/`) + tier-gated
  `install_package`. A built skill that needs a third-party library is dead
  without this.
- **Phase 2** — `run_in_venv`: execute against the instance venv, longer
  timeout, so installed packages are usable.
- **Phase D** — Deep Think mode manager: the queue, idle detector, wake
  interrupt, `/deepthink` command, auto-idle config. Orchestrates 0/1/2.

### Interrupt path

The wake signal must work WITHOUT the conversational LLM (the coder model is
resident during Deep Think). Sources that don't need the main LLM:

- whisper_stt wake-word (openwakeword) — already a plugin
- a keypress in the TUI
- mic VAD threshold

On wake: checkpoint the in-progress job (it's already file-checkpointed; just
flip its queue status), `switch_model` back to the Realtime model,
`reload_skills`, respond. Swap cost ~5-10s — the robot can say "one moment,
coming back" to cover it.

## Open questions for later phases

- Idle threshold default (start: auto-idle OFF; user opts in with a minute
  count).
- Approval UX for agent-proposed jobs (notification + accept/reject, or a
  silence-gate like ARES's 5-minute pattern).
- Whether Deep Think can install packages unattended or queues installs for
  approval on swap-back. (Leaning: installs need the tier-5 confirm flow even
  inside Deep Think — autonomy doesn't bypass the permission ladder.)
