"""DB-8 — formal v1.1.0 → v1.2.0 migration script.

Verifies the SQLite cutover migration:

- Lazy importers fire on bind (facts.json → SQL, etc.)
- Legacy JSON/JSONL files get renamed to ``.legacy`` once their
  SQL counterparts are populated
- audit.log is preserved in place (canonical forensic record)
- The migration is idempotent — re-running is a silent no-op
- The runner bumps manifest.core_version 1.1.0 → 1.2.0
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jaeger_os.core.memory import memory as mem
from jaeger_os.core.memory import sqlite_store
from jaeger_os.migrations import v1_1_0_to_v1_2_0 as mig


@pytest.fixture(autouse=True)
def _isolate_store():
    sqlite_store.close()
    yield
    sqlite_store.close()


def _make_layout(tmp_path: Path) -> SimpleNamespace:
    mem_dir = tmp_path / "memory"
    logs_dir = tmp_path / "logs"
    mem_dir.mkdir(parents=True)
    logs_dir.mkdir(parents=True)
    return SimpleNamespace(
        memory_dir=mem_dir,
        logs_dir=logs_dir,
        audit_log_path=logs_dir / "audit.log",
    )


# ── facts.json migration ─────────────────────────────────────────


def test_migrate_imports_facts_json(tmp_path):
    layout = _make_layout(tmp_path)
    (layout.memory_dir / "facts.json").write_text(
        json.dumps({"name": "jaeger", "tz": "UTC"}),
        encoding="utf-8",
    )

    mig.migrate(layout)

    # SQL has the rows.
    assert mem.recall("name") == "jaeger"
    assert mem.recall("tz") == "UTC"
    # JSON renamed to .legacy.
    assert not (layout.memory_dir / "facts.json").exists()
    assert (layout.memory_dir / "facts.json.legacy").exists()


def test_migrate_leaves_empty_facts_json_alone(tmp_path):
    """If the source has nothing useful, don't rename — there's
    nothing to verify."""
    layout = _make_layout(tmp_path)
    (layout.memory_dir / "facts.json").write_text("{}", encoding="utf-8")

    mig.migrate(layout)
    # No rename — source still in place.
    assert (layout.memory_dir / "facts.json").exists()
    assert not (layout.memory_dir / "facts.json.legacy").exists()


# ── episodic.jsonl migration ─────────────────────────────────────


def test_migrate_imports_episodic_jsonl(tmp_path):
    layout = _make_layout(tmp_path)
    with (layout.memory_dir / "episodic.jsonl").open("w") as fh:
        fh.write(json.dumps({"user": "q1", "decision_raw": "a1",
                             "session_key": "default"}) + "\n")
        fh.write(json.dumps({"user": "q2", "decision_raw": "a2",
                             "session_key": "default"}) + "\n")

    mig.migrate(layout)

    turns = mem.load_recent_turns(10)
    assert [m["content"] for m in turns if m["role"] == "user"] == ["q1", "q2"]
    assert (layout.memory_dir / "episodic.jsonl.legacy").exists()
    assert not (layout.memory_dir / "episodic.jsonl").exists()


def test_migrate_renames_embeddings_cache(tmp_path):
    """Old NPZ embedding cache is replaced by the
    ``episodic_embeddings`` table — rename it aside too."""
    layout = _make_layout(tmp_path)
    with (layout.memory_dir / "episodic.jsonl").open("w") as fh:
        fh.write(json.dumps({"user": "q", "decision_raw": "a",
                             "session_key": "default"}) + "\n")
    (layout.memory_dir / "episodic.embeddings.npz").write_bytes(b"fake npz")

    mig.migrate(layout)
    assert (layout.memory_dir / "episodic.embeddings.npz.legacy").exists()
    assert not (layout.memory_dir / "episodic.embeddings.npz").exists()


# ── schedules.jsonl migration ────────────────────────────────────


def test_migrate_imports_schedules_jsonl(tmp_path):
    layout = _make_layout(tmp_path)
    with (layout.memory_dir / "schedules.jsonl").open("w") as fh:
        fh.write(json.dumps({
            "name": "every_minute",
            "cron": "* * * * *",
            "prompt": "ping",
            "created_at": "2026-01-01T00:00:00+00:00",
            "next_run_at": "2026-01-01T00:01:00+00:00",
            "last_run_at": None,
            "cancelled": False,
        }) + "\n")

    mig.migrate(layout)

    rows = mem.list_schedules()
    assert len(rows) == 1
    assert rows[0]["name"] == "every_minute"
    assert (layout.memory_dir / "schedules.jsonl.legacy").exists()


# ── audit.log handling ───────────────────────────────────────────


def test_migrate_imports_audit_log_but_keeps_file(tmp_path):
    """audit.log stays in place — canonical forensic record."""
    layout = _make_layout(tmp_path)
    with layout.audit_log_path.open("w") as fh:
        fh.write(json.dumps({
            "ts": "2026-01-01T00:00:00+00:00",
            "event": "file_write",
            "path": "x.py",
        }) + "\n")

    mig.migrate(layout)

    rows = mem.list_audit_events()
    assert len(rows) == 1
    assert rows[0]["event"] == "file_write"
    # Critical: audit.log NOT renamed — it's the canonical record.
    assert layout.audit_log_path.exists()
    assert not (layout.audit_log_path.with_name("audit.log.legacy")).exists()


# ── idempotence ──────────────────────────────────────────────────


def test_migrate_is_idempotent(tmp_path):
    """Running twice is a silent no-op — the lazy importers
    short-circuit on populated tables, and the rename short-circuits
    when the source is already moved."""
    layout = _make_layout(tmp_path)
    (layout.memory_dir / "facts.json").write_text(
        json.dumps({"k": "v"}), encoding="utf-8",
    )
    with (layout.memory_dir / "episodic.jsonl").open("w") as fh:
        fh.write(json.dumps({"user": "q", "decision_raw": "a",
                             "session_key": "default"}) + "\n")

    mig.migrate(layout)
    sqlite_store.close()  # simulate process restart
    mig.migrate(layout)  # should not crash, should not duplicate

    assert mem.recall("k") == "v"
    rows = mem.load_recent_turns(10)
    assert [m["content"] for m in rows if m["role"] == "user"] == ["q"]


def test_migrate_handles_missing_legacy_files(tmp_path):
    """A fresh 0.2.0 instance has no JSON/JSONL files at all —
    migration should still complete without error."""
    layout = _make_layout(tmp_path)
    mig.migrate(layout)  # must not raise
    # Tables exist but are empty.
    conn = sqlite_store.connection()
    assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 0


def test_migrate_does_not_clobber_existing_legacy_backup(tmp_path):
    """If a previous partial migration left a ``.legacy`` backup,
    don't overwrite it."""
    layout = _make_layout(tmp_path)
    (layout.memory_dir / "facts.json").write_text(
        json.dumps({"new": "data"}), encoding="utf-8",
    )
    (layout.memory_dir / "facts.json.legacy").write_text(
        "previous-backup", encoding="utf-8",
    )

    mig.migrate(layout)
    # Previous backup preserved (didn't get overwritten).
    assert (
        (layout.memory_dir / "facts.json.legacy").read_text(encoding="utf-8")
        == "previous-backup"
    )
    # But the new facts.json should still be in place — we don't
    # rename when the target already exists.
    assert (layout.memory_dir / "facts.json").exists()


