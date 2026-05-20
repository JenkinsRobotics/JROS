"""Level 3 — multi-turn conversations.

Each scenario is a sequence of user turns sharing one ``session_key``
so the agent's session history carries across. Tests whether the
model resolves pronouns ("multiply that by 2"), recalls facts set
earlier in the conversation, and maintains coherent context across
several turns — the test that most distinguishes a "coherent agent"
from a "stateless tool router."

Each turn within a scenario can have its own expectations (expected
tool, required answer substrings). A scenario passes only if EVERY
turn's expectations are met.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ._runner import (
    answer_contains_all,
    md_table,
    run_turn,
    short,
)


@dataclass
class Turn:
    prompt: str
    expected_tool: str | None = None
    must_contain: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class Scenario:
    name: str
    description: str
    turns: list[Turn]
    cleanup_after: list[str] = field(default_factory=list)


# ── Scenarios ───────────────────────────────────────────────────────


SCENARIOS: list[Scenario] = [
    Scenario(
        name="remember-then-ask",
        description="Remember a fact early, ask about it later.",
        turns=[
            Turn("Remember that I have a meeting at 3 PM tomorrow.",
                 expected_tool="remember"),
            Turn("What time is my meeting?",
                 expected_tool="recall",
                 must_contain=["3"]),
        ],
        cleanup_after=["forget my meeting time"],
    ),
    Scenario(
        name="calc-and-reuse",
        description="Compute a value, then ask the model to use it without re-stating.",
        turns=[
            Turn("Calculate 47 times 23.",
                 expected_tool="calculate",
                 must_contain=["1081"]),
            Turn("Now multiply that result by 2.",
                 expected_tool="calculate",
                 must_contain=["2162"],
                 notes="'that result' resolves only if turn-1 answer is in history."),
        ],
    ),
    Scenario(
        name="file-roundtrip",
        description="Write a file in turn 1; read it back in turn 2.",
        turns=[
            Turn("Create a file called level3_test.txt containing the text "
                 "'sea otters are mammals'.",
                 expected_tool="write_file"),
            Turn("Read level3_test.txt and tell me what it says.",
                 expected_tool="read_file",
                 must_contain=["sea otters"]),
            Turn("Delete level3_test.txt.",
                 expected_tool="delete_file"),
        ],
    ),
    Scenario(
        name="weather-followup",
        description="Get weather for one city, ask about another implicitly.",
        turns=[
            Turn("What's the weather in Seattle?",
                 expected_tool="get_weather",
                 must_contain=["seattle"]),
            Turn("What about Tokyo?",
                 expected_tool="get_weather",
                 must_contain=["tokyo"],
                 notes="Pronoun resolution: 'what about X' inherits the weather intent."),
        ],
    ),
    Scenario(
        name="three-fact-build-up",
        description="Build up three facts across three turns, then query them.",
        turns=[
            Turn("Remember that my favorite food is sushi.",
                 expected_tool="remember"),
            Turn("Also remember that I drive a Toyota.",
                 expected_tool="remember"),
            Turn("And remember my dog's name is Mochi.",
                 expected_tool="remember"),
            Turn("List everything you know about me.",
                 expected_tool="list_facts",
                 must_contain=["sushi", "toyota", "mochi"]),
        ],
        cleanup_after=[
            "forget my favorite food",
            "forget my car",
            "forget my dog's name",
        ],
    ),
    Scenario(
        name="search-then-deepen",
        description="Initial search, then a follow-up that references the topic implicitly.",
        turns=[
            Turn("Search the web for what jaeger tracing is.",
                 expected_tool="web_search",
                 must_contain=["trac"]),
            Turn("Who originally built it?",
                 must_contain=["uber"],
                 notes="Must use prior search context (no new search needed if context is rich)."),
        ],
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
    """Run every scenario. Each scenario uses its own session_key so
    turns within share history; scenarios don't pollute each other."""
    rows: list[dict[str, Any]] = []
    for s_idx, scenario in enumerate(SCENARIOS):
        session = f"l3_{s_idx}_{scenario.name}"
        turn_records: list[dict[str, Any]] = []
        all_pass = True
        scenario_elapsed = 0.0
        for t_idx, turn_spec in enumerate(scenario.turns):
            turn = run_turn(client, turn_spec.prompt, session_key=session)
            scenario_elapsed += turn.elapsed_s
            routing_ok: bool | None = None
            if turn_spec.expected_tool is not None:
                routing_ok = turn_spec.expected_tool in turn.tools_called
            answer_ok: bool | None = (
                answer_contains_all(turn.answer, turn_spec.must_contain)
                if turn_spec.must_contain else None
            )
            turn_pass = (
                (routing_ok is not False)
                and (answer_ok is not False)
                and turn.error is None
            )
            all_pass = all_pass and turn_pass
            turn_records.append({
                "t_idx": t_idx,
                "prompt": turn_spec.prompt,
                "expected_tool": turn_spec.expected_tool,
                "tools_called": turn.tools_called,
                "answer": turn.answer,
                "elapsed_s": turn.elapsed_s,
                "routing_ok": routing_ok,
                "answer_ok": answer_ok,
                "error": turn.error,
                "turn_pass": turn_pass,
            })
            print(
                f"    [L3 {s_idx}.{t_idx}] {short(turn_spec.prompt, 50):52s} "
                f"tool={(turn.tools_called[0] if turn.tools_called else '-')[:18]:18s} "
                f"route={'✓' if routing_ok is True else ('✗' if routing_ok is False else '—')}  "
                f"ans={'✓' if answer_ok is True else ('✗' if answer_ok is False else '—')}  "
                f"{turn.elapsed_s:5.2f}s"
                + (f"  ERR: {turn.error}" if turn.error else ""),
                flush=True,
            )
        rows.append({
            "level": 3,
            "s_idx": s_idx,
            "name": scenario.name,
            "description": scenario.description,
            "turns": turn_records,
            "elapsed_s": scenario_elapsed,
            "scenario_pass": all_pass,
        })
        marker = "✓" if all_pass else "✗"
        print(
            f"  [L3 {s_idx:02d} {marker}] {scenario.name:32s}  "
            f"{len(scenario.turns)} turns  {scenario_elapsed:5.2f}s",
            flush=True,
        )
        if scenario.cleanup_after:
            _cleanup(client, scenario.cleanup_after,
                     session_key=f"{session}_cleanup")
    return rows


