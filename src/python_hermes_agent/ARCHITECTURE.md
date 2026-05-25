# Hermes Agent Architecture

## Directory Structure

```
~/GitHub/GITHUB/Hermes/                    # REPOSITORY
├── python_hermes_agent/                   # ⭐ HERMES AGENT (ALL CODE HERE)
│   ├── runtime_framework/                 # Multi-engine inference support
│   │   ├── runtimes/                     # Engine backends (llama.cpp, MLX)
│   │   │   ├── llama.cpp/
│   │   │   │   ├── 2.16.0/ → [LM Studio]
│   │   │   │   ├── 2.14.0/ → [LM Studio]
│   │   │   │   └── latest → 2.16.0
│   │   │   └── mlx/
│   │   │       ├── 1.6.0/ → [LM Studio]
│   │   │       └── latest → 1.6.0
│   │   ├── scripts/
│   │   │   ├── runtime_manager.py        # CLI management
│   │   │   └── engine_switch.py          # Quick switching
│   │   └── README.md
│   ├── scripts/                           # Utility scripts
│   │   ├── runtime_manager.py
│   │   ├── engine_switch.py
│   │   ├── scan_local_models.py
│   │   └── switch_to_local.py
│   ├── skills/                            # Agent capabilities
│   │   └── lm-studio-engines/
│   │       └── SKILL.md
│   ├── benchmark/                         # Benchmarking tools
│   ├── workspace/                         # ⭐ INSTANCE DATA
│   │   ├── config.yaml                   # Agent configuration
│   │   ├── memories/                     # Conversation history
│   │   │   ├── MEMORY.md
│   │   │   └── USER.md
│   │   ├── logs/                         # Runtime logs
│   │   │   ├── agent.log
│   │   │   └── errors.log
│   │   ├── benchmarks/                   # Test results
│   │   ├── auth.json                     # API credentials
│   │   ├── context_length_cache.yaml     # Runtime cache
│   │   ├── bin/                          # Binary tools
│   │   ├── lsp/                          # Language server
│   │   ├── cron/                         # Scheduled jobs
│   │   ├── images/                       # Generated images
│   │   ├── pastes/                       # Shared content
│   │   └── README.md                     # Workspace documentation
│   ├── upstream/                          # Core Hermes Agent code
│   ├── README.md
│   ├── hermes.sh
│   ├── run_prompt.py
│   └── setup.sh
├── python_pydantic_ai/                    # OTHER AGENT (separate)
│   └── [pydantic ai code]
└── docs/                                  # Shared documentation
    ├── ARCHITECTURE.md
    ├── LLAMA_CPP_PICKER_FIX.md
    ├── LOCAL_MODELS_SETUP.md
    └── SOUL.md
```

## Key Design Principles

### 1. Self-Contained Agent
**All Hermes Agent code lives in `python_hermes_agent/`**
- Copy the folder → get everything
- No external dependencies
- No `~/.hermes/` dependency

### 2. Workspace Pattern
**Instance data in `workspace/` subdirectory**
- Config, memories, logs, benchmarks all in one place
- Easy to backup: just copy `workspace/`
- Easy to reset: delete `workspace/` and recreate
- Multiple instances: each has its own workspace

### 3. Clear Separation
**Code vs Data:**
- `python_hermes_agent/` (excluding workspace/) = CODE
  - Versioned in git
  - Shared across instances
  - Updated via git pull
  
- `python_hermes_agent/workspace/` = DATA
  - NOT versioned (in .gitignore)
  - Instance-specific
  - Backed up separately

### 4. Multiple Agents
**Coexist cleanly in same repo:**
```
python_hermes_agent/      ← Hermes Agent
python_pydantic_ai/       ← Pydantic AI Agent
```
Each has its own:
- Code implementation
- Workspace (config, memories, logs)
- Runtime framework (can share or separate)

## Duplicating Hermes Agent

### Method 1: Copy Directory

```bash
cd ~/GitHub/GITHUB/Hermes

# Copy entire agent
cp -r python_hermes_agent python_hermes_agent_v2

# New instance has everything:
ls python_hermes_agent_v2/
# runtime_framework/ scripts/ skills/ workspace/ ...
```

### Method 2: Git Clone

```bash
# Clone entire repo
git clone ~/GitHub/GITHUB/Hermes hermes-agent-new

cd hermes-agent-new/python_hermes_agent

# Workspace comes with it (or reset it)
rm -rf workspace/memories
rm -rf workspace/logs
mkdir workspace/memories workspace/logs
```

### Method 3: Fresh Instance

```bash
cd ~/GitHub/GITHUB/Hermes

# Copy just the code (not workspace)
rsync -av python_hermes_agent/ python_hermes_agent_new/ \
  --exclude workspace/

# Create fresh workspace
cd python_hermes_agent_new
mkdir workspace
cp ../python_hermes_agent/workspace/config.yaml workspace/
# Edit config for new instance
```

## Workspace Management

### Reset Workspace (Keep Config)

```bash
cd python_hermes_agent

# Reset memories and logs
rm -rf workspace/memories/*
rm -rf workspace/logs/*
rm workspace/benchmarks/*.json

# Keep config.yaml and auth.json
```

### Backup Workspace

```bash
# Backup instance data
tar -czf workspace-backup.tar.gz python_hermes_agent/workspace/

# Or just memories
tar -czf memories-backup.tar.gz python_hermes_agent/workspace/memories/
```

