"""Interactive permission confirmation provider.

Regression cover for the `run_in_venv` bug: with no confirmation
provider wired, the policy defaults to ``DenyAllProvider`` and every
tier-1+ tool (run_in_venv, install_package, …) auto-fails with
"confirmation refused". The launcher now installs
``ConsoleConfirmationProvider``, which prompts an interactive user and
stays fail-safe (denies) on a non-interactive stdin.
"""

from __future__ import annotations

from jaeger_os.core.permissions import (
    ConsoleConfirmationProvider,
    PermissionGrants,
    PermissionPolicy,
    PermissionRequest,
    PermissionTier,
    current_policy,
    install_policy,
    use_policy,
)


def _req(skill: str = "packages", operation: str = "run_in_venv") -> PermissionRequest:
    return PermissionRequest(
        tier=PermissionTier.WRITE_LOCAL,
        skill=skill,
        operation=operation,
        summary="execute Python in the instance venv",
    )


def test_non_interactive_stdin_denies(monkeypatch):
    """No TTY (benchmarks, daemon, piped input) → deny without blocking
    on input(). Same effect as DenyAllProvider — no regression there."""
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert ConsoleConfirmationProvider().confirm(_req()) is False


def test_interactive_yes(monkeypatch):
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    assert ConsoleConfirmationProvider().confirm(_req()) is True


def test_interactive_no(monkeypatch):
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")
    assert ConsoleConfirmationProvider().confirm(_req()) is False


def test_yes_grants_the_skill_for_the_session(monkeypatch):
    """A plain 'yes' is per-SKILL, not per-call — the same skill never
    re-prompts this session. 'when i say yes its a yes.'"""
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    calls = {"n": 0}

    def _one_shot(_prompt: str = "") -> str:
        calls["n"] += 1
        return "y"

    monkeypatch.setattr("builtins.input", _one_shot)
    provider = ConsoleConfirmationProvider()
    assert provider.confirm(_req()) is True
    assert provider.confirm(_req()) is True  # no second prompt
    assert calls["n"] == 1


def test_a_different_skill_still_prompts(monkeypatch):
    """Granting one skill must NOT silently approve another — confirmation
    is per skill, so a fresh skill still asks."""
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    seen: list[str] = []

    def _record(prompt: str = "") -> str:
        seen.append(prompt)
        return "y"

    monkeypatch.setattr("builtins.input", _record)
    provider = ConsoleConfirmationProvider()
    assert provider.confirm(_req(skill="packages")) is True
    assert provider.confirm(_req(skill="computer_use")) is True
    assert len(seen) == 2  # both skills prompted


def test_always_persists_the_skill_grant(monkeypatch):
    """Answering 'always' (or 'allow…') remembers the skill — it is
    recorded in the grant store, not just the session."""
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _p="": "always")
    provider = ConsoleConfirmationProvider()
    assert provider.confirm(_req()) is True
    assert "packages" in provider._grants.persistent


# ── PermissionGrants — persistence ──────────────────────────────────


def test_grants_missing_file_is_empty(tmp_path):
    grants = PermissionGrants.load(tmp_path)
    assert grants.is_granted("computer_use") is False


def test_grants_persist_across_reload(tmp_path):
    """'always allow' survives a restart — the grant is written to
    <instance>/permissions.json and reloaded."""
    g1 = PermissionGrants.load(tmp_path)
    g1.grant_persistent("computer_use")
    assert (tmp_path / "permissions.json").exists()
    # A fresh load (a new boot) sees the grant.
    g2 = PermissionGrants.load(tmp_path)
    assert g2.is_granted("computer_use") is True


def test_session_grant_is_not_persisted(tmp_path):
    g1 = PermissionGrants.load(tmp_path)
    g1.grant_session("computer_use")
    assert g1.is_granted("computer_use") is True
    # session-only — a fresh boot does NOT see it.
    assert PermissionGrants.load(tmp_path).is_granted("computer_use") is False


def test_install_policy_makes_run_in_venv_reachable(monkeypatch):
    """End to end: with the interactive provider installed and the user
    approving, a WRITE_LOCAL request passes the policy check."""
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    with use_policy(PermissionPolicy(confirmation=ConsoleConfirmationProvider())):
        # check() raises if denied; returning None means allowed.
        assert current_policy().check(_req()) is None
