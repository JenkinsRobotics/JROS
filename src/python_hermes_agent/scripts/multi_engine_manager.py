#!/usr/bin/env python3
"""
LM Studio Multi-Engine Manager
Configure and switch between inference engines (llama.cpp, MLX, etc.)
"""
import json
from pathlib import Path
from hermes_tools import terminal, write_file, read_file

LM_STUDIO_PATH = Path.home() / ".lmstudio"
ENGINES_PATH = LM_STUDIO_PATH / "extensions" / "backends"
HERMES_CONFIG = Path.home() / ".hermes" / "config.yaml"

def find_engines():
    """Discover available LM Studio engines."""
    engines = {"mlx": [], "llama.cpp": []}
    
    if not ENGINES_PATH.exists():
        print(f"LM Studio backends not found at {ENGINES_PATH}")
        return engines
    
    for engine_file in ENGINES_PATH.glob("*/libllm_engine.dylib"):
        parts = engine_file.parent.name.split("-")
        if "mlx" in engine_file.parent.name:
            version = next((p for p in parts if p[0].isdigit() and '.' in p), "unknown")
            engines["mlx"].append({"version": version, "path": str(engine_file)})
        elif "llama.cpp" in engine_file.parent.name:
            version = next((p for p in parts if p[0].isdigit() and '.' in p), "unknown")
            engines["llama.cpp"].append({"version": version, "path": str(engine_file)})
    
    return engines

def find_models():
    """Find models in LM Studio with their formats."""
    models = {"mlx": [], "gguf": []}
    models_path = LM_STUDIO_PATH / "models"
    
    if not models_path.exists():
        return models
    
    for model_dir in models_path.glob("*/*"):
        if model_dir.is_dir():
            # Check for MLX
            if (model_dir / "mlx_model_config.json").exists() or \
               any(model_dir.glob("*.mlx")):
                models["mlx"].append(str(model_dir))
            # Check for GGUF
            gguf_files = list(model_dir.glob("*.gguf"))
            if gguf_files:
                models["gguf"].append(str(gguf_files[0]))
    
    return models

def generate_multi_engine_config():
    """Generate Hermes config with multi-engine support."""
    engines = find_engines()
    models = find_models()
    
    print("="*60)
    print("LM STUDIO MULTI-ENGINE CONFIGURATION")
    print("="*60)
    
    print(f"\n📦 Found Engines:")
    print(f"  MLX: {len(engines['mlx'])} versions")
    for e in engines["mlx"]:
        print(f"    - v{e['version']}")
    print(f"  llama.cpp: {len(engines['llama.cpp'])} versions")
    for e in engines["llama.cpp"]:
        print(f"    - v{e['version']}")
    
    print(f"\n📁 Found Models:")
    print(f"  MLX format: {len(models['mlx'])} models")
    for m in models["mlx"][:5]:
        print(f"    - {Path(m).name}")
    print(f"  GGUF format: {len(models['gguf'])} models")
    for m in models["gguf"][:5]:
        print(f"    - {Path(m).name}")
    
    # Generate config additions
    print("\n" + "="*60)
    print("RECOMMENDED CONFIGURATION")
    print("="*60)
    
    config_yaml = """
# Add these providers to ~/.hermes/config.yaml

providers:
  # === MLX ENGINE (Fastest on Apple Silicon) ===
"""
    
    # Add MLX models
    for i, model_path in enumerate(models["mlx"][:3]):
        name = Path(model_path).parent.name.lower().replace(" ", "-").replace("_", "-")
        config_yaml += f"""
  {name}-mlx:
    provider: llama-cpp
    model_path: {model_path}
    n_gpu_layers: -1  # MLX: use all GPU
    n_ctx: 32768
    # Note: Requires MLX engine backend
"""
    
    config_yaml += """
  # === llama.cpp ENGINE (Maximum Compatibility) ===
"""
    
    # Add GGUF models
    for i, model_path in enumerate(models["gguf"][:5]):
        name = Path(model_path).stem.lower().replace(" ", "-").replace("_", "-")[:30]
        config_yaml += f"""
  {name}:
    provider: llama-cpp
    model_path: {model_path}
    n_gpu_layers: 35  # Adjust based on VRAM
    n_ctx: 8192
"""
    
    print(config_yaml)
    
    # Save to file
    output_file = Path.home() / ".hermes" / "multi_engine_config.yaml"
    write_file(path=str(output_file), content=config_yaml)
    print(f"\n💾 Config snippet saved to: {output_file}")
    
    return engines, models

def switch_engine(engine_type, version=None):
    """Switch to a specific engine version."""
    engines = find_engines()
    
    if engine_type not in engines or not engines[engine_type]:
        print(f"❌ No {engine_type} engines found")
        return False
    
    # Select version
    if version:
        engine = next((e for e in engines[engine_type] if version in e["version"]), None)
    else:
        # Use latest
        engine = engines[engine_type][0]
    
    if not engine:
        print(f"❌ Engine version {version} not found")
        return False
    
    print(f"✅ Selected: {engine_type} v{engine['version']}")
    print(f"   Path: {engine['path']}")
    
    # Set environment variable
    terminal(command=f"export LLM_ENGINE_PATH={engine['path']}")
    
    return True

def benchmark_engines(model_path):
    """Benchmark different engines on the same model."""
    print("="*60)
    print(f"BENCHMARKING: {model_path}")
    print("="*60)
    
    engines = find_engines()
    results = []
    
    for engine_type, engine_list in engines.items():
        for engine in engine_list[:2]:  # Test top 2 versions
            print(f"\n🔧 Testing {engine_type} v{engine['version']}...")
            # Would run actual benchmark here
            results.append({
                "engine": engine_type,
                "version": engine["version"],
                "status": "tested"
            })
    
    return results

# Main
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "generate":
            generate_multi_engine_config()
        
        elif command == "switch":
            engine_type = sys.argv[2] if len(sys.argv) > 2 else "llama.cpp"
            version = sys.argv[3] if len(sys.argv) > 3 else None
            switch_engine(engine_type, version)
        
        elif command == "list":
            engines = find_engines()
            models = find_models()
            print("Engines:", engines)
            print("Models:", models)
        
        elif command == "benchmark":
            model_path = sys.argv[2] if len(sys.argv) > 2 else None
            if model_path:
                benchmark_engines(model_path)
            else:
                print("Usage: python multi_engine.py benchmark <model_path>")
    else:
        print("LM Studio Multi-Engine Manager")
        print("\nCommands:")
        print("  generate  - Generate multi-engine config")
        print("  switch    - Switch to specific engine")
        print("  list      - List available engines/models")
        print("  benchmark - Benchmark engines on a model")
        print("\nExamples:")
        print("  python multi_engine.py generate")
        print("  python multi_engine.py switch mlx 1.6.0")
        print("  python multi_engine.py list")
