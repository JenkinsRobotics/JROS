"""``jaeger bench compare`` — multi-model bench with an interactive picker.

The agent can't switch its own model mid-run, so multi-model comparison
is operator-driven by design. This verb is the friendly UX layer over
``benchmark/run_model_sweep.py`` — it discovers ``.gguf`` files on disk,
shows them in a numbered list, and lets the operator pick which ones
to bench. The sweep script does the rest (config swap, subprocess per
model, comparison report).

Flow:

  1. Scan known model dirs (``~/.lmstudio/models/`` by default plus
     any ``model.extra_gguf_dirs`` from the current config) for
     ``*.gguf`` files. Filter out mmproj sidecars.
  2. Print a numbered list with size + currently-active marker.
  3. Accept ``N,M,P`` / ``all`` / ``current`` from stdin. ``--models``
     bypasses the picker for scripts.
  4. Write the selection to a temp file and exec
     ``python benchmark/run_model_sweep.py /tmp/sel.txt``.
  5. The sweep writes its comparison markdown under
     ``benchmark/sweep/RESULTS_<ts>.md`` — we print the path so the
     operator knows where to read.

Args (all optional):

  --models PATH1,PATH2[,...]   Skip the picker; use these models.
  --tags ROUTING,MEMORY        Tag filter for the inner bench.
  --limit N                    Cap cases per model (after tag filter).
  --extra-dirs DIR1,DIR2       Additional directories to scan.
  --dry-run                    Show the selection but don't run.

Exit codes:
  0 — sweep completed (regardless of pass-rate; check the report).
  1 — no models discovered, or sweep failed to launch.
  2 — bad arguments / user cancelled.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import tempfile
from typing import Iterable


_DEFAULT_MODEL_DIRS: tuple[str, ...] = (
    "~/.lmstudio/models",
)


def _cmd_bench_compare_argv(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="jaeger bench compare", add_help=False,
    )
    parser.add_argument(
        "--models", default=None,
        help="comma-separated model paths (skip picker)",
    )
    parser.add_argument(
        "--tags", default=None,
        help="bench tag filter (e.g. 'routing,memory'). Empty = full corpus.",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="cap cases per model after tag filter (0 = no cap)",
    )
    parser.add_argument(
        "--extra-dirs", default=None,
        help="comma-separated extra directories to scan for .gguf files",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="show the selection but don't actually run the sweep",
    )
    parser.add_argument(
        "--instance", default=None,
        help="instance name (default: active)",
    )
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)
    if args.help:
        _print_help()
        return 0

    # Either --models given (scripted) or run the picker.
    if args.models:
        selected = _resolve_paths(args.models.split(","))
        if not selected:
            print("[jaeger bench compare] none of the --models paths "
                  "exist on disk", file=sys.stderr)
            return 2
    else:
        discovered = _discover_models(
            extra_dirs=(args.extra_dirs or "").split(","),
            instance_name=args.instance,
        )
        if not discovered:
            print("[jaeger bench compare] no .gguf models found under "
                  f"{', '.join(_DEFAULT_MODEL_DIRS)} — pass --extra-dirs "
                  "or use --models with explicit paths", file=sys.stderr)
            return 1
        current_path = _current_model_path(instance_name=args.instance)
        selected = _interactive_pick(discovered, current=current_path)
        if not selected:
            print("[jaeger bench compare] cancelled — no models selected",
                  file=sys.stderr)
            return 2

    # Summary of the chosen set before launching.
    print()
    print(f"Selected {len(selected)} model(s) to benchmark:")
    for p in selected:
        size = _human_size(p)
        print(f"  - {pathlib.Path(p).name}  ({size})")
    print()
    if args.tags:
        print(f"Tags filter:   {args.tags}")
    if args.limit:
        print(f"Limit / model: {args.limit}")

    if args.dry_run:
        print("\n--dry-run: not launching sweep.")
        return 0

    # Write a temp file the sweep script can consume.
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8",
    ) as fh:
        for p in selected:
            fh.write(p + "\n")
        models_file = fh.name

    repo = _repo_root()
    sweep_script = repo / "benchmark" / "run_model_sweep.py"
    if not sweep_script.is_file():
        print(f"[jaeger bench compare] sweep script missing at {sweep_script}",
              file=sys.stderr)
        return 1

    print(f"\nLaunching sweep. This will run the bench once per model "
          f"(cold-load each time) — expect several minutes per model.\n")

    env = os.environ.copy()
    # Pass tag + limit through env so the sweep script can forward to
    # the inner ``run_flat_bench.py`` invocation. (The sweep accepts
    # these as env vars rather than CLI flags so the script's surface
    # stays stable for existing users.)
    if args.tags:
        env["JAEGER_BENCH_TAGS"] = args.tags
    if args.limit:
        env["JAEGER_BENCH_LIMIT"] = str(args.limit)

    rc = subprocess.call(
        [sys.executable, str(sweep_script), models_file],
        env=env,
    )

    # Sweep writes its own report path; the script prints it. Surface
    # the SWEEP_DIR for the operator if the rc was ok.
    sweep_dir = repo / "benchmark" / "sweep"
    if rc == 0:
        print(f"\nSweep complete. Reports under: {sweep_dir}")
    else:
        print(f"\n[jaeger bench compare] sweep exited rc={rc}",
              file=sys.stderr)
    return rc


# ── model discovery ─────────────────────────────────────────────


def _discover_models(
    *,
    extra_dirs: Iterable[str],
    instance_name: str | None,
) -> list[str]:
    """Walk known directories for ``.gguf`` files, filtering out
    mmproj sidecar files (they're not chat models). Sorted by path
    for stable picker numbering."""
    dirs: list[pathlib.Path] = []
    for d in _DEFAULT_MODEL_DIRS:
        dirs.append(pathlib.Path(d).expanduser())
    for d in extra_dirs:
        d = (d or "").strip()
        if d:
            dirs.append(pathlib.Path(d).expanduser())
    # Pull extra dirs from the instance config too.
    cfg_dirs = _config_extra_gguf_dirs(instance_name=instance_name)
    for d in cfg_dirs:
        dirs.append(pathlib.Path(d).expanduser())

    found: set[str] = set()
    for root in dirs:
        if not root.exists():
            continue
        for p in root.rglob("*.gguf"):
            name = p.name.lower()
            # Skip mmproj sidecars + projection files — not chat models.
            if "mmproj" in name or "projector" in name:
                continue
            found.add(str(p))
    return sorted(found)


def _config_extra_gguf_dirs(*, instance_name: str | None) -> list[str]:
    """Read ``model.extra_gguf_dirs`` from the active instance's
    config.yaml. Returns [] when no instance is bound or the field
    is missing."""
    try:
        from jaeger_os.core.instance.instance import (
            InstanceLayout, default_instance_name, resolve_instance_dir,
        )
        from jaeger_os.core.instance.schemas import Config, load_yaml
    except Exception:  # noqa: BLE001
        return []
    name = instance_name or default_instance_name()
    try:
        layout = InstanceLayout(root=resolve_instance_dir(name))
        if not layout.config_path.exists():
            return []
        cfg = load_yaml(layout.config_path, Config)
        extras = getattr(cfg.model, "extra_gguf_dirs", None) or []
        return [str(d) for d in extras]
    except Exception:  # noqa: BLE001
        return []


def _current_model_path(*, instance_name: str | None) -> str | None:
    """Return the currently-configured ``model.model_path`` so the
    picker can mark it. None when no instance / no config."""
    try:
        from jaeger_os.core.instance.instance import (
            InstanceLayout, default_instance_name, resolve_instance_dir,
        )
        from jaeger_os.core.instance.schemas import Config, load_yaml
    except Exception:  # noqa: BLE001
        return None
    name = instance_name or default_instance_name()
    try:
        layout = InstanceLayout(root=resolve_instance_dir(name))
        if not layout.config_path.exists():
            return None
        cfg = load_yaml(layout.config_path, Config)
        return getattr(cfg.model, "model_path", None)
    except Exception:  # noqa: BLE001
        return None


# ── picker ──────────────────────────────────────────────────────


def _interactive_pick(
    models: list[str],
    *,
    current: str | None,
) -> list[str]:
    """Numbered-list picker. Returns the user's selection (possibly
    empty if they cancelled with Ctrl-C or blank input).

    Accepts:
      - ``all``          → every model
      - ``current``      → just the currently-configured model
      - ``1,3,5``        → comma-separated indices (1-based)
      - blank / Ctrl-C   → cancel
    """
    print("Available models:")
    print()
    for i, p in enumerate(models, start=1):
        marker = "*" if current and p == current else " "
        name = pathlib.Path(p).name
        size = _human_size(p)
        print(f"  {marker} [{i:>2}] {name:<48} ({size})")
    if current and current not in models:
        print(f"\n  * = currently active (not discovered; passed via config)")
    elif current:
        print(f"\n  * = currently active")
    print()
    print("Pick models — comma-separated indices, 'all', 'current', "
          "or blank to cancel:")
    try:
        raw = input("> ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return []
    if not raw:
        return []
    if raw == "all":
        return list(models)
    if raw == "current":
        return [current] if current else []
    selected: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            idx = int(part)
        except ValueError:
            print(f"  (skipping non-numeric input: {part!r})", file=sys.stderr)
            continue
        if 1 <= idx <= len(models):
            selected.append(models[idx - 1])
        else:
            print(f"  (skipping out-of-range index: {idx})", file=sys.stderr)
    # De-dup while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for p in selected:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


# ── helpers ─────────────────────────────────────────────────────


def _resolve_paths(raw: Iterable[str]) -> list[str]:
    """Expand + validate paths passed via ``--models``."""
    out: list[str] = []
    for p in raw:
        p = (p or "").strip()
        if not p:
            continue
        expanded = pathlib.Path(p).expanduser().resolve()
        if expanded.exists():
            out.append(str(expanded))
        else:
            print(f"[jaeger bench compare] not found: {p}", file=sys.stderr)
    return out


def _human_size(path: str) -> str:
    try:
        bytes_ = pathlib.Path(path).stat().st_size
    except OSError:
        return "?"
    if bytes_ >= 1e9:
        return f"{bytes_ / 1e9:.1f} GB"
    if bytes_ >= 1e6:
        return f"{bytes_ / 1e6:.1f} MB"
    return f"{bytes_} B"


def _repo_root() -> pathlib.Path:
    # The verb runs from any cwd; find the repo by walking up from
    # this file's location. (``daemon/`` is two levels below the
    # top-level ``benchmark/`` directory in the source layout.)
    here = pathlib.Path(__file__).resolve()
    # Editable install: src/jaeger_os/daemon/bench_compare_verb.py
    # Site-packages: site-packages/jaeger_os/daemon/...
    # Walk up looking for ``benchmark/run_model_sweep.py``.
    for parent in [here, *here.parents]:
        candidate = parent / "benchmark" / "run_model_sweep.py"
        if candidate.is_file():
            return parent
    # Fallback: the installed wheel doesn't ship benchmark/, the user
    # has to be on a checkout. Surface that explicitly when we try
    # to run the sweep.
    return here.parents[3]  # best guess; the rc=1 branch below catches it


def _print_help() -> None:
    print(
        "usage: jaeger bench compare [options]\n"
        "\n"
        "Interactive multi-model bench comparison. Discovers .gguf\n"
        "models on disk, shows a numbered picker, runs the full bench\n"
        "corpus against each selected model, writes a comparison\n"
        "report under benchmark/sweep/.\n"
        "\n"
        "options:\n"
        "  --models P1,P2[,...]     skip picker; use these paths\n"
        "  --tags ROUTING,MEMORY    bench tag filter\n"
        "  --limit N                cap cases per model (default: full corpus)\n"
        "  --extra-dirs D1,D2       extra dirs to scan for .gguf\n"
        "  --dry-run                show selection without launching\n"
        "  --instance NAME          instance to read config from\n"
        "\n"
        "Discovery default: scans ~/.lmstudio/models/. Add more dirs\n"
        "with --extra-dirs or by setting model.extra_gguf_dirs in\n"
        "config.yaml.",
        file=sys.stderr,
    )


__all__ = ["_cmd_bench_compare_argv"]
