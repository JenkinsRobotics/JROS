# Engine Compatibility Reference

## Quick Reference: Which Engine for Which Model?

| Model Format | File Extension / Marker | Compatible Engines | Recommended |
|--------------|------------------------|-------------------|-------------|
| **GGUF** | `.gguf` | llama.cpp (all), vLLM | llama.cpp 2.16.0 |
| **MLX** | `mlx_model_config.json` | MLX | MLX 1.6.0 |
| **SafeTensors** | `.safetensors` | MLX, vLLM | MLX 1.6.0 (Apple Silicon) |
| **GPTQ** | `gptq_config.json` or `.pt` | llama.cpp 2.16+, vLLM | vLLM (production) |

## Your Current Models (as of 2026-05-23)

All models are **GGUF format** → use `runtime: llama.cpp/latest`

| Model | Size | Quantization | Path |
|-------|------|--------------|------|
| Qwen 3.5 9B | 5.2GB | Q4_K_M | `~/.lmstudio/models/Qwen3.5-9B-GGUF/` |
| Qwen 3.6 27B | 15GB | Q4_K_M | `~/.lmstudio/models/Qwen3.6-27B-GGUF/` |
| Qwen 3.6 35B A3B | 20GB | Q4_K_M | `~/.lmstudio/models/Qwen3.6-35B-A3B-GGUF/` |
| Gemma 4 E2B | 3.2GB | Q4_K_M | `~/.lmstudio/models/gemma-4-E2B-it-GGUF/` |
| Gemma 4 E4B | 5.0GB | Q4_K_M | `~/.lmstudio/models/gemma-4-E4B-it-GGUF/` |
| Gemma 3 12B | 6.8GB | Q4_K_M | `~/.lmstudio/models/gemma-3-12b-it-GGUF/` |
| Gemma 4 26B A4B | 16GB | Q4_K_M | `~/.lmstudio/models/gemma-4-26B-A4B-it-GGUF/` |
| Gemma 4 31B | 17GB | Q4_K_M | `~/.lmstudio/models/gemma-4-31B-it-GGUF/` |
| Llama 3.2 3B | ~2GB | Q4_K_M | `~/.lmstudio/models/Llama-3.2-3B-Instruct-GGUF/` |

**Note:** No MLX-format models currently installed. All use GGUF → llama.cpp engine.

## Engine Version Recommendations

### llama.cpp Versions

| Version | Release | Best For | Notes |
|---------|---------|----------|-------|
| **2.16.0** | Latest | All GGUF models, Gemma 4 | Default `latest`, best performance |
| **2.14.0** | Stable | Production, well-tested | Good fallback if 2.16 has issues |
| **2.13.0** | Older | Compatibility testing | Minor improvements over 2.12 |
| **2.12.0** | Older | Legacy systems | Stable but slower |
| **2.5.1** | Legacy | Very old models | Only if newer versions fail |

### MLX Versions

| Version | Release | Best For | Notes |
|---------|---------|----------|-------|
| **1.6.0** | Latest | All MLX models | Default `latest`, fastest |
| **1.5.0** | Recent | Stability | Good alternative |
| **1.3.0** | Older | Compatibility | Minor version |
| **0.44.1** | Legacy | Old MLX models | Pre-1.0 API |
| **0.22.1** | Legacy | Very old models | Deprecated |

## Performance Expectations (M-Series Apple Silicon)

### llama.cpp on GGUF Models

| Model Size | Quantization | Tokens/sec (2.16.0) | VRAM Usage |
|------------|--------------|---------------------|------------|
| 3B (Llama 3.2) | Q4_K_M | 60-80 | ~2GB |
| 9B (Qwen 3.5) | Q4_K_M | 35-45 | ~5GB |
| 12B (Gemma 3) | Q4_K_M | 28-35 | ~7GB |
| 27B (Qwen 3.6) | Q4_K_M | 18-25 | ~15GB |
| 35B (Qwen 3.6 A3B) | Q4_K_M | 15-20 | ~20GB |

