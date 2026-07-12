"""0.8.2 HANDOFF RELEASE — the JaegerAI ecosystem-migration path.

Unit-tests migrate_verb's own logic in isolation (network + subprocess
mocked). The full end-to-end walk (real download, real install.sh, real
turn, real rollback) lives in dev/scripts/walk_082_migrate.sh — see
.superpowers/sdd/082-handoff-report.md for that run's results.
"""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from jaeger_os.cli.verbs import migrate_verb as M
from jaeger_os.cli.verbs import update_verb as U


# ── repo slug + availability ─────────────────────────────────────────


def test_jaegerai_repo_slug_default(monkeypatch):
    monkeypatch.delenv("JAEGERAI_REPO_URL", raising=False)
    assert M._jaegerai_repo_slug() == "JenkinsRobotics/JaegerAI"


def test_jaegerai_repo_slug_honours_override(monkeypatch):
    monkeypatch.setenv("JAEGERAI_REPO_URL",
                       "https://github.com/someone/fork.git")
    assert M._jaegerai_repo_slug() == "someone/fork"


def test_check_ecosystem_available_none_when_unreachable(monkeypatch):
    monkeypatch.setattr(M.version_check, "latest_version", lambda *a, **k: None)
    assert M.check_ecosystem_available() is None


def test_check_ecosystem_available_none_below_threshold(monkeypatch):
    monkeypatch.setattr(M.version_check, "latest_version", lambda *a, **k: "0.8.5")
    assert M.check_ecosystem_available() is None


def test_check_ecosystem_available_returns_tag_at_or_above_threshold(monkeypatch):
    monkeypatch.setattr(M.version_check, "latest_version", lambda *a, **k: "0.9.0")
    assert M.check_ecosystem_available() == "0.9.0"
    monkeypatch.setattr(M.version_check, "latest_version", lambda *a, **k: "0.10.2")
    assert M.check_ecosystem_available() == "0.10.2"


# ── already_migrated ──────────────────────────────────────────────────


def test_already_migrated_false_on_legacy_station(tmp_path):
    (tmp_path / "jaeger_os").mkdir()
    assert M.already_migrated(tmp_path) is False


def test_already_migrated_true_once_jaeger_ai_present(tmp_path):
    (tmp_path / "jaeger_ai").mkdir()
    assert M.already_migrated(tmp_path) is True


# ── extraction (reuses update_verb._extract_product with a different
#    allowlist) ───────────────────────────────────────────────────────


def _make_jaegerai_archive(tmp: Path, ref: str = "0.9.0") -> Path:
    src = tmp / "src" / f"JaegerAI-{ref}"
    (src / "jaeger_ai").mkdir(parents=True)
    (src / "jaeger_ai" / "__init__.py").write_text(f'__version__ = "{ref}"\n')
    (src / "requirements.txt").write_text(
        "jaeger-os @ git+https://github.com/JenkinsRobotics/JaegerOS@0.9.0\n")
    (src / "install.sh").write_text("#!/bin/bash\nset -euo pipefail\necho hi\n")
    (src / "jaeger").write_text("#!/bin/bash\nset -euo pipefail\necho hi\n")
    (src / "README.md").write_text("# JaegerAI\n")
    (src / "dev").mkdir()   # not in the allowlist — must be skipped
    (src / "dev" / "marker").write_text("x")
    tarball = tmp / "jaegerai.tar.gz"
    with tarfile.open(tarball, "w:gz") as tf:
        tf.add(src, arcname=f"JaegerAI-{ref}")
    return tarball


def test_extract_jaegerai_product_uses_its_own_allowlist(tmp_path):
    tarball = _make_jaegerai_archive(tmp_path)
    copied = M._extract_jaegerai_product(tarball, tmp_path / "staging")
    assert {"jaeger_ai", "requirements.txt", "install.sh", "jaeger",
            "README.md"} <= set(copied)
    assert "dev" not in copied
    assert (tmp_path / "staging" / "jaeger_ai" / "__init__.py").exists()
    assert not (tmp_path / "staging" / "dev").exists()


# ── the cross-product swap ────────────────────────────────────────────


