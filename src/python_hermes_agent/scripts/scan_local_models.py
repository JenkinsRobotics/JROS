#!/usr/bin/env python3
"""
Scan local system for GGUF models and configure Hermes to use them.
Finds models in:
- ~/GitHub/GITHUB/Hermes/models/
- ~/.lmstudio/models/
- Ollama models (via ollama list)
"""

import json
import os
import subprocess
from pathlib import Path

def get_file_size_gb(path):
    """Get file size in GB."""
    try:
        size_bytes = os.path.getsize(path)
        return round(size_bytes / (1024 ** 3), 2)
    except:
        return 0

def scan_hermes_models():
    """Scan Hermes models directory."""
    models_dir = Path.home() / "GitHub" / "GITHUB" / "Hermes" / "models"
    models = []
    
    if models_dir.exists():
        print(f"\n📁 Scanning {models_dir}...")
        for f in models_dir.glob("*.gguf"):
            if f.is_file() or f.is_symlink():
                # Resolve symlinks to get actual size
                actual_path = f.resolve() if f.is_symlink() else f
                size_gb = get_file_size_gb(str(actual_path))
                models.append({
                    "path": str(f.absolute()),
                    "name": f.name,
                    "size_gb": size_gb,
                    "source": "hermes",
                    "actual_path": str(actual_path) if f.is_symlink() else None
                })
                symlink_info = f" → {actual_path.name}" if f.is_symlink() else ""
                print(f"  ✓ {f.name} ({size_gb} GB){symlink_info}")
    
    return models

def scan_lmstudio_models():
    """Scan LM Studio models directory."""
    lmstudio_dir = Path.home() / ".lmstudio" / "models"
    models = []
    
    if lmstudio_dir.exists():
        print(f"\n📁 Scanning {lmstudio_dir}...")
        for gguf in lmstudio_dir.rglob("*.gguf"):
            if gguf.is_file():
                size_gb = get_file_size_gb(str(gguf))
                # Extract model name from path
                rel_path = gguf.relative_to(lmstudio_dir)
                models.append({
                    "path": str(gguf.absolute()),
                    "name": gguf.name,
                    "size_gb": size_gb,
                    "source": "lmstudio",
                    "relative_path": str(rel_path)
                })
                print(f"  ✓ {rel_path} ({size_gb} GB)")
    
    return models

def scan_ollama_models():
    """Scan Ollama models."""
    models = []
    
    try:
        print(f"\n📁 Scanning Ollama models...")
        result = subprocess.run(
            ["ollama", "list", "--json"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            for model in data.get("models", []):
                name = model.get("name", "unknown")
                size_gb = round(model.get("size", 0) / (1024 ** 3), 2)
                models.append({
                    "name": name,
                    "size_gb": size_gb,
                    "source": "ollama",
                    "ollama_name": name
                })
                print(f"  ✓ {name} ({size_gb} GB)")
    except Exception as e:
        print(f"  ⚠ Ollama scan failed: {e}")
    
    return models

def generate_provider_config(models):
    """Generate Hermes provider config for local models."""
    
    if not models:
        print("\n❌ No local GGUF models found!")
        return None
    
    print("\n" + "=" * 60)
    print("DISCOVERED LOCAL MODELS")
    print("=" * 60)
    
    for i, model in enumerate(models, 1):
        source_icon = {"hermes": "🔷", "lmstudio": "🔵", "ollama": "🟢"}.get(model["source"], "⚪")
        print(f"\n{i}. {source_icon} {model['name']}")
        print(f"   Size: {model['size_gb']} GB")
        print(f"   Source: {model['source']}")
        if model.get("actual_path"):
            print(f"   Symlink to: {model['actual_path']}")
        if model.get("relative_path"):
            print(f"   LM Studio path: {model['relative_path']}")
    
    print("\n" + "=" * 60)
    print("HERMES CONFIGURATION OPTIONS")
    print("=" * 60)
    
    # Generate config snippets
    configs = []
    
    for model in models:
        if model["source"] == "ollama":
            config = {
                "name": model["ollama_name"],
                "provider": "ollama",
                "base_url": "http://localhost:11434/v1",
                "default": model["ollama_name"],
                "api_key": "ollama"
            }
            configs.append(config)
        else:
            # llama-cpp config
            model_path = model["path"]
            config = {
                "name": model["name"].replace(".gguf", ""),
                "provider": "llama-cpp",
                "model_path": model_path,
                "gpu_layers": 35,  # Default for 4-8GB VRAM
                "ctx_size": 8192
            }
            configs.append(config)
    
    return configs

def print_setup_instructions(configs):
    """Print instructions for setting up models in Hermes."""
    
    print("\n" + "=" * 60)
    print("SETUP INSTRUCTIONS")
    print("=" * 60)
    
    print("\n1. Install llama-cpp-python (if not already done):")
    print("   CMAKE_ARGS=\"-DGGML_METAL=on\" pip3 install llama-cpp-python")
    
    print("\n2. Add custom providers to ~/.hermes/config.yaml:")
    print("   providers:")
    
    for config in configs:
        if config.get("provider") == "llama-cpp":
            print(f"     {config['name']}:")
            print(f"       provider: llama-cpp")
            print(f"       model_path: \"{config['model_path']}\"")
            print(f"       n_gpu_layers: {config['gpu_layers']}")
            print(f"       n_ctx: {config['ctx_size']}")
        elif config.get("provider") == "ollama":
            print(f"     {config['name']}:")
            print(f"       provider: ollama")
            print(f"       base_url: \"{config['base_url']}\"")
            print(f"       default: \"{config['default']}\"")
    
    print("\n3. Switch to a local model:")
    print("   hermes model")
    print("   # Then select your local model from the list")
    
    print("\n4. Or set directly via config:")
    if configs:
        first = configs[0]
        print(f"   hermes config set model.default \"{first['name']}\"")
        print(f"   hermes config set model.provider \"{first['provider']}\"")

def main():
    print("=" * 60)
    print("Hermes Local Model Scanner")
    print("=" * 60)
    
    all_models = []
    all_models.extend(scan_hermes_models())
    all_models.extend(scan_lmstudio_models())
    all_models.extend(scan_ollama_models())
    
    if all_models:
        configs = generate_provider_config(all_models)
        if configs:
            print_setup_instructions(configs)
            
            # Save to JSON for reference
            output_file = Path.home() / ".hermes" / "discovered_models.json"
            with open(output_file, "w") as f:
                json.dump({"models": all_models, "configs": configs}, f, indent=2)
            print(f"\n💾 Model list saved to: {output_file}")
    else:
        print("\n❌ No models found in any location.")
        print("\nExpected locations:")
        print("  - ~/GitHub/GITHUB/Hermes/models/*.gguf")
        print("  - ~/.lmstudio/models/**/*.gguf")
        print("  - Ollama models (run 'ollama pull <model>')")

if __name__ == "__main__":
    main()
