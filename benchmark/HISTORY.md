# Jaeger-OS bench history

_Generated 2026-05-28T13:58:23 from 70 run(s) across `benchmark/sweep/` and `benchmark/flat/` — showing runs on/after **2026-05-27** (current benchmark generation)._

## Per-model leaderboard

Best routing accuracy each model has ever scored on this machine. ``Latest *`` columns reflect the most recent run.

| # | Model | Family | Best route% | Best pass% | Latest p50 s | Latest p95 s | Latest tok/s | Latest run | Runs |
|---|---|---|---:|---:|---:|---:|---:|---|---:|
| 1 | `gemma-4-E4B-it-Q4_K_M` | gemma | 98.0% | 92.2% | 2.34 | 18.28 | 22.1 | 2026-05-28 01:41 | 10 |
| 2 | `gemma-4-26B-A4B-it-Q4_K_M` | gemma | 98.0% | 96.1% | 2.81 | 15.53 | 17.7 | 2026-05-28 01:46 | 7 |
| 3 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | qwen | 95.9% | 90.2% | 4.84 | 17.87 | 11.7 | 2026-05-28 01:54 | 6 |
| 4 | `Qwen3.6-35B-A3B-Q4_K_M` | qwen | 95.9% | 94.1% | 37.52 | 61.75 | 6.7 | 2026-05-27 22:30 | 5 |
| 5 | `gemma-4-E2B-it-Q4_K_M` | gemma | 91.8% | 88.2% | 1.34 | 8.62 | 28.2 | 2026-05-28 01:37 | 12 |
| 6 | `NousResearch_Hermes-4-14B-Q4_K_S` | other | 46.9% | 41.2% | 3.26 | 107.58 | 4.2 | 2026-05-27 22:52 | 2 |
| 7 | `Hermes-3-Llama-3.1-8B.Q4_K_M` | llama | 28.6% | 25.5% | 0.04 | 55.39 | 5.8 | 2026-05-28 00:03 | 4 |
| 8 | `Ministral-3-14B-Reasoning-2512-Q4_K_M` | mistral | 3.9% | 3.9% | 1.12 | 4.13 | 5.8 | 2026-05-27 23:21 | 2 |
| 9 | `gemma-3-12B-it-QAT-Q4_0` | gemma | 3.9% | 3.9% | 1.21 | 8.86 | 24.9 | 2026-05-28 02:57 | 6 |
| 10 | `gpt-oss-20b-MXFP4` | other | 3.9% | 3.9% | 1.80 | 6.75 | 30.2 | 2026-05-28 00:23 | 4 |
| 11 | `DeepHermes-AscensionMaze-RLAIF-8b-Atropos-Q4` | other | 3.9% | 3.9% | 16.52 | 65.11 | 25.6 | 2026-05-28 00:20 | 4 |
| 12 | `gpt-oss-20b-hermes.Q3_K_M` | other | 0.0% | 0.0% | 0.03 | 0.03 | 0.0 | 2026-05-28 00:23 | 4 |
| 13 | `DeepSeek-R1-0528-Qwen3-8B-Q3_K_L` | qwen | 0.0% | 0.0% | 0.04 | 69.04 | 0.0 | 2026-05-28 00:30 | 4 |

## Top 10 all-time best runs

Sorted by routing % (then p50 asc). A single great run doesn't make a model great, but tracking peaks tells you what's achievable on this hardware.

| # | Date | Model | Route% | p50 s | p95 s | TPS | Cases | Source |
|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | 2026-05-27 10:58 | `gemma-4-E4B-it-Q4_K_M` | 98.0% | 2.33 | 21.20 | 20.2 | 51 | flat |
| 2 | 2026-05-28 01:41 | `gemma-4-E4B-it-Q4_K_M` | 98.0% | 2.34 | 18.28 | 22.1 | 51 | flat |
| 3 | 2026-05-27 11:19 | `gemma-4-E4B-it-Q4_K_M` | 98.0% | 2.35 | 23.57 | 22.2 | 51 | flat |
| 4 | 2026-05-27 21:14 | `gemma-4-E4B-it-Q4_K_M` | 98.0% | 2.36 | 13.84 | 23.0 | 51 | flat |
| 5 | 2026-05-27 21:32 | `gemma-4-E4B-it-Q4_K_M` | 98.0% | 2.44 | 23.50 | 22.6 | 51 | flat |
| 6 | 2026-05-27 11:15 | `gemma-4-26B-A4B-it-Q4_K_M` | 98.0% | 2.77 | 20.98 | 16.9 | 51 | flat |
| 7 | 2026-05-28 01:46 | `gemma-4-26B-A4B-it-Q4_K_M` | 98.0% | 2.81 | 15.53 | 17.7 | 51 | flat |
| 8 | 2026-05-27 21:39 | `gemma-4-26B-A4B-it-Q4_K_M` | 98.0% | 2.99 | 15.22 | 15.7 | 51 | flat |
| 9 | 2026-05-28 01:46 | `gemma-4-26B-A4B-it-Q4_K_M` | 96.1% | 2.81 | 0.00 | 0.0 | 51 | sweep |
| 10 | 2026-05-28 01:54 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | 95.9% | 4.84 | 17.87 | 11.7 | 51 | flat |

