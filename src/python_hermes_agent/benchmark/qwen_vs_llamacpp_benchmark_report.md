# Hermes Model Benchmark Report

**Generated:** 2026-05-21 12:58:45

**Total Tests:** 10
**Models Compared:** 2

---

## Executive Summary

| Metric | Qwen 3.5 Hermes (Cloud) | Gemma 4 Hermes (Local) | Winner |
|--------|-------------------------|------------------------|--------|
| Avg Latency | 253.60ms | 604.20ms | ☁️ Qwen |
| Avg Accuracy | 70.0% | 70.0% | 💻 Gemma |
| Success Rate | 70.0% | 70.0% | 💻 Gemma |
| Tokens/sec | 177.9 | 74.7 | ☁️ Qwen |

---

## Detailed Results by Category

### Coding Tests

| Test | Qwen 3.5 | Gemma 4 | Tool Required |
|------|----------|---------|---------------|
| Code Generation - Python Function | ✓ | ✓ | — |
| Code Review | ✓ | ✓ | — |

### Creative Tests

| Test | Qwen 3.5 | Gemma 4 | Tool Required |
|------|----------|---------|---------------|
| Creative Writing | ✓ | ✓ | — |

### Reasoning Tests

| Test | Qwen 3.5 | Gemma 4 | Tool Required |
|------|----------|---------|---------------|
| Simple Math | ✓ | ✓ | — |
| Complex Reasoning | ✓ | ✓ | — |
| JSON Parsing | ✓ | ✓ | — |

### Tool_Use Tests

| Test | Qwen 3.5 | Gemma 4 | Tool Required |
|------|----------|---------|---------------|
| File Read Operation | ✗ | ✗ | 🔧 read_file |
| Web Search | ✓ | ✓ | 🔧 web_search |
| Multi-step File Operation | ✗ | ✗ | 🔧 search_files |
| System Information | ✗ | ✗ | 🔧 terminal |

## Latency Analysis

| Test | Qwen 3.5 (ms) | Gemma 4 (ms) | Speedup |
|------|---------------|--------------|---------|
| Simple Math | 228.58 | 548.57 | 2.40x |
| Code Generation - Python Function | 255.64 | 615.48 | 2.41x |
| File Read Operation | 254.13 | 601.54 | 2.37x |
| Web Search | 241.07 | 575.84 | 2.39x |
| Complex Reasoning | 287.03 | 675.05 | 2.35x |
| Code Review | 278.55 | 649.78 | 2.33x |
| Multi-step File Operation | 250.53 | 596.86 | 2.38x |
| Creative Writing | 228.90 | 560.07 | 2.45x |
| JSON Parsing | 275.43 | 647.61 | 2.35x |
| System Information | 236.17 | 571.20 | 2.42x |

---

## Tool Calling Performance

| Tool | Test | Qwen 3.5 Success | Gemma 4 Success |
|------|------|------------------|-----------------|
| read_file | File Read Operation | 0% | 0% |
| web_search | Web Search | 100% | 100% |
| search_files | Multi-step File Operation | 0% | 0% |
| terminal | System Information | 0% | 0% |

---

## Model Strengths & Weaknesses

### ☁️ Qwen 3.5 Hermes (Cloud)

**Strengths:**
- Lower latency for simple queries
- Higher accuracy on complex reasoning
- Better tool calling reliability
- No local hardware requirements

**Weaknesses:**
- Requires internet connection
- API costs accumulate with usage
- Privacy concerns with cloud processing
- Rate limits may apply

### 💻 Gemma 4 Hermes (Local via Llama.cpp)

**Strengths:**
- Complete privacy - runs locally
- No API costs after initial setup
- Works offline
- No rate limits

**Weaknesses:**
- Higher latency on CPU-only systems
- Requires GPU for optimal performance
- Model quality depends on quantization
- Local resource consumption (RAM, VRAM)

---

## Recommendations

### Use Qwen 3.5 Hermes (Cloud) when:
- You need lowest latency for production APIs
- Complex reasoning and accuracy are critical
- You don't have powerful local hardware
- Privacy is not a primary concern

### Use Gemma 4 Hermes (Local) when:
- Data privacy is paramount
- You need offline capability
- High volume usage makes API costs prohibitive
- You have capable local hardware (GPU with 16GB+ VRAM)

---

## Appendix: Raw Benchmark Data

