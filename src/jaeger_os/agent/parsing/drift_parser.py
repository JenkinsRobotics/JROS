"""Tolerant tool-call extractor for local-model text output.

Local GGUF chat templates (Gemma 4, Qwen3-Coder, Hermes) sometimes emit
tool calls as plain text instead of routing them through llama-cpp's
structured ``tool_calls`` field. The agent loop would otherwise see the
calls as inert assistant text and dispatch nothing. This module salvages
them — every dialect we've observed in the wild, with the parser chain
walking from strict JSON to the loosest fallback so a malformed but
real call still fires.

Three public entry points:

  • :func:`extract_tool_calls` — pull all calls out of an assistant text,
    return them as internal ``ToolCall`` dicts. The drop-in for the
    legacy ``_extract_drift_tool_calls`` that returned OpenAI shape.
  • :func:`repair_arguments` — best-effort repair of a malformed JSON
    string the structured path already handed us. Used by adapters that
    *do* get structured ``tool_calls`` but with broken ``arguments``.
  • :func:`normalize_tool_name` — exact-only alias resolution against a
    set of real tool names. No fuzzy matching — an unknown name returns
    unchanged so dispatch surfaces a clean "unknown tool" error.

All helpers are framework-free — they operate on strings + dicts. The
private parser internals (Gemma's ``<|"|>``-quoted strings, Qwen's
nested XML, paren-kwarg Python style, Hermes JSON envelopes) match the
pre-refactor ``core/llm_model.py`` implementation byte-for-byte so the
benchmark suite can compare apples to apples across the migration.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from jaeger_os.agent.schemas.message_types import ToolCall


# ── drift patterns (Gemma + Hermes envelopes) ───────────────────────

_DRIFT_PATTERNS = [
    # <|tool_call>call:name{...}<tool_call|>  (Gemma's native, brace args)
    # Tool names allow ``:`` and ``/`` so MCP qualified names like
    # ``mcp:web/fetch`` salvage.
    re.compile(
        r"<\|tool_call>\s*call:\s*([a-zA-Z_][\w:/.\-]*)\s*\{(.*?)\}\s*<tool_call\|>",
        re.DOTALL,
    ),
    # <|tool_call>call:name(key='value')<tool_call|>  (paren kwargs)
    re.compile(
        r"<\|tool_call>\s*call:\s*([a-zA-Z_][\w:/.\-]*)\s*\((.*?)\)\s*<tool_call\|>",
        re.DOTALL,
    ),
    # <|tool_call|>…<|/tool_call|>   (legacy Gemma JSON envelope)
    # <tool_call>…</tool_call>       (standard Hermes JSON envelope)
    # Capture EVERYTHING inside — not a brace block — so f-string braces
    # inside a ``content:"…"`` value don't stop the lazy quantifier early.
    re.compile(r"<\|tool_call\|>\s*(.*?)\s*<\|/tool_call\|>", re.DOTALL),
    re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL),
]

_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_GEMMA_QUOTE = '<|"|>'
_GEMMA_KEY = re.compile(r"[^:,{}\[\]]+")
_GEMMA_BARE = re.compile(r"[^,{}\[\]]+")

# Paren-kwarg parser regexes — Gemma's Python-style ``key='value', n=3``.
_NEXT_KWARG = re.compile(r"\s*,?\s*([a-zA-Z_]\w*)\s*=\s*")
_KWARG_BOUNDARY = re.compile(r"\s*,\s*[a-zA-Z_]\w*\s*=")

# Qwen3-Coder native XML form — distinct from any Gemma pattern.
_QWEN_TOOLCALL = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_QWEN_FUNCTION = re.compile(r"<function=([^>]+)>(.*?)</function>", re.DOTALL)
_QWEN_PARAM = re.compile(r"<parameter=([^>]+)>\n?(.*?)\n?</parameter>", re.DOTALL)


# ── helpers (verbatim from core/llm_model.py) ──────────────────────


def _degemma_quotes(raw: str) -> str:
    """Normalize Gemma's special-token quotes (``<|"|>``, ``<|'|>``)
    into plain JSON double-quotes. Left as-is they break ``json.loads``
    and silently drop the whole tool call."""
    return raw.replace('<|"|>', '"').replace("<|\'|>", '"')


def _coerce_scalar(val: str) -> Any:
    """Coerce a bare (unquoted) kwarg value to int / float / bool /
    None, else return it as a stripped string."""
    if val and val.lstrip("+-").replace(".", "", 1).isdigit():
        return float(val) if "." in val else int(val)
    low = val.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "none"):
        return None
    return val.strip("'\"")


def _parse_paren_args(raw: str) -> dict[str, Any]:
    """Parse Python-style ``key='value', count=3`` kwargs into a dict.

    Quote-aware. A string value may itself contain the quote character
    (Gemma routinely emits ``content='print(\\'hi\\')'``) — naive
    ``'([^']*)'`` truncates at the first inner quote. A closing quote is
    honoured only when followed by end-of-input or ``, <identifier>=``.
    """
    out: dict[str, Any] = {}
    s = raw
    n = len(s)
    i = 0
    while i < n:
        m = _NEXT_KWARG.match(s, i)
        if not m:
            break
        key = m.group(1)
        i = m.end()
        if i < n and s[i] in ("'", '"'):
            quote = s[i]
            i += 1
            buf: list[str] = []
            while i < n:
                c = s[i]
                if c == "\\" and i + 1 < n:
                    buf.append(s[i + 1])
                    i += 2
                    continue
                if c == quote:
                    rest = s[i + 1:]
                    if rest.strip() == "" or _KWARG_BOUNDARY.match(rest):
                        i += 1
                        break  # real closing quote
                    buf.append(c)  # literal quote inside the value
                    i += 1
                    continue
                buf.append(c)
                i += 1
            out[key] = "".join(buf)
        else:
            j = s.find(",", i)
            if j == -1:
                j = n
            out[key] = _coerce_scalar(s[i:j].strip())
            i = j
    return out


def _gemma_skip_ws(s: str, i: int) -> int:
    while i < len(s) and s[i] in " \t\r\n":
        i += 1
    return i


def _parse_gemma_value(s: str, i: int) -> tuple[Any, int]:
    """Recursive-descent parse of ONE Gemma-native value at ``s[i]``.
    Returns ``(value, index_after)``. Raises ``ValueError`` on malformed
    input."""
    i = _gemma_skip_ws(s, i)
    if i >= len(s):
        raise ValueError("unexpected end of input")
    if s.startswith(_GEMMA_QUOTE, i):
        start = i + len(_GEMMA_QUOTE)
        end = s.find(_GEMMA_QUOTE, start)
        if end == -1:
            raise ValueError("unterminated string")
        return s[start:end], end + len(_GEMMA_QUOTE)
    if s[i] == "{":
        obj: dict[str, Any] = {}
        i = _gemma_skip_ws(s, i + 1)
        if i < len(s) and s[i] == "}":
            return obj, i + 1
        while True:
            i = _gemma_skip_ws(s, i)
            if s.startswith(_GEMMA_QUOTE, i):
                key, i = _parse_gemma_value(s, i)
            else:
                km = _GEMMA_KEY.match(s, i)
                if not km:
                    raise ValueError("expected key")
                key, i = km.group(0).strip(), km.end()
            i = _gemma_skip_ws(s, i)
            if i >= len(s) or s[i] != ":":
                raise ValueError("expected ':'")
            val, i = _parse_gemma_value(s, i + 1)
            obj[str(key)] = val
            i = _gemma_skip_ws(s, i)
            if i < len(s) and s[i] == ",":
                i += 1
                continue
            if i < len(s) and s[i] == "}":
                return obj, i + 1
            raise ValueError("expected ',' or '}'")
    if s[i] == "[":
        arr: list[Any] = []
        i = _gemma_skip_ws(s, i + 1)
        if i < len(s) and s[i] == "]":
            return arr, i + 1
        while True:
            val, i = _parse_gemma_value(s, i)
            arr.append(val)
            i = _gemma_skip_ws(s, i)
            if i < len(s) and s[i] == ",":
                i += 1
                continue
            if i < len(s) and s[i] == "]":
                return arr, i + 1
            raise ValueError("expected ',' or ']'")
    bm = _GEMMA_BARE.match(s, i)
    if not bm:
        raise ValueError("expected value")
    return _coerce_scalar(bm.group(0).strip()), bm.end()


def _parse_loose_args(raw: str) -> dict[str, Any]:
    """Lossy fallback for Gemma input the recursive parser rejects.

    Returns whatever ``key:value`` pairs we can pluck out — better to
    fire the call with some args than drop it entirely. Used only after
    :func:`_parse_gemma_value` has failed.
    """
    cleaned = _degemma_quotes(raw)
    try:
        result = (
            json.loads("{" + cleaned + "}")
            if not cleaned.startswith("{")
            else json.loads(cleaned)
        )
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    pairs: dict[str, Any] = {}
    for match in re.finditer(r"([a-zA-Z_][\w]*)\s*:\s*\"([^\"]*)\"", cleaned):
        pairs[match.group(1)] = match.group(2)
    if pairs:
        return pairs
    for match in re.finditer(r"([a-zA-Z_][\w]*)\s*:\s*([^,}]+)", cleaned):
        pairs[match.group(1).strip()] = match.group(2).strip().strip('"').strip("'")
    return pairs


def _parse_gemma_args(raw: str) -> dict[str, Any]:
    """Parse Gemma 4's native tool-call brace arguments into a dict.

    Handles arbitrary nesting via :func:`_parse_gemma_value`; falls back
    to :func:`_parse_loose_args` when the input is too malformed for
    the recursive parser rather than dropping the whole call."""
    s = (raw or "").strip()
    if not s:
        return {}
    body = s if s.startswith("{") else "{" + s + "}"
    try:
        val, _ = _parse_gemma_value(body, 0)
        if isinstance(val, dict):
            return val
    except (ValueError, IndexError):
        pass
    return _parse_loose_args(raw)


def _parse_drift_payload(raw: str) -> dict[str, Any] | None:
    """Best-effort parse of the JSON-ish payload inside a
    ``<tool_call>…</tool_call>`` block.

    Walks an increasingly tolerant chain:

      1. Strict JSON after de-Gemma-quoting.
      2. Strict-off JSON (tolerates literal control characters in strings).
      3. Trailing-comma stripped, then strict-off JSON.
      4. Jaeger's loose Gemma parser — bare keys, Gemma quote tokens,
         missing key-quotes — with surrounding quote chars stripped from
         the keys / string values it leaves embedded.
    """
    text = (raw or "").strip()
    if not text:
        return None
    degemma = _degemma_quotes(text)
    candidates = [degemma]
    stripped = _TRAILING_COMMA.sub(r"\1", degemma)
    if stripped != degemma:
        candidates.append(stripped)
    for candidate in candidates:
        for strict in (True, False):
            try:
                parsed = json.loads(candidate, strict=strict)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    loose = _parse_gemma_args(text)
    if not loose:
        return None
    cleaned: dict[str, Any] = {}
    for key, value in loose.items():
        if isinstance(key, str):
            key = key.strip().strip('"').strip("'")
        if isinstance(value, str):
            value = value.strip().strip('"').strip("'")
        cleaned[key] = value
    return cleaned or None


_LLAMA_BOT = "<|python_tag|>"


def _extract_llama_raw_json_tool_calls(text: str) -> list[dict[str, Any]]:
    """Salvage Llama 3.x / 4 raw-JSON tool calls.

    Llama emits something like::

        <|python_tag|>{"name": "get_time", "parameters": {"timezone": "UTC"}}

    or simply (no bot-token)::

        {"name": "get_weather", "arguments": {"location": "Tokyo"}}

    The leading ``<|python_tag|>`` is optional. We use stdlib's
    ``json.JSONDecoder.raw_decode`` so multiple JSON objects in a row
    work, and we tolerate surrounding prose. Either ``arguments`` or
    ``parameters`` is accepted (Llama uses ``parameters``, the rest of
    the local-model matrix uses ``arguments``)."""
    # Trim past the bot token if present so the first brace is the
    # JSON we care about.
    scan = text.split(_LLAMA_BOT, 1)[1] if _LLAMA_BOT in text else text
    out: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(scan):
        # Hop to the next '{' — raw_decode wants a JSON-shaped prefix.
        brace = scan.find("{", idx)
        if brace < 0:
            break
        try:
            obj, end = decoder.raw_decode(scan, brace)
        except json.JSONDecodeError:
            idx = brace + 1
            continue
        if isinstance(obj, dict):
            name = obj.get("name") or obj.get("tool_name") or ""
            args = obj.get("arguments")
            if args is None:
                args = obj.get("parameters")
            if isinstance(name, str) and name and isinstance(args, dict):
                out.append({"name": name.strip(), "args": args})
        idx = end
    return out


_MISTRAL_BOT = "[TOOL_CALLS]"


def _extract_mistral_tool_calls(text: str) -> list[dict[str, Any]]:
    """Salvage Mistral ``[TOOL_CALLS]`` emissions.

    Two formats, both seen in the wild:

      - **Pre-v11** (JSON array):
        ``content[TOOL_CALLS] [{"name": "...", "arguments": {...}}, ...]``
      - **v11+** (interleaved): ``[TOOL_CALLS]name1{"k":"v"}[TOOL_CALLS]name2{"k":"v"}``

    Mirrors Hermes's mistral_parser shape. Refuses to fuzzy-match an
    unknown name — same conservative stance as the Gemma/Qwen branches."""
    idx = text.find(_MISTRAL_BOT)
    if idx < 0:
        return []
    out: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()

    while idx >= 0:
        # Move past the bot token and any whitespace.
        cursor = idx + len(_MISTRAL_BOT)
        while cursor < len(text) and text[cursor] in (" ", "\t", "\n", "\r"):
            cursor += 1
        if cursor >= len(text):
            break
        ch = text[cursor]
        if ch == "[":
            # Pre-v11 — single JSON array of {"name", "arguments"} objects.
            try:
                arr, end = decoder.raw_decode(text, cursor)
            except json.JSONDecodeError:
                break
            if isinstance(arr, list):
                for item in arr:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("name") or ""
                    args = item.get("arguments") or item.get("parameters") or {}
                    if isinstance(name, str) and name and isinstance(args, dict):
                        out.append({"name": name.strip(), "args": args})
            idx = text.find(_MISTRAL_BOT, end)
            continue
        # v11+ — bare ``name{"k":"v"}``; possibly chained with more
        # [TOOL_CALLS]name{...} segments. Read name up to the first
        # ``{`` (greedy), then raw_decode the JSON args.
        brace = text.find("{", cursor)
        if brace < 0:
            break
        name = text[cursor:brace].strip()
        try:
            obj, end = decoder.raw_decode(text, brace)
        except json.JSONDecodeError:
            break
        if name and isinstance(obj, dict):
            out.append({"name": name, "args": obj})
        idx = text.find(_MISTRAL_BOT, end)
    return out


def _extract_qwen_tool_calls(text: str) -> list[dict[str, Any]]:
    """Salvage Qwen3-Coder's ``<function=…><parameter=…>`` tool calls.

    Two shapes in the wild, both salvaged here:

      - **Strict (chat-template official):**
        ``<tool_call><function=X><parameter=Y>v</parameter></function></tool_call>``
      - **Loose (the model sometimes drops the wrapper):**
        ``<function=X><parameter=Y>v</parameter></function>``
        — and sometimes appends a stray ``</tool_call>`` closer with no
        matching opener.

    The user reported the loose form leaking into chat text on
    Qwen3-Coder-30B-A3B; the agent never dispatched because the parser
    only scanned inside ``<tool_call>`` wrappers. Now we accept either.

    Returns ``[{name, args}]`` — internal shape conversion lives in the
    public :func:`extract_tool_calls`. Parameter values are kept as raw
    strings; downstream Pydantic validation coerces them.
    """
    out: list[dict[str, Any]] = []
    seen_spans: set[tuple[int, int]] = set()

    # 1. Strict form first — any <function=> *inside* a <tool_call>
    #    wrapper. Recording the span lets us skip the same function
    #    block in the loose-form pass below.
    for tc in _QWEN_TOOLCALL.finditer(text):
        for fn in _QWEN_FUNCTION.finditer(tc.group(1)):
            name = fn.group(1).strip()
            if not name:
                continue
            args: dict[str, Any] = {}
            for pm in _QWEN_PARAM.finditer(fn.group(2)):
                args[pm.group(1).strip()] = pm.group(2)
            out.append({"name": name, "args": args})
        seen_spans.add((tc.start(), tc.end()))

    # 2. Loose form — any <function=> NOT covered by a strict wrapper.
    #    Iterate top-level and skip matches that fall inside a span we
    #    already processed.
    for fn in _QWEN_FUNCTION.finditer(text):
        start, end = fn.start(), fn.end()
        if any(s <= start and end <= e for s, e in seen_spans):
            continue
        name = fn.group(1).strip()
        if not name:
            continue
        args = {}
        for pm in _QWEN_PARAM.finditer(fn.group(2)):
            args[pm.group(1).strip()] = pm.group(2)
        out.append({"name": name, "args": args})
    return out


# ── public surface ─────────────────────────────────────────────────


def _new_id(prefix: str = "drift") -> str:
    """Synthetic tool-call IDs for drift-recovered calls. The wire
    response had no real ID — we mint one so the loop's tool_call_id
    bookkeeping stays consistent across iterations."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def extract_tool_calls(text: str) -> list[ToolCall]:
    """Extract tool calls from a model's NATIVE textual form.

    Covers Gemma 4's three dialects (brace args / paren kwargs / JSON
    envelope) and Qwen3-Coder's nested XML. Returns an empty list when
    no recognised dialect appears — the agent loop then treats the
    response as a final answer.

    Returned dicts are in *internal* :class:`ToolCall` shape with
    ``arguments`` as a real ``dict`` (not a JSON-encoded string).
    """
    # Mistral's bot-token form — ``[TOOL_CALLS]`` followed by either a
    # JSON array (pre-v11) or interleaved name + brace-args (v11+). No
    # ``<`` needed; check first so we don't fall into the no-``<``
    # early-return below.
    if "[TOOL_CALLS]" in text:
        mistral = _extract_mistral_tool_calls(text)
        if mistral:
            return [
                {"id": _new_id("mistral"), "name": m["name"],
                 "arguments": m["args"]}
                for m in mistral
            ]

    # Llama 3.x/4 raw-JSON form — a bare ``{"name": "...", "arguments":
    # {...}}`` (or ``parameters``) preceded by ``<|python_tag|>``, OR
    # the same JSON shape with NO XML wrapping at all. We deliberately
    # require ``<|python_tag|>`` OR absence of every other dialect's
    # opening tag — otherwise the JSON-envelope-inside-``<tool_call>``
    # Hermes shape would be misclassified as Llama.
    _llama_marker_present = _LLAMA_BOT in text
    _other_wrapper_present = (
        "<tool_call>" in text
        or "<|tool_call|>" in text
        or "<|tool_call>" in text
        or "<function=" in text
    )
    if (_llama_marker_present or not _other_wrapper_present) and (
        "{" in text and ('"name"' in text or '"tool_name"' in text)
    ):
        llama = _extract_llama_raw_json_tool_calls(text)
        if llama:
            return [
                {"id": _new_id("llama"), "name": l["name"],
                 "arguments": l["args"]}
                for l in llama
            ]

    if "<" not in text:
        return []

    # Qwen's <function=…> form is distinct from every Gemma pattern; a
    # model only ever speaks one dialect, so if Qwen calls are present
    # they ARE the answer.
    qwen = _extract_qwen_tool_calls(text)
    if qwen:
        return [
            {
                "id": _new_id("qwen"),
                "name": q["name"],
                "arguments": q["args"],
            }
            for q in qwen
        ]

    out: list[ToolCall] = []
    for pat_idx, pattern in enumerate(_DRIFT_PATTERNS):
        for match in pattern.finditer(text):
            groups = match.groups()
            if len(groups) == 2:
                # Gemma form: (name, args_inner)
                name = groups[0]
                if pat_idx == 1:
                    args: Any = _parse_paren_args(groups[1])
                else:
                    args = _parse_gemma_args(groups[1])
            elif len(groups) == 1:
                # JSON envelope — tolerant parser chain.
                payload = _parse_drift_payload(groups[0])
                if not payload:
                    continue
                name = (
                    payload.pop("name", None)
                    or payload.pop("tool", None)
                    or ""
                )
                # Two emission styles for arguments:
                #   • Hermes-XML:  {"name": "X", "arguments": {...}}
                #   • Gemma flat:  {"name": "X", "path": "...", ...}
                # In the flat style every remaining top-level key IS
                # an arg.
                if "arguments" in payload:
                    args = payload["arguments"] or {}
                elif "args" in payload:
                    args = payload["args"] or {}
                else:
                    args = payload
                if isinstance(args, str):
                    inner = _parse_drift_payload(args)
                    args = inner if inner is not None else {}
            else:
                continue
            if not name:
                continue
            if not isinstance(args, dict):
                args = {"value": args}
            out.append({
                "id": _new_id("drift"),
                "name": str(name),
                "arguments": args,
            })
    return out


