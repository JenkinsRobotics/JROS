"""Apple MLX inference backend for pydantic-ai.

Mirrors :class:`~jaeger_os.core.llm_model.LlamaCppModel` but routes
generation through ``mlx_lm`` instead of ``llama_cpp``. The two engines
emit the same drift-format tool calls the local Gemma / Qwen weights
produce, so the inheritance reuses *every* downstream piece — drift
extraction, the arg-repair chain, tool-name normalisation, dedup, the
native-vs-Hermes-XML message rendering, the failure-record diagnostic
field. The only thing this class overrides is the actual generation
step.

mlx-lm is an optional dependency. Imported lazily inside the methods
that need it so non-Apple-Silicon installs (or installs without
``mlx-lm`` in the venv) load this module cleanly.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.settings import ModelSettings

from .llm_model import LlamaCppModel, _shortlist_tools_for_turn, _tool_name


class MlxModel(LlamaCppModel):
    """An MLX-backed pydantic-ai Model.

    Same drift-handling and tool-call plumbing as the llama-cpp path — only
    the generation primitive changes. ``mlx_model`` is the loaded model
    object from :func:`mlx_lm.load`; ``tokenizer`` is its companion (also
    returned by ``mlx_lm.load``).
    """

    def __init__(
        self, mlx_model: Any, tokenizer: Any,
        model_name: str = "local-mlx",
    ) -> None:
        # Deliberately skip ``LlamaCppModel.__init__`` — it expects a
        # llama-cpp instance and treats ``_llama`` as load-bearing. Every
        # other method on the parent class only reads conversion state
        # (``_model_name_value``, ``_is_gemma``, the schema cache) and the
        # module-level helpers, all of which we set up identically here.
        self._llama: Any = None
        self._model_name_value = model_name
        self._is_gemma = "gemma" in (model_name or "").lower()
        self.last_call_times: list[float] = []
        self.last_call_ttft: list[float] = []
        self.last_arg_repair_failures: list[dict[str, Any]] = []
        self._openai_tools_cache_key: Any = None
        self._openai_tools_cache_value: list[dict[str, Any]] | None = None
        self._mlx_model = mlx_model
        self._tokenizer = tokenizer

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        try:
            from mlx_lm import generate  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "MLX backend invoked but mlx-lm is not installed — "
                "run `pip install mlx-lm` on Apple Silicon."
            ) from exc

        chat_messages = self._to_chat_messages(messages)
        tools = self._to_openai_tools(model_request_parameters.function_tools)
        active_tools = _shortlist_tools_for_turn(tools, chat_messages)

        # Render to a prompt string via the tokenizer's chat template. Some
        # tokenizers don't accept a ``tools=`` kwarg — fall back to the
        # plain template rather than crashing the turn.
        try:
            prompt = self._tokenizer.apply_chat_template(
                chat_messages,
                tools=active_tools or None,
                add_generation_prompt=True,
                tokenize=False,
            )
        except (TypeError, NotImplementedError):
            prompt = self._tokenizer.apply_chat_template(
                chat_messages, add_generation_prompt=True, tokenize=False,
            )

        settings = dict(model_settings or {})
        max_tokens = int(settings.get("max_tokens", 2048))
        # mlx-lm's ``generate`` API has fluctuated across releases — some
        # versions take ``temp``, others want a sampler. Pass only what we
        # know is stable and let the library default the rest.
        kwargs: dict[str, Any] = {
            "prompt": prompt,
            "max_tokens": max_tokens,
            "verbose": False,
        }
        temperature = float(settings.get("temperature", 0.0))
        if temperature > 0:
            kwargs["temp"] = temperature

        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        text = await loop.run_in_executor(
            None,
            lambda: generate(self._mlx_model, self._tokenizer, **kwargs),
        )
        elapsed = time.perf_counter() - started
        self.last_call_times.append(elapsed)
        self.last_call_ttft.append(elapsed)

        # Synthesise an OpenAI-shaped chat completion so the parent's
        # ``_to_model_response`` does the drift-extraction / arg-repair /
        # name-normalisation / dedup work — exactly as for the llama-cpp
        # path. ``tool_calls=None`` forces the drift path (mlx-lm has no
        # structured tool_calls field; tool calls arrive embedded in text).
        completion = {
            "choices": [{"message": {"content": text, "tool_calls": None}}],
            "usage": {},
        }
        return self._to_model_response(
            completion,
            valid_tool_names=frozenset(
                filter(None, (_tool_name(t) for t in tools)),
            ),
        )
