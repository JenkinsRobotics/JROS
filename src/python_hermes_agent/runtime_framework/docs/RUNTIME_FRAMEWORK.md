# Hermes Runtime Engine Framework

## Overview

Hermes now supports **multi-engine inference** with organized runtime management, similar to LM Studio's architecture. All inference engines live in `~/.hermes/runtimes/` with versioned folders and symlinks for easy switching.

## Directory Structure

```
~/.hermes/
├── runtimes/                    # Engine runtimes (organized by type)
│   ├── llama.cpp/              # llama.cpp backends
│   │   ├── 2.16.0/ → [LM Studio backend]
│   │   ├── 2.14.0/ → [LM Studio backend]
│   │   ├── 2.13.0/ → [LM Studio backend]
│   │   ├── 2.12.0/ → [LM Studio backend]
│   │   ├── 2.5.1/ → [LM Studio backend]
│   │   └── latest → 2.16.0     # Active version (symlink)
│   ├── mlx/                    # MLX backends (Apple Silicon)
│   │   ├── 1.6.0/ → [LM Studio backend]
│   │   ├── 1.5.0/ → [LM Studio backend]
│   │   ├── 1.3.0/ → [LM Studio backend]
│   │   ├── 0.44.1/ → [LM Studio backend]
│   │   ├── 0.22.1/ → [LM Studio backend]
│   │   └── latest → 1.6.0      # Active version (symlink)
│   └── vllm/                   # Future: vLLM support
│       └── (pending)
├── config.yaml                 # Provider configs with runtime field
└── scripts/
    ├── runtime_manager.py      # CLI for runtime management
    └── engine_switch.py        # Quick engine switching
```

## Key Features

### 1. **Versioned Runtimes**
Each engine version lives in its own folder - no conflicts, easy rollback.

### 2. **Symlink-Based Switching**
The `latest` symlink points to the active version. Change the symlink to switch engines instantly.

### 3. **Auto-Discovery**
Hermes scans `~/.hermes/runtimes/` to find available engines.

### 4. **Format-Aware Selection**
- GGUF models → llama.cpp engine
- MLX models → MLX engine
- Auto-selects compatible engine based on model format

### 5. **Hot Swappable**
Update engines without breaking existing configs - just update the symlink.

## Usage

### List Available Runtimes

```bash
python ~/.hermes/scripts/runtime_manager.py list
```

**Output:**
```
📦 llama.cpp
   Active: 2.16.0
   Available versions:
     - 2.16.0 ← active
     - 2.14.0 
     - 2.13.0 
     - 2.12.0 
     - 2.5.1 

📦 mlx
   Active: 1.6.0
   Available versions:
     - 1.6.0 ← active
     - 1.5.0 
     - 1.3.0 
     - 0.44.1 
     - 0.22.1 
```

### Switch Engine Version

```bash
# Switch to older llama.cpp for stability
python ~/.hermes/scripts/runtime_manager.py use llama.cpp 2.14.0

# Switch to latest MLX for speed
python ~/.hermes/scripts/runtime_manager.py use mlx 1.6.0
```

### Check Model Compatibility

```bash
python ~/.hermes/scripts/runtime_manager.py compat ~/.lmstudio/models/Qwen3.5-9B-GGUF/Qwen3.5-9B-Q4_K_M.gguf
```

**Output:**
```
✅ llama.cpp: Compatible (all versions)
❌ MLX: Not compatible (GGUF format)
✅ vLLM: Compatible (with GGUF support)

   Format: Q4_K_M quantization
   Recommended: llama.cpp 2.14.0+
```

### Show Runtime Status

```bash
python ~/.hermes/scripts/runtime_manager.py status
```

## Configuration

### Provider Config with Runtime

In `~/.hermes/config.yaml`, each provider now has a `runtime` field:

```yaml
providers:
  qwen3.5-9b:
    provider: llama-cpp
    model_path: ~/.lmstudio/models/Qwen3.5-9B-GGUF/Qwen3.5-9B-Q4_K_M.gguf
    runtime: llama.cpp/latest    # ← Uses active llama.cpp version
    n_gpu_layers: 35
    n_ctx: 8192
    
  gemma4-mlx:
    provider: llama-cpp
    model_path: ~/.lmstudio/models/gemma-4-MLX/
    runtime: mlx/latest          # ← Uses active MLX version
    n_gpu_layers: -1
```

### Runtime Resolution

When Hermes loads a model:
1. Reads `runtime: llama.cpp/latest`
2. Resolves symlink: `~/.hermes/runtimes/llama.cpp/latest` → `2.16.0`
3. Loads engine from: `~/.hermes/runtimes/llama.cpp/2.16.0/libllm_engine.dylib`
4. Uses engine to load model

## Engine Compatibility Matrix

| Model Format | llama.cpp | MLX | vLLM |
|--------------|-----------|-----|------|
| GGUF (.gguf) | ✅ All versions | ❌ | ✅ |
| MLX (mlx_model_config.json) | ❌ | ✅ All versions | ❌ |
| SafeTensors | ❌ | ✅ | ✅ |
| GPTQ | ✅ 2.16+ | ❌ | ✅ |

## Engine Selection Guide

### Use llama.cpp When:
- Model is GGUF format (most common)
- Maximum compatibility needed
- Running Qwen 3.5, Llama 3, older models
- Need specific quantization (Q4_K_M, Q5_K_M, etc.)

