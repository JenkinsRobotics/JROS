# SDD ledger — JROS 0.8 module refactor
Spec: dev/docs/JROS_0.8_MODULE_REFACTOR_SPEC.md (commit a3fcc8a)
Phase U next: U1 delete app/bus + repoint chassis onto transport; U2 one Node/NodeHealth; U3 Supervisor replaces runtime.py singletons + enable jaeger.toml nodes; then Phase M kokoro_tts.
U1 base: c9e0e82
U1 T1 implemented (c9e0e82..dc0ecef) 2555 passed; bench pending
U1 COMPLETE (c9e0e82..dc0ecef): one bus — chassis on transport.InProcBus; app/bus/ + child.py deleted (dead), chassis-ZMQ dropped. Gates: review Approved; suite 2555 pass; bench 80/81. Minors→U3: _broker dead code; backend=zmq config incoherence.
U2 COMPLETE (dc0ecef..5ddfcb3): one Node/NodeState/FrameNode; identity verified; grep-clean; app/core/interfaces green
U3 plan committed e1d7528; Task A next
U3 Task A (6484e17..a2f9f7a): bus injection (runtime.set_bus) + transcript
  is_final collision fix + NodeHealth unified on /sense/node_health with
  base-node heartbeats. Suite green.
U3 Task B (final): supervisor-backed ensure_* — factories construct
  nodes directly (no ensure_* recursion), ensure_* delegates to a
  registered Supervisor when the manifest declares+enables the node.
  jaeger.windowed.toml declares tts+animation (enabled=true, headless-
  safe) — audio_session stays declared-but-disabled (real mic/Whisper
  load, no headless degrade path yet; see u3b-report.md). jaeger.toml
  header updated: duality resolved, disabled now because the TUI path
  builds no chassis Supervisor. Headless windowed smoke: one bus, 2/3
  nodes RUNNING, zero orphan threads on shutdown. 1990 tests green
  across app/core/agent/interfaces/nodes. U3 COMPLETE → Phase M next
  (kokoro_tts module).
