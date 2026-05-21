"""TUI port — the new session-info slash commands.

`/status` `/statusbar` `/stop` `/save` were added in the prompt_toolkit
TUI port. The interactive input layer needs a real terminal, but these
command handlers are testable against a model-less JaegerTUI.
"""

from __future__ import annotations

import pytest
from rich.console import Console

from jaeger_os.interfaces.tui import slash_commands as slash
from jaeger_os.interfaces.tui.app import JaegerTUI


@pytest.fixture()
def ctx(tmp_path):
    tui = JaegerTUI(skip_model=True)
    return slash.SlashContext(
        console=Console(file=open("/dev/null", "w"), width=100),
        instance_dir=tmp_path,
        tui=tui,
    )


def test_new_commands_are_registered() -> None:
    for name in ("status", "statusbar", "stop", "save"):
        assert name in slash._BY_NAME, name


def test_statusbar_toggles_the_flag(ctx) -> None:
    ctx.tui._statusbar_on = True
    slash.dispatch("/statusbar", ctx)
    assert ctx.tui._statusbar_on is False
    slash.dispatch("/statusbar", ctx)
    assert ctx.tui._statusbar_on is True


def test_status_runs_clean(ctx) -> None:
    assert slash.dispatch("/status", ctx).quit is False


def test_stop_runs_clean_with_no_processes(ctx) -> None:
    # No tools bound / no processes — must not raise, just report.
    assert slash.dispatch("/stop", ctx).quit is False


def test_save_runs_clean(ctx) -> None:
    # Empty conversation — must not raise.
    assert slash.dispatch("/save", ctx).quit is False