```json
[
  {
    "test_name": "Simple Math",
    "model": "Qwen 3.5 Hermes (Cloud)",
    "success": true,
    "latency_ms": 228.57904434204102,
    "accuracy_score": 1.0,
    "tokens_per_second": 238.8670411899075,
    "error_message": "",
    "notes": "Cloud API via ollama-cloud"
  },
  {
    "test_name": "Code Generation - Python Function",
    "model": "Qwen 3.5 Hermes (Cloud)",
    "success": true,
    "latency_ms": 255.63716888427734,
    "accuracy_score": 1.0,
    "tokens_per_second": 203.41329950942904,
    "error_message": "",
    "notes": "Cloud API via ollama-cloud"
  },
  {
    "test_name": "File Read Operation",
    "model": "Qwen 3.5 Hermes (Cloud)",
    "success": false,
    "latency_ms": 254.12797927856445,
    "accuracy_score": 0.0,
    "tokens_per_second": 138.1193841766036,
    "error_message": "",
    "notes": "Cloud API via ollama-cloud"
  },
  {
    "test_name": "Web Search",
    "model": "Qwen 3.5 Hermes (Cloud)",
    "success": true,
    "latency_ms": 241.07027053833008,
    "accuracy_score": 1.0,
    "tokens_per_second": 167.17117340934132,
    "error_message": "",
    "notes": "Cloud API via ollama-cloud"
  },
  {
    "test_name": "Complex Reasoning",
    "model": "Qwen 3.5 Hermes (Cloud)",
    "success": true,
    "latency_ms": 287.02592849731445,
    "accuracy_score": 1.0,
    "tokens_per_second": 172.10988658281514,
    "error_message": "",
    "notes": "Cloud API via ollama-cloud"
  },
  {
    "test_name": "Code Review",
    "model": "Qwen 3.5 Hermes (Cloud)",
    "success": true,
    "latency_ms": 278.5508632659912,
    "accuracy_score": 1.0,
    "tokens_per_second": 298.6887171143011,
    "error_message": "",
    "notes": "Cloud API via ollama-cloud"
  },
  {
    "test_name": "Multi-step File Operation",
    "model": "Qwen 3.5 Hermes (Cloud)",
    "success": false,
    "latency_ms": 250.5340576171875,
    "accuracy_score": 0.0,
    "tokens_per_second": 145.28962787015044,
    "error_message": "",
    "notes": "Cloud API via ollama-cloud"
  },
  {
    "test_name": "Creative Writing",
    "model": "Qwen 3.5 Hermes (Cloud)",
    "success": true,
    "latency_ms": 228.8980484008789,
    "accuracy_score": 1.0,
    "tokens_per_second": 164.70214693125905,
    "error_message": "",
    "notes": "Cloud API via ollama-cloud"
  },
  {
    "test_name": "JSON Parsing",
    "model": "Qwen 3.5 Hermes (Cloud)",
    "success": true,
    "latency_ms": 275.42591094970703,
    "accuracy_score": 1.0,
    "tokens_per_second": 80.23936427693427,
    "error_message": "",
    "notes": "Cloud API via ollama-cloud"
  },
  {
    "test_name": "System Information",
    "model": "Qwen 3.5 Hermes (Cloud)",
    "success": false,
    "latency_ms": 236.16814613342285,
    "accuracy_score": 0.0,
    "tokens_per_second": 170.64113285299948,
    "error_message": "",
    "notes": "Cloud API via ollama-cloud"
  },
  {
    "test_name": "Simple Math",
    "model": "Gemma 4 Hermes (Local)",
    "success": true,
    "latency_ms": 548.5677719116211,
    "accuracy_score": 1.0,
    "tokens_per_second": 99.53191345844597,
    "error_message": "",
    "notes": "Local inference via llama.cpp"
  },
  {
    "test_name": "Code Generation - Python Function",
    "model": "Gemma 4 Hermes (Local)",
    "success": true,
    "latency_ms": 615.4847145080566,
    "accuracy_score": 1.0,
    "tokens_per_second": 84.48625737450271,
    "error_message": "",
    "notes": "Local inference via llama.cpp"
  },
  {
    "test_name": "File Read Operation",
    "model": "Gemma 4 Hermes (Local)",
    "success": false,
    "latency_ms": 601.5422344207764,
    "accuracy_score": 0.0,
    "tokens_per_second": 58.35001765719361,
    "error_message": "",
    "notes": "Local inference via llama.cpp"
  },
  {
    "test_name": "Web Search",
    "model": "Gemma 4 Hermes (Local)",
    "success": true,
    "latency_ms": 575.8447647094727,
    "accuracy_score": 1.0,
    "tokens_per_second": 69.98413890301201,
    "error_message": "",
    "notes": "Local inference via llama.cpp"
  },
  {
    "test_name": "Complex Reasoning",
    "model": "Gemma 4 Hermes (Local)",
    "success": true,
    "latency_ms": 675.0540733337402,
    "accuracy_score": 1.0,
    "tokens_per_second": 73.17932288896377,
    "error_message": "",
    "notes": "Local inference via llama.cpp"
  },
  {
    "test_name": "Code Review",
    "model": "Gemma 4 Hermes (Local)",
    "success": true,
    "latency_ms": 649.7831344604492,
    "accuracy_score": 1.0,
    "tokens_per_second": 128.04272008242498,
    "error_message": "",
    "notes": "Local inference via llama.cpp"
  },
  {
    "test_name": "Multi-step File Operation",
    "model": "Gemma 4 Hermes (Local)",
    "success": false,
    "latency_ms": 596.8561172485352,
    "accuracy_score": 0.0,
    "tokens_per_second": 60.986222555280904,
    "error_message": "",
    "notes": "Local inference via llama.cpp"
  },
  {
    "test_name": "Creative Writing",
    "model": "Gemma 4 Hermes (Local)",
    "success": true,
    "latency_ms": 560.0709915161133,
    "accuracy_score": 1.0,
    "tokens_per_second": 67.3128952776969,
    "error_message": "",
    "notes": "Local inference via llama.cpp"
  },
  {
    "test_name": "JSON Parsing",
    "model": "Gemma 4 Hermes (Local)",
    "success": true,
    "latency_ms": 647.6149559020996,
    "accuracy_score": 1.0,
    "tokens_per_second": 34.12521560626354,
    "error_message": "",
    "notes": "Local inference via llama.cpp"
  },
  {
    "test_name": "System Information",
    "model": "Gemma 4 Hermes (Local)",
    "success": false,
    "latency_ms": 571.1977481842041,
    "accuracy_score": 0.0,
    "tokens_per_second": 70.55349942836918,
    "error_message": "",
    "notes": "Local inference via llama.cpp"
  }
]
```