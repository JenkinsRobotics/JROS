# Jaeger-OS bench history

_Generated 2026-06-06T14:40:21 from 49 run(s) across `dev_benchmark/sweep/` and `dev_benchmark/flat/` — showing runs on/after **2026-05-29** (current benchmark generation). Filtered out **14** entries for models no longer on disk — historical data preserved in ``dev_benchmark/flat/``._

**Bench corpus version: 1.1** (cutoff 2026-05-29). The leaderboard ranks only runs of this version so the comparison stays apples-to-apples; older 1.0 (51-case) runs are archived and shown separately at the bottom of the report.

## Per-model leaderboard

<details><summary><i>14 hidden uninstalled models</i></summary>

These models have bench history but their ``.gguf`` files are no longer in ``~/.lmstudio/models``. Run ``jaeger bench history --write --include-uninstalled`` to surface them again.

- `gemma-4-26b-a4b-it-q4-k-m`
- `gemma-4-e2b-it-q4-k-m`
- `gemma-4-e4b-it-q6-k`
- `gemma-4-e4b-it-q8-0`
- `gpt-oss-20b-mxfp4`
- `hermes-3-llama-3.1-8b.q8-0`
- `hermes-4-14b-q8-0`
- `hermes-4-3-36b-q3-k-m`
- `ministral-3-14b-reasoning-2512-q4-k-m`
- `qwen3-4b-thinking-2507-q6-k`
- `qwen3-8b-q3-k-l`
- `qwen3-coder-30b-a3b-q4_k_m`
- `qwen3.5-9b-q6-k`
- `qwen3.5-9b-q8-0`

</details>

``Score`` is dead simple: **``passed / total``** from the latest run. Every case worth the same 1/total — pass 50/59 → 84.7%, no tier weighting, no hidden math. The per-tier columns are informational breakdowns of WHICH cases passed: ``Deep-think`` = code / multistep / recovery (what a coding agent needs); ``Real-time`` = routing (what a fast agent needs); ``Multi-turn`` = multiturn / cross-turn (stateful conversations); ``Safety`` = refusal / no-hallucination cases. Latest-run figures, sorted by Score.

**Methodology — ideal state vs baseline.** Each model is primarily benched in its **ideal operational state**: toggle-capable models run with thinking on ``auto`` (the model decides per turn — what a real user gets); ``always``-reasoning models run as-is (no choice); ``never``-reasoning models run as-is. Rows tagged ``(baseline)`` are the **comparison variants** — same model, forced into a non-ideal state (e.g. an ``auto`` model forced to ``off`` for direct-mode benchmarking). Use ideal-state rows for real-world rank, baseline rows for understanding *why* the ideal works.

