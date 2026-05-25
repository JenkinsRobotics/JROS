"""Jaeger daemon — the always-on process that holds the agent.

See :doc:`docs/daemon_split_plan.md` for the phase plan.

Layout:

  • protocol.py  — wire-format dataclasses + the NDJSON codec. Pure data;
                   no IO. Both ends import from here.
  • server.py    — Unix-domain socket listener; routes Request → handler.
                   Phase 1 echoes; Phase 2 holds the agent.
  • client.py    — one-shot or interactive client over the same socket.
  • lifecycle.py — start / stop / status: PID file, fork, signal handling.

Phase 1 ships protocol + server + client + lifecycle as scaffolding.
The agent does *not* move here until Phase 2.
"""

from __future__ import annotations
