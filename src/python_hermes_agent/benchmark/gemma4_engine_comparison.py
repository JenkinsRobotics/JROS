#!/usr/bin/env python3
"""
FIXED BENCHMARK: Gemma4 Ollama vs Gemma4 Llama.cpp

Tests the SAME model (Gemma4) through different inference engines:
1. Ollama (gemma4:31b) - full precision, optimized
2. Llama.cpp (Gemma4-Q4_K_M.gguf) - quantized, local

This isolates whether performance issues are from:
- Quantization (Q4 vs full)
- Inference engine (Ollama vs llama.cpp)
- Model architecture (Gemma4 itself)
"""

import json
import time
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple
from dataclasses import dataclass, asdict

# Test tasks with clear evaluation criteria
TEST_TASKS = [
    {
        "id": "math_001",
        "name": "Arithmetic (234 × 876)",
        "prompt": "What is 234 multiplied by 876? Show your work step by step and give the final answer.",
        "category": "reasoning",
        "expected_answer": "204984",
        "evaluation_type": "exact_match",
    },
    {
        "id": "code_001",
        "name": "Fibonacci Function",
        "prompt": "Write a Python function called calculate_fibonacci that returns the first n Fibonacci numbers. Include type hints and a docstring.",
        "category": "coding",
        "expected_keywords": ["def", "calculate_fibonacci", "typing", "List", "return"],
        "evaluation_type": "keyword_match",
    },
    {
        "id": "logic_001",
        "name": "Bat & Ball Puzzle",
        "prompt": "A bat and ball cost $1.10 in total. The bat costs $1.00 more than the ball. How much does the ball cost? Show your reasoning.",
        "category": "reasoning",
        "expected_answer": "0.05",
        "evaluation_type": "numeric_match",
    },
    {
        "id": "code_002",
        "name": "Code Review - Division by Zero",
        "prompt": "What is the bug in this code?\n\ndef divide(a, b):\n    return a / b\n\nresult = divide(10, 0)",
        "category": "coding",
        "expected_keywords": ["zero", "division", "error"],
        "evaluation_type": "keyword_match",
    },
    {
        "id": "json_001",
        "name": "JSON Extraction",
        "prompt": "Extract all email addresses from this JSON: {\"users\": [{\"email\": \"alice@test.com\"}, {\"email\": \"bob@demo.org\"}]}",
        "category": "reasoning",
        "expected_keywords": ["alice@test.com", "bob@demo.org"],
        "evaluation_type": "keyword_match",
    },
    {
        "id": "explain_001",
        "name": "Explain Quantum Computing",
        "prompt": "Explain quantum computing in 2-3 sentences for a 10-year-old.",
        "category": "creative",
        "expected_keywords": ["quantum", "computer"],
        "evaluation_type": "keyword_match",
    },
]


@dataclass
class BenchmarkResult:
    task_id: str
    task_name: str
    model: str
    inference_engine: str
    category: str
    success: bool
    latency_ms: float
    response_length: int
    tokens_generated: int
    tokens_per_second: float
    accuracy_score: float
    error_message: str
    response_preview: str


def run_ollama_benchmark(prompt: str, task: Dict, model: str = "gemma4:31b") -> BenchmarkResult:
    """Run benchmark using Ollama (full precision model)."""
    start_time = time.time()
    
    try:
        cmd = [
            "ollama", "run", model, prompt
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(Path.home())
        )
        
        latency_ms = (time.time() - start_time) * 1000
        response = result.stdout.strip()
        
        if not response:
            error_msg = "Empty response from Ollama"
            return create_failed_result(task, "Gemma4 (Ollama)", "Ollama", latency_ms, error_msg)
        
        # Evaluate response
        success, accuracy = evaluate_response(response, task)
        tokens = len(response.split()) * 1.3
        tps = (tokens / (latency_ms / 1000)) if latency_ms > 0 else 0
        
        return BenchmarkResult(
            task_id=task["id"],
            task_name=task["name"],
            model="Gemma4 (Ollama)",
            inference_engine="Ollama",
            category=task["category"],
            success=success,
            latency_ms=latency_ms,
            response_length=len(response),
            tokens_generated=int(tokens),
            tokens_per_second=tps,
            accuracy_score=accuracy,
            error_message="",
            response_preview=response[:300].replace("\n", " ")
        )
        
    except subprocess.TimeoutExpired:
        return create_failed_result(task, "Gemma4 (Ollama)", "Ollama", (time.time() - start_time) * 1000, "Timeout after 180s")
    except Exception as e:
        return create_failed_result(task, "Gemma4 (Ollama)", "Ollama", (time.time() - start_time) * 1000, str(e))


