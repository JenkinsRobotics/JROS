"""Skill discovery, manifest validation, and registry.

The registry walks the ``lilith.skills`` package, parses every
``manifest.yaml`` it finds, validates it, and exposes the loaded skills
to the launcher. Cognitive skills always load; physical skills load
only when the runtime environment reports a body is present.

Loading contract: a skill missing a permission tier declaration
fails to load with a clear error.

The validation in :func:`load_manifest` enforces that — and several
sibling rules (``name`` matches the directory, ``category`` is one of
the two valid values, ``entry_point`` is a ``module:attr`` string).

The registry does *not* import skill server modules unless asked. That
keeps discovery cheap and lets ``list_loaded()`` report what's
available without paying import cost. Call :meth:`Registry.load`
to actually import a server.

# PORTABILITY: Layer 1. The registry knows the *shape* of a skill
# directory; it does not know what a skill actually does. The
# ``cognitive`` vs. ``physical`` split is data — the registry filters
# on it but does not know what each category means.
"""

from __future__ import annotations

import importlib
import pathlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

import yaml


SkillCategory = Literal["cognitive", "physical"]
"""The two skill categories. See ``docs/skill_authoring.md``."""

_REQUIRED_FIELDS = ("name", "category", "permission_tier", "entry_point")
_VALID_CATEGORIES: tuple[SkillCategory, ...] = ("cognitive", "physical")
_VALID_TIERS = (0, 1, 2, 3, 4, 5)


# --- Manifest ---------------------------------------------------------------


class ManifestError(ValueError):
    """A skill manifest is missing fields or contains invalid values."""


@dataclass(frozen=True)
class SkillManifest:
    """Validated, parsed view of a ``manifest.yaml``.

    Attributes:
        name: The skill name. Must match the on-disk directory name.
        category: ``"cognitive"`` or ``"physical"``.
        permission_tier: 0..5; matches :class:`PermissionTier` values.
        entry_point: ``"module.path:attr"`` — what the registry imports
            to access the skill's MCP server.
        version: SemVer-ish; informational.
        latency_class: ``"instant" | "fast" | "slow"``; informational.
        dependencies: extra pip deps the skill needs.
        description: free text.
        path: absolute path to the manifest file on disk.
    """

    name: str
    category: SkillCategory
    permission_tier: int
    entry_point: str
    version: str
    latency_class: str
    dependencies: tuple[str, ...]
    description: str
    path: pathlib.Path


