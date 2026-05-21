"""Model discovery — what models are available, and where.

Surveys three sources so the TUI's ``/model`` command can show the full
picture at a glance:

  - **JROS registry** — GGUF models JROS runs in-process (downloaded or
    downloadable), via :mod:`model_resolver`.
  - **Ollama** — a local Ollama server's installed models (its
    ``/api/tags`` endpoint), when the server is running.
  - **LM Studio** — a local LM Studio server's models (its OpenAI-
    compatible ``/v1/models`` endpoint), when it is running.

Every server probe is best-effort with a short timeout: a server that
is not running yields an ``online: False`` status, never an exception.
The point is troubleshooting — being able to A/B the in-process model
against a separate local server to see which is at fault.
"""

from __future__ import annotations

import pathlib
from typing import Any

OLLAMA_URL = "http://localhost:11434"
LMSTUDIO_URL = "http://localhost:1234"
_PROBE_TIMEOUT = 1.5

# Where LM Studio keeps downloaded GGUF models (newer + older layouts).
_LMSTUDIO_DIRS = ("~/.lmstudio/models", "~/.cache/lm-studio/models")


def discover_jaeger() -> list[dict[str, Any]]:
    """JROS's own GGUF models — registered, with download/cache status."""
    try:
        from .model_resolver import list_registered_models
        return list_registered_models()
    except Exception:  # noqa: BLE001
        return []


def _scan_gguf(root: pathlib.Path, source: str) -> list[dict[str, Any]]:
    """Every ``*.gguf`` under ``root`` (recursive), tagged with ``source``."""
    out: list[dict[str, Any]] = []
    if not root.is_dir():
        return out
    try:
        for p in sorted(root.rglob("*.gguf")):
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            out.append({
                "name": p.name,
                "path": str(p),
                "size_gb": round(size / 1e9, 1) if size else None,
                "source": source,
            })
    except Exception:  # noqa: BLE001
        pass
    return out


def discover_local_gguf() -> list[dict[str, Any]]:
    """Every ``.gguf`` file on disk JROS could load in-process — the
    repo ``models/`` dir, the JROS model cache, and LM Studio's model
    folder. De-duplicated by absolute path; works with no server
    running (it is a pure filesystem scan)."""
    try:
        from .model_resolver import repo_models_dir, user_cache_dir
    except Exception:  # noqa: BLE001
        return []
    roots: list[tuple[pathlib.Path, str]] = []
    repo = repo_models_dir()
    if repo is not None:
        roots.append((repo, "repo models/"))
    try:
        roots.append((user_cache_dir(), "jaeger cache"))
    except Exception:  # noqa: BLE001
        pass
    for lm in _LMSTUDIO_DIRS:
        roots.append((pathlib.Path(lm).expanduser(), "lm studio"))
    seen: dict[str, dict[str, Any]] = {}
    for root, source in roots:
        for m in _scan_gguf(root, source):
            seen.setdefault(m["path"], m)
    return list(seen.values())


def discover_ollama_disk() -> list[dict[str, Any]]:
    """Ollama models read from the on-disk manifest tree
    (``~/.ollama/models/manifests``) — works even when the Ollama
    server is not running. Returns ``[{name: 'model:tag'}, …]``."""
    base = pathlib.Path("~/.ollama/models/manifests").expanduser()
    if not base.is_dir():
        return []
    models: list[dict[str, Any]] = []
    try:
        # manifests/<registry>/<namespace>/<model>/<tag-file>
        for tag_file in sorted(base.rglob("*")):
            if tag_file.is_file():
                models.append({"name": f"{tag_file.parent.name}:{tag_file.name}"})
    except Exception:  # noqa: BLE001
        pass
    return models


def _get_json(url: str) -> Any:
    import requests
    resp = requests.get(url, timeout=_PROBE_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def discover_ollama(base: str = OLLAMA_URL) -> dict[str, Any]:
    """Installed Ollama models via ``/api/tags``. Returns
    ``{online, models, endpoint}`` — ``online: False`` if not running."""
    try:
        data = _get_json(f"{base.rstrip('/')}/api/tags")
    except Exception as exc:  # noqa: BLE001
        return {"online": False, "models": [], "endpoint": base,
                "detail": type(exc).__name__}
    models: list[dict[str, Any]] = []
    for m in (data.get("models") or []):
        if isinstance(m, dict) and m.get("name"):
            size = m.get("size")
            models.append({
                "name": m["name"],
                "size_gb": (round(size / 1e9, 1)
                            if isinstance(size, (int, float)) else None),
            })
    return {"online": True, "models": models, "endpoint": base}


def discover_lmstudio(base: str = LMSTUDIO_URL) -> dict[str, Any]:
    """LM Studio models via the OpenAI-compatible ``/v1/models``
    endpoint. Returns ``{online, models, endpoint}``."""
    try:
        data = _get_json(f"{base.rstrip('/')}/v1/models")
    except Exception as exc:  # noqa: BLE001
        return {"online": False, "models": [], "endpoint": base,
                "detail": type(exc).__name__}
    models = [{"name": m["id"]} for m in (data.get("data") or [])
              if isinstance(m, dict) and m.get("id")]
    return {"online": True, "models": models, "endpoint": base}


def discover_all() -> dict[str, Any]:
    """The full picture: JROS registry + Ollama + LM Studio."""
    return {
        "jaeger": discover_jaeger(),
        "ollama": discover_ollama(),
        "lmstudio": discover_lmstudio(),
    }
