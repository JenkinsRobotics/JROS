# JROS repository structure — reviewer guide

**Status:** current as of branch `0.5.0` tip `ede7df5`
**Audience:** reviewers / new contributors / future-you trying to
remember where a thing lives.

## At a glance

```
JROS/
├── jaeger_os/          858 files — the Python framework
├── apps/                 8 files — Swift renderer (in-tree)
├── dev_docs/            62 files — design docs + roadmaps + audits
├── dev_tests/          166 files — pytest suite (~2000 tests)
├── dev_benchmark/      217 files — agent corpus + bench harness
├── dev_scripts/          6 files — developer utilities
├── dev_tools/            4 files — voice / audio reference clients
├── docs/                          — operator-facing docs
├── sandbox/                       — in-repo instance for dev
├── scripts/                       — install / setup
├── CHANGELOG.md                   — per-release history
├── README.md                      — operator-facing entry point
├── LICENSE                        — Apache 2.0
├── pyproject.toml                 — Python packaging
├── requirements.txt               — pip dependencies
├── launch / launch.py             — main entry point shim
├── run.sh                         — daemon mode
└── install.sh                     — one-line curl installer target
```

## `jaeger_os/` — the framework

The Python package.  Imported as `jaeger_os.*` everywhere.

### Top level

```
jaeger_os/
├── __init__.py             — version + package metadata
├── __main__.py             — ``python -m jaeger_os`` entry
├── main.py                 — boot path, prewarm, run_turn, prompts
├── run.py                  — daemon mode
├── topics.py               — bus topic SSOT (msgspec.Struct)
├── _shakedown.py           — boot smoke test
└── README.md
```

### Core subsystems

```
jaeger_os/core/             — framework primitives
├── audio/                   AEC, chimes, reference buffers
├── background/              cron runner, deep-think board
├── bench/                   self-bench cases + runner
├── diagnostics/             health probes
├── instance/                InstanceLayout + per-instance schemas
├── memory/                  SQLite memory backend
├── models/                  llama-cpp + MLX + external model clients
├── prompts/                 assemble.py + rules.py (system prompt)
├── runners/                 ThinkingRunner (deep-think queue)
├── runtime/                 process slot, log rotation, status
├── safety/                  Three Laws, permission tiers
├── skills/                  v3 skill registry + loader
├── tools/                   the agent's tool surface (30 modules)
├── voice/                   parse_gate, non_speech, reply_cleaner
└── credentials.py           per-instance credential storage
```

### Node architecture (0.4 — bus-addressable peripherals)

```
jaeger_os/nodes/            — every peripheral subsystem is here
├── base.py                  Node base class (setup/tick/teardown)
├── runtime.py               singleton: get_bus, ensure_*_node
├── animation/               0.5: face / avatar rendering
│   ├── node.py              AnimationNode
│   ├── base.py              AnimationAdapter Protocol + FrameBuffer
│   ├── bridge.py            WebSocket bridge → Swift app
│   └── adapters/            L1-L4 adapters (vendored from Mochi)
│       ├── image_adapter.py    L1 static raster
│       ├── bitmap_adapter.py   L1 1-bit packed
│       ├── sprite_adapter.py   L2 sheet crop
│       ├── gif_adapter.py      L3 animated GIF/APNG
│       └── math_adapter.py     L4 procedural Python script
├── audio_session/           0.4: mic + AEC + VAD + STT + filters
├── tts/                     0.4: Kokoro speech synthesis
├── vision/                  0.4: camera_frame capture (USB + TCP)
├── motor/                   0.4: universal Protocol; locked
├── light/                   0.4: universal Protocol; locked
└── stt/                     0.4: back-compat shim → audio_session
```

### Transport (0.4 — bus layer)

```
jaeger_os/transport/
├── bus.py                   Bus abstract base + SubscriberFn
├── codec.py                 JSON / MessagePack picker per topic
├── inproc_bus.py            queue.Queue (monolithic mode)
├── zmq_bus.py               ZMQ (future multiprocess mode)
└── broker.py                XPUB↔XSUB proxy for ZMQ
```

### Plugins (3rd-party engine wrappers)

