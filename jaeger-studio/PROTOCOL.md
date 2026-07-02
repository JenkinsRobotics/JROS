# Jaeger Link Protocol — v0 baseline

The seam between **Jaeger Studio** (client app) and **Jaeger / JROS instances**
(devices). Studio connects to an instance the way Bambu Studio connects to a
printer: discover on the LAN, open **one connection**, drive it.

## Design rule

Internal stays internal; the seam is one connection. A Jaeger runs its
compute-graph on a ZeroMQ XSUB/XPUB broker (`transport/broker.py`) internally —
that never leaves the box. A single **gateway** bridges that bus to **one
QUIC connection** to Studio. Framing is `msgspec` + MessagePack end to end
(same as JROS's hot path), so the gateway forwards without re-serializing.

Studio is **not** a raw peer on the internal broker. One external connection =
one thing to secure, auth, and version.

## Transport: QUIC (UDP)

The external seam is **QUIC** — an industry-standard connection protocol over
UDP (IETF RFC 9000; the transport under HTTP/3). Python impl: **`aioquic`**. We
use QUIC, not raw UDP, on purpose: raw UDP is a bare datagram, so anything over
~1500 B (every video frame) forces you to write your own fragmentation +
reassembly, and anything that must arrive forces your own ACK/retransmit — i.e.
you rebuild QUIC, badly. QUIC gives it for free, plus:

- one connection, multiplexed, **no head-of-line blocking across streams**
- **connection migration** — WiFi↔ethernet↔cellular without dropping (a moving
  robot changes networks; the connection survives)
- TLS 1.3 built in — encryption + identity in the same layer
- easy to establish over any L2 (WiFi, ethernet), NAT-friendly

## One connection, two planes — mapped to QUIC primitives

| Plane | Messages | QUIC primitive | Guarantee |
|-------|----------|----------------|-----------|
| Reliable | `hello` `command` `ack` `event` | **bidirectional stream** | reliable, ordered |
| Realtime | `telemetry` `sim_state` `frame` | **DATAGRAM frame** (RFC 9221) | unreliable, latest-wins |

QUIC's unreliable-datagram extension is exactly right for teleop telemetry: no
retransmit of stale state, no HOL blocking behind a dropped frame. Enable it with
`max_datagram_frame_size` on both ends. One long-lived bidi stream carries the
reliable control traffic both directions.

## Wire format

- **Payload:** MessagePack over a msgspec tagged union — the tag *is* the message
  type, so one decode call dispatches everything. `link/wire.py` is the single
  source of truth.
- **On a QUIC stream** (byte stream): length-prefix each message `[u32 len][msgpack]`.
- **On a QUIC datagram:** one message per datagram (already bounded).
- **On the internal zmq bus:** `[topic, payload]` multipart (topic = tag) for
  prefix subscribe. The gateway translates between the two framings.
- **Versioning:** `PROTOCOL_VERSION`, echoed in `hello`. Pre-1.0 = no back-compat.

## Internal topology (unchanged, never exposed)

Instance broker on two loopback ports: `xsub_port` (peers PUB into), `xpub_port`
(peers SUB from). Nodes and the gateway are local zmq peers. Studio never sees
these ports.

## Discovery

Instance UDP-broadcasts a `Beacon` (`instance_id, name, host, quic_port, version,
fingerprint`) every 2 s on port **45454**. Studio listens to build its device
list. LAN-first, like Bambu.

- v0: raw UDP broadcast. Upgrade to mDNS/zeroconf when it earns it.

## Auth / pairing — **stub in v0**

Instances are network-reachable, so this is real security work. The mechanism is
already in the transport: **QUIC uses TLS 1.3**, so the instance holds a cert and
its **SHA-256 fingerprint == `Beacon.fingerprint`**. Studio pairs once (trust the
fingerprint on first connect, like SSH host keys) and pins it thereafter. v0
ships a self-signed cert and Studio skips verification (`CERT_NONE`) — trusted
LAN only until pinning lands.

## What's NOT here yet (named so it's not mistaken for done)

- Cert pinning / pairing flow (fingerprint hook exists; not enforced)
- Media plane for teleop camera/audio (WebRTC media tracks — codec + adaptive
  bitrate; QUIC datagrams carry telemetry, not compressed video)
- mDNS discovery
- Reconnect / instance-gone detection on the Studio side
- Schema for `sim_state` / `frame` payloads (only `telemetry` is defined)
- JROS-side gateway wired into the real daemon (baseline runs a standalone
  gateway over a standalone internal broker — daemon integration is plan-gated)
