---
name: lm-studio-engines
description: Multi-engine inference support using LM Studio backends (llama.cpp, MLX, etc.)
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [Inference, Engines, LM Studio, Performance]
    related_skills: [native-mcp]
---

# LM Studio Multi-Engine Support

This skill enables Hermes to use LM Studio's multiple inference engines for optimal performance across different model types and use cases.

## Runtime Framework

Engines are now managed in `~/.hermes/runtimes/` with versioned folders and symlinks:
```
~/.hermes/runtimes/
  ├── llama.cpp/
  │   ├── 2.16.0/ → [LM Studio backend]
  │   ├── 2.14.0/ → [LM Studio backend]
  │   └── latest → 2.16.0
  └── mlx/
      ├── 1.6.0/ → [LM Studio backend]
      └── latest → 1.6.0
```

**Management CLI:**
```bash
python ~/.hermes/scripts/runtime_manager.py list      # Show all runtimes
python ~/.hermes/scripts/runtime_manager.py use llama.cpp 2.14.0  # Switch version
python ~/.hermes/scripts/runtime_manager.py compat <model.gguf>   # Check compatibility
```

**See Also:** `references/runtime-manager.md` — Complete CLI reference with all commands, workflows, and troubleshooting.

## When to Use

Use this when you want to:
- Switch between llama.cpp and MLX engines based on model type
- Use specific engine versions for compatibility
- Optimize for speed (MLX) vs compatibility (llama.cpp)
- Run MLX-native models that llama.cpp can't load
- Test different engine backends for performance comparison

## Engine Comparison

| Engine | Best For | Speed | Compatibility | Memory |
|--------|----------|-------|---------------|--------|
| **MLX 1.6.0** | Apple Silicon, MLX models | ⭐⭐⭐⭐⭐ | Medium | Low |
| **llama.cpp 2.16.0** | Latest GGUF features | ⭐⭐⭐⭐ | High | Medium |
| **llama.cpp 2.14.0** | Stable GGUF inference | ⭐⭐⭐⭐ | High | Medium |
| **llama.cpp 2.5.1** | Legacy models | ⭐⭐⭐ | Very High | Low |
 
### MLX Engine
- **Pros:** Fastest on Apple Silicon, native Metal support, efficient memory usage
- **Cons:** Only works with MLX-format models, requires Apple Silicon
- **Best for:** Gemma 4, Qwen 3.6, modern models with MLX variants

### llama.cpp Engine
- **Pros:** Universal GGUF support, stable, works with all quantizations
- **Cons:** Slightly slower than MLX on Apple Silicon
- **Best for:** Qwen 3.5, older models, maximum compatibility

## Quick Start

### Option 1: Use LM Studio Server (Recommended)

LM Studio provides a unified API that handles engine selection automatically:

1. **Start LM Studio Server:**
```bash
# In LM Studio UI: Developer → Start Server
# Or via CLI if installed:
lms server start
```

2. **Configure Hermes:**
```yaml
providers:
  lm-studio:
    provider: openai-compatible
    base_url: http://localhost:1234/v1
    api_key: lm-studio
```

3. **Load models in LM Studio** - it auto-selects the best engine

### Option 2: Direct Engine Configuration

For direct engine control, configure per-model:

```yaml
providers:
  qwen-mlx:
    provider: llama-cpp
    model_path: ~/.lmstudio/models/Qwen3.6-27B-MLX-4bit/
    engine: mlx
    n_gpu_layers: -1  # MLX uses all available GPU
    
  qwen-gguf:
    provider: llama-cpp
    model_path: ~/.lmstudio/models/Qwen3.5-9B-GGUF/Qwen3.5-9B-Q4_K_M.gguf
    engine: llama-cpp
    n_gpu_layers: 35
```

## Engine Selection Guide

### Use MLX When:
- Model has MLX variant (`.mlx` or MLX folder)
- You need maximum speed on Apple Silicon
- Memory is constrained (MLX is more efficient)
- Running Gemma 4, Qwen 3.6, or other MLX-optimized models

### Use llama.cpp When:
- Model is GGUF format only
- You need maximum compatibility
- Running older models
- Need specific quantization (Q4_K_M, Q5_K_M, etc.)

