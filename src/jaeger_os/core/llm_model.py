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
    # <|tool_call|>{"name": "x", "arguments": {...}}<|/tool_call|>
    re.compile(r"<\|tool_call\|>\s*(\{.*?\})\s*<\|/tool_call\|>", re.DOTALL),
    # <tool_call>{"name": "x", "arguments": {...}}</tool_call>  (standard Hermes)
    re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL),
]


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
                # JSON form: {"name": "x", "arguments": {...}}. Gemma
                # sometimes wraps string values in its own quote tokens
                # (<|"|> … <|"|>) instead of real JSON quotes, which makes
                # json.loads fail and silently drops the whole tool call —
                # normalize them to " before parsing.
                raw = _degemma_quotes(groups[0])
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                name = payload.get("name", "")
                args = payload.get("arguments", {}) or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(_degemma_quotes(args))
                    except json.JSONDecodeError:
                        args = {}
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
        # OpenAI-format tool defs are stable per agent. Cache by id() of the
        # function_tools list pydantic-ai hands us — saves rebuilding ~20
        # dicts every request.
        self._openai_tools_cache_key: Any = None
        self._openai_tools_cache_value: list[dict[str, Any]] | None = None

    def reset_timings(self) -> None:
        self.last_call_times = []
        self.last_call_ttft = []

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
        # Stash the tool schemas so _fast_finalize renders the SAME
        # <system + tools> prefix this decide call uses. Without it the
        # finalize call (system-only) evicts the tool-schema KV and the
        # next decide cold-prefills all ~60 schemas — ~12s wasted/turn.
        if tools:
            try:
                from jaeger_os.main import _pipeline as _pl
                _pl["openai_tools"] = tools
            except Exception:  # noqa: BLE001
                pass

        settings: dict[str, Any] = dict(model_settings or {})
        kwargs: dict[str, Any] = {
            "messages": chat_messages,
            "max_tokens": settings.get("max_tokens", 2048),
            "temperature": settings.get("temperature", 0.0),
            "top_p": settings.get("top_p", 0.95),
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = settings.get("tool_choice", "auto")

        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        completion = await loop.run_in_executor(
            None, lambda: self._llama.create_chat_completion(**kwargs)
        )
        elapsed = time.perf_counter() - started
        self.last_call_times.append(elapsed)
        # We don't have true TTFT from non-streaming completions, so treat
        # total elapsed as a proxy. Streaming would let us record true TTFT.
        self.last_call_ttft.append(elapsed)
        return self._to_model_response(completion)

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
        from .toolsets import active_toolset_names, tool_visible
        active = frozenset(active_toolset_names())
        key = (id(function_tools) if function_tools else 0, active)
        if key == self._openai_tools_cache_key and self._openai_tools_cache_value is not None:
            return self._openai_tools_cache_value
        result: list[dict[str, Any]] = []
        for t in function_tools or []:
            if not tool_visible(getattr(t, "name", "")):
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

    def _to_model_response(self, completion: dict[str, Any]) -> ModelResponse:
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
                cleaned = cleaned.strip()
                content = cleaned if cleaned else None

        if content:
            parts.append(TextPart(content=content))

        for tc in raw_tool_calls:
            fn = tc.get("function") or {}
            raw_args = fn.get("arguments")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except json.JSONDecodeError:
                args = {}
            parts.append(ToolCallPart(
                tool_name=fn.get("name", ""),
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
