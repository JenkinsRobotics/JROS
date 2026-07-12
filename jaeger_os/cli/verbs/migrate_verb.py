"""``jaeger update``'s ecosystem-migration path (0.8.2 — the HANDOFF
RELEASE). In-place product swap from the legacy JROS monorepo to the
JaegerAI ecosystem (the 0.9 four-way split: JaegerOS + JaegerAI +
JaegerKokoroTTS + JaegerWhisperSTT, installed together via JaegerAI's
own git-pinned ``requirements.txt``).

This reuses :mod:`update_verb`'s tarball-download + product-swap
machinery end-to-end. The only genuinely new logic is:

  * :data:`_JAEGERAI_PRODUCT` — JaegerAI's own product allowlist (a
    different item set than JROS's — ``jaeger_ai`` where JROS has
    ``jaeger_os``), passed into ``update_verb._extract_product``'s new
    ``product=`` parameter.
  * :func:`_migrate_swap` — a full-manifest stash-then-place swap.
    ``update_verb._swap_in`` only stashes an old item when the NEW
    product has an item of the *same name* (a same-family version
    bump); here the old product's ``jaeger_os`` has no counterpart in
    the new manifest at all, so it would never get stashed by that
    name-matched loop. This swap stashes the OLD manifest unconditionally, then
    places the new one.

Everything else — the ``.update-prev/`` swap-history directory, the
per-item ``os.replace`` atomicity, and above all ``jaeger update
--rollback`` — is untouched, reused as-is. That rollback path runs
from the NEWLY INSTALLED ``jaeger_ai`` package's own copy of
``update_verb.py`` (byte-identical to this repo's, module docstrings
and all — confirmed against JaegerAI 0.9.0's source before writing
this) after a migration, and ``_do_rollback`` just walks whatever
``.update-prev/`` holds and restores it by name — it neither knows nor
cares that the names it's restoring (``jaeger_os``, ``install.sh``,
...) differ from the current product's (``jaeger_ai``, ...). No new
rollback code was needed; :func:`run_ecosystem_migration` only ever
*writes* ``.update-prev/`` in the shape ``_do_rollback`` already knows
how to read.

KNOWN GAP (verified in the walk, documented rather than papered over):
``_do_rollback`` restores what's IN ``.update-prev/`` but has no reason
to remove a current-product item that was never stashed there —
``jaeger_ai/`` itself, since it's a NEW item with no old-manifest
counterpart. A rollback therefore leaves ``jaeger_ai/`` sitting next to
the restored ``jaeger_os/`` — harmless (nothing on the restored
station's ``sys.path`` imports it; the restored ``jaeger``/``run.sh``
wrappers exec ``jaeger_os.cli.entry``, not ``jaeger_ai``'s) but is
debris, not a clean revert. Fixed to be crash-SAFE (:func:`_migrate_swap`
clears an existing same-named target before placing, so a repeat
migration over that debris doesn't hit ``ENOTEMPTY``); the debris
itself isn't proactively cleaned since nothing in THIS repo runs again
after a rollback to do it — that would require a patch to JaegerAI's
own ``_do_rollback``, out of this task's repo/scope. Flagged for
JaegerAI's next patch alongside the ``version_check`` bug below.

``.jaeger_os/`` (identity, memory, credentials, models — every byte of
instance state) is named in NEITHER product's allowlist and is
therefore never touched by this module, by the same construction that
already protects it across an ordinary framework update. Both repos
were confirmed (by reading JaegerAI 0.9.0's ``core/instance/instance.py``)
to resolve instance state to the identical path:
``<install_root>/.jaeger_os/instances/<name>/``.

Design choices — judged from reality, not assumed; see
``.superpowers/sdd/082-handoff-report.md`` for the walk that verified
them:

  * **Fresh ``.venv``, not reused.** JaegerAI's dependency graph doesn't
    share package identity with the old editable ``jaeger-os`` install
    this station has today (the git-pinned ``jaeger-os`` JaegerAI pulls
    in is a *different* install of the *same-named* package, resolved
    fresh from GitHub) — reusing the venv risks a stale editable
    ``.pth``/egg-link surviving the swap and shadowing the new one.
    Deleting it and letting JaegerAI's own ``install.sh`` recreate it is
    exactly what a fresh curl install already does, so it's proven code,
    not new code.
  * **JaegerAI's OWN ``install.sh`` does the install**, downloaded as
    part of the product and run in place (``--product`` mode — this
    machine has never run it before, so it's an end-user install, not a
    developer checkout). "The swap places the code; the code installs
    itself" mirrors how the existing tarball-update already defers
    dependency resolution to ``pip``/``uv`` rather than reimplementing
    it here.
  * **Known upstream gap, worked around locally, not fixed here**:
    JaegerAI 0.9.0's ``core/version_check.py`` still hardcodes
    ``_DEFAULT_REPO = "JenkinsRobotics/JROS"`` — a split-era leftover
    (verified by reading the file; out of this task's repo/scope to
    patch since JaegerAI is already tagged 0.9.0). The one override
    that code already honours is the ``JAEGER_REPO_URL`` env var, so
    :func:`_patch_repo_url` exports it from *this station's own*
    ``jaeger``/``run.sh`` wrapper scripts post-swap — a local, two-line
    patch to the migrated station's copies, not a change to the
    JaegerAI source tree. Flagged for JaegerAI to fix at the source;
    see the handoff report.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from jaeger_os.cli.verbs import update_verb as _upd
from jaeger_os.core import version_check

_JAEGERAI_REPO_DEFAULT = "JenkinsRobotics/JaegerAI"
_JAEGERAI_CLONE_URL = "https://github.com/JenkinsRobotics/JaegerAI.git"
_MIN_ECOSYSTEM_VERSION = (0, 9, 0)

# Mirrors JaegerAI 0.9.0's own update_verb._PRODUCT (jaeger_ai/cli/verbs/
# update_verb.py) — kept as a literal copy, not an import, because it
# describes the ARCHIVE we download (a point-in-time snapshot of another
# repo), not this repo's own code.
_JAEGERAI_PRODUCT = (
    "jaeger_ai",
    "install.sh", "run.sh", "jaeger",
    "requirements.txt", "pyproject.toml",
    "jaeger.toml", "jaeger.windowed.toml",
    "README.md", "LICENSE", "CHANGELOG.md",
)


def _jaegerai_repo_slug() -> str:
    """``owner/repo`` for the JaegerAI GitHub API, honouring
    ``JAEGERAI_REPO_URL`` (mirrors ``version_check.repo_slug``'s
    ``JAEGER_REPO_URL`` handling, kept distinct so pointing THIS
    install's ordinary update at a JROS fork never also repoints the
    ecosystem-migration lookup)."""
    url = os.environ.get("JAEGERAI_REPO_URL", "").strip()
    if "github.com" in url:
        tail = url.split("github.com", 1)[1].lstrip("/:").removesuffix(".git")
        if tail.count("/") >= 1:
            return "/".join(tail.split("/")[:2])
    return _JAEGERAI_REPO_DEFAULT


def check_ecosystem_available(*, timeout: float = 5.0) -> str | None:
    """Newest published JaegerAI tag, or ``None`` when GitHub is
    unreachable, no tags exist yet, or the newest tag predates the
    ecosystem's minimum viable version (0.9.0 — the first release where
    all four split repos are live together). Never raises — mirrors
    :func:`version_check.latest_version`'s network-failure handling."""
    tag = version_check.latest_version(_jaegerai_repo_slug(), timeout=timeout)
    if tag is None:
        return None
    if version_check.parse_version(tag) < _MIN_ECOSYSTEM_VERSION:
        return None
    return tag


