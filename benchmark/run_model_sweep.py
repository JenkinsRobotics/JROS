#!/usr/bin/env python3
"""Bench every local model in turn, write a comparison table.

Usage::

    python benchmark/run_model_sweep.py /tmp/bench_models.txt
    python benchmark/run_model_sweep.py /tmp/bench_models.txt --level 1

The input file lists one absolute model path per line. For each entry
we:

  1. Edit the active instance's ``config.yaml`` so ``model.model_path``
     points at that file (preserving everything else).
  2. Spawn ``run_level.py`` as a fresh subprocess — each model gets a
     clean Python interpreter so module-level state doesn't leak, the
     drift parser is the latest committed code, and a crash on one
     model doesn't poison the others.
  3. Parse the per-row output and the BENCHMARK_levelN.md summary the
     run dropped for us.
  4. Restore the original config at the end (always, via try/finally).

Results land in ``benchmark/sweep/RESULTS_<timestamp>.md`` plus a
``sweep_rows.jsonl`` with per-model totals so a future script can plot
trends.

The driver is deliberately dumb — it doesn't try to be clever about
parallelism or hot-swapping. Each model loads from cold; one process at
a time. That's fine for an overnight comparison and far easier to
debug than a hot-swap dance that could leak GPU memory.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict


REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "src"
DEFAULT_INSTANCE_CFG = (
    REPO / "src" / "jaeger_os" / "instance" / "default" / "config.yaml"
)
SWEEP_DIR = REPO / "benchmark" / "sweep"


@dataclass
class ModelResult:
    name: str
    path: str
    size_gb: float
    level: int
    cases: int = 0
    route_ok: int = 0
    answer_ok: int = 0
    elapsed_s: float = 0.0
    load_s: float = 0.0
    p50_turn_s: float = 0.0
    failures: list[str] = field(default_factory=list)
    return_code: int = -1
    error: str | None = None

    @property
    def route_pct(self) -> float:
        return (self.route_ok / self.cases * 100) if self.cases else 0.0

    @property
    def answer_pct(self) -> float:
        return (self.answer_ok / self.cases * 100) if self.cases else 0.0


# ── config swap ────────────────────────────────────────────────────


def _read_config_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_model_path(text: str, new_model_path: str) -> str:
    """Replace ``model.model_path`` value, preserving everything else.

    Earlier versions used a regex-replace on ``model_path:`` — that
    broke when the bench subprocess re-wrote config.yaml during boot
    (normalised key order, added defaults, etc.) so the regex no
    longer matched after the first iteration. YAML round-trip is the
    robust answer: parse → mutate one key → emit.

    We use ``ruamel.yaml`` if available for comment preservation, then
    fall back to stdlib ``yaml`` (loses comments) and finally to the
    regex path as a last resort. Comments only matter for human
    readability of intermediate states; functionally the bench just
    needs ``model.model_path`` to be the path we asked for."""
    try:
        from ruamel.yaml import YAML
        import io
        yaml = YAML()
        yaml.preserve_quotes = True
        data = yaml.load(text)
        if "model" in data and isinstance(data["model"], dict):
            data["model"]["model_path"] = new_model_path
            buf = io.StringIO()
            yaml.dump(data, buf)
            return buf.getvalue()
    except ImportError:
        pass
    except Exception:  # noqa: BLE001 — fall back to next strategy
        pass

    try:
        import yaml as _yaml
        data = _yaml.safe_load(text)
        if isinstance(data, dict) and isinstance(data.get("model"), dict):
            data["model"]["model_path"] = new_model_path
            return _yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
    except Exception:  # noqa: BLE001
        pass

    # Last resort — regex. Same as the original implementation.
    pattern = re.compile(r"^(\s*model_path:\s*).+$", re.MULTILINE)
    new = pattern.sub(rf"\g<1>{new_model_path}", text, count=1)
    if new == text:
        raise RuntimeError(
            "model_path: line not found in config.yaml and no YAML "
            "library available — install ``pyyaml`` or ``ruamel.yaml``."
        )
    return new


# ── run one model ──────────────────────────────────────────────────


def _human_name(path: str) -> str:
    """Short label for the report — last component minus the .gguf."""
    return pathlib.Path(path).stem


def _file_size_gb(path: str) -> float:
    try:
        return pathlib.Path(path).stat().st_size / 1e9
    except OSError:
        return 0.0


# Per-level per-row regexes. Each must produce a ``pass`` group (the
# headline boolean for routing accuracy at that level) and an
# ``elapsed`` group. Auxiliary signals (``ans``, ``order``, ``surf``)
# get folded in where they exist; absent fields default to True (don't
# penalise levels that don't measure them).
_ROW_RE_L1 = re.compile(
    r"\[L1 (?P<idx>\d+)\][^\n]*?route=(?P<pass_mark>[✓✗])\s+ans=(?P<ans>[✓✗—])\s+(?P<elapsed>[\d.]+)s",
)
_ROW_RE_L2 = re.compile(
    r"\[L2 (?P<idx>\d+)\][^\n]*?set=(?P<pass_mark>[✓✗])\s+order=(?P<order>[✓✗—])\s+ans=(?P<ans>[✓✗—])\s+(?P<elapsed>[\d.]+)s",
)
# L3 puts the pass/fail marker INSIDE the row bracket and prints
# scenario-level rows (one per multi-turn scenario, not per turn).
_ROW_RE_L3 = re.compile(
    r"\[L3 (?P<idx>\d+) (?P<pass_mark>[✓✗])\][^\n]+?(?P<elapsed>[\d.]+)s",
)
_ROW_RE_L4 = re.compile(
    r"\[L4 (?P<idx>\d+)\][^\n]*?recov=(?P<pass_mark>[✓✗—])\s+(?P<elapsed>[\d.]+)s",
)


def _parse_bench_output(stdout: str) -> tuple[int, int, int, list[float], list[str], float]:
    """Walk the per-row console output and pull totals + per-row latencies.

    The per-level regex set lets one parser cover all four bench level
    formats. Headline pass-mark differs per level: L1 ``route=``,
    L2 ``set=``, L3 in-bracket ✓/✗, L4 ``recov=``. Auxiliary signals
    (``ans``) populate the answer counter when present.

    Returns (cases, pass_count, answer_ok, latencies, failed_rows, load_s).
    """
    cases = 0
    pass_count = 0
    answer_ok = 0
    latencies: list[float] = []
    failures: list[str] = []
    load_s = 0.0
    for raw in stdout.splitlines():
        if "loaded in " in raw and load_s == 0.0:
            try:
                load_s = float(re.search(r"loaded in (\S+)s", raw).group(1))
            except (AttributeError, ValueError):
                pass
        # Try each regex; first match wins.
        for pattern in (_ROW_RE_L1, _ROW_RE_L2, _ROW_RE_L3, _ROW_RE_L4):
            m = pattern.search(raw)
            if m:
                break
        if not m:
            continue
        cases += 1
        passed = m.group("pass_mark") == "✓"
        if passed:
            pass_count += 1
        # ``ans`` is L1/L2-only; L3/L4 rows don't carry it directly.
        try:
            if m.group("ans") == "✓":
                answer_ok += 1
        except (IndexError, KeyError):
            pass
        latencies.append(float(m.group("elapsed")))
        if not passed:
            # Failure summary — short prompt label for the report.
            mid = raw.split("] ", 1)[1] if "] " in raw else raw
            label = re.split(r"\s+(?:tool=|set=|recov=)", mid, maxsplit=1)[0].strip()
            failures.append(label[:60])
    return cases, pass_count, answer_ok, latencies, failures, load_s


def run_one(model_path: str, *, level: int) -> ModelResult:
    name = _human_name(model_path)
    size = _file_size_gb(model_path)
    print(f"\n══════════════ {name}  ({size:.1f} GB) ══════════════", flush=True)

    saved = _read_config_text(DEFAULT_INSTANCE_CFG)
    try:
        DEFAULT_INSTANCE_CFG.write_text(
            _write_model_path(saved, model_path), encoding="utf-8",
        )

        env = os.environ.copy()
        env["PYTHONPATH"] = (str(SRC) + os.pathsep + env.get("PYTHONPATH", ""))
        started = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, str(REPO / "benchmark" / "run_level.py"),
             str(level), "--no-warmup"],
            cwd=str(REPO),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=2400,   # 40 min cap per model — biggest realistic run
        )
        wall = time.perf_counter() - started
    except subprocess.TimeoutExpired as exc:
        return ModelResult(
            name=name, path=model_path, size_gb=size, level=level,
            error=f"timeout after {exc.timeout:.0f}s", return_code=-1,
        )
    except Exception as exc:  # noqa: BLE001 — surface every failure mode
        return ModelResult(
            name=name, path=model_path, size_gb=size, level=level,
            error=f"{type(exc).__name__}: {exc}", return_code=-1,
        )
    finally:
        DEFAULT_INSTANCE_CFG.write_text(saved, encoding="utf-8")

    cases, route_ok, ans_ok, lats, fails, load_s = _parse_bench_output(proc.stdout)
    lats.sort()
    p50 = lats[len(lats) // 2] if lats else 0.0
    result = ModelResult(
        name=name,
        path=model_path,
        size_gb=size,
        level=level,
        cases=cases,
        route_ok=route_ok,
        answer_ok=ans_ok,
        elapsed_s=wall,
        load_s=load_s,
        p50_turn_s=p50,
        failures=fails,
        return_code=proc.returncode,
    )
    # Tail of the subprocess output to a per-model log so it's easy to
    # poke at failures after the fact without redoing the run.
    log_path = SWEEP_DIR / f"{name}.stdout.log"
    SWEEP_DIR.mkdir(parents=True, exist_ok=True)
    log_path.write_text(proc.stdout, encoding="utf-8")
    print(
        f"  → route {result.route_ok:>2}/{result.cases:>2} "
        f"({result.route_pct:.1f}%)  "
        f"answer {result.answer_ok:>2}/{result.cases:>2} "
        f"({result.answer_pct:.1f}%)  "
        f"p50 {result.p50_turn_s:.1f}s  total {result.elapsed_s:.0f}s",
        flush=True,
    )
    return result


# ── report ─────────────────────────────────────────────────────────


def _write_report(results: list[ModelResult], *, level: int, out_dir: pathlib.Path) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    md_path = out_dir / f"RESULTS_{ts}_level{level}.md"

    # Rank by routing %, tiebreak by p50 latency.
    ranked = sorted(
        [r for r in results if r.cases > 0],
        key=lambda r: (-r.route_pct, r.p50_turn_s),
    )

    lines: list[str] = [
        f"# Model sweep — Level {level}",
        "",
        f"Run at {ts}.  Each model loaded cold, benched against the same "
        f"{ranked[0].cases if ranked else '?'}-prompt Level-{level} suite, "
        "then unloaded.",
        "",
        "Routing % is the primary signal — "
        "answer % is auxiliary (many bench prompts have no expected "
        "answer string, so a '—' in the per-row output is neither pass "
        "nor fail there).",
        "",
        "## Ranking (routing% desc, p50 latency asc)",
        "",
        "| # | Model | Size GB | Route % | Answer % | p50 turn s | Load s |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(ranked, 1):
        lines.append(
            f"| {i} | `{r.name}` | {r.size_gb:.1f} | "
            f"{r.route_pct:.1f}% ({r.route_ok}/{r.cases}) | "
            f"{r.answer_pct:.1f}% ({r.answer_ok}/{r.cases}) | "
            f"{r.p50_turn_s:.1f} | {r.load_s:.1f} |"
        )

    errored = [r for r in results if r.cases == 0]
    if errored:
        lines += [
            "",
            "## Did not produce results",
            "",
            "| Model | Error |",
            "|---|---|",
        ]
        for r in errored:
            lines.append(f"| `{r.name}` | {r.error or 'no rows parsed'} |")

    # Per-model failure surface — the FIRST 5 misrouted prompts per model.
    lines += ["", "## Where each model lost routing points", ""]
    for r in ranked:
        if not r.failures:
            continue
        lines.append(f"**`{r.name}`** — {len(r.failures)} miss(es):")
        for f in r.failures[:5]:
            lines.append(f"  • {f}")
        if len(r.failures) > 5:
            lines.append(f"  • … and {len(r.failures) - 5} more (see `sweep/{r.name}.stdout.log`)")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {md_path.relative_to(REPO)}", flush=True)
    return md_path


def _write_jsonl(results: list[ModelResult], *, out_dir: pathlib.Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "sweep_rows.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps({**asdict(r),
                                 "ts": dt.datetime.now().isoformat()}) + "\n")


# ── entry ──────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("models_file",
                    help="Text file with one absolute model path per line.")
    ap.add_argument("--level", type=int, default=1,
                    help="Benchmark level (default 1).")
    args = ap.parse_args()

    with open(args.models_file, "r", encoding="utf-8") as fh:
        paths = [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    paths = [p for p in paths if pathlib.Path(p).exists()]
    if not paths:
        print("No model paths found in the list (or none exist on disk).",
              file=sys.stderr)
        return 2

    print(f"Sweeping {len(paths)} model(s) at Level {args.level}", flush=True)
    results: list[ModelResult] = []
    for p in paths:
        results.append(run_one(p, level=args.level))
        # Write incremental progress so a crash mid-sweep doesn't lose
        # the partial results.
        _write_jsonl([results[-1]], out_dir=SWEEP_DIR)

    _write_report(results, level=args.level, out_dir=SWEEP_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
