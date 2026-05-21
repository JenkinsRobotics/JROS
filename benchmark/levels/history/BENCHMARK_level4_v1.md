# Level 4 — failure recovery + edge cases

- 10 cases; overall passing **3/10** (30%); surfaced-error **3/9**; no-hallucination **10/10**; recovered (where required) **0/1**; total 52.7s.

| # | Case | Tools | Surf | No-hal | Recov | Ans (short) | Time |
|---|---|---|---|---|---|---|---|
| 0 | run-python-syntax-error | file_read | ✗ | ✓ | — | I can't find the file you're referring to. | 3.95s |
| 1 | run-python-zero-division | run_python | ✗ | ✓ | — | I can't fix the bug because there is no file to read; the c… | 8.75s |
| 2 | read-missing-file | file_read | ✗ | ✓ | — | I couldn't find that file. | 1.30s |
| 3 | delete-missing-file | delete_file | ✗ | ✓ | — | I couldn't find that file to delete it. | 6.74s |
| 4 | calculate-divbyzero | - | ✗ | ✓ | — |  | 5.72s |
| 5 | write-and-fix-loop | file_write | ✓ | ✓ | ✗ | The file was written, but it triggered a syntax error due t… | 1.77s |
| 6 | search-then-no-denial | web_search | — | ✓ | — | Jaeger was created by Uber Technologies. | 9.11s |
| 7 | weather-unknown-location | get_weather | ✓ | ✓ | — | I'm sorry, but I couldn't find any weather information for … | 2.55s |
| 8 | recall-missing-key | recall | ✓ | ✓ | — | I don't have a value stored for that. | 6.35s |
| 9 | schedule-cancel-missing | cancel_schedule | ✗ | ✓ | — | I couldn't find a schedule named 'never_existed_demo_xyz' t… | 6.45s |
