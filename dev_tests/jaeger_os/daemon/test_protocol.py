"""Wire-format protocol — pure-data round-trips.

The daemon protocol is NDJSON: one JSON object per line, UTF-8. Three
message shapes:

  - **Request** — client → daemon. Carries an ``id`` so a response can be
    matched. ``{"id": 1, "op": "ping"}``
  - **Response** — daemon → client, matched by ``id``.
    ``{"id": 1, "ok": true, "result": {...}}``  or
    ``{"id": 1, "ok": false, "error": "..."}``
  - **Event** — daemon → client, unsolicited. No ``id``.
    ``{"event": "status", "phase": "thinking"}``

This file exercises:
  - encode / decode round-trips for every message kind
  - a malformed line surfaces a clean ``ProtocolError``, not a crash
  - the codec is a true stream — partial reads buffer until a newline
"""

from __future__ import annotations

import json

import pytest

from jaeger_os.daemon import protocol as P


# ── encode / decode round-trips ────────────────────────────────────


def test_request_round_trip_minimal():
    """Smallest valid request: id + op, no kwargs."""
    req = P.Request(id=1, op="ping")
    wire = P.encode(req)
    assert wire.endswith(b"\n"), "every frame ends in a newline (NDJSON)"
    out = json.loads(wire.decode("utf-8"))
    assert out == {"id": 1, "op": "ping"}

    decoded = P.decode(wire)
    assert isinstance(decoded, P.Request)
    assert decoded.id == 1
    assert decoded.op == "ping"
    assert decoded.params == {}


def test_request_round_trip_with_params():
    """``params`` carries the op's keyword arguments."""
    req = P.Request(id=7, op="submit_turn",
                    params={"prompt": "what time is it?",
                            "session_key": "tui-default"})
    wire = P.encode(req)
    decoded = P.decode(wire)
    assert isinstance(decoded, P.Request)
    assert decoded.params["prompt"] == "what time is it?"
    assert decoded.params["session_key"] == "tui-default"


def test_response_ok_round_trip():
    resp = P.Response(id=1, ok=True, result={"pong": True})
    decoded = P.decode(P.encode(resp))
    assert isinstance(decoded, P.Response)
    assert decoded.ok is True
    assert decoded.result == {"pong": True}
    assert decoded.error is None


def test_response_error_round_trip():
    """An error response carries ``error`` and has ``ok=False``."""
    resp = P.Response(id=1, ok=False, error="bad op")
    decoded = P.decode(P.encode(resp))
    assert isinstance(decoded, P.Response)
    assert decoded.ok is False
    assert decoded.error == "bad op"
    assert decoded.result is None


def test_event_round_trip():
    """Events carry an ``event`` name + arbitrary payload, no id."""
    evt = P.Event(name="status",
                  payload={"phase": "thinking", "detail": ""})
    decoded = P.decode(P.encode(evt))
    assert isinstance(decoded, P.Event)
    assert decoded.name == "status"
    assert decoded.payload["phase"] == "thinking"


# ── error handling ─────────────────────────────────────────────────


def test_decoding_invalid_json_raises_protocol_error():
    """Garbage on the wire fails with a typed error, not a JSONDecodeError —
    so the dispatch loop can ``except ProtocolError`` cleanly."""
    with pytest.raises(P.ProtocolError):
        P.decode(b"{not json}\n")


def test_decoding_unknown_shape_raises_protocol_error():
    """A line that's valid JSON but matches none of our shapes (no
    ``op``, no ``ok``, no ``event``) is a protocol violation."""
    with pytest.raises(P.ProtocolError):
        P.decode(b'{"hello": "world"}\n')


def test_decoding_response_without_id_is_protocol_error():
    """Responses MUST carry an ``id`` so a caller can match — a missing
    id is unrecoverable, not a default to zero."""
    with pytest.raises(P.ProtocolError):
        P.decode(b'{"ok": true, "result": {}}\n')


# ── streaming codec ────────────────────────────────────────────────


def test_framer_yields_one_message_per_line():
    """Two frames concatenated on the wire produce two decoded messages."""
    framer = P.Framer()
    a = P.encode(P.Request(id=1, op="ping"))
    b = P.encode(P.Request(id=2, op="status"))
    framer.feed(a + b)
    msgs = list(framer.drain())
    assert len(msgs) == 2
    assert msgs[0].id == 1
    assert msgs[1].id == 2


def test_framer_holds_partial_line_until_newline():
    """A real socket can deliver bytes in arbitrary chunks. The framer
    must not emit a message until it sees the terminating newline."""
    framer = P.Framer()
    full = P.encode(P.Request(id=42, op="ping"))
    # Split the frame so the newline arrives in the second chunk.
    half = len(full) - 3
    framer.feed(full[:half])
    assert list(framer.drain()) == [], "no newline yet — must buffer"
    framer.feed(full[half:])
    msgs = list(framer.drain())
    assert len(msgs) == 1
    assert msgs[0].op == "ping"


def test_framer_swallows_blank_lines_between_frames():
    """Some clients emit ``\\r\\n`` line endings or stray blank lines —
    treat them as no-ops, not protocol errors."""
    framer = P.Framer()
    a = P.encode(P.Request(id=1, op="ping"))
    framer.feed(a + b"\n\n" + a)
    msgs = list(framer.drain())
    assert len(msgs) == 2


# ── helper constructors ────────────────────────────────────────────


def test_response_for_builds_a_matching_response():
    """``Response.for_request`` keeps id-matching out of every handler."""
    req = P.Request(id=99, op="ping")
    ok = P.Response.for_request(req, ok=True, result={"pong": True})
    assert ok.id == 99
    err = P.Response.for_request(req, error="nope")
    assert err.id == 99
    assert err.ok is False
    assert err.error == "nope"
