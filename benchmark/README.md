# benchmark/ — JROS benchmark suite

Two complementary model-in-the-loop benchmarks. Both boot the real
agent; together they answer "does it route correctly" **and** "how
fast". The routing bench is also exposed to the agent itself as the
`run_benchmark` tool — when the user says "run the system benchmark"
the agent executes the same corpus against its live pipeline.

| Suite | Driver | Question |
|---|---|---|
| **Routing (flat)** | `run_flat_bench.py` | Did the agent pick the right tool / produce the right answer? |
| **Multi-model sweep** | `run_model_sweep.py` | How does each local GGUF compare on the same bench? |
| **Timing** | `timing/bench.py` | How fast is each prompt turn, vs. the historical baseline? |

The suite **code** is committed. The routing suite's **output**
(`flat/*/rows.jsonl`, `flat/*/summary.{json,md}`, logs) is git-ignored.
The timing suite's `bench_history.jsonl` **is** committed — it is the
append-only historical performance record (see below).

## The flat bench

One canonical corpus of bench cases lives in
[`../src/jaeger_os/core/bench/cases.py`](../src/jaeger_os/core/bench/cases.py).
Each case carries its own scoring rules (expected tools, answer
substrings, hallucination signals, multi-turn session keys), so the
runner is a single uniform pass — no per-level dispatch.

Tags let you run a subset:

- `routing` — single-turn, single expected tool
- `multistep` — single-turn, multiple expected tools (set / ordered)
- `multiturn` — multi-turn scenarios (rows share a session key)
- `recovery` — failure surface + anti-hallucination
- `memory` / `files` / `web` / `code` / `audio` / `schedule` — subsystem

## Running it

### Agent-callable (the live path)

Inside the TUI, just ask:

> "run the system benchmark"

The agent calls the `run_benchmark` tool. Every case fires through
the SAME boot + system prompt + lean surface + dispatch you're
using, which is what makes this the most honest signal. Results land
under `<instance>/logs/bench/<timestamp>/`.

```text
You: run the benchmark with just the routing tag, limit 5
Agent: → run_benchmark(tags="routing", limit=5)
       5/5 cases passed; routing 5/5; answer 5/5; elapsed 18.2s
       full report: <instance>/logs/bench/20260525-141200/
```

### Offline (one boot, the whole corpus)

```bash
python benchmark/run_flat_bench.py              # full corpus
python benchmark/run_flat_bench.py --tags routing
python benchmark/run_flat_bench.py --limit 5    # smoke
```

Writes `benchmark/flat/<timestamp>/{rows.jsonl,summary.json}`.

### Multi-model sweep

For comparing local GGUFs head-to-head — each model gets a fresh
Python interpreter so module-level state doesn't leak:

```bash
python benchmark/run_model_sweep.py /tmp/bench_models.txt
```

The input file lists one absolute model path per line. Sweep output
lands in `benchmark/sweep/`.

## The timing suite — `timing/`

A flat per-prompt wall-clock benchmark: a 47-prompt corpus run through
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
update the expected values in `src/jaeger_os/core/bench/cases.py` (and
the `UMBRELLA_EQUIVALENTS` map there if it's a consolidation).
