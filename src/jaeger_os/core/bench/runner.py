"""Flat bench runner — drives every case through the live agent loop.

The bench runs IN-PROCESS against the same model the agent is currently
using. That means:

  * the system prompt the model sees is the real one
  * the lean surface is the real one
  * the drift parser, dispatch, tier checks all fire
  * answers come back through the real finalizer

Re-entrancy note: this module is called FROM a tool dispatch inside
``drive_one_turn``. The outer turn acquired ``_pipeline['llm_lock']``,
but ``drive_one_turn`` itself doesn't re-acquire — it just calls the
adapter, which calls the model. Each bench case builds a FRESH
``JaegerAgent`` against the same client (separate message history,
shared LLM), so there's no nested lock contention.

Multi-turn handling: cases sharing a ``session`` key reuse the same
``JaegerAgent`` instance, so the prior turn's tool calls + answer
are in history when the next turn fires — same as a real
conversation. Cases without a ``session`` key get a unique session
per case (single-turn purity).
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
import time
from contextlib import redirect_stdout
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .cases import BenchCase, CASES, UMBRELLA_EQUIVALENTS


@dataclass
class BenchRow:
    """One bench case's result. Mirrors the legacy TurnRow shape for
    the per-case fields, but the pass/fail booleans are pre-computed
    so the renderer is a dumb projection."""

    id: str
    prompt: str
    tags: list[str]
    tools_called: list[str]
    answer: str
    elapsed_s: float
    routing_ok: bool | None      # None ⇒ no expected_tools to check
    ordered_ok: bool | None      # None ⇒ ordered=False
    answer_ok: bool | None       # None ⇒ no answer_contains_* set
    no_hallucination: bool       # True when none of hallucination_signals fired
    error: str | None
    case_pass: bool              # rolls up every applicable check


# ── Helpers ─────────────────────────────────────────────────────────


def _matches_tool_set(observed: list[str], expected: list[str],
                      *, ordered: bool) -> bool:
    """Set-match (or ordered subsequence) with umbrella-tool tolerance.

    Umbrella tolerance: a corpus expecting ``remember`` accepts a model
    that called ``memory`` (the umbrella). Without this we'd punish the
    model for routing correctly to the consolidated tool — the corpus
    intentionally uses the pre-consolidation names so historical
    baselines stay comparable."""
    if not expected:
        return True
    def _hit(name: str, observed: list[str]) -> bool:
        if name in observed:
            return True
        return any(eq in observed for eq in UMBRELLA_EQUIVALENTS.get(name, set()))
    if not ordered:
        return all(_hit(name, observed) for name in expected)
    # Ordered: observed must contain expected as a subsequence (umbrella
    # equivalents count as a match for that step).
    expected_iter = iter(expected)
    want = next(expected_iter, None)
    if want is None:
        return True
    for tool in observed:
        equivalents = {want} | UMBRELLA_EQUIVALENTS.get(want, set())
        if tool in equivalents:
            want = next(expected_iter, None)
            if want is None:
                return True
    return False


def _contains_any(haystack: str, needles: list[str]) -> bool:
    if not needles:
        return True
    lower = (haystack or "").lower()
    return any(n.lower() in lower for n in needles)


def _contains_all(haystack: str, needles: list[str]) -> bool:
    if not needles:
        return True
    lower = (haystack or "").lower()
    return all(n.lower() in lower for n in needles)


# ── Live-pipeline turn driver ──────────────────────────────────────


def _drive_one(client: Any, prompt: str, *,
               agent_cache: dict[str, Any],
               session_key: str) -> tuple[list[str], str, float, str | None]:
    """Run one turn through a session-bound :class:`JaegerAgent`. Returns
    ``(tools_called, answer, elapsed_s, error)``."""
    from jaeger_os.agent.loop.runtime_bridge import (
        build_jaeger_agent, drive_one_turn,
    )
    from jaeger_os.main import SKIP_FINAL_TOOLS, _get_agent, _pipeline

    if session_key not in agent_cache:
        _get_agent(client)  # mirror tools onto the registry
        _cfg = _pipeline.get("config")
        _ctx = getattr(getattr(_cfg, "model", None), "ctx", None)
        _layout = _pipeline.get("layout")
        _artifact_dir = (
            (_layout.logs_dir / "tool_results") if _layout is not None else None
        )
        agent_cache[session_key] = build_jaeger_agent(
            client,
            system_prompt=_pipeline.get("system_prompt", ""),
            toolsets=_pipeline.get("toolsets"),
            skip_final_tools=SKIP_FINAL_TOOLS,
            ctx_window=_ctx,
            artifact_dir=_artifact_dir,
        )
    jaeger_agent = agent_cache[session_key]

    started = time.perf_counter()
    error: str | None = None
    out: dict[str, Any] = {}
    try:
        # Devnull-redirect so the bench's nested turns don't spam the
        # live agent's stdout. The model's own progress is captured in
        # the returned dict.
        with open(os.devnull, "w") as devnull, redirect_stdout(devnull):
            out = drive_one_turn(jaeger_agent, prompt)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started

    tools: list[str] = []
    for msg in (out.get("new_messages") or []):
        if msg.get("role") != "assistant":
            continue
        for tc in (msg.get("tool_calls") or []):
            name = tc.get("name") or ""
            if name:
                tools.append(name)

    answer = out.get("answer", "") or ""
    return tools, answer, elapsed, error


# ── Scoring ─────────────────────────────────────────────────────────


def _score(case: BenchCase, tools: list[str], answer: str,
           error: str | None, elapsed_s: float) -> BenchRow:
    """Apply each of the case's optional checks; roll up to ``case_pass``."""
    routing_ok: bool | None = None
    ordered_ok: bool | None = None
    if case.expected_tools:
        routing_ok = _matches_tool_set(tools, case.expected_tools, ordered=False)
        if case.ordered:
            ordered_ok = _matches_tool_set(tools, case.expected_tools, ordered=True)

    answer_ok: bool | None = None
    if case.answer_contains_any or case.answer_contains_all:
        any_ok = _contains_any(answer, case.answer_contains_any) \
            if case.answer_contains_any else True
        all_ok = _contains_all(answer, case.answer_contains_all) \
            if case.answer_contains_all else True
        answer_ok = bool(any_ok and all_ok)

    lower = (answer or "").lower()
    no_hallucination = not any(
        s.lower() in lower for s in case.hallucination_signals
    )

    pieces: list[bool] = [no_hallucination, error is None]
    if routing_ok is not None:
        pieces.append(routing_ok)
    if ordered_ok is not None:
        pieces.append(ordered_ok)
    if answer_ok is not None:
        pieces.append(answer_ok)
    case_pass = all(pieces)

    return BenchRow(
        id=case.id, prompt=case.prompt, tags=list(case.tags),
        tools_called=tools, answer=answer, elapsed_s=round(elapsed_s, 3),
        routing_ok=routing_ok, ordered_ok=ordered_ok, answer_ok=answer_ok,
        no_hallucination=no_hallucination, error=error, case_pass=case_pass,
    )


