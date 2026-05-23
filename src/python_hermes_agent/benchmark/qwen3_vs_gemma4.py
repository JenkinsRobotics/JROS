#!/usr/bin/env python3
"""
Direct Model Comparison: Qwen3-Coder-30B vs Gemma4-26B (both via llama.cpp)

Tests the SAME inference engine with DIFFERENT models to isolate model quality.
"""

import time
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple
from dataclasses import dataclass, asdict
import json

# Check for llama_cpp
try:
    from llama_cpp import Llama
except ImportError:
    print("❌ llama-cpp-python not installed. Run: pip install llama-cpp-python")
    sys.exit(1)

# Model paths
QWEN_PATH = "/Users/jonathanjenkins/GitHub/GITHUB/Hermes/models/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf"
GEMMA_PATH = "/Users/jonathanjenkins/GitHub/GITHUB/Hermes/models/gemma-4-26B-A4B-it-Q4_K_M.gguf"

# Test prompts
TEST_PROMPTS = [
    {
        "id": "math_001",
        "name": "Simple Math",
        "prompt": "What is 234 * 876? Give the final answer.",
        "expected": "204984",
        "category": "reasoning"
    },
    {
        "id": "code_001", 
        "name": "Python Function",
        "prompt": "Write a Python function called 'calculate_fibonacci' with type hints.",
        "expected_keywords": ["def", "calculate_fibonacci", "return"],
        "category": "coding"
    },
    {
        "id": "logic_001",
        "name": "Bat & Ball",
        "prompt": "A bat and ball cost $1.10 total. Bat costs $1.00 more than ball. How much is the ball?",
        "expected": "0.05",
        "category": "reasoning"
    },
]


@dataclass
class ModelResult:
    model_name: str
    model_path: str
    test_id: str
    test_name: str
    success: bool
    latency_ms: float
    response: str
    accuracy: float
    error: str = ""


def load_model(model_path: str, model_name: str):
    """Load a model with optimized settings."""
    print(f"\n📦 Loading {model_name}...")
    print(f"   Path: {model_path}")
    
    if not Path(model_path).exists():
        raise FileNotFoundError(f"Model not found: {model_path}")
    
    start = time.time()
    
    llm = Llama(
        model_path=model_path,
        n_gpu_layers=40,  # More GPU offload
        n_ctx=8192,
        n_batch=512,
        n_threads=8,
        n_threads_batch=8,
        verbose=False,
        chat_format="chatml" if "Qwen" in model_name else None
    )
    
    load_time = time.time() - start
    print(f"✅ Loaded in {load_time:.1f}s")
    
    return llm


def run_inference(llm: Llama, prompt: str, model_name: str) -> Tuple[str, float]:
    """Run inference and measure latency."""
    # Format prompt based on model
    if "Qwen" in model_name:
        formatted = f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"
        stop_tokens = ["<|im_end|>", "<|im_start|>"]
    else:
        formatted = f"<start_of_turn>user\n{prompt}<end_of_turn>\n<start_of_turn>model\n"
        stop_tokens = ["<end_of_turn>", "<start_of_turn>"]
    
    start = time.time()
    
    try:
        output = llm(
            formatted,
            max_tokens=512,
            temperature=0.7,
            top_p=0.9,
            stop=stop_tokens,
            echo=False
        )
        
        latency = (time.time() - start) * 1000
        response = output["choices"][0]["text"].strip()
        
        return response, latency
        
    except Exception as e:
        latency = (time.time() - start) * 1000
        return f"ERROR: {str(e)}", latency


def evaluate(response: str, test: Dict) -> Tuple[bool, float]:
    """Evaluate response quality."""
    response_lower = response.lower()
    
    # Check for expected answer
    if "expected" in test:
        expected = str(test["expected"]).lower()
        if expected in response_lower:
            return True, 1.0
        # Check formatted numbers
        if "," in expected:
            if expected.replace(",", "") in response_lower:
                return True, 1.0
    
    # Check keywords
    if "expected_keywords" in test:
        keywords = test["expected_keywords"]
        matches = sum(1 for kw in keywords if kw.lower() in response_lower)
        accuracy = matches / len(keywords)
        return accuracy >= 0.6, accuracy
    
    return False, 0.0


