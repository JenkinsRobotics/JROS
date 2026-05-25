# LM Studio Engine Discovery — May 23, 2026

## Engines Found

**MLX Engines (5 versions):**
- v1.6.0 — `/Users/jonathanjenkins/.lmstudio/extensions/backends/mlx-llm-mac-arm64-apple-metal-advsimd-1.6.0/libllm_engine.dylib`
- v1.5.0 — `/Users/jonathanjenkins/.lmstudio/extensions/backends/mlx-llm-mac-arm64-apple-metal-advsimd-1.5.0/libllm_engine.dylib`
- v1.3.0 — `/Users/jonathanjenkins/.lmstudio/extensions/backends/mlx-llm-mac-arm64-apple-metal-advsimd-1.3.0/libllm_engine.dylib`
- v0.44.1 — `/Users/jonathanjenkins/.lmstudio/extensions/backends/mlx-llm-mac-arm64-apple-metal-advsimd-0.44.1/libllm_engine.dylib`
- v0.22.1 — `/Users/jonathanjenkins/.lmstudio/extensions/backends/mlx-llm-mac-arm64-apple-metal-advsimd-0.22.1/libllm_engine.dylib`

**llama.cpp Engines (5 versions):**
- v2.16.0 — `/Users/jonathanjenkins/.lmstudio/extensions/backends/llama.cpp-mac-arm64-apple-metal-advsimd-2.16.0/libllm_engine.dylib`
- v2.14.0 — `/Users/jonathanjenkins/.lmstudio/extensions/backends/llama.cpp-mac-arm64-apple-metal-advsimd-2.14.0/libllm_engine.dylib`
- v2.13.0 — `/Users/jonathanjenkins/.lmstudio/extensions/backends/llama.cpp-mac-arm64-apple-metal-advsimd-2.13.0/libllm_engine.dylib`
- v2.12.0 — `/Users/jonathanjenkins/.lmstudio/extensions/backends/llama.cpp-mac-arm64-apple-metal-advsimd-2.12.0/libllm_engine.dylib`
- v2.5.1 — `/Users/jonathanjenkins/.lmstudio/extensions/backends/llama.cpp-mac-arm64-apple-metal-advsimd-2.5.1/libllm_engine.dylib`

## Models Found (GGUF Only)

All models are in GGUF format — no MLX-native models discovered:

1. `Qwen3.6-27B-GGUF/Qwen3.6-27B-Q4_K_M.gguf` (15GB)
2. `Qwen3.5-9B-GGUF/Qwen3.5-9B-Q4_K_M.gguf` (5.2GB)
3. `gemma-4-31B-it-GGUF/mmproj-gemma-4-31B-it-BF16.gguf` (projector)
4. `gemma-4-E2B-it-GGUF/gemma-4-E2B-it-Q4_K_M.gguf` (3.2GB)
5. `gemma-3-12b-it-GGUF/gemma-3-12b-it-Q4_K_M.gguf` (6.8GB)
6. `gemma-4-E4B-it-GGUF/` (5.0GB)
7. `gemma-4-26B-A4B-it-GGUF/` (16GB)
8. `gemma-4-31B-it-GGUF/` (17GB)
9. `Qwen3.6-35B-A3B-GGUF/` (20GB)

## Key Findings

- **No MLX models present** — All models are GGUF format, so they'll use llama.cpp engine
- **MLX would require downloading MLX-native variants** — Look for folders with `mlx_model_config.json`
- **Latest engines recommended** — MLX 1.6.0, llama.cpp 2.16.0 for best performance
- **Engine paths are in LM Studio extensions** — `~/.lmstudio/extensions/backends/*/libllm_engine.dylib`

## Engine Selection for This Setup

Since all models are GGUF:
- Use **llama.cpp 2.16.0** for all current models
- MLX engines only become relevant if downloading MLX-native model variants
- Gemma 4 models in GGUF format still use llama.cpp (not MLX)

## Commands Used

```bash
# Find engines
find ~/.lmstudio -name "*.dylib" -o -name "*.so" | grep -i engine

# Check model formats
find ~/.lmstudio/models -name "*.gguf"
find ~/.lmstudio/models -name "mlx_model_config.json"
```
