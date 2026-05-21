# benchmark/ — JROS benchmark suite

Two complementary model-in-the-loop benchmarks. Both boot the real
agent; together they answer "does it route correctly" **and** "how
fast". This is the end-to-end counterpart to the `pytest` suite (which
tests tools functionally) and the per-skill `tests/benchmark.py` scripts.

| Suite | Dir | Question |
|---|---|---|
| **Routing** | `levels/` | Did the agent pick the right tool? (4 levels) |
| **Timing** | `timing/` | How fast is each prompt turn, vs. the historical baseline? |

The suite **code** is committed. The routing suite's **output**
(`BENCHMARK_*.md`, `*_rows.jsonl`, logs) is git-ignored. The timing
suite's `bench_history.jsonl` **is** committed — it is the append-only
historical performance record (see below).

## The four levels

| Level | File | What it tests |
|---|---|---|
| 1 | `levels/level1_routing.py` | single-turn tool routing — 33 prompts, "did it pick the right tool" |
| 2 | `levels/level2_multistep.py` | multi-step single turn — chaining several tools in one turn |
| 3 | `levels/level3_multiturn.py` | multi-turn — context carried across turns |
| 4 | `levels/level4_recovery.py` | error recovery — does it recover from a failed step |

## Running it

Each run boots its own model client (so a level can run standalone). A
GGUF model must be resolvable — see [`../models/README.md`](../models/README.md).

```bash
# from the JROS repo root
python benchmark/run_level.py 1        # one level
python benchmark/run_all_levels.py     # all four

python benchmark/run_level.py 1 --no-warmup   # skip the prewarm pass
```

Each run writes `levels/BENCHMARK_levelN.md` (a readable report) and
`levels/level_N_rows.jsonl` (raw rows) — both git-ignored.

Historical level-suite snapshots (the v1–v5 progression, carried over
from before jaeger_os had its own repo) are kept in
[`levels/history/`](levels/history/) for reference.

## The timing suite — `timing/`

A flat per-prompt wall-clock benchmark: the 47-prompt corpus run through
`run_command`, each turn timed. It carries a **`legacy` column** — the
lowest historical total ever recorded per prompt, from
`timing/bench_history.jsonl` (3000+ rows preserved from before the
repo split). That column is the baseline every run is measured against.

```bash
python benchmark/timing/bench.py                # run the 47-prompt corpus
python benchmark/timing/bench.py --render-only   # re-render md from history
```

It writes `timing/BENCHMARK.md` (legacy vs. current) and appends to
`timing/bench_history.jsonl` — the history file **is committed**, so the
performance record grows with the project and never resets.

## Note

Expected-tool names track the live tool surface. After a tool rename,
update the `expected_tool` values in the `levels/*.py` and
`timing/bench.py` data.
