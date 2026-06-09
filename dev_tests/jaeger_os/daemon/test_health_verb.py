"""``jaeger health`` — operator-side runtime substrate probe.

Pairs with ``--doctor`` (which runs BEFORE boot for dep checks).
This verb runs the post-boot probe (memory store, sandbox, tool
registry, skills, drift parser) and exits 0/1 on the result.

Replaces the (now-removed) agent-callable ``system_health`` tool —
that surface caused prefill stalls on local Gemma checkpoints
because "do a self check" routed ambiguously across multiple
similarly-named tools. Operator-only via CLI sidesteps the
routing pathology entirely. Matches Hermes Agent's design
(``hermes doctor`` is operator-only; their agent has no self-test
tool).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from jaeger_os.daemon import health_verb


@pytest.fixture
def live_instance(tmp_path, monkeypatch):
    """Build a minimal instance the verb can bind to."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    monkeypatch.delenv("JAEGER_INSTANCE_NAME", raising=False)

    inst = tmp_path / ".jaeger_os" / "instances" / "default"
    inst.mkdir(parents=True)
    (inst / "memory").mkdir()
    (inst / "logs").mkdir()
    (inst / "credentials").mkdir()
    (inst / "skills").mkdir()
    (inst / "workspace").mkdir()
    (inst / "run").mkdir()
    (inst / "home").mkdir()
    (inst / "identity.yaml").write_text(
        "name: Test\nrole: r\npersonality: p\n", encoding="utf-8",
    )
    (inst / "config.yaml").write_text(
        "instance_name: default\nmodel:\n  model_path: x\n  ctx: 32768\n",
        encoding="utf-8",
    )
    (inst / "manifest.json").write_text(
        '{"instance_name":"default","schema_version":"1.2.0"}',
        encoding="utf-8",
    )
    return inst


# ── argument parsing ────────────────────────────────────────────


def test_health_help_returns_zero(capsys):
    rc = health_verb._cmd_health_argv(["-h"])
    err = capsys.readouterr().err
    assert rc == 0
    assert "jaeger health" in err
    assert "--deep" in err
    assert "--json" in err


def test_health_help_explains_doctor_vs_health(capsys):
    """The help text must make the doctor/health split discoverable —
    operators need to know which verb to reach for."""
    health_verb._cmd_health_argv(["-h"])
    err = capsys.readouterr().err
    assert "doctor" in err.lower()  # mentions the sister verb


# ── verb integration ────────────────────────────────────────────


def test_health_returns_zero_on_clean_instance(live_instance, capsys):
    """A freshly-built instance with all the right scaffolding
    should pass every probe and return rc=0."""
    rc = health_verb._cmd_health_argv([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "jaeger health" in out
    assert "passed" in out


def test_health_json_output_is_valid(live_instance, capsys):
    rc = health_verb._cmd_health_argv(["--json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert "ok" in payload
    assert "passed" in payload
    assert "total" in payload
    assert "checks" in payload
    assert isinstance(payload["checks"], list)


def test_health_reports_failures_with_nonzero_exit(live_instance, capsys, monkeypatch):
    """If the probe returns ok=False, exit code must be 1 — so
    scripts can ``jaeger health || alert`` cleanly."""
    def fake_run(deep=False):
        return {
            "ok": False, "passed": 6, "total": 8, "deep": deep,
            "elapsed_s": 0.1, "checks": [
                {"name": "layout", "ok": True, "detail": "ok"},
                {"name": "memory", "ok": False, "detail": "boom"},
            ],
        }
    from jaeger_os.core import diagnostics as diag
    monkeypatch.setattr(diag, "run_health_checks", fake_run)

    rc = health_verb._cmd_health_argv([])
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL" in out
    assert "memory" in out
    assert "boom" in out


def test_health_no_instance_returns_one(tmp_path, monkeypatch, capsys):
    """No instance on disk → bind fails → rc=1 with a useful message
    on stderr (not a stacktrace)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    monkeypatch.delenv("JAEGER_INSTANCE_NAME", raising=False)
    rc = health_verb._cmd_health_argv([])
    err = capsys.readouterr().err
    assert rc == 1
    assert "no instance" in err.lower() or "could not" in err.lower()


# ── dispatcher integration ───────────────────────────────────────


def test_cli_dispatcher_registers_health():
    """``jaeger health`` must be picked up by the daemon CLI
    dispatcher and route to the verb implementation."""
    from jaeger_os.daemon import cli
    assert "health" in cli.SUBCOMMANDS
    assert cli.is_daemon_subcommand(["health"]) is True
    assert cli.is_daemon_subcommand(["health", "--deep"]) is True


def test_dispatcher_calls_health_argv(monkeypatch):
    """End-to-end: ``cli.dispatch(['health', '--json'])`` should
    route to ``_cmd_health_argv(['--json'])``."""
    from jaeger_os.daemon import cli
    captured: list[list[str]] = []
    def fake_argv(argv):
        captured.append(argv)
        return 0
    monkeypatch.setattr(
        "jaeger_os.daemon.health_verb._cmd_health_argv", fake_argv,
    )
    cli.dispatch(["health", "--json"])
    assert captured == [["--json"]]