```
jaeger_os/plugins/
├── kokoro_tts/              TTS engine wrapper
├── whisper_stt/             STT engine wrapper (continuous + two_pass)
├── avaudio_io/              macOS AVAudioEngine bridge
├── discord/                 Discord bot bridge
├── telegram/                Telegram bot bridge
├── imessage/                iMessage bridge
├── mcp/                     Model Context Protocol client
├── messaging_gateway.py     unified socket gateway
└── voice_loop.py            standalone voice daemon
```

### Interfaces (operator surfaces)

```
jaeger_os/interfaces/
├── tui/                     Rich + prompt_toolkit TUI (primary surface)
├── rich_tui/                older Rich-only TUI (archived)
└── tray/                    macOS menu bar tray
```

### Agent loop (the actual brain inference path)

```
jaeger_os/agent/
├── loop/                    JaegerAgent + drive_one_turn + runtime_bridge
├── adapters/                LocalLlama / external HTTP shims
├── dialects/                Hermes / ChatML / Llama-3 / Mistral tool formats
├── parsing/                 response → tool calls extractor
├── schemas/                 tool registry + ToolDef + Message types
└── util/                    context guard, prompt builder, retry
```

### 0.5 new additions

```
jaeger_os/skill_tree/        — XP-driven progression (operator-locked)
├── schema.py                SkillNode + SkillTree + XpAward msgspec
├── registry.py              thread-safe registry + persistence
├── xp_emitter.py            bus subscriber → registry
└── seed.py                  default skill catalog (animation, voice,
                             vision, motor, light, core)

jaeger_os/timeline/          — multi-track performance scheduler
├── schema.py                Timeline / TimelineTrack / TimelineClip
└── runner.py                wall-clock dispatcher → bus topics

jaeger_os/personality/       — structured persona for system prompt
├── schema.py                HEXACO + SPECIAL + Expression + Domains
└── compose.py               compose_block() → system prompt fragment
```

### Other

```
jaeger_os/personas/          wizard prefill templates (jarvis.yaml, ...)
jaeger_os/skills/            v3 skill bundles (memory, files, web, ...)
jaeger_os/models/            model registry + GGUF resolver
jaeger_os/instance/          legacy instance migrations
jaeger_os/migrations/        per-version on-disk schema migrations
jaeger_os/daemon/            archived 0.3.0 daemon (not wired in)
jaeger_os/embodiment/        embodied-robot interfaces (early)
jaeger_os/prompts/           prompt assembly (separate from core/prompts/)
jaeger_os/assets/            shipped assets (chimes, etc.)
jaeger_os/docs/              package-local README fragments
```

## `apps/` — out-of-process surfaces

```
apps/
├── JROS-Avatar/             0.5: Mac-native Swift renderer
│   ├── Package.swift        SwiftPM manifest
│   ├── README.md
│   ├── Sources/JROSAvatar/
│   │   ├── AvatarApp.swift   @main + FrameStore
│   │   ├── ContentView.swift TUI: connect field + status + canvas
│   │   ├── RendererView.swift current-frame display
│   │   ├── WebSocketClient.swift URLSessionWebSocketTask wrapper
│   │   └── FrameDecoder.swift [4-byte len][JSON header][RGBA8]
│   └── Tests/JROSAvatarTests/FrameDecoderTests.swift
└── JaegerOS/                0.3.0 walked-back Swift app — archived,
                             only .build artifacts remain; source
                             was removed during 0.3.0 cleanup
```

## `dev_docs/` — design + audits + roadmaps

