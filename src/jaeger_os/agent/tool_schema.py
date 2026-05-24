"""``ToolDef`` — single source of truth for one tool's contract.

A tool is defined once. The same ``ToolDef`` renders itself three ways
(Anthropic ``input_schema``, OpenAI ``function`` block, Hermes XML
``<tools>`` JSON entry) so we never split the schema and have it drift.
Validation of the model's argument blob happens at dispatch via
``args_model.model_validate`` — that is the single Pydantic trust
boundary per call. Everything else inside the loop is plain dicts.

Flags worth knowing:
  • ``interactive=True``  — must NOT run in parallel with siblings
    (e.g. ``ask_user``, anything that takes the terminal). The agent
    loop forces sequential dispatch when any sibling is interactive.
  • ``dangerous=True``    — physically affects the world. Robots care.
    Reserved for tools like ``move_joint``, ``drive_velocity``,
    ``send_message`` — anything the operator might want confirmed,
    audited, or scoped behind a permission tier on hardware.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel


@dataclass
class ToolDef:
    """One callable tool, plus everything needed to expose it to a
    model and dispatch it safely.

    ``args_model`` is a Pydantic class whose JSON schema describes the
    arguments the model is allowed to pass. ``fn`` is the actual
    handler — it receives keyword args matching the model's fields
    after Pydantic validation. Three renderers convert the same schema
    into the three on-wire formats the adapters use.
    """

    name: str
    description: str
    args_model: type[BaseModel]
    fn: Callable[..., Any]
    interactive: bool = False
    dangerous: bool = False

    # ── on-wire renderers ────────────────────────────────────────────

    def to_anthropic_schema(self) -> dict[str, Any]:
        """The shape Anthropic's Messages API takes in its ``tools``
        list: ``{name, description, input_schema}``."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.args_model.model_json_schema(),
        }

    def to_openai_schema(self) -> dict[str, Any]:
        """The shape OpenAI Chat Completions takes in its ``tools`` list:
        ``{type: 'function', function: {name, description, parameters}}``.
        Covers every OpenAI-compatible endpoint (the real OpenAI,
        OpenRouter, llama.cpp server, LM Studio, Ollama OpenAI-mode,
        Gemini's compat surface, vLLM)."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }

    def to_hermes_xml_block(self) -> str:
        """One JSON entry to include inside the ``<tools>...</tools>``
        block in a Hermes-format system prompt. Returns a single line
        of JSON — the adapter is responsible for the surrounding XML."""
        return json.dumps(
            {
                "type": "function",
                "function": {
                    "name": self.name,
                    "description": self.description,
                    "parameters": self.args_model.model_json_schema(),
                },
            },
            ensure_ascii=True,
        )

    # ── dispatch ─────────────────────────────────────────────────────

    def dispatch(self, raw_args: dict[str, Any]) -> Any:
        """Validate ``raw_args`` against ``args_model``, then call
        ``fn``. Pydantic's ``ValidationError`` propagates so the agent
        loop can return it AS a tool result and let the model self-
        correct rather than crashing the turn.

        Phase-8 hardening: pre-coerce open-weight-model drift (string
        scalars where the schema expects numbers / booleans, bare
        scalars where it expects arrays, JSON-encoded strings) before
        validation fires. Pydantic v2 covers the simple string→number
        case but not the array-wrap or JSON-decode cases, both of
        which Gemma / Qwen / GLM hit routinely.
        """
        from .arg_coercion import coerce_args
        coerced = coerce_args(raw_args, self.args_model.model_json_schema())
        validated = self.args_model.model_validate(coerced)
        return self.fn(**validated.model_dump())


__all__ = ["ToolDef"]
