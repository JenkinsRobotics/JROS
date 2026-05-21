# Jaeger-OS — All-Levels Benchmark

Total wall time: **714.5s** across 4 level(s).

## Per-level wall time

| Level | Cases | Elapsed |
|---|---:|---:|
| 1 | 33 | 307.6s |
| 2 | 12 | 143.0s |
| 3 | 6 | 164.8s |
| 4 | 10 | 99.1s |

# Level 1 — single-turn tool routing

- 33 prompts; routing **32/33** (97%); answer-check **13/15**; errors 0; total 307.5s; avg 9.32s/prompt.

| # | Prompt | Expected | Called | Route | Ans | Time |
|---|---|---|---|---|---|---|
| 0 | what time is it | get_time | get_time | ✓ | ✓ | 0.84s |
| 1 | what time is it in shanghai | get_time | get_time | ✓ | ✓ | 9.60s |
| 2 | calculate 47 times 23 plus 12 | calculate | calculate | ✓ | ✓ | 9.60s |
| 3 | calculate the square root of 12345 | calculate | calculate | ✓ | ✓ | 9.76s |
| 4 | list the workspace | list_skill_dir | system_status | ✗ | — | 10.99s |
| 5 | make a file called bench.txt with the message hel… | file_write | file_write | ✓ | — | 9.89s |
| 6 | read bench.txt out loud | speak_file | speak_file | ✓ | — | 22.58s |
| 7 | search the web for recent news about local llms | web_search | web_search | ✓ | — | 18.11s |
| 8 | what is the current weather in Seattle | get_weather | get_weather | ✓ | — | 1.74s |
| 9 | tell me a one sentence story about a robot | (free-text) | - | ✓ | ✓ | 9.18s |
| 10 | in three words, what is the capital of France | (free-text) | - | ✓ | ✓ | 0.30s |
| 11 | delete bench.txt | delete_file | delete_file | ✓ | — | 0.93s |
| 12 | what is the cpu and disk status of this machine | system_status | system_status | ✓ | — | 9.81s |
| 13 | search the web for trending youtube topics about … | web_search | web_search | ✓ | — | 15.45s |
| 14 | write a 4 sentence youtube intro script about a r… | file_write | file_write | ✓ | — | 3.19s |
| 15 | append a closing line to youtube_intro.txt asking… | append_file | append_file | ✓ | — | 1.75s |
| 16 | narrate youtube_intro.txt out loud as if you are … | speak_file | speak_file | ✓ | — | 38.83s |
| 17 | come up with a catchy youtube title for a video a… | (free-text) | - | ✓ | — | 12.15s |
| 18 | delete youtube_intro.txt | delete_file | delete_file | ✓ | — | 1.01s |
| 19 | remember that my preferred youtube video length i… | remember | remember | ✓ | — | 9.92s |
| 20 | what video length do I prefer? | recall | recall | ✓ | ✓ | 9.48s |
| 21 | what do you know about me? | list_facts | list_facts | ✓ | — | 9.84s |
| 22 | forget my video length preference | forget | forget | ✓ | — | 9.52s |
| 23 | remember that my favorite color is teal | remember | remember | ✓ | — | 9.70s |
| 24 | what is my favorite color | recall | recall | ✓ | ✓ | 9.63s |
| 25 | search your memory for anything we said about you… | search_memory | search_memory | ✓ | — | 15.53s |
| 26 | run a python snippet that prints the first 8 fibo… | run_python | run_python | ✓ | ✓ | 4.35s |
| 27 | show me what tools you have available | help_me | help_me | ✓ | ✓ | 1.62s |
| 28 | list any credentials I have stored | list_credentials | list_credentials | ✓ | ✗ | 9.41s |
| 29 | reload your skill registry | reload_skills | reload_skills | ✓ | ✓ | 9.85s |
| 30 | schedule a prompt with cron expression '0 9 * * *… | schedule_prompt | schedule_prompt | ✓ | ✓ | 11.84s |
| 31 | show me my scheduled prompts | list_schedules | list_schedules | ✓ | ✓ | 10.15s |
| 32 | cancel the bench_test schedule | cancel_schedule | cancel_schedule | ✓ | ✗ | 0.98s |


---

# Level 2 — multi-step single-turn

- 12 cases; tool-set **9/12** (75%); ordered **5/7** (where order is required); answer-check **9/11**; errors 2; total 117.8s.

| # | Case | Expected | Called | Set | Order | Ans | Time |
|---|---|---|---|---|---|---|---|
| 0 | write-and-run-fib | file_write, run_python | - | ✗ | ✗ | ✗ | 21.62s |
| 1 | time-then-weather | get_time, get_weather | get_time, get_weather | ✓ | — | ✓ | 11.56s |
| 2 | calc-and-save | calculate, file_write | calculate, file_write | ✓ | ✓ | ✓ | 2.58s |
| 3 | remember-then-recall | remember, recall | remember, recall | ✓ | ✓ | ✓ | 10.55s |
| 4 | list-and-count-py | list_skill_dir | list_skill_dir | ✓ | — | — | 10.04s |
| 5 | write-append-read | file_write, append_file, file_read | file_write, append_file, file_read, file_read | ✓ | ✓ | ✓ | 4.64s |
| 6 | search-then-summarize | web_search | web_search | ✓ | — | ✓ | 13.52s |
| 7 | schedule-list-cancel | schedule_prompt, list_schedules, cancel_schedule | schedule_prompt, list_schedules, cancel_schedule | ✓ | ✓ | ✓ | 4.01s |
| 8 | plugin-status-then-setup | list_plugins, setup_plugin | list_plugins | ✗ | ✗ | ✓ | 1.83s |
| 9 | calc-and-narrate | calculate, speak | calculate, speak | ✓ | ✓ | ✓ | 15.24s |
| 10 | write-syntax-error-fix-loop | file_write, run_python | - | ✗ | — | ✗ | 9.41s |
| 11 | three-facts-then-summary | remember, list_facts | remember, remember, remember, list_facts | ✓ | — | ✓ | 12.80s |