# ── Filtering / running ─────────────────────────────────────────────


def _filter_cases(cases: list[BenchCase], *,
                  tags: list[str] | None,
                  ids: list[str] | None,
                  limit: int | None) -> list[BenchCase]:
    """Filter the corpus down to what the caller asked for. Multi-turn
    sessions are kept WHOLE — if any of a session's rows match the
    filter, every row in that session is included (otherwise turn 2
    would fail because turn 1's history is gone)."""
    sel = list(cases)
    if tags:
        wanted = {t.lower() for t in tags}
        sel = [c for c in sel if wanted.intersection({t.lower() for t in c.tags})]
    if ids:
        sel = [c for c in sel if c.id in set(ids)]
    if sel and sel != cases:
        # Re-include any rows that share a session with a selected row
        # but didn't themselves match the filter.
        selected_sessions = {c.session for c in sel if c.session}
        if selected_sessions:
            for c in cases:
                if c.session in selected_sessions and c not in sel:
                    sel.append(c)
            # Preserve original corpus order so multi-turn rows stay
            # in turn order.
            order = {id(c): i for i, c in enumerate(cases)}
            sel.sort(key=lambda c: order.get(id(c), 1 << 30))
    if limit is not None and limit > 0:
        sel = sel[:limit]
    return sel


# ── Hermetic mode — snapshot + restore mutable instance state ──────


# Files the bench writes to: facts.json (memory verbs), board.json
# (kanban / deepthink), schedules.json (cron), episodic.jsonl
# (every turn append). Snapshotting these around a run gives us
# 90% of the value of a full tmp-instance hermetic mode at 5% of
# the complexity: the user's live memory is untouched.
_MUTABLE_MEMORY_FILES: tuple[str, ...] = (
    "facts.json",
    "board.json",
    "schedules.json",
    "episodic.jsonl",
)