```
dev_docs/
├── revision_summaries/      per-version lessons-learned summaries
│   ├── README.md             index — every doc tagged 🟢 CURRENT /
│   │                         🟡 PLAN / 🔵 REFERENCE / 🔴 WALKED BACK
│   ├── 0.1.0.md              first release retrospective
│   ├── 0.2.0.md              the 0.2.x line (0.2.0 → 0.2.6)
│   ├── 0.3.0.md              refactor release + walked-back work
│   └── 0.4.0.md              node architecture release
│
├── library_review/          audits of external code we vendor/learn from
│   ├── voicellm.md           voice gate patterns (absorbed)
│   ├── jp01_firmware.md      JP01 robot firmware reference
│   ├── mochi_demo.md         operator's animation engine (0.5 vendor source)
│   ├── final_review.md       post-0.4 VoiceLLM/Hermes salvage sweep
│   └── hermes_supervisor.py  preserved reference for future Track D
│
├── architecture/            — load-bearing architectural docs
│   └── system_runtime_user.md   the three-bucket split (0.2.1+)
│
├── skill_template/          — v3 skill manifest template
│
├── ROADMAP_0.2.0.md         shipped roadmap
├── ROADMAP_0.4.md           shipped roadmap (current node arch)
├── ROADMAP_0.5.md           ACTIVE roadmap
├── 0.5_brainstorm.md        0.5 architectural brainstorm
├── 0.5.0_timeline_schema.md timeline schema design
├── 0.5.0_swift_renderer_plan.md  Swift app phased plan
├── SKILL_TREE.md            XP-progression pattern (operator-locked)
├── STATUS.md                pinned status file
│
├── 0.4.0_*.md               late-cycle 0.4.0 review prompts + audits
├── agent_*.md               agent refactor phase logs (historical)
├── hermes_*.md              hermes audit docs (walked back)
├── instance_layout.md       per-instance directory layout
├── lifecycle_design.md      process/session/extension lifecycle
├── agent_contract.md        auto-generated from core/prompts/rules.py
├── naming_conventions.md    folder/file naming rules
├── lean_surface.md          tool surface size discipline
├── main_loop_review.md      how _run_turn works
├── context_guard.md         prompt-too-big refusal path
├── SELF_MODIFICATION_BOUNDARIES.md  what the agent can/can't change
├── deep_think_design.md     sleep-cycle deep think
├── kanban_design.md         persistent kanban tool
├── external_models.md       LM Studio / OpenAI / Anthropic backends
├── marketplace_spec.md      future skill marketplace (not implemented)
├── physical_skills_status.md   voice-mode skill permissions
├── remote_access.md         tray / IPC for headless access
├── setup.md                 operator-facing setup walk-through
├── skill_sharing_pipeline.md   how skills move between instances
├── daemon_split_plan.md     0.3.0 walked-back daemon design
├── tui_port_notes.md        0.3.0 walked-back daemon TUI port
├── BENCHMARK_0.1.0.md       superseded by bench v1.1
├── code_review_2026_05_24.md  pre-0.2.0 review (drove System/Runtime/User)
├── native_handler_ab.md     A/B test: native tool dispatch
├── toolset_scoping_ab.md    A/B test: toolset narrowing
├── odysseus_review_and_0.3.0_plan.md   0.3.0 original plan (walked back)
└── STRUCTURE.md             this file
```

See `dev_docs/revision_summaries/README.md` for the catalogue of
every doc by status.

## `dev_tests/` — pytest suite (~2000 tests)

Mirrors the `jaeger_os/` package tree under `dev_tests/jaeger_os/`:

```
dev_tests/jaeger_os/
├── core/                    core subsystem tests
├── nodes/                   one test module per node
│   ├── test_animation.py            AnimationNode lifecycle
│   ├── test_image_adapter.py        L1 adapter
│   ├── test_bitmap_adapter.py       L1 adapter
│   ├── test_sprite_adapter.py       L2 adapter
│   ├── test_gif_adapter.py          L3 adapter
│   ├── test_math_adapter.py         L4 procedural
│   ├── test_frame_bridge.py         WebSocket bridge
│   ├── test_animation_e2e.py        full pipeline integration
│   ├── test_audio_session.py
│   ├── test_tts.py
│   ├── test_vision.py
│   ├── test_motor.py
│   ├── test_light.py
│   └── test_runtime.py
├── transport/               Bus / codec / broker tests
├── skill_tree/              registry + XpEmitter + seed catalog
├── timeline/                schema + runner
├── personality/             schemas + compose + assemble integration
├── agent/                   loop + adapters + dialect tests
├── interfaces/              TUI + voice_session tests
├── plugins/                 plugin unit tests
├── skills/                  v3 manifest tests
├── runtime/                 process slot + locks
├── migrations/              version-migration scripts
├── daemon/                  archived
└── main/                    boot path tests
```

## `dev_benchmark/` — agent corpus

```
dev_benchmark/
├── HISTORY.md               leaderboard + per-model run history
├── README.md
├── run_flat_bench.py        single-model bench runner
├── run_model_sweep.py       multi-model comparison
├── run_model_sanity.py      quick smoke
├── voice_gate_latency.py    KV-cache thrashing regression probe
├── flat/                    per-model run outputs (gitignored bodies)
├── sweep/                   multi-model sweep outputs (gitignored)
├── archive/                 0.1.0 corpus + legacy runs
├── levels/                  level-test history (timing baseline)
└── timing/                  bench_history.jsonl (committed baseline)
```

