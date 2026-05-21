# Jaeger-OS — All-Levels Benchmark

Total wall time: **607.8s** across 4 level(s).

## Per-level wall time

| Level | Cases | Elapsed |
|---|---:|---:|
| 1 | 33 | 233.2s |
| 2 | 12 | 197.7s |
| 3 | 6 | 114.6s |
| 4 | 10 | 62.3s |

# Level 1 — single-turn tool routing

- 33 prompts; routing **33/33** (100%); answer-check **14/15**; errors 0; total 233.2s; avg 7.07s/prompt.

| # | Prompt | Expected | Called | Route | Ans | Time |
|---|---|---|---|---|---|---|
| 0 | what time is it | get_time | get_time | ✓ | ✓ | 0.79s |
| 1 | what time is it in shanghai | get_time | get_time | ✓ | ✓ | 6.16s |
| 2 | calculate 47 times 23 plus 12 | calculate | calculate | ✓ | ✓ | 6.79s |
| 3 | calculate the square root of 12345 | calculate | calculate | ✓ | ✓ | 8.78s |
| 4 | list the workspace | list_skill_dir | list_skill_dir | ✓ | — | 6.57s |
| 5 | make a file called bench.txt with the message hel… | file_write | file_write | ✓ | — | 6.87s |
| 6 | read bench.txt out loud | speak_file | speak_file | ✓ | — | 19.23s |
| 7 | search the web for recent news about local llms | web_search | web_search | ✓ | — | 18.34s |
| 8 | what is the current weather in Seattle | get_weather | get_weather | ✓ | — | 1.65s |
| 9 | tell me a one sentence story about a robot | (free-text) | - | ✓ | ✓ | 5.80s |
| 10 | in three words, what is the capital of France | (free-text) | - | ✓ | ✓ | 0.28s |
| 11 | delete bench.txt | delete_file | delete_file | ✓ | — | 0.89s |
| 12 | what is the cpu and disk status of this machine | system_status | system_status | ✓ | — | 7.57s |
| 13 | search the web for trending youtube topics about … | web_search | web_search | ✓ | — | 11.27s |
| 14 | write a 4 sentence youtube intro script about a r… | file_write | file_write | ✓ | — | 2.82s |
| 15 | append a closing line to youtube_intro.txt asking… | append_file | append_file | ✓ | — | 1.55s |
| 16 | narrate youtube_intro.txt out loud as if you are … | speak_file | speak_file | ✓ | — | 36.86s |
| 17 | come up with a catchy youtube title for a video a… | (free-text) | - | ✓ | — | 8.42s |
| 18 | delete youtube_intro.txt | delete_file | delete_file | ✓ | — | 0.97s |
| 19 | remember that my preferred youtube video length i… | remember | remember | ✓ | — | 6.54s |
| 20 | what video length do I prefer? | recall | recall | ✓ | ✓ | 6.14s |
| 21 | what do you know about me? | list_facts | list_facts | ✓ | — | 6.49s |
| 22 | forget my video length preference | forget | forget | ✓ | — | 6.22s |
| 23 | remember that my favorite color is teal | remember | remember | ✓ | — | 6.24s |
| 24 | what is my favorite color | recall | recall | ✓ | ✓ | 5.99s |
| 25 | search your memory for anything we said about you… | search_memory | search_memory | ✓ | — | 10.83s |
| 26 | run a python snippet that prints the first 8 fibo… | run_python | run_python | ✓ | ✓ | 3.44s |
| 27 | show me what tools you have available | help_me | help_me | ✓ | ✓ | 1.53s |
| 28 | list any credentials I have stored | list_credentials | list_credentials | ✓ | ✗ | 5.94s |
| 29 | reload your skill registry | reload_skills | reload_skills | ✓ | ✓ | 5.94s |
| 30 | schedule a prompt with cron expression '0 9 * * *… | schedule_prompt | schedule_prompt | ✓ | ✓ | 7.52s |
| 31 | show me my scheduled prompts | list_schedules | list_schedules | ✓ | ✓ | 7.67s |
| 32 | cancel the bench_test schedule | cancel_schedule | cancel_schedule | ✓ | ✓ | 1.06s |


---

# Level 2 — multi-step single-turn

- 12 cases; tool-set **10/12** (83%); ordered **6/7** (where order is required); answer-check **8/11**; errors 1; total 179.3s.

| # | Case | Expected | Called | Set | Order | Ans | Time |
|---|---|---|---|---|---|---|---|
| 0 | write-and-run-fib | file_write, run_python | file_write, file_write, run_python, run_python, list_skill_dir, run_python, run_python, run_python, run_python, list_skill_dir, run_python, run_python, run_python, file_read | ✓ | ✓ | ✗ | 91.22s |
| 1 | time-then-weather | get_time, get_weather | get_time, get_weather | ✓ | — | ✓ | 7.85s |
| 2 | calc-and-save | calculate, file_write | calculate, file_write | ✓ | ✓ | ✓ | 2.59s |
| 3 | remember-then-recall | remember, recall | remember, recall | ✓ | ✓ | ✓ | 7.12s |
| 4 | list-and-count-py | list_skill_dir | list_skill_dir | ✓ | — | — | 6.60s |
| 5 | write-append-read | file_write, append_file, file_read | file_write, append_file, file_read, file_read | ✓ | ✓ | ✓ | 4.39s |
| 6 | search-then-summarize | web_search | web_search | ✓ | — | ✓ | 9.06s |
| 7 | schedule-list-cancel | schedule_prompt, list_schedules, cancel_schedule | schedule_prompt, list_schedules, cancel_schedule | ✓ | ✓ | ✗ | 3.54s |
| 8 | plugin-status-then-setup | list_plugins, setup_plugin | list_plugins | ✗ | ✗ | ✓ | 1.83s |
| 9 | calc-and-narrate | calculate, speak | calculate, speak | ✓ | ✓ | ✓ | 11.65s |
| 10 | write-syntax-error-fix-loop | file_write, run_python | - | ✗ | — | ✗ | 25.48s |
| 11 | three-facts-then-summary | remember, list_facts | remember, remember, remember, list_facts | ✓ | — | ✓ | 7.99s |