## Full chronological log

Every run we have data for (70 total), newest first. ``vs peak`` shows the route% delta from this model's all-time best (0.0% = this run IS the peak).

| Date | Model | Route% | p50 s | TPS | Cases | vs peak | Source |
|---|---|---:|---:|---:|---:|---:|---|
| 2026-05-28 02:57 | `gemma-3-12B-it-QAT-Q4_0` | 0.0% | 1.21 | 24.9 | 51 | -3.9pp | flat |
| 2026-05-28 01:54 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | 95.9% | 4.84 | 11.7 | 51 | **peak** | flat |
| 2026-05-28 01:46 | `gemma-4-26B-A4B-it-Q4_K_M` | 98.0% | 2.81 | 17.7 | 51 | **peak** | flat |
| 2026-05-28 01:41 | `gemma-4-E4B-it-Q4_K_M` | 98.0% | 2.34 | 22.1 | 51 | **peak** | flat |
| 2026-05-28 01:37 | `gemma-4-E2B-it-Q4_K_M` | 91.8% | 1.34 | 28.2 | 51 | **peak** | flat |
| 2026-05-28 00:30 | `DeepSeek-R1-0528-Qwen3-8B-Q3_K_L` | 0.0% | 0.04 | 0.0 | 51 | **peak** | flat |
| 2026-05-28 00:23 | `gpt-oss-20b-hermes.Q3_K_M` | 0.0% | 0.03 | 0.0 | 51 | **peak** | flat |
| 2026-05-28 00:23 | `gpt-oss-20b-MXFP4` | 0.0% | 1.80 | 30.2 | 51 | -3.9pp | flat |
| 2026-05-28 00:20 | `DeepHermes-AscensionMaze-RLAIF-8b-Atropos-Q4` | 0.0% | 16.52 | 25.6 | 51 | -3.9pp | flat |
| 2026-05-28 00:03 | `Hermes-3-Llama-3.1-8B.Q4_K_M` | 28.6% | 0.04 | 5.8 | 51 | **peak** | flat |
| 2026-05-27 23:21 | `Ministral-3-14B-Reasoning-2512-Q4_K_M` | 0.0% | 1.12 | 5.8 | 51 | -3.9pp | flat |
| 2026-05-27 23:18 | `DeepSeek-R1-0528-Qwen3-8B-Q3_K_L` | 0.0% | 0.02 | 1.3 | 51 | **peak** | flat |
| 2026-05-27 23:13 | `gpt-oss-20b-hermes.Q3_K_M` | 0.0% | 0.02 | 0.0 | 51 | **peak** | flat |
| 2026-05-27 23:13 | `gpt-oss-20b-MXFP4` | 0.0% | 1.62 | 41.7 | 51 | -3.9pp | flat |
| 2026-05-27 23:11 | `DeepHermes-AscensionMaze-RLAIF-8b-Atropos-Q4` | 0.0% | 17.44 | 48.0 | 51 | -3.9pp | flat |
| 2026-05-27 22:52 | `NousResearch_Hermes-4-14B-Q4_K_S` | 46.9% | 3.26 | 4.2 | 51 | **peak** | flat |
| 2026-05-27 22:39 | `Hermes-3-Llama-3.1-8B.Q4_K_M` | 0.0% | 1.36 | 31.2 | 51 | -28.6pp | flat |
| 2026-05-27 22:30 | `Qwen3.6-35B-A3B-Q4_K_M` | 95.9% | 37.52 | 6.7 | 51 | **peak** | flat |
| 2026-05-27 21:46 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | 93.9% | 4.50 | 16.8 | 51 | -2.0pp | flat |
| 2026-05-27 21:39 | `gemma-4-26B-A4B-it-Q4_K_M` | 98.0% | 2.99 | 15.7 | 51 | **peak** | flat |
| 2026-05-27 21:34 | `gemma-3-12B-it-QAT-Q4_0` | 0.0% | 1.23 | 23.8 | 51 | -3.9pp | flat |
| 2026-05-27 21:32 | `gemma-4-E4B-it-Q4_K_M` | 98.0% | 2.44 | 22.6 | 51 | **peak** | flat |
| 2026-05-27 21:27 | `gemma-4-E2B-it-Q4_K_M` | 91.8% | 1.38 | 27.2 | 51 | **peak** | flat |
| 2026-05-27 21:16 | `gemma-3-12B-it-QAT-Q4_0` | 0.0% | 1.20 | 24.9 | 51 | -3.9pp | flat |
| 2026-05-27 21:14 | `gemma-4-E4B-it-Q4_K_M` | 98.0% | 2.36 | 23.0 | 51 | **peak** | flat |
| 2026-05-27 21:10 | `gemma-4-E2B-it-Q4_K_M` | 91.8% | 1.32 | 27.6 | 51 | **peak** | flat |
| 2026-05-27 20:42 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | 93.9% | 4.25 | 17.4 | 51 | -2.0pp | flat |
| 2026-05-27 20:35 | `gemma-4-E2B-it-Q4_K_M` | 91.8% | 1.32 | 26.0 | 51 | **peak** | flat |
| 2026-05-27 19:42 | `gemma-4-E2B-it-Q4_K_M` | 91.8% | 1.33 | 26.4 | 51 | **peak** | flat |
| 2026-05-27 14:42 | `gemma-4-E2B-it-Q4_K_M` | 89.8% | 1.38 | 20.0 | 51 | -2.0pp | flat |
| 2026-05-27 14:38 | `Qwen3.6-35B-A3B-Q4_K_M` | 95.9% | 37.18 | 6.8 | 51 | **peak** | flat |
| 2026-05-27 11:19 | `gemma-4-E4B-it-Q4_K_M` | 98.0% | 2.35 | 22.2 | 51 | **peak** | flat |
| 2026-05-27 11:15 | `gemma-4-26B-A4B-it-Q4_K_M` | 98.0% | 2.77 | 16.9 | 51 | **peak** | flat |
| 2026-05-27 10:58 | `gemma-4-E4B-it-Q4_K_M` | 98.0% | 2.33 | 20.2 | 51 | **peak** | flat |
| 2026-05-28 02:57 | `gemma-3-12B-it-QAT-Q4_0` | 3.9% | 1.21 | 0.0 | 51 | **peak** | sweep |
| 2026-05-28 01:54 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | 90.2% | 4.84 | 0.0 | 51 | -5.7pp | sweep |
| 2026-05-28 01:46 | `gemma-4-26B-A4B-it-Q4_K_M` | 96.1% | 2.81 | 0.0 | 51 | -1.9pp | sweep |
| 2026-05-28 01:41 | `gemma-4-E4B-it-Q4_K_M` | 90.2% | 2.34 | 0.0 | 51 | -7.8pp | sweep |
| 2026-05-28 01:37 | `gemma-4-E2B-it-Q4_K_M` | 88.2% | 1.34 | 0.0 | 51 | -3.6pp | sweep |
| 2026-05-28 00:30 | `DeepSeek-R1-0528-Qwen3-8B-Q3_K_L` | 0.0% | 0.04 | 0.0 | 51 | **peak** | sweep |
| 2026-05-28 00:23 | `gpt-oss-20b-hermes.Q3_K_M` | 0.0% | 0.03 | 0.0 | 51 | **peak** | sweep |
| 2026-05-28 00:23 | `gpt-oss-20b-MXFP4` | 3.9% | 1.80 | 0.0 | 51 | **peak** | sweep |
| 2026-05-28 00:20 | `DeepHermes-AscensionMaze-RLAIF-8b-Atropos-Q4` | 3.9% | 16.52 | 0.0 | 51 | **peak** | sweep |
| 2026-05-28 00:03 | `Hermes-3-Llama-3.1-8B.Q4_K_M` | 25.5% | 0.04 | 0.0 | 51 | -3.1pp | sweep |
| 2026-05-27 23:21 | `Ministral-3-14B-Reasoning-2512-Q4_K_M` | 3.9% | 1.12 | 0.0 | 51 | **peak** | sweep |
| 2026-05-27 23:18 | `DeepSeek-R1-0528-Qwen3-8B-Q3_K_L` | 0.0% | 0.02 | 0.0 | 51 | **peak** | sweep |
| 2026-05-27 23:13 | `gpt-oss-20b-hermes.Q3_K_M` | 0.0% | 0.02 | 0.0 | 51 | **peak** | sweep |
| 2026-05-27 23:13 | `gpt-oss-20b-MXFP4` | 3.9% | 1.62 | 0.0 | 51 | **peak** | sweep |
| 2026-05-27 23:11 | `DeepHermes-AscensionMaze-RLAIF-8b-Atropos-Q4` | 3.9% | 17.44 | 0.0 | 51 | **peak** | sweep |
| 2026-05-27 22:52 | `NousResearch_Hermes-4-14B-Q4_K_S` | 41.2% | 3.26 | 0.0 | 51 | -5.8pp | sweep |
| 2026-05-27 22:39 | `Hermes-3-Llama-3.1-8B.Q4_K_M` | 3.9% | 1.36 | 0.0 | 51 | -24.6pp | sweep |
| 2026-05-27 22:30 | `Qwen3.6-35B-A3B-Q4_K_M` | 94.1% | 37.52 | 0.0 | 51 | -1.8pp | sweep |
| 2026-05-27 21:46 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | 88.2% | 4.50 | 0.0 | 51 | -7.7pp | sweep |
| 2026-05-27 21:39 | `gemma-4-26B-A4B-it-Q4_K_M` | 94.1% | 2.99 | 0.0 | 51 | -3.8pp | sweep |
| 2026-05-27 21:34 | `gemma-3-12B-it-QAT-Q4_0` | 3.9% | 1.23 | 0.0 | 51 | **peak** | sweep |
| 2026-05-27 21:32 | `gemma-4-E4B-it-Q4_K_M` | 90.2% | 2.44 | 0.0 | 51 | -7.8pp | sweep |
| 2026-05-27 21:28 | `gemma-4-E2B-it-Q4_K_M` | 88.2% | 1.38 | 0.0 | 51 | -3.6pp | sweep |
| 2026-05-27 21:16 | `gemma-3-12B-it-QAT-Q4_0` | 3.9% | 1.20 | 0.0 | 51 | **peak** | sweep |
| 2026-05-27 21:14 | `gemma-4-E4B-it-Q4_K_M` | 92.2% | 2.36 | 0.0 | 51 | -5.8pp | sweep |
| 2026-05-27 21:10 | `gemma-4-E2B-it-Q4_K_M` | 88.2% | 1.32 | 0.0 | 51 | -3.6pp | sweep |
| 2026-05-27 20:42 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | 88.2% | 4.25 | 0.0 | 51 | -7.7pp | sweep |
| 2026-05-27 20:35 | `gemma-4-E2B-it-Q4_K_M` | 88.2% | 1.32 | 0.0 | 51 | -3.6pp | sweep |
| 2026-05-27 19:42 | `gemma-4-E2B-it-Q4_K_M` | 88.2% | 1.33 | 0.0 | 51 | -3.6pp | sweep |
| 2026-05-27 14:42 | `gemma-4-E2B-it-Q4_K_M` | 86.3% | 1.38 | 0.0 | 51 | -5.6pp | sweep |
| 2026-05-27 14:38 | `Qwen3.6-35B-A3B-Q4_K_M` | 94.1% | 37.18 | 0.0 | 51 | -1.8pp | sweep |
| 2026-05-27 11:19 | `gemma-4-E4B-it-Q4_K_M` | 92.2% | 2.35 | 0.0 | 51 | -5.8pp | sweep |
| 2026-05-27 11:15 | `gemma-4-26B-A4B-it-Q4_K_M` | 94.1% | 2.77 | 0.0 | 51 | -3.8pp | sweep |
| 2026-05-27 10:58 | `Qwen3.6-35B-A3B-Q4_K_M` | 88.2% | 2.33 | 0.0 | 51 | -7.7pp | sweep |
| 2026-05-27 10:53 | `gemma-4-E4B-it-Q4_K_M` | 92.2% | 2.51 | 0.0 | 51 | -5.8pp | sweep |
| 2026-05-27 10:49 | `gemma-4-26B-A4B-it-Q4_K_M` | 92.2% | 2.47 | 0.0 | 51 | -5.8pp | sweep |

_2 model(s) report **whitespace-estimate** tokens/sec — the adapter didn't surface a ``usage`` field for those runs. Real tokenizer counts land when the run was driven through llama-cpp / OpenAI / Anthropic adapters with usage reporting._