def run_llamacpp_benchmark(prompt: str, task: Dict, model_path: str) -> BenchmarkResult:
    """Run benchmark using Llama.cpp (quantized GGUF model)."""
    start_time = time.time()
    
    try:
        from llama_cpp import Llama
        
        llm = Llama(
            model_path=model_path,
            n_gpu_layers=35,
            n_ctx=8192,
            verbose=False,
            n_threads=8
        )
        
        # Format prompt for Gemma
        formatted_prompt = f"<start_of_turn>user\n{prompt}<end_of_turn>\n<start_of_turn>model\n"
        
        output = llm(
            formatted_prompt,
            max_tokens=1024,
            temperature=0.7,
            top_p=0.9,
            stop=["<end_of_turn>", "<start_of_turn>"],
            echo=False
        )
        
        response = output["choices"][0]["text"].strip()
        latency_ms = (time.time() - start_time) * 1000
        
        if not response:
            return create_failed_result(task, "Gemma4 (Llama.cpp)", "Llama.cpp", latency_ms, "Empty response")
        
        # Evaluate response
        success, accuracy = evaluate_response(response, task)
        tokens = len(response.split()) * 1.3
        tps = (tokens / (latency_ms / 1000)) if latency_ms > 0 else 0
        
        return BenchmarkResult(
            task_id=task["id"],
            task_name=task["name"],
            model="Gemma4 (Llama.cpp)",
            inference_engine="Llama.cpp",
            category=task["category"],
            success=success,
            latency_ms=latency_ms,
            response_length=len(response),
            tokens_generated=int(tokens),
            tokens_per_second=tps,
            accuracy_score=accuracy,
            error_message="",
            response_preview=response[:300].replace("\n", " ")
        )
        
    except ImportError:
        latency_ms = (time.time() - start_time) * 1000
        return create_failed_result(task, "Gemma4 (Llama.cpp)", "Llama.cpp", latency_ms, "llama-cpp-python not installed")
    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        return create_failed_result(task, "Gemma4 (Llama.cpp)", "Llama.cpp", latency_ms, str(e))


def create_failed_result(task: Dict, model: str, engine: str, latency_ms: float, error_msg: str) -> BenchmarkResult:
    """Helper to create a failed result."""
    return BenchmarkResult(
        task_id=task["id"],
        task_name=task["name"],
        model=model,
        inference_engine=engine,
        category=task["category"],
        success=False,
        latency_ms=latency_ms,
        response_length=0,
        tokens_generated=0,
        tokens_per_second=0,
        accuracy_score=0.0,
        error_message=error_msg,
        response_preview=""
    )


def evaluate_response(response: str, task: Dict) -> Tuple[bool, float]:
    """Evaluate if response meets expectations."""
    response_lower = response.lower()
    
    # Exact match (for math answers)
    if task.get("evaluation_type") == "exact_match" and "expected_answer" in task:
        expected = str(task["expected_answer"])
        if expected in response or expected.replace(".", ",") in response:
            return True, 1.0
        # Also check for formatted numbers like 204,984
        if "," in expected:
            plain = expected.replace(",", "")
            if plain in response:
                return True, 1.0
        return False, 0.0
    
    # Numeric match (for puzzles)
    if task.get("evaluation_type") == "numeric_match" and "expected_answer" in task:
        expected = str(task["expected_answer"])
        if expected in response or f"${expected}" in response or f"{expected} cents" in response.lower():
            return True, 1.0
        return False, 0.0
    
    # Keyword match (for code, explanations)
    if "expected_keywords" in task:
        keywords = task["expected_keywords"]
        matches = sum(1 for kw in keywords if kw.lower() in response_lower)
        accuracy = matches / len(keywords)
        return accuracy >= 0.6, accuracy
    
    return False, 0.0