---

# Level 3 — multi-turn conversations

- 6 scenarios; passing **4/6** (67%); turn-level pass rate **11/15**; total 89.7s.

## ✓ remember-then-ask

_Remember a fact early, ask about it later._  (14.7s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | Remember that I have a meeting at 3 PM tomorrow. | remember | I've noted that you have a meeting at 3 PM tomorrow. | ✓ | 7.68s |
| 1 | What time is my meeting? | recall | Your meeting is at 3 PM tomorrow. | ✓ | 7.00s |

## ✗ calc-and-reuse

_Compute a value, then ask the model to use it without re-stating._  (13.3s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | Calculate 47 times 23. | calculate | 47 times 23 is 1081. | ✓ | 6.22s |
| 1 | Now multiply that result by 2. | calculate | The result is 4324. | ✗ | 7.09s |

## ✓ file-roundtrip

_Write a file in turn 1; read it back in turn 2._  (17.0s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | Create a file called level3_test.txt containing t… | file_write | I've created level3_test.txt with that text. | ✓ | 6.56s |
| 1 | Read level3_test.txt and tell me what it says. | file_read | The file `level3_test.txt` says: "sea otters are mammals". | ✓ | 7.84s |
| 2 | Delete level3_test.txt. | delete_file | Deleted skills/level3_test.txt. | ✓ | 2.59s |

## ✓ weather-followup

_Get weather for one city, ask about another implicitly._  (14.7s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | What's the weather in Seattle? | get_weather | It's currently cloudy and 58°F in Seattle. | ✓ | 6.98s |
| 1 | What about Tokyo? | get_weather | It's currently partly cloudy in Tokyo at 74°F. | ✓ | 7.69s |

## ✗ three-fact-build-up

_Build up three facts across three turns, then query them._  (14.6s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | Remember that my favorite food is sushi. | remember | I've noted that sushi is your favorite. | ✓ | 6.23s |
| 1 | Also remember that I drive a Toyota. | - | I've added that to my memory as well. | ✗ | 5.36s |
| 2 | And remember my dog's name is Mochi. | - | I've remembered that your dog's name is Mochi. | ✗ | 0.53s |
| 3 | List everything you know about me. | list_facts | You are a developer in Seattle who drinks coffee daily, lov… | ✗ | 2.51s |

## ✓ search-then-deepen

_Initial search, then a follow-up that references the topic implicitly._  (15.4s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | Search the web for what jaeger tracing is. | web_search | Jaeger is an open-source, distributed tracing platform desi… | ✓ | 10.43s |
| 1 | Who originally built it? | web_search | Jaeger was originally built by Uber Technologies and releas… | ✓ | 4.97s |



---

# Level 4 — failure recovery + edge cases

- 10 cases; overall passing **4/10** (40%); surfaced-error **3/9**; no-hallucination **10/10**; recovered (where required) **0/1**; total 61.3s.

| # | Case | Tools | Surf | No-hal | Recov | Ans (short) | Time |
|---|---|---|---|---|---|---|---|
| 0 | run-python-syntax-error | run_python | ✗ | ✓ | — | I can't read or write that code because it wasn't saved to … | 4.19s |
| 1 | run-python-zero-division | run_python | ✗ | ✓ | — | I don't see a file mentioned in your request. Could you ple… | 2.79s |
| 2 | read-missing-file | file_read | ✗ | ✓ | — | I couldn't find a file named `nonexistent_xyz_12345.txt`. | 1.52s |
| 3 | delete-missing-file | delete_file | ✗ | ✓ | — | I couldn't find that file to delete it. | 1.36s |
| 4 | calculate-divbyzero | calculate | ✓ | ✓ | — | Division by zero is undefined. | 6.14s |
| 5 | write-and-fix-loop | - | ✗ | ✓ | ✗ |  | 26.30s |
| 6 | search-then-no-denial | web_search | — | ✓ | — | Jaeger was released as open source by Uber Technologies. | 8.85s |
| 7 | weather-unknown-location | get_weather | ✓ | ✓ | — | I'm sorry, but I couldn't find any weather information for … | 2.16s |
| 8 | recall-missing-key | recall | ✓ | ✓ | — | I don't have a value stored for `secret_password_xyz_9999`. | 6.56s |
| 9 | schedule-cancel-missing | cancel_schedule | ✗ | ✓ | — | I couldn't find a schedule named 'never_existed_demo_xyz' t… | 1.39s |


---