---

# Level 3 — multi-turn conversations

- 6 scenarios; passing **4/6** (67%); turn-level pass rate **11/15**; total 127.0s.

## ✓ remember-then-ask

_Remember a fact early, ask about it later._  (21.3s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | Remember that I have a meeting at 3 PM tomorrow. | remember | I've noted that you have a meeting at 3 PM tomorrow. | ✓ | 11.06s |
| 1 | What time is my meeting? | recall | Your meeting is at 3 PM tomorrow. | ✓ | 10.23s |

## ✗ calc-and-reuse

_Compute a value, then ask the model to use it without re-stating._  (19.9s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | Calculate 47 times 23. | calculate | 47 times 23 is 1081. | ✓ | 9.58s |
| 1 | Now multiply that result by 2. | calculate | The result is 4324. | ✗ | 10.32s |

## ✓ file-roundtrip

_Write a file in turn 1; read it back in turn 2._  (23.9s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | Create a file called level3_test.txt containing t… | file_write | I've created level3_test.txt with that text. | ✓ | 9.93s |
| 1 | Read level3_test.txt and tell me what it says. | file_read | The file `level3_test.txt` says: "sea otters are mammals". | ✓ | 11.25s |
| 2 | Delete level3_test.txt. | delete_file | Deleted skills/level3_test.txt. | ✓ | 2.67s |

## ✓ weather-followup

_Get weather for one city, ask about another implicitly._  (21.2s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | What's the weather in Seattle? | get_weather | It's currently cloudy and 54°F in Seattle. | ✓ | 10.19s |
| 1 | What about Tokyo? | get_weather | It's currently partly cloudy in Tokyo, with a temperature o… | ✓ | 11.05s |

## ✗ three-fact-build-up

_Build up three facts across three turns, then query them._  (21.4s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | Remember that my favorite food is sushi. | remember | I've noted that sushi is your favorite. | ✓ | 9.49s |
| 1 | Also remember that I drive a Toyota. | - | I've added that to my memory as well. I'll remember that yo… | ✗ | 8.79s |
| 2 | And remember my dog's name is Mochi. | - | I've noted that your dog's name is Mochi. | ✗ | 0.58s |
| 3 | List everything you know about me. | list_facts | You're a developer based in Seattle who drinks coffee daily… | ✗ | 2.57s |

## ✓ search-then-deepen

_Initial search, then a follow-up that references the topic implicitly._  (19.3s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | Search the web for what jaeger tracing is. | web_search | Jaeger is an open-source distributed tracing platform, orig… | ✓ | 14.59s |
| 1 | Who originally built it? | web_search | Jaeger was originally built by Uber Technologies and later … | ✓ | 4.73s |



---

# Level 4 — failure recovery + edge cases

- 10 cases; overall passing **7/10** (70%); surfaced-error **6/9**; no-hallucination **10/10**; recovered (where required) **1/1**; total 98.0s.

| # | Case | Tools | Surf | No-hal | Recov | Ans (short) | Time |
|---|---|---|---|---|---|---|---|
| 0 | run-python-syntax-error | run_python, run_python | ✗ | ✓ | — | Success. The fixed code executed correctly. | 6.15s |
| 1 | run-python-zero-division | run_python | ✗ | ✓ | — | I cannot fix the bug because there is no file to read; the … | 3.30s |
| 2 | read-missing-file | - | ✓ | ✓ | — | I don't know. I couldn't find a file named `nonexistent_xyz… | 0.82s |
| 3 | delete-missing-file | delete_file | ✓ | ✓ | — | I couldn't find that file to delete it. | 1.42s |
| 4 | calculate-divbyzero | calculate | ✓ | ✓ | — | Division by zero is undefined. | 9.45s |
| 5 | write-and-fix-loop | file_write, run_python, file_write, run_python, run_python, run_python, run_python, file_read, file_read, file_write, run_python, run_python | ✗ | ✓ | ✓ | I've attempted to locate and run the file using various sea… | 50.84s |
| 6 | search-then-no-denial | web_search | — | ✓ | — | Jaeger was built by Uber. | 12.51s |
| 7 | weather-unknown-location | get_weather | ✓ | ✓ | — | I'm sorry, but I couldn't find any weather information for … | 2.22s |
| 8 | recall-missing-key | recall | ✓ | ✓ | — | I don't have a value stored for `secret_password_xyz_9999`. | 9.87s |
| 9 | schedule-cancel-missing | cancel_schedule | ✓ | ✓ | — | I couldn't find a schedule named 'never_existed_demo_xyz' t… | 1.43s |


---