# ── Render ──────────────────────────────────────────────────────────


def render_markdown(rows: list[dict[str, Any]]) -> str:
    n = len(rows)
    passing = sum(1 for r in rows if r["scenario_pass"])
    total_turns = sum(len(r["turns"]) for r in rows)
    total_passing_turns = sum(
        1 for r in rows for t in r["turns"] if t["turn_pass"]
    )
    total_elapsed = sum(r["elapsed_s"] for r in rows)

    lines = [
        "# Level 3 — multi-turn conversations",
        "",
        f"- {n} scenarios; passing **{passing}/{n}** "
        f"({100 * passing / n:.0f}%); "
        f"turn-level pass rate **{total_passing_turns}/{total_turns}**; "
        f"total {total_elapsed:.1f}s.",
        "",
    ]
    for r in rows:
        marker = "✓" if r["scenario_pass"] else "✗"
        lines.append(f"## {marker} {r['name']}")
        lines.append("")
        lines.append(f"_{r['description']}_  ({r['elapsed_s']:.1f}s total)")
        lines.append("")
        lines.append(md_table(
            ["Turn", "Prompt", "Tool", "Answer (short)", "OK", "Time"],
            [
                [
                    str(t["t_idx"]),
                    short(t["prompt"], 50),
                    (t["tools_called"][0] if t["tools_called"] else "-"),
                    short(t["answer"], 60),
                    ("✓" if t["turn_pass"] else "✗")
                    + (f" err={t['error']}" if t["error"] else ""),
                    f"{t['elapsed_s']:.2f}s",
                ]
                for t in r["turns"]
            ],
        ))
        lines.append("")
    return "\n".join(lines) + "\n"