def test_migrate_swap_stashes_full_old_manifest_and_places_new(tmp_path):
    """The critical case update_verb._swap_in CAN'T handle: 'jaeger_os' has
    no same-named counterpart in the new manifest, so a name-matched swap
    would silently strand it in home/. _migrate_swap must stash it anyway."""
    home = tmp_path / "home"
    (home / "jaeger_os").mkdir(parents=True)
    (home / "jaeger_os" / "__init__.py").write_text("OLD")
    (home / "requirements.txt").write_text("old-deps")
    (home / "install.sh").write_text("old installer")
    (home / ".venv").mkdir(); (home / ".venv" / "marker").write_text("venv")
    (home / ".jaeger_os").mkdir()
    (home / ".jaeger_os" / "instances").mkdir()
    inst = home / ".jaeger_os" / "instances" / "default"
    inst.mkdir()
    (inst / "manifest.json").write_text('{"instance_name": "default"}')

    staging = home / ".update-staging"
    (staging / "jaeger_ai").mkdir(parents=True)
    (staging / "jaeger_ai" / "__init__.py").write_text("NEW")
    (staging / "install.sh").write_text("new installer")
    prev = home / ".update-prev"

    stashed, placed = M._migrate_swap(
        home, staging, prev,
        old_items=U._PRODUCT, new_items=["jaeger_ai", "install.sh"])

    # old-only item (no same-named replacement) WAS stashed — the case
    # update_verb._swap_in structurally cannot handle.
    assert "jaeger_os" in stashed
    assert (prev / "jaeger_os" / "__init__.py").read_text() == "OLD"
    assert "requirements.txt" in stashed
    assert "install.sh" in stashed
    assert (prev / "install.sh").read_text() == "old installer"

    assert set(placed) == {"jaeger_ai", "install.sh"}
    assert (home / "jaeger_ai" / "__init__.py").read_text() == "NEW"
    assert (home / "install.sh").read_text() == "new installer"
    assert not (home / "jaeger_os").exists()   # moved out, not left behind

    # never touched
    assert (home / ".venv" / "marker").read_text() == "venv"
    assert (inst / "manifest.json").read_text() == '{"instance_name": "default"}'


def test_migrate_swap_then_do_rollback_restores_old_manifest_generically(tmp_path):
    """Proves the actual reuse claim: update_verb._do_rollback (UNCHANGED,
    generic — it just walks prev/) correctly reverses a cross-product
    swap it was never written to know about, because it identifies items
    by what's actually IN .update-prev/, not by name-matching against the
    current product.

    Known, documented gap (see migrate_verb's module docstring): a
    same-named-only-in-prev item like 'jaeger_ai' — never stashed, since
    it has no old-manifest counterpart — is left behind as harmless
    debris. This test pins that exact, understood behaviour rather than
    asserting a full clean revert _do_rollback structurally can't give us
    without a patch to JaegerAI's own (out-of-repo) copy."""
    home = tmp_path / "home"
    (home / "jaeger_os").mkdir(parents=True)
    (home / "jaeger_os" / "__init__.py").write_text("OLD")
    (home / "run.sh").write_text("old run.sh")
    staging = home / ".update-staging"
    (staging / "jaeger_ai").mkdir(parents=True)
    (staging / "jaeger_ai" / "__init__.py").write_text("NEW")
    prev = home / ".update-prev"

    M._migrate_swap(home, staging, prev,
                    old_items=("jaeger_os", "run.sh"), new_items=["jaeger_ai"])
    assert (home / "jaeger_ai").exists()
    assert not (home / "jaeger_os").exists()

    assert U._do_rollback(home) == 0
    assert (home / "jaeger_os" / "__init__.py").read_text() == "OLD"
    assert (home / "run.sh").read_text() == "old run.sh"
    assert (home / "jaeger_ai").exists()      # documented debris, not a bug
    assert not prev.exists()                  # consumed


def test_migrate_swap_is_retry_safe_over_rollback_debris(tmp_path):
    """A re-migration attempted after an imperfect rollback (jaeger_ai/
    debris still present, per the gap above) must not crash with
    ENOTEMPTY — _migrate_swap clears an existing same-named target
    before placing the freshly-staged one."""
    home = tmp_path / "home"
    (home / "jaeger_os").mkdir(parents=True)
    (home / "jaeger_os" / "__init__.py").write_text("OLD-AGAIN")
    (home / "jaeger_ai").mkdir()               # leftover debris, non-empty
    (home / "jaeger_ai" / "stale.py").write_text("STALE")
    staging = home / ".update-staging"
    (staging / "jaeger_ai").mkdir(parents=True)
    (staging / "jaeger_ai" / "__init__.py").write_text("FRESH")
    prev = home / ".update-prev"

    stashed, placed = M._migrate_swap(
        home, staging, prev, old_items=("jaeger_os",), new_items=["jaeger_ai"])
    assert placed == ["jaeger_ai"]
    assert (home / "jaeger_ai" / "__init__.py").read_text() == "FRESH"
    assert not (home / "jaeger_ai" / "stale.py").exists()   # debris cleared


