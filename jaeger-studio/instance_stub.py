"""Mock Jaeger instance for developing Studio standalone.

Internal zmq bus + QUIC gateway + a telemetry pump — the same shape a real JROS
instance exposes, minus the real daemon. Studio connects to this exactly as it
will to a real Jaeger. When the daemon-side gateway lands, point Studio at the
real instance and delete nothing here (it stays the dev fixture).

Run:  python instance_stub.py
"""
from __future__ import annotations

import asyncio
import time

import zmq

from link import InstanceLink, wire
from link.quic import Gateway

XSUB, XPUB, QUIC = 45550, 45551, 45560


async def main() -> None:
    inst = InstanceLink(instance_id="i1", name="Jaeger-01", version="0",
                        xsub_port=XSUB, xpub_port=XPUB)
    inst.start(command_handler=lambda cmd: f"echo:{cmd.name}")

    node = zmq.Context.instance().socket(zmq.PUB)
    node.connect(f"tcp://127.0.0.1:{XSUB}")

    gw = await Gateway(xsub_port=XSUB, xpub_port=XPUB, quic_port=QUIC).start()
    print(f"instance-stub up: QUIC udp/{QUIC}, fingerprint {gw.fingerprint[:16]}…  (Ctrl-C to stop)")

    seq = 0
    while True:
        node.send_multipart(wire.encode(wire.Telemetry(
            ts=time.time(), seq=seq, cpu=0.25 + 0.2 * (seq % 5) / 5, pose=[0.0, 1.0, 2.0])))
        seq += 1
        await asyncio.sleep(0.05)  # 20 Hz


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
