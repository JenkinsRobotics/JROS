"""Agent-callable self-bench — cases, scoring, runner integration.

The bench corpus is a flat list of :class:`BenchCase` rows that the
agent runs against the LIVE pipeline via the ``run_benchmark`` tool.
This file pins the contract that:

  * every case is tagged, scorable, and parseable
  * the runner correctly handles multi-turn sessions
  * tag / id / limit filters do what they say
  * the umbrella-tool equivalence keeps consolidated-tool calls
    from showing as routing failures
  * the summary roll-up captures what the agent will quote back
"""

from __future__ import annotations

import types

import pytest

from jaeger_os.core.bench import BenchCase, summarise
from jaeger_os.core.bench.cases import CASES, UMBRELLA_EQUIVALENTS, all_tags
from jaeger_os.core.bench.runner import (
    BenchRow,
    _contains_all,
    _contains_any,
    _filter_cases,
    _matches_tool_set,
    _score,
)


# ── corpus shape ───────────────────────────────────────────────────


def test_every_case_has_a_unique_id():
    """IDs are the user-facing handle for re-running a single failure
    (`run_benchmark(ids="...")`) — duplicates would route both rows to
    the same retry."""
    ids = [c.id for c in CASES]
    dupes = {x for x in ids if ids.count(x) > 1}
    assert not dupes, f"duplicate bench case ids: {sorted(dupes)}"


def test_every_case_has_at_least_one_tag():
    """Untagged cases can't be filtered. Force a tag at authoring time."""
    for c in CASES:
        assert c.tags, f"case {c.id!r} has no tags"


def test_known_tag_set_covers_every_case():
    """all_tags() should equal the set we union from every case — a
    typo'd tag in a case ('rounting') would be silently filtered out."""
    declared = all_tags()
    rebuilt: set[str] = set()
    for c in CASES:
        rebuilt.update(c.tags)
    assert declared == rebuilt


def test_multiturn_cases_share_a_non_empty_session():
    """A case tagged ``multiturn`` only makes sense as part of a
    session; an empty session key would give it isolated history and
    defeat the test."""
    for c in CASES:
        if "multiturn" in c.tags:
            assert c.session, f"multiturn case {c.id!r} has no session key"


# ── matchers ────────────────────────────────────────────────────────


def test_matches_tool_set_unordered_full_match():
    assert _matches_tool_set(["a", "b", "c"], ["a", "b"], ordered=False)


def test_matches_tool_set_unordered_missing():
    assert not _matches_tool_set(["a", "c"], ["a", "b"], ordered=False)


def test_matches_tool_set_ordered_subsequence():
    """Ordered = subsequence (not necessarily contiguous)."""
    assert _matches_tool_set(["x", "a", "y", "b"], ["a", "b"], ordered=True)
    assert not _matches_tool_set(["b", "a"], ["a", "b"], ordered=True)


def test_matches_tool_set_accepts_umbrella_equivalent():
    """A model calling ``memory`` for an expected ``remember`` is
    routing correctly to the consolidated tool — the bench must not
    punish that."""
    assert "memory" in UMBRELLA_EQUIVALENTS["remember"]
    assert _matches_tool_set(["memory"], ["remember"], ordered=False)
    assert _matches_tool_set(["memory"], ["remember"], ordered=True)


def test_contains_any_and_all_are_case_insensitive():
    assert _contains_any("Hello WORLD", ["world"])
    assert _contains_all("Buy milk, walk dog", ["BUY MILK", "WALK DOG"])
    assert not _contains_any("nothing here", ["xyz"])


# ── scoring ─────────────────────────────────────────────────────────


def _case(**kwargs) -> BenchCase:
    return BenchCase(id="t", prompt="p", **kwargs)


def test_score_passes_with_no_checks():
    """A case with no assertions still passes when there's no error
    and nothing hallucinated."""
    row = _score(_case(), tools=[], answer="ok", error=None, elapsed_s=0.1)
    assert row.case_pass is True
    assert row.routing_ok is None
    assert row.answer_ok is None