# ── repo-url patch (works around JaegerAI 0.9.0's version_check bug) ──


def test_patch_repo_url_inserts_export_after_set_dash(tmp_path):
    (tmp_path / "jaeger").write_text("#!/bin/bash\nset -euo pipefail\necho hi\n")
    (tmp_path / "run.sh").write_text("#!/bin/bash\nset -euo pipefail\necho hi\n")
    M._patch_repo_url(tmp_path)
    for name in ("jaeger", "run.sh"):
        text = (tmp_path / name).read_text()
        assert 'export JAEGER_REPO_URL="https://github.com/JenkinsRobotics/JaegerAI.git"' in text
        lines = text.splitlines()
        assert lines[0] == "#!/bin/bash"
        assert lines[1] == "set -euo pipefail"
        assert "JAEGER_REPO_URL" in lines[2]


def test_patch_repo_url_idempotent(tmp_path):
    (tmp_path / "jaeger").write_text("#!/bin/bash\nset -euo pipefail\necho hi\n")
    M._patch_repo_url(tmp_path)
    once = (tmp_path / "jaeger").read_text()
    M._patch_repo_url(tmp_path)
    assert (tmp_path / "jaeger").read_text() == once


def test_patch_repo_url_skips_missing_files(tmp_path):
    M._patch_repo_url(tmp_path)   # no jaeger/run.sh present — must not raise


# ── run_ecosystem_migration orchestration ──────────────────────────────


def test_run_ecosystem_migration_aborts_when_archive_missing_jaeger_ai(
        tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(U, "_download_tarball", lambda repo, ref, dest: dest.write_bytes(b""))
    monkeypatch.setattr(M, "_extract_jaegerai_product", lambda tarball, staging: [])
    assert M.run_ecosystem_migration(home, ref="0.9.0") == 1
    assert "archive missing jaeger_ai" in capsys.readouterr().err


def test_run_ecosystem_migration_full_success(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    (home / "jaeger_os").mkdir(parents=True)
    (home / "jaeger_os" / "__init__.py").write_text("OLD")
    (home / ".venv").mkdir(); (home / ".venv" / "marker").write_text("v")
    (home / ".jaeger_os").mkdir()
    (home / ".jaeger_os" / "state.txt").write_text("precious")

    monkeypatch.setattr(U, "_download_tarball", lambda repo, ref, dest: dest.write_bytes(b""))

    def fake_extract(tarball, staging):
        (staging / "jaeger_ai").mkdir(parents=True)
        (staging / "jaeger_ai" / "__init__.py").write_text("NEW")
        (staging / "install.sh").write_text("#!/bin/bash\nexit 0\n")
        return ["jaeger_ai", "install.sh"]

    monkeypatch.setattr(M, "_extract_jaegerai_product", fake_extract)

    ran: list = []

    class _R:
        returncode = 0

    def fake_run(argv, **kwargs):
        ran.append(argv)
        return _R()

    monkeypatch.setattr(M.subprocess, "run", fake_run)

    rc = M.run_ecosystem_migration(home, ref="0.9.0")
    assert rc == 0
    assert (home / "jaeger_ai" / "__init__.py").read_text() == "NEW"
    assert not (home / "jaeger_os").exists()
    assert (home / ".update-prev" / "jaeger_os" / "__init__.py").read_text() == "OLD"
    assert not (home / ".venv").exists()   # removed for a fresh install
    assert ran == [["bash", str(home / "install.sh"), "--product"]]
    # .jaeger_os/ never named in any manifest -> untouched, still there
    assert (home / ".jaeger_os" / "state.txt").read_text() == "precious"
    out = capsys.readouterr().out
    assert "migrated to JaegerAI 0.9.0" in out


def test_run_ecosystem_migration_install_failure_leaves_rollback_hint(
        tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    (home / "jaeger_os").mkdir(parents=True)

    monkeypatch.setattr(U, "_download_tarball", lambda repo, ref, dest: dest.write_bytes(b""))

    def fake_extract(tarball, staging):
        (staging / "jaeger_ai").mkdir(parents=True)
        (staging / "install.sh").write_text("#!/bin/bash\nexit 1\n")
        return ["jaeger_ai", "install.sh"]

    monkeypatch.setattr(M, "_extract_jaegerai_product", fake_extract)

    class _R:
        returncode = 3

    monkeypatch.setattr(M.subprocess, "run", lambda *a, **k: _R())
    rc = M.run_ecosystem_migration(home, ref="0.9.0")
    assert rc == 3
    assert "rollback" in capsys.readouterr().err
