"""Kanban board agent tools.

The agent's task-planning surface — see docs/kanban_design.md.

  • board_view(column, tag)        — read the board
  • board_add(title, …)            — add a card to the `ready` column
  • board_move(card_id, column)    — move a card between columns
  • board_update(card_id, …)       — edit a card / log progress on it

The board is one JSON file inside the instance (``memory/board.json``);
these tools are local bookkeeping and are NOT confirmation-gated — the
same low-risk class as ``remember``. The one rule the tools enforce is
the approval gate: a card cannot be moved ``backlog → ready`` by the
agent — that is the user's approval step (``/board approve`` in the
TUI). Deep Think jobs live on this same board (``source="deepthink"``).
"""

from __future__ import annotations

from typing import Any

from ._common import _require_layout
from ..board import COLUMNS, board_for_layout
from ..permissions import PermissionTier, requires_tier


def _card_brief(card: Any) -> dict[str, Any]:
    """Compact card view for tool results."""
    out = {
        "id": card.id,
        "title": card.title,
        "column": card.column,
        "priority": card.priority,
        "source": card.source,
    }
    if card.tags:
        out["tags"] = card.tags
    if card.parent:
        out["parent"] = card.parent
    return out


@requires_tier(PermissionTier.READ_ONLY, skill="board", operation="board_view",
               summary="read the kanban board")
def board_view(column: str = "", tag: str = "") -> dict[str, Any]:
    """Read the kanban task board. Optionally filter by ``column``
    (backlog / ready / in_progress / blocked / done) or ``tag``.
    Use this to see what work is queued, in progress, or blocked."""
    board = board_for_layout(_require_layout())
    cards = board.list(column=column or None, tag=tag or None)
    return {
        "ok": True,
        "summary": board.summary(),
        "cards": [_card_brief(c) for c in cards],
    }


def board_add(
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    priority: str = "med",
) -> dict[str, Any]:
    """Add a card to the kanban board (lands in the ``ready`` column,
    ready to work). Use this to lay out a multi-step task as cards so
    you — and the user — can track it. ``priority`` is low / med / high."""
    clean = (title or "").strip()
    if not clean:
        return {"ok": False, "error": "empty card title"}
    board = board_for_layout(_require_layout())
    card = board.add(
        clean, column="ready", description=description,
        source="agent", created_by="agent",
        tags=tags or [], priority=priority,
    )
    return {"ok": True, "card_id": card.id, "title": card.title,
            "column": card.column}


def board_move(card_id: str, column: str) -> dict[str, Any]:
    """Move a card to another column — ``in_progress`` when you start
    it, ``done`` when finished, ``blocked`` when it needs the user.
    A card cannot be moved ``backlog → ready``: that is the user's
    approval step for proposed work (they run ``/board approve``)."""
    board = board_for_layout(_require_layout())
    card = board.get(card_id)
    if card is None:
        return {"ok": False, "error": f"no card {card_id!r}"}
    if column not in COLUMNS:
        return {"ok": False, "error": f"unknown column {column!r}; "
                f"use one of {', '.join(COLUMNS)}"}
    if card.column == "backlog" and column == "ready":
        return {
            "ok": False,
            "error": ("backlog → ready is the user's approval step — "
                      "ask them to approve it (/board approve "
                      f"{card_id})."),
        }
    moved = board.move(card_id, column)
    return {"ok": True, "card_id": card_id, "column": moved.column}


def board_update(
    card_id: str,
    title: str = "",
    description: str = "",
    priority: str = "",
    add_tag: str = "",
    note: str = "",
    result: str = "",
) -> dict[str, Any]:
    """Edit a card or log progress on it. ``note`` appends to the card's
    running log; ``result`` records the outcome; ``add_tag`` adds one
    tag. Empty arguments are left unchanged."""
    board = board_for_layout(_require_layout())
    card = board.get(card_id)
    if card is None:
        return {"ok": False, "error": f"no card {card_id!r}"}
    fields: dict[str, Any] = {}
    if title.strip():
        fields["title"] = title.strip()
    if description.strip():
        fields["description"] = description.strip()
    if priority.strip():
        fields["priority"] = priority.strip()
    if add_tag.strip() and add_tag.strip() not in card.tags:
        fields["tags"] = [*card.tags, add_tag.strip()]
    if note.strip():
        fields["notes"] = (card.notes + "\n" + note.strip()).strip()
    if result.strip():
        fields["result"] = result.strip()
    if not fields:
        return {"ok": False, "error": "nothing to update"}
    board.update(card_id, **fields)
    return {"ok": True, "card_id": card_id, "updated": sorted(fields)}


# ---------------------------------------------------------------------------
# Consolidated kanban tool — one tool, every board operation
# ---------------------------------------------------------------------------
def kanban(action: str, card_id: str = "", title: str = "",
           description: str = "", column: str = "", tag: str = "",
           priority: str = "", note: str = "") -> dict[str, Any]:
    """The kanban task board — ONE tool, action-dispatch. ``action``:

      - ``view``     — read the board (optional ``column`` / ``tag`` filter)
      - ``add``      — add a card: ``title`` (+ ``description`` / ``priority``
        low|med|high / ``tag``)
      - ``move``     — move card ``card_id`` to ``column``
      - ``update``   — edit / log on card ``card_id`` (``note`` appends a
        progress line)
      - ``complete`` — mark card ``card_id`` done
      - ``block``    — mark card ``card_id`` blocked (needs the user)
      - ``unblock``  — move a blocked card back to ready

    Columns: backlog / ready / in_progress / blocked / done. Lay a
    multi-step task out as cards so you and the user can track it."""
    act = (action or "").strip().lower()
    if act in ("view", "show", "list", "read"):
        return board_view(column=column, tag=tag)
    if act in ("add", "create", "new"):
        return board_add(title=title, description=description,
                         tags=[tag.strip()] if tag.strip() else None,
                         priority=priority or "med")
    if act == "move":
        if not column:
            return {"ok": False, "error": "move needs a target column"}
        return board_move(card_id=card_id, column=column)
    if act in ("update", "comment", "log", "edit"):
        return board_update(card_id=card_id, title=title,
                            description=description, priority=priority,
                            add_tag=tag, note=note)
    if act in ("complete", "done", "finish"):
        return board_move(card_id=card_id, column="done")
    if act == "block":
        return board_move(card_id=card_id, column="blocked")
    if act in ("unblock", "resume"):
        return board_move(card_id=card_id, column="ready")
    return {"ok": False,
            "error": f"unknown kanban action {action!r} — use one of: "
                     "view, add, move, update, complete, block, unblock"}
