"""Level 2 — multi-step single-turn.

Each prompt is a single user turn but requires the agent to chain
multiple tool calls to satisfy it. Tests whether the model decomposes
a request, picks the right tools in plausible order, and uses each
result as input to the next.

Scoring per row:
  - ``tool_set_ok``  — every expected tool was called (order optional)
  - ``ordered_ok``   — expected tools appear in the right order
  - ``answer_ok``    — final answer contains a required substring (when set)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ._runner import (
    TurnRow,
    answer_contains_all,
    matches_tool_set,
    md_table,
    run_turn,
    short,
)


# ── Test case shape ────────────────────────────────────────────────


@dataclass
class MultiStepCase:
    """One Level-2 prompt with multi-tool expectations."""

    name: str
    prompt: str
    expected_tools: list[str]           # set; every one must be called
    ordered: bool = False                # if True, also assert call order
    must_contain: list[str] = field(default_factory=list)  # AND across all
    cleanup_after: list[str] = field(default_factory=list)  # follow-up prompts run as new turns
    notes: str = ""


# ── Cases ──────────────────────────────────────────────────────────


CASES: list[MultiStepCase] = [
    MultiStepCase(
        name="write-and-run-fib",
        prompt=(
            "Write a python file called fib10.py in the skills/ directory "
            "that prints the first 10 Fibonacci numbers (0 through 34), "
            "then run it with run_python to confirm it works."
        ),
        expected_tools=["write_file", "run_python"],
        ordered=True,
        must_contain=["0", "1", "2", "3", "5", "8", "13", "21", "34"],
        cleanup_after=["delete fib10.py"],
        notes="Tests the canonical write→verify code workflow + Phase-2 syntax check.",
    ),
    MultiStepCase(
        name="time-then-weather",
        prompt="What time is it in Tokyo and what's the weather there?",
        expected_tools=["get_time", "get_weather"],
        ordered=False,
        must_contain=["tokyo"],
        notes="Two independent tool calls for one composite question.",
    ),
    MultiStepCase(
        name="calc-and-save",
        prompt=(
            "Calculate 47 times 23 plus 12, then save the result to math.txt."
        ),
        expected_tools=["calculate", "write_file"],
        ordered=True,
        must_contain=["1093"],
        cleanup_after=["delete math.txt"],
        notes="Tool composition: calculate output feeds into file_write.",
    ),
    MultiStepCase(
        name="remember-then-recall",
        prompt=(
            "Remember that my home town is Seattle, then immediately recall "
            "my home town to confirm it stuck."
        ),
        expected_tools=["remember", "recall"],
        ordered=True,
        must_contain=["seattle"],
        cleanup_after=["forget my home town"],
        notes="Memory write→read round trip in one turn.",
    ),
    MultiStepCase(
        name="list-and-count-py",
        prompt=(
            "List the workspace and tell me how many .py files are in it."
        ),
        expected_tools=["list_skill_dir"],
        ordered=False,
        must_contain=[],  # quality answer requires LLM to count from list
        notes="Tool call + LLM analysis of its result.",
    ),
    MultiStepCase(
        name="write-append-read",
        prompt=(
            "Create todo.txt with 'buy milk', append 'walk dog' to it, "
            "then read it back and tell me both items."
        ),
        expected_tools=["write_file", "append_file", "read_file"],
        ordered=True,
        must_contain=["buy milk", "walk dog"],
        cleanup_after=["delete todo.txt"],
        notes="Three-step file lifecycle in one turn.",
    ),
    MultiStepCase(
        name="search-then-summarize",
        prompt=(
            "Search the web for what jaeger tracing is, then explain it in "
            "one sentence using what you found."
        ),
        expected_tools=["web_search"],
        ordered=False,
        must_contain=["trac"],  # 'tracing' or 'trace' should appear
        notes="Web search + LLM synthesis (Tool Results rule).",
    ),
    MultiStepCase(
        name="schedule-list-cancel",
        prompt=(
            "Schedule a prompt with cron '0 9 * * *' named morning_demo "
            "that says hello, then list my schedules to confirm it's there, "
            "then cancel morning_demo."
        ),
        expected_tools=["schedule_prompt", "list_schedules", "cancel_schedule"],
        ordered=True,
        must_contain=["morning_demo"],
        notes="Scheduling lifecycle in one turn.",
    ),
    MultiStepCase(
        name="plugin-status-then-setup",
        prompt=(
            "What plugins do I have, and walk me through setting up discord "
            "if it isn't ready yet."
        ),
        expected_tools=["list_plugins", "setup_plugin"],
        ordered=True,
        must_contain=["discord"],
        notes="Plugin discovery + setup-guide flow.",
    ),
    MultiStepCase(
        name="calc-and-narrate",
        prompt="Calculate 2 to the power of 16 and speak the answer out loud.",
        expected_tools=["calculate", "text_to_speech"],
        ordered=True,
        must_contain=["65536"],
        notes="Compute + audio output composition.",
    ),
    MultiStepCase(
        name="write-syntax-error-fix-loop",
        prompt=(
            "Write a python file called broken.py with the line 'print(' "
            "(intentionally broken), then run it. If it fails, fix it to "
            "print 'hello' and run it again."
        ),
        expected_tools=["write_file", "run_python"],
        ordered=False,
        must_contain=["hello"],
        cleanup_after=["delete broken.py"],
        notes="Tests Phase-2 syntax check + Phase-3 fix-loop fired by run_python failure.",
    ),
    MultiStepCase(
        name="three-facts-then-summary",
        prompt=(
            "Remember three things about me: I'm a developer, I drink "
            "coffee daily, and I live in Seattle. Then list all my facts."
        ),
        expected_tools=["remember", "list_facts"],
        ordered=False,
        must_contain=["developer", "coffee", "seattle"],
        cleanup_after=[
            "forget that I'm a developer",
            "forget that I drink coffee daily",
            "forget that I live in Seattle",
        ],
        notes="Multiple remember calls + a final summary read.",
    ),
]


# ── Run ─────────────────────────────────────────────────────────────


def _cleanup(client: Any, prompts: list[str], session_key: str) -> None:
    """Best-effort cleanup so a Level-2 row leaves no instance state
    behind for the next row. Failures are silent — these are
    housekeeping, not assertions."""
    for cleanup_prompt in prompts:
        try:
            run_turn(client, cleanup_prompt, session_key=session_key)
        except Exception:
            pass


def run_level(client: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, case in enumerate(CASES):
        # Each case gets its own session so prior tool calls (remember /
        # file_write) don't influence routing for the next case.
        session = f"l2_{idx}_{case.name}"
        turn: TurnRow = run_turn(client, case.prompt, session_key=session)
        tool_set_ok = matches_tool_set(turn.tools_called, case.expected_tools, ordered=False)
        ordered_ok = matches_tool_set(turn.tools_called, case.expected_tools, ordered=True)
        answer_ok: bool | None = (
            answer_contains_all(turn.answer, case.must_contain)
            if case.must_contain else None
        )
        rows.append({
            "level": 2,
            "idx": idx,
            "name": case.name,
            "prompt": case.prompt,
            "expected_tools": case.expected_tools,
            "expected_ordered": case.ordered,
            "tools_called": turn.tools_called,
            "answer": turn.answer,
            "elapsed_s": turn.elapsed_s,
            "tool_set_ok": tool_set_ok,
            "ordered_ok": ordered_ok,
            "answer_ok": answer_ok,
            "error": turn.error,
        })
        ord_marker = "✓" if ordered_ok else "✗"
        print(
            f"  [L2 {idx:02d}] {case.name:32s} "
            f"set={'✓' if tool_set_ok else '✗'}  "
            f"order={ord_marker if case.ordered else '—'}  "
            f"ans={'✓' if answer_ok is True else ('✗' if answer_ok is False else '—')}  "
            f"{turn.elapsed_s:5.2f}s"
            + (f"  ERR: {turn.error}" if turn.error else ""),
            flush=True,
        )
        if case.cleanup_after:
            _cleanup(client, case.cleanup_after, session_key=f"{session}_cleanup")
    return rows


# ── Render ──────────────────────────────────────────────────────────


def render_markdown(rows: list[dict[str, Any]]) -> str:
    n = len(rows)
    set_ok = sum(1 for r in rows if r["tool_set_ok"])
    ord_required = [r for r in rows if r["expected_ordered"]]
    ord_ok = sum(1 for r in ord_required if r["ordered_ok"])
    ans_checked = [r for r in rows if r["answer_ok"] is not None]
    ans_ok = sum(1 for r in ans_checked if r["answer_ok"])
    errors = sum(1 for r in rows if r["error"])
    total = sum(r["elapsed_s"] for r in rows)

    lines = [
        "# Level 2 — multi-step single-turn",
        "",
        f"- {n} cases; tool-set **{set_ok}/{n}** "
        f"({100 * set_ok / n:.0f}%); "
        f"ordered **{ord_ok}/{len(ord_required)}** "
        f"(where order is required); "
        f"answer-check **{ans_ok}/{len(ans_checked)}**; "
        f"errors {errors}; total {total:.1f}s.",
        "",
        md_table(
            ["#", "Case", "Expected", "Called", "Set", "Order", "Ans", "Time"],
            [
                [
                    str(r["idx"]),
                    r["name"],
                    ", ".join(r["expected_tools"]),
                    ", ".join(r["tools_called"]) or "-",
                    "✓" if r["tool_set_ok"] else "✗",
                    ("✓" if r["ordered_ok"] else "✗") if r["expected_ordered"] else "—",
                    ("✓" if r["answer_ok"] is True
                     else "✗" if r["answer_ok"] is False else "—"),
                    f"{r['elapsed_s']:.2f}s",
                ]
                for r in rows
            ],
        ),
    ]
    return "\n".join(lines) + "\n"
