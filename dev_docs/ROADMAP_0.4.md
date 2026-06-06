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

## Architecture diagram

```
                ┌──────────────────────────────────┐
                │       BRAIN  (Mac)               │
                │   LLM + agent loop + tools       │  
                │   subscribes /sense/* topics     │
                │   publishes /act/* topics        │
                └──────────┬───────────────────────┘
                           │ ZMQ pub/sub
              ┌────────────┼──────────────┐
              │            │              │
     ┌────────▼─────┐ ┌────▼────────┐ ┌───▼────────┐
     │  audio_in    │ │  audio_out  │ │  vision    │
     │  (Mac mic)   │ │  (Mac spk)  │ │  (Jetson)  │
     └──────────────┘ └─────────────┘ └────────────┘
              │            ▲              │
     ┌────────▼─────┐      │     ┌────────▼─────────┐
     │   stt        │      │     │    moondream     │
     │  (Whisper)   │      │     │    vision_lm     │
     └──────────────┘      │     └──────────────────┘
              │            │
     ┌────────▼─────┐ ┌────┴────────┐
     │ /sense/      │ │  /act/      │   ← canonical topic namespaces
     │ transcript   │ │ audio_out   │
     │ vision       │ │ motion      │
     │ touch        │ │ light       │
     │ proprio      │ │ speech      │
     └──────────────┘ └─────────────┘
                           │
              ┌────────────┴──────────────┐
              │                           │
     ┌────────▼─────┐           ┌─────────▼────────┐
     │  motor_ctrl  │           │   led_ctrl       │
     │  (Teensy)    │           │   (ESP32)        │
     └──────────────┘           └──────────────────┘
```

The brain doesn't know whether `audio_in` is a Mac mic, a Jetson mic, or
a simulated mic.  It subscribes to `/sense/audio_in` — wherever that
message comes from.

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
  - [ ] `jaeger_os/topics.py` — single source of truth
    - constant names: `SENSE_AUDIO_IN`, `ACT_AUDIO_OUT`, etc.
    - Pydantic schemas for each topic's payload
    - schema versioning (`topic_v: int` on every message)
  - [ ] `jaeger_os/transport.py` — ZMQ wrapper
    - default `inproc://` for in-process nodes
    - `ipc://` for same-machine multi-process
    - `tcp://` for cross-machine (JP01: Mac↔Jetson↔Teensy)
    - autodetect from `JAEGER_TRANSPORT` env / config
  - [ ] `launch.py` — gains a `--mode {monolithic,multiprocess}` flag
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

## Open questions

1. **Brain co-location.**  Does the brain stay on the Mac, or does it
   also live on the Jetson?  Today Gemma needs unified memory (Apple
   Silicon).  Jetson can host smaller models but not 26B-class.  TBD
   whether 0.4 supports both as configurable.

2. **Message serialization.**  MessagePack vs Pydantic JSON vs raw
   protobuf.  MessagePack is the leading candidate for the hardware
   topics (binary, fast); JSON for human-debuggable topics like
   transcripts.  Need to pick before Track A locks the wire format.

3. **Time sync across boards.**  Mac↔Jetson↔Teensy clock drift will
   matter for proprio + vision fusion.  PTP?  NTP?  Custom-on-USB?
   Probably out of scope for 0.4.0, but the topic schema should
   carry a `t_emit_ns` field from day one.

4. **Tool ↔ node mapping.**  Today the brain's tools call into
   in-process plugins (Kokoro, Whisper, Moondream).  Once those are
   nodes, the agent's tool surface needs to dispatch to ZMQ instead.
   The tool definition can stay the same; the implementation routes
   through the topic layer.  Need to design this contract.

5. **What library inventory does the operator want to absorb?**  The
   operator has signalled they want to drop other repos into the
   workspace for review (likely ROS-adjacent + agentic).  Reserve a
   `dev_docs/library_review/` directory for those notes.

---

## Library review queue (operator drops in)

| Lib | Pattern to evaluate | Notes |
|---|---|---|
| _(operator to fill)_ | _(operator to fill)_ | _(operator to fill)_ |