### Restore Workspace

```bash
# Restore from backup
tar -xzf workspace-backup.tar.gz -C python_hermes_agent/
```

### Multiple Workspaces

```bash
# Create dev workspace
cp -r workspace workspace.dev

# Edit workspace.dev/config.yaml for dev settings

# Switch workspaces
mv workspace workspace.prod
mv workspace.dev workspace
```

## Configuration

### Config Location
```
python_hermes_agent/workspace/config.yaml
```

### Runtime Paths (Relative)
```yaml
providers:
  qwen3.5-9b:
    provider: llama-cpp
    model_path: ~/.lmstudio/models/Qwen3.5-9B-GGUF/Qwen3.5-9B-Q4_K_M.gguf
    runtime: ../runtime_framework/runtimes/llama.cpp/latest
    # ↑ Relative to workspace/
```

### Model Paths (Absolute or ~)
```yaml
providers:
  qwen3.5-9b:
    model_path: ~/.lmstudio/models/Qwen3.5-9B-GGUF/Qwen3.5-9B-Q4_K_M.gguf
    # ↑ Use absolute path or ~ for external models
```

## Runtime Framework

### Location
```
python_hermes_agent/runtime_framework/
```

### Usage
```bash
cd python_hermes_agent

# List engines
python runtime_framework/scripts/runtime_manager.py list

# Switch engine
python runtime_framework/scripts/runtime_manager.py use llama.cpp 2.14.0

# Check compatibility
python runtime_framework/scripts/runtime_manager.py compat <model.gguf>
```

### Update Engines
```bash
cd python_hermes_agent/runtime_framework

# Install from LM Studio
python scripts/runtime_manager.py install llama.cpp 2.17.0

# Switch to new version
python scripts/runtime_manager.py use llama.cpp 2.17.0
```

## Skills

### Location
```
python_hermes_agent/skills/
```

### Usage
Skills are loaded automatically by Hermes Agent. To use:

```python
# In agent code
from hermes import HermesAgent

agent = HermesAgent()
agent.load_skill('lm-studio-engines')
```

### Create New Skill
```bash
cd python_hermes_agent/skills
mkdir my-new-skill
# Create SKILL.md following format
```

## Benchmarking

### Location
```
python_hermes_agent/benchmark/
```

### Run Benchmarks
```bash
cd python_hermes_agent

# Run benchmark suite
python benchmark/run.py

# Results saved to workspace/benchmarks/
```

### Compare Results
```bash
cd python_hermes_agent/workspace/benchmarks
cat *.json | jq '.pass_rate'
```

## Troubleshooting

### "Workspace not found"

**Problem:** Config or code expects workspace/ but it's missing

**Solution:**
```bash
cd python_hermes_agent
mkdir workspace
# Copy config from backup or create new
```

### "Runtime not found"

**Problem:** Runtime paths in config are wrong

**Solution:** Check paths are relative to workspace/:
```yaml
runtime: ../runtime_framework/runtimes/llama.cpp/latest
```

### "Skills not loading"

**Problem:** Skills path wrong

**Solution:** Skills should be in:
```
python_hermes_agent/skills/
```

### Multiple Agents Conflict

**Problem:** Two agents trying to use same workspace

**Solution:** Each agent should have its own workspace/:
```
python_hermes_agent/workspace/
python_hermes_agent_v2/workspace/
```

## Backup Strategy

### Full Agent Backup
```bash
cd ~/GitHub/GITHUB/Hermes
tar -czf hermes-agent-full.tar.gz python_hermes_agent/
```

### Code Only (No Workspace)
```bash
cd ~/GitHub/GITHUB/Hermes
tar -czf hermes-agent-code.tar.gz python_hermes_agent/ \
  --exclude workspace/
```

### Workspace Only
```bash
cd ~/GitHub/GITHUB/Hermes
tar -czf hermes-workspace.tar.gz python_hermes_agent/workspace/
```

### Git Backup
```bash
cd ~/GitHub/GITHUB/Hermes
git add .
git commit -m "Hermes Agent backup"
git push
```

## Migration from ~/.hermes/

If you have an old setup using `~/.hermes/`:

### Old Structure
```
~/.hermes/
├── config.yaml
├── memories/
├── logs/
└── ...
```

### New Structure
```
python_hermes_agent/workspace/
├── config.yaml
├── memories/
├── logs/
└── ...
```

### Migration Steps
1. Copy `~/.hermes/*` → `python_hermes_agent/workspace/`
2. Update config paths to use relative paths
3. Test agent works
4. Remove or archive `~/.hermes/`

## Summary

| Component | Location | Versioned? | Instance-Specific? |
|-----------|----------|------------|-------------------|
| Agent Code | `python_hermes_agent/` | ✅ Yes | ❌ No |
| Runtime Framework | `python_hermes_agent/runtime_framework/` | ✅ Yes | ❌ No |
| Scripts | `python_hermes_agent/scripts/` | ✅ Yes | ❌ No |
| Skills | `python_hermes_agent/skills/` | ✅ Yes | ❌ No |
| Workspace | `python_hermes_agent/workspace/` | ❌ No | ✅ Yes |
| Config | `workspace/config.yaml` | ❌ No | ✅ Yes |
| Memories | `workspace/memories/` | ❌ No | ✅ Yes |
| Logs | `workspace/logs/` | ❌ No | ✅ Yes |

**Rule:** Everything in `python_hermes_agent/` except `workspace/` is code.
