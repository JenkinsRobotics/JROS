"""Playbook skills — discovery + the skill() tool.

The hermes skill library (markdown playbooks, often with embedded
shell/Python or a scripts/ folder) was imported into skills/. The
`skill` tool discovers and reads them ON DEMAND — they are never dumped
into the prompt, so the library can't bloat context.
"""

from __future__ import annotations

from jaeger_os.core import playbook_skills as pb
from jaeger_os.core.tools import skill


# ── discovery ────────────────────────────────────────────────────────


def test_playbooks_are_discovered() -> None:
    skills = pb.discover_playbooks()
    assert len(skills) >= 50           # 87 imported — generous floor
    assert all(s.name and s.path.name == "SKILL.md" for s in skills)


def test_code_skills_are_not_playbooks() -> None:
    # computer_use_v2 is a Python tool-registering skill — excluded.
    names = {s.name for s in pb.discover_playbooks()}
    assert "computer_use" not in names


def test_find_playbook_is_fuzzy() -> None:
    s = pb.find_playbook("codebase")
    assert s is not None and "codebase" in s.name.lower()


# ── the skill() tool ─────────────────────────────────────────────────


def test_skill_list() -> None:
    r = skill(action="list")
    assert r["ok"] is True and r["count"] >= 50


def test_skill_search_finds_by_keyword() -> None:
    r = skill(action="search", query="codebase")
    assert r["ok"] is True
    assert any("codebase" in s["name"].lower() for s in r["skills"])


def test_skill_search_needs_a_query() -> None:
    assert skill(action="search")["ok"] is False


def test_skill_view_returns_instructions() -> None:
    r = skill(action="view", name="codebase-inspection")
    assert r["ok"] is True
    assert "pygount" in r["instructions"].lower()


def test_skill_view_unknown_is_clean() -> None:
    assert skill(action="view", name="no-such-skill-xyz")["ok"] is False


def test_skill_unknown_action_is_clean() -> None:
    r = skill(action="teleport")
    assert r["ok"] is False and "unknown" in r["error"]
