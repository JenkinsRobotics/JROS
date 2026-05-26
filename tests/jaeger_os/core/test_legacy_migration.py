"""INST-8 — legacy layout migration.

The 0.1.0 → 0.2.0 step moves ``~/.jaeger/<name>/`` (flat) into
``~/.jaeger/instances/<name>/`` (nested). The bootstrap that does
the move lives in ``core/instance/legacy_migrations.py``; tests
here pin the contract: idempotent, backed up, safe on collisions,
no-op on a clean machine.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from jaeger_os.core.instance import legacy_migrations as L


def _make_legacy_instance(home: Path, name: str, *,
                          memory: bool = True,
                          extra: dict[str, str] | None = None) -> Path:
    """Build a minimal 0.1.0-shaped instance dir for tests."""
    root = home / ".jaeger" / name
    root.mkdir(parents=True)
    (root / "identity.yaml").write_text(f"name: {name}\n", encoding="utf-8")
    (root / "config.yaml").write_text("ctx: 32768\n", encoding="utf-8")
    (root / "manifest.json").write_text(
        '{"instance_name":"%s","core_version":"1.0.0"}' % name,
        encoding="utf-8",
    )
    if memory:
        (root / "memory").mkdir()
        (root / "memory" / "facts.json").write_text("{}", encoding="utf-8")
    if extra:
        for rel, body in extra.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
    return root


# ── discovery ───────────────────────────────────────────────────────


def test_discover_finds_legacy_instances(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    _make_legacy_instance(tmp_path, "default")
    _make_legacy_instance(tmp_path, "work")
    discovered = L.discover_legacy_instances()
    names = sorted(p.name for p in discovered)
    assert names == ["default", "work"]


def test_discover_skips_reserved_top_names(monkeypatch, tmp_path):
    """``instances/``, ``backups/``, ``active_instance``, ``jaeger.env``
    are NEVER legacy instances — must be excluded even if (somehow)
    they contain an identity.yaml."""
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / ".jaeger"
    root.mkdir()
    (root / "instances").mkdir()
    (root / "instances" / "identity.yaml").write_text("nope", encoding="utf-8")
    (root / "backups").mkdir()
    (root / "backups" / "identity.yaml").write_text("nope", encoding="utf-8")
    (root / "active_instance").write_text("default", encoding="utf-8")
    (root / "jaeger.env").write_text("export X=Y", encoding="utf-8")
    # And one real legacy instance to confirm discovery still works.
    _make_legacy_instance(tmp_path, "default")
    discovered = L.discover_legacy_instances()
    assert [p.name for p in discovered] == ["default"]


def test_discover_skips_dirs_without_identity(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / ".jaeger"
    root.mkdir()
    # A directory without identity.yaml is NOT a legacy instance.
    (root / "random_dir").mkdir()
    (root / "random_dir" / "note.txt").write_text("hello", encoding="utf-8")
    assert L.discover_legacy_instances() == []


def test_discover_empty_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    # No ~/.jaeger at all.
    assert L.discover_legacy_instances() == []


# ── migration ───────────────────────────────────────────────────────


def test_migrate_moves_instances_under_instances_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    _make_legacy_instance(tmp_path, "default")
    _make_legacy_instance(tmp_path, "work")
    buf = io.StringIO()
    report = L.migrate_legacy_layout(write_stdout=buf)
    assert set(report["moved"]) == {"default", "work"}
    assert report["noop"] is False
    # Old paths gone.
    assert not (tmp_path / ".jaeger" / "default").exists()
    assert not (tmp_path / ".jaeger" / "work").exists()
    # New paths populated with the same content.
    assert (tmp_path / ".jaeger" / "instances" / "default" / "identity.yaml").exists()
    assert (tmp_path / ".jaeger" / "instances" / "work" / "config.yaml").exists()


def test_migrate_writes_backup_zip(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    _make_legacy_instance(tmp_path, "default")
    report = L.migrate_legacy_layout(write_stdout=io.StringIO())
    backup = report["backup"]
    assert backup is not None
    assert Path(backup).exists()
    assert Path(backup).suffix == ".zip"
    # The archive contains the legacy instance's identity.yaml so
    # the user can recover even if the move went sideways.
    with zipfile.ZipFile(backup) as zf:
        names = zf.namelist()
    assert any("default/identity.yaml" in n for n in names)


def test_migrate_is_idempotent(monkeypatch, tmp_path):
    """Re-running on the same machine after the move is done: no-op,
    no second backup, no errors."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _make_legacy_instance(tmp_path, "default")
    L.migrate_legacy_layout(write_stdout=io.StringIO())
    report2 = L.migrate_legacy_layout(write_stdout=io.StringIO())
    assert report2["moved"] == []
    assert report2["noop"] is True
    assert report2["backup"] is None


def test_migrate_skips_collisions(monkeypatch, tmp_path):
    """If both the legacy and nested paths exist (a partial earlier
    migration?), the migrator skips that name and records why."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _make_legacy_instance(tmp_path, "default")
    # Pre-existing destination.
    (tmp_path / ".jaeger" / "instances" / "default").mkdir(parents=True)
    (tmp_path / ".jaeger" / "instances" / "default" / "marker").write_text(
        "i was here first", encoding="utf-8",
    )
    report = L.migrate_legacy_layout(write_stdout=io.StringIO())
    assert "default" not in report["moved"]
    skipped_names = [n for n, _ in report["skipped"]]
    assert "default" in skipped_names
    # The pre-existing marker survives.
    assert (tmp_path / ".jaeger" / "instances" / "default" / "marker").read_text() \
        == "i was here first"
    # The legacy dir survives too (not deleted).
    assert (tmp_path / ".jaeger" / "default" / "identity.yaml").exists()


def test_migrate_handles_extra_files(monkeypatch, tmp_path):
    """Skills, credentials, logs — all the substructure travels along."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _make_legacy_instance(tmp_path, "default", extra={
        "skills/my_skill_v1/SKILL.md": "# my skill",
        "credentials/external_model_api_key": "sk-abc",
        "logs/audit.log": '{"ts": "x"}\n',
    })
    L.migrate_legacy_layout(write_stdout=io.StringIO())
    moved = tmp_path / ".jaeger" / "instances" / "default"
    assert (moved / "skills" / "my_skill_v1" / "SKILL.md").read_text() == "# my skill"
    assert (moved / "credentials" / "external_model_api_key").read_text() == "sk-abc"
    assert (moved / "logs" / "audit.log").exists()


# ── manifest bump via the per-instance migration runner ─────────────


def test_manifest_bump_via_migration_runner(monkeypatch, tmp_path):
    """After legacy-layout migration moves the instance, the regular
    runner's ``v1_0_0_to_v1_1_0.py`` migration should bump the
    manifest. End-to-end sanity check."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _make_legacy_instance(tmp_path, "default")
    # 1. Layout move (pre-resolver).
    L.migrate_legacy_layout(write_stdout=io.StringIO())

    # 2. Now the resolver works, and run_pending_migrations on the
    # nested instance bumps the manifest.
    from jaeger_os.core.instance.instance import (
        InstanceLayout, resolve_instance_dir,
    )
    from jaeger_os.core.instance.migrations import run_pending_migrations

    layout = InstanceLayout(root=resolve_instance_dir("default"))
    assert layout.exists()

    applied = run_pending_migrations(layout)
    assert "v1_0_0_to_v1_1_0" in applied

    # Manifest now records 1.1.0.
    import json
    manifest = json.loads(layout.manifest_path.read_text(encoding="utf-8"))
    assert manifest["core_version"] == "1.1.0"
