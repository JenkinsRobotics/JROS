"""Self-improvement probe — which model is best at the *deep-think* task the
skill-review loop actually runs: read a trajectory, find the planted
inefficiency, and state the one reusable imperative lesson.

This is a proxy for ``agent/background/skill_review.py``'s second-person audit
(no tools, pure reasoning), so the relative ranking across models tells us who
should own the deep-think / skill-improvement role per RAM tier.

Two modes (so each model loads in its OWN process — avoids the exit-teardown
crash + cross-model state bleed, exactly like run_model_sweep.py):
  * inner:  ``--model <registry-key>``  → swap config, boot, run cases, print RESULT_JSON
  * outer:  ``--models k1 k2 ...``      → subprocess the inner mode per model, table the results
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
for p in (str(_REPO), str(_HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)


# ── the probe corpus: planted-inefficiency trajectories ─────────────
# Each is another agent's trajectory with ONE obvious inefficiency. The model
# must name the reusable lesson; answer_contains_any holds the acceptable
# phrasings of the right lesson. Deliberately lenient (keyword match) — we want
# relative ranking, not absolute grading.
def _cases():
    from jaeger_os.core.bench.cases import BenchCase

    AUDIT = ("Below is a log of another agent's run. Review it as if it were "
             "someone else's work. State the SINGLE most valuable reusable "
             "lesson as one short imperative sentence.\n\n")
    return [
        BenchCase(
            id="si_batch_reads",
            prompt=AUDIT + ("1. read_file(a.py)\n2. read_file(b.py)\n"
                            "3. read_file(c.py)\n4. read_file(d.py)\n"
                            "(each in its own step, waiting for each before the next)"),
            answer_contains_any=["batch", "parallel", "at once", "single step",
                                 "one step", "together", "concurrent", "simultaneously"],
            tags=["selfimprove"]),
        BenchCase(
            id="si_repeat_failed_cmd",
            prompt=AUDIT + ("1. run `pytest` → ModuleNotFoundError: no_such_pkg\n"
                            "2. run `pytest` → ModuleNotFoundError: no_such_pkg\n"
                            "3. run `pytest` → ModuleNotFoundError: no_such_pkg"),
            answer_contains_any=["don't repeat", "do not repeat", "change", "fix the cause",
                                 "root cause", "diagnose", "install", "different",
                                 "stop retrying", "same command"],
            tags=["selfimprove"]),
        BenchCase(
            id="si_read_whole_file",
            prompt=AUDIT + ("1. read_file(server.py)  # 4000 lines, to find one function\n"
                            "2. scrolled the entire file looking for `def handle_login`"),
            answer_contains_any=["grep", "search", "targeted", "ripgrep", "find the symbol",
                                 "go to definition", "jump", "don't read the whole",
                                 "do not read the whole", "specific lines", "offset"],
            tags=["selfimprove"]),
        BenchCase(
            id="si_no_verify",
            prompt=AUDIT + ("1. edited auth.py to fix the bug\n"
                            "2. reported 'fixed' to the user\n"
                            "(no test run, no reproduction check)"),
            answer_contains_any=["verify", "test", "run the test", "confirm", "reproduce",
                                 "check", "validate", "prove"],
            tags=["selfimprove"]),
        BenchCase(
            id="si_ask_before_looking",
            prompt=AUDIT + ("1. user: 'add a flag to the parser'\n"
                            "2. agent: 'which file is the parser in?'\n"
                            "(the repo has one obvious cli/parser.py)"),
            answer_contains_any=["look", "search", "check the code", "explore", "grep",
                                 "find it yourself", "before asking", "investigate",
                                 "read the repo", "don't ask"],
            tags=["selfimprove"]),
        BenchCase(
            id="si_overengineer",
            prompt=AUDIT + ("1. needed to format one date string\n"
                            "2. built a DateFormatterFactory with a strategy interface "
                            "and 3 plugin classes for that one call site"),
            answer_contains_any=["yagni", "over-engineer", "overengineer", "simplest",
                                 "one line", "too much", "premature", "abstraction",
                                 "just use", "unnecessary", "keep it simple"],
            tags=["selfimprove"]),
    ]


def _run_one(model_key: str) -> dict:
    """Inner mode: swap config to model_key, boot, run the probe cases."""
    from run_model_sweep import DEFAULT_INSTANCE_CFG, _write_model_path  # noqa: E402

    from jaeger_os.core.models.model_resolver import resolve_model_path
    from jaeger_os.core.bench.runner import run_bench

    model_path = resolve_model_path(model_key, auto_download=False)
    cfg = DEFAULT_INSTANCE_CFG
    original = cfg.read_text()
    try:
        cfg.write_text(_write_model_path(original, model_path))
        from jaeger_os.main import boot_for_tui
        boot = boot_for_tui(instance_name=None, with_memory=False, warmup=False)
        rows = run_bench(boot.client, cases=_cases(), hermetic=False)
    finally:
        cfg.write_text(original)  # always restore, even if boot wrote over it

    per_case = {r.id: bool(r.answer_ok) for r in rows}
    passed = sum(1 for v in per_case.values() if v)
    return {
        "model": model_key,
        "model_path": model_path,
        "passed": passed,
        "total": len(rows),
        "per_case": per_case,
        "answers": {r.id: (r.answer or "")[:240] for r in rows},
    }


def _run_sweep(model_keys: list[str]) -> int:
    results = []
    for key in model_keys:
        print(f"\n=== probing {key} (own subprocess) ===", flush=True)
        proc = subprocess.run(
            [sys.executable, "-u", __file__, "--model", key],
            cwd=str(_REPO), capture_output=True, text=True)
        line = next((l for l in proc.stdout.splitlines()
                     if l.startswith("RESULT_JSON ")), None)
        if line is None:
            print(f"  ⚠ no result from {key} (rc={proc.returncode})")
            print("  --- tail stderr ---")
            print("\n".join(proc.stderr.splitlines()[-15:]))
            results.append({"model": key, "passed": -1, "total": 6, "per_case": {}})
            continue
        r = json.loads(line[len("RESULT_JSON "):])
        results.append(r)
        print(f"  {key}: {r['passed']}/{r['total']}")

    # table
    case_ids = [c.id for c in _cases()]
    print("\n" + "=" * 72)
    print("SELF-IMPROVEMENT PROBE — audit-reasoning (planted inefficiencies)")
    print("=" * 72)
    hdr = f"{'model':<34} {'score':>7}  " + " ".join(c.split("_", 1)[1][:6] for c in case_ids)
    print(hdr)
    for r in sorted(results, key=lambda x: x["passed"], reverse=True):
        marks = " ".join(("✓" if r["per_case"].get(c) else "·").center(6) for c in case_ids)
        print(f"{r['model']:<34} {r['passed']:>3}/{r['total']:<3}  {marks}")

    out = _HERE / "sweep" / "SELFIMPROVE_PROBE.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("# Self-improvement probe\n\n```\n" + hdr + "\n" +
                   "\n".join(
                       f"{r['model']:<34} {r['passed']:>3}/{r['total']:<3}  " +
                       " ".join(("Y" if r['per_case'].get(c) else ".").center(6) for c in case_ids)
                       for r in sorted(results, key=lambda x: x['passed'], reverse=True)) +
                   "\n```\n\n## answers\n\n" +
                   "\n".join(f"### {r['model']}\n" +
                             "\n".join(f"- **{cid}** ({'Y' if r['per_case'].get(cid) else '.'}): {a}"
                                       for cid, a in r.get("answers", {}).items())
                             for r in results) + "\n")
    print(f"\nwrote {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="inner mode: probe this one registry key")
    ap.add_argument("--models", nargs="+", help="outer mode: subprocess each key")
    args = ap.parse_args()
    if args.model:
        result = _run_one(args.model)
        print("RESULT_JSON " + json.dumps(result), flush=True)
        return 0
    if args.models:
        return _run_sweep(args.models)
    ap.error("pass --model (inner) or --models (outer)")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
