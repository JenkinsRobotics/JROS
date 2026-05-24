"""Environment preflight — verify the libraries and system tools a
Jaeger needs, and offer to install whatever is missing.

`pip install jaeger-os` pulls the Python packages, but a few of them
wrap system libraries pip cannot provide — PortAudio for audio I/O,
the macOS toolchain for native builds. This module checks the whole
surface, reports exactly what is missing, and — with the user's
consent — runs the fix and re-verifies:

  • ``jaeger-os --doctor`` prints the full report, then offers to
    install anything missing.
  • a concise pass runs at every boot, so a missing dependency is
    surfaced up front, not mid-conversation.

It never installs anything WITHOUT consent — auto-running `pip`/`brew`
silently is too invasive. ``--doctor`` asks first.
"""

from __future__ import annotations

import importlib
import importlib.util
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field


@dataclass
class Check:
    """One probed dependency."""

    name: str
    category: str          # voice | vision | external | memory | messaging | system
    ok: bool
    detail: str = ""
    fix: str = ""                       # human-readable fix
    fix_cmd: list[str] = field(default_factory=list)  # runnable argv, when auto-fixable


# Optional Python deps: (import-name, pip-name, category, pip-extra).
# Core deps (pydantic-ai, llama-cpp-python, rich, …) are NOT listed — if
# one were missing the package would fail to import long before this
# module runs, so a Python ImportError is the report in that case.
_OPTIONAL_DEPS: list[tuple[str, str, str, str]] = [
    ("kokoro", "kokoro", "voice", "voice"),
    ("pywhispercpp", "pywhispercpp", "voice", "voice"),
    ("sounddevice", "sounddevice", "voice", "voice"),
    ("scipy", "scipy", "voice", "voice"),
    ("torch", "torch", "vision", "vision"),
    ("transformers", "transformers", "vision", "vision"),
    ("diffusers", "diffusers", "vision", "vision"),
    ("openai", "openai", "external", "external"),
    ("anthropic", "anthropic", "external", "external"),
    ("sentence_transformers", "sentence-transformers", "memory", "memory"),
    ("discord", "discord.py", "messaging", "messaging"),
]


def _module_present(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _check_python_deps() -> list[Check]:
    out: list[Check] = []
    for mod, pip_name, cat, extra in _OPTIONAL_DEPS:
        present = _module_present(mod)
        out.append(Check(
            name=mod, category=cat, ok=present,
            detail="installed" if present else "not installed",
            fix="" if present else f'pip install "jaeger-os[{extra}]"',
            fix_cmd=[] if present
            else [sys.executable, "-m", "pip", "install", pip_name],
        ))
    return out


def _check_portaudio() -> Check:
    """PortAudio backs `sounddevice` (TTS/STT audio I/O) and pip cannot
    install it. The honest probe is to import sounddevice and see if its
    native library actually loads."""
    if not _module_present("sounddevice"):
        return Check("PortAudio", "system", False, "sounddevice not installed",
                     'pip install "jaeger-os[voice]"',
                     [sys.executable, "-m", "pip", "install", "sounddevice"])
    try:
        import sounddevice  # noqa: F401
    except Exception as exc:  # noqa: BLE001 — native load failure
        has_brew = shutil.which("brew") is not None
        return Check(
            "PortAudio", "system", False,
            f"sounddevice could not load its native library: {exc}",
            "brew install portaudio" if has_brew
            else "install Homebrew (brew.sh), then: brew install portaudio",
            ["brew", "install", "portaudio"] if has_brew else [],
        )
    return Check("PortAudio", "system", True, "audio I/O ready")


def _check_binaries() -> list[Check]:
    out = [Check(
        "git", "system", shutil.which("git") is not None,
        "instance versioning",
        "" if shutil.which("git") else "xcode-select --install",
    )]
    if platform.system() == "Darwin":
        for binary in ("osascript", "screencapture"):
            present = shutil.which(binary) is not None
            out.append(Check(
                binary, "system", present,
                "computer-use" if present else "missing — computer_use needs it",
            ))
    return out


def check_environment() -> list[Check]:
    """Probe every optional Python dependency plus the system libraries
    and binaries. Returns one :class:`Check` per item."""
    return _check_python_deps() + [_check_portaudio()] + _check_binaries()


def missing(checks: list[Check]) -> list[Check]:
    return [c for c in checks if not c.ok]


def fixable(checks: list[Check]) -> list[list[str]]:
    """The de-duplicated set of runnable fix commands for the missing
    checks — what :func:`install_missing` would run."""
    seen: set[tuple[str, ...]] = set()
    cmds: list[list[str]] = []
    for c in missing(checks):
        if c.fix_cmd:
            key = tuple(c.fix_cmd)
            if key not in seen:
                seen.add(key)
                cmds.append(c.fix_cmd)
    return cmds


def install_missing(checks: list[Check]) -> list[Check]:
    """Run the fix command for each auto-fixable missing check, then
    re-probe and return a fresh environment report. The caller is
    responsible for getting the user's consent first."""
    for cmd in fixable(checks):
        print(f"  → {' '.join(cmd)}", flush=True)
        try:
            subprocess.run(cmd, check=False, timeout=900)
        except Exception as exc:  # noqa: BLE001
            print(f"    failed: {type(exc).__name__}: {exc}", flush=True)
    importlib.invalidate_caches()
    return check_environment()


def format_report(checks: list[Check]) -> str:
    """A grouped, human-readable report for ``jaeger-os --doctor``."""
    lines = ["", "  Jaeger-OS — environment check", ""]
    for category in ("voice", "vision", "external", "memory", "messaging", "system"):
        group = [c for c in checks if c.category == category]
        if not group:
            continue
        lines.append(f"  {category}")
        for c in group:
            mark = "✓" if c.ok else "✗"
            lines.append(f"    {mark} {c.name:<22}{c.detail}")
        lines.append("")
    bad = missing(checks)
    if not bad:
        lines.append("  All dependencies present — the Jaeger is fully operational.")
    else:
        lines.append(f"  {len(bad)} item(s) need attention:")
        for cmd in sorted({c.fix for c in bad if c.fix}):
            lines.append(f"    {cmd}")
    lines.append("")
    return "\n".join(lines)


def boot_warning(checks: list[Check]) -> str:
    """A concise one-block warning for the boot log — empty when the
    environment is fully ready."""
    bad = missing(checks)
    if not bad:
        return ""
    names = ", ".join(c.name for c in bad)
    out = [f"[jaeger] ⚠ {len(bad)} optional dependency issue(s): {names}",
           "[jaeger]   run `jaeger-os --doctor` to install them"]
    return "\n".join(out)
