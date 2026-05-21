# Level 2 — multi-step single-turn

- 12 cases; tool-set **4/12** (33%); ordered **0/7** (where order is required); answer-check **6/11**; errors 0; total 76.3s.

| # | Case | Expected | Called | Set | Order | Ans | Time |
|---|---|---|---|---|---|---|---|
| 0 | write-and-run-fib | file_write, run_python | file_write | ✗ | ✗ | ✗ | 8.52s |
| 1 | time-then-weather | get_time, get_weather | get_time, get_weather | ✓ | — | ✓ | 7.85s |
| 2 | calc-and-save | calculate, file_write | calculate | ✗ | ✗ | ✓ | 1.19s |
| 3 | remember-then-recall | remember, recall | remember | ✗ | ✗ | ✗ | 6.43s |
| 4 | list-and-count-py | list_skill_dir | list_skill_dir | ✓ | — | — | 6.29s |
| 5 | write-append-read | file_write, append_file, file_read | file_write | ✗ | ✗ | ✗ | 6.39s |
| 6 | search-then-summarize | web_search | web_search | ✓ | — | ✓ | 9.06s |
| 7 | schedule-list-cancel | schedule_prompt, list_schedules, cancel_schedule | schedule_prompt | ✗ | ✗ | ✓ | 2.11s |
| 8 | plugin-status-then-setup | list_plugins, setup_plugin | list_plugins | ✗ | ✗ | ✓ | 6.95s |
| 9 | calc-and-narrate | calculate, speak | calculate | ✗ | ✗ | ✗ | 6.17s |
| 10 | write-syntax-error-fix-loop | file_write, run_python | file_write | ✗ | — | ✗ | 6.68s |
| 11 | three-facts-then-summary | remember, list_facts | remember, remember, remember, list_facts | ✓ | — | ✓ | 8.67s |
