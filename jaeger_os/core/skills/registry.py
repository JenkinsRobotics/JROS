"""Retired in 0.3.0.

This module was Lilith-line scaffolding — it referenced a
``jaeger_os.instance.lilith.skills`` namespace that doesn't exist
and a parallel ``manifest.yaml`` format with ``category:
cognitive|physical`` as the only taxonomy axis.

Its useful ideas have been folded into the v3 skill system:

  * Deferred-import discovery, tier validation, environment-filtered
    loading → :mod:`jaeger_os.core.skills.skill_loader`
  * Cognitive / physical split → ``domains`` field on the unified v3
    manifest (multi-valued; see ``docs/skill_schema_v3.md``)
  * Capability filtering → ``Manifest.is_supported_package`` /
    ``Manifest.is_supported_runtime``

Importing this module is a no-op; importing any symbol from it
raises ``DeprecationWarning``-via-``ImportError`` so the call site
gets a loud signal to migrate.
"""

from __future__ import annotations


def __getattr__(name: str):  # noqa: D401
    raise ImportError(
        f"jaeger_os.core.skills.registry.{name} was retired in 0.3.0. "
        "Use jaeger_os.core.skills.skill_loader (discover_skills / "
        "load_and_register) and jaeger_os.core.skills.manifest_v3 "
        "(Manifest, load_manifest_from_folder) instead. "
        "See docs/skill_schema_v3.md."
    )
