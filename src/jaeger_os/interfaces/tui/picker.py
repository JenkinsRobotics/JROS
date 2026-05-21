"""Centered arrow-key picker for the TUI.

Interactive slash commands (``/model`` …) use this instead of making
the user type a name: a box centered in the terminal, a highlight bar,
↑/↓ to move, Enter to select, Esc to cancel. Built on prompt_toolkit's
``radiolist_dialog`` so it themes + scrolls for free.
"""

from __future__ import annotations

from typing import Any


def pick(
    title: str,
    options: list[tuple[Any, str]],
    *,
    text: str = "",
    default: Any = None,
) -> Any:
    """Show a centered single-select picker.

    ``options`` is ``[(value, label), …]``. ``default`` pre-selects a
    value (the highlight starts there). Returns the chosen value, or
    ``None`` if the user cancels (Esc) or a dialog can't be built (no
    TTY). Call it only when no other prompt is on screen — it runs its
    own prompt_toolkit application."""
    if not options:
        return None
    try:
        from prompt_toolkit.shortcuts import radiolist_dialog
        from prompt_toolkit.styles import Style
    except Exception:  # noqa: BLE001
        return None
    # Jaeger blue accent on the dialog frame + selection highlight.
    style = Style.from_dict({
        "dialog":             "bg:default",
        "dialog.body":        "bg:default",
        "dialog frame.label": "fg:ansibrightblue bold",
        "dialog.body radiolist": "bg:default",
        "radio-selected":     "fg:ansibrightblue bold",
        "radio-checked":      "fg:ansibrightblue bold",
        "button.focused":     "bg:ansibrightblue fg:ansiblack",
    })
    kwargs: dict[str, Any] = dict(
        title=title, text=text, values=options, style=style)
    if default is not None and any(v == default for v, _ in options):
        kwargs["default"] = default
    try:
        return radiolist_dialog(**kwargs).run()
    except Exception:  # noqa: BLE001
        return None
