"""Daemon wire protocol — NDJSON over a Unix-domain socket.

Pure-data module: dataclasses + a codec. No IO. Both the server and the
client import from here, so the wire format has exactly one source of
truth and a typo in field names breaks tests immediately.

## Frame shapes

Each frame is a single UTF-8 JSON object followed by ``\\n``.

  - **Request** — client → daemon. ``{"id": <int>, "op": <str>, ...}``
    Every request carries an ``id`` the caller picks so the response can
    be matched (request/response on the same connection is logically
    pipelined; we don't rely on ordering).

  - **Response** — daemon → client. Always carries the request's ``id``.
    Success: ``{"id": <int>, "ok": true, "result": <any>}``
    Failure: ``{"id": <int>, "ok": false, "error": <str>}``

  - **Event** — daemon → client, unsolicited. ``{"event": <str>, ...}``
    Events carry no ``id`` because nothing on the client side is waiting
    on a specific one. The client treats them as a stream.

## Why NDJSON instead of length-prefixed framing

Stdlib only. Easy to debug with ``cat`` against a Unix socket. The
small downside — JSON can't carry an embedded newline in a string — is
handled by Python's ``json`` module, which escapes them on encode.

## Why a stateful Framer instead of one-call decode

A real socket delivers bytes in arbitrary chunks, never aligned to frame
boundaries. ``Framer`` buffers partial lines and yields complete
messages as they arrive. Single-frame ``decode()`` is kept as a
convenience for callers that already have a full frame in hand (notably
the test suite).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator, Union


class ProtocolError(ValueError):
    """A frame on the wire is malformed or doesn't match any known
    message shape. The dispatcher catches this and either drops the
    connection or returns a typed error response, depending on whether
    the frame was parseable enough to extract an ``id``."""


# ── message dataclasses ────────────────────────────────────────────


@dataclass(frozen=True)
class Request:
    """A client → daemon op. ``params`` carries keyword arguments for
    the op handler; we keep them in a nested dict (vs. ``**kwargs`` at
    the top level) so the wire format stays stable when we add fields
    like ``trace_id`` or ``session_key`` outside of params."""
    id: int
    op: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Response:
    """A daemon → client reply, matched to a Request by ``id``."""
    id: int
    ok: bool
    result: Any = None
    error: str | None = None

    @classmethod
    def for_request(cls, req: "Request", *,
                    ok: bool = True,
                    result: Any = None,
                    error: str | None = None) -> "Response":
        """Match the response's ``id`` to a Request — keeps every
        handler from having to remember to copy the id."""
        if error is not None:
            return cls(id=req.id, ok=False, error=error)
        return cls(id=req.id, ok=ok, result=result)


@dataclass(frozen=True)
class Event:
    """An unsolicited daemon → client message. Used for streaming
    status, partial tokens, tool-call notifications, and the
    permission-prompt round-trip in Phase 2."""
    name: str
    payload: dict[str, Any] = field(default_factory=dict)


Message = Union[Request, Response, Event]


# ── codec ──────────────────────────────────────────────────────────


def encode(msg: Message) -> bytes:
    """Serialize one frame, terminator included. Always UTF-8."""
    if isinstance(msg, Request):
        obj: dict[str, Any] = {"id": msg.id, "op": msg.op}
        if msg.params:
            obj["params"] = msg.params
    elif isinstance(msg, Response):
        obj = {"id": msg.id, "ok": msg.ok}
        if msg.ok:
            if msg.result is not None:
                obj["result"] = msg.result
        else:
            obj["error"] = msg.error or ""
    elif isinstance(msg, Event):
        obj = {"event": msg.name, **msg.payload}
    else:
        raise TypeError(f"not a Message: {type(msg).__name__}")
    # ``ensure_ascii=False`` keeps emoji + unicode readable on the wire;
    # ``separators`` trims spaces so a frame stays compact.
    return (json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
            + "\n").encode("utf-8")


def decode(frame: bytes) -> Message:
    """Parse one complete frame (with or without trailing newline) into
    its typed message. ``ProtocolError`` on garbage or unknown shape."""
    text = frame.decode("utf-8", errors="replace").strip()
    if not text:
        raise ProtocolError("empty frame")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(obj, dict):
        raise ProtocolError("frame must be a JSON object")
    return _from_dict(obj)


def _from_dict(obj: dict[str, Any]) -> Message:
    if "event" in obj:
        name = obj["event"]
        payload = {k: v for k, v in obj.items() if k != "event"}
        return Event(name=str(name), payload=payload)
    if "op" in obj:
        if "id" not in obj:
            raise ProtocolError("request missing 'id'")
        return Request(
            id=int(obj["id"]),
            op=str(obj["op"]),
            params=dict(obj.get("params") or {}),
        )
    if "ok" in obj:
        if "id" not in obj:
            raise ProtocolError("response missing 'id'")
        return Response(
            id=int(obj["id"]),
            ok=bool(obj["ok"]),
            result=obj.get("result"),
            error=obj.get("error"),
        )
    raise ProtocolError("unknown message shape (no 'op'/'ok'/'event' key)")


# ── streaming framer ───────────────────────────────────────────────


class Framer:
    """Reassembles NDJSON frames from arbitrary byte chunks.

    Usage::

        framer = Framer()
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            framer.feed(chunk)
            for msg in framer.drain():
                handle(msg)
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self._ready: list[Message] = []

    def feed(self, chunk: bytes) -> None:
        """Append bytes; parse out any newline-terminated frames found."""
        if not chunk:
            return
        self._buf.extend(chunk)
        while True:
            nl = self._buf.find(b"\n")
            if nl < 0:
                break
            line = bytes(self._buf[:nl])
            del self._buf[: nl + 1]
            if not line.strip():
                # Blank line between frames — common with CRLF clients
                # and harmless. Don't surface a ProtocolError for it.
                continue
            self._ready.append(decode(line))

    def drain(self) -> Iterator[Message]:
        """Yield every complete message accumulated since the last drain."""
        ready = self._ready
        self._ready = []
        yield from ready


__all__ = [
    "Event",
    "Framer",
    "Message",
    "ProtocolError",
    "Request",
    "Response",
    "decode",
    "encode",
]