### Use Specific llama.cpp Versions:
- **2.16.0:** Latest features, Gemma 4 SWA support
- **2.14.0:** Stable, well-tested
- **2.5.1:** Legacy model compatibility

## Configuration Examples

### High-Performance Setup (MLX + llama.cpp)

```yaml
providers:
  # Fast MLX for daily use
  qwen-mlx-fast:
    provider: llama-cpp
    model_path: ~/.lmstudio/models/Qwen3.6-27B-MLX-4bit/
    n_gpu_layers: -1
    n_ctx: 32768
    
  # Compatible llama.cpp for everything else
  qwen-gguf:
    provider: llama-cpp
    model_path: ~/.lmstudio/models/Qwen3.5-9B-GGUF/Qwen3.5-9B-Q4_K_M.gguf
    n_gpu_layers: 35
    n_ctx: 8192
    
  # Gemma 4 with latest engine
  gemma4-mlx:
    provider: llama-cpp
    model_path: ~/.lmstudio/models/gemma-4-26B-A4B-it-MLX-4bit/
    n_gpu_layers: -1
```

### Engine Switching Script

Create `~/.hermes/scripts/switch_engine.py`:

```python
#!/usr/bin/env python3
"""Switch between inference engines for current model."""
import sys
from hermes_tools import terminal

ENGINE_PATHS = {
    "mlx": "/Users/jonathanjenkins/.lmstudio/extensions/backends/mlx-llm-mac-arm64-apple-metal-advsimd-1.6.0/libllm_engine.dylib",
    "llama-2.16": "/Users/jonathanjenkins/.lmstudio/extensions/backends/llama.cpp-mac-arm64-apple-metal-advsimd-2.16.0/libllm_engine.dylib",
    "llama-2.14": "/Users/jonathanjenkins/.lmstudio/extensions/backends/llama.cpp-mac-arm64-apple-metal-advsimd-2.14.0/libllm_engine.dylib",
}

def switch_engine(engine_name):
    engine_path = ENGINE_PATHS.get(engine_name)
    if not engine_path:
        print(f"Unknown engine: {engine_name}")
        print(f"Available: {list(ENGINE_PATHS.keys())}")
        sys.exit(1)
    
    # Set environment variable for llama-cpp
    terminal(command=f"export LLM_ENGINE_PATH={engine_path}")
    print(f"Switched to {engine_name}")
    print(f"Engine path: {engine_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python switch_engine.py <engine_name>")
        print(f"Available: {list(ENGINE_PATHS.keys())}")
        sys.exit(1)
    
    switch_engine(sys.argv[1])
```

## Performance Tuning

### MLX Optimization

```yaml
providers:
  mlx-optimized:
    provider: llama-cpp
    model_path: ~/.lmstudio/models/model-mlx/
    n_gpu_layers: -1  # Use all GPU layers
    n_ctx: 32768      # Large context
    # MLX-specific (via env vars)
    env:
      MLX_METAL_MEMORY_GUARD: "1"
      MLX_FORCE_SINGLE_PRECISION: "0"
```

### llama.cpp Optimization

```yaml
providers:
  llama-cpp-fast:
    provider: llama-cpp
    model_path: ~/.lmstudio/models/model.gguf
    n_gpu_layers: 35  # Adjust based on VRAM
    n_ctx: 8192
    n_threads: 8      # Match CPU cores
    n_batch: 512      # Batch size
    flash_attn: true  # Enable flash attention
```

## Troubleshooting

### Engine Won't Load

**Symptoms:** Model fails to load, crashes, or falls back to CPU

**Solutions:**
1. Check engine path exists:
```bash
ls -la ~/.lmstudio/extensions/backends/
```

2. Verify model format matches engine:
```bash
# MLX models
file ~/.lmstudio/models/*/mlx_model_config.json

# GGUF models
file ~/.lmstudio/models/*/*.gguf
```

3. Check GPU memory:
```bash
system_profiler SPDisplaysDataType | grep "Total Number of Cores"
```

### Slow Performance

