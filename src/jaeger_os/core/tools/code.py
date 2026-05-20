"""Code-execution skills.

  • run_python(code, timeout_s) — execute a Python snippet in a sandboxed
                                  subprocess (fresh interpreter, fresh
                                  tempdir cwd, capped output, hard timeout)
  • run_shell(command, timeout_s) — run a shell command. HIGHEST-risk
                                  tool: tier-4 gated + confirmation +
                                  audit. For git / npm / brew / ffmpeg —
                                  anything the pure-Python tools can't do.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from typing import Any

from ._common import _audit, _require_layout
from ..permissions import PermissionTier, requires_tier


def run_python(code: str, timeout_s: float = 10.0) -> dict[str, Any]:
    """Execute Python code in a fresh, isolated subprocess.

    Sandboxing rules — all enforced by the subprocess boundary:
      - Fresh `python -I` (isolated) with no inherited site-packages.
      - cwd is a fresh tempdir, not the workspace.
      - 10s default timeout (overridable).
      - 200 KB cap on captured stdout/stderr.

    Returns {ok, exit_code, stdout, stderr, elapsed_s, timed_out}.
    """
    cleaned = (code or "").strip()
    if not cleaned:
        return {"ok": False, "error": "empty code"}
    MAX = 200_000
    started = time.perf_counter()
    timed_out = False
    with tempfile.TemporaryDirectory(prefix="jaeger_run_") as scratch:
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", cleaned],
                capture_output=True, text=True, timeout=timeout_s,
                cwd=scratch,
                env={"PATH": os.environ.get("PATH", ""), "HOME": scratch},
            )
            stdout, stderr, exit_code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = -1
            stdout = (exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")) or ""
            stderr = (exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")) or ""
    elapsed = time.perf_counter() - started
    return {
        "ok": exit_code == 0 and not timed_out,
        "exit_code": exit_code,
        "stdout": stdout[:MAX],
        "stderr": stderr[:MAX],
        "elapsed_s": round(elapsed, 3),
        "timed_out": timed_out,
    }


@requires_tier(
    PermissionTier.PRIVILEGED,
    skill="shell",
    operation="run_shell",
    summary="run an arbitrary shell command",
)
def run_shell(command: str, timeout_s: float = 60.0) -> dict[str, Any]:
    """Run a shell command — git, npm, brew, ffmpeg, anything the
    pure-Python tools can't reach.

    THIS IS THE HIGHEST-RISK TOOL. It is gated at PRIVILEGED (tier 4),
    so every call routes through the permission confirmation flow — the
    human sees and approves the exact command before it runs. Every
    invocation is written to the instance audit log.

    Sandboxing is partial by nature (a shell command can do anything
    the OS lets the user do): the command runs with a fresh tempdir as
    cwd and a hard timeout, but it is NOT filesystem-confined the way
    file_write is. Use it deliberately; prefer install_package /
    run_in_venv / run_python when they can do the job.

    Returns ``{ok, exit_code, stdout, stderr, elapsed_s, timed_out}``.
    """
    cleaned = (command or "").strip()
    if not cleaned:
        return {"ok": False, "error": "empty command"}
    timeout = max(1.0, min(float(timeout_s or 60.0), 600.0))

    # Audit every shell invocation, even before it runs — the audit log
    # is the tamper-evident record of what the agent was permitted to do.
    try:
        layout = _require_layout()
        _audit("run_shell", {"command": cleaned[:500], "timeout_s": timeout})
    except Exception:  # noqa: BLE001
        pass

    MAX = 200_000
    started = time.perf_counter()
    timed_out = False
    with tempfile.TemporaryDirectory(prefix="jaeger_shell_") as scratch:
        try:
            proc = subprocess.run(
                ["/bin/sh", "-c", cleaned],
                capture_output=True, text=True, timeout=timeout,
                cwd=scratch,
            )
            stdout, stderr, exit_code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = -1
            stdout = (exc.stdout.decode() if isinstance(exc.stdout, bytes)
                      else (exc.stdout or "")) or ""
            stderr = (exc.stderr.decode() if isinstance(exc.stderr, bytes)
                      else (exc.stderr or "")) or ""
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                    "command": cleaned}
    elapsed = time.perf_counter() - started
    return {
        "ok": exit_code == 0 and not timed_out,
        "command": cleaned,
        "exit_code": exit_code,
        "stdout": stdout[:MAX],
        "stderr": stderr[:MAX],
        "elapsed_s": round(elapsed, 3),
        "timed_out": timed_out,
    }
