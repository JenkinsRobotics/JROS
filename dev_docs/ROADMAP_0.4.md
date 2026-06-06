# JROS 0.4 Roadmap — Embodied node architecture

**Status:** draft (2026-06-06)
**Pre-req:** 0.3.0 shipped (in-process TUI + persistent voice pipeline + skill v3)
**Target:** the framework needs to be usable on real robot hardware

---

## The position

> **JROS = ROS + Agentic AI + local/hardware focus on a Mac.**

That's the one-liner.  No one else owns this combination:

- **ROS** owns embodied robotics middleware but doesn't think about LLM agents.
- **Hermes / OpenAI Agents / LangChain** own agentic loops but assume one
  process on one machine.
- **Ollama / LM Studio** own local-LLM-as-a-service but stop at chat.
- **ros2_control + Foxglove** own teleoperation but not autonomous decisions.

JROS is the framework where a **local LLM agent thinks**, and **dedicated
hardware nodes** carry out the perception and action — coordinated like the
cortexes of a single brain, on a Mac as the master, with Jetson + Teensy +
ESP32 as the spine.

0.3.0 proved the brain works in a monolithic TUI.  0.4 wires the spine.

---

## The single biggest decision

**0.4 adopts a node-based architecture, ZMQ as transport.**

| Why ZMQ, not ROS 2 / DDS | Why ZMQ, not raw sockets |
|---|---|
| ZMQ runs first-class on macOS without Docker | Pub/sub built-in (no roll-your-own broker) |
| ~50 KB library; embedded C bindings (Teensy/ESP32 possible) | Patterns library: REQ/REP, PUB/SUB, PUSH/PULL, DEALER/ROUTER |
| Sub-millisecond local latency (`inproc://`, `ipc://`) | Transport-agnostic — same code, swap transport |
| Battle-tested (CERN, Hedge funds, Spotify) | Built-in TTL, backpressure, multi-part messages |

DDS / ROS 2 stays a future migration target if the fleet ever outgrows ZMQ.
The message-passing pattern is the load-bearing part; the wire format is
swappable.

---

## Architecture diagram (canonical, 2026-06-06 operator-confirmed)

```
                    ┌────────────────────────────────────────┐
                    │            BRAIN NODE  (Mac)            │
                    │                                         │
                    │   LLM (Gemma) + agent loop              │
                    │   In-process: tools, memory, skills,    │
                    │                permissions, persona     │
                    │                                         │
                    │   Tools = networking shims:             │
                    │     - text_to_speech → publish /act/speech
                    │     - listen        → subscribe /sense/transcript
                    │     - vision_analyze → subscribe /sense/vision
                    │     - computer_use  → publish /act/motion etc.
                    └────────────┬────────────────────────────┘
                                 │ ZMQ pub/sub
              ┌──────────────────┼──────────────────┐
              │                  │                  │
     ┌────────▼─────┐    ┌───────▼──────┐    ┌──────▼──────┐
     │  audio_in    │    │   audio_out  │    │   vision    │
     │  (Mac mic)   │    │   (Mac spk)  │    │   (Jetson)  │
     │  PUB /sense/ │    │  SUB /act/   │    │  PUB /sense/│
     │  audio_in    │    │  audio_out   │    │  vision     │
     └──────┬───────┘    └──────▲───────┘    └─────────────┘
            │                   │
     ┌──────▼───────┐    ┌──────┴───────┐
     │   stt        │    │   tts        │   ← own nodes; backend-swappable
     │  (Whisper)   │    │  (Kokoro)    │      (today's Kokoro tomorrow's
     │  SUB audio_in│    │  SUB /act/   │       MLX-TTS or NeuTTS without
     │  PUB transcr │    │  speech      │       touching the brain)
     │              │    │  PUB audio_out
     └──────────────┘    └──────────────┘
            │                   │
            ▼                   ▼
         /sense/transcript      /sense/spoken (TTS ack)

   ┌─────────────────────────────────────────────────────┐
   │ Canonical topic namespaces                           │
   │   /sense/audio_in       raw mic frames (binary)     │
   │   /sense/transcript     STT text + confidence (JSON)│
   │   /sense/vision         YOLOv8 boxes / scene (JSON) │
   │   /sense/touch          contact sensors (JSON)      │
   │   /sense/proprio        encoders + IMU (JSON)       │
   │   /sense/spoken         TTS-done ack (JSON)         │
   │   /act/speech           text to speak (JSON)        │
   │   /act/audio_out        raw speaker frames (binary) │
   │   /act/motion           motor commands (JSON)       │
   │   /act/light            LED commands (JSON)         │
   └─────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴──────────────────┐
              │                                  │
     ┌────────▼─────────┐              ┌─────────▼────────┐
     │  motor_ctrl      │              │   led_ctrl       │
     │  (ESP32, MC01)   │              │   (Teensy, AVC01)│
     │  SUB /act/motion │              │   SUB /act/light │
     │  PUB /sense/proprio              │  PUB /sense/spoken
     └──────────────────┘              └──────────────────┘
```