| # | Model | Mode | Family | **Score** | Deep-think | Real-time | Multi-turn | Safety | Best route% | Latest elapsed | Tokens/task | Peak TPS | VRAM | Peak load | Latest run | Runs |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| 1 | `gemma-4-12b-it-q4_k_m` | 🧠 auto | gemma | **94.9%** | 18/18 | 24/25 | 11/12 | 4/5 | 98.1% | 7m17s | 67 | — | — | 3.3 | 2026-06-04 23:45 | 1 |
| 2 | `gemma-4-26b-a4b-it-q4_k_m` | 🧠 auto | gemma | **93.2%** | 15/18 | 25/25 | 11/12 | 5/5 | 100.0% | 4m47s | 66 | — | — | 13.0 | 2026-06-06 01:31 | 7 |
| 3 | `qwen3-30b-a3b-q4_k_m` | 🧠 auto | qwen | **93.2%** | 16/18 | 24/25 | 12/12 | 4/5 | 98.1% | 24m29s | 673 | — | — | 4.6 | 2026-05-31 01:35 | 2 |
| 4 | `qwen3-4b-thinking-2507-q3-k-l` | 🧠 auto | qwen | **93.2%** | 16/18 | 24/25 | 12/12 | 3/5 | 100.0% | 1h16m | 1884 | — | — | 4.1 | 2026-05-31 08:41 | 2 |
| 5 | `qwen3.5-9b-q4-k-m` | 🧠 auto | qwen | **93.2%** | 16/18 | 25/25 | 12/12 | 3/5 | 100.0% | 1h04m | 216 | — | — | 2.4 | 2026-05-31 06:19 | 2 |
| 6 | `qwen3.6-35b-a3b-q4-k-m` | 🧠 auto | qwen | **91.5%** | 16/18 | 24/25 | 10/12 | 4/5 | 92.3% | 1h03m | 311 | — | — | 11.1 | 2026-05-31 05:15 | 2 |
| 7 | `qwen3-4b-thinking-2507-q8-0` | 🧠 auto | qwen | **91.5%** | 14/18 | 24/25 | 12/12 | 4/5 | 96.2% | 1h05m | 1731 | — | — | 3.9 | 2026-05-31 07:25 | 2 |
| 8 | `qwen3-14b-q8-0` | 🧠 auto | qwen | **89.8%** | 14/18 | 24/25 | 12/12 | 3/5 | 100.0% | 57m23s | 763 | — | — | 2.7 | 2026-05-31 03:10 | 2 |
| 9 | `qwen3-14b-q3-k-l` | 🧠 auto | qwen | **89.8%** | 15/18 | 25/25 | 12/12 | 2/5 | 100.0% | 1h01m | 522 | — | — | 2.6 | 2026-05-31 04:11 | 2 |
| 10 | `gemma-4-e4b-it-q4-k-m` | 🧠 auto | gemma | **88.1%** | 14/18 | 24/25 | 11/12 | 3/5 | 100.0% | 3m47s | 76 | — | — | 3.9 | 2026-05-31 08:48 | 4 |
| 11 | `qwen3-coder-30b-a3b-instruct-q3-k-l` | 🧠 auto | qwen | **88.1%** | 14/18 | 25/25 | 11/12 | 3/5 | 96.2% | 9m47s | 92 | — | — | 5.1 | 2026-05-31 01:02 | 3 |
| 12 | `qwen3-8b-q8-0` | 🧠 auto | qwen | **88.1%** | 14/18 | 24/25 | 11/12 | 3/5 | 100.0% | 36m44s | 767 | — | — | 3.9 | 2026-05-31 02:12 | 2 |

## Top 10 all-time best runs

Sorted by routing % (then p50 asc). A single great run doesn't make a model great, but tracking peaks tells you what's achievable on this hardware.

| # | Date | Model | Route% | p50 s | p95 s | TPS | Cases | Source |
|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | 2026-05-31 08:48 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.21 | 10.43 | 21.2 | 59 | flat |
| 2 | 2026-05-29 13:21 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.21 | 10.46 | 20.4 | 59 | flat |
| 3 | 2026-05-30 23:43 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.21 | 8.07 | 22.0 | 59 | flat |
| 4 | 2026-05-31 00:48 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.22 | 8.76 | 13.8 | 59 | flat |
| 5 | 2026-05-31 00:52 | `gemma-4-26b-a4b-it-q4_k_m` | 100.0% | 2.37 | 10.91 | 17.8 | 59 | flat |
| 6 | 2026-06-04 01:09 | `gemma-4-26b-a4b-it-q4_k_m` | 100.0% | 2.52 | 15.57 | 17.2 | 59 | flat |
| 7 | 2026-05-29 16:58 | `gemma-4-26b-a4b-it-q4_k_m` | 100.0% | 2.52 | 17.61 | 16.1 | 59 | flat |
| 8 | 2026-05-30 23:47 | `gemma-4-26b-a4b-it-q4_k_m` | 100.0% | 2.57 | 12.59 | 16.4 | 59 | flat |
| 9 | 2026-05-30 23:30 | `gemma-4-26b-a4b-it-q4_k_m` | 100.0% | 2.60 | 11.91 | 16.0 | 59 | flat |
| 10 | 2026-05-31 02:12 | `qwen3-8b-q8-0` | 100.0% | 20.69 | 60.55 | 23.4 | 59 | flat |

## Full chronological log