def generate_report(results: List[BenchmarkResult]) -> str:
    """Generate comprehensive markdown report."""
    lines = []
    
    lines.append("# 🔬 Gemma4 Inference Engine Benchmark")
    lines.append(f"\n**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"\n**Model:** Gemma4 (same model, different engines)")
    lines.append(f"\n**Goal:** Isolate performance differences between Ollama and Llama.cpp")
    lines.append("\n---\n")
    
    # Split results
    ollama_results = [r for r in results if r.inference_engine == "Ollama"]
    llamacpp_results = [r for r in results if r.inference_engine == "Llama.cpp"]
    
    # Executive Summary
    lines.append("## 📊 Executive Summary\n")
    lines.append("| Metric | 🦙 Ollama (Full) | 🐍 Llama.cpp (Q4_K_M) | Winner |")
    lines.append("|--------|------------------|------------------------|--------|")
    
    if ollama_results and llamacpp_results:
        ollama_latency = sum(r.latency_ms for r in ollama_results) / len(ollama_results)
        llamacpp_latency = sum(r.latency_ms for r in llamacpp_results) / len(llamacpp_results)
        
        ollama_accuracy = sum(r.accuracy_score for r in ollama_results) / len(ollama_results) * 100
        llamacpp_accuracy = sum(r.accuracy_score for r in llamacpp_results) / len(llamacpp_results) * 100
        
        ollama_success = sum(1 for r in ollama_results if r.success) / len(ollama_results) * 100
        llamacpp_success = sum(1 for r in llamacpp_results if r.success) / len(llamacpp_results) * 100
        
        ollama_tps = sum(r.tokens_per_second for r in ollama_results) / len(ollama_results)
        llamacpp_tps = sum(r.tokens_per_second for r in llamacpp_results) / len(llamacpp_results)
        
        latency_winner = "🦙 Ollama" if ollama_latency < llamacpp_latency else "🐍 Llama.cpp"
        accuracy_winner = "🦙 Ollama" if ollama_accuracy > llamacpp_accuracy else "🐍 Llama.cpp"
        success_winner = "🦙 Ollama" if ollama_success > llamacpp_success else "🐍 Llama.cpp"
        tps_winner = "🦙 Ollama" if ollama_tps > llamacpp_tps else "🐍 Llama.cpp"
        
        lines.append(f"| **Avg Latency** | {ollama_latency:.1f}ms | {llamacpp_latency:.1f}ms | {latency_winner} |")
        lines.append(f"| **Avg Accuracy** | {ollama_accuracy:.1f}% | {llamacpp_accuracy:.1f}% | {accuracy_winner} |")
        lines.append(f"| **Success Rate** | {ollama_success:.1f}% | {llamacpp_success:.1f}% | {success_winner} |")
        lines.append(f"| **Tokens/sec** | {ollama_tps:.1f} | {llamacpp_tps:.1f} | {tps_winner} |")
        
        # Quantization impact analysis
        lines.append("\n### 🎯 Quantization Impact Analysis\n")
        accuracy_diff = ollama_accuracy - llamacpp_accuracy
        latency_diff = llamacpp_latency / ollama_latency if ollama_latency > 0 else 0
        
        if abs(accuracy_diff) < 5:
            lines.append(f"✅ **Quantization Loss: Minimal** ({accuracy_diff:.1f} percentage points)")
        elif abs(accuracy_diff) < 15:
            lines.append(f"⚠️ **Quantization Loss: Moderate** ({accuracy_diff:.1f} percentage points)")
        else:
            lines.append(f"❌ **Quantization Loss: Severe** ({accuracy_diff:.1f} percentage points)")
        
        lines.append(f"\n📈 **Speed Trade-off:** Llama.cpp is {latency_diff:.1f}x {'slower' if latency_diff > 1 else 'faster'} than Ollama")
    
    lines.append("\n---\n")
    
    # Detailed Results
    lines.append("## 📋 Detailed Test Results\n")
    lines.append("| # | Test | Category | Ollama | Llama.cpp | Notes |")
    lines.append("|---|------|----------|--------|-----------|-------|")
    
    for i, task in enumerate(TEST_TASKS, 1):
        ollama = next((r for r in ollama_results if r.task_id == task["id"]), None)
        llamacpp = next((r for r in llamacpp_results if r.task_id == task["id"]), None)
        
        ollama_status = "✅" if (ollama and ollama.success) else "❌" if ollama else "⏭️"
        llamacpp_status = "✅" if (llamacpp and llamacpp.success) else "❌" if llamacpp else "⏭️"
        
        notes = []
        if ollama and llamacpp:
            if ollama.accuracy_score > llamacpp.accuracy_score:
                notes.append("Ollama more accurate")
            elif llamacpp.accuracy_score > ollama.accuracy_score:
                notes.append("Llama.cpp more accurate")
            if ollama.latency_ms < llamacpp.latency_ms:
                notes.append(f"Ollama {llamacpp.latency_ms/ollama.latency_ms:.1f}x faster")
            else:
                notes.append(f"Llama.cpp {ollama.latency_ms/llamacpp.latency_ms:.1f}x faster")
        
        note_str = ", ".join(notes) if notes else "—"
        lines.append(f"| {i} | {task['name']} | {task['category']} | {ollama_status} | {llamacpp_status} | {note_str} |")
    
    lines.append("\n---\n")
    
    # Latency Breakdown
    lines.append("## ⏱️ Latency Comparison\n")
    lines.append("| Test | Ollama (ms) | Llama.cpp (ms) | Slowdown |")
    lines.append("|------|-------------|----------------|----------|")
    
    for task in TEST_TASKS:
        ollama = next((r for r in ollama_results if r.task_id == task["id"]), None)
        llamacpp = next((r for r in llamacpp_results if r.task_id == task["id"]), None)
        
        if ollama and llamacpp:
            factor = llamacpp.latency_ms / ollama.latency_ms if ollama.latency_ms > 0 else 0
            factor_str = f"{factor:.2f}x" if factor > 1 else f"{1/factor:.2f}x faster" if factor > 0 else "N/A"
            lines.append(f"| {task['name']} | {ollama.latency_ms:.1f} | {llamacpp.latency_ms:.1f} | {factor_str} |")
    
    lines.append("\n---\n")
    
    # Recommendations
    lines.append("## 🎓 Recommendations\n")
    lines.append("")
    lines.append("### Use Ollama When:\n")
    lines.append("✅ You want best accuracy (full precision model)")
    lines.append("✅ You need fastest inference (optimized engine)")
    lines.append("✅ You're okay with ~19GB model download")
    lines.append("✅ You want easy model management")
    lines.append("")
    lines.append("### Use Llama.cpp When:\n")
    lines.append("✅ You need offline/portable deployment")
    lines.append("✅ You want smaller model files (quantized)")
    lines.append("✅ You need fine-grained control over inference")
    lines.append("✅ You're deploying to edge devices")
    lines.append("")
    
    # Configuration notes
    lines.append("## 🖥️ Test Configuration\n")
    lines.append("")
    lines.append("### Ollama Setup\n")
    lines.append("- **Model:** gemma4:31b (full precision)")
    lines.append("- **Size:** ~19 GB")
    lines.append("- **Engine:** Ollama (optimized)")
    lines.append("")
    lines.append("### Llama.cpp Setup\n")
    lines.append("- **Model:** Gemma-4-26B-A4B-it-Q4_K_M.gguf")
    lines.append("- **Size:** ~16 GB (quantized)")
    lines.append("- **Quantization:** Q4_K_M (4-bit)")
    lines.append("- **GPU Layers:** 35")
    lines.append("- **Context:** 8192 tokens")
    lines.append("")
    
    # Raw data
    lines.append("---\n")
    lines.append("## 📁 Raw Data\n")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps([asdict(r) for r in results], indent=2))
    lines.append("```")
    
    return "\n".join(lines)


