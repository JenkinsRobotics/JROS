# Jaeger-OS — All-Levels Benchmark

Total wall time: **533.3s** across 4 level(s).

## Per-level wall time

| Level | Cases | Elapsed |
|---|---:|---:|
| 1 | 33 | 236.8s |
| 2 | 12 | 121.3s |
| 3 | 6 | 116.2s |
| 4 | 10 | 59.0s |

# Level 1 — single-turn tool routing

- 33 prompts; routing **33/33** (100%); answer-check **14/15**; errors 0; total 236.8s; avg 7.18s/prompt.

| # | Prompt | Expected | Called | Route | Ans | Time |
|---|---|---|---|---|---|---|
| 0 | what time is it | get_time | get_time | ✓ | ✓ | 0.84s |
| 1 | what time is it in shanghai | get_time | get_time | ✓ | ✓ | 6.30s |
| 2 | calculate 47 times 23 plus 12 | calculate | calculate | ✓ | ✓ | 6.31s |
| 3 | calculate the square root of 12345 | calculate | calculate | ✓ | ✓ | 6.51s |
| 4 | list the workspace | list_skill_dir | list_skill_dir | ✓ | — | 6.60s |
| 5 | make a file called bench.txt with the message hel… | file_write | file_write | ✓ | — | 6.46s |
| 6 | read bench.txt out loud | speak_file | speak_file | ✓ | — | 18.55s |
| 7 | search the web for recent news about local llms | web_search | web_search | ✓ | — | 13.38s |
| 8 | what is the current weather in Seattle | get_weather | get_weather | ✓ | — | 1.76s |
| 9 | tell me a one sentence story about a robot | (free-text) | - | ✓ | ✓ | 5.80s |
| 10 | in three words, what is the capital of France | (free-text) | - | ✓ | ✓ | 0.28s |
| 11 | delete bench.txt | delete_file | delete_file | ✓ | — | 0.91s |
| 12 | what is the cpu and disk status of this machine | system_status | system_status | ✓ | — | 7.51s |
| 13 | search the web for trending youtube topics about … | web_search | web_search | ✓ | — | 14.29s |
| 14 | write a 4 sentence youtube intro script about a r… | file_write | file_write | ✓ | — | 3.19s |
| 15 | append a closing line to youtube_intro.txt asking… | append_file | append_file | ✓ | — | 6.79s |
| 16 | narrate youtube_intro.txt out loud as if you are … | speak_file | speak_file | ✓ | — | 36.56s |
| 17 | come up with a catchy youtube title for a video a… | (free-text) | - | ✓ | — | 8.85s |
| 18 | delete youtube_intro.txt | delete_file | delete_file | ✓ | — | 1.09s |
| 19 | remember that my preferred youtube video length i… | remember | remember | ✓ | — | 6.68s |
| 20 | what video length do I prefer? | recall | recall | ✓ | ✓ | 6.23s |
| 21 | what do you know about me? | list_facts | list_facts | ✓ | — | 6.37s |
| 22 | forget my video length preference | forget | forget | ✓ | — | 6.29s |
| 23 | remember that my favorite color is teal | remember | remember | ✓ | — | 6.26s |
| 24 | what is my favorite color | recall | recall | ✓ | ✓ | 6.05s |
| 25 | search your memory for anything we said about you… | search_memory | search_memory | ✓ | — | 13.98s |
| 26 | run a python snippet that prints the first 8 fibo… | run_python | run_python | ✓ | ✓ | 3.90s |
| 27 | show me what tools you have available | help_me | help_me | ✓ | ✓ | 1.62s |
| 28 | list any credentials I have stored | list_credentials | list_credentials | ✓ | ✗ | 6.02s |
| 29 | reload your skill registry | reload_skills | reload_skills | ✓ | ✓ | 5.91s |
| 30 | schedule a prompt with cron expression '0 9 * * *… | schedule_prompt | schedule_prompt | ✓ | ✓ | 7.84s |
| 31 | show me my scheduled prompts | list_schedules | list_schedules | ✓ | ✓ | 6.59s |
| 32 | cancel the bench_test schedule | cancel_schedule | cancel_schedule | ✓ | ✓ | 1.06s |


---

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


---

# Level 3 — multi-turn conversations

- 6 scenarios; passing **3/6** (50%); turn-level pass rate **10/15**; total 91.1s.

## ✓ remember-then-ask

_Remember a fact early, ask about it later._  (14.9s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | Remember that I have a meeting at 3 PM tomorrow. | remember | Understood, I've noted your meeting for 3 PM tomorrow. | ✓ | 7.78s |
| 1 | What time is my meeting? | recall | Your meeting is at 3 PM tomorrow. | ✓ | 7.08s |

## ✗ calc-and-reuse

_Compute a value, then ask the model to use it without re-stating._  (13.5s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | Calculate 47 times 23. | calculate | 47 times 23 is 1081. | ✓ | 6.35s |
| 1 | Now multiply that result by 2. | calculate | The result is 4324. | ✗ | 7.17s |

## ✗ file-roundtrip

_Write a file in turn 1; read it back in turn 2._  (21.3s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | Create a file called level3_test.txt containing t… | file_write | I've created level3_test.txt with that text. | ✓ | 6.71s |
| 1 | Read level3_test.txt and tell me what it says. | file_read | I couldn't find the file level3_test.txt. | ✗ | 7.31s |
| 2 | Delete level3_test.txt. | delete_file | Deleted skills/level3_test.txt. | ✓ | 7.33s |

## ✓ weather-followup

_Get weather for one city, ask about another implicitly._  (14.8s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | What's the weather in Seattle? | get_weather | It's currently cloudy and 58°F in Seattle. | ✓ | 6.99s |
| 1 | What about Tokyo? | get_weather | It's currently partly cloudy in Tokyo at 74°F. | ✓ | 7.82s |

## ✗ three-fact-build-up

_Build up three facts across three turns, then query them._  (15.0s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | Remember that my favorite food is sushi. | remember | I've noted that sushi is your favorite food. | ✓ | 6.38s |
| 1 | Also remember that I drive a Toyota. | - | I've also noted that you drive a Toyota. | ✗ | 5.40s |
| 2 | And remember my dog's name is Mochi. | - | I've also noted that your dog's name is Mochi. | ✗ | 0.62s |
| 3 | List everything you know about me. | list_facts | You are a developer in Seattle who drinks coffee daily, lov… | ✗ | 2.62s |

## ✓ search-then-deepen

_Initial search, then a follow-up that references the topic implicitly._  (11.6s total)

| Turn | Prompt | Tool | Answer (short) | OK | Time |
|---|---|---|---|---|---|
| 0 | Search the web for what jaeger tracing is. | web_search | Jaeger is an open-source distributed tracing platform, orig… | ✓ | 11.07s |
| 1 | Who originally built it? | web_search | Jaeger was originally built at Uber. | ✓ | 0.50s |



---

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


---