**Key architectural decisions** (locked 2026-06-06):

1. **One brain process, N hardware-bound peripheral nodes.**  Not one
   node per tool — that's the ROS 2 mistake (extreme granularity).
   The brain's tools, memory, and skill registry stay in-process for
   sub-microsecond function-call latency.

2. **STT and TTS are their own nodes, not in the brain.**  Operator
   call: voice pipelines will evolve; today's Kokoro becomes
   tomorrow's MLX-TTS or NeuTTS without touching the brain.  Same
   `/act/speech` and `/sense/transcript` topic contract; the
   subscriber implementation swaps freely.  Bonus: STT can move to
   Jetson GPU later for CUDA acceleration without the brain
   noticing.

3. **Tool ↔ node contract** (operator's framing, kept verbatim):
   "A tool does the networking and the node does the execution."
   The agent's tool surface stays identical to today's:

   ```python
   text_to_speech("hello")   # same signature
   listen(seconds=5)          # same signature
   ```

   What changes is the implementation: instead of calling Kokoro
   in-process, the tool publishes to `/act/speech` and waits for
   the matching `/sense/spoken` ack with a correlation ID.  In
   monolithic mode (single process, inproc transport) the round-trip
   is microseconds; in multi-process mode it's still sub-millisecond
   on localhost.

4. **The brain doesn't know where its peripherals run.**  It
   subscribes to `/sense/audio_in` — wherever that comes from
   (Mac mic, Jetson mic, simulated mic from a WAV file).  This is
   what unlocks the Mac-only → Mac+Jetson+Teensy+ESP32 transition
   without rewriting the brain.

---

## Tracks of work

### Track A — node foundation (0.4.0 must-have)

**Goal:** the laptop monolith becomes "all nodes in one process," same
code path for nodes-as-threads OR nodes-as-processes.

  - [ ] `jaeger_os/nodes/base.py` — `Node` base class
    - lifecycle hooks: `setup()`, `tick()`, `teardown()`, `health()`
    - ZMQ socket setup boilerplate (configurable transport: inproc / ipc / tcp)
    - log routing into the existing `jaeger_os` logger
    - signal handling: graceful SIGTERM, restart on SIGUSR1
  - [x] **A.1** — `jaeger_os/topics.py` — single source of truth
    - constant names: `SENSE_AUDIO_IN`, `ACT_AUDIO_OUT`, etc.
    - **`msgspec.Struct` schemas** (NOT Pydantic — landed at A.1.1
      after operator-flagged inconsistency; see commit `0b0b38c`).
      Pydantic stays in JROS for config + tool schemas where its
      richer ecosystem earns the overhead; transport schemas live
      where microseconds matter.
    - schema versioning (`topic_v: int` on every message)
    - landed 2026-06-06; 49 tests pass
  - [ ] **A.2** — `jaeger_os/transport/codec.py` (NEW step inserted
    on second-agent review)
    - JSON encoder/decoder for text topics (`/sense/transcript`,
      `/act/speech`, etc.) — `msgspec.json.encode/decode`
    - MessagePack encoder/decoder for binary topics
      (`/sense/audio_in`, `/act/audio_out`, `/sense/vision`) —
      `msgspec.msgpack.encode/decode`
    - Pick-by-topic helper so call sites don't have to remember
      which encoding belongs to which namespace
  - [ ] **A.3** — `jaeger_os/transport/inproc_bus.py` — in-process
    Bus (the VoiceLLM port).  Uses the codec from A.2.
  - [ ] **A.4** — `jaeger_os/transport/zmq_bus.py` — ZMQ pub/sub
    behind the same Bus interface.
    - default `inproc://` for in-process nodes
    - `ipc://` for same-machine multi-process
    - `tcp://` for cross-machine (JP01: Mac↔Jetson↔Teensy)
    - autodetect from `JAEGER_TRANSPORT` env / config
  - [ ] **A.5** — `jaeger_os/nodes/base.py` — `Node` base class
    - lifecycle hooks: `setup()`, `tick()`, `teardown()`, `health()`
    - Bus socket setup boilerplate
    - log routing into the existing `jaeger_os` logger
    - signal handling: graceful SIGTERM, restart on SIGUSR1
  - [ ] **A.6** — `launch.py` — gains a `--mode {monolithic,multiprocess}` flag
    - `monolithic` (default): all nodes inproc, current TUI behaviour
    - `multiprocess`: spawn each node as its own Python subprocess

### Track B — first node split (0.4.0 must-have)

**Goal:** prove the IPC layer end-to-end with the simplest possible case.

  - [ ] `jaeger_os/nodes/audio_io.py` — wraps the persistent Kokoro
    player + mic input as a single node, publishes
    `/sense/audio_in` frames and subscribes `/act/audio_out` frames.
    Runs in-process by default; spawns standalone with `--multiprocess`.
  - [ ] Brain now reads transcripts from `/sense/transcript` (still
    in-process for now) instead of calling Whisper directly.
  - [ ] **Verification gate:** TUI works identically in both modes.
    `./launch` (monolithic) and `./launch --multiprocess` must produce
    the same operator experience.

### Track C — hardware adapters (0.4.1)

**Goal:** the JP01 boards can host their nodes.

  - [ ] **Teensy** — serial protocol adapter
    - `jaeger_os/nodes/motor_ctrl.py` subscribes `/act/motion`,
      translates Pydantic messages to a binary frame, writes to a
      Teensy 4.x over USB-CDC.
    - Teensy firmware (separate repo) speaks the binary frame; emits
      `/sense/proprio` (encoder + IMU) back over the same link.
  - [ ] **ESP32** — LED control via `/act/light`
    - same shape as motor_ctrl; Tcp/UDP to an ESP32 running a tiny
      firmware that maps RGB messages to a WS2812 strip.
  - [ ] **Jetson** — vision pipeline lives there
    - `jaeger_os/nodes/vision.py` runs Whisper-large or Moondream
      CUDA-accelerated on Jetson Orin.
    - Publishes `/sense/vision` (bounding boxes, OCR text, scene
      description) over `tcp://` back to the Mac brain.
  - [ ] **Discovery** — a tiny `jaeger_os/nodes/registry.py` so the
    brain doesn't have to know IP addresses.  Uses mDNS (Bonjour on
    Mac, Avahi on Linux).  Each node advertises its topics; brain
    queries on boot.

