# 🔬 Hermes Model Benchmark: Qwen 3.5 vs Gemma 4 (Llama.cpp)

**Date:** 2026-05-21 13:01:32
**Location:** macOS 25.3.0
**Tests:** 8 tasks across 3 categories

---

## 📊 Executive Summary

| Metric | ☁️ Qwen 3.5 Hermes | 💻 Gemma 4 Hermes | Winner |
|--------|-------------------|-------------------|--------|
| **Avg Latency** | 24.9ms | 7161.9ms | ☁️ Qwen |
| **Avg Accuracy** | 0.0% | 62.5% | 💻 Gemma |
| **Success Rate** | 0.0% | 62.5% | 💻 Gemma |
| **Tokens/sec** | 0.0 | 22.1 | 💻 Gemma |

---

## 📋 Detailed Test Results

| # | Test | Category | Qwen 3.5 | Gemma 4 | Tool Required |
|---|------|----------|----------|---------|---------------|
| 1 | Arithmetic Calculation | reasoning | ❌ | ❌ | — |
| 2 | Python Code Generation | coding | ❌ | ✅ | — |
| 3 | File Read Test | tool_use | ❌ | ❌ | read_file |
| 4 | File Search Test | tool_use | ❌ | ✅ | search_files |
| 5 | Terminal Command Test | tool_use | ❌ | ❌ | terminal |
| 6 | Logic Puzzle | reasoning | ❌ | ✅ | — |
| 7 | Code Review | coding | ❌ | ✅ | — |
| 8 | JSON Parsing | reasoning | ❌ | ✅ | — |

---

## ⏱️ Latency Breakdown

| Test | Qwen 3.5 (ms) | Gemma 4 (ms) | Slowdown Factor |
|------|---------------|--------------|-----------------|
| Arithmetic Calculation | 24.7 | 23653.8 | 959.27x slower |
| Python Code Generation | 26.5 | 5740.4 | 216.91x slower |
| File Read Test | 25.4 | 2028.6 | 79.71x slower |
| File Search Test | 24.6 | 5907.4 | 240.09x slower |
| Terminal Command Test | 24.4 | 3413.2 | 140.04x slower |
| Logic Puzzle | 24.4 | 6322.0 | 258.78x slower |
| Code Review | 24.7 | 7930.4 | 321.23x slower |
| JSON Parsing | 24.5 | 2299.3 | 93.78x slower |

---

## 🎯 Performance by Category

### Coding

| Model | Accuracy | Avg Latency |
|-------|----------|-------------|
| ☁️ Qwen 3.5 | 0.0% | 25.6ms |
| 💻 Gemma 4 | 100.0% | 6835.4ms |

### Reasoning

| Model | Accuracy | Avg Latency |
|-------|----------|-------------|
| ☁️ Qwen 3.5 | 0.0% | 24.5ms |
| 💻 Gemma 4 | 66.7% | 10758.4ms |

### Tool_Use

| Model | Accuracy | Avg Latency |
|-------|----------|-------------|
| ☁️ Qwen 3.5 | 0.0% | 24.8ms |
| 💻 Gemma 4 | 33.3% | 3783.1ms |

## 🖥️ Test Configuration

### Cloud Model (Qwen 3.5 Hermes)

- **Provider:** Ollama Cloud API
- **Model:** Qwen 3.5 Hermes (397B)
- **API Mode:** Chat Completions

### Local Model (Gemma 4 Hermes)

- **Provider:** Llama.cpp (llama-cpp-python)
- **Model:** Gemma-4-26B-A4B-it-GGUF
- **Quantization:** Q4_K_M
- **Model Size:** ~16GB
- **GPU Layers:** 35 (partial offload)
- **Context:** 8192 tokens

## 🎓 Conclusions & Recommendations


### When to Use Qwen 3.5 Hermes (Cloud)

✅ Production APIs requiring lowest latency
✅ Complex reasoning tasks needing maximum accuracy
✅ Users without powerful local hardware
✅ Scenarios where API costs are acceptable

### When to Use Gemma 4 Hermes (Local)

✅ Privacy-sensitive applications
✅ Offline or air-gapped environments
✅ High-volume usage where API costs are prohibitive
✅ Users with capable GPU hardware (16GB+ VRAM)

---

## 📁 Appendix: Raw Data


