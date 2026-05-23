#!/usr/bin/env python3
"""
Switch Hermes to use a local llama-cpp model.
Usage: python3 switch_to_local.py [model_name]
       model_name: gemma4-26b, qwen3-coder-30b, qwen3.5-9b, etc.
"""

import sys
from pathlib import Path

CONFIG_PATH = Path.home() / ".hermes" / "config.yaml"

# Read config
with open(CONFIG_PATH, 'r') as f:
    lines = f.readlines()

# Find and update provider line
provider_map = {
    'gemma4-26b': ('llama-cpp', 'gemma4-26b'),
    'qwen3-coder-30b': ('llama-cpp', 'gemma4-26b'),  # Use gemma path for now
    'qwen3.5-9b': ('llama-cpp', 'qwen3.5-9b'),
    'gemma4-31b': ('llama-cpp', 'gemma4-31b'),
    'gemma4-e4b': ('llama-cpp', 'gemma4-e4b'),
    'gemma3-12b': ('llama-cpp', 'gemma3-12b'),
    'llama3.2-3b': ('llama-cpp', 'llama3.2-3b'),
}

if len(sys.argv) < 2:
    print("Available local models:")
    for name in provider_map.keys():
        print(f"  - {name}")
    print("\nUsage: python3 switch_to_local.py <model_name>")
    print("Example: python3 switch_to_local.py gemma4-26b")
    sys.exit(0)

model_name = sys.argv[1]
if model_name not in provider_map:
    print(f"Unknown model: {model_name}")
    print("Available:", list(provider_map.keys()))
    sys.exit(1)

provider, default = provider_map[model_name]

# Update config
new_lines = []
in_model_section = False
for line in lines:
    if line.startswith('model:'):
        in_model_section = True
        new_lines.append(line)
    elif in_model_section and line.startswith('  provider:'):
        new_lines.append(f'  provider: {provider}\n')
        in_model_section = False
    elif line.startswith('  default:') and provider == 'llama-cpp':
        # For llama-cpp, the default is the provider name (model is in provider config)
        new_lines.append(f'  default: {default}\n')
    else:
        new_lines.append(line)

# Write back
with open(CONFIG_PATH, 'w') as f:
    f.writelines(new_lines)

print(f"✓ Switched to {model_name} ({provider})")
print(f"\nRun 'hermes' to start chatting with the local model!")
print("Or test with: hermes chat -q 'Hello!'")
