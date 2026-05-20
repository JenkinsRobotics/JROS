# benchmark/ — JROS routing benchmark suite

The model-in-the-loop benchmark: it boots the real agent and checks
whether it routes prompts to the right tools. This is the end-to-end
counterpart to the `pytest` suite (which tests tools functionally) and
the per-skill `tests/benchmark.py` scripts.

The suite **code** is committed; its **output** (`BENCHMARK_*.md`,
`*_rows.jsonl`, logs) is git-ignored — those are local run artifacts.

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

## Note

Expected-tool names track the live tool surface. After a tool rename,
update the `expected_tool` values in the `levels/*.py` data.
