"""Per-tool and per-turn tool-result budgeting + history pruning.

A single tool can return a payload large enough to blow the local model's
context — a big terminal dump, a screenshot, a huge run_python stdout, an MCP
server's response. Jaeger's older caps are per-tool and piecemeal (web.py
truncates, search_files caps, file_read pages + dedups). This is the uniform
safety net:

* :class:`TurnResultBudget` — any tool return over a size cap is persisted to
  a file under the instance dir and replaced in context with a compact
  preview + the path; a per-turn aggregate budget catches a turn that
  accumulates many medium-sized results.
* :func:`compact_history` — prunes bulky payloads (oversized tool-call args,
  large old tool returns) out of OLD messages so a long session does not
  carry every past result at full fidelity.

Mirrors Hermes' tools/tool_result_storage.py + the result-pruning half of
agent/context_compressor.py, adapted to Jaeger: Jaeger tools return dicts
(not strings) and Jaeger writes to a real local instance dir, so persistence
is a direct file write — no sandbox-env abstraction.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic_ai.messages import ToolCallPart, ToolReturnPart


@dataclass(frozen=True)
class BudgetConfig:
    """Size limits, in characters of the serialized result."""

    per_tool_cap: int = 24_000       # a single result over this is persisted
    per_turn_budget: int = 120_000   # once a turn's results pass this, cap hard
    preview_chars: int = 2_000       # how much of an oversized result stays


DEFAULT_BUDGET = BudgetConfig()

# History pruning — applied only to messages older than the live turn.
_HISTORY_ARG_CAP = 600       # max chars kept per old tool-call arg string
_HISTORY_RESULT_CAP = 1_200  # max chars kept per old tool return
_KEEP_RECENT_MESSAGES = 6    # the most recent N messages are never pruned

# Keep the persisted-results dir from growing without bound.
_MAX_STORED_FILES = 64

# Keys marking a result dict this module has already shrunk.
_TRUNCATED_KEY = "truncated"  # set by TurnResultBudget.process
_PRUNED_KEY = "pruned"        # set by _truncate_tool_return


def budget_from_env() -> BudgetConfig:
    """A :class:`BudgetConfig` honouring ``JAEGER_TOOL_RESULT_CAP`` and
    ``JAEGER_TURN_RESULT_BUDGET`` env overrides, else the defaults."""
    def _env_int(name: str, default: int) -> int:
        raw = os.environ.get(name)
        if not raw:
            return default
        try:
            return max(500, int(raw))
        except ValueError:
            return default

    return BudgetConfig(
        per_tool_cap=_env_int("JAEGER_TOOL_RESULT_CAP", DEFAULT_BUDGET.per_tool_cap),
        per_turn_budget=_env_int("JAEGER_TURN_RESULT_BUDGET", DEFAULT_BUDGET.per_turn_budget),
        preview_chars=DEFAULT_BUDGET.preview_chars,
    )


def _serialize(content: Any) -> str:
    """A tool result as text, for sizing and persistence."""
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=True, default=str, indent=2)
    except (TypeError, ValueError):
        return str(content)


def _generate_preview(text: str, max_chars: int) -> str:
    """First ``max_chars`` of ``text``, trimmed back to a line boundary."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    newline = cut.rfind("\n")
    if newline > max_chars // 2:
        cut = cut[:newline]
    return cut


