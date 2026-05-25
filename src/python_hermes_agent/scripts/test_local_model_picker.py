#!/usr/bin/env python3
"""
Test if llama-cpp providers show up in the model picker.
Run this after the model_switch.py fix to verify local models are detected.
"""

import sys
sys.path.insert(0, '/Users/jonathanjenkins/GitHub/GITHUB/Hermes/python_hermes_agent/upstream')

import yaml
from pathlib import Path

# Load config
config_path = Path.home() / '.hermes' / 'config.yaml'
with open(config_path, 'r') as f:
    config = yaml.safe_load(f)

print("=" * 60)
print("Local Model Provider Detection Test")
print("=" * 60)

user_providers = config.get('providers', {})
print(f"\nFound {len(user_providers)} custom providers in config:\n")

llama_cpp_count = 0
for name, settings in user_providers.items():
    provider_type = settings.get('provider', 'unknown')
    model_path = settings.get('model_path', '')
    
    if provider_type == 'llama-cpp' and model_path:
        llama_cpp_count += 1
        print(f"  ✓ {name}")
        print(f"    Provider: {provider_type}")
        print(f"    Model: {model_path}")
        print(f"    GPU Layers: {settings.get('n_gpu_layers', 0)}")
        print(f"    Context: {settings.get('n_ctx', 0)}")
        print()

print(f"\nTotal llama-cpp providers: {llama_cpp_count}")

if llama_cpp_count > 0:
    print("\n✓ SUCCESS: llama-cpp providers are configured!")
    print("\nNow run 'hermes model' in your terminal to see them in the picker.")
    print("The fix allows providers with model_path to show up alongside API-based providers.")
else:
    print("\n✗ No llama-cpp providers found in config.")
    print("Check ~/.hermes/config.yaml for providers with 'provider: llama-cpp'")
