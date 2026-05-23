"""The `skill` tool — discover and read playbook skills on demand.

A skill is an experienced playbook for a task — instructions plus, often,
runnable shell/Python or a ``scripts/`` folder. There are dozens; they
are NOT dumped into the prompt. The agent calls this tool to find the
right skill for a task, then reads it and follows it with its normal
tools (``terminal``, ``execute_code``, …). On-demand, so the skill
library never bloats context.
"""

from __future__ import annotations

import pathlib
from typing import Any

from .. import playbook_skills as _pb

# Cap a single skill's instructions so one huge SKILL.md can't blow the
# context window. Skills run long but rarely past this.
_MAX_SKILL_CHARS = 16_000

# Recognised linked-file categories inside a skill folder.
_FILE_CATEGORIES = ("scripts", "references", "templates", "assets")


def _bucket_skill_files(folder: pathlib.Path) -> dict[str, list[str]]:
    """List a skill folder's bundled files (everything but SKILL.md),
    bucketed by category — so the model knows what scripts / references
    a skill carries without guessing filenames."""
    buckets: dict[str, list[str]] = {}
    try:
        for p in sorted(folder.rglob("*")):
            if not p.is_file() or p.name == "SKILL.md":
                continue
            if any(part.startswith(".") for part in p.relative_to(folder).parts):
                continue
            rel = str(p.relative_to(folder))
            top = rel.split("/", 1)[0] if "/" in rel else ""
            cat = top if top in _FILE_CATEGORIES else "other"
            buckets.setdefault(cat, []).append(rel)
    except Exception:  # noqa: BLE001
        pass
    return buckets


def _read_skill_file(folder: pathlib.Path, relpath: str) -> dict[str, Any]:
    """Read one file from a skill folder, sandbox-checked against it."""
    rel = pathlib.Path(relpath)
    if rel.is_absolute() or any(part == ".." for part in rel.parts):
        return {"ok": False, "error": "file must be a relative path, no '..'"}
    folder = folder.resolve()
    target = (folder / rel).resolve()
    try:
        target.relative_to(folder)
    except ValueError:
        return {"ok": False, "error": "file escapes the skill folder"}
    if not target.is_file():
        return {"ok": False, "error": f"no such file in the skill: {relpath}"}
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {"ok": False, "error": f"couldn't read {relpath}: {exc}"}
    return {"ok": True, "file": relpath,
            "content": text[:_MAX_SKILL_CHARS],
            "truncated": len(text) > _MAX_SKILL_CHARS}


def skill(action: str, name: str = "", query: str = "",
          file: str = "") -> dict[str, Any]:
    """Discover and read playbook skills — experienced procedures for a
    task. ``action`` selects the operation:

      - ``list``   — every available skill (name · category · one-liner).
      - ``search`` — skills matching ``query`` (name / description /
        tags / category). Use this FIRST when a task might have a skill.
      - ``view``   — the full instructions of skill ``name``, plus a
        ``files`` listing of its bundled scripts / references. Pass
        ``file="scripts/foo.py"`` to read one of those bundled files.
      - ``stats``  — usage telemetry: which tools and skills get used.
      - ``curate`` — assess the skill library: which agent-authored
        skills have gone stale. Read-only — reports, archives nothing.

    Reach for a skill when a task is non-trivial and specialized
    ("inspect a codebase", "make an ascii-art banner", "search arxiv")."""
    act = (action or "").strip().lower()

    if act in ("stats", "usage"):
        from ..usage_stats import top_skills, top_tools
        return {"ok": True, "tools": top_tools(12), "skills": top_skills(12)}

    if act in ("curate", "curation", "cleanup"):
        # Read-only dry run — surfaces stale / unused agent-authored
        # skills. Archiving is a deliberate, separate step (curator A2).
        from ..curator import run_curation
        return run_curation(apply=False)

    if act in ("list", "all", ""):
        skills = _pb.available_playbooks()
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
        for s in _pb.available_playbooks():
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
        folder = s.path.parent
        # `file` given → return that bundled file's contents directly.
        if file:
            return {"name": s.name, **_read_skill_file(folder, file)}
        try:
            content = s.path.read_text(encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": f"couldn't read skill: {exc}"}
        # Expand {{date}} / {{instance_name}} / {{skill_folder}} … template
        # placeholders before the model sees the body (audit A6).
        try:
            from ..skill_preprocessing import preprocess_skill
            content = preprocess_skill(
                content, skill_name=s.name, skill_folder=folder)
        except Exception:  # noqa: BLE001 — never let preprocessing break view
            pass
        try:
            from ..usage_stats import record_skill
            record_skill(s.name)
        except Exception:  # noqa: BLE001
            pass
        result = {
            "ok": True, "name": s.name, "category": s.category,
            "origin": s.origin,
            "instructions": content[:_MAX_SKILL_CHARS],
            "truncated": len(content) > _MAX_SKILL_CHARS,
            "folder": str(folder),
            "files": _bucket_skill_files(folder),
        }
        # Advisory prerequisites — surfaced only when declared so the model
        # knows what to load (a toolset) or fall back from before following.
        if s.platforms:
            result["platforms"] = s.platforms
        if s.requires_tools:
            result["requires_tools"] = s.requires_tools
        if s.requires_toolsets:
            result["requires_toolsets"] = s.requires_toolsets
        if s.fallback_for_tools:
            result["fallback_for_tools"] = s.fallback_for_tools
        # Safety scan — a playbook is markdown the model is told to run.
        # Surface a warning so the model treats a flagged skill with
        # care; never blocks the read (the model still needs to see it).
        try:
            from ..skills_guard import scan_skill
            scan = scan_skill(s.path.parent, name=s.name)
            if not scan.is_clean:
                result["safety"] = scan.verdict
            if scan.is_danger:
                # Only a danger verdict gets a prominent warning — a
                # caution is recorded quietly so the model isn't
                # desensitised by frequent low-signal notices.
                result["safety_warning"] = (
                    f"⚠ This skill tripped the safety scanner as "
                    f"DANGER ({len(scan.findings)} finding(s)) — it "
                    "contains patterns like exfiltration, reverse "
                    "shells, or destructive commands. Review every "
                    "command before running it; do not blindly execute."
                )
        except Exception:  # noqa: BLE001
            pass
        return result

    return {"ok": False,
            "error": f"unknown skill action {action!r} — "
                     "use list / search / view"}
