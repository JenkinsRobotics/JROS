"""Custom Pydantic AI Model that wraps an in-process llama-cpp-python Llama.

Same Llama instance our other frameworks use — no HTTP layer, no separate
llama-server process. We adapt llama-cpp-python's OpenAI-style chat-completion
output to pydantic-ai's ModelMessage / ModelResponse format.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any


def _native_tools_enabled() -> bool:
    """Whether to render conversation history in each model's NATIVE tool
    dialect (structured ``tool_calls`` + ``tool`` messages, rendered by
    the GGUF's own chat template) instead of the legacy Hermes-XML path.

    OFF by default — the prototype A/B (docs/native_handler_ab.md) showed
    the native path is a wash on accuracy at n=1, so the proven legacy
    baseline stays the default until a multi-sample run justifies the
    switch. ``JAEGER_NATIVE_TOOLS=1`` opts in."""
    return os.environ.get("JAEGER_NATIVE_TOOLS", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


# Drift patterns: Gemma 4 (not OpenAI-tuned) sometimes emits tool calls in
# its own XML-ish format that llama-cpp-python's chat handler doesn't
# convert into structured tool_calls. We salvage them here so pydantic-ai
# sees a proper ToolCallPart and not a raw text blob.
_DRIFT_PATTERNS = [
    # <|tool_call>call:name{...}<tool_call|>  (Gemma's native form, brace args)
    # Tool names allow `:` and `/` so MCP qualified names like mcp:web/fetch salvage.
    re.compile(r"<\|tool_call>\s*call:\s*([a-zA-Z_][\w:/.\-]*)\s*\{(.*?)\}\s*<tool_call\|>", re.DOTALL),
    # <|tool_call>call:name(key='value')<tool_call|>  (paren args — Gemma's
    # Python-kwargs variant, observed in Level-2 bench for recall/remember)
    re.compile(r"<\|tool_call>\s*call:\s*([a-zA-Z_][\w:/.\-]*)\s*\((.*?)\)\s*<tool_call\|>", re.DOTALL),
    # <|tool_call|>…<|/tool_call|>   (legacy Gemma JSON envelope)
    # <tool_call>…</tool_call>       (standard Hermes JSON envelope)
    # Capture EVERYTHING between the tags — not a brace block — so f-string
    # braces inside a `content:"…"` value (e.g. ``f"...{x}..."``) do not stop
    # the lazy quantifier early and shred the payload.
    re.compile(r"<\|tool_call\|>\s*(.*?)\s*<\|/tool_call\|>", re.DOTALL),
    re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL),
]


# Trailing comma in a JSON-ish blob (used by both _parse_drift_payload and
# _repair_tool_call_arguments). Defined up here because the drift parser
# below uses it before the repair helpers further down the file.
_DRIFT_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def _parse_drift_payload(raw: str) -> dict[str, Any] | None:
    """Best-effort parse of the JSON-ish payload inside a
    ``<tool_call>…</tool_call>`` block. Walks an increasingly tolerant
    parser chain so we recover real tool calls from Gemma's malformed
    emissions instead of letting the agent emit them as inert text:

      1. Strict JSON after de-Gemma-quoting.
      2. Strict-off JSON (tolerates literal control characters in strings).
      3. Trailing-comma stripped, then strict-off JSON.
      4. Jaeger's loose Gemma parser — accepts bare keys, Gemma quote
         tokens, missing key-quotes — with surrounding quote chars stripped
         from the keys / string values it leaves embedded.
    """
    text = (raw or "").strip()
    if not text:
        return None
    degemma = _degemma_quotes(text)
    candidates = [degemma]
    stripped_commas = _DRIFT_TRAILING_COMMA.sub(r"\1", degemma)
    if stripped_commas != degemma:
        candidates.append(stripped_commas)
    for candidate in candidates:
        for strict in (True, False):
            try:
                parsed = json.loads(candidate, strict=strict)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    # Fall back to the Gemma-native loose parser — it accepts bare keys and
    # Gemma quote tokens, which is what survives when strict JSON cannot.
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


_NEXT_KWARG = re.compile(r"\s*,?\s*([a-zA-Z_]\w*)\s*=\s*")
# A candidate closing quote is real only when what follows is the end
# of the args, or a `, <identifier>=` that opens the next kwarg.
_KWARG_BOUNDARY = re.compile(r"\s*,\s*[a-zA-Z_]\w*\s*=")


def _coerce_scalar(val: str) -> Any:
    """Coerce a bare (unquoted) kwarg value to int / float / bool / None,
    else return it as a stripped string."""
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

    Quote-aware. A string value may itself contain the quote character —
    Gemma routinely emits code-bearing args like
    ``content='print('hi')'`` — so a naive ``'([^']*)'`` regex truncates
    the value at the first inner quote. Here a closing quote is honored
    only when it is followed by end-of-input or ``, <identifier>=``
    (the start of the next kwarg); any other quote is a literal inside
    the value. Backslash escapes are respected. Bare numbers / booleans
    / null coerce to their Python equivalents.
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
            # Bare value — up to the next top-level comma.
            j = s.find(",", i)
            if j == -1:
                j = n
            out[key] = _coerce_scalar(s[i:j].strip())
            i = j
    return out


def _degemma_quotes(raw: str) -> str:
    """Normalize Gemma's special-token quotes (`<|"|>`, `<|'|>`) into
    plain JSON double-quotes. Gemma routinely wraps string values in
    these instead of real quotes — left as-is they make ``json.loads``
    fail, which silently drops the whole tool call."""
    return raw.replace('<|"|>', '"').replace("<|'|>", '"')


def _parse_loose_args(raw: str) -> dict[str, Any]:
    """Convert Gemma's loose `{timezone:<|"|>Asia/Shanghai<|"|>}` into a clean dict.

    Gemma drops standard JSON quoting in favor of its own special-token
    quotes (`<|"|>...<|"|>`). We strip those and try to parse what's left
    as JSON; if that fails, parse manually.
    """
    cleaned = _degemma_quotes(raw)
    # Try parsing as JSON first
    try:
        result = json.loads("{" + cleaned + "}") if not cleaned.startswith("{") else json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    # Manual parse: key:"value" pairs
    pairs: dict[str, Any] = {}
    for match in re.finditer(r"([a-zA-Z_][\w]*)\s*:\s*\"([^\"]*)\"", cleaned):
        pairs[match.group(1)] = match.group(2)
    if pairs:
        return pairs
    # Last resort: try to interpret as bare key:value
    for match in re.finditer(r"([a-zA-Z_][\w]*)\s*:\s*([^,}]+)", cleaned):
        pairs[match.group(1).strip()] = match.group(2).strip().strip('"').strip("'")
    return pairs


# --- Gemma 4 native brace-arg parser -------------------------------------------
# Gemma 4's chat template renders tool-call arguments as a JSON-ish object
# with BARE keys and <|"|>-delimited strings, e.g.
#   {query:<|"|>population of japan<|"|>,max_results:5,opts:{deep:true}}
# A proper recursive parser handles arbitrary nesting and — unlike the old
# _parse_loose_args, which returned on the first quoted pair — never drops a
# key.
_GEMMA_QUOTE = '<|"|>'
_GEMMA_KEY = re.compile(r"[^:,{}\[\]]+")
_GEMMA_BARE = re.compile(r"[^,{}\[\]]+")


def _gemma_skip_ws(s: str, i: int) -> int:
    while i < len(s) and s[i] in " \t\r\n":
        i += 1
    return i


def _parse_gemma_value(s: str, i: int) -> tuple[Any, int]:
    """Recursive-descent parse of ONE Gemma-native value at ``s[i]``.
    Returns ``(value, index_after)``. Raises ValueError on malformed input."""
    i = _gemma_skip_ws(s, i)
    if i >= len(s):
        raise ValueError("unexpected end of input")
    # String — <|"|>...<|"|>
    if s.startswith(_GEMMA_QUOTE, i):
        start = i + len(_GEMMA_QUOTE)
        end = s.find(_GEMMA_QUOTE, start)
        if end == -1:
            raise ValueError("unterminated string")
        return s[start:end], end + len(_GEMMA_QUOTE)
    # Object — {key:value,...} with bare or quoted keys
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
    # Array — [value,...]
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
    # Bareword — number / bool / null / unquoted text
    bm = _GEMMA_BARE.match(s, i)
    if not bm:
        raise ValueError("expected value")
    return _coerce_scalar(bm.group(0).strip()), bm.end()


def _parse_gemma_args(raw: str) -> dict[str, Any]:
    """Parse Gemma 4's native tool-call brace arguments into a dict.

    Handles arbitrary nesting and never silently drops a key. Falls back
    to the older loose parse rather than dropping the whole call when the
    input is too malformed for the recursive parser."""
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


# --- Qwen3-Coder native tool-call parser ---------------------------------------
# Qwen3-Coder emits tool calls as nested XML, NOT JSON:
#   <tool_call><function=name><parameter=p>value</parameter></function></tool_call>
_QWEN_TOOLCALL = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_QWEN_FUNCTION = re.compile(r"<function=([^>]+)>(.*?)</function>", re.DOTALL)
_QWEN_PARAM = re.compile(r"<parameter=([^>]+)>\n?(.*?)\n?</parameter>", re.DOTALL)


def _extract_qwen_tool_calls(text: str) -> list[dict[str, Any]]:
    """Salvage Qwen3-Coder's native ``<function=…><parameter=…>`` tool
    calls. Returns OpenAI-style tool_calls. Parameter values are kept as
    raw strings — pydantic-ai coerces them against the tool schema."""
    out: list[dict[str, Any]] = []
    for tc in _QWEN_TOOLCALL.finditer(text):
        for fn in _QWEN_FUNCTION.finditer(tc.group(1)):
            name = fn.group(1).strip()
            if not name:
                continue
            args: dict[str, Any] = {}
            for pm in _QWEN_PARAM.finditer(fn.group(2)):
                args[pm.group(1).strip()] = pm.group(2)
            out.append({
                "id": "qwen_" + uuid.uuid4().hex[:8],
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            })
    return out


def _extract_drift_tool_calls(text: str) -> list[dict[str, Any]]:
    """Extract tool calls from a model's NATIVE textual form when
    llama-cpp-python didn't parse them into structured tool_calls.

    Covers Gemma 4 (``<|tool_call>call:name{…}<tool_call|>``) and
    Qwen3-Coder (``<function=…><parameter=…>``) — each model's own
    dialect. Returns OpenAI-style tool_calls."""
    # Cheap early-exit: every native form opens with `<`.
    if "<" not in text:
        return []
    # Qwen3-Coder's <function=…> form is distinct from every Gemma
    # pattern; a model only ever speaks one dialect, so if Qwen calls
    # are present they ARE the answer.
    qwen = _extract_qwen_tool_calls(text)
    if qwen:
        return qwen
    out: list[dict[str, Any]] = []
    for pat_idx, pattern in enumerate(_DRIFT_PATTERNS):
        for match in pattern.finditer(text):
            groups = match.groups()
            if len(groups) == 2:
                # Gemma form: (name, args_inner)
                name = groups[0]
                # Pattern 0 = brace args; pattern 1 = paren kwargs.
                if pat_idx == 1:
                    args = _parse_paren_args(groups[1])
                else:
                    args = _parse_gemma_args(groups[1])
            elif len(groups) == 1:
                # JSON envelope — walks several tolerant parsers so we
                # recover even when Gemma writes a malformed payload (key
                # missing closing quote, value wrapped in `<|"|>` instead
                # of `"`, etc.). Without this the call would be emitted as
                # inert text and never fire.
                payload = _parse_drift_payload(groups[0])
                if not payload:
                    continue
                name = (payload.pop("name", None)
                        or payload.pop("tool", None)
                        or "")
                # Two emission styles for arguments:
                #   • Hermes-XML:  {"name": "X", "arguments": {...}}
                #   • Gemma flat:  {"name": "X", "path": "...", "content": ...}
                # In the flat style every remaining top-level key IS an arg.
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
            out.append({
                "id": "drift_" + uuid.uuid4().hex[:8],
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            })
    return out


# --- Tool-call repair & normalization ------------------------------------------
# Local GGUF chat handlers (Gemma 4, Qwen3) sometimes hand llama-cpp-python a
# tool call it DOES parse into structured ``tool_calls`` — but with malformed
# JSON arguments or a drifted tool name. The old path silently turned a JSON
# parse failure into ``args = {}`` and passed the raw name through unchanged,
# converting a parse failure into a confident-looking *wrong* tool attempt.
# These helpers repair the common local-model drift conservatively before
# pydantic-ai sees the call; genuine schema errors still fall through to
# pydantic-ai's own validation retry.

_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def _coerce_args_dict(parsed: Any) -> dict[str, Any] | None:
    """Coerce a ``json.loads`` result into a plain args dict, or ``None`` when
    it cannot be one. Also unwraps the double-encoded ``'{"x": 1}'`` string
    that local models occasionally emit for the ``arguments`` field."""
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


def _repair_tool_call_arguments(raw: str) -> tuple[dict[str, Any], bool]:
    """Best-effort repair of a malformed tool-call ``arguments`` JSON string.

    Returns ``(args, recovered)``. ``recovered`` is ``False`` only when every
    pass failed and the caller is getting ``{}`` as a last resort — so the
    caller can record the parse failure instead of swallowing it silently.

    Conservative by design: it fixes drift local GGUF handlers actually emit —
    Gemma special-token quotes, literal control characters inside strings,
    trailing commas, a wholly single-quoted blob, Python ``None``/``null``
    literals — then hands off to Jaeger's existing tolerant parsers rather than
    guessing further.
    """
    s = (raw or "").strip()
    if not s or s.lower() in ("none", "null"):
        # An empty / null argument blob is a fully-recovered empty call.
        return {}, True

    cleaned = _degemma_quotes(s)
    # Pass 1: strict-off JSON tolerates literal tabs/newlines inside string
    # values; retry once with trailing commas stripped.
    for candidate in (cleaned, _TRAILING_COMMA.sub(r"\1", cleaned)):
        try:
            parsed = json.loads(candidate, strict=False)
        except json.JSONDecodeError:
            continue
        coerced = _coerce_args_dict(parsed)
        if coerced is not None:
            return coerced, True

    # Pass 2: a wholly single-quoted blob — common local-model drift. Swap
    # quotes only when no double quote is present, where the blind swap is
    # safe; mixed-quote input is left for the tolerant parser below.
    if "'" in cleaned and '"' not in cleaned:
        try:
            parsed = json.loads(cleaned.replace("'", '"'), strict=False)
        except json.JSONDecodeError:
            parsed = None
        coerced = _coerce_args_dict(parsed)
        if coerced is not None:
            return coerced, True

    # Pass 3: Jaeger's own tolerant parser — bare keys, nesting, Gemma quote
    # tokens, and it already falls back to _parse_loose_args for the messiest
    # input. Fed the raw string so its <|"|>-aware parser still has the tokens.
    loose = _parse_gemma_args(s)
    if loose:
        return loose, True

    return {}, False


def _normalize_tool_name(name: str, valid: frozenset[str]) -> str:
    """Map a drifted tool name onto a real one via exact alias / case /
    separator variants. No fuzzy matching — an unrecognised name is returned
    unchanged so pydantic-ai surfaces a clean 'unknown tool' error and the
    model retries, rather than us silently dispatching a guess."""
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
    # A trailing `tool` / `_tool` the model sometimes tacks onto a class-like
    # emission (e.g. ``ReadFileTool``, ``read_file_tool``).
    for base in list(candidates):
        for suffix in ("_tool", "-tool", "tool"):
            if base.endswith(suffix) and len(base) > len(suffix):
                _add(base[: -len(suffix)].rstrip("_-"))
    for candidate in candidates:
        if candidate in valid:
            return candidate
    return raw


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content") or ""
            return content if isinstance(content, str) else str(content)
    return ""


_TOOL_INTENT_HINTS: dict[str, tuple[str, ...]] = {
    "get_time": ("time", "date", "day", "today", "year", "timezone"),
    "calculate": ("calculate", "compute", "math", "sqrt", "square root", "divided", "times", "plus"),
    "system_status": ("cpu", "disk", "memory", "machine", "system status"),
    "list_skill_dir": ("list", "workspace", "files", "directory", "dir"),
    "read_file": ("read", "open file", "inside", "contents"),
    "write_file": ("write", "save", "create", "file"),
    "append_file": ("append", "add line"),
    "patch": ("patch", "edit", "fix", "modify", "replace", "rewrite"),
    "delete_file": ("delete", "remove"),
    "search_files": ("search files", "grep", "find in files"),
    "run_python": ("run", "execute", "python", "script", "verify"),
    "run_in_venv": ("venv", "package", "library", "import"),
    "terminal": ("terminal", "shell", "command", "git", "npm", "brew", "ffmpeg"),
    "install_package": ("install", "pip", "dependency", "package"),
    "web_search": ("web", "search", "recent", "latest", "current news", "look up"),
    "web_extract": ("url", "page", "extract", "docs", "read website"),
    "get_weather": ("weather", "forecast", "temperature"),
    "remember": ("remember", "my favorite", "i prefer", "i am", "i'm", "my name"),
    "recall": ("recall", "remember what", "what did i", "favorite", "prefer"),
    "forget": ("forget", "remove my", "delete my"),
    "list_facts": ("what do you know", "list facts", "everything you know"),
    "search_memory": ("search memory", "talk about", "yesterday", "past"),
    "text_to_speech": ("speak", "out loud", "narrate", "say aloud"),
    "listen": ("listen", "record", "microphone", "mic"),
    "vision_analyze": ("image", "picture", "photo", "look at"),
    "image_generate": ("generate image", "draw", "create image"),
    "schedule_prompt": ("schedule", "cron", "remind"),
    "list_schedules": ("scheduled", "schedules"),
    "cancel_schedule": ("cancel schedule", "cancel the scheduled"),
    "list_plugins": ("plugins", "integrations"),
    "setup_plugin": ("setup", "set up", "configure"),
    "list_credentials": ("credentials", "stored keys"),
    "get_credential": ("credential", "api key", "token"),
    "reload_skills": ("reload skill", "skill registry"),
    "computer_do": (
        "use the computer", "operate the computer", "do on my computer",
        "in the app", "browser", "safari", "finder", "settings",
    ),
    "computer_use": (
        "click", "double click", "right click", "drag", "scroll", "type",
        "press", "hotkey", "window", "focus window", "menu bar",
    ),
    "computer_capture": ("screenshot", "screen", "see the screen", "look at the screen", "capture"),
    "computer_look": ("look at the computer", "look at the screen", "active window", "onscreen"),
    "computer_windows": ("windows", "open apps", "running apps", "frontmost app"),
    "computer_open": ("open app", "launch app", "focus app", "switch to"),
    "computer_click": ("click", "button", "element", "control"),
}


def _auto_tool_shortlist_enabled() -> bool:
    return os.environ.get("JAEGER_AUTO_TOOL_SHORTLIST", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def _tool_schema_limit(default: int) -> int:
    raw = os.environ.get("JAEGER_TOOL_SCHEMA_LIMIT")
    if not raw:
        return default
    try:
        return max(8, int(raw))
    except ValueError:
        return default


def _tool_name(tool: dict[str, Any]) -> str:
    return ((tool.get("function") or {}).get("name") or "").strip()


def _select_tool_schemas(
    tools: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    *,
    limit: int,
    require_intent_match: bool,
) -> list[dict[str, Any]]:
    """Select a compact tool surface while preserving original order.

    `require_intent_match` keeps the proactive path conservative: if the
    request does not clearly match known tool hints, return the full schema
    set instead of hiding a tool the model may need.
    """
    if len(tools) <= limit:
        return tools
    text = _last_user_text(messages).lower()
    must_have = (
        "clarify", "help_me", "todo", "load_toolset",
        "get_time", "calculate",
        "read_file", "write_file", "append_file", "patch",
    )
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(tool: dict[str, Any]) -> None:
        if len(selected) >= limit:
            return
        name = _tool_name(tool)
        if name and name not in seen:
            seen.add(name)
            selected.append(tool)

    by_name = {_tool_name(tool): tool for tool in tools if _tool_name(tool)}
    limit = max(limit, sum(1 for name in must_have if name in by_name))
    for name in must_have:
        if name in by_name:
            add(by_name[name])

    matched_intents = 0
    for name, hints in _TOOL_INTENT_HINTS.items():
        if name in by_name and any(h in text for h in hints):
            add(by_name[name])
            matched_intents += 1

    if require_intent_match and matched_intents == 0:
        return tools

    for tool in tools:
        if len(selected) >= limit:
            break
        add(tool)
    return selected


def _shortlist_tools_for_turn(
    tools: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    *,
    limit: int = 32,
) -> list[dict[str, Any]]:
    """Proactively reduce schema noise for local models.

    This is intentionally conservative: it only shrinks the visible tool
    surface when the user prompt matches explicit intent hints. Ambiguous
    prompts still get the full tool list.
    """
    if not _auto_tool_shortlist_enabled():
        return tools
    return _select_tool_schemas(
        tools,
        messages,
        limit=_tool_schema_limit(limit),
        require_intent_match=True,
    )


def _compact_tools_for_context(
    tools: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    *,
    limit: int = 18,
) -> list[dict[str, Any]]:
    """Select a small relevant tool schema set after context overflow.

    This is a fallback for local llama.cpp models: if the full schema surface
    overflows n_ctx, a narrower schema list is far better than failing before
    the agent can make any tool call.
    """
    return _select_tool_schemas(
        tools,
        messages,
        limit=limit,
        require_intent_match=False,
    )

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage


class LlamaCppModel(Model):
    """Wrap a loaded `llama_cpp.Llama` instance as a Pydantic AI Model."""

    def __init__(self, llama: Any, model_name: str = "local-gemma-4-26b-a4b") -> None:
        self._llama = llama
        self._model_name_value = model_name
        # Gemma 4 and Qwen3 want different tool-message shapes: Gemma's
        # template reads `tool_responses`, Qwen's reads OpenAI `content`.
        self._is_gemma = "gemma" in (model_name or "").lower()
        self.last_call_times: list[float] = []
        self.last_call_ttft: list[float] = []
        # Tool-call arg blobs that survived every repair pass and still had to
        # fall back to {} — recorded per turn so a parse failure is visible to
        # diagnostics instead of silently swallowed.
        self.last_arg_repair_failures: list[dict[str, Any]] = []
        # OpenAI-format tool defs are stable per agent. Cache by id() of the
        # function_tools list pydantic-ai hands us — saves rebuilding ~20
        # dicts every request.
        self._openai_tools_cache_key: Any = None
        self._openai_tools_cache_value: list[dict[str, Any]] | None = None

    def reset_timings(self) -> None:
        self.last_call_times = []
        self.last_call_ttft = []
        self.last_arg_repair_failures = []

    # --- Model property contract ---------------------------------------------------
    @property
    def model_name(self) -> str:
        return self._model_name_value

    @property
    def system(self) -> str:
        return "local"

    # --- Main request entry point --------------------------------------------------
    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        chat_messages = self._to_chat_messages(messages)
        tools = self._to_openai_tools(model_request_parameters.function_tools)
        active_tools = _shortlist_tools_for_turn(tools, chat_messages)
        # Stash the tool schemas so _fast_finalize renders the SAME
        # <system + tools> prefix this decide call uses. Without it the
        # finalize call (system-only) evicts the tool-schema KV and the
        # next decide cold-prefills all ~60 schemas — ~12s wasted/turn.
        if active_tools:
            try:
                from jaeger_os.main import _pipeline as _pl
                _pl["openai_tools"] = active_tools
            except Exception:  # noqa: BLE001
                pass

        settings: dict[str, Any] = dict(model_settings or {})
        kwargs: dict[str, Any] = {
            "messages": chat_messages,
            "max_tokens": settings.get("max_tokens", 2048),
            "temperature": settings.get("temperature", 0.0),
            "top_p": settings.get("top_p", 0.95),
        }
        if active_tools:
            kwargs["tools"] = active_tools
            kwargs["tool_choice"] = settings.get("tool_choice", "auto")

        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        try:
            completion = await loop.run_in_executor(
                None, lambda: self._llama.create_chat_completion(**kwargs)
            )
        except ValueError as exc:
            msg = str(exc)
            if "exceed context window" not in msg and "Requested tokens" not in msg:
                raise
            compact = _compact_tools_for_context(active_tools, chat_messages)
            if not compact or len(compact) >= len(active_tools):
                raise
            kwargs["tools"] = compact
            try:
                from jaeger_os.main import _pipeline as _pl
                _pl["openai_tools"] = compact
            except Exception:  # noqa: BLE001
                pass
            completion = await loop.run_in_executor(
                None, lambda: self._llama.create_chat_completion(**kwargs)
            )
        elapsed = time.perf_counter() - started
        self.last_call_times.append(elapsed)
        # We don't have true TTFT from non-streaming completions, so treat
        # total elapsed as a proxy. Streaming would let us record true TTFT.
        self.last_call_ttft.append(elapsed)
        return self._to_model_response(
            completion,
            valid_tool_names=frozenset(filter(None, (_tool_name(t) for t in tools))),
        )

    async def request_stream(self, *args, **kwargs):  # type: ignore[override]
        # Streaming is more complex; for now, fall back to non-streaming.
        # Pydantic-AI tolerates this — `Agent.run_sync` and `agent.run` both work.
        raise NotImplementedError("Streaming not implemented for LlamaCppModel")

    # --- Conversions ---------------------------------------------------------------
    @staticmethod
    def _tool_call_args(part: Any) -> dict[str, Any]:
        """A tool-call part's args as a plain dict (pydantic-ai gives
        either a dict or a JSON string)."""
        args_val = getattr(part, "args", None)
        if isinstance(args_val, str):
            try:
                return json.loads(args_val)
            except json.JSONDecodeError:
                return {}
        return args_val or {}

    def _to_chat_messages(self, messages: list[ModelMessage]) -> list[dict[str, Any]]:
        """Convert pydantic-ai messages to llama-cpp-python chat format.

        Two paths, switched by ``JAEGER_NATIVE_TOOLS`` (see
        :func:`_native_tools_enabled`):

        • **native** (default) — emit structured ``tool_calls`` on
          assistant turns and proper ``tool`` messages, so the GGUF's OWN
          chat template renders the conversation in the model's native
          tool dialect. Gemma 4 then sees its past actions as
          ``<|tool_call>call:…`` / ``<|tool_response>…`` — exactly what
          it was trained on, instead of a foreign Hermes-XML transcript.
        • **legacy** — tool history hand-serialized as Hermes XML inside
          user/assistant content. Kept for the A/B benchmark.
        """
        if _native_tools_enabled():
            return self._to_native_messages(messages)
        return self._to_legacy_messages(messages)

    def _to_native_messages(self, messages: list[ModelMessage]) -> list[dict[str, Any]]:
        """Structured path — feed the GGUF's own template the message
        shape it expects so it renders native tool tokens itself."""
        out: list[dict[str, Any]] = []
        for msg in messages:
            kind = getattr(msg, "kind", None)
            if kind == "request":
                for part in msg.parts:
                    pk = getattr(part, "part_kind", None)
                    if pk == "system-prompt":
                        out.append({"role": "system", "content": part.content})
                    elif pk == "user-prompt":
                        content = part.content if isinstance(part.content, str) else str(part.content)
                        out.append({"role": "user", "content": content})
                    elif pk == "tool-return":
                        tool_name = getattr(part, "tool_name", "") or "tool"
                        response = part.content
                        if self._is_gemma:
                            # Gemma's template renders `tool_responses`;
                            # giving it `content` too would double-print.
                            out.append({
                                "role": "tool",
                                "tool_responses": [
                                    {"name": tool_name, "response": response},
                                ],
                            })
                        else:
                            # Qwen + OpenAI-shaped templates read `content`.
                            body = json.dumps(
                                {"name": tool_name, "content": response},
                                ensure_ascii=True, default=str,
                            )
                            out.append({
                                "role": "tool",
                                "content": body,
                                "tool_call_id": getattr(part, "tool_call_id", "") or "",
                            })
            elif kind == "response":
                texts: list[str] = []
                tool_calls: list[dict[str, Any]] = []
                for part in msg.parts:
                    pk = getattr(part, "part_kind", None)
                    if pk == "text":
                        texts.append(part.content)
                    elif pk == "tool-call":
                        tool_calls.append({
                            "id": getattr(part, "tool_call_id", "") or ("call_" + uuid.uuid4().hex[:8]),
                            "type": "function",
                            "function": {
                                "name": part.tool_name,
                                "arguments": self._tool_call_args(part),
                            },
                        })
                assistant: dict[str, Any] = {
                    "role": "assistant",
                    "content": "\n".join(t for t in texts if t),
                }
                if tool_calls:
                    assistant["tool_calls"] = tool_calls
                out.append(assistant)
        return out

    def _to_legacy_messages(self, messages: list[ModelMessage]) -> list[dict[str, Any]]:
        """Legacy path — tool history hand-serialized as Hermes XML in
        user/assistant content. Pre-native baseline; kept for the A/B."""
        out: list[dict[str, Any]] = []
        for msg in messages:
            kind = getattr(msg, "kind", None)
            if kind == "request":
                for part in msg.parts:
                    pk = getattr(part, "part_kind", None)
                    if pk == "system-prompt":
                        out.append({"role": "system", "content": part.content})
                    elif pk == "user-prompt":
                        content = part.content if isinstance(part.content, str) else str(part.content)
                        out.append({"role": "user", "content": content})
                    elif pk == "tool-return":
                        # Wrap as user-role message with Hermes-style <tool_response>
                        tool_name = getattr(part, "tool_name", "")
                        payload = {"name": tool_name, "content": part.content}
                        body = json.dumps(payload, ensure_ascii=True, default=str)
                        out.append({
                            "role": "user",
                            "content": f"<tool_response>\n{body}\n</tool_response>",
                        })
            elif kind == "response":
                texts: list[str] = []
                tool_call_strs: list[str] = []
                for part in msg.parts:
                    pk = getattr(part, "part_kind", None)
                    if pk == "text":
                        texts.append(part.content)
                    elif pk == "tool-call":
                        args_dict = self._tool_call_args(part)
                        call_json = json.dumps(
                            {"name": part.tool_name, "arguments": args_dict},
                            ensure_ascii=True,
                        )
                        tool_call_strs.append(f"<tool_call>\n{call_json}\n</tool_call>")
                content_pieces = [t for t in texts if t]
                content_pieces.extend(tool_call_strs)
                content = "\n".join(content_pieces) if content_pieces else ""
                out.append({"role": "assistant", "content": content})
        return out

    def _to_openai_tools(self, function_tools: list[Any]) -> list[dict[str, Any]]:
        # Pydantic-AI hands us the same function_tools list every request.
        # Scope it to the active toolsets (core/toolsets.py) so the model
        # routes over a small surface, not all ~60 schemas at once. Cache
        # by (list id, active toolsets) — the active set only ever grows,
        # so this rebuilds at most once per toolset widening.
        from .toolsets import active_toolset_names, model_visible
        active = frozenset(active_toolset_names())
        key = (id(function_tools) if function_tools else 0, active)
        if key == self._openai_tools_cache_key and self._openai_tools_cache_value is not None:
            return self._openai_tools_cache_value
        result: list[dict[str, Any]] = []
        for t in function_tools or []:
            if not model_visible(getattr(t, "name", "")):
                continue
            schema = getattr(t, "parameters_json_schema", None) or {"type": "object", "properties": {}}
            result.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": schema,
                },
            })
        self._openai_tools_cache_key = key
        self._openai_tools_cache_value = result
        return result

    def _to_model_response(
        self,
        completion: dict[str, Any],
        valid_tool_names: frozenset[str] | None = None,
    ) -> ModelResponse:
        choice = completion["choices"][0]
        msg = choice["message"]
        parts: list[Any] = []

        content = msg.get("content")
        raw_tool_calls = list(msg.get("tool_calls") or [])

        # If llama-cpp-python didn't parse tool calls but the content looks
        # like a drift-format tool invocation, salvage it. Also strip the
        # tool-call XML out of any remaining text so we don't double-emit.
        if content:
            drifted = _extract_drift_tool_calls(content)
            if drifted:
                raw_tool_calls.extend(drifted)
                # Remove all drift-pattern matches from content so the visible
                # text is just the model's prose (if any).
                cleaned = content
                for pattern in _DRIFT_PATTERNS:
                    cleaned = pattern.sub("", cleaned)
                cleaned = _QWEN_TOOLCALL.sub("", cleaned)
                cleaned = cleaned.strip()
                content = cleaned if cleaned else None

        if content:
            parts.append(TextPart(content=content))

        valid = valid_tool_names or frozenset()
        seen_calls: set[tuple[str, str]] = set()
        for tc in raw_tool_calls:
            fn = tc.get("function") or {}
            raw_args = fn.get("arguments")
            if isinstance(raw_args, dict):
                args: dict[str, Any] = raw_args
            elif isinstance(raw_args, str):
                try:
                    parsed: Any = json.loads(raw_args)
                except json.JSONDecodeError:
                    parsed = None
                coerced = _coerce_args_dict(parsed)
                if coerced is not None:
                    args = coerced
                else:
                    # llama-cpp-python parsed a structured call but its args
                    # are not clean JSON — repair, don't silently drop to {}.
                    args, recovered = _repair_tool_call_arguments(raw_args)
                    if not recovered:
                        self.last_arg_repair_failures.append({
                            "tool": str(fn.get("name", "")),
                            "raw": raw_args[:200],
                        })
            else:
                args = {}
            name = _normalize_tool_name(str(fn.get("name", "")), valid)
            dedup_key = (name, json.dumps(args, sort_keys=True, default=str))
            if dedup_key in seen_calls:
                continue
            seen_calls.add(dedup_key)
            parts.append(ToolCallPart(
                tool_name=name,
                args=args,
                tool_call_id=tc.get("id") or str(uuid.uuid4()),
            ))

        usage_data = completion.get("usage") or {}
        usage = RequestUsage(
            input_tokens=int(usage_data.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage_data.get("completion_tokens", 0) or 0),
        )

        return ModelResponse(
            parts=parts,
            usage=usage,
            model_name=self._model_name_value,
            timestamp=datetime.now(timezone.utc),
        )
