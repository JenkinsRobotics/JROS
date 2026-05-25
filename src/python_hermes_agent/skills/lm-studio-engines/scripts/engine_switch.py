#!/usr/bin/env python3
"""
Quick engine switcher for LM Studio backends.
Usage: python engine_switch.py <engine>

Available engines:
  mlx-1.6     — MLX 1.6.0 (fastest for Apple Silicon, MLX models only)
  mlx-1.5     — MLX 1.5.0
  llama-2.16  — llama.cpp 2.16.0 (latest, recommended for GGUF)
  llama-2.14  — llama.cpp 2.14.0 (stable)
  llama-2.13  — llama.cpp 2.13.0
"""
import sys
from hermes_tools import terminal

ENGINES = {
    "mlx-1.6": "/Users/jonathanjenkins/.lmstudio/extensions/backends/mlx-llm-mac-arm64-apple-metal-advsimd-1.6.0/libllm_engine.dylib",
    "mlx-1.5": "/Users/jonathanjenkins/.lmstudio/extensions/backends/mlx-llm-mac-arm64-apple-metal-advsimd-1.5.0/libllm_engine.dylib",
    "llama-2.16": "/Users/jonathanjenkins/.lmstudio/extensions/backends/llama.cpp-mac-arm64-apple-metal-advsimd-2.16.0/libllm_engine.dylib",
    "llama-2.14": "/Users/jonathanjenkins/.lmstudio/extensions/backends/llama.cpp-mac-arm64-apple-metal-advsimd-2.14.0/libllm_engine.dylib",
    "llama-2.13": "/Users/jonathanjenkins/.lmstudio/extensions/backends/llama.cpp-mac-arm64-apple-metal-advsimd-2.13.0/libllm_engine.dylib",
}

if len(sys.argv) < 2:
    print("Usage: python engine_switch.py <engine>")
    print("Available:", list(ENGINES.keys()))
    sys.exit(1)

engine = sys.argv[1]
if engine not in ENGINES:
    print(f"Unknown engine: {engine}")
    print("Available:", list(ENGINES.keys()))
    sys.exit(1)

terminal(command=f"export LLM_ENGINE_PATH={ENGINES[engine]}")
print(f"✓ Switched to {engine}")
print(f"  Path: {ENGINES[engine]}")
