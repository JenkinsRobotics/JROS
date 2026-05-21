"""Playbook skills — markdown skill definitions the agent reads on demand.

A skill is a folder under ``skills/`` with a ``SKILL.md``: YAML
frontmatter (name, description, tags) + a markdown body of instructions.
Skills are *dynamic* — some are pure playbooks, many carry embedded
shell/Python or a ``scripts/`` folder. The agent discovers them
(``skill`` tool: list / search) and reads one (view) to follow it,
running whatever it contains with its normal tools.

Separate from :mod:`skill_loader` — that imports Python *code* skills
that register tools. A playbook skill registers no tools; it is
knowledge + procedure the agent executes with `terminal` / `execute_code`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# skills/ sits at the package root:  core/ → jaeger_os/ → skills/
_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

# JROS code skills are named "<name>_v<N>" and carry a Python module —
# skill_loader.py owns those; they are not playbooks.
_VERSIONED = re.compile(r"_v\d+$")


@dataclass
class PlaybookSkill:
    name: str
    category: str
    description: str
    path: Path                       # the SKILL.md file
    tags: list[str] = field(default_factory=list)


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Parse a leading ``---`` YAML frontmatter block. ``{}`` if absent."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        import yaml
        data = yaml.safe_load(text[3:end])
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _is_code_skill(folder: Path) -> bool:
    """True for a JROS Python tool-registering skill (skill_loader's job)."""
    if _VERSIONED.search(folder.name):
        return True
    try:
        return any(p.suffix == ".py" for p in folder.iterdir() if p.is_file())
    except OSError:
        return False


def _tags_of(fm: dict[str, Any]) -> list[str]:
    meta = fm.get("metadata")
    if isinstance(meta, dict):
        hermes = meta.get("hermes")
        if isinstance(hermes, dict) and isinstance(hermes.get("tags"), list):
            return [str(t) for t in hermes["tags"]]
    if isinstance(fm.get("tags"), list):
        return [str(t) for t in fm["tags"]]
    return []


def discover_playbooks() -> list[PlaybookSkill]:
    """Every playbook skill under ``skills/`` (recursive), sorted by name."""
    out: list[PlaybookSkill] = []
    if not _SKILLS_DIR.is_dir():
        return out
    for md in _SKILLS_DIR.rglob("SKILL.md"):
        folder = md.parent
        if _is_code_skill(folder):
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = _parse_frontmatter(text)
        try:
            rel = folder.relative_to(_SKILLS_DIR)
            category = rel.parts[0] if len(rel.parts) > 1 else "general"
        except ValueError:
            category = "general"
        out.append(PlaybookSkill(
            name=str(fm.get("name") or folder.name),
            category=category,
            description=str(fm.get("description") or "").strip(),
            path=md,
            tags=_tags_of(fm),
        ))
    return sorted(out, key=lambda s: (s.category, s.name))


def find_playbook(name: str) -> PlaybookSkill | None:
    """Resolve a playbook by exact then substring name match."""
    needle = (name or "").strip().lower()
    if not needle:
        return None
    skills = discover_playbooks()
    for s in skills:
        if s.name.lower() == needle:
            return s
    for s in skills:
        if needle in s.name.lower():
            return s
    return None