### Track D — robustness primitives (0.4.x)

**Goal:** survive any single node crashing without taking the agent down.

  - [ ] Per-node supervisor (`launch.py` enhancement)
    - restart-on-crash with exponential backoff (already prototyped by
      Hermes's `supervisor.py` — port the pattern)
    - max-restarts-per-window circuit breaker
  - [ ] Topic TTLs — messages older than N seconds get dropped at the
    subscriber side (no stale sensor readings driving the brain)
  - [ ] Backpressure — slow consumers shouldn't kill the publisher;
    ZMQ's `HWM` (high-water mark) handles this; expose it via config
  - [ ] Health topic — every node publishes `/health/<name>` every 1s
    with `{ok: bool, last_tick_s: float, error?: str}`.  Brain can
    drop tools whose backing nodes report unhealthy.
  - [ ] Graceful degradation contract — if `vision` node dies, brain's
    `vision_analyze` tool returns a structured error, NOT a hung call.

### Track E — simulation mode (0.4.x)

**Goal:** run the brain on a laptop without the robot, useful for dev.

  - [ ] Stub nodes that mock sensors
    - `audio_in_stub` — replays a WAV file as if it were live mic
    - `vision_stub` — serves a directory of images on a topic timer
    - `motor_stub` — accepts motion commands, logs them, returns OK
  - [ ] `./launch --sim` — wires stubs instead of real hardware

### Track F — operator UX (0.4.x)

**Goal:** monitoring + introspection beyond just the TUI.

  - [ ] Topic inspector — a `jaeger_os/nodes/inspector.py` that runs
    a local web server (FastAPI + WebSocket), shows live topic
    traffic in a browser.  Foxglove-lite for JROS.
  - [ ] Record/replay — `jrostool record /sense/transcript /act/motion`
    captures topic streams to a bag file; `jrostool replay` plays
    them back for offline debugging.

---

## Milestones

| Tag | Theme | Tracks |
|---|---|---|
| **0.4.0** | Node foundation + first split | A + B |
| **0.4.1** | Hardware adapters | C |
| **0.4.2** | Robustness | D |
| **0.4.3** | Sim + introspection | E + F |
| **0.5.0** | DDS migration evaluated, ROS 2 bridge (optional) | — |

---

## What 0.4 explicitly does NOT do

  - **Doesn't deprecate the monolithic TUI.** Laptop-only users keep
    their current experience; nodes-in-one-process is the default.
  - **Doesn't require Docker.** Every node runs as a plain Python
    process in `.venv`.  Hardware adapter firmware (Teensy/ESP32)
    is separate.
  - **Doesn't redesign the agent loop, tools, memory, or skill
    system.**  Those are stable.  0.4 is plumbing, not brain surgery.
  - **Doesn't introduce ROS 2 / DDS.**  ZMQ is the chosen transport.
    A ROS 2 *bridge* node may appear in 0.5 for interop with existing
    ROS ecosystems, but JROS's primitives stay ZMQ-native.
  - **Doesn't try to be a general-purpose robot framework.**  JROS is
    Mac-first.  Linux on Jetson is supported because JP01 needs it.
    Windows is not on the roadmap.

---

## Resolved decisions (2026-06-06 lock-in)

  ✦ **STT/TTS placement.**  RESOLVED — own nodes, not in the brain.
    Voice pipelines will evolve; today's Kokoro + Whisper become
    tomorrow's MLX-TTS or NeuTTS without touching the brain.  Same
    `/act/speech` and `/sense/transcript` topic contract; subscriber
    implementation swaps freely.  Bonus: STT can move to Jetson GPU
    later without the brain noticing.

  ✦ **Tool ↔ node dispatch contract.**  RESOLVED — "**a tool does
    the networking, the node does the execution**" (operator's
    phrasing, kept as the canonical formulation).  The agent's tool
    signatures stay identical to today's; the implementation goes
    from in-process call to topic publish + correlation-ID wait for
    the ack message.  Sub-ms round-trip in both monolithic and
    multi-process modes.

  ✦ **Library inventory.**  RESOLVED — JP01_Firmware + VoiceLLM
    reviewed (`dev_docs/library_review/`); Lilith-AI explicitly
    skipped per operator (hasn't tracked JROS); Hermes also delisted.

## Still open

1. **Brain co-location.**  Does the brain stay on the Mac, or does it
   also live on the Jetson?  Today Gemma needs unified memory (Apple
   Silicon).  Jetson can host smaller models but not 26B-class.  TBD
   whether 0.4 supports both as configurable.

2. **Message serialization.**  Lean is **JSON for text topics**
   (`/sense/transcript`, `/act/motion`, `/sense/spoken`) — human-
   readable in `tcpdump`, easy to inspect — and **MessagePack for
   binary topics** (`/sense/audio_in`, `/act/audio_out`,
   `/sense/vision`) — 30-50 % smaller, faster encode/decode.  Operator
   sign-off needed before Track A locks the wire format.

3. **Time sync across boards.**  Mac↔Jetson↔Teensy clock drift will
   matter for proprio + vision fusion.  PTP?  NTP?  Custom-on-USB?
   Probably out of scope for 0.4.0, but the topic schema should
   carry a `t_emit_ns` field from day one so the data's there when
   sync arrives.

---

## Library review queue

Detailed reviews live under `dev_docs/library_review/<name>.md`.
This table is the index + the absorption verdict.

| Lib | Reviewed | Verdict | Use it for |
|---|---|---|---|
| **JP01_Firmware** | [`jp01_firmware.md`](library_review/jp01_firmware.md) | **Absorb as Track C spec source** | Board layout truth (JP01-VCC01 / AVC01 / MC01 / CC01), motor + LED serial protocols, blackbox_logger pattern, ReactPy web UI alignment |
| **VoiceLLM** | [`voicellm.md`](library_review/voicellm.md) | **Absorb three patterns into Track A** | Single-process Bus (verbatim, ~30 lines), LLM-gated speech (`<ignore>`/`<reply>`), explicit orchestrator FSM, optional mlx-lm backend |

## Correction to the architecture diagram

The original diagram in this doc had the board mapping inverted.  Per
JP01_Firmware's actual controller layout (confirmed by the operator
2026-06-06):

  - **JP01-AVC01 (Teensy)** runs the audio + LED matrix (`.ino`,
    `NeoPixelHandler.h`, `LedMatrixHandler.h`).
  - **JP01-MC01 (ESP32)** runs the motors + sensors.
  - **JP01-VCC01 (Jetson Orin)** runs vision/AI/PC interface (YOLOv8,
    dual CSI cams, Flask web).
  - **JP01-CC01** — the host-PC operator UI (currently a manual
    Python tool the operator runs to connect to + control individual
    components).  **JROS on the Mac REPLACES CC01.**  Same role
    (central computer + operator surface), but with autonomous
    agentic control instead of manual driving.  This is the headline
    deliverable that 0.4 enables on real hardware.

