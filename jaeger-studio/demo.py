"""Self-check: stand up an instance, connect a Studio client, prove the seam.

Run: python demo.py   (needs pyzmq + msgspec)

Exercises the load-bearing paths end to end over real TCP:
  1. beacon encode/decode round-trips (discovery contract)
  2. telemetry fans out instance -> studio (realtime plane)
  3. command -> handler -> ack round-trips studio -> instance -> studio (reliable plane)
"""
from __future__ import annotations

import threading
import time

from link import InstanceLink, StudioLink, wire


def main() -> None:
    # 1. beacon contract
    b = wire.Beacon(instance_id="i1", name="Jaeger-01", host="127.0.0.1",
                    xsub_port=45550, xpub_port=45551, version="0", fingerprint="x")
    assert wire.decode_beacon(wire.encode_beacon(b)) == b, "beacon codec broken"

    # 2. bring up instance with an echo command handler
    inst = InstanceLink(instance_id="i1", name="Jaeger-01", version="0")
    inst.start(command_handler=lambda cmd: f"echo:{cmd.name}")

    stop = threading.Event()

    def pump():
        seq = 0
        while not stop.is_set():
            inst.publish(wire.Telemetry(ts=time.time(), seq=seq, cpu=0.3,
                                        pose=[0.0, 1.0, 2.0]))
            seq += 1
            time.sleep(0.02)  # 50 Hz

    threading.Thread(target=pump, daemon=True).start()

    # 3. Studio connects and drains
    studio = StudioLink().connect("127.0.0.1", 45550, 45551)
    time.sleep(0.3)  # let SUB subscription propagate (slow-joiner)

    got_telem = wait_for(studio, wire.Telemetry, deadline=3.0)
    assert got_telem and got_telem.pose == [0.0, 1.0, 2.0], "telemetry never arrived"

    cmd_id = studio.send_command("ping", {"n": 1})
    ack = wait_for(studio, wire.Ack, deadline=3.0, match=lambda m: m.id == cmd_id)
    assert ack and ack.ok and ack.detail == "echo:ping", f"bad ack: {ack}"

    stop.set()
    inst.stop()
    print("PASS — discovery + telemetry + command/ack seam is live")


def wait_for(studio, kind, *, deadline, match=None):
    end = time.time() + deadline
    while time.time() < end:
        msg = studio.recv(timeout=0.5)
        if isinstance(msg, kind) and (match is None or match(msg)):
            return msg
    return None


if __name__ == "__main__":
    main()
