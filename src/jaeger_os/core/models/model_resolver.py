"""Model path resolution + on-demand download.

Jaeger ships as a framework but the actual GGUF weights don't travel
in the wheel — they're too big (15 GB+) and licensing varies by model.
This module is the single place that turns "the agent wants gemma 4"
into an absolute path on disk, fetching from HuggingFace Hub if the
file isn't already cached.

Resolution order for any input string ``name_or_path``:

  1. Absolute path → use as-is (errors if it doesn't exist).
  2. Registry key (e.g. ``gemma-4-26b-a4b-it-q4_k_m``) → check
     ``~/.jaeger/models/<key>/<file>``, then the repo's ``./models/<file>``
     (dev convenience for symlinks to LM Studio), then download from
     HF Hub to the user cache.
  3. Relative path (e.g. ``./models/x.gguf`` or ``x.gguf``) → check
     cwd, repo root, then user cache. If still not found, fall through
     to treating the basename as a registry key.

The user cache at ``~/.jaeger/models/<name>/<file>`` is the production
location. The repo's ``./models/`` directory stays valid as a dev
convenience — symlinks to LM Studio's cache resolve naturally through
step 2.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import sys
import urllib.request
from typing import Any


# ── Registry ────────────────────────────────────────────────────────


# Every entry maps a stable key to its canonical source + filename.
# Add new entries here; don't hardcode HF paths in config files.
#
# Two roles:
#   * "realtime" — the fast conversational/routing model (Gemma 4 MoE).
#   * "coder"    — the heavy skill-authoring model used in Deep Think
#                  mode (see docs/deep_think_design.md). Swapped in via
#                  jaeger_os.main.switch_model when the robot enters
#                  Deep Think; swapped back out on wake.
MODEL_REGISTRY: dict[str, dict[str, Any]] = {
    "gemma-4-26b-a4b-it-q4_k_m": {
        "hf_repo": "lmstudio-community/gemma-4-26B-A4B-it-GGUF",
        "hf_file": "gemma-4-26B-A4B-it-Q4_K_M.gguf",
        "size_gb": 15.7,
        "role": "realtime",
        "description": (
            "Gemma 4 26B MoE (4B active), Q4_K_M quantization. "
            "Default jaeger realtime model — best quality/speed "
            "tradeoff on Apple Silicon."
        ),
    },
    # ── Deep Think coder model ──────────────────────────────────────
    # Coordinates verified against the HuggingFace API 2026-05-19:
    # the repo + file both exist; size is the real Content-Length.
    # switch_model("qwen3-coder-30b-a3b-q4_k_m") auto-downloads this on
    # first use if it isn't already in ~/.jaeger/models/ or ./models/.
    "qwen3-coder-30b-a3b-q4_k_m": {
        "hf_repo": "lmstudio-community/Qwen3-Coder-30B-A3B-Instruct-GGUF",
        "hf_file": "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf",
        "size_gb": 17.4,
        "role": "coder",
        "verified": True,
        "description": (
            "Qwen3-Coder 30B MoE (3B active), Q4_K_M. Deep Think "
            "skill-authoring model — coding-specialized, MoE-fast. "
            "Auto-downloads (~17.4 GB) on first Deep Think entry."
        ),
    },
}


DEFAULT_MODEL = "gemma-4-26b-a4b-it-q4_k_m"
# The model Deep Think swaps in for skill authoring. Overridable per
# instance via config (deep_think.coder_model) once Phase D lands.
DEFAULT_CODER_MODEL = "qwen3-coder-30b-a3b-q4_k_m"


# ── Filesystem locations ────────────────────────────────────────────


def user_cache_dir() -> pathlib.Path:
    """Returns ``$JAEGER_MODELS_DIR`` if set, else ``~/.jaeger/models/``.

    Production deployments override via env var; dev keeps the home dir."""
    override = os.environ.get("JAEGER_MODELS_DIR", "").strip()
    if override:
        return pathlib.Path(override).expanduser().resolve()
    return pathlib.Path.home() / ".jaeger" / "models"


def repo_models_dir() -> pathlib.Path | None:
    """Returns the repo's ``./models/`` dir if jaeger_os is running from
    a source checkout (the usual dev shape). Returns None for installed-
    wheel deployments where there's no repo root to walk to.

    Lets us treat the existing symlink at ``<repo>/models/gemma-...gguf``
    as a valid resolution target without changing the dev workflow."""
    here = pathlib.Path(__file__).resolve()
    # src/jaeger_os/core/model_resolver.py → parents[3] = repo root
    for ancestor in here.parents:
        candidate = ancestor / "models"
        if candidate.is_dir() and (ancestor / "pyproject.toml").is_file():
            return candidate
    return None


# ── Resolution ──────────────────────────────────────────────────────


def resolve_model_path(
    name_or_path: str | None = None,
    *,
    auto_download: bool = True,
    progress: bool = True,
) -> str:
    """Resolve a model reference to an absolute on-disk path.

    Args:
      name_or_path: registry key, absolute path, or relative path. None
        means "use the default model" (DEFAULT_MODEL).
      auto_download: when the resolution lands on a registry key whose
        file isn't cached locally, download from HuggingFace Hub. Set
        False for CI / offline contexts that should fail loudly.
      progress: show download progress on stderr when fetching.

    Returns the absolute string path. Raises FileNotFoundError if the
    file can't be resolved (and auto_download didn't fix it).
    """
    # Accept str OR pathlib.Path — pydantic config types model_path as Path,
    # so the value arrives as PosixPath. Coerce so .strip() / lowercase work.
    raw = str(name_or_path) if name_or_path else ""
    ref = raw.strip() or DEFAULT_MODEL

    # Strip a leading "./" so users can write "./models/x.gguf" naturally.
    p = pathlib.Path(ref).expanduser()

    # 1. Absolute path — must exist.
    if p.is_absolute():
        if p.exists():
            return str(p)
        raise FileNotFoundError(
            f"Model not found at absolute path: {p}. "
            f"Edit your instance config or run "
            f"`python -m jaeger_os --download-model {DEFAULT_MODEL}`."
        )

    # 2. Registry key (no path separator, no extension).
    key = ref.lower()
    if key in MODEL_REGISTRY:
        return _resolve_registered(key, auto_download=auto_download,
                                   progress=progress)

    # 3. Relative path — check the usual locations in order.
    candidates: list[pathlib.Path] = [pathlib.Path.cwd() / p]
    repo_models = repo_models_dir()
    if repo_models is not None:
        candidates.append(repo_models / p.name)
    candidates.append(user_cache_dir() / p.name)
    for c in candidates:
        if c.exists():
            return str(c.resolve())

    # 4. Fall back: treat the basename (sans .gguf) as a registry key.
    basename_key = p.stem.lower()
    if basename_key in MODEL_REGISTRY:
        return _resolve_registered(basename_key, auto_download=auto_download,
                                   progress=progress)

    raise FileNotFoundError(
        f"Could not resolve model {ref!r}. Tried: "
        f"{[str(c) for c in candidates]}. Known models: "
        f"{sorted(MODEL_REGISTRY.keys())}"
    )


def _resolve_registered(
    key: str, *, auto_download: bool, progress: bool,
) -> str:
    """For a registry-key reference, find the file in user cache OR
    the repo's models/ dir, downloading if necessary."""
    entry = MODEL_REGISTRY[key]
    filename = entry["hf_file"]

    # User cache (production location).
    cached = user_cache_dir() / key / filename
    if cached.exists():
        return str(cached.resolve())

    # Repo's ./models/<file> (dev convenience — likely a symlink to
    # LM Studio's own cache).
    repo_models = repo_models_dir()
    if repo_models is not None:
        repo_path = repo_models / filename
        if repo_path.exists():
            return str(repo_path.resolve())

    if not auto_download:
        raise FileNotFoundError(
            f"Model {key!r} not in user cache or repo ./models/, and "
            f"auto_download=False."
        )

    # Download into the user cache.
    return str(download_model(key, progress=progress))


