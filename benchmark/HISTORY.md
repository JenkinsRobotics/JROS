# Jaeger-OS bench history

_Generated 2026-05-29T09:32:24 from 130 run(s) across `benchmark/sweep/` and `benchmark/flat/` — showing runs on/after **2026-05-27** (current benchmark generation)._

## Per-model leaderboard

``Route%`` is the easy metric — *did it dispatch the right tool* on routing cases. ``Deep-think`` is the HARD one — full pass (right tool + correct answer + finished the chain) on code / multistep / recovery cases, the capability a deep-think / coding agent needs. ``Real-time`` is full pass on routing, for a speed-focused agent. Latest-run figures.

| # | Model | Family | Deep-think | Real-time | Best route% | Best pass% | Latest p50 s | Latest tok/s | Latest run | Runs |
|---|---|---|---:|---:|---:|---:|---:|---:|---|---:|
| 1 | `gemma-4-E4B-it-Q4_K_M` | gemma | 14/18 | 24/25 | 100.0% | 92.2% | 2.18 | 21.7 | 2026-05-28 23:01 | 12 |
| 2 | `gemma-4-26B-A4B-it-Q4_K_M` | gemma | 15/18 | 24/25 | 100.0% | 96.1% | 2.52 | 16.3 | 2026-05-29 00:37 | 11 |
| 3 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | qwen | 15/18 | 24/25 | 98.0% | 94.1% | 3.03 | 15.8 | 2026-05-29 00:42 | 14 |
| 4 | `Qwen3-30B-A3B-Q4_K_M` | qwen | 15/18 | 24/25 | 98.0% | 92.2% | 16.46 | 29.1 | 2026-05-29 01:02 | 2 |
| 5 | `Qwen3-Coder-30B-A3B-Instruct-Q3_K_L` | qwen | 14/18 | 25/25 | 95.9% | 90.2% | 3.08 | 13.8 | 2026-05-29 02:17 | 2 |
| 6 | `Qwen3.6-35B-A3B-Q4_K_M` | qwen | 16/18 | 24/25 | 95.9% | 94.1% | 37.52 | 6.7 | 2026-05-27 22:30 | 5 |
| 7 | `gemma-4-E2B-it-Q4_K_M` | gemma | 11/18 | 22/25 | 91.8% | 88.2% | 1.32 | 28.7 | 2026-05-28 22:58 | 14 |
| 8 | `gemma-4-E4B-it-Q8_0` | gemma | 3/18 | 18/25 | 91.8% | 47.1% | 1.47 | 13.6 | 2026-05-29 01:35 | 2 |
| 9 | `Ministral-3-14B-Reasoning-2512-Q4_K_M` | mistral | 9/18 | 23/25 | 85.7% | 74.5% | 3.83 | 8.8 | 2026-05-29 03:25 | 8 |
| 10 | `gpt-oss-20b-MXFP4` | other | 7/18 | 22/25 | 85.7% | 76.5% | 4.42 | 41.7 | 2026-05-29 00:33 | 10 |
| 11 | `Hermes-4-14B-Q8_0` | other | 13/18 | 19/25 | 83.7% | 78.4% | 5.73 | 12.4 | 2026-05-29 04:14 | 2 |
| 12 | `gemma-4-E2B-it-Q8_0` | gemma | 4/18 | 18/25 | 75.5% | 47.1% | 0.77 | 19.0 | 2026-05-29 01:33 | 2 |
| 13 | `Hermes-3-Llama-3.1-8B.Q4_K_M` | llama | 8/18 | 19/25 | 75.5% | 60.8% | 4.87 | 5.0 | 2026-05-29 00:22 | 12 |
| 14 | `NousResearch_Hermes-4-14B-Q4_K_S` | other | 7/18 | 15/25 | 59.2% | 52.9% | 3.95 | 9.6 | 2026-05-29 03:56 | 4 |
| 15 | `Hermes-4-14B-Q4_K_S` | other | 7/18 | 10/25 | 55.1% | 45.1% | 3.75 | 14.3 | 2026-05-29 03:50 | 2 |
| 16 | `DeepSeek-R1-0528-Qwen3-8B-Q3_K_L` | qwen | 0/18 | 8/25 | 16.3% | 15.7% | 0.04 | 7.7 | 2026-05-28 17:31 | 6 |
| 17 | `gemma-3-12B-it-QAT-Q4_0` | gemma | 0/18 | 2/25 | 3.9% | 3.9% | 0.93 | 23.8 | 2026-05-29 00:24 | 8 |
| 18 | `gemma-3-12b-it-Q8_0` | gemma | 0/18 | 2/25 | 3.9% | 3.9% | 1.33 | 17.4 | 2026-05-29 02:08 | 2 |
| 19 | `DeepHermes-AscensionMaze-RLAIF-8b-Atropos-Q4` | other | 0/18 | 2/25 | 3.9% | 3.9% | 16.52 | 25.6 | 2026-05-28 00:20 | 4 |
| 20 | `gpt-oss-20b-hermes.Q3_K_M` | other | 0/18 | 0/25 | 0.0% | 0.0% | 0.02 | 0.0 | 2026-05-29 04:14 | 6 |
| 21 | `gpt-oss-20b-hermes.Q8_0` | other | 0/18 | 0/25 | 0.0% | 0.0% | 0.02 | 0.0 | 2026-05-29 04:14 | 2 |

