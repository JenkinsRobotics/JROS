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
    PermissionPolicy,
    PermissionRequest,
    PermissionTier,
    current_policy,
    install_policy,
    use_policy,
)


def _req() -> PermissionRequest:
    return PermissionRequest(
        tier=PermissionTier.WRITE_LOCAL,
        skill="packages",
        operation="run_in_venv",
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


def test_allow_all_sticks(monkeypatch):
    """Answering 'a' approves and remembers — later requests this
    session auto-approve without re-prompting."""
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    calls = {"n": 0}

    def _one_shot(_prompt: str = "") -> str:
        calls["n"] += 1
        return "a"

    monkeypatch.setattr("builtins.input", _one_shot)
    provider = ConsoleConfirmationProvider()
    assert provider.confirm(_req()) is True
    assert provider.confirm(_req()) is True  # no second prompt
    assert calls["n"] == 1


def test_install_policy_makes_run_in_venv_reachable(monkeypatch):
    """End to end: with the interactive provider installed and the user
    approving, a WRITE_LOCAL request passes the policy check."""
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    with use_policy(PermissionPolicy(confirmation=ConsoleConfirmationProvider())):
        # check() raises if denied; returning None means allowed.
        assert current_policy().check(_req()) is None
