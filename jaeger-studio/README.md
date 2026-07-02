# Jaeger Studio (seed)

Standalone client app for Jaeger / JROS instances — the "Bambu Studio" of the
stack. Discover devices on the LAN, connect, monitor telemetry, drive commands,
and (later) design avatars, run sim, teleop. You set an instance up once; you
don't need Studio running day to day, so it lives in its own app, its own repo.

> **Staging folder.** This lives inside the JROS repo only to prototype the seam
> against the real transport stack. It's self-contained (deps: `pyzmq`,
> `msgspec` — no `jaeger_os` imports) and lifts out to its own repo unchanged.

## Baseline (what's here)

The **link layer** — the load-bearing seam. Everything else (UI, design tools)
is UI on top of this.

```
link/wire.py       protocol contract: messages, framing, beacon  (source of truth)
link/instance.py   internal Jaeger bus: zmq broker, beacon, publish + command loop
link/quic.py       the seam: QUIC/UDP gateway (instance) + Studio QUIC client
link/studio.py     LAN-only zmq client (early scaffold; superseded by quic.py)
demo_quic.py       self-check — Studio <-> instance over one real QUIC/UDP connection
demo.py            self-check — internal zmq bus in isolation
PROTOCOL.md        the wire spec + what's stubbed
```

## Run the self-check

```bash
pip install -r requirements.txt
python demo_quic.py   # -> PASS — Studio <-> instance over QUIC/UDP
```

## The idea in one breath

A Jaeger runs its compute-graph on an internal **ZeroMQ** bus (same as JROS). A
single **gateway** bridges that bus to **one QUIC connection** (UDP) to Studio.
Two planes map to QUIC primitives: reliable control on a **stream**, realtime
telemetry on **datagrams**. Internal bus never leaves the box. See
[PROTOCOL.md](PROTOCOL.md).

## Next (needs a plan + your OK — touches the JROS daemon)

To make a real instance reachable, JROS must expose its broker on TCP + run the
beacon. That's a daemon-arch change on the JROS side — plan first, not a drive-by.

Then, in priority order: CURVE auth/pairing → a Qt Studio shell over `StudioLink`
→ media plane for teleop → `sim_state` schema.