def already_migrated(home: Path) -> bool:
    """True once this station's product IS the JaegerAI stack (the
    migration already ran here)."""
    return (home / "jaeger_ai").exists()


def _extract_jaegerai_product(tarball: Path, staging: Path) -> list[str]:
    return _upd._extract_product(tarball, staging, product=_JAEGERAI_PRODUCT)


def _migrate_swap(home: Path, staging: Path, prev: Path,
                  old_items: tuple[str, ...],
                  new_items: list[str]) -> tuple[list[str], list[str]]:
    """Cross-product swap: every OLD item that exists in ``home`` is
    unconditionally stashed into ``prev`` (not just ones with a
    same-named replacement — ``update_verb._swap_in`` can't stash
    ``jaeger_os``, since the new manifest has no item by that name),
    then every staged NEW item is placed into ``home``. Same
    ``os.replace`` per-item atomicity as ``_swap_in``; neither loop
    ever names ``.venv/`` or ``.jaeger_os/``, so neither is touched.
    Returns ``(stashed, placed)`` item names."""
    if prev.exists():
        shutil.rmtree(prev)
    prev.mkdir(parents=True)
    stashed: list[str] = []
    for item in old_items:
        cur = home / item
        if cur.exists():
            os.replace(cur, prev / item)
            stashed.append(item)
    placed: list[str] = []
    for item in new_items:
        new = staging / item
        if not new.exists():
            continue
        cur = home / item
        if cur.exists():
            # A non-empty directory already at the target breaks a bare
            # os.replace (ENOTEMPTY). Only reachable via a RE-migration
            # over debris left by update_verb._do_rollback: it restores
            # the old manifest but — being generic, and unaware this was
            # a cross-product swap — has no reason to remove a NEW item
            # like jaeger_ai/ that was never in .update-prev/ to begin
            # with (see the module docstring's "known gap"). Clearing it
            # here makes a repeat migration idempotent instead of a crash.
            shutil.rmtree(cur) if cur.is_dir() else cur.unlink()
        os.replace(new, home / item)
        placed.append(item)
    return stashed, placed