# ── runner integration: manifest bump ────────────────────────────


def test_migrate_via_runner_bumps_manifest_to_1_2_0(monkeypatch, tmp_path):
    """End-to-end: the discovery runner picks up v1_1_0_to_v1_2_0
    and bumps the manifest from 1.1.0 → 1.2.0."""
    from jaeger_os.core.instance.instance import InstanceLayout
    from jaeger_os.core.instance.migrations import run_pending_migrations
    from jaeger_os.core.instance.schemas import Manifest, dump_json
    from datetime import datetime, timezone

    # Set up a minimal instance at 1.1.0 with a populated facts.json
    inst = tmp_path / "instance"
    (inst / "memory").mkdir(parents=True)
    (inst / "logs").mkdir(parents=True)
    (inst / "credentials").mkdir(parents=True)
    (inst / "skills").mkdir(parents=True)
    (inst / "workspace").mkdir(parents=True)
    (inst / "run").mkdir(parents=True)
    (inst / "home").mkdir(parents=True)
    (inst / "memory" / "facts.json").write_text(
        json.dumps({"k": "v"}), encoding="utf-8",
    )
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    dump_json(
        inst / "manifest.json",
        Manifest(
            instance_name="testinst",
            core_version="1.1.0",
            created_at=now,
        ),
    )
    # Need identity.yaml + config.yaml present for v1_0_0_to_v1_1_0
    # to be skipped — but our manifest is already at 1.1.0 so the
    # runner won't try to run v1_0_0_to_v1_1_0 anyway.
    layout = InstanceLayout(root=inst)

    applied = run_pending_migrations(layout)
    assert "v1_1_0_to_v1_2_0" in applied

    manifest_after = json.loads(
        layout.manifest_path.read_text(encoding="utf-8")
    )
    assert manifest_after["core_version"] == "1.2.0"
    # SQL store populated.
    assert mem.recall("k") == "v"
