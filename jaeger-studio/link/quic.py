"""QUIC external seam — the single UDP connection between Studio and an instance.

Industry-standard QUIC via `aioquic` (the transport under HTTP/3). Two planes map
onto QUIC primitives:

  - reliable (hello/command/ack/event) -> one long-lived bidirectional stream
  - realtime (telemetry/sim_state)     -> QUIC DATAGRAM frames (RFC 9221)

`Gateway` runs on the instance and bridges the internal zmq bus to QUIC. Nothing
here touches jaeger_os; in a real instance the gateway attaches to the existing
broker instead of the standalone one in instance.py.
"""
from __future__ import annotations

import asyncio
import datetime
import itertools
import ssl
from contextlib import asynccontextmanager

import zmq
import zmq.asyncio
from aioquic.asyncio import QuicConnectionProtocol, connect, serve
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import (
    ConnectionTerminated,
    DatagramFrameReceived,
    HandshakeCompleted,
    StreamDataReceived,
)
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from . import wire

ALPN = ["jaeger/0"]
_MAX_DGRAM = 65536


def self_signed() -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    """Ephemeral cert for the QUIC/TLS layer. Its SHA-256 == Beacon.fingerprint."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "jaeger")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    return key, cert


def fingerprint(cert: x509.Certificate) -> str:
    return cert.fingerprint(hashes.SHA256()).hex()


# --- instance side: bridge internal zmq bus <-> one QUIC connection ---


class _GatewayProto(QuicConnectionProtocol):
    gateway: "Gateway"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._unframer = wire.Unframer()
        self._ctrl_stream: int | None = None  # where to send reliable msgs back

    def quic_event_received(self, event):
        if isinstance(event, HandshakeCompleted):
            self.gateway._conns.add(self)
        elif isinstance(event, StreamDataReceived):
            self._ctrl_stream = event.stream_id
            for blob in self._unframer.feed(event.data):
                self.gateway.inject(wire.unpack(blob))  # studio -> internal bus
        elif isinstance(event, DatagramFrameReceived):
            self.gateway.inject(wire.unpack(event.data))  # realtime studio -> instance
        elif isinstance(event, ConnectionTerminated):
            self.gateway._conns.discard(self)

    def send_to_studio(self, msg: wire.Message) -> None:
        data = wire.pack(msg)
        if wire.is_realtime(msg):
            self._quic.send_datagram_frame(data)
        elif self._ctrl_stream is not None:
            self._quic.send_stream_data(self._ctrl_stream, wire.frame(data), False)
        else:
            return  # control stream not open yet; drop reliable until studio says hello
        self.transmit()


class Gateway:
    def __init__(self, *, xsub_port: int, xpub_port: int, quic_port: int,
                 host: str = "0.0.0.0"):
        self.xsub_port = xsub_port
        self.xpub_port = xpub_port
        self.quic_port = quic_port
        self.host = host
        self._conns: set[_GatewayProto] = set()
        self._server = None
        self._sub: zmq.asyncio.Socket | None = None
        self._pub: zmq.Socket | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> "Gateway":
        actx = zmq.asyncio.Context.instance()
        self._sub = actx.socket(zmq.SUB)
        self._sub.connect(f"tcp://127.0.0.1:{self.xpub_port}")
        for topic in (b"telemetry", b"event", b"ack"):
            self._sub.setsockopt(zmq.SUBSCRIBE, topic)
        # plain (non-async) PUB for injecting studio->bus from sync quic callbacks;
        # ponytail: cross-thread-free because it's only touched on the event loop.
        self._pub = zmq.Context.instance().socket(zmq.PUB)
        self._pub.connect(f"tcp://127.0.0.1:{self.xsub_port}")

        config = QuicConfiguration(is_client=False, alpn_protocols=ALPN,
                                   max_datagram_frame_size=_MAX_DGRAM)
        key, cert = self_signed()
        config.certificate = cert
        config.private_key = key
        self.fingerprint = fingerprint(cert)

        gw = self

        def create(*a, **k):
            p = _GatewayProto(*a, **k)
            p.gateway = gw
            return p

        self._server = await serve(self.host, self.quic_port,
                                   configuration=config, create_protocol=create)
        self._task = asyncio.ensure_future(self._forward())
        return self

    def inject(self, msg: wire.Message) -> None:
        self._pub.send_multipart(wire.encode(msg))

    async def _forward(self) -> None:
        while True:
            msg = wire.decode(await self._sub.recv_multipart())
            for proto in list(self._conns):
                proto.send_to_studio(msg)

    def close(self) -> None:
        if self._task:
            self._task.cancel()
        if self._server:
            self._server.close()


# --- studio side: the client the UI sits on ---


class StudioQuicLink:
    def __init__(self, proto: "_ClientProto", stream_id: int):
        self._proto = proto
        self._stream = stream_id
        self._ids = itertools.count(1)

    def _send(self, msg: wire.Message) -> None:
        self._proto._quic.send_stream_data(self._stream, wire.frame(wire.pack(msg)), False)
        self._proto.transmit()

    async def send_command(self, name: str, args: dict | None = None) -> str:
        cmd = wire.Command(id=f"c{next(self._ids)}", name=name, args=args or {})
        self._send(cmd)
        return cmd.id

    async def recv(self, timeout: float = 1.0) -> wire.Message | None:
        try:
            return await asyncio.wait_for(self._proto.inbox.get(), timeout)
        except asyncio.TimeoutError:
            return None


class _ClientProto(QuicConnectionProtocol):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.inbox: asyncio.Queue = asyncio.Queue()
        self._unframer = wire.Unframer()

    def quic_event_received(self, event):
        if isinstance(event, StreamDataReceived):
            for blob in self._unframer.feed(event.data):
                self.inbox.put_nowait(wire.unpack(blob))
        elif isinstance(event, DatagramFrameReceived):
            self.inbox.put_nowait(wire.unpack(event.data))


@asynccontextmanager
async def studio_connect(host: str, quic_port: int, *, name: str = "studio"):
    """Open the single QUIC connection to an instance and hand back a link."""
    config = QuicConfiguration(is_client=True, alpn_protocols=ALPN,
                               max_datagram_frame_size=_MAX_DGRAM)
    config.verify_mode = ssl.CERT_NONE  # ponytail: pin Beacon.fingerprint for real auth
    async with connect(host, quic_port, configuration=config,
                       create_protocol=_ClientProto) as proto:
        stream_id = proto._quic.get_next_available_stream_id()
        link = StudioQuicLink(proto, stream_id)
        # open the control stream so the gateway learns where to send replies
        link._send(wire.Hello(instance_id="?", name=name,
                              version=wire.PROTOCOL_VERSION, role="studio"))
        yield link