def _coerce_args_dict(parsed: Any) -> dict[str, Any] | None:
    """Coerce a ``json.loads`` result into a plain args dict, or
    ``None`` when it cannot be one. Also unwraps the double-encoded
    ``'{"x": 1}'`` string local models occasionally emit."""
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, str):
        try:
            inner = json.loads(parsed, strict=False)
        except json.JSONDecodeError:
            return None
        if isinstance(inner, dict):
            return inner
    return None


def repair_arguments(raw: str) -> tuple[dict[str, Any], bool]:
    """Best-effort repair of a malformed tool-call ``arguments`` JSON
    string the *structured* tool-calling path handed us. Returns
    ``(args, recovered)``. ``recovered`` is ``False`` only when every
    pass failed and the caller is getting ``{}`` as a last resort — so
    it can record the parse failure instead of swallowing it silently.

    Conservative on purpose: fixes drift we've actually observed (Gemma
    special-token quotes, literal control chars, trailing commas, wholly
    single-quoted blobs, Python ``None``/``null``) then hands off to the
    tolerant Gemma parser rather than guessing further.
    """
    s = (raw or "").strip()
    if not s or s.lower() in ("none", "null"):
        return {}, True

    cleaned = _degemma_quotes(s)
    for candidate in (cleaned, _TRAILING_COMMA.sub(r"\1", cleaned)):
        try:
            parsed = json.loads(candidate, strict=False)
        except json.JSONDecodeError:
            continue
        coerced = _coerce_args_dict(parsed)
        if coerced is not None:
            return coerced, True

    if "'" in cleaned and '"' not in cleaned:
        try:
            parsed = json.loads(cleaned.replace("'", '"'), strict=False)
        except json.JSONDecodeError:
            parsed = None
        coerced = _coerce_args_dict(parsed)
        if coerced is not None:
            return coerced, True

    loose = _parse_gemma_args(s)
    if loose:
        return loose, True

    return {}, False


