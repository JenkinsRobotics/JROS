#!/usr/bin/env python3
"""
Hermes Runtime Manager
Manage inference engine runtimes (llama.cpp, MLX, vLLM)
"""
import sys
import os
import subprocess
from pathlib import Path

def run_command(cmd):
    """Run shell command and return output."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return {"output": result.stdout, "exit_code": result.returncode}

HERMES_RUNTIMES = Path.home() / ".hermes" / "runtimes"
LM_STUDIO_BACKENDS = Path.home() / ".lmstudio" / "extensions" / "backends"

SUPPORTED_ENGINES = {
    "llama.cpp": {
        "latest_stable": "2.16.0",
        "description": "Universal GGUF inference, maximum compatibility",
        "best_for": ["GGUF models", "Qwen 3.5", "Legacy models"],
    },
    "mlx": {
        "latest_stable": "1.6.0",
        "description": "Apple Silicon optimized, fastest on M-series",
        "best_for": ["MLX models", "Gemma 4", "Qwen 3.6", "Maximum speed"],
    },
    "vllm": {
        "latest_stable": "pending",
        "description": "High-throughput serving (future support)",
        "best_for": ["Production serving", "Batch inference"],
    }
}

def list_runtimes():
    """List all available runtimes."""
    print("="*60)
    print("HERMES RUNTIMES")
    print("="*60)
    
    for engine_type in ["llama.cpp", "mlx", "vllm"]:
        runtime_dir = HERMES_RUNTIMES / engine_type
        
        if not runtime_dir.exists():
            print(f"\n❌ {engine_type}: Not installed")
            continue
        
        # Find latest symlink
        latest_link = runtime_dir / "latest"
        latest_version = None
        if latest_link.exists() and latest_link.is_symlink():
            latest_version = os.readlink(latest_link)
        
        print(f"\n📦 {engine_type}")
        print(f"   Active: {latest_version or 'None'}")
        print(f"   Available versions:")
        
        # List all version directories
        versions = []
        for item in runtime_dir.iterdir():
            if item.is_dir() and item.name != "latest" and item.name[0].isdigit():
                versions.append(item.name)
        
        versions.sort(key=lambda v: tuple(map(int, v.split('.'))), reverse=True)
        
        for v in versions:
            marker = "← active" if v == latest_version else ""
            print(f"     - {v} {marker}")

def use_runtime(engine_type, version):
    """Switch to a specific runtime version."""
    runtime_dir = HERMES_RUNTIMES / engine_type
    
    if not runtime_dir.exists():
        print(f"❌ Engine '{engine_type}' not found")
        print(f"   Available: {list(SUPPORTED_ENGINES.keys())}")
        return False
    
    version_path = runtime_dir / version
    if not version_path.exists():
        print(f"❌ Version '{version}' not found for {engine_type}")
        print(f"   Available versions:")
        for item in runtime_dir.iterdir():
            if item.is_dir() and item.name != "latest" and item.name[0].isdigit():
                print(f"     - {item.name}")
        return False
    
    # Update latest symlink
    latest_link = runtime_dir / "latest"
    if latest_link.exists() or latest_link.is_symlink():
        latest_link.unlink()
    
    latest_link.symlink_to(version, target_is_directory=True)
    
    print(f"✅ Switched {engine_type} to v{version}")
    print(f"   Path: {latest_link} → {version}")
    
    # Verify engine loads
    print("\n   Testing engine...")
    result = run_command(f"file {version_path}/libllm_engine.dylib")
    if result["exit_code"] == 0:
        print(f"   ✓ Engine binary verified")
    
    return True

def install_runtime(engine_type, version=None):
    """Install a new runtime version from LM Studio or download."""
    if version is None:
        version = SUPPORTED_ENGINES[engine_type]["latest_stable"]
    
    print(f"📥 Installing {engine_type} v{version}...")
    
    # Check if already in LM Studio
    if engine_type == "llama.cpp":
        pattern = f"llama.cpp-mac-arm64-apple-metal-advsimd-{version}"
    elif engine_type == "mlx":
        pattern = f"mlx-llm-mac-arm64-apple-metal-advsimd-{version}"
    else:
        print(f"❌ Auto-install not supported for {engine_type}")
        return False
    
    lm_studio_path = LM_STUDIO_BACKENDS / pattern
    
    if lm_studio_path.exists():
        print(f"   Found in LM Studio: {pattern}")
        
        # Create symlink
        runtime_dir = HERMES_RUNTIMES / engine_type
        runtime_dir.mkdir(exist_ok=True)
        
        target = runtime_dir / version
        if not target.exists():
            target.symlink_to(lm_studio_path, target_is_directory=True)
            print(f"   ✓ Linked to {target}")
            
            # Update latest if needed
            latest_link = runtime_dir / "latest"
            if not latest_link.exists():
                latest_link.symlink_to(version, target_is_directory=True)
                print(f"   ✓ Set as latest")
        
        return True
    else:
        print(f"   ❌ Not found in LM Studio")
        print(f"   Download from: https://github.com/ggerganov/llama.cpp/releases")
        print(f"   Or install via LM Studio UI")
        return False

def update_runtime(engine_type):
    """Update to latest version."""
    if engine_type not in SUPPORTED_ENGINES:
        print(f"❌ Unknown engine: {engine_type}")
        return False
    
    latest = SUPPORTED_ENGINES[engine_type]["latest_stable"]
    print(f"🔄 Updating {engine_type} to v{latest}...")
    
    return install_runtime(engine_type, latest)

def check_compatibility(model_path):
    """Check which runtimes are compatible with a model."""
    model_file = Path(model_path)
    
    print("="*60)
    print(f"COMPATIBILITY: {model_file.name}")
    print("="*60)
    
    # Check file extension
    if model_file.suffix == ".gguf":
        print("\n✅ llama.cpp: Compatible (all versions)")
        print("❌ MLX: Not compatible (GGUF format)")
        print("✅ vLLM: Compatible (with GGUF support)")
        
        # Check which GGUF features
        result = run_command(f"file {model_file}")
        if "Q4_K_M" in result["output"]:
            print("\n   Format: Q4_K_M quantization")
            print("   Recommended: llama.cpp 2.14.0+")
        
    elif (model_file / "mlx_model_config.json").exists():
        print("\n❌ llama.cpp: Not compatible (MLX format)")
        print("✅ MLX: Compatible (native format)")
        print("❌ vLLM: Not compatible")
        
    else:
        print("\n⚠️  Unknown model format")
        print("   Check model documentation for compatibility")
    
    print("\n" + "="*60)

def status():
    """Show runtime status summary."""
    print("="*60)
    print("HERMES RUNTIME STATUS")
    print("="*60)
    
    for engine_type, info in SUPPORTED_ENGINES.items():
        runtime_dir = HERMES_RUNTIMES / engine_type
        
        if runtime_dir.exists():
            latest_link = runtime_dir / "latest"
            active = os.readlink(latest_link) if latest_link.exists() else "None"
            print(f"\n✅ {engine_type}")
            print(f"   Description: {info['description']}")
            print(f"   Active: v{active}")
            print(f"   Best for: {', '.join(info['best_for'])}")
        else:
            print(f"\n❌ {engine_type}: Not installed")
            print(f"   Description: {info['description']}")

def help():
    """Show help."""
    print("""
