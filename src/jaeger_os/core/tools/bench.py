"""Agent-callable system benchmark.

  • run_benchmark(tags, limit, ids) — runs the flat bench corpus
    against the LIVE agent pipeline and returns a scored summary.

This is the bench the user invokes by saying "run the system
benchmark" to the agent. The agent calls this tool, which drives
every case back through the same boot/system-prompt/dispatch path the
user just talked to — the most honest signal we can get for "did
this change regress routing?"

Tier: WRITE_LOCAL — the bench writes per-run markdown + jsonl under
``<instance>/logs/bench/``. Without that gate a curious user could
poke at the bench and unknowingly trigger a multi-minute model
session; the confirm/tier system lets the user opt in deliberately.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ._common import _require_layout
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier


@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="bench",
    operation="run_benchmark",
    summary="run the agent self-benchmark against the live pipeline",
)
def run_benchmark(
    tags: str = "",
    limit: int = 0,
    ids: str = "",
    save: bool = True,
) -> dict[str, Any]:
    """Run the flat self-benchmark suite against the live agent.

    Every case fires through the SAME pipeline you're using right
    now — same system prompt, same lean surface, same drift parser,
    same dispatch. That's what makes this trustworthy: a regression
    here is a regression in the surface the user actually talks to.

    Args:
      tags:  comma-separated subset of bench tags (e.g.
             ``"routing,memory"``). Empty = full corpus. Available
             tags: routing, multistep, multiturn, recovery, memory,
             files, web, code, audio, schedule.
      limit: cap on the number of cases (after tag filtering).
             0 = no cap. Multi-turn sessions are kept whole.
      ids:   comma-separated case ids to run (e.g.
             ``"time_now,calc_sqrt"``). Empty = no id filter.
      save:  when True (default), the per-row jsonl + a summary
             markdown are written under
             ``<instance>/logs/bench/<timestamp>/``.

    Returns a summary dict with topline counts plus per-tag breakdown
    and the failure list. Run individual rows by passing ``ids`` —
    handy for re-running a single flaky case after a fix.
    """
    from jaeger_os.core.bench import run_bench, summarise
    from jaeger_os.main import _pipeline

    client = _pipeline.get("client")
    if client is None:
        return {"ok": False, "error": "no live client — bench can only run "
                                       "inside a booted instance"}

    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    id_list = [i.strip() for i in (ids or "").split(",") if i.strip()]
    cap = int(limit) if limit and int(limit) > 0 else None

    started = time.perf_counter()
    rows = run_bench(client, tags=tag_list or None, ids=id_list or None,
                     limit=cap)
    summary = summarise(rows)
    summary["wall_s"] = round(time.perf_counter() - started, 2)

    if save and rows:
        try:
            layout = _require_layout()
            out_dir = Path(layout.logs_dir) / "bench" / \
                time.strftime("%Y%m%d-%H%M%S")
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "rows.jsonl").write_text(
                "\n".join(json.dumps(r, default=str, ensure_ascii=False)
                          for r in summary["rows"]) + "\n",
                encoding="utf-8",
            )
            (out_dir / "summary.json").write_text(
                json.dumps(
                    {k: v for k, v in summary.items() if k != "rows"},
                    indent=2, default=str, ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (out_dir / "summary.md").write_text(
                _render_markdown(summary), encoding="utf-8",
            )
            summary["report_dir"] = str(out_dir)
        except Exception as exc:  # noqa: BLE001 — never let bookkeeping
            # break the agent's view of the bench result
            summary["save_error"] = f"{type(exc).__name__}: {exc}"

    # Strip the rows from the agent-facing return — the full rows file
    # is on disk, and shoving 40 KB of jsonl into the model's context
    # is exactly what truncate_oversized_result would clip anyway.
    summary.pop("rows", None)
    return summary


def _render_markdown(summary: dict[str, Any]) -> str:
    """One-page summary suitable for ``logs/bench/<ts>/summary.md``."""
    total = summary.get("total", 0) or 1
    pass_pct = 100 * summary.get("passed", 0) / total
    lines = [
        "# Jaeger-OS — system benchmark",
        "",
        f"- **{summary.get('passed', 0)} / {summary.get('total', 0)}** "
        f"cases passed ({pass_pct:.0f}%)",
        f"- routing: {summary.get('routing_passed', 0)} / "
        f"{summary.get('routing_total', 0)}",
        f"- answer-checks: {summary.get('answer_passed', 0)} / "
        f"{summary.get('answer_total', 0)}",
        f"- errors: {summary.get('errors', 0)}",
        f"- elapsed: {summary.get('elapsed_s', 0)}s "
        f"(wall: {summary.get('wall_s', 0)}s)",
        "",
        "## By tag",
        "",
        "| Tag | Passed | Total |",
        "|---|---:|---:|",
    ]
    for tag, counts in sorted((summary.get("by_tag") or {}).items()):
        lines.append(
            f"| {tag} | {counts.get('passed', 0)} | {counts.get('total', 0)} |"
        )
    failures = summary.get("failures") or []
    if failures:
        lines.append("")
        lines.append(f"## Failures ({len(failures)})")
        lines.append("")
        for f in failures:
            lines.append(f"### {f['id']}")
            lines.append(f"- prompt: {f['prompt']!r}")
            lines.append(f"- tools called: {f['tools_called']}")
            lines.append(f"- routing_ok: {f['routing_ok']}, "
                         f"answer_ok: {f['answer_ok']}, "
                         f"no_hallucination: {f['no_hallucination']}")
            if f.get("error"):
                lines.append(f"- error: {f['error']}")
            lines.append("")
    return "\n".join(lines) + "\n"


__all__ = ["run_benchmark"]