def _patch_repo_url(home: Path) -> None:
    """Work around the known JaegerAI 0.9.0 ``version_check.repo_slug``
    bug (see module docstring) by exporting ``JAEGER_REPO_URL`` from
    this station's own wrapper scripts, so `jaeger update` / `jaeger
    doctor` on THIS migrated station check JaegerAI's tags, not
    JROS's. Idempotent (no-ops if already patched, e.g. a re-run)."""
    line = f'export JAEGER_REPO_URL="{_JAEGERAI_CLONE_URL}"\n'
    for name in ("jaeger", "run.sh"):
        path = home / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if "JAEGER_REPO_URL" in text:
            continue
        lines = text.splitlines(keepends=True)
        for i, one_line in enumerate(lines):
            if one_line.startswith("set -"):
                lines.insert(i + 1, line)
                break
        else:
            lines.insert(1, line)   # fallback: right after the shebang
        path.write_text("".join(lines), encoding="utf-8")


def run_ecosystem_migration(home: Path, *, ref: str | None = None) -> int:
    """The migrate path: download JaegerAI@``ref``, swap the product in
    place, then hand off to JaegerAI's own ``install.sh`` for the
    .venv/deps/app build. ``.jaeger_os/`` (all instance state) is never
    named in either product manifest and so is never touched — this
    function contains no code path that can reach it. Returns 0 on
    success; the old stack is recoverable via ``jaeger update
    --rollback`` on any non-zero return past the swap."""
    ref = ref or check_ecosystem_available() or "0.9.0"
    repo = _jaegerai_repo_slug()
    print(f"[jaeger update] JaegerAI ecosystem migration: {repo}@{ref}")

    staging = home / _upd._STAGING_DIR
    prev = home / _upd._PREV_DIR
    shutil.rmtree(staging, ignore_errors=True)
    try:
        with tempfile.TemporaryDirectory() as td:
            tarball = Path(td) / "jaegerai.tar.gz"
            _upd._download_tarball(repo, ref, tarball)
            copied = _extract_jaegerai_product(tarball, staging)
        if "jaeger_ai" not in copied:
            print("[jaeger update] archive missing jaeger_ai/ — aborting "
                  "migration (nothing changed).", file=sys.stderr)
            return 1
        old_items = _upd._PRODUCT   # this install's OWN full manifest
        stashed, placed = _migrate_swap(home, staging, prev, old_items, copied)
        print(f"[jaeger update] stashed {len(stashed)} legacy item(s) into "
              f"{_upd._PREV_DIR}/; placed {len(placed)} JaegerAI item(s).")
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    _patch_repo_url(home)

    venv = home / ".venv"
    if venv.exists():
        print("[jaeger update] removing the legacy .venv (a fresh one is "
              "built below — see module docstring for why it isn't reused)…")
        shutil.rmtree(venv)

    install_sh = home / "install.sh"
    if not install_sh.exists():
        print("[jaeger update] JaegerAI product missing install.sh — files "
              "are swapped but deps/app were NOT installed; run it by hand, "
              "or `jaeger update --rollback` to revert.", file=sys.stderr)
        return 1
    print("[jaeger update] running JaegerAI's installer "
          "(.venv + deps + app build)…")
    rc = subprocess.run(["bash", str(install_sh), "--product"],
                        cwd=home, check=False).returncode
    if rc != 0:
        print(f"[jaeger update] JaegerAI install.sh exited {rc} — "
              f"`jaeger update --rollback` to revert to the legacy stack.",
              file=sys.stderr)
        return rc

    print()
    print(f"[jaeger update] migrated to JaegerAI {ref}. Instance data "
          f"(.jaeger_os/) was never touched. Restart to apply; "
          f"`jaeger update --rollback` restores the legacy JROS stack.")
    return 0


__all__ = [
    "check_ecosystem_available", "already_migrated",
    "run_ecosystem_migration",
]
