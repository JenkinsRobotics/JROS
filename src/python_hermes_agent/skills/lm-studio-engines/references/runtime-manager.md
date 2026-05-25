# Hermes Runtime Manager CLI

**Location:** `~/.hermes/scripts/runtime_manager.py`

**Purpose:** Command-line interface for managing inference engine runtimes (llama.cpp, MLX, vLLM)

## Commands

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
python ~/.hermes/scripts/runtime_manager.py use <engine> <version>

# Examples:
python ~/.hermes/scripts/runtime_manager.py use llama.cpp 2.14.0
python ~/.hermes/scripts/runtime_manager.py use mlx 1.6.0
```

**What it does:**
1. Validates engine type and version exist
2. Updates `~/.hermes/runtimes/<engine>/latest` symlink
3. Verifies engine binary is present
4. Reports success/failure

### Check Model Compatibility
```bash
python ~/.hermes/scripts/runtime_manager.py compat <model_path>

# Example:
python ~/.hermes/scripts/runtime_manager.py compat \
  ~/.lmstudio/models/Qwen3.5-9B-GGUF/Qwen3.5-9B-Q4_K_M.gguf
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

**Output:** Summary of all runtimes with descriptions and active versions

### Install New Runtime
```bash
python ~/.hermes/scripts/runtime_manager.py install <engine> [version]

# Example (from LM Studio backends):
python ~/.hermes/scripts/runtime_manager.py install llama.cpp 2.16.0
```

### Update to Latest
```bash
python ~/.hermes/scripts/runtime_manager.py update <engine>

# Example:
python ~/.hermes/scripts/runtime_manager.py update llama.cpp
```

## Implementation Details

**Path Resolution:**
- Hermes runtimes: `~/.hermes/runtimes/`
- LM Studio backends: `~/.lmstudio/extensions/backends/`
- Symlinks: `<runtime>/<version>/` → `<LM Studio backend>/`

**Engine Detection:**
- llama.cpp: Folders matching `llama.cpp-mac-arm64-apple-metal-advsimd-*`
- MLX: Folders matching `mlx-llm-mac-arm64-apple-metal-advsimd-*`
- Version extracted from folder name (first token starting with digit and containing `.`)

**Symlink Strategy:**
- Each version gets its own symlinked folder
- `latest` symlink points to active version
- Switching = updating `latest` symlink (instant, no config changes)

## Integration with Hermes Config

Providers in `~/.hermes/config.yaml` reference runtimes:

```yaml
providers:
  qwen3.5-9b:
    provider: llama-cpp
    model_path: ~/.lmstudio/models/Qwen3.5-9B-GGUF/Qwen3.5-9B-Q4_K_M.gguf
    runtime: llama.cpp/latest    # ← Resolved at load time
    n_gpu_layers: 35
    n_ctx: 8192
```

**Resolution Flow:**
1. Hermes reads `runtime: llama.cpp/latest`
2. Resolves symlink: `latest` → `2.16.0`
3. Loads engine from: `~/.hermes/runtimes/llama.cpp/2.16.0/libllm_engine.dylib`
4. Uses engine to initialize model

## Common Workflows

### Benchmark Different Engines
```bash
# Test with 2.16.0
python ~/.hermes/scripts/runtime_manager.py use llama.cpp 2.16.0
python ~/.hermes/benchmarks/quick_bench.py

# Test with 2.14.0
python ~/.hermes/scripts/runtime_manager.py use llama.cpp 2.14.0
python ~/.hermes/benchmarks/quick_bench.py

# Compare results in ~/.hermes/benchmarks/
```

### Rollback After Bad Update
```bash
# New version causing issues
python ~/.hermes/scripts/runtime_manager.py use llama.cpp 2.14.0

# Verify model loads
hermes chat -q "test"

# If working, keep; if not, try another version
```

### Prepare for MLX Models
```bash
# Verify MLX engine is available
python ~/.hermes/scripts/runtime_manager.py list

# Ensure MLX 1.6.0 is active (fastest)
python ~/.hermes/scripts/runtime_manager.py use mlx 1.6.0

# Download MLX-format models via LM Studio
# Add to config with runtime: mlx/latest
```

## Troubleshooting

### "Version not found"
**Cause:** Engine not in LM Studio backends yet

**Fix:**
1. Update LM Studio to download latest backends
2. Or manually download from GitHub releases
3. Re-run: `python ~/.hermes/scripts/runtime_manager.py install <engine> <version>`

### "Engine binary verification failed"
**Cause:** Corrupted download or incomplete symlink

**Fix:**
```bash
# Remove bad symlink
rm ~/.hermes/runtimes/llama.cpp/<version>

# Re-create
python ~/.hermes/scripts/runtime_manager.py install llama.cpp <version>
```

### Model loads but slow
**Cause:** Using older/slower engine version

**Fix:**
```bash
# Switch to latest
python ~/.hermes/scripts/runtime_manager.py update llama.cpp

# Or try MLX if model has MLX variant
python ~/.hermes/scripts/runtime_manager.py use mlx 1.6.0
```

## Related Files

- **Skill:** `~/.hermes/skills/lm-studio-engines/SKILL.md`
- **Framework Doc:** `~/.hermes/RUNTIME_FRAMEWORK.md`
- **Config:** `~/.hermes/config.yaml` (providers with `runtime:` field)
- **Runtimes:** `~/.hermes/runtimes/` (engine symlinks)
