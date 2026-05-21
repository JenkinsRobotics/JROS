"""Pydantic v2 schemas for the on-disk files an instance owns.

Three files live at the root of every instance directory and are validated
against these models on every read. Hand-edits to the YAML are welcome —
the schemas exist so a typo doesn't silently corrupt runtime state.

  identity.yaml   → Identity   (name, role, personality, voice tone)
  config.yaml     → Config     (model endpoint, runtime knobs)
  manifest.json   → Manifest   (core_version pin, instance_name, created_at)

The setup wizard writes all three; the agent loop reads them; the agent
itself is forbidden from editing identity/config/manifest by the
sandboxed file tools.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# Bumped whenever the on-disk shape of identity.yaml / config.yaml changes
# in a way that needs a migration. Stored in manifest.json on instance
# creation; mismatch with the installed core triggers refuse-to-start at
# runtime (full migration system is M2 work).
CORE_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# identity.yaml
# ---------------------------------------------------------------------------
class Identity(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=64, description="Agent's display name")
    role: str = Field(..., min_length=1, max_length=256, description="One-line role description")
    personality: str = Field(..., min_length=1, max_length=2048)
    voice_tone: str = Field("neutral", max_length=64)
    # Kokoro voice identifier (e.g. ``am_michael`` for a male voice,
    # ``af_heart`` for a female voice). ``None`` falls back to the
    # plugin-level default. Picked per-instance so Jarvis and Lilith
    # don't share the same voice.
    voice_id: str | None = Field(None, max_length=64,
                                 description="Kokoro voice id (am_*, af_*)")

    @field_validator("name")
    @classmethod
    def _no_path_chars(cls, v: str) -> str:
        if any(c in v for c in "/\\:*?\"<>|"):
            raise ValueError("name must not contain path-illegal characters")
        return v


# ---------------------------------------------------------------------------
# config.yaml
# ---------------------------------------------------------------------------
class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # In-process llama-cpp-python is the only adapter Jaeger M1 supports.
    # M2 may add OpenAI-compatible HTTP endpoints; the discriminator stays here
    # so we don't have to migrate config files later.
    backend: Literal["llama_cpp_python"] = "llama_cpp_python"
    model_path: Path = Field(..., description="Absolute path to the GGUF weights")
    ctx: int = Field(8192, ge=512, le=131_072)
    gpu_layers: int = Field(-1, description="-1 = offload all, 0 = CPU-only")
    n_batch: int = 512
    n_ubatch: int = 512
    flash_attn: bool = True
    threads: int | None = None


class DisplayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    show_latency: bool = False
    show_tool_activity: bool = True
    show_help_on_start: bool = True
    # What pressing Enter does while the agent is mid-turn (hermes parity):
    #   "interrupt" — cancel the running turn, run the new message now
    #   "queue"     — run the new message after the current turn finishes
    #   "steer"     — inject the message into the running turn as guidance
    busy_input_mode: str = "interrupt"


class RetentionConfig(BaseModel):
    """M3 will wire log rotation + memory cap to these; M1 just persists them."""
    model_config = ConfigDict(extra="forbid")
    logs_keep_days: int = Field(30, ge=1)
    logs_max_total_mb: int = Field(1024, ge=16)
    memory_max_mb: int = Field(1024, ge=16)


class SkillsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled_base_skills: list[str] = Field(default_factory=list,
        description="Empty = enable all; otherwise allowlist by skill folder name.")
    hot_reload: bool = False
    run_smoke_tests: bool = True
    include_self_improvement_contract: bool = Field(
        default=False,
        description=(
            "Inject the full v2 self-improvement contract (skill versioning, "
            "smoke tests, rollback rules) into the system prompt. Off by "
            "default — adds ~900 words and only matters when the agent is "
            "actively authoring new skills. Routing benchmarks run leaner "
            "without it."
        ),
    )


class DeepThinkConfig(BaseModel):
    """Deep Think autonomous-mode settings. See docs/deep_think_design.md."""

    model_config = ConfigDict(extra="forbid")
    coder_model: str = Field(
        "qwen3-coder-30b-a3b-q4_k_m",
        description="Model swapped in for Deep Think skill authoring.",
    )
    auto_idle_minutes: int = Field(
        30, ge=0, le=240,
        description=(
            "Minutes of no user input before the TUI auto-enters Deep "
            "Think (when there's approved queued work) — the Jaeger uses "
            "free time to work its own queue. Default 30. 0 = OFF: Deep "
            "Think only starts via /deepthink start."
        ),
    )


class VoiceConfig(BaseModel):
    """Always-on voice settings.

    A Jaeger is embodied — like a person, it always listens. The TUI
    keeps the mic live for the whole session, so the user can talk or
    type at any moment. Every field is tunable live from the TUI with
    ``/voice`` and persisted back to config.yaml.
    """

    model_config = ConfigDict(extra="forbid")
    enabled: bool = Field(
        True,
        description="Mic live from TUI boot. Off = text-only TUI.",
    )
    wake_word: bool = Field(
        True,
        description=(
            "Require a wake phrase ('hey <name>') to address the agent. "
            "Off = every spoken utterance is sent straight to the agent."
        ),
    )
    follow_up: bool = Field(
        True,
        description=(
            "After a reply, open a short window where the user can speak "
            "again without re-saying the wake word."
        ),
    )
    barge_in: bool = Field(
        True,
        description=(
            "Allow interrupting the agent mid-sentence by speaking. Uses "
            "echo cancellation (speexdsp) so the open mic doesn't hear the "
            "agent itself; falls back to mic-pause when speexdsp is absent."
        ),
    )
    follow_up_seconds: float = Field(
        15.0, ge=2.0, le=120.0,
        description="Length of the no-wake-word follow-up window.",
    )


class ExternalModelConfig(BaseModel):
    """Opt-in external-model pipeline. Jaeger is local-first — this is
    OFF by default. When ``enabled``, the agent's brain runs on an
    external provider instead of the in-process llama-cpp model.

    Providers:
      • ``lmstudio``     — a local LM Studio server (OpenAI-compatible HTTP)
      • ``ollama``       — a local Ollama server (OpenAI-compatible HTTP)
      • ``ollama-cloud`` — Ollama Cloud (https://ollama.com/v1), an
                           OpenAI-compatible cloud endpoint; needs a key
      • ``openai``       — any OpenAI-compatible cloud / self-hosted endpoint
      • ``anthropic``    — Claude via the Anthropic API
      • ``gemini``       — Google Gemini via its OpenAI-compatible endpoint

    ``lmstudio`` and ``ollama`` are both still on-device — a separate
    local server, used to A/B against the in-process model when
    troubleshooting whether the local llama-cpp model is at fault.
    ``ollama-cloud``, ``openai``, ``anthropic`` and ``gemini`` are true
    cloud brains (the agent phones out) — off by default, like the rest
    of this block.

    The API key is NEVER stored in this file. It is read from the
    instance's credentials/ store by the name in ``api_key_credential``
    (the sanctioned secret path), falling back to the ``api_key_env``
    environment variable. A local LM Studio server needs no real key.
    """

    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    provider: Literal[
        "lmstudio", "ollama", "ollama-cloud", "openai", "anthropic", "gemini",
    ] = "lmstudio"
    base_url: str = Field(
        "http://localhost:1234/v1",
        description=("OpenAI-compatible endpoint (lmstudio / ollama / openai). "
                     "LM Studio: :1234/v1 · Ollama: :11434/v1. Ignored for anthropic."),
    )
    model: str = Field(
        "local-model",
        description="Model id the provider expects (a 'claude-…' id, or an LM Studio model name).",
    )
    api_key_credential: str = Field(
        "external_model_api_key",
        description="Credential name holding the API key (looked up in credentials/).",
    )
    api_key_env: str = Field(
        "",
        description="Env var to read the key from when the credential is absent.",
    )
    max_tokens: int = Field(1024, ge=16, le=32_768)
    timeout_s: float = Field(60.0, gt=0, le=600)


class WarmupConfig(BaseModel):
    """Boot-time warmup — pre-load the heavy plugins so a Jaeger is
    fully operational the moment boot finishes, not on first use.

    A deployed robot runs TTS and STT constantly, so those default ON —
    the first ``text_to_speech`` / ``listen`` should be instant, not a
    cold model load mid-conversation. Vision pulls a multi-GB model, so
    it defaults OFF — flip it on per-instance when the robot needs it.
    Set a flag false to trim boot time on a dev box that won't use it.
    """

    model_config = ConfigDict(extra="forbid")
    tts: bool = True       # warm Kokoro TTS at boot
    stt: bool = True       # warm Whisper STT at boot
    vision: bool = False   # warm the Moondream2 VLM — heavy, opt-in


class PermissionsConfig(BaseModel):
    """How the agent handles tier-gated actions — running code,
    controlling the computer, installing packages.

      • ``confirm`` — the agent asks before each tier-gated action.
      • ``allow``   — auto-approve; nothing prompts (a trusted,
                      unattended robot).

    Chosen during first-boot setup and persisted here, so the posture
    survives every restart. Change it any time by editing this field.
    Tier-0 reads are always free; this governs tiers 1-4.
    """

    model_config = ConfigDict(extra="forbid")
    mode: Literal["confirm", "allow"] = "confirm"


class SecurityConfig(BaseModel):
    """Security posture toggles.

    ``allow_lazy_installs`` — when an optional feature backend (Kokoro
    TTS, a vision model, the ddgs search client) is missing, may the
    framework pip-install it into the instance venv on first use?
    OFF by default: a missing backend returns a clean "feature
    unavailable, run X" message instead of installing silently.
    """

    model_config = ConfigDict(extra="forbid")
    allow_lazy_installs: bool = False


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance_name: str = Field(..., min_length=1, max_length=64)
    model: ModelConfig
    display: DisplayConfig = Field(default_factory=DisplayConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    deep_think: DeepThinkConfig = Field(default_factory=DeepThinkConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    external_model: ExternalModelConfig = Field(default_factory=ExternalModelConfig)
    warmup: WarmupConfig = Field(default_factory=WarmupConfig)
    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)

    @field_validator("instance_name")
    @classmethod
    def _safe_instance_name(cls, v: str) -> str:
        if any(c in v for c in "/\\:*?\"<>|. "):
            raise ValueError("instance_name must be path-safe (no /, \\, spaces, dots, etc.)")
        return v


# ---------------------------------------------------------------------------
# manifest.json
# ---------------------------------------------------------------------------
class Manifest(BaseModel):
    """Per-instance metadata. Pins the core version that owns this instance
    so a future core upgrade can decide whether to migrate or refuse."""
    model_config = ConfigDict(extra="forbid")

    instance_name: str
    core_version: str = CORE_VERSION
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    last_started_at: str | None = None

    def with_started_now(self) -> "Manifest":
        return self.model_copy(update={"last_started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})


# ---------------------------------------------------------------------------
# Generic helpers — write+read with validation
# ---------------------------------------------------------------------------
def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    import os
    os.replace(tmp, path)


def dump_yaml(path: Path, model: BaseModel) -> None:
    import yaml
    data = model.model_dump(mode="json")
    _atomic_write(path, yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def load_yaml(path: Path, model_cls: type[BaseModel]) -> Any:
    import yaml
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return model_cls.model_validate(raw)


def dump_json(path: Path, model: BaseModel) -> None:
    _atomic_write(path, model.model_dump_json(indent=2))


def load_json(path: Path, model_cls: type[BaseModel]) -> Any:
    import json
    with path.open("r", encoding="utf-8") as fh:
        return model_cls.model_validate(json.load(fh))