## Top 10 all-time best runs

Sorted by routing % (then p50 asc). A single great run doesn't make a model great, but tracking peaks tells you what's achievable on this hardware.

| # | Date | Model | Route% | p50 s | p95 s | TPS | Cases | Source |
|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | 2026-05-28 23:01 | `gemma-4-E4B-it-Q4_K_M` | 100.0% | 2.18 | 9.17 | 21.7 | 51 | flat |
| 2 | 2026-05-28 16:47 | `gemma-4-26B-A4B-it-Q4_K_M` | 100.0% | 2.42 | 14.71 | 15.3 | 51 | flat |
| 3 | 2026-05-29 00:37 | `gemma-4-26B-A4B-it-Q4_K_M` | 100.0% | 2.52 | 12.98 | 16.3 | 51 | flat |
| 4 | 2026-05-27 10:58 | `gemma-4-E4B-it-Q4_K_M` | 98.0% | 2.33 | 21.20 | 20.2 | 51 | flat |
| 5 | 2026-05-28 01:41 | `gemma-4-E4B-it-Q4_K_M` | 98.0% | 2.34 | 18.28 | 22.1 | 51 | flat |
| 6 | 2026-05-27 11:19 | `gemma-4-E4B-it-Q4_K_M` | 98.0% | 2.35 | 23.57 | 22.2 | 51 | flat |
| 7 | 2026-05-27 21:14 | `gemma-4-E4B-it-Q4_K_M` | 98.0% | 2.36 | 13.84 | 23.0 | 51 | flat |
| 8 | 2026-05-27 21:32 | `gemma-4-E4B-it-Q4_K_M` | 98.0% | 2.44 | 23.50 | 22.6 | 51 | flat |
| 9 | 2026-05-27 11:15 | `gemma-4-26B-A4B-it-Q4_K_M` | 98.0% | 2.77 | 20.98 | 16.9 | 51 | flat |
| 10 | 2026-05-28 01:46 | `gemma-4-26B-A4B-it-Q4_K_M` | 98.0% | 2.81 | 15.53 | 17.7 | 51 | flat |

## Full chronological log

Every run we have data for (130 total), newest first. ``vs peak`` shows the route% delta from this model's all-time best (0.0% = this run IS the peak).

