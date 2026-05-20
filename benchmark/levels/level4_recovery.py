"""Level 4 — failure recovery + edge cases.

Each prompt is engineered to make ONE specific failure mode visible:
the underlying tool returns an error, the model emits malformed JSON,
the requested resource doesn't exist, etc. We then check whether the
agent **recovers gracefully** instead of silently succeeding or
crashing.

Scoring per row:
  - ``surfaced_error``  — final answer mentions the failure (no silent success)
  - ``recovered``        — fix-loop fired / fallback path used (for run_python
                           + web_search) and produced a usable answer
  - ``no_hallucination`` — model didn't fabricate (e.g. claim a tool doesn't
                           exist after calling it, or invent a file content)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ._runner import (
    TurnRow,
    answer_contains_any,
    md_table,
    run_turn,
    short,
)


@dataclass
class RecoveryCase:
    name: str
    prompt: str
    description: str
    # The agent's final answer must contain at least one of these
    # substrings (case-insensitive) to count as "surfaced". An empty
    # list means we don't check surfacing for this case.
    error_signals: list[str] = field(default_factory=list)
    # Phrases that, if present in the answer, indicate hallucination
    # (e.g. "I don't have a web tool" after a successful web_search).
    hallucination_signals: list[str] = field(default_factory=list)
    # If True, we additionally check that the agent made a SECOND tool
    # call (recovery / retry / fallback) — proves the agent didn't
    # just dump the first failure and quit.
    expects_retry: bool = False
    cleanup_after: list[str] = field(default_factory=list)


# ── Cases ──────────────────────────────────────────────────────────


CASES: list[RecoveryCase] = [
    RecoveryCase(
        name="run-python-syntax-error",
        prompt=(
            "Use run_python to execute this code (it has a syntax error on "
            "purpose): print(   — note the unclosed parenthesis. After it "
            "fails, tell me what went wrong."
        ),
        description="Bad syntax via run_python. Agent should surface the error, "
                    "not pretend the script worked.",
        error_signals=["syntax", "error", "fail", "broken", "invalid",
                       "couldn't", "could not", "unable", "unclosed"],
        hallucination_signals=["successfully", "hello world"],
        expects_retry=False,
    ),
    RecoveryCase(
        name="run-python-zero-division",
        prompt=(
            "Use run_python to evaluate the expression one divided by zero. "
            "After it fails, tell me what error name Python raised."
        ),
        description="Runtime error inside run_python. Agent should report "
                    "ZeroDivisionError.",
        error_signals=["zero", "division", "zerodivision", "error",
                       "couldn't", "could not", "unable"],
        hallucination_signals=["infinity", "undefined as math"],
    ),
    RecoveryCase(
        name="read-missing-file",
        prompt="Read a file called nonexistent_xyz_12345.txt and tell me what's inside.",
        description="file_read of a missing file. Agent should say it's missing, "
                    "not fabricate contents.",
        error_signals=["not found", "doesn't exist", "no such", "missing",
                       "couldn't find", "could not find", "unable to find",
                       "wasn't able", "isn't there"],
        hallucination_signals=["the file contains", "the file says"],
    ),
    RecoveryCase(
        name="delete-missing-file",
        prompt="Delete the file totally_not_a_real_file_8675309.txt.",
        description="delete_file of a missing path. Should report not-found, "
                    "not 'successfully deleted'.",
        error_signals=["not found", "doesn't exist", "no such", "missing",
                       "couldn't find", "could not find", "unable to find",
                       "wasn't able", "couldn't delete"],
        hallucination_signals=["deleted successfully", "removed it"],
    ),
    RecoveryCase(
        name="calculate-divbyzero",
        prompt="Calculate 12345 divided by 0.",
        description="calculate with a degenerate input. Should surface the "
                    "error gracefully (not crash, not invent a number).",
        error_signals=["zero", "undefined", "infinity", "cannot", "error",
                       "division", "infinite"],
        hallucination_signals=["the answer is 0", "the result is 12345"],
    ),
    RecoveryCase(
        name="write-and-fix-loop",
        prompt=(
            "Use file_write to create skills/fix_demo.py with this code: "
            "`def hello(:\\n    print('hi')`. The colon after the paren is a "
            "syntax error. After writing, run_python the file. If the run "
            "fails, fix the file (remove the colon) and run it again."
        ),
        description="Tests Phase-2 syntax surface + Phase-3 fix-loop. "
                    "Final answer must mention success or 'hi'.",
        error_signals=["fix", "syntax", "corrected", "hi"],
        hallucination_signals=[],
        expects_retry=True,
        cleanup_after=["delete fix_demo.py"],
    ),
    RecoveryCase(
        name="search-then-no-denial",
        prompt=(
            "Search the web for 'jaeger distributed tracing uber'. Use the "
            "result to tell me who built jaeger."
        ),
        description="Tests anti-hallucination rule: after web_search returns, "
                    "the model must NOT say 'I don't have a web tool'.",
        error_signals=[],
        hallucination_signals=[
            "don't have access",
            "don't have a web",
            "i can't search",
            "not able to search",
        ],
    ),
    RecoveryCase(
        name="weather-unknown-location",
        prompt="What's the weather in Atlantis_FakeCity_99999?",
        description="get_weather with a nonsense location. Should surface "
                    "the unknown-location error, not invent a forecast.",
        error_signals=["unknown", "not found", "couldn't", "could not",
                       "unable", "fail", "error", "sorry"],
        hallucination_signals=["sunny", "cloudy", "degrees fahrenheit"],
    ),
    RecoveryCase(
        name="recall-missing-key",
        prompt=(
            "Recall what my secret_password_xyz_9999 is. Tell me whether "
            "you actually have a value stored for it."
        ),
        description="recall for a never-set key. Should say 'no value' or "
                    "similar, not invent one.",
        error_signals=["no value", "not", "don't", "haven't", "missing",
                       "empty", "couldn't", "no record"],
        hallucination_signals=[
            "your password is",
            "the value is",
            "i remember",
        ],
    ),
    RecoveryCase(
        name="schedule-cancel-missing",
        prompt="Cancel the scheduled prompt named never_existed_demo_xyz.",
        description="cancel_schedule for a name that was never scheduled. "
                    "Should report 'no such schedule'.",
        error_signals=["no schedule", "not found", "doesn't exist",
                       "couldn't find", "could not find", "unable to find",
                       "no such", "wasn't able"],
        hallucination_signals=["cancelled successfully", "removed"],
    ),
]


# ── Run ─────────────────────────────────────────────────────────────


def _cleanup(client: Any, prompts: list[str], session_key: str) -> None:
    for cleanup_prompt in prompts:
        try:
            run_turn(client, cleanup_prompt, session_key=session_key)
        except Exception:
            pass


def run_level(client: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, case in enumerate(CASES):
        session = f"l4_{idx}_{case.name}"
        turn: TurnRow = run_turn(client, case.prompt, session_key=session)

        answer_lower = (turn.answer or "").lower()
        surfaced_error: bool | None = (
            answer_contains_any(turn.answer, case.error_signals)
            if case.error_signals else None
        )
        hallucinated = (
            any(s.lower() in answer_lower for s in case.hallucination_signals)
            if case.hallucination_signals else False
        )
        no_hallucination = not hallucinated
        recovered: bool | None = None
        if case.expects_retry:
            # Retry = at least one tool was called more than once, OR the
            # model called the SAME tool in two consecutive turns (fix-loop).
            recovered = len(turn.tools_called) > len(set(turn.tools_called)) \
                or turn.tools_called.count("run_python") >= 2 \
                or turn.tools_called.count("write_file") >= 2

        # Overall pass: surfaced (when expected) AND not hallucinated AND
        # recovered (when expected) AND no infra-level exception.
        pieces = [no_hallucination, turn.error is None]
        if surfaced_error is not None:
            pieces.append(surfaced_error)
        if recovered is not None:
            pieces.append(recovered)
        case_pass = all(pieces)

        rows.append({
            "level": 4,
            "idx": idx,
            "name": case.name,
            "description": case.description,
            "prompt": case.prompt,
            "tools_called": turn.tools_called,
            "answer": turn.answer,
            "elapsed_s": turn.elapsed_s,
            "surfaced_error": surfaced_error,
            "no_hallucination": no_hallucination,
            "recovered": recovered,
            "expects_retry": case.expects_retry,
            "case_pass": case_pass,
            "error": turn.error,
        })
        print(
            f"  [L4 {idx:02d}] {case.name:32s} "
            f"surf={'✓' if surfaced_error is True else ('✗' if surfaced_error is False else '—')}  "
            f"no-halluc={'✓' if no_hallucination else '✗'}  "
            f"recov={'✓' if recovered is True else ('✗' if recovered is False else '—')}  "
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
    passing = sum(1 for r in rows if r["case_pass"])
    surfaced = [r for r in rows if r["surfaced_error"] is not None]
    surfaced_ok = sum(1 for r in surfaced if r["surfaced_error"])
    no_halluc_ok = sum(1 for r in rows if r["no_hallucination"])
    recovery = [r for r in rows if r["recovered"] is not None]
    recovery_ok = sum(1 for r in recovery if r["recovered"])
    total = sum(r["elapsed_s"] for r in rows)

    lines = [
        "# Level 4 — failure recovery + edge cases",
        "",
        f"- {n} cases; overall passing **{passing}/{n}** "
        f"({100 * passing / n:.0f}%); "
        f"surfaced-error **{surfaced_ok}/{len(surfaced)}**; "
        f"no-hallucination **{no_halluc_ok}/{n}**; "
        f"recovered (where required) **{recovery_ok}/{len(recovery)}**; "
        f"total {total:.1f}s.",
        "",
        md_table(
            ["#", "Case", "Tools", "Surf", "No-hal", "Recov", "Ans (short)", "Time"],
            [
                [
                    str(r["idx"]),
                    r["name"],
                    ", ".join(r["tools_called"]) or "-",
                    ("✓" if r["surfaced_error"] is True
                     else "✗" if r["surfaced_error"] is False else "—"),
                    "✓" if r["no_hallucination"] else "✗",
                    ("✓" if r["recovered"] is True
                     else "✗" if r["recovered"] is False else "—"),
                    short(r["answer"], 60),
                    f"{r['elapsed_s']:.2f}s",
                ]
                for r in rows
            ],
        ),
    ]
    return "\n".join(lines) + "\n"
