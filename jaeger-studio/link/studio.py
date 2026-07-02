"""Studio-side link: the client half of the seam.

Discover instances on the LAN, connect to one's broker, subscribe to the
telemetry/event/ack fanout, and push commands. This is the object a Studio UI
(Qt, web, whatever) sits on top of — the UI never touches zmq.
"""
from __future__ import annotations

import itertools
import socket

import zmq

from . import wire

_ids = itertools.count(1)


class StudioLink:
    def __init__(self):
        self._ctx = zmq.Context.instance()
        self._pub: zmq.Socket | None = None  # commands -> instance
        self._sub: zmq.Socket | None = None  # telemetry/event/ack <- instance

    @staticmethod
    def discover(timeout: float = 3.0) -> list[wire.Beacon]:
        """Listen for LAN beacons. Returns unique instances seen within timeout."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", wire.BEACON_PORT))
        sock.settimeout(timeout)
        found: dict[str, wire.Beacon] = {}
        try:
            while True:
                try:
                    data, _ = sock.recvfrom(2048)
                except socket.timeout:
                    break
                b = wire.decode_beacon(data)
                found[b.instance_id] = b
        finally:
            sock.close()
        return list(found.values())

    def connect(self, host: str, xsub_port: int, xpub_port: int) -> "StudioLink":
        self._pub = self._ctx.socket(zmq.PUB)
        self._pub.connect(f"tcp://{host}:{xsub_port}")
        self._sub = self._ctx.socket(zmq.SUB)
        self._sub.setsockopt(zmq.RCVHWM, 4)  # realtime: shallow queue, drop stale under load
        self._sub.connect(f"tcp://{host}:{xpub_port}")
        for topic in (b"telemetry", b"event", b"ack"):
            self._sub.setsockopt(zmq.SUBSCRIBE, topic)
        return self

    def connect_beacon(self, b: wire.Beacon) -> "StudioLink":
        return self.connect(b.host, b.xsub_port, b.xpub_port)

    def send_command(self, name: str, args: dict | None = None) -> str:
        assert self._pub is not None, "connect() first"
        cmd = wire.Command(id=f"c{next(_ids)}", name=name, args=args or {})
        self._pub.send_multipart(wire.encode(cmd))
        return cmd.id

    def recv(self, timeout: float = 1.0) -> wire.Message | None:
        assert self._sub is not None, "connect() first"
        poller = zmq.Poller()
        poller.register(self._sub, zmq.POLLIN)
        if dict(poller.poll(int(timeout * 1000))).get(self._sub) != zmq.POLLIN:
            return None
        return wire.decode(self._sub.recv_multipart())
