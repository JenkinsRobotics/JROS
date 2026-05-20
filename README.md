# JROS — Jaeger Robot Operating Software

A Mac-native, Python-first alternative to ROS, built for embodied AI agents (Jaegers).

**Version:** 0.1.0-alpha
**Status:** Active Development
**Reference Unit:** [JP01](02_DOCUMENTATION/05_JROS_JP01.md) (Jaeger Prototype 01)
**Reference Digital Agent:** [Lilith](02_DOCUMENTATION/09_JROS_LILITH.md)

---

## What is JROS?

JROS is the operating framework for Jaegers — humanoid robots, drones, and digital AI agents that share a single coherent runtime. It provides the nervous system (transport, nodes, topics) and the brain (agent loop, memory, learned skills, custom neural networks) so the same agent code runs on a 120×120 LED-faced drone or a chat-only desktop companion.

JROS is built from real hardware pain. It runs on Apple Silicon and Jetson Orin without Docker, without special OS versions, and without dependency hell. It is `pip install` simple — a venv is sufficient.

The first physical Jaeger is **JP01**. The first digital Jaeger is **Lilith**. Both evolve together with the framework.

---

## The Two Layers

```
┌────────────────────────────────────────────────────────────┐
│                      AGENT (BRAIN)                          │
│         perceive → plan → act    +  memory  +  skills       │
│         one loop per Jaeger body                            │
└──────────────────────────┬─────────────────────────────────┘
                           │  invokes
┌──────────────────────────▼─────────────────────────────────┐
│                    NODES (NERVOUS SYSTEM)                   │
│   tts │ stt │ llm │ vision │ motors │ leds │ mcu_serial    │
│   pluggable, hot-swappable, transport-agnostic             │
└────────────────────────────────────────────────────────────┘
```

**Nodes** are processes that do one thing — capture audio, run TTS, drive servos, talk to a Teensy. They speak over standardized topics (ZMQ + UDP). See `02_JROS_ARCHITECTURE.md`.

**Agents** are the brain. They subscribe to perception topics, reason with an LLM, look up memories, plan an action sequence, and dispatch it to nodes. See `08_JROS_AGENTS.md`.

A Jaeger is the union of one agent loop and a configured set of nodes.

---

## Repo Layout

```
JROS/
├── 01_JROS/                  framework source code (jaeger_base, jaeger_core, plugins)
├── 02_DOCUMENTATION/         the spec — read this first
│   ├── 01_JROS_OVERVIEW.md         vision, philosophy, why-not-ROS
│   ├── 02_JROS_ARCHITECTURE.md     transport, envelope, topics, repo structure
│   ├── 03_JROS_NODE_STANDARD.md    plugin/node contract, boot sequence, CLI
│   ├── 04_JROS_TRANSPORT.md        ZMQ + UDP, audio/waypoint formats, M[###] hex
│   ├── 05_JROS_JP01.md             JP01 reference implementation
│   ├── 06_JROS_NODES_REGISTRY.md   living registry of all plugins
│   ├── 07_JROS_ROADMAP.md          sprint plan and version milestones
│   ├── 08_JROS_AGENTS.md           agent loop, memory, learned skills
│   ├── 09_JROS_LILITH.md           Lilith — digital-only reference Jaeger
│   ├── 10_JROS_GLOSSARY.md         quick-reference glossary
│   ├── 11_JROS_STACK.md            pinned tech stack (Gemma 4, PydanticAI, MuJoCo, YOLO, CAN, FOC)
│   ├── 12_JROS_AGENT_IMPLEMENTATION.md   first-build spec — Cortex prompt, Pydantic schemas
│   ├── 13_JROS_SKILL_SYSTEM.md     RPG progression — XP, levels, knowledge injection, nightly consolidation
│   └── 14_JROS_OPEN_QUESTIONS.md   unsettled spec items — orchestrator, sim engine, onboard compute, etc.
└── LICENSE
```

---

## Quick Start

JROS is alpha. The framework Python package is scaffolded under `01_JROS/` — every module has the right class signatures, docstrings, and `NotImplementedError` stubs, ready to be filled in.

```bash
cd 01_JROS
pip install -e .          # imports work, no logic yet
pip install -e ".[dev]"
pytest                    # smoke tests confirm the package imports cleanly
```

The current validated *plugin* is `kokoro_tts_node` (its own repo) — the empirical seed the docs were extracted from. Sprint 1 extracts its proven shapes into `01_JROS/jros/jaeger_base/`.

For the full picture, read the docs in numeric order. They are designed to be read top-to-bottom.

---

## Reference Implementations

| Jaeger | Form | Role | Notes |
|---|---|---|---|
| **Lilith** | Digital — local LLM with adjustable personality, runs on Mac | 🥇 First JROS-native agent (Sprint 2) | Proves the agent layer (`jros.jaeger_agent`) before JP01 inherits it. See `09_JROS_LILITH.md`. |
| **JP01** | Drone — Mac + Jetson + Teensy + ESP32 + LED panel + servos + cameras + mics | 🤖 First hardware Jaeger (Sprint 4) | Inherits Lilith's agent unchanged; adds hardware middleware. See `05_JROS_JP01.md`. |

The strategy is **agent first, body second**. Lilith proves the brain in software, then JP01 puts a body around the same brain. More Jaegers will be added as the platform matures — a new Jaeger is a config file plus a custom logic node, not a fork of the runtime.

---

## Project Information

| | |
|---|---|
| Project Status | <mark style="background-color: green"> &nbsp; ACTIVE &nbsp;</mark> |
| Code Status | <mark style="background-color: yellow"> &nbsp; ALPHA &nbsp;</mark> |
| Development Status | <mark style="background-color: green"> &nbsp; ACTIVE &nbsp;</mark> |

---

## Links

SUPPORT US ►

Consider Subscribing: https://www.youtube.com/@Jenkins_Robotics<br>
Patreon ➔ https://www.patreon.com/JenkinsRobotics<br>
Venmo ➔ https://venmo.com/u/JenkinsRobotics<br>

FOLLOW US ►

Discord ➔ https://discord.gg/sAnE5pRVyT<br>
Twitter ➔ https://twitter.com/j<br>
Instagram ➔ https://www.instagram.com/jenkinsrobotics/<br>
Facebook ➔ https://www.facebook.com/jenkinsrobotics/<br>
GitHub ➔ https://jenkinsrobotics.github.io<br>