Hermes Runtime Manager

Usage:
  python runtime_manager.py <command> [args]

Commands:
  list                      List all available runtimes
  status                    Show runtime status summary
  use <engine> <version>    Switch to specific version
  install <engine> [ver]    Install runtime from LM Studio
  update <engine>           Update to latest version
  compat <model_path>       Check model compatibility
  help                      Show this help

Examples:
  python runtime_manager.py list
  python runtime_manager.py use llama.cpp 2.14.0
  python runtime_manager.py install mlx 1.6.0
  python runtime_manager.py compat ~/.lmstudio/models/Qwen3.5-9B.gguf

Runtimes Directory:
  ~/.hermes/runtimes/
    ├── llama.cpp/
    │   ├── 2.16.0/
    │   ├── 2.14.0/
    │   └── latest → 2.16.0
    └── mlx/
        ├── 1.6.0/
        └── latest → 1.6.0
""")

# Main
if __name__ == "__main__":
    if len(sys.argv) < 2:
        help()
        sys.exit(0)
    
    command = sys.argv[1]
    
    if command == "list":
        list_runtimes()
    
    elif command == "status":
        status()
    
    elif command == "use":
        if len(sys.argv) < 4:
            print("❌ Usage: runtime_manager.py use <engine> <version>")
            sys.exit(1)
        use_runtime(sys.argv[2], sys.argv[3])
    
    elif command == "install":
        if len(sys.argv) < 3:
            print("❌ Usage: runtime_manager.py install <engine> [version]")
            sys.exit(1)
        version = sys.argv[3] if len(sys.argv) > 3 else None
        install_runtime(sys.argv[2], version)
    
    elif command == "update":
        if len(sys.argv) < 3:
            print("❌ Usage: runtime_manager.py update <engine>")
            sys.exit(1)
        update_runtime(sys.argv[2])
    
    elif command == "compat":
        if len(sys.argv) < 3:
            print("❌ Usage: runtime_manager.py compat <model_path>")
            sys.exit(1)
        check_compatibility(sys.argv[2])
    
    elif command == "help":
        help()
    
    else:
        print(f"❌ Unknown command: {command}")
        help()
        sys.exit(1)
