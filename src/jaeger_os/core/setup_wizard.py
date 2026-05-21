"""First-boot setup — the Jaeger onboarding wizard.

Triggered by main.py when the resolved instance dir has no valid
identity/config/manifest trio yet. It walks the user through setup one
step at a time — identity, model, permissions, warm-up — then writes
the three files, lays out the directory, and git-inits the instance so
skill changes are versioned. When it finishes, the system is ready to
run; boot continues straight into the agent.

Re-runnable: if the instance already exists, it is backed up aside
(`<dir>.bak.<timestamp>`) before a fresh one is built — re-running
never destroys prior work.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .instance import (
    InstanceLayout,
    backup_instance_dir,
    default_instance_name,
    resolve_instance_dir,
)
from .model_resolver import DEFAULT_MODEL, MODEL_REGISTRY
from .schemas import (
    CORE_VERSION,
    Config,
    DisplayConfig,
    Identity,
    Manifest,
    ModelConfig,
    PermissionsConfig,
    RetentionConfig,
    SkillsConfig,
    WarmupConfig,
    dump_json,
    dump_yaml,
)

_TOTAL_STEPS = 5

# Kokoro voices offered at setup — (voice_id, human label).
_VOICES = [
    ("am_michael", "Michael — male, even-keeled"),
    ("af_heart", "Heart — female, warm"),
    ("am_adam", "Adam — male, bright"),
    ("af_bella", "Bella — female, expressive"),
]


# ── prompt helpers ───────────────────────────────────────────────────


def _ask(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    return input(f"  {label}{suffix}: ").strip() or default


def _ask_yn(label: str, default: bool) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = input(f"  {label} ({hint}): ").strip().lower()
    return default if not raw else raw[0] == "y"


def _ask_int(label: str, default: int) -> int:
    while True:
        raw = _ask(label, str(default))
        try:
            return int(raw)
        except ValueError:
            print(f"     (expected a number, got {raw!r})")


def _ask_choice(prompt: str, options: list[tuple[str, str]], default: int = 0) -> str:
    """Numbered single-choice pick. ``options`` = [(value, label), …].
    Returns the chosen value. A bare Enter takes the default."""
    for i, (_value, label) in enumerate(options):
        marker = "›" if i == default else " "
        print(f"     {marker} {i + 1}. {label}")
    while True:
        raw = input(f"  {prompt} [{default + 1}]: ").strip()
        if not raw:
            return options[default][0]
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        print(f"     (pick 1-{len(options)})")


def _banner(line: str) -> None:
    print()
    print("  ┌" + "─" * 56 + "┐")
    print(f"  │  {line:<54}│")
    print("  └" + "─" * 56 + "┘")


def _step(n: int, title: str) -> None:
    print()
    print(f"  ── Step {n}/{_TOTAL_STEPS} · {title} " + "─" * (34 - len(title)))


# ── the wizard ───────────────────────────────────────────────────────


def run_wizard(*, force: bool = False, instance_name: str | None = None) -> InstanceLayout:
    """Walk first-boot setup end to end. Returns the new instance layout."""
    name = instance_name or default_instance_name()
    layout = InstanceLayout(root=resolve_instance_dir(name))

    _banner("Welcome to Jaeger-OS")
    print()
    print("  Let's set up your Jaeger. Five quick steps — identity, model,")
    print("  permissions, and warm-up — then it boots straight in.")
    print(f"  Instance: {layout.root}")

    if layout.exists():
        if not force and not _ask_yn(
            "\n  This instance already exists. Back it up and start fresh?", False
        ):
            print("  Setup cancelled.")
            sys.exit(0)
        backup_instance_dir(layout)

    # ── Step 1 · Identity ───────────────────────────────────────────
    _step(1, "Identity")
    print("  Who is this Jaeger?")
    agent_name = _ask("Name", "Jarvis")
    role = _ask("Role — what does it do?", "general-purpose agentic assistant")
    personality = _ask(
        "Personality (one line)",
        "Helpful, capable, concise — honest about uncertainty.",
    )
    print("  Voice:")
    voice_id = _ask_choice("Pick a voice", _VOICES, default=0)
    identity = Identity(
        name=agent_name, role=role, personality=personality,
        voice_tone="clear, even-keeled", voice_id=voice_id,
    )

    # ── Step 2 · Model ──────────────────────────────────────────────
    _step(2, "Model")
    print("  Which model is the Jaeger's brain?")
    model_opts = [
        (key, f"{key}" + ("  (default)" if key == DEFAULT_MODEL else ""))
        for key in MODEL_REGISTRY
    ]
    model_opts.append(("__custom__", "a custom GGUF path"))
    default_idx = next((i for i, (k, _) in enumerate(model_opts) if k == DEFAULT_MODEL), 0)
    model_choice = _ask_choice("Pick a model", model_opts, default=default_idx)
    if model_choice == "__custom__":
        model_path = _ask("Path to a .gguf file", "")
        if model_path and not Path(model_path).expanduser().exists():
            print(f"     ⚠  {model_path} not found — saving anyway; "
                  "resolve it before first use.")
    else:
        model_path = model_choice
        print(f"     → {model_path} (resolved from the registry; "
              "downloaded on first use if not cached).")

    # ── Step 3 · Permissions ────────────────────────────────────────
    _step(3, "Permissions")
    print("  Some tools act on the world — run code, control the computer,")
    print("  install packages. How should the agent handle those?")
    perm_mode = _ask_choice(
        "Choose",
        [
            ("confirm", "Ask me before each action  (recommended)"),
            ("allow", "Auto-allow everything  (trusted, unattended robot)"),
        ],
        default=0,
    )

    # ── Step 4 · Warm-up ────────────────────────────────────────────
    _step(4, "Warm-up")
    print("  Pre-load components at boot so they're instant on first use.")
    warm_tts = _ask_yn("Warm Text-to-Speech (Kokoro)?", True)
    warm_stt = _ask_yn("Warm Speech-to-Text (Whisper)?", True)
    warm_vision = _ask_yn("Warm Vision (Moondream2 — heavier, multi-GB)?", False)

    # ── Step 5 · Review ─────────────────────────────────────────────
    _step(5, "Review")
    print(f"     Identity     {agent_name} — {role}")
    print(f"     Voice        {voice_id}")
    print(f"     Model        {model_path}")
    print(f"     Permissions  {'ask before each action' if perm_mode == 'confirm' else 'auto-allow'}")
    print(f"     Warm-up      TTS={'on' if warm_tts else 'off'}  "
          f"STT={'on' if warm_stt else 'off'}  Vision={'on' if warm_vision else 'off'}")
    if not _ask_yn("\n  Looks good — create the Jaeger?", True):
        print("  Setup cancelled. Re-run to start over.")
        sys.exit(0)

    config = Config(
        instance_name=name,
        model=ModelConfig(model_path=model_path, ctx=16384, gpu_layers=-1),
        display=DisplayConfig(),
        skills=SkillsConfig(),
        retention=RetentionConfig(),
        warmup=WarmupConfig(tts=warm_tts, stt=warm_stt, vision=warm_vision),
        permissions=PermissionsConfig(mode=perm_mode),
    )
    manifest = Manifest(instance_name=name, core_version=CORE_VERSION)

    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    dump_yaml(layout.identity_path, identity)
    dump_yaml(layout.config_path, config)
    dump_json(layout.manifest_path, manifest)
    _git_init(layout.root)

    _banner(f"{agent_name} is ready")
    print()
    print(f"  Instance: {layout.root}")
    print("  Booting now…")
    print()
    return layout


# ── git ──────────────────────────────────────────────────────────────


def _git_init(root: Path) -> None:
    if not _has_git():
        return
    try:
        subprocess.run(
            ["git", "init", "-q", "-b", "main", str(root)],
            check=True, capture_output=True, timeout=10,
        )
        (root / ".gitignore").write_text(
            "# Auto-generated by the Jaeger wizard.\n"
            ".lock\n"
            "credentials/\n"
            "logs/\n"
            "memory/episodic.embeddings.npz\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "-C", str(root), "add", "-A"],
            check=True, capture_output=True, timeout=10,
        )
        subprocess.run(
            ["git", "-C", str(root), "-c", "user.email=jaeger@local",
             "-c", "user.name=jaeger-setup",
             "commit", "-q", "-m", "jaeger: initial instance"],
            check=False, capture_output=True, timeout=10,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"[jaeger] git init skipped: {exc}", file=sys.stderr, flush=True)


def _has_git() -> bool:
    try:
        from shutil import which
        return which("git") is not None
    except Exception:  # noqa: BLE001
        return False
