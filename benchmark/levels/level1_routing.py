"""Level 1 — single-turn tool routing.

The canonical "did the agent pick the right tool" bench. One prompt
per row; one expected tool; one optional answer assertion. This is
the floor — if Level 1 regresses, the model is mis-routing on the
easy stuff and higher levels won't trust the underlying signal.

Prompt set is the same 33-prompt list shipped in the legacy unified
bench so historical numbers compare directly to the new tiered run.
"""

from __future__ import annotations

from typing import Any

from ._runner import (
    TurnRow,
    answer_contains_any,
    matches_tool_set,
    md_table,
    run_turn,
    short,
)


# ── Prompt set ──────────────────────────────────────────────────────


# (prompt, expected_tool, answer_substrings)
#   expected_tool: tool the agent should call; None ⇒ free-text expected
#   answer_substrings: list of substrings, ANY of which is acceptable;
#                      empty list ⇒ no content check
PROMPTS: list[tuple[str, str | None, list[str]]] = [
    # ── Core routing
    ("what time is it",                                                              "get_time",          [":"]),
    ("what time is it in shanghai",                                                  "get_time",          [":", "shanghai", "china"]),
    ("calculate 47 times 23 plus 12",                                                "calculate",         ["1093"]),
    ("calculate the square root of 12345",                                           "calculate",         ["111.10", "111.108", "111.1"]),
    ("list the workspace",                                                           "list_skill_dir",    []),
    ("make a file called bench.txt with the message hello from the benchmark",       "write_file",        []),
    ("read bench.txt out loud",                                                      "text_to_speech",             []),
    ("search the web for recent news about local llms",                              "web_search",        []),
    ("what is the current weather in Seattle",                                       "get_weather",       []),
    ("tell me a one sentence story about a robot",                                   None,                ["robot"]),
    ("in three words, what is the capital of France",                                None,                ["paris"]),
    ("delete bench.txt",                                                             "delete_file",       []),
    ("what is the cpu and disk status of this machine",                              "system_status",     []),
    # ── YouTube workflow
    ("search the web for trending youtube topics about home robots",                 "web_search",        []),
    ("write a 4 sentence youtube intro script about a robot named Lilith discovering coffee and save it to youtube_intro.txt", "write_file", []),
    ("append a closing line to youtube_intro.txt asking viewers to subscribe",       "append_file",       []),
    ("narrate youtube_intro.txt out loud as if you are reading it for a youtube video", "text_to_speech",          []),
    ("come up with a catchy youtube title for a video about a robot vacuum gone rogue", None,             []),
    ("delete youtube_intro.txt",                                                     "delete_file",       []),
    # ── Memory cycle (youtube)
    ("remember that my preferred youtube video length is 90 seconds",                "remember",          []),
    ("what video length do I prefer?",                                               "recall",            ["90"]),
    ("what do you know about me?",                                                   "list_facts",        []),
    ("forget my video length preference",                                            "forget",            []),
    # ── Memory cycle (favorite color)
    ("remember that my favorite color is teal",                                      "remember",          []),
    ("what is my favorite color",                                                    "recall",            ["teal"]),
    # ── Extended coverage
    ("search your memory for anything we said about youtube",                        "search_memory",     []),
    ("run a python snippet that prints the first 8 fibonacci numbers",               "run_python",        ["0", "1", "2", "3", "5", "8", "13", "21"]),
    ("show me what tools you have available",                                        "help_me",           ["time", "math", "memory", "file", "web", "tool"]),
    ("list any credentials I have stored",                                           "list_credentials",  ["no credentials", "none", "empty", "[]"]),
    ("reload your skill registry",                                                   "reload_skills",     ["registered", "no new", "skill", "skipped"]),
    ("schedule a prompt with cron expression '0 9 * * *' named bench_test that says good morning", "schedule_prompt", ["bench_test", "scheduled", "next run"]),
    ("show me my scheduled prompts",                                                 "list_schedules",    ["bench_test"]),
    ("cancel the bench_test schedule",                                               "cancel_schedule",   ["bench_test", "cancel"]),
]


# ── Run ─────────────────────────────────────────────────────────────


def run_level(client: Any) -> list[dict[str, Any]]:
    """Run every Level-1 prompt. Each gets a UNIQUE session_key so
    memory/episodic state from one prompt doesn't leak into the next
    (single-turn purity)."""
    rows: list[dict[str, Any]] = []
    for idx, (prompt, expected_tool, needles) in enumerate(PROMPTS):
        turn: TurnRow = run_turn(client, prompt, session_key=f"l1_{idx}")
        # Routing OK if expected_tool is None (free-text expected) OR
        # the expected tool appears anywhere in the call sequence.
        if expected_tool is None:
            routing_ok = len(turn.tools_called) == 0
        else:
            routing_ok = expected_tool in turn.tools_called
        answer_ok: bool | None = (
            answer_contains_any(turn.answer, needles) if needles else None
        )
        rows.append({
            "level": 1,
            "idx": idx,
            "prompt": prompt,
            "expected_tool": expected_tool,
            "tools_called": turn.tools_called,
            "answer": turn.answer,
            "elapsed_s": turn.elapsed_s,
            "routing_ok": routing_ok,
            "answer_ok": answer_ok,
            "error": turn.error,
        })
        print(
            f"  [L1 {idx:02d}] {short(prompt, 50):52s} "
            f"tool={(turn.tools_called[0] if turn.tools_called else '-')[:18]:18s} "
            f"route={'✓' if routing_ok else '✗'}  "
            f"ans={'✓' if answer_ok is True else ('✗' if answer_ok is False else '—')}  "
            f"{turn.elapsed_s:5.2f}s"
            + (f"  ERR: {turn.error}" if turn.error else ""),
            flush=True,
        )
    return rows


# ── Render ──────────────────────────────────────────────────────────


def render_markdown(rows: list[dict[str, Any]]) -> str:
    n = len(rows)
    routed = sum(1 for r in rows if r["routing_ok"])
    answer_checked = [r for r in rows if r["answer_ok"] is not None]
    answer_passes = sum(1 for r in answer_checked if r["answer_ok"])
    errors = sum(1 for r in rows if r["error"])
    total = sum(r["elapsed_s"] for r in rows)
    avg = total / n if n else 0.0

    lines = [
        "# Level 1 — single-turn tool routing",
        "",
        f"- {n} prompts; routing **{routed}/{n}** ({100 * routed / n:.0f}%); "
        f"answer-check **{answer_passes}/{len(answer_checked)}**; "
        f"errors {errors}; total {total:.1f}s; avg {avg:.2f}s/prompt.",
        "",
        md_table(
            ["#", "Prompt", "Expected", "Called", "Route", "Ans", "Time"],
            [
                [
                    str(r["idx"]),
                    short(r["prompt"], 50),
                    r["expected_tool"] or "(free-text)",
                    (r["tools_called"][0] if r["tools_called"] else "-"),
                    "✓" if r["routing_ok"] else "✗",
                    ("✓" if r["answer_ok"] is True
                     else "✗" if r["answer_ok"] is False else "—"),
                    f"{r['elapsed_s']:.2f}s",
                ]
                for r in rows
            ],
        ),
    ]
    return "\n".join(lines) + "\n"