**MLX too slow:**
- Ensure using latest MLX version (1.6.0)
- Check `n_gpu_layers: -1` (use all GPU)
- Verify model is MLX format, not GGUF

**llama.cpp too slow:**
- Increase `n_gpu_layers` (up to VRAM limit)
- Enable `flash_attn: true`
- Use newer engine version (2.16.0)

### Memory Issues

**Reduce memory usage:**
```yaml
providers:
  low-memory:
    provider: llama-cpp
    model_path: ~/.lmstudio/models/model.gguf
    n_gpu_layers: 20  # Reduce GPU layers
    n_ctx: 4096       # Smaller context
    n_batch: 256      # Smaller batch
```

### Runtime Framework Issues

**`latest` symlink points to wrong version:**
This happens if setup script doesn't sort versions correctly.
```bash
# Check current target
readlink ~/.hermes/runtimes/llama.cpp/latest

# Fix manually (should point to newest)
rm ~/.hermes/runtimes/llama.cpp/latest
ln -s 2.16.0 ~/.hermes/runtimes/llama.cpp/latest
```

**Model configured with wrong runtime:**
GGUF models with `runtime: mlx/latest` will fail to load.
```bash
# Check model format
python ~/.hermes/scripts/runtime_manager.py compat <model_path>

# Fix config: use runtime: llama.cpp/latest for GGUF
```

**Engine binary verification fails:**
```bash
# Verify binary exists and is valid
file ~/.hermes/runtimes/llama.cpp/latest/libllm_engine.dylib
# Should report: Mach-O 64-bit dynamically linked shared library arm64

# If broken, reinstall
python ~/.hermes/scripts/runtime_manager.py install llama.cpp 2.16.0
```

## Benchmarks

Expected performance on M-series chips:

| Model | Engine | Size | Tokens/sec | Load Time |
|-------|--------|------|------------|-----------|
| Qwen 3.5 9B | MLX | 5GB | 45-55 | 2-3s |
| Qwen 3.5 9B | llama.cpp | 5GB | 35-45 | 3-4s |
| Qwen 3.6 27B | MLX | 15GB | 25-35 | 5-7s |
| Qwen 3.6 27B | llama.cpp | 15GB | 18-25 | 7-10s |
| Gemma 4 26B | MLX | 16GB | 28-38 | 6-8s |
| Gemma 4 26B | llama.cpp | 16GB | 20-28 | 8-12s |

## Integration with Hermes

To use engines in Hermes Agent:

1. **Load this skill** for engine management
2. **Configure providers** with engine paths
3. **Switch models** with `hermes model` command
4. **Monitor performance** with built-in metrics

Example workflow:
```bash
# Start with fast MLX for daily work
hermes config set model.provider qwen-mlx-fast

# Switch to compatible llama.cpp for complex tasks
hermes config set model.provider qwen-gguf

# Check which engine is active
hermes config show | grep provider
```

## Advanced: Custom Engine Builds

To use custom engine builds:

1. **Build engine:**
```bash
cd ~/dev/llama.cpp
make -j
```

2. **Configure in Hermes:**
```yaml
providers:
  custom-engine:
    provider: llama-cpp
    model_path: ~/.lmstudio/models/model.gguf
    engine_path: ~/dev/llama.cpp/build/libllama.dylib
```

## Notes

- Engine switching requires model reload
- MLX only works on Apple Silicon (M1/M2/M3)
- Some models only available in GGUF or MLX format
- LM Studio server auto-selects best engine (recommended for most users)
- Direct engine config gives more control but requires manual management
- **Runtime Framework:** Engines now managed in `~/.hermes/runtimes/` with versioned symlinks for easy switching without config changes

## Support Files

- `references/engine-discovery-2026-05-23.md` — Session-specific engine/model inventory
- `scripts/engine_switch.py` — Quick CLI engine switcher

## Quick Commands

```bash
# Switch engine
python ~/.hermes/skills/lm-studio-engines/scripts/engine_switch.py llama-2.16
python ~/.hermes/skills/lm-studio-engines/scripts/engine_switch.py mlx-1.6

# List available
python ~/.hermes/skills/lm-studio-engines/scripts/engine_switch.py
```