# Explicit alias map: pre-rename / pre-consolidation tool names →
# their current canonical name. Only added when the rename was
# documented and the older name had real bench / training data
# behind it. NOT a fuzzy match table — an alias here only fires
# if the canonical name is in the agent's registered ``valid`` set,
# so adding entries is safe.
#
# Keep this small and intentional. The point is to absorb known
# historical drift (``run_python`` → ``execute_code``); we do NOT
# want a model guessing a tool that doesn't exist and silently
# landing on something else.
_TOOL_ALIASES: dict[str, str] = {
    # Phase-9 rename.
    "run_python":   "execute_code",
    "run_shell":    "terminal",
    # Pre-umbrella memory verbs. The granular tools are still
    # registered (under the ``memory_granular`` toolset) so this
    # alias only fires when they're not currently visible AND the
    # umbrella is.
    # NB ordering matters — these are checked LAST, after the
    # exact-case lookup. A model that explicitly calls ``remember``
    # while the granular toolset is loaded still routes there.
    # Aliasing only kicks in when ``remember`` is NOT in ``valid``
    # but ``memory`` is.
    # Voice / file legacy spellings.
    "speak":        "text_to_speech",
    "file_write":   "write_file",
    "file_read":    "read_file",
    # Skill index — old names that may surface from training data.
    "list_tools":   "describe_tool",
}


