#!/usr/bin/env python3
"""Run a small Hermes benchmark against the currently selected model.

Switch Hermes to the model/provider you want to measure, run this script, and
paste the Markdown table into notes or chat. The runner intentionally calls the
normal quiet Hermes CLI path through python_hermes_agent.run_prompt so it tests
the same agent loop used by `hermes chat -Q -q`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from python_hermes_agent.run_prompt import run_prompt


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    prompt: str
    expected: tuple[str, ...]
    category: str


CASES = (
    BenchmarkCase(
        name="Arithmetic",
        prompt="Calculate 234 multiplied by 876. Return the final number.",
        expected=("204984",),
        category="reasoning",
    ),
    BenchmarkCase(
        name="Workspace Listing",
        prompt="Use a tool to list the top-level workspace and name three entries.",
        expected=("python_hermes_agent", "benchmark"),
        category="tool_use",
    ),
    BenchmarkCase(
        name="Read File",
        prompt=(
            "Use a tool to read python_hermes_agent/README.md and tell me "
            "what model/provider it says this Hermes wrapper uses."
        ),
        expected=("qwen", "ollama"),
        category="tool_use",
    ),
    BenchmarkCase(
        name="Create Plan",
        prompt=(
            "Inspect benchmark/bench.py with tools and tell me whether its "
            "default prompt suite includes a workspace listing task."
        ),
        expected=("workspace",),
        category="tool_use",
    ),
    BenchmarkCase(
        name="Code",
        prompt=(
            "Write a Python function named clamp(value, lower, upper) with "
            "type hints. Return code only."
        ),
        expected=("def clamp", "return"),
        category="coding",
    ),
)

PROMISE_RE = re.compile(
    r"\b(i['’]?ll|i will|let me|going to)\b.{0,120}"
    r"\b(create|write|inspect|read|run|check|prepare|list)\b",
    re.IGNORECASE | re.DOTALL,
)


def _passes(case: BenchmarkCase, text: str, result: dict[str, Any]) -> tuple[bool, str]:
    if result.get("error"):
        return False, str(result["error"])
    if result.get("exit_code") not in (None, 0):
        return False, f"exit {result['exit_code']}"
    if PROMISE_RE.search(text) and len(text.split()) < 80:
        return False, "promise without visible result"

    haystack = text.lower()
    missing = [item for item in case.expected if item.lower() not in haystack]
    if missing:
        return False, f"missing {', '.join(missing)}"
    return True, ""


def run_suite(label: str, toolsets: str | None, timeout_s: float) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for case in CASES:
        print(f"[manual-hermes-bench] {case.name}...", flush=True)
        result = run_prompt(case.prompt, toolsets=toolsets, timeout_s=timeout_s)
        text = str(result.get("text") or "").strip()
        passed, reason = _passes(case, text, result)
        rows.append(
            {
                "name": case.name,
                "category": case.category,
                "prompt": case.prompt,
                "passed": passed,
                "reason": reason,
                "elapsed_s": round(float(result.get("elapsed_s") or 0.0), 3),
                "session_id": result.get("session_id"),
                "exit_code": result.get("exit_code"),
                "response": text,
                "stderr": result.get("raw_stderr", ""),
            }
        )

    return {
        "label": label,
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "toolsets": toolsets,
        "timeout_s": timeout_s,
        "passed": sum(1 for row in rows if row["passed"]),
        "total": len(rows),
        "rows": rows,
    }


def markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Manual Hermes Benchmark",
        "",
        f"Label: `{payload['label']}`",
        f"Run at: `{payload['run_at']}`",
        f"Toolsets: `{payload['toolsets'] or 'Hermes config default'}`",
        f"Score: **{payload['passed']}/{payload['total']}**",
        "",
        "| Case | Category | Result | Seconds | Note |",
        "|---|---|---|---:|---|",
    ]
    for row in payload["rows"]:
        result = "PASS" if row["passed"] else "FAIL"
        note = row["reason"] or (row["session_id"] or "")
        note = str(note).replace("|", "/")
        lines.append(
            f"| {row['name']} | {row['category']} | {result} | "
            f"{row['elapsed_s']:.3f} | {note} |"
        )

    lines.extend(["", "## Responses", ""])
    for row in payload["rows"]:
        lines.append(f"### {row['name']}")
        lines.append("")
        lines.append("```text")
        lines.append((row["response"] or "(empty)")[:4000])
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark the Hermes model/provider selected in config."
    )
    parser.add_argument("--label", default="current Hermes config")
    parser.add_argument(
        "--toolsets",
        default="terminal,files",
        help="Toolsets passed to Hermes for benchmark calls.",
    )
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path for the full JSON payload.",
    )
    parser.add_argument(
        "--markdown-out",
        type=Path,
        default=None,
        help="Optional path for the Markdown report.",
    )
    args = parser.parse_args()

    payload = run_suite(args.label, args.toolsets or None, args.timeout)
    report = markdown_report(payload)
    print()
    print(report)

    if args.json_out:
        args.json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.write_text(report, encoding="utf-8")

    return 0 if payload["passed"] == payload["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