def test_score_fails_on_missing_expected_tool():
    row = _score(_case(expected_tools=["calculate"]),
                 tools=["get_time"], answer="", error=None, elapsed_s=0.1)
    assert row.routing_ok is False
    assert row.case_pass is False


def test_score_fails_on_hallucination_signal():
    """Even if everything else passes, an answer that triggers a
    hallucination signal flips the case to fail."""
    row = _score(_case(hallucination_signals=["the answer is 0"]),
                 tools=[], answer="The answer is 0, exactly.",
                 error=None, elapsed_s=0.1)
    assert row.no_hallucination is False
    assert row.case_pass is False


def test_score_passes_on_answer_contains_all_match():
    row = _score(_case(answer_contains_all=["seattle", "raining"]),
                 tools=[], answer="It's raining in SEATTLE today.",
                 error=None, elapsed_s=0.1)
    assert row.answer_ok is True
    assert row.case_pass is True


def test_score_fails_when_tool_raised():
    row = _score(_case(), tools=[], answer="",
                 error="RuntimeError: boom", elapsed_s=0.1)
    assert row.case_pass is False


# ── filtering ──────────────────────────────────────────────────────


def _corpus() -> list[BenchCase]:
    return [
        BenchCase(id="a", prompt="x", tags=["routing"]),
        BenchCase(id="b", prompt="x", tags=["multistep"]),
        BenchCase(id="c1", prompt="x", session="conv", tags=["multiturn"]),
        BenchCase(id="c2", prompt="x", session="conv", tags=["multiturn"]),
        BenchCase(id="d", prompt="x", tags=["recovery"]),
    ]


def test_filter_by_tag():
    out = _filter_cases(_corpus(), tags=["routing"], ids=None, limit=None)
    assert [c.id for c in out] == ["a"]


def test_filter_by_id():
    out = _filter_cases(_corpus(), tags=None, ids=["a", "d"], limit=None)
    assert {c.id for c in out} == {"a", "d"}


def test_filter_preserves_full_multiturn_session():
    """Picking just c1 by id pulls c2 along — otherwise turn 2 would
    run against fresh history and meaningless context."""
    out = _filter_cases(_corpus(), tags=None, ids=["c1"], limit=None)
    assert [c.id for c in out] == ["c1", "c2"]


def test_filter_limit_clips_after_filtering():
    out = _filter_cases(_corpus(), tags=None, ids=None, limit=2)
    assert len(out) == 2
    assert [c.id for c in out] == ["a", "b"]


def test_filter_unknown_tag_returns_empty():
    out = _filter_cases(_corpus(), tags=["nope"], ids=None, limit=None)
    assert out == []


# ── summarise ──────────────────────────────────────────────────────


def _row(id_: str, *, pass_: bool, tags: list[str] | None = None,
         routing_ok: bool | None = True,
         answer_ok: bool | None = True) -> BenchRow:
    return BenchRow(
        id=id_, prompt="p", tags=tags or ["routing"],
        tools_called=["calculate"], answer="a", elapsed_s=0.1,
        routing_ok=routing_ok, ordered_ok=None, answer_ok=answer_ok,
        no_hallucination=True, error=None, case_pass=pass_,
    )


def test_summarise_topline_counts():
    s = summarise([_row("a", pass_=True), _row("b", pass_=False)])
    assert s["total"] == 2
    assert s["passed"] == 1
    assert s["pass_rate"] == 0.5
    assert len(s["failures"]) == 1
    assert s["failures"][0]["id"] == "b"


def test_summarise_per_tag_breakdown():
    rows = [
        _row("a", pass_=True, tags=["routing", "memory"]),
        _row("b", pass_=False, tags=["routing"]),
        _row("c", pass_=True, tags=["memory"]),
    ]
    s = summarise(rows)
    assert s["by_tag"]["routing"] == {"total": 2, "passed": 1}
    assert s["by_tag"]["memory"] == {"total": 2, "passed": 2}


def test_summarise_empty_rows_does_not_crash():
    s = summarise([])
    assert s["total"] == 0
    assert s["pass_rate"] == 0.0
    assert s["failures"] == []
