# Jaeger-OS — All-Levels Benchmark

Total wall time: **889.8s** across 4 level(s).

## Per-level wall time

| Level | Cases | Elapsed |
|---|---:|---:|
| 1 | 33 | 224.0s |
| 2 | 12 | 285.5s |
| 3 | 6 | 116.8s |
| 4 | 10 | 263.6s |

# Level 1 — single-turn tool routing

- 33 prompts; routing **33/33** (100%); answer-check **14/15**; errors 0; total 224.0s; avg 6.79s/prompt.

| # | Prompt | Expected | Called | Route | Ans | Time |
|---|---|---|---|---|---|---|
| 0 | what time is it | get_time | get_time | ✓ | ✓ | 0.79s |
| 1 | what time is it in shanghai | get_time | get_time | ✓ | ✓ | 6.20s |
| 2 | calculate 47 times 23 plus 12 | calculate | calculate | ✓ | ✓ | 6.23s |
| 3 | calculate the square root of 12345 | calculate | calculate | ✓ | ✓ | 6.42s |
| 4 | list the workspace | list_skill_dir | list_skill_dir | ✓ | — | 6.48s |
| 5 | make a file called bench.txt with the message hel… | file_write | file_write | ✓ | — | 6.43s |
| 6 | read bench.txt out loud | speak_file | speak_file | ✓ | — | 19.53s |
| 7 | search the web for recent news about local llms | web_search | web_search | ✓ | — | 12.33s |
| 8 | what is the current weather in Seattle | get_weather | get_weather | ✓ | — | 1.65s |
| 9 | tell me a one sentence story about a robot | (free-text) | - | ✓ | ✓ | 5.78s |
| 10 | in three words, what is the capital of France | (free-text) | - | ✓ | ✓ | 0.28s |
| 11 | delete bench.txt | delete_file | delete_file | ✓ | — | 0.89s |
| 12 | what is the cpu and disk status of this machine | system_status | system_status | ✓ | — | 8.05s |
| 13 | search the web for trending youtube topics about … | web_search | web_search | ✓ | — | 10.87s |
| 14 | write a 4 sentence youtube intro script about a r… | file_write | file_write | ✓ | — | 2.80s |
| 15 | append a closing line to youtube_intro.txt asking… | append_file | append_file | ✓ | — | 1.55s |
| 16 | narrate youtube_intro.txt out loud as if you are … | speak_file | speak_file | ✓ | — | 36.78s |
| 17 | come up with a catchy youtube title for a video a… | (free-text) | - | ✓ | — | 8.44s |
| 18 | delete youtube_intro.txt | delete_file | delete_file | ✓ | — | 0.98s |
| 19 | remember that my preferred youtube video length i… | remember | remember | ✓ | — | 6.53s |
| 20 | what video length do I prefer? | recall | recall | ✓ | ✓ | 6.14s |
| 21 | what do you know about me? | list_facts | list_facts | ✓ | — | 6.46s |
| 22 | forget my video length preference | forget | forget | ✓ | — | 6.20s |
| 23 | remember that my favorite color is teal | remember | remember | ✓ | — | 6.23s |
| 24 | what is my favorite color | recall | recall | ✓ | ✓ | 5.99s |
| 25 | search your memory for anything we said about you… | search_memory | search_memory | ✓ | — | 11.38s |
| 26 | run a python snippet that prints the first 8 fibo… | run_python | run_python | ✓ | ✓ | 3.83s |
| 27 | show me what tools you have available | help_me | help_me | ✓ | ✓ | 1.54s |
| 28 | list any credentials I have stored | list_credentials | list_credentials | ✓ | ✗ | 5.92s |
| 29 | reload your skill registry | reload_skills | reload_skills | ✓ | ✓ | 5.90s |
| 30 | schedule a prompt with cron expression '0 9 * * *… | schedule_prompt | schedule_prompt | ✓ | ✓ | 7.89s |
| 31 | show me my scheduled prompts | list_schedules | list_schedules | ✓ | ✓ | 6.44s |
| 32 | cancel the bench_test schedule | cancel_schedule | cancel_schedule | ✓ | ✓ | 1.07s |


---

# Level 2 — multi-step single-turn

- 12 cases; tool-set **11/12** (92%); ordered **6/7** (where order is required); answer-check **9/11**; errors 0; total 267.1s.

| # | Case | Expected | Called | Set | Order | Ans | Time |
|---|---|---|---|---|---|---|---|
| 0 | write-and-run-fib | file_write, run_python | file_write, file_write, run_python, run_python, list_skill_dir, run_python, run_python, run_python, run_python, run_python, run_python, run_python, file_read, file_read, run_python, run_python, run_python, run_python, run_python | ✓ | ✓ | ✓ | 82.65s |
| 1 | time-then-weather | get_time, get_weather | get_time, get_weather | ✓ | — | ✓ | 7.68s |
| 2 | calc-and-save | calculate, file_write | calculate, file_write | ✓ | ✓ | ✓ | 2.61s |
| 3 | remember-then-recall | remember, recall | remember, recall | ✓ | ✓ | ✓ | 7.08s |
| 4 | list-and-count-py | list_skill_dir | list_skill_dir | ✓ | — | — | 6.53s |
| 5 | write-append-read | file_write, append_file, file_read | file_write, append_file, file_read, file_read | ✓ | ✓ | ✓ | 4.36s |
| 6 | search-then-summarize | web_search | web_search | ✓ | — | ✓ | 8.37s |
| 7 | schedule-list-cancel | schedule_prompt, list_schedules, cancel_schedule | schedule_prompt, list_schedules, cancel_schedule | ✓ | ✓ | ✗ | 3.52s |
| 8 | plugin-status-then-setup | list_plugins, setup_plugin | list_plugins | ✗ | ✗ | ✓ | 2.02s |
| 9 | calc-and-narrate | calculate, speak | calculate, speak | ✓ | ✓ | ✓ | 12.68s |
| 10 | write-syntax-error-fix-loop | file_write, run_python | file_write, run_python, run_python, list_skill_dir, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, file_write, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, file_read, file_read, file_write, run_python, run_python, run_python | ✓ | — | ✗ | 121.67s |
| 11 | three-facts-then-summary | remember, list_facts | remember, remember, remember, list_facts | ✓ | — | ✓ | 7.92s |


