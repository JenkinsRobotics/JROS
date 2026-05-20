"""Model-management tools — the agent's view of available LLMs.

  • list_models()         — registered models + cache status (read-only)
  • download_model(name)  — fetch a registered model from HF Hub

Design intent (2026-05-19): the agent must NOT download models silently
on its own. ``download_model`` is gated at ``PRIVILEGED`` (tier 4) so it
routes through the permission confirmation flow — it only runs when the
user explicitly asks for a model, or agrees to one the agent recommended
in conversation. ``list_models`` is read-only (tier 0) so the agent can
freely tell the user what's available and make a recommendation.

The FRAMEWORK still auto-downloads a missing model when one is needed
for boot / switch_model — that's plumbing, not an agent decision. These
tools are the *deliberate* path: the agent choosing, with the user, to
fetch a model.
"""

from __future__ import annotations

from typing import Any

from ..permissions import PermissionTier, requires_tier


def list_models() -> dict[str, Any]:
    """List every model in the registry with its role (realtime / coder)
    and cache status (ready / not downloaded). Read-only — use this to
    tell the user what's available or to back a recommendation."""
    from ..model_resolver import MODEL_REGISTRY, list_registered_models
    rows = list_registered_models()
    for r in rows:
        entry = MODEL_REGISTRY.get(r["name"], {})
        r["role"] = entry.get("role", "unknown")
    return {"models": rows, "count": len(rows)}


@requires_tier(
    PermissionTier.PRIVILEGED,
    skill="models",
    operation="download_model",
    summary="download a model (large — multiple GB) from HuggingFace Hub",
)
def download_model(name: str) -> dict[str, Any]:
    """Download a registered model into the user model cache.

    Tier-4 (PRIVILEGED): a model is a multi-GB download, so this routes
    through the permission confirmation flow — it runs only when the
    user has agreed (either by asking directly or approving a model you
    recommended). Do NOT call this speculatively; recommend first, let
    the user decide, then call it.

    ``name`` must be a key in the model registry — call ``list_models``
    to see valid names. Returns ``{ok, model, path}`` on success or
    ``{ok: False, error: ...}``."""
    from ..model_resolver import MODEL_REGISTRY
    from ..model_resolver import download_model as _download

    key = (name or "").strip()
    if key not in MODEL_REGISTRY:
        return {
            "ok": False,
            "model": key,
            "error": (f"unknown model {key!r}; call list_models() for the "
                      f"registry. Known: {sorted(MODEL_REGISTRY.keys())}"),
        }
    try:
        path = _download(key, progress=False)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "model": key, "error": str(exc)}
    return {"ok": True, "model": key, "path": str(path)}
