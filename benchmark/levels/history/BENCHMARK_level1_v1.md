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