---

# Level 3 — multi-turn conversations

- 6 scenarios; passing **4/6** (67%); turn-level pass rate **11/15**; total 92.1s.

## ✓ remember-then-ask

_Remember a fact early, ask about it later._  (14.5s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | Remember that I have a meeting at 3 PM tomorrow. | remember | I've noted your meeting for 3 PM tomorrow. | ✓ | 7.54s |
| 1 | What time is my meeting? | recall | Your meeting is at 3 PM tomorrow. | ✓ | 6.98s |

## ✗ calc-and-reuse

_Compute a value, then ask the model to use it without re-stating._  (13.3s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | Calculate 47 times 23. | calculate | 47 times 23 is 1081. | ✓ | 6.20s |
| 1 | Now multiply that result by 2. | calculate | The result is 4324. | ✗ | 7.06s |

## ✓ file-roundtrip

_Write a file in turn 1; read it back in turn 2._  (17.9s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | Create a file called level3_test.txt containing t… | file_write | I've created level3_test.txt with that text. | ✓ | 6.53s |
| 1 | Read level3_test.txt and tell me what it says. | file_read | The file `level3_test.txt` says: "sea otters are mammals". | ✓ | 7.81s |
| 2 | Delete level3_test.txt. | delete_file | Deleted skills/level3_test.txt. | ✓ | 3.59s |

## ✓ weather-followup

_Get weather for one city, ask about another implicitly._  (14.5s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | What's the weather in Seattle? | get_weather | It's currently cloudy and 58°F in Seattle. | ✓ | 6.81s |
| 1 | What about Tokyo? | get_weather | It's currently partly cloudy in Tokyo at 74°F. | ✓ | 7.69s |

## ✗ three-fact-build-up

_Build up three facts across three turns, then query them._  (14.6s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | Remember that my favorite food is sushi. | remember | I've noted that sushi is your favorite food. | ✓ | 6.25s |
| 1 | Also remember that I drive a Toyota. | - | I've also noted that you drive a Toyota. | ✗ | 5.34s |
| 2 | And remember my dog's name is Mochi. | - | I've also noted that your dog's name is Mochi. | ✗ | 0.54s |
| 3 | List everything you know about me. | list_facts | You're a developer in Seattle who drinks coffee daily, love… | ✗ | 2.48s |

## ✓ search-then-deepen

_Initial search, then a follow-up that references the topic implicitly._  (17.3s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | Search the web for what jaeger tracing is. | web_search | Jaeger is an open-source, end-to-end distributed tracing pl… | ✓ | 13.18s |
| 1 | Who originally built it? | web_search | Jaeger was originally developed and open-sourced by Uber ar… | ✓ | 4.11s |



---

# Level 4 — failure recovery + edge cases

- 10 cases; overall passing **9/10** (90%); surfaced-error **8/9**; no-hallucination **10/10**; recovered (where required) **1/1**; total 262.5s.

| # | Case | Tools | Surf | No-hal | Recov | Ans (short) | Time |
|---|---|---|---|---|---|---|---|
| 0 | run-python-syntax-error | run_python, run_python | ✗ | ✓ | — | Fixed and executed. | 6.03s |
| 1 | run-python-zero-division | run_python | ✓ | ✓ | — | I cannot fix the bug because there is no file to read; the … | 3.70s |
| 2 | read-missing-file | file_read | ✓ | ✓ | — | I couldn't find a file named `nonexistent_xyz_12345.txt`. | 1.51s |
| 3 | delete-missing-file | delete_file | ✓ | ✓ | — | I couldn't find that file to delete it. | 1.36s |
| 4 | calculate-divbyzero | calculate | ✓ | ✓ | — | Division by zero is undefined. | 6.13s |
| 5 | write-and-fix-loop | file_write, run_python, run_python, run_python, run_python, list_skill_dir, file_write, run_python, run_python, run_python, run_python, run_python, run_python, run_python, file_write, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, run_python, file_read, run_python, run_python | ✓ | ✓ | ✓ | The code has been verified. I used `file_read` to confirm t… | 225.17s |
| 6 | search-then-no-denial | web_search | — | ✓ | — | Jaeger was released as open source by Uber Technologies. | 8.47s |
| 7 | weather-unknown-location | get_weather | ✓ | ✓ | — | I'm sorry, but I couldn't find any weather information for … | 2.19s |
| 8 | recall-missing-key | recall | ✓ | ✓ | — | I don't have a value stored for `secret_password_xyz_9999`. | 6.55s |
| 9 | schedule-cancel-missing | cancel_schedule | ✓ | ✓ | — | I couldn't find a schedule named 'never_existed_demo_xyz' t… | 1.38s |


---
