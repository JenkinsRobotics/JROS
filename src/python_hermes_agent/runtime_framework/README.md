# Hermes Runtime Framework

Multi-engine inference support for Hermes Agent - manage llama.cpp, MLX, and other inference engines.

## Quick Start

```bash
# List available engines
python runtime_framework/scripts/runtime_manager.py list

# Switch engine version
python runtime_framework/scripts/runtime_manager.py use llama.cpp 2.14.0

# Check model compatibility
python runtime_framework/scripts/runtime_manager.py compat <model_path>
```

## Directory Structure

```
runtime_framework/
├── runtimes/              # Engine backends (symlinks to LM Studio)
│   ├── llama.cpp/
│   │   ├── 2.16.0/ → [LM Studio backend]
│   │   ├── 2.14.0/ → [LM Studio backend]
│   │   └── latest → 2.16.0
│   └── mlx/
│       ├── 1.6.0/ → [LM Studio backend]
│       └── latest → 1.6.0
├── scripts/
│   ├── runtime_manager.py   # CLI management tool
│   └── engine_switch.py     # Quick switching
├── docs/
│   └── RUNTIME_FRAMEWORK.md # Full documentation
└── README.md               # This file
```

## What This Is

The Runtime Framework provides **multi-engine inference** for Hermes Agent:

- **Organized engine management** - All inference engines in one place
- **Version control** - Keep multiple versions side-by-side
- **Easy switching** - Change engines without config changes
- **Format-aware** - Auto-select compatible engine for model type

## Engine Types

| Engine | Best For | Speed | Compatibility |
|--------|----------|-------|---------------|
| **llama.cpp** | GGUF models, maximum compatibility | ⭐⭐⭐⭐ | Very High |
| **MLX** | Apple Silicon, MLX models | ⭐⭐⭐⭐⭐ | Medium |
| **vLLM** | Production serving (future) | ⭐⭐⭐⭐⭐ | High |

## Setup

### 1. Link LM Studio Engines

```bash
cd ~/GitHub/GITHUB/Hermes/runtime_framework

# Run setup (or manually link)
python scripts/runtime_manager.py install llama.cpp 2.16.0
python scripts/runtime_manager.py install mlx 1.6.0
```

### 2. Configure Hermes

In your `~/.hermes/config.yaml` or agent config:

```yaml
providers:
  qwen3.5-9b:
    provider: llama-cpp
    model_path: ~/.lmstudio/models/Qwen3.5-9B-GGUF/Qwen3.5-9B-Q4_K_M.gguf
    runtime: ~/GitHub/GITHUB/Hermes/runtime_framework/runtimes/llama.cpp/latest
    n_gpu_layers: 35
```

### 3. Use

```bash
# Switch to stable version for production
python scripts/runtime_manager.py use llama.cpp 2.14.0

# Switch to fastest for development
python scripts/runtime_manager.py use mlx 1.6.0
```

## Commands

```bash
# List all available runtimes
python scripts/runtime_manager.py list

# Show status summary
python scripts/runtime_manager.py status

# Switch to specific version
python scripts/runtime_manager.py use llama.cpp 2.14.0

# Install from LM Studio
python scripts/runtime_manager.py install mlx 1.6.0

# Update to latest
python scripts/runtime_manager.py update llama.cpp

# Check model compatibility
python scripts/runtime_manager.py compat <model_path>

# Show help
python scripts/runtime_manager.py help
```

## Integration with Hermes Agent

The runtime framework is **separate from the agent code** - it's a supporting framework that agents use.

### For Agent Instances

When you create a new agent instance:

1. **Clone the repo:**
```bash
git clone ~/GitHub/GITHUB/Hermes new-agent-instance
```

2. **Runtime framework is included** in `runtime_framework/`

3. **Create instance config:**
```bash
# Instance-specific config
cp runtime_framework/config.example.yaml ~/.hermes/config.yaml
```

4. **Link runtimes** (or use repo's runtimes directly)

### For New Agent Types

When you duplicate to create a new agent (e.g., `python_hermes_agent` → `python_hermes_agent_v2`):

1. **Runtime framework stays shared** - all agents use the same `runtime_framework/`
2. **Each agent has its own config** in `~/.hermes/` or agent-specific config
3. **Agents can use different engines** by setting different `runtime:` paths

## Why This Structure?

### ✅ Good (In Repo)
- `runtime_framework/` - Part of source, versioned, copied with agent
- `skills/` - Procedural knowledge, part of agent capabilities
- `scripts/` - Tools that come with the agent

### ✅ Good (In ~/.hermes/)
- `config.yaml` - User-specific settings
- `memories/` - Session state, conversation history
- `logs/` - Instance-specific logs
- `benchmarks/` - Test results from YOUR runs

### ❌ Bad (Was in ~/.hermes/)
- Runtime code - Would be lost when duplicating agent
- Skills - Agent capabilities should be in repo
- Management scripts - Tools should be versioned

## Updating Engines

### From LM Studio

When LM Studio updates:

```bash
# Install new version into runtime framework
python scripts/runtime_manager.py install llama.cpp 2.17.0

# Switch to use it
python scripts/runtime_manager.py use llama.cpp 2.17.0
```

### Manual Download

```bash
cd runtime_framework/runtimes/llama.cpp/
curl -LO https://github.com/ggerganov/llama.cpp/releases/download/...
unzip && mv extracted 2.17.0
ln -sf 2.17.0 latest
```

## Benchmarking

Test different engines on your workloads:

```bash
# Test with 2.16.0
python scripts/runtime_manager.py use llama.cpp 2.16.0
python benchmark/run.py

# Test with 2.14.0
python scripts/runtime_manager.py use llama.cpp 2.14.0
python benchmark/run.py

# Compare results
cat benchmark/results/*.json | jq '.pass_rate'
```

## Troubleshooting

### Engine Won't Load

```bash
# Check engine exists
ls -la runtime_framework/runtimes/llama.cpp/latest/

# Verify binary
file runtime_framework/runtimes/llama.cpp/latest/libllm_engine.dylib

# Switch to older version
python scripts/runtime_manager.py use llama.cpp 2.14.0
```

### Slow Performance

```bash
# Try MLX for Apple Silicon
python scripts/runtime_manager.py use mlx 1.6.0

# Try latest llama.cpp
python scripts/runtime_manager.py use llama.cpp 2.16.0
```

## Documentation

- **Full Guide:** `docs/RUNTIME_FRAMEWORK.md`
- **Skill:** `../skills/lm-studio-engines/SKILL.md`
- **LM Studio Skill:** Load with `skill_view(name='lm-studio-engines')`

## License

MIT - Part of Hermes Agent framework
