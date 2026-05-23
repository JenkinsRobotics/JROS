#!/usr/bin/env python3
"""
Qwen 3.6 Ollama Benchmark

Tests Qwen 3.6 via Ollama once downloaded.
"""

import subprocess
import time
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List
from dataclasses import dataclass, asdict
import json

TEST_PROMPTS = [
    {
        "id": "math_001",
        "name": "Arithmetic (234 × 876)",
        "prompt": "What is 234 multiplied by 876? Show your work and give the final answer.",
        "expected": "204984",
        "category": "reasoning"
    },
    {
        "id": "code_001",
        "name": "Fibonacci Function",
        "prompt": "Write a Python function called calculate_fibonacci that returns the first n Fibonacci numbers. Include type hints and docstring.",
        "expected_keywords": ["def", "calculate_fibonacci", "return", "List"],
        "category": "coding"
    },
    {
        "id": "logic_001",
        "name": "Bat & Ball Puzzle",
        "prompt": "A bat and ball cost $1.10 total. The bat costs $1.00 more than the ball. How much does the ball cost? Show reasoning.",
        "expected": "0.05",
        "category": "reasoning"
    },
    {
        "id": "code_002",
        "name": "Code Review",
        "prompt": "What bug exists in this code?\n\ndef divide(a, b):\n    return a / b\n\nprint(divide(10, 0))",
        "expected_keywords": ["zero", "division", "error"],
        "category": "coding"
    },
    {
        "id": "json_001",
        "name": "JSON Extraction",
        "prompt": "Extract emails from: {\"users\": [{\"email\": \"alice@test.com\"}, {\"email\": \"bob@demo.org\"}]}",
        "expected_keywords": ["alice@test.com", "bob@demo.org"],
        "category": "reasoning"
    },
]

@dataclass
class BenchmarkResult:
    test_id: str
    test_name: str
    model: str
    success: bool
    latency_ms: float
    response_preview: str
    accuracy: float
    error: str = ""


def run_ollama_test(prompt: str, model: str = "qwen3.6:latest") -> tuple:
    """Run a single test via Ollama."""
    start = time.time()
    
    try:
        cmd = ["ollama", "run", model, prompt]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        latency = (time.time() - start) * 1000
        response = result.stdout.strip()
        
        return response, latency, ""
    except subprocess.TimeoutExpired:
        latency = (time.time() - start) * 1000
        return "", latency, "Timeout after 180s"
    except Exception as e:
        latency = (time.time() - start) * 1000
        return "", latency, str(e)


def evaluate(response: str, test: Dict) -> tuple:
    """Evaluate response quality."""
    response_lower = response.lower()
    
    # Check expected answer
    if "expected" in test:
        expected = str(test["expected"]).lower()
        if expected in response_lower or expected.replace(".", ",") in response_lower:
            return True, 1.0
        if "," in expected and expected.replace(",", "") in response_lower:
            return True, 1.0
    
    # Check keywords
    if "expected_keywords" in test:
        keywords = test["expected_keywords"]
        matches = sum(1 for kw in keywords if kw.lower() in response_lower)
        accuracy = matches / len(keywords)
        return accuracy >= 0.6, accuracy
    
    return False, 0.0


def main():
    model = "qwen3.6:latest"
    
    print("="*80)
    print(f"🔬 QWEN 3.6 BENCHMARK (Ollama)")
    print("="*80)
    print()
    
    # Check if model exists
    result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    if model not in result.stdout:
        print(f"❌ Model '{model}' not found. Download with: ollama pull {model}")
        sys.exit(1)
    
    print(f"✅ Model: {model}")
    print()
    
    all_results = []
    
    for i, test in enumerate(TEST_PROMPTS, 1):
        print(f"[{i}/{len(TEST_PROMPTS)}] {test['name']}...", end=" ", flush=True)
        
        response, latency, error = run_ollama_test(test["prompt"], model)
        
        if error:
            print(f"❌ {latency/1000:.1f}s - {error}")
            all_results.append(BenchmarkResult(
                test_id=test["id"],
                test_name=test["name"],
                model=model,
                success=False,
                latency_ms=latency,
                response_preview="",
                accuracy=0.0,
                error=error
            ))
            continue
        
        success, accuracy = evaluate(response, test)
        status = "✅" if success else "❌"
        print(f"{status} {latency/1000:.1f}s (acc: {accuracy*100:.0f}%)")
        
        all_results.append(BenchmarkResult(
            test_id=test["id"],
            test_name=test["name"],
            model=model,
            success=success,
            latency_ms=latency,
            response_preview=response[:300].replace("\n", " "),
            accuracy=accuracy
        ))
    
    # Summary
    print()
    print("="*80)
    print("SUMMARY")
    print("="*80)
    
    success_rate = sum(1 for r in all_results if r.success) / len(all_results) * 100
    avg_latency = sum(r.latency_ms for r in all_results) / len(all_results) / 1000
    avg_accuracy = sum(r.accuracy for r in all_results) / len(all_results) * 100
    
    print(f"Success Rate: {success_rate:.0f}%")
    print(f"Avg Latency: {avg_latency:.1f}s")
    print(f"Avg Accuracy: {avg_accuracy:.0f}%")
    print()
    
    # Save report
    report_path = Path(__file__).parent / "qwen36_ollama_benchmark.md"
    
    report = f"""# 🔬 Qwen 3.6 Ollama Benchmark

**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Model:** {model}

## Summary

| Metric | Value |
|--------|-------|
| Success Rate | {success_rate:.0f}% |
| Avg Latency | {avg_latency:.1f}s |
| Avg Accuracy | {avg_accuracy:.0f}% |

## Detailed Results

| Test | Category | Success | Latency | Accuracy |
|------|----------|---------|---------|----------|
"""
    
    for r in all_results:
        status = "✅" if r.success else "❌"
        report += f"| {r.test_name} | {r.test_id.split('_')[0]} | {status} | {r.latency_ms/1000:.1f}s | {r.accuracy*100:.0f}% |\n"
    
    report += f"""
## Raw Data

```json
{json.dumps([asdict(r) for r in all_results], indent=2)}
```
"""
    
    with open(report_path, "w") as f:
        f.write(report)
    
    print(f"📁 Report saved: {report_path}")


if __name__ == "__main__":
    main()
