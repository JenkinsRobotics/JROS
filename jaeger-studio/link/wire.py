"""Wire contract — the load-bearing seam between Jaeger Studio and instances.

One fabric, two logical planes, both riding the same ZeroMQ pub/sub broker that
JROS already runs internally (transport/broker.py, XSUB/XPUB):

  - reliable plane  : command / event / ack / hello   (must not drop)
  - realtime plane  : telemetry / sim_state / frame     (latest-wins, may drop)

Framing is MessagePack via msgspec — the same encoding JROS uses on its hot
path, so an instance can bridge internal topics straight out to Studio with no
re-serialization. Messages are a tagged union: the tag *is* the topic, so a peer
subscribes by topic prefix and decodes the whole union with one call.

This module is deliberately self-contained (deps: pyzmq, msgspec) so the folder
lifts cleanly into its own repo. Nothing here imports jaeger_os.
"""
from __future__ import annotations

import msgspec

PROTOCOL_VERSION = "0"

# --- messages: tag == topic. Add a struct here and it's on the wire. ---


class Hello(msgspec.Struct, tag="hello"):
    instance_id: str
    name: str
    version: str
    role: str  # "instance" | "studio"


class Telemetry(msgspec.Struct, tag="telemetry"):
    ts: float
    seq: int
    cpu: float
    pose: list[float]  # realtime plane: latest-wins, fine to drop


class Command(msgspec.Struct, tag="command"):
    id: str
    name: str
    args: dict


class Ack(msgspec.Struct, tag="ack"):
    id: str
    ok: bool
    detail: str = ""


class Event(msgspec.Struct, tag="event"):
    ts: float
    level: str  # info | warn | error
    text: str


Message = Hello | Telemetry | Command | Ack | Event

_decoder = msgspec.msgpack.Decoder(Message)


def topic_of(msg: Message) -> bytes:
    """Topic frame = the struct's tag. One source of truth."""
    return type(msg).__struct_config__.tag.encode()


def encode(msg: Message) -> list[bytes]:
    """[topic, payload] — multipart so SUB sockets filter by prefix."""
    return [topic_of(msg), msgspec.msgpack.encode(msg)]


def decode(frames: list[bytes]) -> Message:
    return _decoder.decode(frames[-1])


# --- single-blob framing for QUIC (stream = length-prefixed; datagram = 1 msg) ---

REALTIME = (Telemetry,)  # rides QUIC DATAGRAM (unreliable, latest-wins)


def pack(msg: Message) -> bytes:
    return msgspec.msgpack.encode(msg)


def unpack(data: bytes) -> Message:
    return _decoder.decode(data)


def is_realtime(msg: Message) -> bool:
    return isinstance(msg, REALTIME)


def frame(data: bytes) -> bytes:
    """Length-prefix a message for a QUIC byte stream."""
    return len(data).to_bytes(4, "big") + data


class Unframer:
    """Reassemble length-prefixed messages from a QUIC stream's byte chunks."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[bytes]:
        self._buf += chunk
        out: list[bytes] = []
        while len(self._buf) >= 4:
            n = int.from_bytes(self._buf[:4], "big")
            if len(self._buf) < 4 + n:
                break
            out.append(bytes(self._buf[4:4 + n]))
            del self._buf[:4 + n]
        return out


# --- discovery beacon: what an instance broadcasts so Studio can find it ---


class Beacon(msgspec.Struct):
    instance_id: str
    name: str
    host: str
    xsub_port: int  # peers PUB into here (commands from Studio, telemetry from nodes)
    xpub_port: int  # peers SUB from here (fanout of everything)
    version: str
    fingerprint: str  # instance pubkey fingerprint — pins identity for pairing


def encode_beacon(b: Beacon) -> bytes:
    return msgspec.msgpack.encode(b)


def decode_beacon(data: bytes) -> Beacon:
    return msgspec.msgpack.decode(data, type=Beacon)


BEACON_PORT = 45454  # UDP broadcast port for LAN discovery
