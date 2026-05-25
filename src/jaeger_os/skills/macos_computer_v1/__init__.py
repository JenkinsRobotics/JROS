"""macOS-native computer control — capability-ladder dispatch.

Public surface:

  * :func:`register` — the skill entry point. Wires
    ``computer_do`` / ``computer_use`` / ``computer_look`` onto the
    agent's tool registry. The skill loader calls this.
  * :func:`computer_do` / :func:`computer_use` / :func:`computer_look`
    — direct callable APIs for tests / non-skill-loader callers.

Implementation:

  * :mod:`.engines` — one module per capability tier (applescript,
    browser, ax, vision). Each implements the :class:`Engine`
    protocol; each can be tested in isolation.
  * :mod:`.planner` — step → engine selection + dispatch.
  * :mod:`.macos_computer` — agent-facing tool wrappers + register().

See ``SKILL.md`` for the design contract.
"""

from __future__ import annotations

from .macos_computer import (
    computer_do,
    computer_look,
    computer_use,
    register,
)

__all__ = ["computer_do", "computer_look", "computer_use", "register"]