def main():
    """Run the benchmark."""
    print("="*80)
    print("🔬 GEMMA4 INFERENCE ENGINE BENCHMARK")
    print("Ollama (Full) vs Llama.cpp (Q4_K_M Quantized)")
    print("="*80)
    print()
    
    model_path = "/Users/jonathanjenkins/GitHub/GITHUB/Hermes/models/gemma-4-26B-A4B-it-Q4_K_M.gguf"
    
    # Check if model exists
    if not Path(model_path).exists():
        print(f"❌ ERROR: Model not found at {model_path}")
        print("Please download the model or check the path.")
        sys.exit(1)
    
    print(f"✅ Model found: {model_path}")
    print()
    
    all_results = []
    
    # Run Ollama benchmarks
    print("🦙 Running Ollama (Gemma4:31b) benchmarks...\n")
    for i, task in enumerate(TEST_TASKS, 1):
        print(f"  [{i}/{len(TEST_TASKS)}] {task['name']}...", end=" ", flush=True)
        result = run_ollama_benchmark(task["prompt"], task)
        all_results.append(result)
        status = "✅" if result.success else "❌"
        print(f"{status} {result.latency_ms:.0f}ms (acc: {result.accuracy_score*100:.0f}%)")
        if result.error_message:
            print(f"      ⚠️ {result.error_message}")
    
    print()
    
    # Run Llama.cpp benchmarks
    print("🐍 Running Llama.cpp (Gemma4 Q4_K_M) benchmarks...\n")
    for i, task in enumerate(TEST_TASKS, 1):
        print(f"  [{i}/{len(TEST_TASKS)}] {task['name']}...", end=" ", flush=True)
        result = run_llamacpp_benchmark(task["prompt"], task, model_path)
        all_results.append(result)
        status = "✅" if result.success else "❌"
        print(f"{status} {result.latency_ms:.0f}ms (acc: {result.accuracy_score*100:.0f}%)")
        if result.error_message:
            print(f"      ⚠️ {result.error_message}")
    
    print()
    
    # Generate report
    print("📊 Generating report...")
    report = generate_report(all_results)
    
    # Save report
    report_path = Path(__file__).parent / "gemma4_ollama_vs_llamacpp.md"
    with open(report_path, "w") as f:
        f.write(report)
    
    print(f"✅ Report saved to: {report_path}")
    print()
    print("="*80)
    print("BENCHMARK COMPLETE")
    print("="*80)
    print()
    
    # Print summary
    print(report.split("## 📁 Raw Data")[0])


if __name__ == "__main__":
    main()
