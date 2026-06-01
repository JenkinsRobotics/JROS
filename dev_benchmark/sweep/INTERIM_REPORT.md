# Local-model sweep — Level 1 routing (interim)

Sweep started 2026-05-24 ~15:13 PT against the 34-prompt Level-1 routing
suite (the same suite the historical bench uses). 12 candidate GGUF
files, one cold subprocess per model so the freshly-fixed drift parser
is active in every run.

System crash mid-sweep at gemma-4-31B-it-Q4_K_M (dense 18.7 GB —
likely the trigger, as Qwen3.6-27B-dense had already timed out and the
machine was sitting on a swap-heavy state). **Skipping the dense 31B
on re-run.** 7 clean results below; 3 small models (E2B/E4B + manual
Qwen3-Coder re-bench with the drift fix) are queued.

## Results so far — ranked by routing %

| # | Model | Quant / type | Route % | p50 turn | Total | Verdict |
|---|---|---|---|---|---|---|
| **1** | **Qwen3.6-35B-A3B-Q4_K_M** | MoE 35B / 3B-active | **91.2%** (31/34) | 23.6s | 15.5m | **Top accuracy by ~20 points.** Slower per turn than Gemma-4-26B-A4B but well within agentic loop tolerance. |
| 2 | Qwen3.5-9B-Q4_K_M | Dense 9B | 70.6% (24/34) | 35.1s | 20.8m | Strong routing, but the 35s p50 makes an agentic turn (3-5 tool calls) painfully slow. |
| 3 | gemma-4-26B-A4B-it-Q4_K_M | MoE 26B / 4B-active | 67.6% (23/34) | **5.6s** | **4.4m** | **Best speed/accuracy.** Currently the JROS default — confirmed sensible. Loses to Qwen3.6-35B-A3B on accuracy but wins on latency by 4×. |
| 4 | Qwen3-Coder-30B-A3B *(pre-fix, bench-1)* | MoE 30B / 3B-active | 61.8% (21/34) | ~3s | 4.2m | Run was before the loose-`<function=>` drift fix. Sweep iter errored on config swap. Will re-bench. |
| — | gemma-3-12b-it-Q4_K_M | Dense 12B | 8.8% (3/34) | 1.1s | 1.3m | **No tool calls — answers as plain text.** |
| — | gemma-3-12B-it-QAT-Q4_0 | Dense 12B QAT | 8.8% (3/34) | 1.0s | 1.3m | Same flatline as Q4_K_M variant. |
| — | Ministral-3-14B-Reasoning-2512 | Dense 14B "reasoning" | 8.8% (3/34) | 1.0s | 1.7m | Reasoning-tuned, but emits zero tool calls. |
| — | Llama-3.2-3B-Instruct | Dense 3B | 8.8% (3/34) | 0.4s | 0.5m | Chat model, not agentic. |
| ✕ | Qwen3.6-27B-Q4_K_M | Dense 27B | timeout 40m | — | — | **Too slow.** Can't finish 34 routing prompts in 40 minutes. Dense 27B is unviable at this hardware tier. |

## Take-aways

1. **The MoE thesis is decisive on this hardware.** Of the four
   models that scored above zero on tool routing, three are MoE
   (Qwen3.6-35B-A3B, gemma-4-26B-A4B, Qwen3-Coder-30B-A3B) and the
   one dense exception (Qwen3.5-9B) pays a 4-7× per-turn latency
   penalty for similar quality. Dense 27B+ is **unviable** —
   Qwen3.6-27B couldn't complete the bench in 40 minutes.

2. **Gemma 3 doesn't tool-call in llama.cpp** — both the Q4_K_M and
   QAT variants flatline at 8.8% (which is just text-only chat
   matching). Don't ship Gemma 3 to operators who need agentic
   behavior.

3. **Llama 3.2 3B and Ministral 14B-Reasoning are text-chat models**,
   not agentic. Same 3/34 score as Gemma 3, meaning the few "passes"
   are plain-text answers that happened to match expected strings.

4. **The JROS default (gemma-4-26B-A4B) is well-positioned but not
   the leader.** It's the best speed/accuracy tradeoff. If routing
   accuracy is the priority, Qwen3.6-35B-A3B is the upgrade target —
   but it's 4× slower per turn.

## Pre-fix vs post-fix question (still open)

Qwen3-Coder-30B-A3B's bench-1 number (61.8%) was taken *before* the
loose `<function=…>` drift-parser fix. Many of its routing misses were
the model emitting:

```
<function=remember>
</function>
</tool_call>
```

— which the old parser missed entirely (no `<tool_call>` wrapper). The
sweep's auto-iter for Qwen3-Coder errored on the config-swap regex (the
pre-sweep config had two `model_path` lines from an earlier session),
so we never got the post-fix number. Manual re-bench queued.

If Qwen3-Coder-30B-A3B re-benches at 75-80% with the drift fix, it
becomes a serious alternative to Qwen3.6-35B-A3B because of its much
better per-turn latency (~3s vs 23s).

## Recommendation

| Use case | Pick |
|---|---|
| **Default JROS instance, voice/interactive** | gemma-4-26B-A4B-it-Q4_K_M (5.6s p50 keeps the loop snappy; 67.6% routing is acceptable for everyday tasks) |
| **Accuracy-first deployment, batch / agentic** | Qwen3.6-35B-A3B-Q4_K_M (91.2% routing wins on harder L2/L4 paths, p50 23s is tolerable for non-interactive work) |
| **Skip / remove** | Llama-3.2-3B, Ministral-14B, both Gemma-3 variants, Qwen3.6-27B-Dense, gemma-4-31B-Dense (suspected crash culprit) |

## Files

- `benchmark/sweep/sweep_rows.jsonl` — one JSON row per attempted model
- `benchmark/sweep/<model>.stdout.log` — full per-row output from each
  successful bench (for failure inspection)
- `benchmark/run_model_sweep.py` — the driver
- `/tmp/sweep_l1.log` — parent process tee'd output

To re-run a single model with the same driver:

```bash
# minimal model list
echo "/path/to/model.gguf" > /tmp/single_model.txt
PYTHONPATH=src python benchmark/run_model_sweep.py /tmp/single_model.txt --level 1
```
