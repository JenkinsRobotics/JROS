# 🔬 Model Comparison: Qwen3-Coder-30B vs Gemma4-26B

**Date:** 2026-05-21 17:32:52

**Engine:** llama.cpp (same for both)

**Goal:** Isolate model quality differences

---

## 📊 Executive Summary

| Metric | Qwen3-Coder-30B | Gemma4-26B | Winner |
|--------|-----------------|------------|--------|
| **Success Rate** | 67% | 67% | Tie |
| **Avg Latency** | 7.8s | 4.9s | Gemma4 |
| **Avg Accuracy** | 67% | 67% | Tie |

### 📐 Model Specifications

| Spec | Qwen3-Coder-30B | Gemma4-26B |
|------|-----------------|------------|
| Parameters | 30B (A3B MoE) | 26B (A4B MoE) |
| Quantization | Q4_K_M | Q4_K_M |
| File Size | 18.6 GB | 16.0 GB |
| Context | 256K | 262K |

---

## 📋 Test-by-Test Results

| Test | Category | Qwen3 | Gemma4 | Qwen Time | Gemma Time |
|------|----------|-------|--------|-----------|------------|
| Simple Math | reasoning | ❌ | ❌ | 6.8s | 2.2s |
| Python Function | coding | ✅ | ✅ | 12.5s | 7.8s |
| Bat & Ball | reasoning | ✅ | ✅ | 4.1s | 4.7s |

---

## 🎓 Conclusions


### 🤝 It's a Tie

Both models perform similarly on these tests.

### 💡 Recommendations


**Use Gemma4-26B when:**
- You need faster inference
- Disk space is limited (16GB)
- General reasoning is the priority

---

## 📁 Raw Data

```json
[
  {
    "model_name": "Qwen3-Coder-30B",
    "model_path": "/Users/jonathanjenkins/GitHub/GITHUB/Hermes/models/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf",
    "test_id": "math_001",
    "test_name": "Simple Math",
    "success": false,
    "latency_ms": 6829.571962356567,
    "response": "I need to calculate 234 \u00d7 876.\n\nLet me break this down step by step:\n\n234 \u00d7 876 = 234 \u00d7 (800 + 70 + 6)\n= 234 \u00d7 800 + 234 \u00d7 70 + 234 \u00d7 6\n\nCalculating each term:\n- 234 \u00d7 800 = 187,200\n- 234 \u00d7 70 = 16,380\n- 234 \u00d7 6 = 1,404\n\nAdding them together:\n187,200 + 16,380 + 1,404 = 204,984\n\n234 \u00d7 876 = 204,984",
    "accuracy": 0.0,
    "error": "Low accuracy"
  },
  {
    "model_name": "Qwen3-Coder-30B",
    "model_path": "/Users/jonathanjenkins/GitHub/GITHUB/Hermes/models/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf",
    "test_id": "code_001",
    "test_name": "Python Function",
    "success": true,
    "latency_ms": 12541.191339492798,
    "response": "```python\ndef calculate_fibonacci(n: int) -> int:\n    \"\"\"\n    Calculate the nth Fibonacci number using an iterative approach.\n    \n    The Fibonacci sequence starts with 0 and 1, and each subsequent number\n    is the sum of the two preceding numbers.\n    \n    Args:\n        n (int): The position in the Fibonacci sequence (non-negative integer)\n        \n    Returns:\n        int: The nth Fibonacci number\n        \n    Raises:\n        ValueError: If n is negative\n        \n    Examples:\n        >>> ca",
    "accuracy": 1.0,
    "error": ""
  },
  {
    "model_name": "Qwen3-Coder-30B",
    "model_path": "/Users/jonathanjenkins/GitHub/GITHUB/Hermes/models/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf",
    "test_id": "logic_001",
    "test_name": "Bat & Ball",
    "success": true,
    "latency_ms": 4093.5940742492676,
    "response": "Let me solve this step by step.\n\nLet's define:\n- Ball cost = x dollars\n- Bat cost = x + 1.00 dollars (since it costs $1.00 more than the ball)\n\nSince they cost $1.10 total:\nx + (x + 1.00) = 1.10\n\nSimplifying:\n2x + 1.00 = 1.10\n2x = 1.10 - 1.00\n2x = 0.10\nx = 0.05\n\nTherefore, the ball costs $0.05 (5 cents).\n\nLet me verify:\n- Ball: $0.05\n- Bat: $1.00 + $0.05 = $1.05\n- Total: $0.05 + $1.05 = $1.10 \u2713\n\nThe ball costs 5 cents.",
    "accuracy": 1.0,
    "error": ""
  },
  {
    "model_name": "Gemma4-26B",
    "model_path": "/Users/jonathanjenkins/GitHub/GITHUB/Hermes/models/gemma-4-26B-A4B-it-Q4_K_M.gguf",
    "test_id": "math_001",
    "test_name": "Simple Math",
    "success": false,
    "latency_ms": 2220.4012870788574,
    "response": "<|channel>thought\n<channel|>To find the product of 234 and 876, you can multiply them step-by-step:\n\n1.  **234 * 6** = 1,404\n2.  **234 * 70** = 16,380\n3.  **234 * 800** = 187,200\n\nNow, add the results together:\n1,404 + 16,380 + 187,200 = 204,984\n\n**Final Answer:**\n204,984",
    "accuracy": 0.0,
    "error": "Low accuracy"
  },
  {
    "model_name": "Gemma4-26B",
    "model_path": "/Users/jonathanjenkins/GitHub/GITHUB/Hermes/models/gemma-4-26B-A4B-it-Q4_K_M.gguf",
    "test_id": "code_001",
    "test_name": "Python Function",
    "success": true,
    "latency_ms": 7827.720165252686,
    "response": "<|channel>thought\n<channel|>Here is a Python function that calculates the $n^{th}$ Fibonacci number using an iterative approach, which is more efficient than recursion for larger values.\n\n```python\ndef calculate_fibonacci(n: int) -> int:\n    \"\"\"\n    Calculates the nth Fibonacci number.\n\n    Args:\n        n (int): The position in the Fibonacci sequence (must be a non-negative integer).\n\n    Returns:\n        int: The nth Fibonacci number.\n\n    Raises:\n        ValueError: If n is a negative integer",
    "accuracy": 1.0,
    "error": ""
  },
  {
    "model_name": "Gemma4-26B",
    "model_path": "/Users/jonathanjenkins/GitHub/GITHUB/Hermes/models/gemma-4-26B-A4B-it-Q4_K_M.gguf",
    "test_id": "logic_001",
    "test_name": "Bat & Ball",
    "success": true,
    "latency_ms": 4665.721893310547,
    "response": "---\nThe ball costs **$0.05** (5 cents).\n\n**Reasoning:**\n1.  Let $x$ be the cost of the ball.\n1.  Let $g$\n2.  Let $g$ be the cost of theLL\nLet $s$<|channel>Let $b$ be the cost of the ball.\nLet $a$ be the cost of the bat.\nThe total cost is $1.10.\nThe bat costs $1.00 more than the ball.\nSo, $a = b + 1.00$.\nThe total cost is $a + b = 1.10$.\nSubstituting the first equation into the second:\n$(b + 1.00) + b = 1.10$\n$2b + 1.00 = 1.10$\n$2b = 1.10 - 1.00$\n$2b = 0.10$\n$b = 0.05$\n\nThe ball costs $0.05.\nThe ",
    "accuracy": 1.0,
    "error": ""
  }
]
```