# ── Download ────────────────────────────────────────────────────────


def download_model(name: str, *, progress: bool = True) -> pathlib.Path:
    """Download ``name`` from HuggingFace Hub into the user cache.

    Prefers ``huggingface_hub.hf_hub_download`` (resumable, cached,
    integrity-checked) when the library is available. Falls back to
    a plain ``urllib`` GET against the public resolve URL when the
    library isn't installed — slower, no resume, but no extra deps.

    Returns the absolute path to the downloaded file."""
    if name not in MODEL_REGISTRY:
        raise ValueError(
            f"Unknown model {name!r}. Known: {sorted(MODEL_REGISTRY.keys())}"
        )
    entry = MODEL_REGISTRY[name]
    target_dir = user_cache_dir() / name
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / entry["hf_file"]
    if target.exists():
        return target

    repo_id = entry["hf_repo"]
    filename = entry["hf_file"]
    size_gb = entry.get("size_gb")

    msg = (f"[jaeger] downloading {name} from huggingface.co/{repo_id} "
           f"(~{size_gb} GB)..." if size_gb is not None
           else f"[jaeger] downloading {name}...")
    if progress:
        print(msg, file=sys.stderr, flush=True)

    # Preferred path: huggingface_hub.
    try:
        from huggingface_hub import hf_hub_download
        downloaded = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=str(target_dir),
        )
        result = pathlib.Path(downloaded)
        if result != target:
            shutil.move(str(result), str(target))
        return target
    except ImportError:
        pass  # fall through to urllib

    # Fallback: urllib. HF Hub's resolve endpoint is a plain HTTP GET.
    url = f"https://huggingface.co/{repo_id}/resolve/main/{filename}"
    tmp = target.with_suffix(target.suffix + ".part")

    def _hook(blocks: int, block_size: int, total_size: int) -> None:
        if not progress or total_size <= 0:
            return
        downloaded_b = blocks * block_size
        pct = min(100.0, 100.0 * downloaded_b / total_size)
        sys.stderr.write(
            f"\r[jaeger] {name}: {pct:5.1f}%  "
            f"({downloaded_b // (1024 * 1024)}/{total_size // (1024 * 1024)} MB)"
        )
        sys.stderr.flush()

    urllib.request.urlretrieve(url, tmp, reporthook=_hook)  # noqa: S310
    if progress:
        sys.stderr.write("\n")
        sys.stderr.flush()
    tmp.rename(target)
    return target


# ── Helpers for the CLI / agent tools ───────────────────────────────


def list_registered_models() -> list[dict[str, Any]]:
    """Return one entry per known model with cache status. Used by the
    ``--list-models`` CLI flag and (later) by a ``list_models`` agent
    tool so the user/agent can see what's available + downloaded."""
    out: list[dict[str, Any]] = []
    for key, entry in MODEL_REGISTRY.items():
        cached_path = user_cache_dir() / key / entry["hf_file"]
        repo_models = repo_models_dir()
        repo_path = (repo_models / entry["hf_file"]) if repo_models else None
        cached = cached_path.exists()
        local_dev = repo_path is not None and repo_path.exists()
        out.append({
            "name": key,
            "hf_repo": entry["hf_repo"],
            "filename": entry["hf_file"],
            "size_gb": entry.get("size_gb"),
            "description": entry.get("description", ""),
            "status": (
                "ready (user cache)" if cached
                else "ready (repo dev)" if local_dev
                else "not downloaded"
            ),
            "path": (str(cached_path) if cached
                     else str(repo_path) if local_dev
                     else None),
        })
    return out