### MLX on MLX Models (Expected, Not Yet Tested)

| Model Size | Quantization | Tokens/sec (1.6.0) | VRAM Usage |
|------------|--------------|--------------------|------------|
| 9B | 4-bit | 45-55 | ~5GB |
| 27B | 4-bit | 25-35 | ~15GB |
| 35B | 4-bit | 20-28 | ~20GB |

**Speed gain:** MLX is ~20-30% faster than llama.cpp on Apple Silicon for equivalent models.

## How to Check Model Format

### Method 1: Runtime Manager
```bash
python ~/.hermes/scripts/runtime_manager.py compat <model_path>
```

### Method 2: Manual Check
```bash
# Check for GGUF
file ~/.lmstudio/models/*/*.gguf
# Output: data (or specific GGUF marker)

# Check for MLX
ls ~/.lmstudio/models/*/mlx_model_config.json
# If exists: MLX format
```

### Method 3: LM Studio UI
1. Open LM Studio
2. Go to "My Models"
3. Click model → shows format in details

## Config Template by Format

### GGUF Model Config
```yaml
providers:
  my-model:
    provider: llama-cpp
    model_path: ~/.lmstudio/models/model.gguf
    runtime: llama.cpp/latest    # ← Always for GGUF
    n_gpu_layers: 35
    n_ctx: 8192
```

### MLX Model Config
```yaml
providers:
  my-model-mlx:
    provider: llama-cpp
    model_path: ~/.lmstudio/models/model-mlx/
    runtime: mlx/latest          # ← Always for MLX
    n_gpu_layers: -1             # ← MLX uses all GPU
    n_ctx: 32768
```

## Common Mistakes

### ❌ Wrong: GGUF Model with MLX Runtime
```yaml
# This will FAIL
providers:
  qwen-gguf:
    model_path: ~/.lmstudio/models/Qwen3.5-9B.gguf
    runtime: mlx/latest    # ← Wrong! GGUF needs llama.cpp
```

### ✅ Correct: GGUF Model with llama.cpp Runtime
```yaml
providers:
  qwen-gguf:
    model_path: ~/.lmstudio/models/Qwen3.5-9B.gguf
    runtime: llama.cpp/latest    # ← Correct
```

### ❌ Wrong: Hardcoded Engine Path
```yaml
# Don't do this - breaks when you update engines
providers:
  my-model:
    model_path: ~/.lmstudio/models/model.gguf
    engine_path: ~/.lmstudio/extensions/backends/...  # ← Brittle
```

### ✅ Correct: Use Runtime Symlink
```yaml
# Do this - automatically uses latest
providers:
  my-model:
    model_path: ~/.lmstudio/models/model.gguf
    runtime: llama.cpp/latest    # ← Flexible, updateable
```

## Downloading MLX Variants

To get MLX versions of your models (for 20-30% speed boost):

1. **Via LM Studio UI:**
   - Search for model
   - Look for "MLX" or "Apple MLX" variant
   - Download (separate from GGUF)

2. **Via Hugging Face:**
   ```bash
   # Example for Qwen
   git lfs install
   git clone https://huggingface.co/Qwen/Qwen3.6-27B-MLX-4bit
   ```

3. **Verify Format:**
   ```bash
   ls <downloaded-folder>/mlx_model_config.json
   # Should exist for MLX format
   ```

4. **Add to Config:**
   ```yaml
   providers:
     qwen3.6-27b-mlx:
       provider: llama-cpp
       model_path: ~/.lmstudio/models/Qwen3.6-27B-MLX-4bit/
       runtime: mlx/latest
       n_gpu_layers: -1
   ```

## Related Files

- **Skill:** `~/.hermes/skills/lm-studio-engines/SKILL.md`
- **Runtime Manager:** `~/.hermes/scripts/runtime_manager.py`
- **Framework Doc:** `~/.hermes/RUNTIME_FRAMEWORK.md`