def run_benchmark(llm: Llama, model_name: str, model_path: str) -> List[ModelResult]:
    """Run full benchmark on a model."""
    results = []
    
    print(f"\n{'='*80}")
    print(f"Testing: {model_name}")
    print(f"{'='*80}\n")
    
    for i, test in enumerate(TEST_PROMPTS, 1):
        print(f"[{i}/{len(TEST_PROMPTS)}] {test['name']}...", end=" ", flush=True)
        
        response, latency = run_inference(llm, test["prompt"], model_name)
        success, accuracy = evaluate(response, test)
        
        status = "✅" if success else "❌"
        print(f"{status} {latency/1000:.1f}s")
        
        if not success:
            print(f"   Response: {response[:100]}...")
        
        results.append(ModelResult(
            model_name=model_name,
            model_path=model_path,
            test_id=test["id"],
            test_name=test["name"],
            success=success,
            latency_ms=latency,
            response=response[:500],
            accuracy=accuracy,
            error="" if success else "Low accuracy"
        ))
    
    return results


def generate_report(all_results: List[ModelResult]) -> str:
    """Generate markdown report."""
    lines = []
    
    lines.append("# 🔬 Model Comparison: Qwen3-Coder-30B vs Gemma4-26B")
    lines.append(f"\n**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"\n**Engine:** llama.cpp (same for both)")
    lines.append(f"\n**Goal:** Isolate model quality differences\n")
    lines.append("---\n")
    
    # Split by model
    qwen_results = [r for r in all_results if "Qwen" in r.model_name]
    gemma_results = [r for r in all_results if "Gemma" in r.model_name]
    
    # Summary
    lines.append("## 📊 Executive Summary\n")
    lines.append("| Metric | Qwen3-Coder-30B | Gemma4-26B | Winner |")
    lines.append("|--------|-----------------|------------|--------|")
    
    if qwen_results and gemma_results:
        qwen_success = sum(1 for r in qwen_results if r.success) / len(qwen_results) * 100
        gemma_success = sum(1 for r in gemma_results if r.success) / len(gemma_results) * 100
        
        qwen_latency = sum(r.latency_ms for r in qwen_results) / len(qwen_results)
        gemma_latency = sum(r.latency_ms for r in gemma_results) / len(gemma_results)
        
        qwen_accuracy = sum(r.accuracy for r in qwen_results) / len(qwen_results) * 100
        gemma_accuracy = sum(r.accuracy for r in gemma_results) / len(gemma_results) * 100
        
        winner_success = "Qwen3" if qwen_success > gemma_success else "Gemma4" if gemma_success > qwen_success else "Tie"
        winner_latency = "Qwen3" if qwen_latency < gemma_latency else "Gemma4" if gemma_latency < qwen_latency else "Tie"
        winner_accuracy = "Qwen3" if qwen_accuracy > gemma_accuracy else "Gemma4" if gemma_accuracy > qwen_accuracy else "Tie"
        
        lines.append(f"| **Success Rate** | {qwen_success:.0f}% | {gemma_success:.0f}% | {winner_success} |")
        lines.append(f"| **Avg Latency** | {qwen_latency/1000:.1f}s | {gemma_latency/1000:.1f}s | {winner_latency} |")
        lines.append(f"| **Avg Accuracy** | {qwen_accuracy:.0f}% | {gemma_accuracy:.0f}% | {winner_accuracy} |")
        
        # Model specs
        lines.append("\n### 📐 Model Specifications\n")
        lines.append("| Spec | Qwen3-Coder-30B | Gemma4-26B |")
        lines.append("|------|-----------------|------------|")
        lines.append("| Parameters | 30B (A3B MoE) | 26B (A4B MoE) |")
        lines.append("| Quantization | Q4_K_M | Q4_K_M |")
        lines.append("| File Size | 18.6 GB | 16.0 GB |")
        lines.append("| Context | 256K | 262K |")
    
    lines.append("\n---\n")
    
    # Detailed results
    lines.append("## 📋 Test-by-Test Results\n")
    lines.append("| Test | Category | Qwen3 | Gemma4 | Qwen Time | Gemma Time |")
    lines.append("|------|----------|-------|--------|-----------|------------|")
    
    for test in TEST_PROMPTS:
        qwen = next((r for r in qwen_results if r.test_id == test["id"]), None)
        gemma = next((r for r in gemma_results if r.test_id == test["id"]), None)
        
        qwen_status = "✅" if (qwen and qwen.success) else "❌"
        gemma_status = "✅" if (gemma and gemma.success) else "❌"
        
        qwen_time = f"{qwen.latency_ms/1000:.1f}s" if qwen else "N/A"
        gemma_time = f"{gemma.latency_ms/1000:.1f}s" if gemma else "N/A"
        
        lines.append(f"| {test['name']} | {test['category']} | {qwen_status} | {gemma_status} | {qwen_time} | {gemma_time} |")
    
    lines.append("\n---\n")
    
    # Conclusions
    lines.append("## 🎓 Conclusions\n")
    lines.append("")
    
    if qwen_success > gemma_success:
        lines.append("### 🏆 Qwen3-Coder-30B Wins\n")
        lines.append(f"- Higher accuracy ({qwen_accuracy:.0f}% vs {gemma_accuracy:.0f}%)")
        lines.append(f"- Better success rate ({qwen_success:.0f}% vs {gemma_success:.0f}%)")
        if qwen_latency < gemma_latency:
            lines.append(f"- Faster inference ({qwen_latency/1000:.1f}s vs {gemma_latency/1000:.1f}s)")
    elif gemma_success > qwen_success:
        lines.append("### 🏆 Gemma4-26B Wins\n")
        lines.append(f"- Higher accuracy ({gemma_accuracy:.0f}% vs {qwen_accuracy:.0f}%)")
        lines.append(f"- Better success rate ({gemma_success:.0f}% vs {qwen_success:.0f}%)")
        if gemma_latency < qwen_latency:
            lines.append(f"- Faster inference ({gemma_latency/1000:.1f}s vs {qwen_latency/1000:.1f}s)")
    else:
        lines.append("### 🤝 It's a Tie\n")
        lines.append("Both models perform similarly on these tests.")
    
    lines.append("\n### 💡 Recommendations\n")
    lines.append("")
    if qwen_success > gemma_success:
        lines.append("**Use Qwen3-Coder-30B when:**")
        lines.append("- You need better coding capabilities")
        lines.append("- Accuracy is more important than speed")
        lines.append("- You have the disk space (18.6GB)")
    else:
        lines.append("**Use Gemma4-26B when:**")
        lines.append("- You need faster inference")
        lines.append("- Disk space is limited (16GB)")
        lines.append("- General reasoning is the priority")
    
    lines.append("\n---\n")
    lines.append("## 📁 Raw Data\n")
    lines.append("```json")
    lines.append(json.dumps([asdict(r) for r in all_results], indent=2))
    lines.append("```")
    
    return "\n".join(lines)


def main():
    print("="*80)
    print("🔬 MODEL COMPARISON: Qwen3-Coder-30B vs Gemma4-26B")
    print("Both via llama.cpp (isolating model quality)")
    print("="*80)
    
    all_results = []
    
    # Test Qwen3
    try:
        qwen_llm = load_model(QWEN_PATH, "Qwen3-Coder-30B")
        qwen_results = run_benchmark(qwen_llm, "Qwen3-Coder-30B", QWEN_PATH)
        all_results.extend(qwen_results)
        del qwen_llm  # Free memory
    except Exception as e:
        print(f"❌ Qwen3 failed: {e}")
    
    # Test Gemma4
    try:
        gemma_llm = load_model(GEMMA_PATH, "Gemma4-26B")
        gemma_results = run_benchmark(gemma_llm, "Gemma4-26B", GEMMA_PATH)
        all_results.extend(gemma_results)
        del gemma_llm
    except Exception as e:
        print(f"❌ Gemma4 failed: {e}")
    
    # Generate report
    print("\n📊 Generating report...")
    report = generate_report(all_results)
    
    # Save
    report_path = Path(__file__).parent / "qwen3_vs_gemma4_comparison.md"
    with open(report_path, "w") as f:
        f.write(report)
    
    print(f"✅ Report saved: {report_path}")
    print("\n" + "="*80)
    
    # Print summary
    print(report.split("## 📁 Raw Data")[0])


if __name__ == "__main__":
    main()
