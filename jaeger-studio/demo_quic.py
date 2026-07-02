"""Self-check for the QUIC seam: Studio <-> instance over one real UDP connection.

Run: python demo_quic.py   (needs aioquic + pyzmq + msgspec)

Topology exercised:
  node --zmq--> internal broker --zmq--> Gateway --QUIC/UDP--> Studio   (telemetry, datagram)
  Studio --QUIC/UDP--> Gateway --zmq--> command loop --zmq--> Gateway --QUIC--> Studio  (command/ack, stream)
"""
from __future__ import annotations

import asyncio
import time

import zmq

from link import InstanceLink, wire
from link.quic import Gateway, studio_connect

XSUB, XPUB, QUIC = 45550, 45551, 45560


async def main() -> None:
    # internal Jaeger: zmq broker + a command handler (echo)
    inst = InstanceLink(instance_id="i1", name="Jaeger-01", version="0",
                        xsub_port=XSUB, xpub_port=XPUB)
    inst.start(command_handler=lambda cmd: f"echo:{cmd.name}")

    # a "node" publishing telemetry onto the internal bus (single-threaded pump)
    node = zmq.Context.instance().socket(zmq.PUB)
    node.connect(f"tcp://127.0.0.1:{XSUB}")

    gw = await Gateway(xsub_port=XSUB, xpub_port=XPUB, quic_port=QUIC).start()
    await asyncio.sleep(0.3)  # let gateway SUB subscription propagate

    async def pump():
        seq = 0
        while True:
            node.send_multipart(wire.encode(
                wire.Telemetry(ts=time.time(), seq=seq, cpu=0.3, pose=[0.0, 1.0, 2.0])))
            seq += 1
            await asyncio.sleep(0.02)  # 50 Hz

    pumping = asyncio.ensure_future(pump())

    async with studio_connect("127.0.0.1", QUIC, name="studio-1") as studio:
        telem = await wait_for(studio, wire.Telemetry, deadline=5.0)
        assert telem and telem.pose == [0.0, 1.0, 2.0], "no telemetry over QUIC datagram"

        cmd_id = await studio.send_command("ping", {"n": 1})
        ack = await wait_for(studio, wire.Ack, deadline=5.0,
                             match=lambda m: m.id == cmd_id)
        assert ack and ack.ok and ack.detail == "echo:ping", f"bad ack over QUIC stream: {ack}"

    pumping.cancel()
    gw.close()
    inst.stop()
    print("PASS — Studio <-> instance over QUIC/UDP: telemetry (datagram) + command/ack (stream)")


async def wait_for(studio, kind, *, deadline, match=None):
    end = time.time() + deadline
    while time.time() < end:
        msg = await studio.recv(timeout=0.5)
        if isinstance(msg, kind) and (match is None or match(msg)):
            return msg
    return None


if __name__ == "__main__":
    asyncio.run(main())
