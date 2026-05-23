# 🔬 Gemma4 Inference Engine Benchmark

**Date:** 2026-05-21 13:29:00

**Model:** Gemma4 (same model, different engines)

**Goal:** Isolate performance differences between Ollama and Llama.cpp

---

## 📊 Executive Summary

| Metric | 🦙 Ollama (Full) | 🐍 Llama.cpp (Q4_K_M) | Winner |
|--------|------------------|------------------------|--------|
| **Avg Latency** | 77794.8ms | 7567.3ms | 🐍 Llama.cpp |
| **Avg Accuracy** | 83.3% | 0.0% | 🦙 Ollama |
| **Success Rate** | 83.3% | 0.0% | 🦙 Ollama |
| **Tokens/sec** | 5.5 | 0.0 | 🦙 Ollama |

### 🎯 Quantization Impact Analysis

❌ **Quantization Loss: Severe** (83.3 percentage points)

📈 **Speed Trade-off:** Llama.cpp is 0.1x faster than Ollama

---

## 📋 Detailed Test Results

| # | Test | Category | Ollama | Llama.cpp | Notes |
|---|------|----------|--------|-----------|-------|
| 1 | Arithmetic (234 × 876) | reasoning | ❌ | ❌ | Llama.cpp 3.2x faster |
| 2 | Fibonacci Function | coding | ✅ | ❌ | Ollama more accurate, Llama.cpp 68.2x faster |
| 3 | Bat & Ball Puzzle | reasoning | ✅ | ❌ | Ollama more accurate, Llama.cpp 59.0x faster |
| 4 | Code Review - Division by Zero | coding | ✅ | ❌ | Ollama more accurate, Llama.cpp 42.4x faster |
| 5 | JSON Extraction | reasoning | ✅ | ❌ | Ollama more accurate, Llama.cpp 9.4x faster |
| 6 | Explain Quantum Computing | creative | ✅ | ❌ | Ollama more accurate, Llama.cpp 19.0x faster |

---

## ⏱️ Latency Comparison

| Test | Ollama (ms) | Llama.cpp (ms) | Slowdown |
|------|-------------|----------------|----------|
| Arithmetic (234 × 876) | 114055.9 | 35624.2 | 3.20x faster |
| Fibonacci Function | 111369.7 | 1632.0 | 68.24x faster |
| Bat & Ball Puzzle | 96581.8 | 1638.1 | 58.96x faster |
| Code Review - Division by Zero | 76007.7 | 1793.7 | 42.37x faster |
| JSON Extraction | 20577.5 | 2181.9 | 9.43x faster |
| Explain Quantum Computing | 48175.9 | 2533.7 | 19.01x faster |

---

## 🎓 Recommendations


### Use Ollama When:

✅ You want best accuracy (full precision model)
✅ You need fastest inference (optimized engine)
✅ You're okay with ~19GB model download
✅ You want easy model management

### Use Llama.cpp When:

✅ You need offline/portable deployment
✅ You want smaller model files (quantized)
✅ You need fine-grained control over inference
✅ You're deploying to edge devices

## 🖥️ Test Configuration


### Ollama Setup

- **Model:** gemma4:31b (full precision)
- **Size:** ~19 GB
- **Engine:** Ollama (optimized)

### Llama.cpp Setup

- **Model:** Gemma-4-26B-A4B-it-Q4_K_M.gguf
- **Size:** ~16 GB (quantized)
- **Quantization:** Q4_K_M (4-bit)
- **GPU Layers:** 35
- **Context:** 8192 tokens

---

## 📁 Raw Data


