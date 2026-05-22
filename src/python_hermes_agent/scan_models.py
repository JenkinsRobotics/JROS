#!/usr/bin/env python3
"""
Hermes Model Scanner & Selector

Scans local model directories (Hermes models/, LMStudio, Ollama) for GGUF files
and presents them in a selectable interface for use with llama.cpp agent.

Usage:
    python scan_models.py              # Interactive selection
    python scan_models.py --list       # List all models
    python scan_models.py --select     # Select and set as default
    python scan_models.py --config     # Show current config
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict


@dataclass
class ModelInfo:
    """Information about a GGUF model."""
    path: str
    filename: str
    model_name: str
    quantization: str
    size_gb: float
    source: str  # "hermes", "lmstudio", "ollama"
    repo_name: Optional[str] = None


def get_model_size_gb(path: str) -> float:
    """Get model file size in GB."""
    try:
        size_bytes = os.path.getsize(path)
        return round(size_bytes / (1024 ** 3), 2)
    except OSError:
        return 0.0


def extract_model_info(filepath: str, source: str) -> Optional[ModelInfo]:
    """Extract model information from filepath."""
    filename = os.path.basename(filepath)
    
    # Skip projector files
    if filename.startswith("mmproj-"):
        return None
    
    if not filename.endswith(".gguf"):
        return None
    
    # Extract model name and quantization from filename
    # Examples:
    # - Llama-3.2-3B-Instruct-Q4_K_M.gguf
    # - Qwen3.5-9B-Q4_K_M.gguf
    # - gemma-4-31B-it-Q4_K_M.gguf
    
    name_parts = filename.replace(".gguf", "").split("-")
    
    # Try to identify quantization (usually last 1-2 parts)
    quant_patterns = ["Q4_K_M", "Q5_K_M", "Q6_K", "Q8_0", "Q3_K_M", "Q2_K", 
                      "IQ4_NL", "IQ3_S", "BF16", "FP16"]
    
    quantization = "Unknown"
    model_name_parts = name_parts
    
    for i in range(len(name_parts) - 1, max(0, len(name_parts) - 3), -1):
        part = "-".join(name_parts[i:])
        if any(p in part.upper() for p in quant_patterns):
            quantization = part
            model_name_parts = name_parts[:i]
            break
    
    model_name = "-".join(model_name_parts) if model_name_parts else filename
    
    # Extract repo name for LMStudio models
    repo_name = None
    if source == "lmstudio":
        # Path format: ~/.lmstudio/models/<repo>/<model>/<file>
        parts = filepath.split(os.sep)
        try:
            repo_idx = parts.index("models") + 1
            if repo_idx < len(parts):
                repo_name = parts[repo_idx]
        except (ValueError, IndexError):
            pass
    
    return ModelInfo(
        path=filepath,
        filename=filename,
        model_name=model_name,
        quantization=quantization,
        size_gb=get_model_size_gb(filepath),
        source=source,
        repo_name=repo_name,
    )


def scan_hermes_models(base_dir: str) -> List[ModelInfo]:
    """Scan Hermes models/ directory."""
    models = []
    models_dir = os.path.join(base_dir, "models")
    
    if not os.path.exists(models_dir):
        return models
    
    for root, dirs, files in os.walk(models_dir):
        for file in files:
            if file.endswith(".gguf") and not file.startswith("mmproj-"):
                filepath = os.path.join(root, file)
                info = extract_model_info(filepath, "hermes")
                if info:
                    models.append(info)
    
    return models


def scan_lmstudio_models(home_dir: str) -> List[ModelInfo]:
    """Scan LMStudio models directory."""
    models = []
    lmstudio_dir = os.path.join(home_dir, ".lmstudio", "models")
    
    if not os.path.exists(lmstudio_dir):
        return models
    
    for root, dirs, files in os.walk(lmstudio_dir):
        for file in files:
            if file.endswith(".gguf") and not file.startswith("mmproj-"):
                filepath = os.path.join(root, file)
                info = extract_model_info(filepath, "lmstudio")
                if info:
                    models.append(info)
    
    return models


def scan_ollama_models(home_dir: str) -> List[ModelInfo]:
    """Scan Ollama models directory."""
    models = []
    ollama_dir = os.path.join(home_dir, ".ollama", "models", "blobs")
    
    if not os.path.exists(ollama_dir):
        return models
    
    # Ollama stores models as blobs with sha256 names
    # We need to check manifests to get actual model names
    manifests_dir = os.path.join(home_dir, ".ollama", "models", "manifests")
    
    if not os.path.exists(manifests_dir):
        return models
    
    # For now, just list the blobs (limited info)
    for file in os.listdir(ollama_dir):
        if file.startswith("sha256-"):
            filepath = os.path.join(ollama_dir, file)
            # Ollama blobs are not directly usable as GGUF files
            # Skip for now - would need to export from Ollama first
            pass
    
    return models


def scan_all_models() -> Dict[str, List[ModelInfo]]:
    """Scan all model sources."""
    home_dir = os.path.expanduser("~")
    hermes_dir = os.path.join(home_dir, "GitHub", "GITHUB", "Hermes")
    
    results = {
        "hermes": scan_hermes_models(hermes_dir),
        "lmstudio": scan_lmstudio_models(home_dir),
        "ollama": scan_ollama_models(home_dir),
    }
    
    return results


def print_model_table(models: List[ModelInfo], show_index: bool = True):
    """Print models in a formatted table."""
    if not models:
        print("No models found.")
        return
    
    # Sort by model name
    models.sort(key=lambda m: (m.model_name.lower(), m.quantization))
    
    # Calculate column widths
    idx_width = 4
    name_width = max(len(m.model_name) for m in models) + 2
    quant_width = max(len(m.quantization) for m in models) + 2
    size_width = 8
    source_width = 10
    
    # Print header
    header = f"{'#':<{idx_width}} {'Model':<{name_width}} {'Quant':<{quant_width}} {'Size':<{size_width}} {'Source':<{source_width}}"
    print(header)
    print("-" * len(header))
    
    # Print models
    for i, model in enumerate(models, 1):
        idx_str = f"{i}." if show_index else ""
        source_str = f"{model.source} ({model.repo_name})" if model.repo_name else model.source
        print(f"{idx_str:<{idx_width}} {model.model_name:<{name_width}} {model.quantization:<{quant_width}} {model.size_gb:>5.2f} GB {source_str:<{source_width}}")


def select_model_interactive(models: List[ModelInfo]) -> Optional[ModelInfo]:
    """Interactive model selection."""
    if not models:
        print("No models available.")
        return None
    
    print_model_table(models)
    print()
    
    while True:
        try:
            choice = input(f"Select model (1-{len(models)}): ").strip()
            if not choice:
                return None
            
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                return models[idx]
            else:
                print(f"Please enter a number between 1 and {len(models)}")
        except ValueError:
            print("Please enter a valid number")
        except KeyboardInterrupt:
            print()
            return None


def set_model_as_default(model: ModelInfo, hermes_home: str = None):
    """Set model as default in Hermes config."""
    if hermes_home is None:
        hermes_home = os.path.expanduser("~/.hermes")
    
    config_path = os.path.join(hermes_home, "config.yaml")
    env_path = os.path.join(hermes_home, ".env")
    
    # Update .env file
    env_vars = {
        "LLAMA_CPP_MODEL_PATH": model.path,
        "LLAMA_CPP_GPU_LAYERS": "35",  # Default to moderate GPU offload
        "LLAMA_CPP_CTX_SIZE": "8192",
    }
    
    # Read existing .env
    existing_vars = {}
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    existing_vars[key.strip()] = value.strip()
    
    # Update with new values
    existing_vars.update(env_vars)
    
    # Write back
    os.makedirs(os.path.dirname(env_path), exist_ok=True)
    with open(env_path, "w") as f:
        f.write("# Llama.cpp model configuration (set by scan_models.py)\n")
        f.write(f"LLAMA_CPP_MODEL_PATH=\"{model.path}\"\n")
        f.write(f"LLAMA_CPP_GPU_LAYERS=\"{env_vars['LLAMA_CPP_GPU_LAYERS']}\"\n")
        f.write(f"LLAMA_CPP_CTX_SIZE=\"{env_vars['LLAMA_CPP_CTX_SIZE']}\"\n")
        f.write(f"# Model: {model.model_name} ({model.quantization})\n")
        f.write(f"# Source: {model.source}\n")
        f.write(f"# Size: {model.size_gb} GB\n")
    
    print(f"✓ Model set as default in {env_path}")
    print(f"  Path: {model.path}")
    print(f"  Quantization: {model.quantization}")
    print(f"  Size: {model.size_gb} GB")
    print()
    print("To use this model:")
    print("  hermes chat --model llama-cpp")
    print()
    print("Or adjust GPU layers:")
    print("  export LLAMA_CPP_GPU_LAYERS=50  # Increase for more GPU offload")
    print("  hermes chat --model llama-cpp")


def generate_hf_repo_suggestion(model: ModelInfo) -> Optional[str]:
    """Suggest HuggingFace repo based on model name."""
    # Common GGUF uploaders
    uploaders = ["bartowski", "lmstudio-community", "TheBloke", "MaziyarPanahi"]
    
    model_lower = model.model_name.lower()
    
    # Try to match known patterns
    if "llama" in model_lower:
        if "3.2" in model_lower:
            return "bartowski/Llama-3.2-*-Instruct-GGUF"
        elif "3.1" in model_lower:
            return "bartowski/Llama-3.1-*-Instruct-GGUF"
    elif "qwen" in model_lower:
        return "bartowski/Qwen*-GGUF"
    elif "gemma" in model_lower:
        return "lmstudio-community/gemma-*-GGUF"
    elif "mistral" in model_lower:
        return "bartowski/Mistral-*-Instruct-GGUF"
    
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Scan and select GGUF models for Hermes agent"
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all available models"
    )
    parser.add_argument(
        "--select", "-s",
        action="store_true",
        help="Interactively select a model to set as default"
    )
    parser.add_argument(
        "--config", "-c",
        action="store_true",
        help="Show current model configuration"
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output as JSON"
    )
    parser.add_argument(
        "--hermes-home",
        type=str,
        default=os.path.expanduser("~/.hermes"),
        help="Hermes home directory (default: ~/.hermes)"
    )
    
    args = parser.parse_args()
    
    # Scan models
    print("Scanning for GGUF models...", file=sys.stderr)
    all_models = scan_all_models()
    
    # Flatten and combine
    models = []
    for source, source_models in all_models.items():
        models.extend(source_models)
    
    # Remove duplicates (same path)
    seen_paths = set()
    unique_models = []
    for model in models:
        if model.path not in seen_paths:
            seen_paths.add(model.path)
            unique_models.append(model)
    
    models = unique_models
    
    if args.json:
        output = {
            "models": [
                {
                    "path": m.path,
                    "filename": m.filename,
                    "model_name": m.model_name,
                    "quantization": m.quantization,
                    "size_gb": m.size_gb,
                    "source": m.source,
                    "repo_name": m.repo_name,
                }
                for m in models
            ],
            "total": len(models),
        }
        print(json.dumps(output, indent=2))
        return
    
    if args.config:
        env_path = os.path.join(args.hermes_home, ".env")
        if os.path.exists(env_path):
            print(f"Current configuration ({env_path}):")
            print()
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("LLAMA_CPP_"):
                        print(line)
        else:
            print("No Hermes configuration found.")
        return
    
    if args.list:
        print(f"\nFound {len(models)} GGUF models:\n")
        
        # Group by source
        for source in ["hermes", "lmstudio", "ollama"]:
            source_models = [m for m in models if m.source == source]
            if source_models:
                print(f"\n{source.upper()} ({len(source_models)} models):")
                print("-" * 60)
                print_model_table(source_models, show_index=False)
        return
    
    if args.select:
        print(f"\nFound {len(models)} available models:\n")
        selected = select_model_interactive(models)
        
        if selected:
            print(f"\nSelected: {selected.model_name} ({selected.quantization})")
            print(f"  Path: {selected.path}")
            print(f"  Size: {selected.size_gb} GB")
            print(f"  Source: {selected.source}")
            
            hf_suggestion = generate_hf_repo_suggestion(selected)
            if hf_suggestion:
                print(f"  HF Repo (similar): {hf_suggestion}")
            
            print()
            confirm = input("Set as default model? (y/n): ").strip().lower()
            if confirm == "y":
                set_model_as_default(selected, args.hermes_home)
        return
    
    # Default: interactive selection
    print(f"\n{'='*60}")
    print("Hermes Model Selector")
    print(f"{'='*60}")
    print(f"\nFound {len(models)} GGUF models from:")
    print(f"  - Hermes models/: {len(all_models['hermes'])}")
    print(f"  - LMStudio: {len(all_models['lmstudio'])}")
    print(f"  - Ollama: {len(all_models['ollama'])}")
    print()
    
    selected = select_model_interactive(models)
    
    if selected:
        print(f"\n✓ Selected: {selected.model_name}")
        print(f"  Path: {selected.path}")
        print(f"  Quantization: {selected.quantization}")
        print(f"  Size: {selected.size_gb} GB")
        print()
        
        # Show command to use
        print("To use this model with Hermes:")
        print(f"  hermes chat --model llama-cpp --model-path \"{selected.path}\"")
        print()
        
        # Offer to set as default
        confirm = input("Set as default model in ~/.hermes/.env? (y/n): ").strip().lower()
        if confirm == "y":
            set_model_as_default(selected, args.hermes_home)


if __name__ == "__main__":
    main()
