# Four-way agent benchmark

All four agents driven by the same local Gemma 4 26B-A4B Q4_K_M weights. The first three load the model in-process; `python_hermes_agent` drives it over HTTP via `llama_cpp.server`.

## Per-prompt total seconds

| prompt | python_custom_json | python_hermes_xml | python_pydantic_ai | python_hermes_agent |
|---|---:|---:|---:|---:|
| what time is it | 1.35 | 2.89 | 0.22 | 2.95 |
| calculate 47 times 23 plus 12 | 1.23 | 0.68 | 0.46 | 1.73 |
| tell me a one sentence story about a robot | 1.71 | 0.48 | 0.46 | 1.90 |
| search the web for recent news about local llms | 7.21 | 4.49 | 6.21 | 1.80 |
| list files in the workspace directory | 0.69 | 0.52 | 0.92 | 1.91 |
| **TOTAL** | **12.20** | **9.07** | **8.27** | **10.28** |
| **AVG / prompt** | **2.44** | **1.81** | **1.65** | **2.06** |

## Per-prompt answers

### `what time is it`

| agent | answer |
|---|---|
| python_custom_json | 2026-05-16 09:56:27 AM PDT |
| python_hermes_xml | 2026-05-16 09:56:43 AM PDT |
| python_pydantic_ai | 2026-05-16 09:56:55 AM PDT |
| python_hermes_agent | I do not have access to a real-time clock or your local system time, so so |

### `calculate 47 times 23 plus 12`

| agent | answer |
|---|---|
| python_custom_json | 47 * 23 + 12 = 1093 |
| python_hermes_xml | 47 * 23 + 12 = 1093 |
| python_pydantic_ai | 1093 |
| python_hermes_agent | (empty) |

### `tell me a one sentence story about a robot`

| agent | answer |
|---|---|
| python_custom_json | The robot spent its final moments polishing a single, rusted rose, ensuring its last programmed task was a be… |
| python_hermes_xml | The robot spent its final moments of battery life watching the sunset, wondering if the orange glow was a sig… |
| python_pydantic_ai | The robot spent its final battery cycle watching the sunset, finally understanding why humans wrote so much p… |
| python_hermes_agent | (empty) |

### `search the web for recent news about local llms`

| agent | answer |
|---|---|
| python_custom_json | Recent news regarding local LLMs highlights several key trends: ⏎ *   **Edge AI & TinyML:** There is a growing … |
| python_hermes_xml | Recent news regarding local LLMs highlights significant advancements in performance and model availability. K… |
| python_pydantic_ai | Recent news and trends regarding local LLMs include: ⏎ *   **Edge AI Integration:** There is a growing focus on… |
| python_hermes_agent | (empty) |

### `list files in the workspace directory`

| agent | answer |
|---|---|
| python_custom_json | { ⏎   "path": ".", ⏎   "entries": [ ⏎     { ⏎       "name": "agent_test", ⏎       "type": "directory", ⏎       "bytes": n… |
| python_hermes_xml | { ⏎   "path": ".", ⏎   "entries": [ ⏎     { ⏎       "name": "agent_test", ⏎       "type": "directory", ⏎       "bytes": n… |
| python_pydantic_ai | The workspace contains a directory named `self_test` and a file named `dogs_vs_robots_script.md`. |
| python_hermes_agent | (empty) |
