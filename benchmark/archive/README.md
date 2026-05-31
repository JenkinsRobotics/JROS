# Archived bench artifacts

Frozen results from before the 2026-05-25 flat-corpus cutover. Kept
for historical reference; not read by any current tool.

| Dir | Era | Notes |
|---|---|---|
| `baseline/` | pre-May-25, 4-level capture | `level{1..4}.log` + `*_rows.jsonl` from the original Hermes-style level corpus. `diff_report.md` captured a Phase-9 vs legacy comparison. |
| `legacy/` | May 23 | per-level rows from the pre-Phase-9 (pydantic-ai) agent loop, before the JaegerAgent rewrite. |
| `jaeger_agent/` | May 23 | per-level rows from early JaegerAgent runs. |
| `legacy_l1_postfix/` | May 23 | one-off re-run of level-1 after a parser fix. |
| `jaeger_agent_l1_postfix/` | May 23 | same, on the new agent. |

For current results see `../sweep/` (multi-model) and `../flat/` (per-run).