```json
[
  {
    "task_id": "math_001",
    "task_name": "Arithmetic Calculation",
    "model": "Qwen 3.5 Hermes (Cloud)",
    "category": "reasoning",
    "success": false,
    "latency_ms": 24.658203125,
    "response_length": 0,
    "tokens_generated": 0,
    "tokens_per_second": 0.0,
    "tool_calls_made": 0,
    "accuracy_score": 0.0,
    "error_message": "",
    "response_preview": ""
  },
  {
    "task_id": "code_001",
    "task_name": "Python Code Generation",
    "model": "Qwen 3.5 Hermes (Cloud)",
    "category": "coding",
    "success": false,
    "latency_ms": 26.46493911743164,
    "response_length": 0,
    "tokens_generated": 0,
    "tokens_per_second": 0.0,
    "tool_calls_made": 0,
    "accuracy_score": 0.0,
    "error_message": "",
    "response_preview": ""
  },
  {
    "task_id": "file_001",
    "task_name": "File Read Test",
    "model": "Qwen 3.5 Hermes (Cloud)",
    "category": "tool_use",
    "success": false,
    "latency_ms": 25.44999122619629,
    "response_length": 0,
    "tokens_generated": 0,
    "tokens_per_second": 0.0,
    "tool_calls_made": 0,
    "accuracy_score": 0.0,
    "error_message": "",
    "response_preview": ""
  },
  {
    "task_id": "search_001",
    "task_name": "File Search Test",
    "model": "Qwen 3.5 Hermes (Cloud)",
    "category": "tool_use",
    "success": false,
    "latency_ms": 24.60479736328125,
    "response_length": 0,
    "tokens_generated": 0,
    "tokens_per_second": 0.0,
    "tool_calls_made": 0,
    "accuracy_score": 0.0,
    "error_message": "",
    "response_preview": ""
  },
  {
    "task_id": "terminal_001",
    "task_name": "Terminal Command Test",
    "model": "Qwen 3.5 Hermes (Cloud)",
    "category": "tool_use",
    "success": false,
    "latency_ms": 24.374008178710938,
    "response_length": 0,
    "tokens_generated": 0,
    "tokens_per_second": 0.0,
    "tool_calls_made": 0,
    "accuracy_score": 0.0,
    "error_message": "",
    "response_preview": ""
  },
  {
    "task_id": "reason_001",
    "task_name": "Logic Puzzle",
    "model": "Qwen 3.5 Hermes (Cloud)",
    "category": "reasoning",
    "success": false,
    "latency_ms": 24.430036544799805,
    "response_length": 0,
    "tokens_generated": 0,
    "tokens_per_second": 0.0,
    "tool_calls_made": 0,
    "accuracy_score": 0.0,
    "error_message": "",
    "response_preview": ""
  },
  {
    "task_id": "code_002",
    "task_name": "Code Review",
    "model": "Qwen 3.5 Hermes (Cloud)",
    "category": "coding",
    "success": false,
    "latency_ms": 24.687767028808594,
    "response_length": 0,
    "tokens_generated": 0,
    "tokens_per_second": 0.0,
    "tool_calls_made": 0,
    "accuracy_score": 0.0,
    "error_message": "",
    "response_preview": ""
  },
  {
    "task_id": "json_001",
    "task_name": "JSON Parsing",
    "model": "Qwen 3.5 Hermes (Cloud)",
    "category": "reasoning",
    "success": false,
    "latency_ms": 24.518966674804688,
    "response_length": 0,
    "tokens_generated": 0,
    "tokens_per_second": 0.0,
    "tool_calls_made": 0,
    "accuracy_score": 0.0,
    "error_message": "",
    "response_preview": ""
  },
  {
    "task_id": "math_001",
    "task_name": "Arithmetic Calculation",
    "model": "Gemma 4 Hermes (Local)",
    "category": "reasoning",
    "success": false,
    "latency_ms": 23653.797149658203,
    "response_length": 1210,
    "tokens_generated": 317,
    "tokens_per_second": 13.410109082827892,
    "tool_calls_made": 0,
    "accuracy_score": 0.0,
    "error_message": "",
    "response_preview": "<|channel>thought\n<channel|>To multiply 234 by 876, we can use the long multiplication method, breaking it down by multiplying 234 by each digit of 876 (the ones, tens, and hundreds places).\n\n**Step 1"
  },
  {
    "task_id": "code_001",
    "task_name": "Python Code Generation",
    "model": "Gemma 4 Hermes (Local)",
    "category": "coding",
    "success": true,
    "latency_ms": 5740.427017211914,
    "response_length": 931,
    "tokens_generated": 145,
    "tokens_per_second": 25.36396675080749,
    "tool_calls_made": 0,
    "accuracy_score": 1.0,
    "error_message": "",
    "response_preview": "<|channel>thought\n<channel|>```python\nfrom typing import List\n\ndef calculate_fibonacci(n: int) -> List[int]:\n    \"\"\"\n    Generates a list containing the first n numbers of the Fibonacci sequence.\n\n   "
  },
  {
    "task_id": "file_001",
    "task_name": "File Read Test",
    "model": "Gemma 4 Hermes (Local)",
    "category": "tool_use",
    "success": false,
    "latency_ms": 2028.588056564331,
    "response_length": 17,
    "tokens_generated": 1,
    "tokens_per_second": 0.6408398175239746,
    "tool_calls_made": 0,
    "accuracy_score": 0.0,
    "error_message": "",
    "response_preview": "<|channel>thought"
  },
  {
    "task_id": "search_001",
    "task_name": "File Search Test",
    "model": "Gemma 4 Hermes (Local)",
    "category": "tool_use",
    "success": true,
    "latency_ms": 5907.369375228882,
    "response_length": 999,
    "tokens_generated": 171,
    "tokens_per_second": 29.048462877497197,
    "tool_calls_made": 0,
    "accuracy_score": 1.0,
    "error_message": "",
    "response_preview": "<|channel>thought\n<channel|>To find these files, you can use the `find` command in your terminal. \n\nOpen your terminal and run the following command:\n\n```bash\nfind /Users/jonathanjenkins/GitHub/GITHUB"
  },
  {
    "task_id": "terminal_001",
    "task_name": "Terminal Command Test",
    "model": "Gemma 4 Hermes (Local)",
    "category": "tool_use",
    "success": false,
    "latency_ms": 3413.228750228882,
    "response_length": 513,
    "tokens_generated": 115,
    "tokens_per_second": 33.89752298091403,
    "tool_calls_made": 0,
    "accuracy_score": 0.0,
    "error_message": "",
    "response_preview": "<|channel>thought\npart of the system prompt or a simulated environment. I do not have access to a real operating system or a terminal to execute commands like `pwd`. I am a large language model runnin"
  },
  {
    "task_id": "reason_001",
    "task_name": "Logic Puzzle",
    "model": "Gemma 4 Hermes (Local)",
    "category": "reasoning",
    "success": true,
    "latency_ms": 6322.0179080963135,
    "response_length": 740,
    "tokens_generated": 183,
    "tokens_per_second": 28.993907113938455,
    "tool_calls_made": 0,
    "accuracy_score": 1.0,
    "error_message": "",
    "response_preview": "<|channel>thought\n<channel|>To find the cost of the ball, we can use a simple algebraic equation.\n\n### 1. Define the variables:\nLet **$x$** be the cost of the ball.\nSince the bat costs $1.00 more than"
  },
  {
    "task_id": "code_002",
    "task_name": "Code Review",
    "model": "Gemma 4 Hermes (Local)",
    "category": "coding",
    "success": true,
    "latency_ms": 7930.350065231323,
    "response_length": 1414,
    "tokens_generated": 291,
    "tokens_per_second": 36.71969050605912,
    "tool_calls_made": 0,
    "accuracy_score": 1.0,
    "error_message": "",
    "response_preview": "<|channel>thought\n<channel|>The bug in this code is a **`ZeroDivisionError`**.\n\n### The Issue\nIn mathematics and in Python, division by zero is undefined. When the code executes `divide_numbers(10, 0)"
  },
  {
    "task_id": "json_001",
    "task_name": "JSON Parsing",
    "model": "Gemma 4 Hermes (Local)",
    "category": "reasoning",
    "success": true,
    "latency_ms": 2299.2959022521973,
    "response_length": 134,
    "tokens_generated": 19,
    "tokens_per_second": 8.480857109734957,
    "tool_calls_made": 0,
    "accuracy_score": 1.0,
    "error_message": "",
    "response_preview": "<|channel>ms_thought\n<channel|>The email addresses extracted from the JSON are:\n\n* alice@example.com\n* bob@test.org\n* charlie@demo.net"
  }
]
```