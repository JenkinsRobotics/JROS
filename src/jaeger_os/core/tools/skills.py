"""The `skill` tool — discover and read playbook skills on demand.

A skill is an experienced playbook for a task — instructions plus, often,
runnable shell/Python or a ``scripts/`` folder. There are dozens; they
are NOT dumped into the prompt. The agent calls this tool to find the
right skill for a task, then reads it and follows it with its normal
tools (``terminal``, ``execute_code``, …). On-demand, so the skill
library never bloats context.
"""

from __future__ import annotations

from typing import Any

from .. import playbook_skills as _pb

# Cap a single skill's instructions so one huge SKILL.md can't blow the
# context window. Skills run long but rarely past this.
_MAX_SKILL_CHARS = 16_000


def skill(action: str, name: str = "", query: str = "") -> dict[str, Any]:
    """Discover and read playbook skills — experienced procedures for a
    task. ``action`` selects the operation:

      - ``list``   — every available skill (name · category · one-liner).
      - ``search`` — skills matching ``query`` (name / description /
        tags / category). Use this FIRST when a task might have a skill.
      - ``view``   — the full instructions of skill ``name``. Read them,
        then carry them out with your normal tools. A skill may contain
        shell/Python to run or reference files in its folder.

    Reach for a skill when a task is non-trivial and specialized
    ("inspect a codebase", "make an ascii-art banner", "search arxiv")."""
    act = (action or "").strip().lower()

    if act in ("list", "all", ""):
        skills = _pb.discover_playbooks()
        return {
            "ok": True, "count": len(skills),
            "skills": [{"name": s.name, "category": s.category,
                        "description": s.description} for s in skills],
        }

    if act in ("search", "find"):
        q = (query or name).strip().lower()
        if not q:
            return {"ok": False, "error": "search needs a query"}
        hits = []
        for s in _pb.discover_playbooks():
            hay = (f"{s.name} {s.description} {s.category} "
                   f"{' '.join(s.tags)}").lower()
            if all(term in hay for term in q.split()):
                hits.append({"name": s.name, "category": s.category,
                             "description": s.description})
        return {"ok": True, "count": len(hits), "query": q, "skills": hits}

    if act in ("view", "use", "read", "get", "open"):
        target = name or query
        s = _pb.find_playbook(target)
        if s is None:
            return {"ok": False,
                    "error": f"no skill matching {target!r} — "
                             "try action='list' or action='search'"}
        try:
            content = s.path.read_text(encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": f"couldn't read skill: {exc}"}
        return {
            "ok": True, "name": s.name, "category": s.category,
            "instructions": content[:_MAX_SKILL_CHARS],
            "truncated": len(content) > _MAX_SKILL_CHARS,
            "folder": str(s.path.parent),
        }

    return {"ok": False,
            "error": f"unknown skill action {action!r} — "
                     "use list / search / view"}