@contextlib.contextmanager
def _hermetic_memory(layout: Any) -> Iterator[None]:
    """Snapshot the mutable memory files on entry; restore them on
    exit. Any bench-driven writes between are invisible to the user's
    live state after the ``with`` block.

    Best-effort throughout — if a snapshot or restore fails (no
    permission, disk full, etc.) we log and let the run continue.
    The alternative — refusing to run the bench because we can't
    guarantee perfect isolation — would be worse for the operator
    who just wants the routing number.

    Layout duck-type: anything with a ``memory_dir`` attribute that
    points at a real directory works. Tests can pass a tmp-path
    ``SimpleNamespace``."""
    memory_dir = Path(getattr(layout, "memory_dir", "") or "")
    if not memory_dir or not memory_dir.is_dir():
        # No layout / no memory dir → run un-snapshotted. The bench
        # cases that don't touch persistent state still work fine.
        yield
        return

    snapshot_dir = Path(tempfile.mkdtemp(prefix=".bench_snapshot_",
                                         dir=str(memory_dir)))
    saved: dict[str, Path] = {}
    try:
        for name in _MUTABLE_MEMORY_FILES:
            src = memory_dir / name
            if src.is_file():
                dst = snapshot_dir / name
                try:
                    shutil.copy2(src, dst)
                    saved[name] = dst
                except OSError:
                    # Couldn't snapshot this one — log mentally,
                    # carry on. The post-restore step will skip it.
                    pass
        yield
    finally:
        # Restore: copy each snapshotted file back. If snapshot was
        # missing (file didn't exist pre-run) AND the bench created
        # it, remove the bench-created file so the live state stays
        # at "absent".
        for name in _MUTABLE_MEMORY_FILES:
            live = memory_dir / name
            backup = saved.get(name)
            if backup is not None and backup.is_file():
                try:
                    shutil.copy2(backup, live)
                except OSError:
                    pass
            elif live.is_file():
                # File didn't exist pre-bench; the bench created it.
                # Remove so the user's instance returns to its
                # pre-bench shape exactly.
                try:
                    live.unlink()
                except OSError:
                    pass
        try:
            shutil.rmtree(snapshot_dir, ignore_errors=True)
        except OSError:
            pass


def run_bench(
    client: Any,
    *,
    cases: list[BenchCase] | None = None,
    tags: list[str] | None = None,
    ids: list[str] | None = None,
    limit: int | None = None,
    progress: Any = None,
    hermetic: bool = True,
) -> list[BenchRow]:
    """Run the flat bench against ``client`` and return one
    :class:`BenchRow` per case.

    ``progress`` (optional callable) is invoked as
    ``progress(idx, total, case_id, passed, elapsed_s)`` after every
    case — useful for surfacing live progress in the tool result or
    on the TUI status line.

    ``hermetic=True`` (default) snapshots the live instance's
    mutable memory files (``facts.json`` / ``board.json`` /
    ``schedules.json`` / ``episodic.jsonl``) before the run and
    restores them after. This kills the contamination that made
    ``creds_list`` / ``schedule_list`` style cases fail against an
    instance with prior state — the bench reads "what does it
    look like RIGHT NOW with no bleed from earlier sessions" and
    the operator's live memory is untouched after the run finishes.
    Pass ``hermetic=False`` for legacy behaviour (bench writes
    persist; rarely useful)."""
    corpus = cases if cases is not None else CASES
    selected = _filter_cases(corpus, tags=tags, ids=ids, limit=limit)
    rows: list[BenchRow] = []
    agent_cache: dict[str, Any] = {}
    cleanup_queue: list[tuple[str, str]] = []  # (session, prompt)

    # Look up the live layout for the hermetic snapshot. If the
    # client wasn't booted via the standard pipeline (raw test
    # fixture, etc.) we just run un-snapshotted.
    snapshot_ctx: contextlib.AbstractContextManager[Any] = contextlib.nullcontext()
    if hermetic:
        try:
            from jaeger_os.main import _pipeline
            layout = _pipeline.get("layout")
            if layout is not None:
                snapshot_ctx = _hermetic_memory(layout)
        except Exception:  # noqa: BLE001 — snapshot is opt-in convenience
            pass

    with snapshot_ctx:
        for idx, case in enumerate(selected):
            session_key = case.session or f"bench_{case.id}"
            tools, answer, elapsed, error = _drive_one(
                client, case.prompt,
                agent_cache=agent_cache, session_key=session_key,
            )
            row = _score(case, tools, answer, error, elapsed)
            rows.append(row)
            for cleanup_prompt in (case.cleanup_after or []):
                cleanup_queue.append((f"{session_key}_cleanup", cleanup_prompt))
            if callable(progress):
                try:
                    progress(idx, len(selected), case.id, row.case_pass,
                             row.elapsed_s)
                except Exception:  # noqa: BLE001 — progress hook never breaks bench
                    pass

        # Best-effort cleanup of any state cases left behind. Failures
        # are ignored — the next run will overwrite anyway.
        for session_key, cleanup_prompt in cleanup_queue:
            try:
                _drive_one(client, cleanup_prompt,
                           agent_cache=agent_cache, session_key=session_key)
            except Exception:  # noqa: BLE001
                pass
    return rows