def normalize_tool_name(name: str, valid: frozenset[str] | set[str]) -> str:
    """Map a drifted tool name onto a real one via exact alias / case /
    separator variants. No fuzzy matching — an unrecognised name is
    returned unchanged so dispatch surfaces a clean 'unknown tool'
    error and the model retries, rather than silently dispatching a
    guess.

    Resolution order (first match wins):
      1. exact match in ``valid``
      2. case / separator / trailing-``tool``-suffix variants
      3. the explicit :data:`_TOOL_ALIASES` table (only when the
         alias target is itself in ``valid``)
    """
    raw = (name or "").strip()
    if not raw or not valid or raw in valid:
        return raw
    candidates: list[str] = []

    def _add(candidate: str) -> None:
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    lowered = raw.lower()
    _add(lowered)
    _add(lowered.replace("-", "_").replace(" ", "_").replace(".", "_"))
    _add(re.sub(r"(?<!^)(?=[A-Z])", "_", raw).lower())
    # A trailing ``tool`` / ``_tool`` the model sometimes tacks onto a
    # class-like emission (``ReadFileTool``, ``read_file_tool``).
    for base in list(candidates):
        for suffix in ("_tool", "-tool", "tool"):
            if base.endswith(suffix) and len(base) > len(suffix):
                _add(base[: -len(suffix)].rstrip("_-"))
    for candidate in candidates:
        if candidate in valid:
            return candidate
    # Explicit alias as last resort — only redirects when the alias's
    # target is a real registered tool.
    for candidate in candidates + [raw]:
        target = _TOOL_ALIASES.get(candidate)
        if target and target in valid:
            return target
    return raw


__all__ = [
    "extract_tool_calls",
    "repair_arguments",
    "normalize_tool_name",
]
