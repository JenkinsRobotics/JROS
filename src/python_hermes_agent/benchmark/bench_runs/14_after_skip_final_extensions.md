# Four-way agent benchmark

All four agents driven by the same local Gemma 4 26B-A4B Q4_K_M weights. The first three load the model in-process; `python_hermes_agent` drives it over HTTP via `llama_cpp.server`.

## Per-prompt total seconds

| prompt | python_pydantic_ai |
|---|---:|
| what time is it | 2.59 |
| calculate 47 times 23 plus 12 | 0.46 |
| tell me a one sentence story about a robot | 0.47 |
| search the web for recent news about local llms | 6.89 |
| list files in the workspace directory | 0.92 |
| **TOTAL** | **11.33** |
| **AVG / prompt** | **2.27** |

## Per-prompt answers

### `what time is it`

| agent | answer |
|---|---|
| python_pydantic_ai | 2026-05-16 09:36:55 AM PDT |

### `calculate 47 times 23 plus 12`

| agent | answer |
|---|---|
| python_pydantic_ai | 1093 |

### `tell me a one sentence story about a robot`

| agent | answer |
|---|---|
| python_pydantic_ai | The robot spent its final battery cycle watching the sunset, finally understanding why humans wrote so much p… |

### `search the web for recent news about local llms`

| agent | answer |
|---|---|
| python_pydantic_ai | Recent news and trends regarding local LLMs include: ⏎ *   **Edge AI Integration:** There is a growing focus on… |

### `list files in the workspace directory`

| agent | answer |
|---|---|
| python_pydantic_ai | The workspace contains a directory named `self_test` and a file named `dogs_vs_robots_script.md`. |