Every run we have data for (49 total), newest first. ``vs peak`` shows the route% delta from this model's all-time best (0.0% = this run IS the peak).

| Date | Model | Route% | p50 s | TPS | Cases | vs peak | Source |
|---|---|---:|---:|---:|---:|---:|---|
| 2026-06-06 12:59 | `gemma-4-26b-a4b-it-q4-k-m` | 98.1% | 2.77 | 14.6 | 59 | **peak** | flat |
| 2026-06-06 01:31 | `gemma-4-26b-a4b-it-q4_k_m` | 98.1% | 2.78 | 14.7 | 59 | -1.9pp | flat |
| 2026-06-04 23:45 | `gemma-4-12b-it-q4_k_m` | 98.1% | 4.41 | 9.7 | 59 | **peak** | flat |
| 2026-06-04 01:09 | `gemma-4-26b-a4b-it-q4_k_m` | 100.0% | 2.52 | 17.2 | 59 | **peak** | flat |
| 2026-06-04 01:03 | `gemma-4-26b-a4b-it-q4_k_m` | 96.2% | 2.55 | 17.6 | 59 | -3.8pp | flat |
| 2026-05-31 08:48 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.21 | 21.2 | 59 | **peak** | flat |
| 2026-05-31 08:41 | `qwen3-4b-thinking-2507-q3-k-l` | 100.0% | 39.00 | 28.4 | 59 | **peak** | flat |
| 2026-05-31 07:25 | `qwen3-4b-thinking-2507-q8-0` | 94.2% | 35.52 | 30.4 | 59 | -1.9pp | flat |
| 2026-05-31 06:19 | `qwen3.5-9b-q4-k-m` | 100.0% | 49.81 | 3.8 | 59 | **peak** | flat |
| 2026-05-31 05:15 | `qwen3.6-35b-a3b-q4-k-m` | 92.3% | 34.81 | 7.6 | 59 | **peak** | flat |
| 2026-05-31 04:11 | `qwen3-14b-q3-k-l` | 98.1% | 31.76 | 9.1 | 59 | -1.9pp | flat |
| 2026-05-31 03:10 | `qwen3-14b-q8-0` | 100.0% | 29.88 | 14.6 | 59 | **peak** | flat |
| 2026-05-31 02:12 | `qwen3-8b-q8-0` | 100.0% | 20.69 | 23.4 | 59 | **peak** | flat |
| 2026-05-31 01:35 | `qwen3-30b-a3b-q4_k_m` | 98.1% | 16.87 | 29.9 | 59 | **peak** | flat |
| 2026-05-31 01:10 | `qwen3-coder-30b-a3b-q4_k_m` | 98.1% | 3.16 | 10.5 | 59 | **peak** | flat |
| 2026-05-31 01:02 | `qwen3-coder-30b-a3b-instruct-q3-k-l` | 96.2% | 3.36 | 9.7 | 59 | **peak** | flat |
| 2026-05-31 00:52 | `gemma-4-26b-a4b-it-q4_k_m` | 100.0% | 2.37 | 17.8 | 59 | **peak** | flat |
| 2026-05-31 00:48 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.22 | 13.8 | 59 | **peak** | flat |
| 2026-05-31 00:05 | `qwen3-coder-30b-a3b-instruct-q3-k-l` | 96.2% | 3.17 | 15.3 | 59 | **peak** | flat |
| 2026-05-30 23:56 | `qwen3-coder-30b-a3b-q4_k_m` | 98.1% | 3.31 | 10.3 | 59 | **peak** | flat |
| 2026-05-30 23:47 | `gemma-4-26b-a4b-it-q4_k_m` | 100.0% | 2.57 | 16.4 | 59 | **peak** | flat |
| 2026-05-30 23:43 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.21 | 22.0 | 59 | **peak** | flat |
| 2026-05-30 23:36 | `gemma-4-e4b-it-q8-0` | 92.3% | 1.50 | 14.2 | 59 | **peak** | flat |
| 2026-05-30 23:33 | `gemma-4-e4b-it-q6-k` | 92.3% | 1.45 | 13.6 | 59 | **peak** | flat |
| 2026-05-30 23:30 | `gemma-4-26b-a4b-it-q4_k_m` | 100.0% | 2.60 | 16.0 | 59 | **peak** | flat |
| 2026-05-30 22:57 | `gemma-4-e4b-it-q8-0` | 92.3% | 1.50 | 14.6 | 59 | **peak** | flat |
| 2026-05-30 22:54 | `qwen3.6-35b-a3b-q4-k-m` | 90.4% | 35.19 | 7.3 | 59 | -1.9pp | flat |
| 2026-05-30 21:55 | `qwen3-coder-30b-a3b-q4_k_m` | 98.1% | 3.33 | 9.5 | 59 | **peak** | flat |
| 2026-05-30 18:53 | `qwen3.5-9b-q8-0` | 96.2% | 45.24 | 7.6 | 59 | **peak** | flat |
| 2026-05-30 17:44 | `qwen3.5-9b-q6-k` | 96.2% | 50.32 | 6.6 | 59 | **peak** | flat |
| 2026-05-30 16:26 | `gemma-4-e4b-it-q6-k` | 92.3% | 1.41 | 14.0 | 59 | **peak** | flat |
| 2026-05-30 16:23 | `qwen3-4b-thinking-2507-q8-0` | 96.2% | 33.88 | 30.1 | 59 | **peak** | flat |
| 2026-05-30 15:16 | `qwen3-4b-thinking-2507-q6-k` | 96.2% | 30.99 | 33.3 | 59 | **peak** | flat |
| 2026-05-30 14:21 | `qwen3-4b-thinking-2507-q3-k-l` | 100.0% | 39.00 | 28.8 | 59 | **peak** | flat |
| 2026-05-30 12:20 | `qwen3.5-9b-q4-k-m` | 100.0% | 49.89 | 3.7 | 59 | **peak** | flat |
| 2026-05-30 04:41 | `hermes-4-3-36b-q3-k-m` | 0.0% | 0.06 | 0.0 | 59 | **peak** | flat |
| 2026-05-30 02:41 | `qwen3-14b-q8-0` | 98.1% | 30.07 | 14.6 | 59 | -1.9pp | flat |
| 2026-05-30 01:48 | `qwen3-8b-q8-0` | 100.0% | 21.30 | 23.5 | 59 | **peak** | flat |
| 2026-05-30 01:10 | `qwen3-14b-q3-k-l` | 100.0% | 31.62 | 13.1 | 59 | **peak** | flat |
| 2026-05-30 00:17 | `hermes-3-llama-3.1-8b.q8-0` | 0.0% | 46.58 | 0.0 | 59 | **peak** | flat |
| 2026-05-29 23:23 | `qwen3-8b-q3-k-l` | 98.1% | 25.71 | 21.6 | 59 | **peak** | flat |
| 2026-05-29 17:23 | `qwen3-30b-a3b-q4_k_m` | 96.2% | 16.74 | 29.3 | 59 | -1.9pp | flat |
| 2026-05-29 16:58 | `gemma-4-26b-a4b-it-q4_k_m` | 100.0% | 2.52 | 16.1 | 59 | **peak** | flat |
| 2026-05-29 16:53 | `hermes-4-14b-q8-0` | 84.6% | 6.04 | 13.4 | 59 | **peak** | flat |
| 2026-05-29 15:56 | `qwen3-coder-30b-a3b-instruct-q3-k-l` | 94.2% | 3.32 | 7.4 | 59 | -1.9pp | flat |
| 2026-05-29 15:45 | `gpt-oss-20b-mxfp4` | 86.5% | 3.95 | 38.8 | 59 | **peak** | flat |
| 2026-05-29 14:34 | `ministral-3-14b-reasoning-2512-q4-k-m` | 92.3% | 4.10 | 11.9 | 59 | **peak** | flat |
| 2026-05-29 13:21 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.21 | 20.4 | 59 | **peak** | flat |
| 2026-05-29 12:46 | `gemma-4-e2b-it-q4-k-m` | 84.6% | 1.29 | 29.3 | 59 | **peak** | flat |
