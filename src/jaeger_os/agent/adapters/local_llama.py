"""``LocalLlamaAdapter`` — in-process llama-cpp-python.

llama-cpp's ``create_chat_completion`` exposes an OpenAI-compatible
response shape, so 95% of :class:`OpenAIAdapter` applies unchanged.
The remaining 5%:

  • the "client" is a ``llama_cpp.Llama`` instance, not an
    ``openai.OpenAI`` — we wrap it in a thin facade that exposes
    ``.chat.completions.create(**kw)`` so the parent class's call path
    works verbatim.
  • Gemma 4 / Qwen3-Coder routinely emit tool calls as TEXT inside
    ``<tool_call>…</tool_call>`` blocks even when ``tools=[...]`` is
    passed structurally — :mod:`jaeger_os.agent.dialects` salvages
    those after the parent's parse step.

Construction stays light: nothing loads at import time. A real
``Llama`` instance is built on first call (or injected by the caller
when sharing one across adapters / instances).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from jaeger_os.agent.dialects import (
    detect_family,
    detect_reasoning,
    extract_tool_calls,
    render_tools_for,
    strip_think_blocks,
    textify_tool_history,
)
from jaeger_os.agent.schemas.message_types import Message
from jaeger_os.agent.schemas.tool_schema import ToolDef
from .openai import OpenAIAdapter


# Stall-watchdog floor for reasoning models. They legitimately spend
# minutes deliberating in ``<think>`` blocks; the default 120s floor
# fires mid-thought, abandons the llama worker, and the next call hits
# a corrupted KV cache → process crash (the 2026-05-28 ``0/1`` aborts).
# A reasoning model gets at least this long before the watchdog trips.
_REASONING_STALL_FLOOR_S = 300.0


# Sensible llama-cpp defaults for Apple Silicon. Match the existing
# ``core/llm_client.py:LlamaCppPythonClient`` so a head-to-head with the
# legacy path measures the agent loop, not the backend.
_LLAMA_DEFAULTS: dict[str, Any] = {
    "n_ctx": 8192,
    "n_gpu_layers": -1,
    "n_batch": 512,
    "n_ubatch": 512,
    "flash_attn": True,
    "swa_full": False,
    "verbose": False,
}


class _LlamaChatFacade:
    """Adapts a ``llama_cpp.Llama`` to the ``.chat.completions.create``
    shape :class:`OpenAIAdapter._ensure_client` expects.

    Two nested attributes, one bound method — enough surface for the
    parent adapter's call site without dragging in the rest of the
    OpenAI client API. ``models.list`` is stubbed for health checks.
    """

    def __init__(self, llama: Any) -> None:
        self._llama = llama
        self.chat = self
        self.completions = self
        # ``models.list`` is what :meth:`OpenAIAdapter.health_check`
        # calls — an in-process model is always reachable once loaded,
        # so return an empty list rather than an exception.
        self.models = _LlamaModelsStub()

    def create(self, **kwargs: Any) -> Any:
        """Pass through to ``create_chat_completion``, stripping kwargs
        llama-cpp doesn't understand. The response is already in OpenAI
        shape so :meth:`OpenAIAdapter.parse_response` decodes it
        unchanged.

        Critical fix: llama-cpp's Jinja chat template (Qwen3.5, Gemma,
        Hermes, …) iterates ``tool_call.arguments|items`` — it expects
        ``arguments`` as a **dict**. But the OpenAI wire format encodes
        it as a JSON string, so the parent adapter's ``format_messages``
        JSON-dumps. We re-decode in-place here so the in-process chat
        template sees the dict it needs. Without this, the second turn
        of any multi-iteration conversation crashes with
        ``TypeError: Can only get item pairs from a mapping`` from
        Jinja's ``do_items`` filter.
        """
        kwargs.pop("stream", None) or kwargs.setdefault("stream", False)
        # llama-cpp accepts the same field names — only the auth-y bits
        # ride OpenAI's HTTP envelope and have no in-process equivalent.
        for hostonly in ("api_key", "base_url", "extra_headers", "timeout"):
            kwargs.pop(hostonly, None)
        msgs = kwargs.get("messages")
        if isinstance(msgs, list):
            kwargs["messages"] = [
                _coerce_none_content(_decode_tool_call_args(m)) for m in msgs
            ]
        # Phase-8 hardening: sanitise tool schemas before handing them
        # to llama-cpp's grammar generator. The generator rejects
        # bare-string schema values, ``type: [X, "null"]`` arrays, and
        # ``anyOf`` nullable unions with HTTP 400 / parse failures.
        # Sanitisation is idempotent so calling it twice is safe.
        tools = kwargs.get("tools")
        if isinstance(tools, list):
            from jaeger_os.agent.parsing import schema_sanitizer
            kwargs["tools"] = schema_sanitizer.sanitize_tool_schemas(tools)
        return self._llama.create_chat_completion(**kwargs)


class _LlamaModelsStub:
    @staticmethod
    def list() -> Any:
        from types import SimpleNamespace
        return SimpleNamespace(data=[])


def _coerce_none_content(msg: Any) -> Any:
    """Return ``msg`` with ``content=None`` rewritten to ``""``.

    A pure tool-call assistant turn carries ``content=None`` in the
    OpenAI wire shape — fine for OpenAI's API, but many GGUF chat
    templates render content with an unguarded ``'</think>' in content``
    or ``content + …`` and crash on ``None`` (verified: DeepSeek-R1's
    embedded template, 2026-05-28). We're the in-process path that runs
    the template directly, so we feed it a clean empty string instead.
    Matching the model means adapting to its template, not the reverse.
    """
    if isinstance(msg, dict) and msg.get("content") is None:
        return {**msg, "content": ""}
    return msg


def _decode_tool_call_args(msg: Any) -> Any:
    """Return ``msg`` with any assistant ``tool_calls[*].function.arguments``
    JSON-string decoded back to a dict.

    The OpenAI wire format encodes ``arguments`` as a JSON-encoded
    string; llama-cpp's bundled Jinja chat templates (Qwen3.5, Gemma,
    Hermes, …) instead expect a dict so they can iterate ``|items``.
    Walking once per message is O(messages × tool_calls) which is
    negligible vs the actual generation cost.

    Non-string ``arguments`` (already-dict, ``None``, malformed)
    pass through unchanged so the template's own ``|tojson`` fallback
    handles them.
    """
    if not isinstance(msg, dict):
        return msg
    if msg.get("role") != "assistant":
        return msg
    tool_calls = msg.get("tool_calls")
    if not tool_calls:
        return msg
    import json as _json
    new_tool_calls: list[Any] = []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            new_tool_calls.append(tc)
            continue
        fn = tc.get("function")
        if not isinstance(fn, dict):
            new_tool_calls.append(tc)
            continue
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                decoded = _json.loads(args) if args else {}
            except (TypeError, ValueError):
                decoded = {}
            new_tool_calls.append({
                **tc,
                "function": {**fn, "arguments": decoded},
            })
        else:
            new_tool_calls.append(tc)
    return {**msg, "tool_calls": new_tool_calls}


class LocalLlamaAdapter(OpenAIAdapter):
    """In-process llama-cpp-python. Same wire shape as OpenAI; drift
    parser layered on top of :meth:`parse_response` because local
    chat templates routinely emit tool calls as text.

    Construction options:

      * ``model_path`` — path to the GGUF file. Required unless
        ``llama`` is injected.
      * ``llama`` — pre-loaded ``llama_cpp.Llama`` instance. Skip the
        path-based load entirely; useful when one model serves multiple
        agents or unit tests inject a stub.
      * ``llama_kwargs`` — overrides for the ``Llama`` constructor
        (``n_ctx``, ``n_gpu_layers``, …). Defaults match the legacy
        :class:`jaeger_os.core.models.llm_client.LlamaCppPythonClient` so
        benchmarks compare apples to apples.
      * Everything else (``model``, ``max_tokens``, ``temperature``)
        flows to :class:`OpenAIAdapter` unchanged.
    """

    def __init__(
        self,
        *,
        model: str = "local",
        model_path: str | Path | None = None,
        llama: Any = None,
        llama_kwargs: dict[str, Any] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        top_p: float = 0.95,
    ) -> None:
        # Skip OpenAIAdapter's network kwargs entirely — we never talk
        # to an HTTP endpoint. Pass the bits that DO apply via super().
        super().__init__(
            provider="local-llama",
            model=model,
            api_key=None,
            base_url=None,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            client=None,
        )
        self.model_path = Path(model_path).expanduser() if model_path else None
        self.llama_kwargs = {**_LLAMA_DEFAULTS, **(llama_kwargs or {})}
        # Either an already-built Llama, or built on first use.
        self._llama = llama
        # Override the diagnostic name so /runtime shows the right label.
        self.name = "local-llama"
        # Whether to embed the tool catalogue in the system prompt using
        # the MODEL'S NATIVE dialect (on top of the structured ``tools=``
        # param). Default ON. See ``format_messages``.
        self.inject_tools_prose = True
        # Cached tool dialect ("chatml" / "mistral" / "llama3" / …),
        # resolved lazily on first ``format_messages``.
        self._tool_family: str | None = None
        # Cached reasoning flag (model emits <think> deliberation).
        self._is_reasoning: bool | None = None

    # ── tool presentation ───────────────────────────────────────────

    def _resolve_tool_family(self) -> str:
        """Determine the model's native tool dialect from its name +
        embedded chat template. Cached after the first call.

        Principle: we match the model. Each family was trained on a
        specific tool dialect; we present tools in THAT dialect so the
        model never has to drift to a foreign format.
        """
        if self._tool_family is not None:
            return self._tool_family
        name = ""
        if self.model_path is not None:
            name = Path(self.model_path).stem
        template = ""
        # The embedded chat template lives in the Llama metadata once
        # the client is built. Read it if available; fall back to the
        # name alone otherwise (the name is usually enough).
        llama = self._llama
        meta = getattr(llama, "metadata", None) if llama is not None else None
        if isinstance(meta, dict):
            template = meta.get("tokenizer.chat_template", "") or ""
            if not name:
                name = meta.get("general.name", "") or ""
        self._tool_family = detect_family(name, template)
        self._is_reasoning = detect_reasoning(name, template)
        return self._tool_family

    def _resolve_reasoning(self) -> bool:
        """Whether this model emits ``<think>`` deliberation. Resolved
        alongside the tool family (same name+template signals)."""
        if self._is_reasoning is None:
            self._resolve_tool_family()  # populates both
        return bool(self._is_reasoning)

    def format_messages(
        self,
        messages: list[Message],
        tools: list[ToolDef],
        system: str,
    ) -> dict[str, Any]:
        """Build the chat-completion kwargs, presenting tools through
        BOTH channels:

          1. The structured ``tools=`` param (parent OpenAIAdapter) —
             llama-cpp applies the model's chat template when its handler
             supports function-calling. This works for models whose GGUF
             template renders tools (Gemma-4, some Qwen).

          2. A NATIVE-DIALECT tool block embedded in the system prompt
             (this override, via :mod:`jaeger_os.agent.dialects`). Many GGUF
             builds ship templates with the tool section stripped (the
             LM Studio Hermes-3 build, verified), so the structured
             param silently no-ops and the model never sees the tools →
             it answers as a plain chatbot (the 3.9% flatlines in the
             2026-05-27 sweep).

        Crucially, the prose block is rendered in the MODEL'S OWN
        dialect — Hermes/Qwen get ``<tools>`` + ``<tool_call>``, Mistral
        gets ``[AVAILABLE_TOOLS]`` + ``[TOOL_CALLS]``, Llama gets the
        ``<|python_tag|>`` convention. We match the model; it never
        drifts to a format foreign to it. The drift parser reads back
        whatever native format it emits.

        Gemma + unknown families inject nothing here (their structured
        path works / we don't want to perturb a working model).
        """
        kwargs = super().format_messages(messages, tools, system)
        if not (self.inject_tools_prose and tools):
            return kwargs
        family = self._resolve_tool_family()
        addition = render_tools_for(family, tools)
        if not addition:
            return kwargs  # gemma/unknown → structured channel only
        wire = kwargs.get("messages") or []
        for entry in wire:
            if entry.get("role") == "system":
                existing = entry.get("content") or ""
                entry["content"] = (
                    f"{existing}\n\n{addition}" if existing else addition
                )
                break
        else:
            wire.insert(0, {"role": "system", "content": addition})
        # Prose families are driven entirely as TEXT: rewrite tool-call
        # history into native in-dialect text turns and drop the
        # structured ``tools=`` param. Otherwise the conversation history
        # (assistant ``tool_calls`` + ``tool`` results) routes back
        # through the model's own GGUF tool template — which is fragile
        # and mutually incompatible across builds (DeepSeek-R1 crashes on
        # dict args / None content; Hermes builds strip the tool section).
        # We presented the catalogue as prose, so the structured channel
        # is redundant here. Gemma already returned above (its handler
        # works), so reaching this point means a text-driven family.
        kwargs["messages"] = textify_tool_history(wire, family)
        kwargs.pop("tools", None)
        kwargs.pop("tool_choice", None)
        return kwargs

    # ── client lifecycle ────────────────────────────────────────────

    def _ensure_client(self) -> Any:
        """Build (or reuse) the ``Llama`` instance, wrap it in the
        chat-completions facade, and cache for subsequent calls.

        Heavy: the first call loads the GGUF off disk and warms the
        graph. Make sure the agent loop calls this once per adapter
        lifetime, not once per turn — that's why ``self._client``
        caches the facade.
        """
        if self._client is not None:
            return self._client
        if self._llama is None:
            if self.model_path is None:
                raise ValueError(
                    "LocalLlamaAdapter needs either ``model_path`` or a "
                    "pre-loaded ``llama`` instance."
                )
            from llama_cpp import Llama
            if not self.model_path.exists():
                raise FileNotFoundError(f"GGUF not found: {self.model_path}")
            self._llama = Llama(
                model_path=str(self.model_path),
                **self.llama_kwargs,
            )
        self._client = _LlamaChatFacade(self._llama)
        return self._client

    # ── in-process call (override the inherited HTTP version) ───────

    def call(
        self,
        formatted: Any,
        interrupt_event: Any,
        *,
        stale_timeout: float | None = None,
        on_heartbeat: Any = None,
        **kwargs: Any,
    ) -> Any:
        """In-process call with a **caller-controlled stall watchdog**.

        Earlier this method force-set ``stale_timeout=None`` and
        substituted an uncancellable interrupt event, because abandoning
        the llama-cpp call from a worker thread leaves a half-decoded
        KV cache that produces ``llama_decode -3`` on the next call.
        That was correct for the next-call safety angle but it had a
        nasty side-effect: a Metal prefill stall (which we hit on short
        + ambiguous prompts) hung the loop forever, with no way for the
        user to recover except SIGKILL from another terminal.

        New posture:

          * The interrupt event is STILL ignored for the in-process
            path. Ctrl-C from the TUI cannot safely tear down a
            llama-cpp call mid-decode, so we let the model finish (or
            the watchdog below catch the hang) and the agent loop
            discards the result at the boundary.

          * The stale-timeout HOWEVER is now passed through. When
            ``interruptible_call`` raises ``StaleCallTimeout``, the
            worker thread keeps running in the background (still
            unsafe to kill), but the agent loop gets control back and
            can surface a clean message to the user — "the model
            stalled; use ``jaeger kill`` to recover". A leaked thread
            is the lesser evil compared with a hung TUI.

          * The abandoned thread is documented as a known caveat. The
            next in-process call MAY see KV corruption and need a
            fresh ``Llama`` instance (the agent loop's adapter chain
            handles this by re-creating the client on certain
            error-types — see ``_ensure_client``). For one-shot mode
            (most common case in dev) the process exits anyway.
        """
        # Reasoning models legitimately deliberate for minutes; raise
        # the watchdog floor so it doesn't fire mid-think (which would
        # abandon the worker + corrupt the KV cache for the next call).
        if (
            stale_timeout is not None
            and self._resolve_reasoning()
            and stale_timeout < _REASONING_STALL_FLOOR_S
        ):
            stale_timeout = _REASONING_STALL_FLOOR_S
        uncancellable_event = threading.Event()
        return super().call(
            formatted,
            uncancellable_event,
            stale_timeout=stale_timeout,    # PASS THROUGH — the watchdog
            on_heartbeat=on_heartbeat,
            **kwargs,
        )

    # ── parse with drift fallback ───────────────────────────────────

    def parse_response(self, raw: Any) -> Message:
        """Decode the chat-completions response, then merge any
        text-format tool calls salvaged by the drift parser.

        Why both: llama-cpp's chat handler may parse some calls into the
        structured ``tool_calls`` field while leaving others as raw text
        (template quirks vary per model — Gemma 4 in particular). The
        union is what the model actually intended; the agent loop
        dispatches both equally.
        """
        message = super().parse_response(raw)
        text = message.get("content") or ""
        # Reasoning models emit ``<think>…</think>`` deliberation BEFORE
        # the answer / tool call. Strip it first so (a) the drift parser
        # doesn't try to read tool calls out of the reasoning, and (b)
        # the visible answer isn't a wall of internal monologue. The
        # actual tool call (if any) comes after ``</think>``.
        if "<think>" in text:
            stripped = strip_think_blocks(text)
            message["content"] = stripped or None
            text = stripped
        # Cheap pre-filter: skip the drift parser only when the text
        # can't possibly hold a tool call. Two shapes qualify:
        #   * angle-bracket envelopes — ``<tool_call>``, ``<|python_tag|>``
        #   * bare top-level JSON — ``{"name": …, "arguments": …}`` with
        #     NO wrapping (DeepSeek-R1, Qwen, Llama emit this natively).
        # The original guard only checked for ``<`` and so silently
        # dropped every bare-JSON tool call — the model did the right
        # thing in its native format but JROS treated the JSON as a
        # plain-text answer (the 2026-05-28 DeepSeek-R1 0% flatline).
        _has_envelope = "<" in text
        _has_bare_json = "{" in text and (
            '"name"' in text or '"tool_name"' in text
        )
        if not (_has_envelope or _has_bare_json):
            return message
        salvaged = extract_tool_calls(text)
        if not salvaged:
            return message
        # Strip the envelopes from the visible text so the loop doesn't
        # echo the markup back to the user on the final answer.
        cleaned = self._strip_tool_call_blocks(text).strip()
        # Bare-JSON tool calls (no envelope) aren't removed by the
        # envelope stripper — so when the cleaned remainder is itself
        # just a tool-call JSON object, null it. Otherwise the model's
        # raw ``{"name": …}`` would surface as the visible "answer".
        if cleaned.startswith("{") and (
            '"name"' in cleaned or '"tool_name"' in cleaned
        ):
            cleaned = ""
        message["content"] = cleaned or None
        existing = list(message.get("tool_calls") or [])
        existing.extend(salvaged)
        message["tool_calls"] = existing
        return message

    @staticmethod
    def _strip_tool_call_blocks(text: str) -> str:
        """Remove every ``<tool_call>`` / ``<|tool_call|>`` envelope
        from the response text. Mirrors :class:`HermesXMLAdapter`'s
        helper — kept here so the local-llama and Hermes-XML paths
        agree on the visible-text contract."""
        import re
        patterns = [
            r"<\|tool_call\|>\s*.*?\s*<\|/tool_call\|>",
            r"<\|tool_call>\s*call:[^<]*<tool_call\|>",
            r"<tool_call>\s*.*?\s*</tool_call>",
        ]
        out = text
        for p in patterns:
            out = re.sub(p, "", out, flags=re.DOTALL)
        return out

    # ── capabilities + diagnostics ──────────────────────────────────

    def supports(self, feature: str) -> bool:
        # llama-cpp's chat handlers vary per-model on parallel tool
        # calling; the drift parser handles the multi-call case from
        # text either way. Report only what the wire format guarantees.
        if feature == "streaming":
            return self.streaming
        return False

    def health_check(self) -> dict[str, Any]:
        """In-process — if the ``Llama`` is loaded, we're reachable."""
        try:
            self._ensure_client()
            return {"ok": True, "detail": "model loaded", "latency_s": 0.0}
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "detail": f"{type(exc).__name__}: {exc}"[:200],
                "latency_s": 0.0,
            }

    def describe(self) -> str:
        path = self.model_path.name if self.model_path else self.model
        return f"local-llama · {path}"


__all__ = ["LocalLlamaAdapter"]
