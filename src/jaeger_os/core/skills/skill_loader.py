"""Skill discovery and resolution.

A *skill* is a self-contained directory:

    skills/<name>_v<N>/
        SKILL.md            # When + how to use this skill
        <python module>     # Implementation
        tests/
            smoke_test.py   # Decides whether the skill is safe to register

The loader scans two zones:

  1. Core skills        — jaeger_os/skills/   (read-only, shipped with the framework)
  2. Instance skills    — <instance_dir>/skills/  (agent-writable, per-instance)

Resolution rules:

  - On name collision, **instance wins over core**.
  - Within a zone, the highest `_v<N>` suffix wins.
  - A skill whose smoke test fails is *skipped*, not registered, and the
    failure goes into logs/audit.log so the human can see why.

Skill modules are imported via importlib and are expected to expose a
top-level callable named `register(agent)` that registers one or more
PydanticAI tools onto the agent. The loader never imports a `.py` from
outside the two zones — the path is computed from the discovered folder.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from jaeger_os.core.instance.instance import InstanceLayout


# Core skills shipped with the framework. Was `base_skills/` before the
# M3.5 rename; the new name matches `<instance_dir>/skills/` for symmetry
# (same word, different zone).
# core/skills/ lives two levels deeper than the framework root, so reach up two.
CORE_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"


_SKILL_RE = re.compile(r"^(?P<name>[A-Za-z][A-Za-z0-9_]*)_v(?P<v>\d+)$")


@dataclass(frozen=True)
class DiscoveredSkill:
    name: str
    version: int
    zone: str            # "core" or "instance"
    folder: Path
    module_path: Path    # the .py file we'll import
    has_smoke: bool


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def _scan_zone(root: Path, zone: str) -> list[DiscoveredSkill]:
    found: list[DiscoveredSkill] = []
    if not root.exists():
        return found
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        m = _SKILL_RE.match(child.name)
        if not m:
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.exists():
            # A folder that looks like a skill but is missing SKILL.md is a
            # half-finished thing — skip silently.
            continue
        module = _pick_module_file(child)
        if module is None:
            continue
        found.append(DiscoveredSkill(
            name=m.group("name"),
            version=int(m.group("v")),
            zone=zone,
            folder=child,
            module_path=module,
            has_smoke=(child / "tests" / "smoke_test.py").exists(),
        ))
    return found


def _pick_module_file(folder: Path) -> Path | None:
    """A skill folder may contain multiple files; the import target is
    one of (in order): <name without version>.py, skill.py, __init__.py.
    If none exist, the skill isn't importable and is skipped."""
    base = _SKILL_RE.match(folder.name)
    candidates: list[Path] = []
    if base:
        candidates.append(folder / f"{base.group('name')}.py")
    candidates.append(folder / "skill.py")
    candidates.append(folder / "__init__.py")
    for c in candidates:
        if c.exists():
            return c
    return None


def discover_skills(layout: InstanceLayout) -> list[DiscoveredSkill]:
    """Return the resolved skill set: highest-version-per-name, instance
    winning over core on name collision."""
    core = _scan_zone(CORE_SKILLS_DIR, "core")
    instance = _scan_zone(layout.skills_dir, "instance")

    # Pick highest version per (zone, name) first.
    def best_in(seq: Iterable[DiscoveredSkill]) -> dict[str, DiscoveredSkill]:
        out: dict[str, DiscoveredSkill] = {}
        for s in seq:
            cur = out.get(s.name)
            if cur is None or s.version > cur.version:
                out[s.name] = s
        return out

    core_best = best_in(core)
    instance_best = best_in(instance)
    # Instance wins on collision.
    merged = {**core_best, **instance_best}
    return sorted(merged.values(), key=lambda s: (s.zone != "instance", s.name))


# ---------------------------------------------------------------------------
# Smoke test gating
# ---------------------------------------------------------------------------
def _run_smoke(skill: DiscoveredSkill, timeout_s: float = 10.0) -> tuple[bool, str]:
    test = skill.folder / "tests" / "smoke_test.py"
    if not test.exists():
        return True, ""  # no test → trust by default (M2 will require trusted tests)
    try:
        proc = subprocess.run(
            [sys.executable, str(test)],
            capture_output=True, text=True, timeout=timeout_s,
            cwd=str(skill.folder),
        )
    except subprocess.TimeoutExpired:
        return False, f"smoke test timed out after {timeout_s}s"
    except Exception as exc:
        return False, f"smoke test couldn't run: {exc}"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-2000:]
        return False, f"smoke test exit={proc.returncode}\n{tail}"
    return True, ""


