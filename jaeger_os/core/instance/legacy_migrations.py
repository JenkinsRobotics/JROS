"""Pre-resolver layout migrations — one-shot at boot, before the
regular per-instance migration runner gets to fire.

The regular ``core/instance/migrations.py`` runner takes a resolved
:class:`InstanceLayout` and applies schema-level changes. That works
when the resolver can already FIND the instance. But the 0.1.0 →
0.2.0 step moved the on-disk layout from ``~/.jaeger/<name>/``
(flat) to ``~/.jaeger/instances/<name>/`` (nested). A 0.1.0 user's
instance lives at the old path; the new resolver looks at the new
path and finds nothing. The regular runner never gets a chance.

This module is the bridge: a single ``migrate_legacy_layout()``
function called once at boot (from ``main.py``) that scans
``~/.jaeger/`` for loose instance directories and moves them into
``~/.jaeger/instances/<name>/``. It runs BEFORE the resolver; after
it finishes, the resolver works against the new layout and the
regular runner picks up the manifest-bump migration
(``v1_0_0_to_v1_1_0``) the normal way.

Safe to call repeatedly — if no legacy paths exist, it's a no-op.
Always writes a one-shot pre-migration backup before moving so the
user can always undo.
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


# Names directly under ~/.jaeger/ that are NEVER legacy instances.
# Anything else with an identity.yaml gets migrated.
_RESERVED_TOP_NAMES = frozenset({
    "instances",        # the new nested root
    "backups",          # backup archive store
    "active_instance",  # sticky-default file
    "jaeger.env",       # sourceable shell exports
})


def _user_root() -> Path:
    """``~/.jaeger/`` resolved fresh on each call (so tests can
    monkeypatch ``HOME``)."""
    return Path("~/.jaeger").expanduser()


def _looks_like_legacy_instance(path: Path) -> bool:
    """A directory directly under ``~/.jaeger/`` is a legacy 0.1.0
    instance if it's a real directory AND contains ``identity.yaml``.
    Reserved names (``instances``, ``backups``, …) are excluded.
    """
    if not path.is_dir():
        return False
    if path.name in _RESERVED_TOP_NAMES:
        return False
    return (path / "identity.yaml").exists()


def discover_legacy_instances() -> list[Path]:
    """Return every legacy 0.1.0-shaped instance directory under
    ``~/.jaeger/``. Empty list when the user is already on the new
    layout (or has no instances at all).
    """
    root = _user_root()
    if not root.exists():
        return []
    return sorted(p for p in root.iterdir() if _looks_like_legacy_instance(p))


def _backup_legacy_layout(legacy_dirs: list[Path]) -> Path | None:
    """Write a single zip archive containing every legacy instance
    directory before any moves. Returns the archive path on success
    or ``None`` on failure (caller decides whether to proceed — the
    default is to refuse the migration without a backup)."""
    root = _user_root()
    backups_dir = root / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    archive = backups_dir / f"pre-1.1.0-{ts}.zip"
    try:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for inst_dir in legacy_dirs:
                for path in inst_dir.rglob("*"):
                    if path.is_file() or path.is_symlink():
                        # Store paths relative to ~/.jaeger/ so the
                        # archive has the same shape as the live tree.
                        rel = path.relative_to(root)
                        try:
                            zf.write(path, arcname=str(rel))
                        except OSError:
                            # Skip individual files we can't read
                            # (locked sockets, etc.) — keep going.
                            continue
        return archive
    except OSError as exc:
        print(f"[jaeger-migrate] backup failed: {exc}", file=sys.stderr,
              flush=True)
        return None


def migrate_legacy_layout(*, write_stdout=None) -> dict[str, object]:
    """Find every loose ``~/.jaeger/<name>/`` instance and move it to
    ``~/.jaeger/instances/<name>/``. One-shot bootstrap for the
    0.1.0 → 0.2.0 layout change (INST-10).

    Returns a dict reporting what happened — useful for tests and for
    the CLI to print a summary:
      - ``moved``: list of names that were relocated
      - ``backup``: path of the pre-migration archive (or None)
      - ``skipped``: list of (name, reason) tuples
      - ``noop``: True when nothing was eligible

    Idempotent: running twice on the same machine is safe; the
    second run finds nothing to do.

    Side effect: prints progress to ``write_stdout`` (defaults to
    real stdout) so the user sees what's happening at boot.
    """
    out = (write_stdout.write if write_stdout is not None
           else lambda s: print(s, end="", flush=True))

    legacy = discover_legacy_instances()
    if not legacy:
        return {"moved": [], "backup": None, "skipped": [], "noop": True}

    out(f"[jaeger-migrate] found 0.1.0 layout — moving "
        f"{len(legacy)} instance(s) into ~/.jaeger/instances/\n")

    # One pre-migration backup of the entire legacy set. If this
    # fails we refuse to move — the user MUST be able to roll back.
    backup = _backup_legacy_layout(legacy)
    if backup is None:
        out("[jaeger-migrate] refusing to migrate without a backup. "
            "Free up disk + retry, or restore manually.\n")
        return {"moved": [], "backup": None, "skipped": [
            (p.name, "backup-failed") for p in legacy
        ], "noop": False}
    out(f"[jaeger-migrate] backed up to {backup}\n")

    root = _user_root()
    instances_root = root / "instances"
    instances_root.mkdir(parents=True, exist_ok=True)

    moved: list[str] = []
    skipped: list[tuple[str, str]] = []

    for src in legacy:
        name = src.name
        dst = instances_root / name
        if dst.exists():
            # Collision — likely a partial previous migration.
            # Don't overwrite; surface and skip.
            out(f"[jaeger-migrate] skip {name}: destination already "
                f"exists at {dst}\n")
            skipped.append((name, "destination-exists"))
            continue
        try:
            shutil.move(str(src), str(dst))
        except OSError as exc:
            out(f"[jaeger-migrate] skip {name}: move failed ({exc})\n")
            skipped.append((name, f"move-failed: {exc}"))
            continue
        out(f"[jaeger-migrate] {name} → {dst}\n")
        moved.append(name)

    out(f"[jaeger-migrate] done — {len(moved)} moved, "
        f"{len(skipped)} skipped\n")

    return {
        "moved": moved,
        "backup": backup,
        "skipped": skipped,
        "noop": False,
    }


__all__ = [
    "discover_legacy_instances",
    "migrate_legacy_layout",
]
