"""Qt <-> asyncio bridge for the QUIC link.

aioquic is asyncio; Qt is its own loop. Rather than pull in qasync, run the link
in a daemon thread with its own event loop and hand messages to the GUI as Qt
signals (auto-queued to the GUI thread). Commands go the other way via
run_coroutine_threadsafe. ~1 small class, no new dependency.
"""
from __future__ import annotations

import asyncio
import threading

from PySide6.QtCore import QObject, Signal

from link import wire
from link.quic import studio_connect


class AsyncLink(QObject):
    telemetry = Signal(object)      # wire.Telemetry
    event = Signal(object)          # wire.Event
    ack = Signal(object)            # wire.Ack
    connected = Signal()
    disconnected = Signal(str)

    def __init__(self, host: str, port: int):
        super().__init__()
        self._host, self._port = host, port
        self._loop: asyncio.AbstractEventLoop | None = None
        self._link = None

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def send_command(self, name: str, args: dict | None = None) -> None:
        if self._link and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._link.send_command(name, args or {}), self._loop)

    # --- worker thread ---

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self) -> None:
        try:
            async with studio_connect(self._host, self._port, name="studio") as link:
                self._link = link
                self.connected.emit()
                while True:
                    msg = await link.recv(timeout=1.0)
                    if isinstance(msg, wire.Telemetry):
                        self.telemetry.emit(msg)
                    elif isinstance(msg, wire.Event):
                        self.event.emit(msg)
                    elif isinstance(msg, wire.Ack):
                        self.ack.emit(msg)
        except Exception as e:  # dev shell: surface, don't crash the GUI
            self.disconnected.emit(repr(e))
