"""Per-tool / per-turn tool-result budgeting and history pruning.

A single tool return can be large enough to blow the local model's context —
a terminal dump, a screenshot, a huge run_python stdout. ``TurnResultBudget``
persists an oversized payload to a file and leaves a compact preview in
context; ``compact_history`` prunes bulky payloads out of old messages so a
long session does not carry every past result at full fidelity.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from jaeger_os.core.tool_result_budget import (
    _KEEP_RECENT_MESSAGES,
    BudgetConfig,
    TurnResultBudget,
    _generate_preview,
    _serialize,
    budget_from_env,
    compact_history,
)
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)


def _budget(tmp_path, **cfg) -> TurnResultBudget:
    return TurnResultBudget(SimpleNamespace(memory_dir=tmp_path), BudgetConfig(**cfg))


# ── TurnResultBudget ─────────────────────────────────────────────────


def test_small_result_passes_through_unchanged(tmp_path):
    budget = _budget(tmp_path, per_tool_cap=1000)
    content = {"ok": True, "data": "short"}
    assert budget.process(content, "calculate", "c1") is content


def test_oversized_result_is_persisted_and_previewed(tmp_path):
    budget = _budget(tmp_path, per_tool_cap=100, per_turn_budget=10_000,
                     preview_chars=50)
    out = budget.process({"output": "A" * 5000}, "terminal", "call_99")
    assert out["truncated"] is True
    assert out["tool"] == "terminal"
    assert out["original_chars"] > 5000
    assert len(out["preview"]) <= 50
    assert "stored_at" in out
    # the full payload is preserved on disk
    full = Path(out["stored_at"]).read_text(encoding="utf-8")
    assert "A" * 5000 in full


def test_per_turn_budget_caps_after_aggregate_exceeded(tmp_path):
    """A result under the per-tool cap is still capped once the turn's
    aggregate has blown the per-turn budget."""
    budget = _budget(tmp_path, per_tool_cap=10_000, per_turn_budget=300,
                     preview_chars=50)
    first = {"data": "B" * 400}
    assert budget.process(first, "t", "c1") is first  # under per-tool cap
    second = {"data": "C" * 400}
    out = budget.process(second, "t", "c2")  # turn budget now blown
    assert out["truncated"] is True


def test_persist_failure_still_returns_a_preview(tmp_path):
    """When the result cannot be written to disk, the model still gets a
    preview — just without a stored_at path."""
    bad = tmp_path / "not_a_dir"
    bad.write_text("x", encoding="utf-8")  # memory_dir is a file → mkdir fails
    budget = TurnResultBudget(SimpleNamespace(memory_dir=bad),
                              BudgetConfig(per_tool_cap=100, preview_chars=50))
    out = budget.process({"output": "Z" * 5000}, "t", "c1")
    assert out["truncated"] is True
    assert "stored_at" not in out
    assert len(out["preview"]) <= 50


def test_budget_from_env_honours_overrides(monkeypatch):
    monkeypatch.setenv("JAEGER_TOOL_RESULT_CAP", "5000")
    monkeypatch.setenv("JAEGER_TURN_RESULT_BUDGET", "9000")
    cfg = budget_from_env()
    assert cfg.per_tool_cap == 5000
    assert cfg.per_turn_budget == 9000


# ── helpers ──────────────────────────────────────────────────────────


def test_serialize_renders_a_dict_as_json():
    assert '"a"' in _serialize({"a": 1})
    assert _serialize("plain string") == "plain string"


def test_generate_preview_trims_to_a_line_boundary():
    text = "line one\n" + "x" * 1000
    out = _generate_preview(text, 100)
    assert len(out) <= 100
    assert _generate_preview("short", 100) == "short"


# ── compact_history ──────────────────────────────────────────────────


def _call(args: dict) -> ModelResponse:
    return ModelResponse(parts=[
        ToolCallPart(tool_name="file_write", args=args, tool_call_id="c1"),
    ])


def _return(content) -> ModelRequest:
    return ModelRequest(parts=[
        ToolReturnPart(tool_name="file_read", content=content, tool_call_id="c1"),
    ])


def test_compact_history_truncates_old_tool_call_args():
    old = _call({"path": "x.py", "content": "Z" * 5000})
    history = [old] + [_return({"ok": True}) for _ in range(_KEEP_RECENT_MESSAGES + 1)]
    pruned = compact_history(history)
    assert pruned >= 1
    truncated = history[0].parts[0].args["content"]
    assert len(truncated) < 5000
    assert "pruned" in truncated


def test_compact_history_prunes_old_large_tool_returns():
    old = _return({"data": "Q" * 5000})
    history = [old] + [_return({"ok": True}) for _ in range(_KEEP_RECENT_MESSAGES + 1)]
    compact_history(history)
    assert history[0].parts[0].content.get("pruned") is True


def test_compact_history_leaves_recent_messages_at_full_fidelity():
    recent = _call({"content": "Z" * 5000})
    history = [_return({"ok": True}) for _ in range(2)] + [recent]
    compact_history(history)
    assert len(history[-1].parts[0].args["content"]) == 5000


def test_compact_history_is_a_noop_for_short_history():
    assert compact_history([_return({"ok": True})]) == 0