# ---------------------------------------------------------------------------
# Import + registration
# ---------------------------------------------------------------------------
def _import_skill(skill: DiscoveredSkill) -> Any:
    mod_name = f"_jaeger_skill_{skill.zone}_{skill.name}_v{skill.version}"
    spec = importlib.util.spec_from_file_location(mod_name, skill.module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not build import spec for {skill.module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class SkillLoadReport:
    registered: list[DiscoveredSkill]
    skipped: list[tuple[DiscoveredSkill, str]]


_REGISTERED_KEYS: set[tuple[str, int, str]] = set()


def reset_registered() -> None:
    """Drop the loader's idempotency cache. Used by tests that bind/unbind
    an instance several times without restarting the process."""
    _REGISTERED_KEYS.clear()


class _ToolCapturingAgent:
    """Wraps the agent during a skill's ``register()`` so we record
    exactly which tools the skill adds — that captured set IS the
    skill's toolset (a skill is a self-describing bundle of tools).
    Every other attribute passes straight through to the real agent.

    Phase-6.2 cutover: ``tool_plain`` and ``tool`` no longer write to
    the pydantic-ai agent — they write into
    :mod:`jaeger_os.agent.schemas.tool_registry` via
    :func:`register_tool_from_function`. The wrapped ``self._agent`` is
    still used for non-tool attribute pass-through (skill code that
    reads ``agent.model``, etc.). The skill source stays unchanged —
    ``@agent.tool_plain`` still does the right thing, just into the
    new registry."""

    def __init__(self, agent: Any) -> None:
        self._agent = agent
        self.captured: list[str] = []

    def _register(
        self, fn: Callable[..., Any], **kwargs: Any,
    ) -> Callable[..., Any]:
        """Lift one skill function into the framework-free registry.
        Captures the name so the skill becomes its own named toolset."""
        from jaeger_os.agent.schemas.tool_registry import register_tool_from_function
        name = getattr(fn, "__name__", None)
        if name:
            self.captured.append(name)
        # ``register_tool_from_function`` synthesizes the args model from
        # the function signature — works for the vast majority of skill
        # tools, which use plain type hints. Skills that need a custom
        # args model can call ``register_tool_instance`` directly.
        register_tool_from_function(fn, **kwargs)
        return fn

    def _wrap(self, _legacy_real: Callable[..., Any] | None) -> Callable[..., Any]:
        def deco(*args: Any, **kwargs: Any) -> Any:
            # Bare-decorator form: @agent.tool_plain  → args == (fn,)
            if len(args) == 1 and not kwargs and callable(args[0]):
                return self._register(args[0])
            # Parametrised form: @agent.tool_plain(retries=…) returns a
            # decorator. Honour the kwargs that map to our decorator's
            # surface (``name`` / ``description``); silently drop the
            # pydantic-ai-specific knobs (``retries``) since the new
            # loop owns retry semantics.
            our_kwargs: dict[str, Any] = {}
            for k in ("name", "description"):
                if k in kwargs:
                    our_kwargs[k] = kwargs[k]
            def capture_parametrized(fn: Callable[..., Any]) -> Any:
                return self._register(fn, **our_kwargs)
            return capture_parametrized
        return deco

    @property
    def tool_plain(self) -> Callable[..., Any]:
        return self._wrap(None)

    @property
    def tool(self) -> Callable[..., Any]:
        return self._wrap(None)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._agent, name)


def _skill_summary(skill: DiscoveredSkill) -> str:
    """One-line summary for the toolset catalog — the SKILL.md
    ``description:`` field, else a generic fallback."""
    try:
        md = (skill.module_path.parent / "SKILL.md").read_text(encoding="utf-8")
    except Exception:
        return f"the {skill.name} skill"
    for line in md.splitlines():
        if line.strip().lower().startswith("description:"):
            desc = line.split(":", 1)[1].strip()
            if desc:
                return desc
    return f"the {skill.name} skill"


def load_and_register(
    agent: Any,
    layout: InstanceLayout,
    *,
    run_smoke_tests: bool = True,
    enabled_allowlist: list[str] | None = None,
    audit: Callable[[str, dict[str, Any]], None] | None = None,
) -> SkillLoadReport:
    """Discover skills, gate on smoke tests, register passers onto the agent.

    `enabled_allowlist` (from config.skills.enabled_base_skills) filters
    *core* skills only — instance skills are always considered. Empty list
    or None disables the filter.
    `audit` is the audit-log callback (so skips are visible in logs/audit.log).
    """
    registered: list[DiscoveredSkill] = []
    skipped: list[tuple[DiscoveredSkill, str]] = []

    for skill in discover_skills(layout):
        key = (skill.name, skill.version, skill.zone)
        if key in _REGISTERED_KEYS:
            # Already wired during a prior call — skipping is the correct
            # behavior for hot-reload (pydantic-ai's @tool_plain raises if
            # we try to register the same name twice).
            continue

        if (
            skill.zone == "core"
            and enabled_allowlist
            and skill.name not in enabled_allowlist
        ):
            skipped.append((skill, "disabled by config"))
            if audit:
                audit("skill_skip", {"skill": skill.name, "version": skill.version,
                                     "zone": skill.zone, "reason": "disabled_by_config"})
            continue

        if run_smoke_tests and skill.has_smoke:
            ok, msg = _run_smoke(skill)
            if not ok:
                skipped.append((skill, msg))
                if audit:
                    audit("skill_smoke_fail", {"skill": skill.name, "version": skill.version,
                                                "zone": skill.zone, "error": msg[:500]})
                print(f"[jaeger-skills] {skill.name}_v{skill.version} ({skill.zone}) skipped: smoke test failed.",
                      flush=True)
                continue

        # Safety scan — a static content scan (exfiltration, prompt
        # injection, destructive commands, embedded secrets). A `danger`
        # verdict blocks an instance-zone skill before its Python is
        # imported; a core/shipped skill is only warned about.
        try:
            from jaeger_os.core.safety.skills_guard import scan_skill
            scan = scan_skill(skill.folder, name=skill.name)
        except Exception:  # noqa: BLE001
            scan = None
        if scan is not None and scan.is_danger:
            if audit:
                audit("skill_guard_flag", {
                    "skill": skill.name, "version": skill.version,
                    "zone": skill.zone, "verdict": scan.verdict,
                    "findings": len(scan.findings),
                })
            if skill.zone != "core":
                skipped.append((skill, f"safety scan: {scan.verdict}"))
                print(f"[jaeger-skills] {skill.name}_v{skill.version} "
                      f"({skill.zone}) skipped: safety scan flagged "
                      f"{len(scan.findings)} issue(s).", flush=True)
                continue
            print(f"[jaeger-skills] WARNING: core skill {skill.name} "
                  f"tripped the safety scan ({len(scan.findings)} "
                  "finding(s)) — loading anyway (shipped/trusted).",
                  flush=True)

        try:
            module = _import_skill(skill)
            register = getattr(module, "register", None)
            if register is None:
                skipped.append((skill, "no register(agent) callable"))
                continue
            # Register through a capturing wrapper so the skill's tools
            # become its own named toolset (a skill IS a toolset).
            capturing = _ToolCapturingAgent(agent)
            register(capturing)
            if capturing.captured:
                try:
                    from jaeger_os.core.skills.toolsets import register_skill_toolset
                    register_skill_toolset(skill.name, capturing.captured,
                                           summary=_skill_summary(skill))
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:
            tb = traceback.format_exc(limit=4)
            skipped.append((skill, f"import/register failed: {exc}\n{tb}"))
            if audit:
                audit("skill_register_fail", {"skill": skill.name, "version": skill.version,
                                              "zone": skill.zone, "error": str(exc)})
            print(f"[jaeger-skills] {skill.name}_v{skill.version} ({skill.zone}) skipped: {exc}",
                  flush=True)
            continue

        registered.append(skill)
        _REGISTERED_KEYS.add(key)
        if audit:
            audit("skill_registered", {"skill": skill.name, "version": skill.version,
                                        "zone": skill.zone})

    if registered:
        names = ", ".join(f"{s.name}_v{s.version}({s.zone})" for s in registered)
        print(f"[jaeger-skills] registered {len(registered)} tool-skill(s): {names}", flush=True)
    # Playbook skills (procedural SKILL.md docs the agent reads on
    # demand via the ``skill`` tool) live alongside the tool-skills but
    # are NOT registered as agent tools — they get discovered + indexed
    # separately. Mention the count here so the operator sees the full
    # surface, not just the Python-module slice.
    try:
        from jaeger_os.core.skills.playbook_skills import discover_playbooks
        pb_count = len(discover_playbooks())
        if pb_count:
            print(f"[jaeger-skills] {pb_count} playbook skill(s) available "
                  f"via the ``skill`` tool (action=list/view).", flush=True)
    except Exception:  # noqa: BLE001 — playbook discovery must not block boot
        pass
    return SkillLoadReport(registered=registered, skipped=skipped)