# ── Summarising ────────────────────────────────────────────────────


# Named suites the bench rolls up against. Each suite is a tag-filter
# over the corpus plus a pass-rate threshold the report grades against.
# Reporting in suites (rather than just topline) keeps regressions
# legible: "routing 22/25, multistep 7/9, recovery 5/9" tells the
# operator which category dropped — a flat "44/57" hides it.
#
# Thresholds are advisory — the bench still reports the raw pass count.
# Tune them per-model in a follow-up once we have data; current values
# are conservative ballparks based on the gemma-4-E4B baseline.
SUITES: dict[str, dict[str, Any]] = {
    "smoke":     {"tags": {"routing"}, "limit": 5,  "threshold": 0.80,
                  "blurb": "5-case sanity check; routing only"},
    "routing":   {"tags": {"routing"},          "threshold": 0.85,
                  "blurb": "single-turn, single-tool dispatch"},
    "multistep": {"tags": {"multistep"},        "threshold": 0.65,
                  "blurb": "single-turn, multiple-tool chaining"},
    "multiturn": {"tags": {"multiturn"},        "threshold": 0.70,
                  "blurb": "multi-turn conversations with carried history"},
    "recovery":  {"tags": {"recovery"},         "threshold": 0.60,
                  "blurb": "failure surface + anti-hallucination"},
    "full":      {"tags": None,                 "threshold": 0.70,
                  "blurb": "every case in the corpus"},
}


def _suite_rows(rows: list[BenchRow], suite_name: str) -> list[BenchRow]:
    """Filter ``rows`` to the cases that belong to ``suite_name``. The
    ``smoke`` suite additionally clips to ``limit`` cases so the
    summary stays honest about what was actually exercised."""
    spec = SUITES.get(suite_name)
    if spec is None:
        return []
    tags = spec.get("tags")
    if tags is None:
        out = list(rows)
    else:
        out = [r for r in rows if tags.intersection(r.tags)]
    limit = spec.get("limit")
    if limit:
        out = out[:int(limit)]
    return out


def summarise(rows: list[BenchRow]) -> dict[str, Any]:
    """Reduce a list of bench rows into a single dict the agent (or a
    rendering layer) can format. Keeps individual rows under ``rows``
    for drill-down while exposing the topline counts AND a per-suite
    breakdown — a flat "97% pass rate" hides which category regressed,
    so we publish "routing 22/25, multistep 7/9, recovery 5/9" too."""
    total = len(rows)
    passed = sum(1 for r in rows if r.case_pass)
    routing_checked = [r for r in rows if r.routing_ok is not None]
    answer_checked = [r for r in rows if r.answer_ok is not None]
    errors = sum(1 for r in rows if r.error)
    total_elapsed = sum(r.elapsed_s for r in rows)

    by_tag: dict[str, dict[str, int]] = {}
    for r in rows:
        for tag in r.tags:
            slot = by_tag.setdefault(tag, {"total": 0, "passed": 0})
            slot["total"] += 1
            if r.case_pass:
                slot["passed"] += 1

    # Per-suite roll-up — grades against each suite's advisory
    # threshold so the report says "routing FAIL (passed below 0.85)"
    # instead of just dumping counts.
    suites: dict[str, dict[str, Any]] = {}
    for name, spec in SUITES.items():
        suite_rows = _suite_rows(rows, name)
        if not suite_rows:
            continue
        s_total = len(suite_rows)
        s_passed = sum(1 for r in suite_rows if r.case_pass)
        rate = s_passed / s_total if s_total else 0.0
        threshold = float(spec.get("threshold", 0.0))
        suites[name] = {
            "total": s_total,
            "passed": s_passed,
            "pass_rate": round(rate, 3),
            "threshold": threshold,
            "meets_threshold": rate >= threshold,
            "blurb": spec.get("blurb", ""),
        }

    return {
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "routing_passed": sum(1 for r in routing_checked if r.routing_ok),
        "routing_total": len(routing_checked),
        "answer_passed": sum(1 for r in answer_checked if r.answer_ok),
        "answer_total": len(answer_checked),
        "errors": errors,
        "elapsed_s": round(total_elapsed, 2),
        "suites": suites,
        "by_tag": by_tag,
        "failures": [
            {"id": r.id, "prompt": r.prompt[:100],
             "tools_called": r.tools_called,
             "answer": (r.answer or "")[:200],
             "routing_ok": r.routing_ok, "answer_ok": r.answer_ok,
             "no_hallucination": r.no_hallucination, "error": r.error}
            for r in rows if not r.case_pass
        ],
        "rows": [asdict(r) for r in rows],
    }


__all__ = ["BenchRow", "run_bench", "summarise"]