| Date | Model | Route% | p50 s | TPS | Cases | vs peak | Source |
|---|---|---:|---:|---:|---:|---:|---|
| 2026-05-29 04:14 | `gpt-oss-20b-hermes.Q8_0` | 0.0% | 0.02 | 0.0 | 51 | **peak** | flat |
| 2026-05-29 04:14 | `gpt-oss-20b-hermes.Q3_K_M` | 0.0% | 0.02 | 0.0 | 51 | **peak** | flat |
| 2026-05-29 04:14 | `Hermes-4-14B-Q8_0` | 83.7% | 5.73 | 12.4 | 51 | **peak** | flat |
| 2026-05-29 03:56 | `NousResearch_Hermes-4-14B-Q4_K_S` | 59.2% | 3.95 | 9.6 | 51 | **peak** | flat |
| 2026-05-29 03:50 | `Hermes-4-14B-Q4_K_S` | 55.1% | 3.75 | 14.3 | 51 | **peak** | flat |
| 2026-05-29 03:25 | `Ministral-3-14B-Reasoning-2512-Q4_K_M` | 85.7% | 3.83 | 8.8 | 51 | **peak** | flat |
| 2026-05-29 02:17 | `Qwen3-Coder-30B-A3B-Instruct-Q3_K_L` | 95.9% | 3.08 | 13.8 | 51 | **peak** | flat |
| 2026-05-29 02:08 | `gemma-3-12b-it-Q8_0` | 0.0% | 1.33 | 17.4 | 51 | -3.9pp | flat |
| 2026-05-29 01:35 | `gemma-4-E4B-it-Q8_0` | 91.8% | 1.47 | 13.6 | 51 | **peak** | flat |
| 2026-05-29 01:33 | `gemma-4-E2B-it-Q8_0` | 75.5% | 0.77 | 19.0 | 51 | **peak** | flat |
| 2026-05-29 01:02 | `Qwen3-30B-A3B-Q4_K_M` | 98.0% | 16.46 | 29.1 | 51 | **peak** | flat |
| 2026-05-29 00:42 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | 98.0% | 3.03 | 15.8 | 51 | **peak** | flat |
| 2026-05-29 00:37 | `gemma-4-26B-A4B-it-Q4_K_M` | 100.0% | 2.52 | 16.3 | 51 | **peak** | flat |
| 2026-05-29 00:33 | `gpt-oss-20b-MXFP4` | 85.7% | 4.42 | 41.7 | 51 | **peak** | flat |
| 2026-05-29 00:24 | `gemma-3-12B-it-QAT-Q4_0` | 0.0% | 0.93 | 23.8 | 51 | -3.9pp | flat |
| 2026-05-29 00:22 | `Hermes-3-Llama-3.1-8B.Q4_K_M` | 75.5% | 4.87 | 5.0 | 51 | **peak** | flat |
| 2026-05-28 23:01 | `gemma-4-E4B-it-Q4_K_M` | 100.0% | 2.18 | 21.7 | 51 | **peak** | flat |
| 2026-05-28 22:58 | `gemma-4-E2B-it-Q4_K_M` | 85.7% | 1.32 | 28.7 | 51 | -6.1pp | flat |
| 2026-05-28 19:40 | `Ministral-3-14B-Reasoning-2512-Q4_K_M` | 81.6% | 3.80 | 7.1 | 51 | -4.1pp | flat |
| 2026-05-28 18:26 | `Ministral-3-14B-Reasoning-2512-Q4_K_M` | 0.0% | 1.19 | 7.0 | 51 | -85.7pp | flat |
| 2026-05-28 18:23 | `gpt-oss-20b-MXFP4` | 85.7% | 4.02 | 40.0 | 51 | **peak** | flat |
| 2026-05-28 18:13 | `Hermes-3-Llama-3.1-8B.Q4_K_M` | 75.5% | 5.17 | 4.9 | 51 | **peak** | flat |
| 2026-05-28 17:48 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | 98.0% | 2.85 | 13.7 | 51 | **peak** | flat |
| 2026-05-28 17:32 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | 0.0% | 0.02 | 0.0 | 51 | -98.0pp | flat |
| 2026-05-28 17:32 | `Hermes-3-Llama-3.1-8B.Q4_K_M` | 0.0% | 0.03 | 0.0 | 51 | -75.5pp | flat |
| 2026-05-28 17:31 | `DeepSeek-R1-0528-Qwen3-8B-Q3_K_L` | 16.3% | 0.04 | 7.7 | 51 | **peak** | flat |
| 2026-05-28 17:11 | `Hermes-3-Llama-3.1-8B.Q4_K_M` | 12.2% | 0.03 | 1.2 | 51 | -63.3pp | flat |
| 2026-05-28 17:03 | `gpt-oss-20b-MXFP4` | 83.7% | 3.96 | 38.8 | 51 | -2.0pp | flat |
| 2026-05-28 16:54 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | 95.9% | 2.75 | 10.8 | 51 | -2.0pp | flat |
| 2026-05-28 16:47 | `gemma-4-26B-A4B-it-Q4_K_M` | 100.0% | 2.42 | 15.3 | 51 | **peak** | flat |
| 2026-05-28 02:57 | `gemma-3-12B-it-QAT-Q4_0` | 0.0% | 1.21 | 24.9 | 51 | -3.9pp | flat |
| 2026-05-28 01:54 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | 95.9% | 4.84 | 11.7 | 51 | -2.0pp | flat |
| 2026-05-28 01:46 | `gemma-4-26B-A4B-it-Q4_K_M` | 98.0% | 2.81 | 17.7 | 51 | -2.0pp | flat |
| 2026-05-28 01:41 | `gemma-4-E4B-it-Q4_K_M` | 98.0% | 2.34 | 22.1 | 51 | -2.0pp | flat |
| 2026-05-28 01:37 | `gemma-4-E2B-it-Q4_K_M` | 91.8% | 1.34 | 28.2 | 51 | **peak** | flat |
| 2026-05-28 00:30 | `DeepSeek-R1-0528-Qwen3-8B-Q3_K_L` | 0.0% | 0.04 | 0.0 | 51 | -16.3pp | flat |
| 2026-05-28 00:23 | `gpt-oss-20b-hermes.Q3_K_M` | 0.0% | 0.03 | 0.0 | 51 | **peak** | flat |
| 2026-05-28 00:23 | `gpt-oss-20b-MXFP4` | 0.0% | 1.80 | 30.2 | 51 | -85.7pp | flat |
| 2026-05-28 00:20 | `DeepHermes-AscensionMaze-RLAIF-8b-Atropos-Q4` | 0.0% | 16.52 | 25.6 | 51 | -3.9pp | flat |
| 2026-05-28 00:03 | `Hermes-3-Llama-3.1-8B.Q4_K_M` | 28.6% | 0.04 | 5.8 | 51 | -46.9pp | flat |
| 2026-05-27 23:21 | `Ministral-3-14B-Reasoning-2512-Q4_K_M` | 0.0% | 1.12 | 5.8 | 51 | -85.7pp | flat |
| 2026-05-27 23:18 | `DeepSeek-R1-0528-Qwen3-8B-Q3_K_L` | 0.0% | 0.02 | 1.3 | 51 | -16.3pp | flat |
| 2026-05-27 23:13 | `gpt-oss-20b-hermes.Q3_K_M` | 0.0% | 0.02 | 0.0 | 51 | **peak** | flat |
| 2026-05-27 23:13 | `gpt-oss-20b-MXFP4` | 0.0% | 1.62 | 41.7 | 51 | -85.7pp | flat |
| 2026-05-27 23:11 | `DeepHermes-AscensionMaze-RLAIF-8b-Atropos-Q4` | 0.0% | 17.44 | 48.0 | 51 | -3.9pp | flat |
| 2026-05-27 22:52 | `NousResearch_Hermes-4-14B-Q4_K_S` | 46.9% | 3.26 | 4.2 | 51 | -12.2pp | flat |
| 2026-05-27 22:39 | `Hermes-3-Llama-3.1-8B.Q4_K_M` | 0.0% | 1.36 | 31.2 | 51 | -75.5pp | flat |
| 2026-05-27 22:30 | `Qwen3.6-35B-A3B-Q4_K_M` | 95.9% | 37.52 | 6.7 | 51 | **peak** | flat |
| 2026-05-27 21:46 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | 93.9% | 4.50 | 16.8 | 51 | -4.1pp | flat |
| 2026-05-27 21:39 | `gemma-4-26B-A4B-it-Q4_K_M` | 98.0% | 2.99 | 15.7 | 51 | -2.0pp | flat |
| 2026-05-27 21:34 | `gemma-3-12B-it-QAT-Q4_0` | 0.0% | 1.23 | 23.8 | 51 | -3.9pp | flat |
| 2026-05-27 21:32 | `gemma-4-E4B-it-Q4_K_M` | 98.0% | 2.44 | 22.6 | 51 | -2.0pp | flat |
| 2026-05-27 21:27 | `gemma-4-E2B-it-Q4_K_M` | 91.8% | 1.38 | 27.2 | 51 | **peak** | flat |
| 2026-05-27 21:16 | `gemma-3-12B-it-QAT-Q4_0` | 0.0% | 1.20 | 24.9 | 51 | -3.9pp | flat |
| 2026-05-27 21:14 | `gemma-4-E4B-it-Q4_K_M` | 98.0% | 2.36 | 23.0 | 51 | -2.0pp | flat |
| 2026-05-27 21:10 | `gemma-4-E2B-it-Q4_K_M` | 91.8% | 1.32 | 27.6 | 51 | **peak** | flat |
| 2026-05-27 20:42 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | 93.9% | 4.25 | 17.4 | 51 | -4.1pp | flat |
| 2026-05-27 20:35 | `gemma-4-E2B-it-Q4_K_M` | 91.8% | 1.32 | 26.0 | 51 | **peak** | flat |
| 2026-05-27 19:42 | `gemma-4-E2B-it-Q4_K_M` | 91.8% | 1.33 | 26.4 | 51 | **peak** | flat |
| 2026-05-27 14:42 | `gemma-4-E2B-it-Q4_K_M` | 89.8% | 1.38 | 20.0 | 51 | -2.0pp | flat |
| 2026-05-27 14:38 | `Qwen3.6-35B-A3B-Q4_K_M` | 95.9% | 37.18 | 6.8 | 51 | **peak** | flat |
| 2026-05-27 11:19 | `gemma-4-E4B-it-Q4_K_M` | 98.0% | 2.35 | 22.2 | 51 | -2.0pp | flat |
| 2026-05-27 11:15 | `gemma-4-26B-A4B-it-Q4_K_M` | 98.0% | 2.77 | 16.9 | 51 | -2.0pp | flat |
| 2026-05-27 10:58 | `gemma-4-E4B-it-Q4_K_M` | 98.0% | 2.33 | 20.2 | 51 | -2.0pp | flat |
| 2026-05-29 04:14 | `gpt-oss-20b-hermes.Q8_0` | 0.0% | 0.02 | 0.0 | 51 | **peak** | sweep |
| 2026-05-29 04:14 | `gpt-oss-20b-hermes.Q3_K_M` | 0.0% | 0.02 | 0.0 | 51 | **peak** | sweep |
| 2026-05-29 04:14 | `Hermes-4-14B-Q8_0` | 78.4% | 5.73 | 0.0 | 51 | -5.2pp | sweep |
| 2026-05-29 03:56 | `NousResearch_Hermes-4-14B-Q4_K_S` | 52.9% | 3.95 | 0.0 | 51 | -6.2pp | sweep |
| 2026-05-29 03:50 | `Hermes-4-14B-Q4_K_S` | 45.1% | 3.75 | 0.0 | 51 | -10.0pp | sweep |
| 2026-05-29 03:25 | `Ministral-3-14B-Reasoning-2512-Q4_K_M` | 74.5% | 3.83 | 0.0 | 51 | -11.2pp | sweep |
| 2026-05-29 02:17 | `Qwen3-Coder-30B-A3B-Instruct-Q3_K_L` | 90.2% | 3.08 | 0.0 | 51 | -5.7pp | sweep |
| 2026-05-29 02:08 | `gemma-3-12b-it-Q8_0` | 3.9% | 1.33 | 0.0 | 51 | **peak** | sweep |
| 2026-05-29 01:35 | `gemma-4-E4B-it-Q8_0` | 47.1% | 1.47 | 0.0 | 51 | -44.8pp | sweep |
| 2026-05-29 01:33 | `gemma-4-E2B-it-Q8_0` | 47.1% | 0.77 | 0.0 | 51 | -28.5pp | sweep |
| 2026-05-29 01:02 | `Qwen3-30B-A3B-Q4_K_M` | 92.2% | 16.46 | 0.0 | 51 | -5.8pp | sweep |
| 2026-05-29 00:42 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | 94.1% | 3.03 | 0.0 | 51 | -3.8pp | sweep |
| 2026-05-29 00:37 | `gemma-4-26B-A4B-it-Q4_K_M` | 94.1% | 2.52 | 0.0 | 51 | -5.9pp | sweep |
| 2026-05-29 00:33 | `gpt-oss-20b-MXFP4` | 72.5% | 4.42 | 0.0 | 51 | -13.2pp | sweep |
| 2026-05-29 00:24 | `gemma-3-12B-it-QAT-Q4_0` | 3.9% | 0.93 | 0.0 | 51 | **peak** | sweep |
| 2026-05-29 00:22 | `Hermes-3-Llama-3.1-8B.Q4_K_M` | 60.8% | 4.87 | 0.0 | 51 | -14.7pp | sweep |
| 2026-05-28 23:01 | `gemma-4-E4B-it-Q4_K_M` | 90.2% | 2.18 | 0.0 | 51 | -9.8pp | sweep |
| 2026-05-28 22:58 | `gemma-4-E2B-it-Q4_K_M` | 80.4% | 1.32 | 0.0 | 51 | -11.4pp | sweep |
| 2026-05-28 19:40 | `Ministral-3-14B-Reasoning-2512-Q4_K_M` | 66.7% | 3.80 | 0.0 | 51 | -19.0pp | sweep |
| 2026-05-28 18:26 | `Ministral-3-14B-Reasoning-2512-Q4_K_M` | 3.9% | 1.19 | 0.0 | 51 | -81.8pp | sweep |
| 2026-05-28 18:23 | `gpt-oss-20b-MXFP4` | 76.5% | 4.02 | 0.0 | 51 | -9.2pp | sweep |
| 2026-05-28 18:13 | `Hermes-3-Llama-3.1-8B.Q4_K_M` | 60.8% | 5.17 | 0.0 | 51 | -14.7pp | sweep |
| 2026-05-28 17:48 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | 90.2% | 2.85 | 0.0 | 51 | -7.8pp | sweep |
| 2026-05-28 17:32 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | 0.0% | 0.02 | 0.0 | 51 | -98.0pp | sweep |
| 2026-05-28 17:32 | `Hermes-3-Llama-3.1-8B.Q4_K_M` | 0.0% | 0.03 | 0.0 | 51 | -75.5pp | sweep |
| 2026-05-28 17:31 | `DeepSeek-R1-0528-Qwen3-8B-Q3_K_L` | 15.7% | 0.04 | 0.0 | 51 | -0.6pp | sweep |
| 2026-05-28 17:11 | `Hermes-3-Llama-3.1-8B.Q4_K_M` | 9.8% | 0.03 | 0.0 | 51 | -65.7pp | sweep |
| 2026-05-28 17:03 | `gpt-oss-20b-MXFP4` | 72.5% | 3.96 | 0.0 | 51 | -13.2pp | sweep |
| 2026-05-28 16:54 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | 90.2% | 2.75 | 0.0 | 51 | -7.8pp | sweep |
| 2026-05-28 16:47 | `gemma-4-26B-A4B-it-Q4_K_M` | 94.1% | 2.42 | 0.0 | 51 | -5.9pp | sweep |
| 2026-05-28 02:57 | `gemma-3-12B-it-QAT-Q4_0` | 3.9% | 1.21 | 0.0 | 51 | **peak** | sweep |
| 2026-05-28 01:54 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | 90.2% | 4.84 | 0.0 | 51 | -7.8pp | sweep |
| 2026-05-28 01:46 | `gemma-4-26B-A4B-it-Q4_K_M` | 96.1% | 2.81 | 0.0 | 51 | -3.9pp | sweep |
| 2026-05-28 01:41 | `gemma-4-E4B-it-Q4_K_M` | 90.2% | 2.34 | 0.0 | 51 | -9.8pp | sweep |
| 2026-05-28 01:37 | `gemma-4-E2B-it-Q4_K_M` | 88.2% | 1.34 | 0.0 | 51 | -3.6pp | sweep |
| 2026-05-28 00:30 | `DeepSeek-R1-0528-Qwen3-8B-Q3_K_L` | 0.0% | 0.04 | 0.0 | 51 | -16.3pp | sweep |
| 2026-05-28 00:23 | `gpt-oss-20b-hermes.Q3_K_M` | 0.0% | 0.03 | 0.0 | 51 | **peak** | sweep |
| 2026-05-28 00:23 | `gpt-oss-20b-MXFP4` | 3.9% | 1.80 | 0.0 | 51 | -81.8pp | sweep |
| 2026-05-28 00:20 | `DeepHermes-AscensionMaze-RLAIF-8b-Atropos-Q4` | 3.9% | 16.52 | 0.0 | 51 | **peak** | sweep |
| 2026-05-28 00:03 | `Hermes-3-Llama-3.1-8B.Q4_K_M` | 25.5% | 0.04 | 0.0 | 51 | -50.0pp | sweep |
| 2026-05-27 23:21 | `Ministral-3-14B-Reasoning-2512-Q4_K_M` | 3.9% | 1.12 | 0.0 | 51 | -81.8pp | sweep |
| 2026-05-27 23:18 | `DeepSeek-R1-0528-Qwen3-8B-Q3_K_L` | 0.0% | 0.02 | 0.0 | 51 | -16.3pp | sweep |
| 2026-05-27 23:13 | `gpt-oss-20b-hermes.Q3_K_M` | 0.0% | 0.02 | 0.0 | 51 | **peak** | sweep |
| 2026-05-27 23:13 | `gpt-oss-20b-MXFP4` | 3.9% | 1.62 | 0.0 | 51 | -81.8pp | sweep |
| 2026-05-27 23:11 | `DeepHermes-AscensionMaze-RLAIF-8b-Atropos-Q4` | 3.9% | 17.44 | 0.0 | 51 | **peak** | sweep |
| 2026-05-27 22:52 | `NousResearch_Hermes-4-14B-Q4_K_S` | 41.2% | 3.26 | 0.0 | 51 | -18.0pp | sweep |
| 2026-05-27 22:39 | `Hermes-3-Llama-3.1-8B.Q4_K_M` | 3.9% | 1.36 | 0.0 | 51 | -71.6pp | sweep |
| 2026-05-27 22:30 | `Qwen3.6-35B-A3B-Q4_K_M` | 94.1% | 37.52 | 0.0 | 51 | -1.8pp | sweep |
| 2026-05-27 21:46 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | 88.2% | 4.50 | 0.0 | 51 | -9.7pp | sweep |
| 2026-05-27 21:39 | `gemma-4-26B-A4B-it-Q4_K_M` | 94.1% | 2.99 | 0.0 | 51 | -5.9pp | sweep |
| 2026-05-27 21:34 | `gemma-3-12B-it-QAT-Q4_0` | 3.9% | 1.23 | 0.0 | 51 | **peak** | sweep |
| 2026-05-27 21:32 | `gemma-4-E4B-it-Q4_K_M` | 90.2% | 2.44 | 0.0 | 51 | -9.8pp | sweep |
| 2026-05-27 21:28 | `gemma-4-E2B-it-Q4_K_M` | 88.2% | 1.38 | 0.0 | 51 | -3.6pp | sweep |
| 2026-05-27 21:16 | `gemma-3-12B-it-QAT-Q4_0` | 3.9% | 1.20 | 0.0 | 51 | **peak** | sweep |
| 2026-05-27 21:14 | `gemma-4-E4B-it-Q4_K_M` | 92.2% | 2.36 | 0.0 | 51 | -7.8pp | sweep |
| 2026-05-27 21:10 | `gemma-4-E2B-it-Q4_K_M` | 88.2% | 1.32 | 0.0 | 51 | -3.6pp | sweep |
| 2026-05-27 20:42 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | 88.2% | 4.25 | 0.0 | 51 | -9.7pp | sweep |
| 2026-05-27 20:35 | `gemma-4-E2B-it-Q4_K_M` | 88.2% | 1.32 | 0.0 | 51 | -3.6pp | sweep |
| 2026-05-27 19:42 | `gemma-4-E2B-it-Q4_K_M` | 88.2% | 1.33 | 0.0 | 51 | -3.6pp | sweep |
| 2026-05-27 14:42 | `gemma-4-E2B-it-Q4_K_M` | 86.3% | 1.38 | 0.0 | 51 | -5.6pp | sweep |
| 2026-05-27 14:38 | `Qwen3.6-35B-A3B-Q4_K_M` | 94.1% | 37.18 | 0.0 | 51 | -1.8pp | sweep |
| 2026-05-27 11:19 | `gemma-4-E4B-it-Q4_K_M` | 92.2% | 2.35 | 0.0 | 51 | -7.8pp | sweep |
| 2026-05-27 11:15 | `gemma-4-26B-A4B-it-Q4_K_M` | 94.1% | 2.77 | 0.0 | 51 | -5.9pp | sweep |
| 2026-05-27 10:58 | `Qwen3.6-35B-A3B-Q4_K_M` | 88.2% | 2.33 | 0.0 | 51 | -7.7pp | sweep |
| 2026-05-27 10:53 | `gemma-4-E4B-it-Q4_K_M` | 92.2% | 2.51 | 0.0 | 51 | -7.8pp | sweep |
| 2026-05-27 10:49 | `gemma-4-26B-A4B-it-Q4_K_M` | 92.2% | 2.47 | 0.0 | 51 | -7.8pp | sweep |

_2 model(s) report **whitespace-estimate** tokens/sec — the adapter didn't surface a ``usage`` field for those runs. Real tokenizer counts land when the run was driven through llama-cpp / OpenAI / Anthropic adapters with usage reporting._
