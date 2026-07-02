"""Instance-side link: the device half of the seam.

Hosts the XSUB/XPUB broker (same topology as JROS transport/broker.py), broadcasts
a discovery beacon, and gives node code a `publish()` + a command handler loop.

In real JROS this collapses into the existing broker — the instance already runs
one. Here it stands alone so the baseline is runnable without importing jaeger_os.
"""
from __future__ import annotations

import socket
import threading
import time

import zmq

from . import wire


class InstanceLink:
    def __init__(self, *, instance_id: str, name: str, version: str,
                 xsub_port: int = 45550, xpub_port: int = 45551,
                 host: str = "*"):
        self.instance_id = instance_id
        self.name = name
        self.version = version
        self.xsub_port = xsub_port
        self.xpub_port = xpub_port
        self.host = host
        self._ctx = zmq.Context.instance()
        self._stop = threading.Event()
        self._pub: zmq.Socket | None = None
        self._threads: list[threading.Thread] = []

    # --- lifecycle ---

    def start(self, command_handler=None) -> "InstanceLink":
        self._run_bg(self._broker)
        self._pub = self._ctx.socket(zmq.PUB)
        self._pub.connect(f"tcp://127.0.0.1:{self.xsub_port}")
        self._run_bg(self._beacon)
        if command_handler is not None:
            self._run_bg(lambda: self._commands(command_handler))
        time.sleep(0.2)  # ponytail: let broker bind + PUB connect settle (slow-joiner)
        return self

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=1)

    def publish(self, msg: wire.Message) -> None:
        assert self._pub is not None, "start() first"
        self._pub.send_multipart(wire.encode(msg))

    # --- internals ---

    def _run_bg(self, fn) -> None:
        t = threading.Thread(target=fn, daemon=True)
        t.start()
        self._threads.append(t)

    def _broker(self) -> None:
        xsub = self._ctx.socket(zmq.XSUB)
        xpub = self._ctx.socket(zmq.XPUB)
        xsub.bind(f"tcp://{self.host}:{self.xsub_port}")
        xpub.bind(f"tcp://{self.host}:{self.xpub_port}")
        try:
            zmq.proxy(xsub, xpub)  # blocks until context terminates
        except zmq.ContextTerminated:
            pass

    def _beacon(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        b = wire.Beacon(
            instance_id=self.instance_id, name=self.name,
            host=_lan_ip(), xsub_port=self.xsub_port, xpub_port=self.xpub_port,
            version=self.version,
            fingerprint="unpaired",  # ponytail: real pubkey fingerprint when pairing lands
        )
        payload = wire.encode_beacon(b)
        while not self._stop.wait(2.0):
            try:
                sock.sendto(payload, ("255.255.255.255", wire.BEACON_PORT))
            except OSError:
                pass
        sock.close()

    def _commands(self, handler) -> None:
        sub = self._ctx.socket(zmq.SUB)
        sub.connect(f"tcp://127.0.0.1:{self.xpub_port}")
        sub.setsockopt(zmq.SUBSCRIBE, b"command")
        poller = zmq.Poller()
        poller.register(sub, zmq.POLLIN)
        while not self._stop.is_set():
            if dict(poller.poll(200)).get(sub) != zmq.POLLIN:
                continue
            cmd = wire.decode(sub.recv_multipart())
            try:
                detail = handler(cmd) or ""
                ack = wire.Ack(id=cmd.id, ok=True, detail=str(detail))
            except Exception as e:  # command handlers must not kill the loop
                ack = wire.Ack(id=cmd.id, ok=False, detail=repr(e))
            self.publish(ack)
        sub.close()


def _lan_ip() -> str:
    """Best-effort primary LAN IP (no traffic sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()