def _prune_storage_dir(results_dir: Path) -> None:
    """Keep at most ``_MAX_STORED_FILES`` persisted results, newest first."""
    try:
        files = sorted(
            results_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for stale in files[_MAX_STORED_FILES:]:
            stale.unlink(missing_ok=True)
    except OSError:
        pass


def _persist(text: str, tool_name: str, tool_call_id: str, results_dir: Path) -> str | None:
    """Write the full result to a file; return its path, or None on failure."""
    try:
        results_dir.mkdir(parents=True, exist_ok=True)
        safe_tool = "".join(c if c.isalnum() else "_" for c in tool_name)[:40] or "tool"
        stamp = (tool_call_id or uuid.uuid4().hex)[:32]
        path = results_dir / f"{safe_tool}_{stamp}.txt"
        path.write_text(text, encoding="utf-8")
        _prune_storage_dir(results_dir)
        return str(path)
    except OSError:
        return None


class TurnResultBudget:
    """Per-turn tool-result budgeter. Construct one per turn."""

    def __init__(self, layout: Any, config: BudgetConfig = DEFAULT_BUDGET) -> None:
        memory_dir = getattr(layout, "memory_dir", None)
        self._results_dir = (
            Path(memory_dir) / "large_results" if memory_dir is not None
            else Path("large_results")
        )
        self._config = config
        self._spent = 0
        self.persisted_count = 0

    def process(self, content: Any, tool_name: str, tool_call_id: str) -> Any:
        """Return ``content`` unchanged when it fits the budget, or a compact
        preview dict — full payload persisted to a file — when it does not."""
        text = _serialize(content)
        size = len(text)
        # Once the turn's aggregate is over budget, cap everything hard.
        over_turn = self._spent >= self._config.per_turn_budget
        cap = self._config.preview_chars if over_turn else self._config.per_tool_cap
        if size <= cap:
            self._spent += size
            return content
        preview = _generate_preview(text, self._config.preview_chars)
        stored_at = _persist(text, tool_name, tool_call_id, self._results_dir)
        self._spent += len(preview)
        self.persisted_count += 1
        capped: dict[str, Any] = {
            _TRUNCATED_KEY: True,
            "tool": tool_name,
            "original_chars": size,
            "preview": preview,
            "note": (
                "This result was too large for the context window. "
                + (f"The full output was saved to {stored_at} — read it with "
                   "file_read (offset/limit) if you need more. " if stored_at
                   else "")
                + "Work from the preview above; do not re-run the tool just "
                "to see the rest."
            ),
        }
        if stored_at:
            capped["stored_at"] = stored_at
        return capped


def _truncate_tool_args(part: ToolCallPart) -> bool:
    """Truncate oversized string values in an old tool call's args, in place."""
    args = getattr(part, "args", None)
    if not isinstance(args, dict):
        return False
    changed = False
    for key, value in args.items():
        if isinstance(value, str) and len(value) > _HISTORY_ARG_CAP:
            dropped = len(value) - _HISTORY_ARG_CAP
            args[key] = value[:_HISTORY_ARG_CAP] + f"… [+{dropped} chars pruned]"
            changed = True
    return changed


def _truncate_tool_return(part: ToolReturnPart) -> bool:
    """Replace an old tool return's bulky content with a short preview."""
    content = getattr(part, "content", None)
    if isinstance(content, dict) and (
        content.get(_TRUNCATED_KEY) or content.get(_PRUNED_KEY)
    ):
        return False  # already a budget-capped / pruned preview
    text = _serialize(content)
    if len(text) <= _HISTORY_RESULT_CAP:
        return False
    part.content = {
        _PRUNED_KEY: True,
        "preview": _generate_preview(text, _HISTORY_RESULT_CAP),
        "note": "Earlier tool result — pruned from history to save context.",
    }
    return True


def compact_history(history: list[Any]) -> int:
    """Prune bulky payloads from OLD messages in ``history``, in place.

    Returns the number of parts pruned. The most recent
    ``_KEEP_RECENT_MESSAGES`` messages are left at full fidelity so the live
    turn is never degraded.
    """
    if len(history) <= _KEEP_RECENT_MESSAGES:
        return 0
    pruned = 0
    for msg in history[:-_KEEP_RECENT_MESSAGES]:
        for part in getattr(msg, "parts", []) or []:
            if isinstance(part, ToolCallPart):
                if _truncate_tool_args(part):
                    pruned += 1
            elif isinstance(part, ToolReturnPart):
                if _truncate_tool_return(part):
                    pruned += 1
    return pruned