**Recommended versions:**
- **2.16.0** (latest): Best performance, Gemma 4 support
- **2.14.0** (stable): Well-tested, reliable
- **2.5.1** (legacy): Old model compatibility

### Use MLX When:
- Model has MLX variant
- Maximum speed on Apple Silicon (M1/M2/M3)
- Memory efficiency important
- Running Gemma 4, Qwen 3.6 MLX variants

**Performance gain:** 20-30% faster than llama.cpp on Apple Silicon

## Updating Engines

### Option 1: From LM Studio

When LM Studio updates its backends:

```bash
# 1. Update LM Studio (downloads new engines)
# 2. Re-run setup to link new versions
python ~/.hermes/scripts/runtime_manager.py install llama.cpp 2.17.0

# 3. Switch to new version
python ~/.hermes/scripts/runtime_manager.py use llama.cpp 2.17.0
```

### Option 2: Manual Download

```bash
# Download from GitHub releases
cd ~/.hermes/runtimes/llama.cpp/
curl -LO https://github.com/ggerganov/llama.cpp/releases/download/bXXXX/llama.cpp-mac-arm64.zip
unzip llama.cpp-mac-arm64.zip
mv extracted_folder 2.17.0

# Update symlink
ln -sf 2.17.0 latest
```

## Troubleshooting

### Engine Won't Load

**Symptoms:** Model fails to load, crashes

**Solutions:**
1. Check engine exists:
```bash
ls -la ~/.hermes/runtimes/llama.cpp/latest/
```

2. Verify binary:
```bash
file ~/.hermes/runtimes/llama.cpp/latest/libllm_engine.dylib
```

3. Switch to older version:
```bash
python ~/.hermes/scripts/runtime_manager.py use llama.cpp 2.14.0
```

### Slow Performance

**Try different engine versions:**
```bash
# Test MLX for speed
python ~/.hermes/scripts/runtime_manager.py use mlx 1.6.0

# Test latest llama.cpp
python ~/.hermes/scripts/runtime_manager.py use llama.cpp 2.16.0

# Test stable version
python ~/.hermes/scripts/runtime_manager.py use llama.cpp 2.14.0
```

### Memory Issues

**Reduce GPU layers in config:**
```yaml
providers:
  low-memory:
    provider: llama-cpp
    model_path: ~/.lmstudio/models/model.gguf
    runtime: llama.cpp/latest
    n_gpu_layers: 20  # Reduce from 35
    n_ctx: 4096       # Smaller context
```

## Benchmarking Different Engines

```bash
# Test same model with different engines
python ~/.hermes/scripts/runtime_manager.py use llama.cpp 2.16.0
python ~/.hermes/benchmarks/quick_bench.py  # Run benchmark

python ~/.hermes/scripts/runtime_manager.py use llama.cpp 2.14.0
python ~/.hermes/benchmarks/quick_bench.py

python ~/.hermes/scripts/runtime_manager.py use mlx 1.6.0
python ~/.hermes/benchmarks/quick_bench.py

# Compare results in ~/.hermes/benchmarks/
```

## Files Created

| File | Purpose |
|------|---------|
| `~/.hermes/runtimes/` | Runtime engine directory |
| `~/.hermes/scripts/runtime_manager.py` | CLI management tool |
| `~/.hermes/scripts/engine_switch.py` | Quick switching script |
| `~/.hermes/RUNTIME_FRAMEWORK.md` | Architecture documentation |
| `~/.hermes/skills/lm-studio-engines/SKILL.md` | Usage guide skill |
| `~/.hermes/config.yaml` | Updated with runtime fields |

## Commands Reference

```bash
# List all runtimes
python ~/.hermes/scripts/runtime_manager.py list

# Show status summary
python ~/.hermes/scripts/runtime_manager.py status

# Switch to specific version
python ~/.hermes/scripts/runtime_manager.py use llama.cpp 2.14.0

# Install from LM Studio
python ~/.hermes/scripts/runtime_manager.py install mlx 1.6.0

# Update to latest
python ~/.hermes/scripts/runtime_manager.py update llama.cpp

# Check model compatibility
python ~/.hermes/scripts/runtime_manager.py compat <model_path>

# Show help
python ~/.hermes/scripts/runtime_manager.py help
```

## Migration from Old Setup

If you had hardcoded engine paths:

**Before:**
```yaml
providers:
  qwen3.5-9b:
    provider: llama-cpp
    model_path: ~/.lmstudio/models/Qwen3.5-9B.gguf
    # Engine path hardcoded or implicit
```

**After:**
```yaml
providers:
  qwen3.5-9b:
    provider: llama-cpp
    model_path: ~/.lmstudio/models/Qwen3.5-9B.gguf
    runtime: llama.cpp/latest  # ← Explicit runtime reference
```

Benefits:
- ✅ Easy engine switching without config changes
- ✅ Multiple versions side-by-side
- ✅ Clear which engine version is active
- ✅ Organized, maintainable structure

## Next Steps

1. **Test different engines** on your models to find optimal performance
2. **Download MLX variants** of models for 20-30% speed boost
3. **Benchmark** different engine versions on your workloads
4. **Add vLLM support** when ready for production serving

---

**Documentation:** See `~/.hermes/skills/lm-studio-engines/SKILL.md` for detailed usage guide
**Skill:** Load with `skill_view(name='lm-studio-engines')` for engine selection guidance