```json
[
  {
    "task_id": "math_001",
    "task_name": "Arithmetic (234 \u00d7 876)",
    "model": "Gemma4 (Ollama)",
    "inference_engine": "Ollama",
    "category": "reasoning",
    "success": false,
    "latency_ms": 114055.93681335449,
    "response_length": 2948,
    "tokens_generated": 798,
    "tokens_per_second": 6.998320493445292,
    "accuracy_score": 0.0,
    "error_message": "",
    "response_preview": "Thinking... The user wants to multiply two numbers: 234 and 876.      *   Number 1: 234     *   Number 2: 876      *   Method: Long multiplication.     *   Setup:         ```           876         x 234         -----         ```      *   **Step 1: Multiply 876 by 4 (the ones place of 234)**         "
  },
  {
    "task_id": "code_001",
    "task_name": "Fibonacci Function",
    "model": "Gemma4 (Ollama)",
    "inference_engine": "Ollama",
    "category": "coding",
    "success": true,
    "latency_ms": 111369.71378326416,
    "response_length": 3647,
    "tokens_generated": 686,
    "tokens_per_second": 6.16325549094791,
    "accuracy_score": 1.0,
    "error_message": "",
    "response_preview": "Thinking... *   Function name: `calculate_fibonacci`.     *   Purpose: Return the first `n` Fibonacci numbers.     *   Requirements: Include type hints and a docstring.      *   Fibonacci sequence starts with 0 and 1.     *   Each subsequent number is the sum of the previous two.     *   Sequence: 0"
  },
  {
    "task_id": "logic_001",
    "task_name": "Bat & Ball Puzzle",
    "model": "Gemma4 (Ollama)",
    "inference_engine": "Ollama",
    "category": "reasoning",
    "success": true,
    "latency_ms": 96581.84766769409,
    "response_length": 1666,
    "tokens_generated": 388,
    "tokens_per_second": 4.024565789395405,
    "accuracy_score": 1.0,
    "error_message": "",
    "response_preview": "Thinking... *   Total cost (bat + ball) = $1.10.     *   Price difference (bat - ball) = $1.00.     *   Goal: Find the cost of the ball.      *   Many people instinctively answer $0.10 because they see \"1.10\" and \u001b[K \"1.00\" and subtract them.     *   Verification of intuitive answer: If ball = $0.10"
  },
  {
    "task_id": "code_002",
    "task_name": "Code Review - Division by Zero",
    "model": "Gemma4 (Ollama)",
    "inference_engine": "Ollama",
    "category": "coding",
    "success": true,
    "latency_ms": 76007.66897201538,
    "response_length": 2021,
    "tokens_generated": 410,
    "tokens_per_second": 5.404717781191908,
    "accuracy_score": 1.0,
    "error_message": "",
    "response_preview": "Thinking... *   Code:         ```python         def divide(a, b):             return a / b          result = divide(10, 0)         ```     *   Operation: Division of `a` (10) by `b` (0).      *   In mathematics and in almost all programming languages (including P\u001b[1D\u001b[K Python), dividing a number by"
  },
  {
    "task_id": "json_001",
    "task_name": "JSON Extraction",
    "model": "Gemma4 (Ollama)",
    "inference_engine": "Ollama",
    "category": "reasoning",
    "success": true,
    "latency_ms": 20577.495098114014,
    "response_length": 457,
    "tokens_generated": 78,
    "tokens_per_second": 3.7905488315314395,
    "accuracy_score": 1.0,
    "error_message": "",
    "response_preview": "Thinking... *   Input: A JSON string `{\"users\": [{\"email\": \"alice@test.com\"}, {\"email\":\u001b[9D\u001b[K {\"email\": \"bob@demo.org\"}]}`.     *   Task: Extract all email addresses.      *   Root is an object.     *   Key `\"users\"` maps to a list of objects.     *   Each object in the list has a key `\"email\"`.   "
  },
  {
    "task_id": "explain_001",
    "task_name": "Explain Quantum Computing",
    "model": "Gemma4 (Ollama)",
    "inference_engine": "Ollama",
    "category": "creative",
    "success": true,
    "latency_ms": 48175.865173339844,
    "response_length": 1509,
    "tokens_generated": 310,
    "tokens_per_second": 6.4492873948829255,
    "accuracy_score": 1.0,
    "error_message": "",
    "response_preview": "Thinking... *   Topic: Quantum Computing.     *   Target Audience: 10-year-old (needs simple analogies, no jargon lik\u001b[3D\u001b[K like \"superposition\" or \"entanglement\" without simple explanation).     *   Constraint: 2-3 sentences.      *   Classical computers use bits (0 or 1).     *   Quantum computer"
  },
  {
    "task_id": "math_001",
    "task_name": "Arithmetic (234 \u00d7 876)",
    "model": "Gemma4 (Llama.cpp)",
    "inference_engine": "Llama.cpp",
    "category": "reasoning",
    "success": false,
    "latency_ms": 35624.220848083496,
    "response_length": 0,
    "tokens_generated": 0,
    "tokens_per_second": 0,
    "accuracy_score": 0.0,
    "error_message": "llama_decode returned -3",
    "response_preview": ""
  },
  {
    "task_id": "code_001",
    "task_name": "Fibonacci Function",
    "model": "Gemma4 (Llama.cpp)",
    "inference_engine": "Llama.cpp",
    "category": "coding",
    "success": false,
    "latency_ms": 1631.9549083709717,
    "response_length": 0,
    "tokens_generated": 0,
    "tokens_per_second": 0,
    "accuracy_score": 0.0,
    "error_message": "llama_decode returned -3",
    "response_preview": ""
  },
  {
    "task_id": "logic_001",
    "task_name": "Bat & Ball Puzzle",
    "model": "Gemma4 (Llama.cpp)",
    "inference_engine": "Llama.cpp",
    "category": "reasoning",
    "success": false,
    "latency_ms": 1638.1299495697021,
    "response_length": 0,
    "tokens_generated": 0,
    "tokens_per_second": 0,
    "accuracy_score": 0.0,
    "error_message": "llama_decode returned -3",
    "response_preview": ""
  },
  {
    "task_id": "code_002",
    "task_name": "Code Review - Division by Zero",
    "model": "Gemma4 (Llama.cpp)",
    "inference_engine": "Llama.cpp",
    "category": "coding",
    "success": false,
    "latency_ms": 1793.74098777771,
    "response_length": 0,
    "tokens_generated": 0,
    "tokens_per_second": 0,
    "accuracy_score": 0.0,
    "error_message": "llama_decode returned -3",
    "response_preview": ""
  },
  {
    "task_id": "json_001",
    "task_name": "JSON Extraction",
    "model": "Gemma4 (Llama.cpp)",
    "inference_engine": "Llama.cpp",
    "category": "reasoning",
    "success": false,
    "latency_ms": 2181.901216506958,
    "response_length": 0,
    "tokens_generated": 0,
    "tokens_per_second": 0,
    "accuracy_score": 0.0,
    "error_message": "llama_decode returned -3",
    "response_preview": ""
  },
  {
    "task_id": "explain_001",
    "task_name": "Explain Quantum Computing",
    "model": "Gemma4 (Llama.cpp)",
    "inference_engine": "Llama.cpp",
    "category": "creative",
    "success": false,
    "latency_ms": 2533.698797225952,
    "response_length": 0,
    "tokens_generated": 0,
    "tokens_per_second": 0,
    "accuracy_score": 0.0,
    "error_message": "llama_decode returned -3",
    "response_preview": ""
  }
]
```