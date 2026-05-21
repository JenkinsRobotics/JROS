"""External-model pipeline — run the agent on a non-local brain.

Jaeger-OS is local-first: the default brain is the in-process
llama-cpp model wrapped by :class:`jaeger_os.core.llm_model.LlamaCppModel`.
This module is the opt-in alternative — when ``config.external_model``
is enabled, the agent runs on an external provider instead:

  • ``lmstudio``  — a local LM Studio server (OpenAI-compatible HTTP).
                    Still on-device, just a separate process / GUI.
  • ``openai``    — any OpenAI-compatible cloud or self-hosted endpoint.
  • ``anthropic`` — Claude via the Anthropic API.

The agent loop (``agent.iter()``, skip-final, the fix loop, Deep Think)
is model-agnostic — it only needs (a) a pydantic-ai ``Model`` for the
tool-calling loop and (b) a ``.chat()`` shim for the bounded
fast-finalize / thinking passes. :class:`ExternalModelClient` provides
both, mirroring the surface of ``LlamaCppPythonClient`` so the rest of
``main.py`` doesn't branch on backend.

Security / local-first invariants:
  • Disabled by default — a fresh instance never phones home.
  • API keys are read from the instance ``credentials/`` store (the
    sanctioned secret path), or an env var. They are never written to
    ``config.yaml`` and never logged.
  • Local model swap for Deep Think (``switch_model``) is a llama-cpp
    feature; when an external brain is active Deep Think keeps using
    that same external model (no local coder swap).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from .schemas import ExternalModelConfig


# OpenAI-compatible providers all speak the same /chat/completions wire
# format; only anthropic is its own shape. ``ollama-cloud`` is Ollama's
# hosted endpoint (https://ollama.com/v1) — same protocol as local
# ollama, but a real API key is required.
_OPENAI_COMPATIBLE = {"lmstudio", "ollama", "ollama-cloud", "openai"}

# The conventional environment variable each provider's key lives in,
# checked last by :func:`resolve_api_key`.
_CONVENTIONAL_ENV = {
    "openai": "OPENAI_API_KEY",
    "lmstudio": "OPENAI_API_KEY",
    "ollama-cloud": "OLLAMA_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


@dataclass
class ExtChatResult:
    """Completion shape the fast-finalize / thinking passes expect —
    duck-compatible with ``main._ChatResult``."""

    text: str
    latency_s: float
    ttft_s: float = 0.0


class ExternalModelError(RuntimeError):
    """Raised when an external model can't be built or reached."""


# ---------------------------------------------------------------------------
# Key resolution
# ---------------------------------------------------------------------------
def resolve_api_key(ext: ExternalModelConfig, layout: Any | None) -> str:
    """Resolve the provider API key, in priority order:

      1. the instance credential named ``ext.api_key_credential``
      2. the environment variable named ``ext.api_key_env``
      3. the provider's conventional env var (OPENAI_API_KEY /
         ANTHROPIC_API_KEY)

    Returns ``""`` when nothing is found — fine for a local LM Studio
    server, which accepts any placeholder key.
    """
    if layout is not None and ext.api_key_credential:
        try:
            from . import credentials as creds

            return creds.get_credential(layout, ext.api_key_credential)
        except Exception:  # noqa: BLE001 — missing credential is expected
            pass
    if ext.api_key_env:
        val = os.environ.get(ext.api_key_env, "")
        if val:
            return val
    conventional = _CONVENTIONAL_ENV.get(ext.provider, "")
    return os.environ.get(conventional, "") if conventional else ""


# ---------------------------------------------------------------------------
# pydantic-ai Model construction
# ---------------------------------------------------------------------------
def build_external_model(ext: ExternalModelConfig, api_key: str) -> Any:
    """Build the pydantic-ai ``Model`` for ``ext``.

    LM Studio / OpenAI-compatible endpoints map to ``OpenAIChatModel``
    with a custom-base-url provider; anthropic maps to ``AnthropicModel``.
    External models emit native structured tool calls, so none of the
    llama-cpp drift-parsing in ``LlamaCppModel`` is needed here.
    """
    if ext.provider in _OPENAI_COMPATIBLE:
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        # Local servers (LM Studio, local Ollama) need no real key but
        # reject an empty one — any non-empty placeholder works. True
        # cloud endpoints ('ollama-cloud', 'openai') genuinely require a
        # key and are never placeholdered.
        _placeholder = {"lmstudio": "lm-studio", "ollama": "ollama"}
        key = api_key or _placeholder.get(ext.provider, "")
        if not key:
            env = ext.api_key_env or _CONVENTIONAL_ENV.get(
                ext.provider, "OPENAI_API_KEY")
            raise ExternalModelError(
                f"provider {ext.provider!r} needs an API key — set the "
                f"{ext.api_key_credential!r} credential or the {env} "
                f"env var."
            )
        provider = OpenAIProvider(base_url=ext.base_url, api_key=key)
        return OpenAIChatModel(ext.model, provider=provider)

    if ext.provider == "anthropic":
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider

        if not api_key:
            raise ExternalModelError(
                "provider 'anthropic' needs an API key — set the "
                f"{ext.api_key_credential!r} credential or the "
                f"{ext.api_key_env or 'ANTHROPIC_API_KEY'} env var."
            )
        return AnthropicModel(ext.model, provider=AnthropicProvider(api_key=api_key))

    raise ExternalModelError(f"unknown provider {ext.provider!r}")