def load_manifest(path: pathlib.Path) -> SkillManifest:
    """Parse and validate a manifest file.

    Raises:
        FileNotFoundError: when ``path`` does not exist.
        ManifestError: when fields are missing, empty, or invalid.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Skill manifest not found: {path}")
    raw_text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ManifestError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError(
            f"{path} top level must be a YAML mapping, got {type(data).__name__}"
        )

    missing = [f for f in _REQUIRED_FIELDS if f not in data]
    if missing:
        raise ManifestError(
            f"{path} is missing required field(s): {', '.join(missing)}"
        )

    name = str(data["name"]).strip()
    if not name:
        raise ManifestError(f"{path}: 'name' must be non-empty")

    # The directory the manifest lives in is the canonical name.
    expected_dir_name = path.parent.name
    if name != expected_dir_name:
        raise ManifestError(
            f"{path}: declared name {name!r} does not match its directory "
            f"{expected_dir_name!r}"
        )

    category = data["category"]
    if category not in _VALID_CATEGORIES:
        raise ManifestError(
            f"{path}: 'category' must be one of "
            f"{list(_VALID_CATEGORIES)}, got {category!r}"
        )

    tier = data["permission_tier"]
    if not isinstance(tier, int) or tier not in _VALID_TIERS:
        raise ManifestError(
            f"{path}: 'permission_tier' must be an integer 0..5, got {tier!r}"
        )

    entry_point = str(data["entry_point"]).strip()
    if ":" not in entry_point:
        raise ManifestError(
            f"{path}: 'entry_point' must be 'module.path:attr', got {entry_point!r}"
        )

    deps_raw: Any = data.get("dependencies", [])
    if deps_raw is None:
        deps_raw = []
    if not isinstance(deps_raw, list):
        raise ManifestError(
            f"{path}: 'dependencies' must be a list, got {type(deps_raw).__name__}"
        )
    deps = tuple(str(d) for d in deps_raw)

    return SkillManifest(
        name=name,
        category=category,  # type: ignore[arg-type]
        permission_tier=int(tier),
        entry_point=entry_point,
        version=str(data.get("version", "0.0.0")),
        latency_class=str(data.get("latency_class", "fast")),
        dependencies=deps,
        description=str(data.get("description", "")).strip(),
        path=path,
    )


# --- Discovery --------------------------------------------------------------


def _skills_root(skills_package: str = "jaeger_os.instance.lilith.skills") -> pathlib.Path:
    """Resolve the on-disk directory of the skills package."""
    pkg = importlib.import_module(skills_package)
    if not hasattr(pkg, "__file__") or pkg.__file__ is None:
        raise RuntimeError(f"Cannot resolve filesystem path of {skills_package}")
    return pathlib.Path(pkg.__file__).parent


def discover_manifests(
    skills_package: str = "jaeger_os.instance.lilith.skills",
) -> Iterator[SkillManifest]:
    """Yield every valid manifest under the skills package, in stable order.

    Manifest files that fail validation cause :class:`ManifestError` to
    bubble — discovery is *strict* by design (master prompt acceptance
    criterion: a skill missing a permission tier fails to load with a
    clear error).
    """
    root = _skills_root(skills_package)
    # Sorted for deterministic order; tests rely on it.
    for manifest_path in sorted(root.rglob("manifest.yaml")):
        yield load_manifest(manifest_path)


# --- Registry ---------------------------------------------------------------


@dataclass
class Registry:
    """Holds the manifests Lilith picked up at startup, plus their loaders.

    ``Registry`` is intentionally simple: a list of validated manifests,
    plus an on-demand cache of imported entry-point objects. The
    launcher will hand the registry to Hermes; Hermes will iterate
    ``manifests`` and spawn each skill's MCP server.

    Attributes:
        environment: ``"desktop"`` or ``"robot"``. Determines whether
            physical skills are loaded.
        manifests: All manifests admitted under the current environment.
            Cognitive skills are always present; physical skills appear
            only when ``environment == "robot"``.
    """

    environment: str
    manifests: tuple[SkillManifest, ...]
    _entry_points: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def discover(
        cls,
        environment: str,
        *,
        skills_package: str = "jaeger_os.instance.lilith.skills",
    ) -> "Registry":
        """Walk the skills tree, validate manifests, filter by environment."""
        admitted: list[SkillManifest] = []
        for manifest in discover_manifests(skills_package):
            if manifest.category == "physical" and environment != "robot":
                # Physical skills only load when there's a body.
                continue
            admitted.append(manifest)
        return cls(environment=environment, manifests=tuple(admitted))

    # ---- queries ----------------------------------------------------------

    def by_category(self, category: SkillCategory) -> tuple[SkillManifest, ...]:
        return tuple(m for m in self.manifests if m.category == category)

    def names(self) -> tuple[str, ...]:
        return tuple(m.name for m in self.manifests)

    def get(self, name: str) -> SkillManifest:
        for manifest in self.manifests:
            if manifest.name == name:
                return manifest
        raise KeyError(f"No skill named {name!r} in registry")

    # ---- loading ----------------------------------------------------------

    def load(self, name: str) -> Any:
        """Resolve and return the entry-point object for skill ``name``.

        Imports the module on the first call and caches the resolved
        attribute. Subsequent calls return the cached object.
        """
        if name in self._entry_points:
            return self._entry_points[name]
        manifest = self.get(name)
        module_path, _, attr = manifest.entry_point.partition(":")
        module = importlib.import_module(module_path)
        if not hasattr(module, attr):
            raise ManifestError(
                f"Skill {name!r} entry_point {manifest.entry_point!r} "
                f"resolves to {module_path} but it has no attribute {attr!r}"
            )
        resolved = getattr(module, attr)
        self._entry_points[name] = resolved
        return resolved

    def __iter__(self) -> Iterator[SkillManifest]:
        return iter(self.manifests)

    def __len__(self) -> int:
        return len(self.manifests)

    def __contains__(self, name: object) -> bool:
        return any(m.name == name for m in self.manifests)


def filter_by_environment(
    manifests: Iterable[SkillManifest],
    environment: str,
) -> tuple[SkillManifest, ...]:
    """Apply the environment filter manually (for tests / introspection)."""
    if environment == "robot":
        return tuple(manifests)
    return tuple(m for m in manifests if m.category != "physical")


__all__ = [
    "ManifestError",
    "Registry",
    "SkillCategory",
    "SkillManifest",
    "discover_manifests",
    "filter_by_environment",
    "load_manifest",
]
