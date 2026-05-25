#!/usr/bin/env python3
"""
Quick test for llama-cpp provider in Hermes.
Tests loading a local GGUF model and running inference.
"""

import os
import sys
from pathlib import Path

# Test llama-cpp-python directly
print("=" * 60)
print("Testing llama-cpp-python Installation")
print("=" * 60)

try:
    from llama_cpp import Llama
    print("✓ llama-cpp-python imported successfully")
except Exception as e:
    print(f"✗ Failed to import llama-cpp-python: {e}")
    sys.exit(1)

# Test model loading
MODEL_PATH = "/Users/jonathanjenkins/GitHub/GITHUB/Hermes/models/gemma-4-26B-A4B-it-Q4_K_M.gguf"

if not Path(MODEL_PATH).exists():
    print(f"✗ Model not found: {MODEL_PATH}")
    sys.exit(1)

print(f"\n✓ Model file exists: {MODEL_PATH}")
print(f"  Size: {Path(MODEL_PATH).stat().st_size / (1024**3):.2f} GB")

print("\nLoading model (this may take 10-30 seconds)...")
try:
    llm = Llama(
        model_path=MODEL_PATH,
        n_ctx=8192,
        n_gpu_layers=35,
        verbose=False
    )
    print("✓ Model loaded successfully!")
    
    print("\nRunning test inference...")
    output = llm(
        "What is 2 + 2? Answer in one word.",
        max_tokens=10,
        temperature=0.1
    )
    
    text = output["choices"][0]["text"].strip()
    print(f"✓ Inference successful!")
    print(f"  Prompt: 'What is 2 + 2? Answer in one word.'")
    print(f"  Response: '{text}'")
    
    print("\n" + "=" * 60)
    print("SUCCESS: llama-cpp provider is ready for Hermes!")
    print("=" * 60)
    
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