## `dev_scripts/` — developer utilities

```
dev_scripts/
├── check_wheel.py           verify pip wheel contents
├── dev_env.sh               JAEGER_INSTANCE_DIR shim for in-repo dev
├── generate_agent_contract.py  regenerates dev_docs/agent_contract.md
├── node_verification.py     --node-test smoke gate impl
├── run_tests.sh             test-runner wrapper
└── tts_node_test.py         --tts-test smoke gate impl
```

## `dev_tools/` — reference / debug clients

```
dev_tools/
└── audio_smoke/             voice_assistant_persistent.py + variants
                             (reference voice loops the operator
                             built before JROS — preserved for
                             pattern comparison)
```

## `sandbox/` — in-repo dev instance

`<project>/sandbox/.jaeger_os/instances/jros-dev/` is the operator's
local development instance.  Gitignored.  Pointed at via
`JAEGER_INSTANCE_DIR` env var (see `dev_scripts/dev_env.sh`).

## Top-level entry points

| File | What |
|---|---|
| `launch` | shell shim → `./launch.py` |
| `launch.py` | the operator's main entry — boots TUI, voice loop, etc. |
| `run.sh` | daemon mode (background JROS) |
| `install.sh` | curl installer target |
| `pyproject.toml` | Python packaging metadata |
| `requirements.txt` | pip dependencies |

## Branches + tags

```
origin/master    — 0.4.0 release tip (fc8eea1) + 1093140 prewarm-default flip
origin/0.4.0     — release branch (same tip as master)
origin/0.5.0     — ACTIVE — 0.5 work happens here
origin/0.3.0-archive — walked-back 0.3.0 daemon/Swift work
refs/tags/0.4.0  — at fc8eea1 (annotated release tag)
                   plus 0.1.0 / 0.2.0 / ... / 0.2.6
```

No `v0.X.Y` dual-form tags — operator-locked naming
convention (see `~/.claude/.../memory/feedback-tags-only-on-explicit-ok.md`).

## Things to know that aren't obvious

1. **Three-bucket architecture** (System / Runtime / User) governs
   the whole codebase since 0.2.1.  `jaeger_os/` is the framework
   (System); `~/.jaeger_os/instances/<name>/` is operator state
   (User); the boundary is the `InstanceLayout` object.  See
   `dev_docs/architecture/system_runtime_user.md`.

2. **Conscious / unconscious model** (0.4 operator-locked):
   peripheral nodes filter / gate / reflex; brain only engages on
   confirmed signals.  See 0.4.0 CHANGELOG entry for the audio-side
   codification.

3. **Skill tree** is a project-wide pattern, not just animation.
   Every node + skill has level + XP + prereqs.  Operator's
   long-term goal is video-game-aesthetic visualisation.  See
   `dev_docs/SKILL_TREE.md`.

4. **Mochi vendoring**: `/Users/jonathanjenkins/GITHUB/Mochi/` is
   the operator's prior animation engine; the L1-L4 adapters in
   `jaeger_os/nodes/animation/adapters/` are distilled from
   Mochi's handlers.  Audit at `dev_docs/library_review/mochi_demo.md`.

5. **Standing operator rules** (in chat memory + commit history):
   - No `git push` without explicit OK that turn
   - No new/moved tags without explicit OK that turn
   - Tags only `0.X.Y` form (never `v0.X.Y`)
   - Each robot = one persona (no multi-persona switching)
   - Walk user flows before claiming a UX is shipped
   - Commit at milestones, not every pass

## Where to start a review

1. `CHANGELOG.md` — read the 0.4.0 + 0.4.0 late-cycle entries to
   understand the active architectural model.
2. `dev_docs/ROADMAP_0.5.md` — what 0.5 is + isn't.
3. `dev_docs/SKILL_TREE.md` — load-bearing pattern.
4. `dev_docs/revision_summaries/README.md` — what every other doc
   means + whether it's still current.
5. `jaeger_os/topics.py` — the bus SSOT; reading this gives the
   shape of every signal flowing through JROS.
6. `jaeger_os/main.py` — the boot path.  Long but mostly linear.
7. `jaeger_os/nodes/` — pick any node (TTS is simplest) to see how
   the bus contract gets implemented.