# ---------------------------------------------------------------------------
# Client — mirrors LlamaCppPythonClient's surface
# ---------------------------------------------------------------------------
def _merge_consecutive(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Collapse consecutive same-role messages into one. The
    fast-finalize path sends two user turns in a row; Anthropic is
    strict about role alternation, so merge before sending."""
    out: list[dict[str, str]] = []
    for m in messages:
        if out and out[-1]["role"] == m["role"]:
            out[-1] = {"role": m["role"], "content": out[-1]["content"] + "\n\n" + m["content"]}
        else:
            out.append({"role": m["role"], "content": m["content"]})
    return out


class ExternalModelClient:
    """External-brain client. Exposes the same surface ``main.py`` uses
    on ``LlamaCppPythonClient``:

      • ``.model``   — the pydantic-ai ``Model`` for the agent loop
      • ``.chat()``  — bounded completion for fast-finalize / thinking
      • ``.kind``    — ``"external"`` (vs ``"local"``)
      • ``.describe()`` — one-line human summary for the status panel
    """

    kind = "external"
    llm = None  # no in-process Llama — kept so `client.llm` access is safe

    def __init__(self, ext: ExternalModelConfig, layout: Any | None = None) -> None:
        self.ext = ext
        self._api_key = resolve_api_key(ext, layout)
        self.model = build_external_model(ext, self._api_key)
        self.model_name = ext.model
        self.provider = ext.provider

    # -- bounded completion shim -------------------------------------------
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
        top_p: float = 0.95,
        stream: bool = False,
        grammar: str | None = None,
    ) -> ExtChatResult:
        """One-shot chat completion. ``stream`` / ``grammar`` are ignored
        (parity with ``LlamaCppPythonClient.chat``)."""
        started = time.perf_counter()
        if self.provider in _OPENAI_COMPATIBLE:
            text = self._chat_openai(messages, max_tokens, temperature, top_p)
        else:
            text = self._chat_anthropic(messages, max_tokens, temperature, top_p)
        return ExtChatResult(text=text.strip(), latency_s=time.perf_counter() - started)

    def _chat_openai(self, messages, max_tokens, temperature, top_p) -> str:
        from openai import OpenAI

        key = self._api_key or ("lm-studio" if self.provider == "lmstudio" else "")
        client = OpenAI(
            base_url=self.ext.base_url, api_key=key, timeout=self.ext.timeout_s,
        )
        completion = client.chat.completions.create(
            model=self.ext.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
        )
        return completion.choices[0].message.content or ""

    def _chat_anthropic(self, messages, max_tokens, temperature, top_p) -> str:
        from anthropic import Anthropic

        client = Anthropic(api_key=self._api_key, timeout=self.ext.timeout_s)
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        convo = _merge_consecutive(
            [m for m in messages if m["role"] in ("user", "assistant")]
        )
        resp = client.messages.create(
            model=self.ext.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system or None,
            messages=convo or [{"role": "user", "content": "(no input)"}],
        )
        return "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        )

    # -- diagnostics -------------------------------------------------------
    def describe(self) -> str:
        where = self.ext.base_url if self.provider in _OPENAI_COMPATIBLE else "api.anthropic.com"
        return f"external · {self.provider} · {self.ext.model} · {where}"

    def connectivity_check(self) -> dict[str, Any]:
        """Tiny live request to confirm the endpoint answers. Returns
        ``{ok, detail, latency_s}``. Used by boot + the /model command so
        a misconfigured endpoint fails loud instead of mid-conversation."""
        try:
            result = self.chat(
                [{"role": "user", "content": "reply with the single word: ok"}],
                max_tokens=8,
                temperature=0.0,
            )
            return {
                "ok": bool(result.text),
                "detail": result.text[:80] or "(empty reply)",
                "latency_s": round(result.latency_s, 2),
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": f"{type(exc).__name__}: {exc}", "latency_s": 0.0}
