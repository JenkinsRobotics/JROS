# BENCHMARK v0.1.0 baseline — Level 1 routing

**Snapshot date:** 2026-05-24
**Branch:** `jaeger-os-hermes`
**Scorer:** umbrella-aware (accepts `memory` for the five fine-grained memory verbs and `execute_code` for `run_python`; see `level1_routing.py` _UMBRELLA_EQUIVALENTS).

## What changed from v5

The v5 baseline (33/33 = 100%) was scored against the pre-consolidation
tool surface (`remember` / `recall` / `forget` / `list_facts` /
`search_memory` were separate tools; `run_python` was the code-exec
name). JROS has since umbrella'd those into `memory(action=...)` and
renamed `run_python` → `execute_code`. The bench corpus is unchanged
from v5 (so historical numbers stay comparable), but the scorer now
recognises the umbrella forms — without this fix the JROS default
appeared to regress from 100% → 73.5%. With the fix it lands at
97.1%, effectively matching the v5 baseline.

## Level 1 — 34 single-turn routing prompts

Run cold per model (fresh subprocess each), `JAEGER_TOOLSET_SCOPING`
unset (default — lean surface OFF, the full tool surface visible to
the model), drift parser fix active for Qwen3-Coder's loose
`<function=…>` form.

### Top tier — viable for agentic deployments

| Rank | Model | Size GB | Route % | Cases | p50 turn s | Total s |
|---|---|---:|---:|---:|---:|---:|
| 1= | **gemma-4-E4B-it-Q4_K_M** 🏆 | 5.3 | **97.1%** | 33/34 | **1.6** | 294 |
| 1= | gemma-4-26B-A4B-it-Q4_K_M *(JROS default)* | 15.7 | **97.1%** | 33/34 | 3.0 | 326 |
| 3= | gemma-4-E2B-it-Q4_K_M | 3.4 | 94.1% | 32/34 | 1.2 | 183 |
| 3= | Qwen3-Coder-30B-A3B-Instruct-Q4_K_M | 18.6 | 94.1% | 32/34 | 3.2 | 302 |
| 5 | Qwen3.5-9B-Q4_K_M | 5.6 | 88.2% | 30/34 | 35.1 | 1250 |

### Not viable

| Model | Size GB | Route % | Reason |
|---|---:|---:|---|
| Qwen3.6-35B-A3B-Q4_K_M | 21.2 | 8.8% | Cold-load failure mode — bench completes 34 prompts in <20s with no tool calls. Separate model-load bug, not a routing issue. Needs investigation before deletion. |
| gemma-3-12b-it-Q4_K_M | 7.3 | 8.8% | Gemma 3 family does not emit tool-call XML in llama.cpp at this quant. |
| gemma-3-12B-it-QAT-Q4_0 | 6.9 | 8.8% | Same flatline as Q4_K_M variant. |
| Ministral-3-14B-Reasoning-2512-Q4_K_M | 8.2 | 8.8% | Reasoning-tuned but no tool calls. |
| Llama-3.2-3B-Instruct-Q4_K_M | 2.0 | 8.8% | Chat model, not agentic. |
| Qwen3.6-27B-Q4_K_M | 16.5 | timeout | Dense 27B too slow for 34 prompts in the 40-min cap. |

### Recommendation

For an **agentic** Jaeger on Apple Silicon:

| Use case | Pick |
|---|---|
| **Default / voice-interactive** | **gemma-4-E4B-it-Q4_K_M** — same 97.1% routing as the 26B default at 5.3 GB and 1.6s p50 (5× faster turn-to-turn). Recommended new JROS default. |
| Conservative default | gemma-4-26B-A4B-it — equally accurate, more headroom for harder reasoning at the cost of memory and speed. |
| Code-heavy workloads (Deep Think) | Qwen3-Coder-30B-A3B-Instruct — 94.1% routing with code specialization. Keep as the Deep Think coder model. |
| Smallest viable | gemma-4-E2B-it — 94.1% routing at 3.4 GB. Good for edge / constrained deployments. |

## L2 / L3 / L4

Not captured in this baseline — the multi-step, multi-turn, and
recovery benches need to be re-run against the corrected scorer's
equivalents map (the L2/L3/L4 `expected_tools` sets also reference
v5 names). Tracked as follow-up.

## Notes on the routing-regression investigation

Initial readings showed the JROS default at 67.6% / 73.5% — apparent
27-32-point regression from v5's 100%. Root cause was the bench scorer
expecting fine-grained tool names that have since umbrella'd:

  - `remember` / `recall` / `forget` / `list_facts` / `search_memory`
    → all became `memory(action=...)`
  - `run_python` → `execute_code`

With the scorer updated to accept those equivalents, the default lands
at 97.1% — the small remaining gap from 100% is one prompt (#16
"append a closing line…") that the model routes to `list_skill_dir`
instead of `append_file`, plus a similar variance prompt. Acceptable
baseline noise.

The **lean tool surface** (`JAEGER_TOOLSET_SCOPING=1`) showed mixed
results — helps E4B by +3, hurts E2B by −18, hurts the default by −6.
Reverted to OFF by default for 0.1.0; opt-in via env.

## Reproducing

```bash
# Single model
echo "/path/to/model.gguf" > /tmp/single_model.txt
PYTHONPATH=src python benchmark/run_model_sweep.py /tmp/single_model.txt --level 1

# All candidates
cat > /tmp/bench_models.txt <<EOF
/path/to/model_a.gguf
/path/to/model_b.gguf
EOF
PYTHONPATH=src python benchmark/run_model_sweep.py /tmp/bench_models.txt --level 1
```

The sweep writes `benchmark/sweep/sweep_rows.jsonl` (one row per model
attempt) and `benchmark/sweep/<model>.stdout.log` per successful run.