Topic-to-node mapping for Track C should use these names so JROS
nodes line up 1:1 with the firmware controllers.

## Library inventory decisions

  - **Lilith-AI** — operator says SKIP.  It's a JROS implementation
    that hasn't tracked JROS itself, so reviewing it would teach us
    things we already know.  Will be updated downstream once JROS
    stabilises.
  - **Hermes** — already informed the JROS install pattern; no fresh
    review needed unless Track D wants to port `supervisor.py`
    verbatim.

## Carry-forward patterns already absorbed

  - **VoiceLLM → JROS:** the `<ignore>` / `<reply>` LLM-gated speech
    pattern landed at commit `ee8bb9b` as an opt-in
    `config.voice.llm_gate` flag (default off).  Sits above the
    existing STT-level `is_non_speech_marker()` filter as the second
    line of defence for always-on embodied agents.  See
    `jaeger_os/core/voice/llm_gate.py` and
    `rules.VOICE_LLM_GATE_RULE`.

## Reverse migration queue (JROS → upstream)

VoiceLLM's audio pipeline is older than ours; if the operator wants
to ship a final pass over VoiceLLM, JROS has improvements worth
porting back:

  - Persistent Kokoro player (sounddevice + avaudio backends with
    live CoreAudio default-device resolution) — replaces VoiceLLM's
    per-call `sd.OutputStream` open.
  - Audio backend config toggle.
  - Whisper STT hardening (the `_NON_SPEECH_MARKERS` set + AEC
    plumbing).
  - The `tts_node.shutdown()` deterministic teardown that prevents
    the `Pa_Terminate`-at-exit segfault class on macOS 26.

These are NOT 0.4 deliverables for JROS — they'd be a separate
"VoiceLLM audio refresh" patch landing in that repo when the
operator chooses.
