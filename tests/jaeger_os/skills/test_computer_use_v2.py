"""computer_use_v2 — the self-verifying, LLM-looping rebuild.

Covers the pure logic the skill's reliability rests on: accessibility-
tree parsing, element matching, controller-reply parsing, action
dispatch, and the run_goal guards. The action tools + the LLM loop need
a live desktop + model, so they are exercised only through their
non-OS-touching guard paths.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "src" / "jaeger_os" / "skills" / "computer_use_v2" / "computer_use.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("computer_use_v2_mod", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cu = _load()


_SCREEN = cu._parse_screen(
    "app: Calculator\nwindow: Calculator\n"
    "AXButton ||| 5 ||| ||| ||| 10 ||| 20 ||| 40 ||| 40\n"
    "AXButton ||| + ||| add ||| ||| 60 ||| 20 ||| 40 ||| 40\n"
    "AXStaticText ||| ||| result display ||| 0 ||| 5 ||| 0 ||| 200 ||| 30\n"
)


# ── parsing ──────────────────────────────────────────────────────────


def test_parse_screen_app_and_count() -> None:
    assert _SCREEN["app"] == "Calculator"
    assert _SCREEN["count"] == 3


def test_parse_screen_centre_point() -> None:
    five = _SCREEN["elements"][0]
    assert five["name"] == "5"
    assert five["x"] == 30 and five["y"] == 40  # centre of (10,20)+(40,40)


def test_parse_screen_captures_value() -> None:
    # the display element carries an AX value of "0"
    display = _SCREEN["elements"][2]
    assert display["value"] == "0"


# ── window awareness (the whole desktop, not just the front window) ──


def test_parse_windows_groups_apps_and_marks_frontmost() -> None:
    apps = cu._parse_windows(
        "APP ||| Code ||| yes\n"
        "WIN ||| Code ||| computer_use.py\n"
        "APP ||| Safari ||| no\n"
        "WIN ||| Safari ||| YouTube - Home\n"
        "WIN ||| Safari ||| News\n"
    )
    by = {a["app"]: a for a in apps}
    assert by["Code"]["frontmost"] is True
    assert by["Safari"]["frontmost"] is False
    assert by["Safari"]["windows"] == ["YouTube - Home", "News"]


def test_format_windows_flags_the_frontmost_app() -> None:
    rendered = cu._format_windows([
        {"app": "Code", "frontmost": True, "windows": ["a.py"]},
        {"app": "Safari", "frontmost": False, "windows": ["YouTube"]},
    ])
    assert "Code" in rendered and "[FRONTMOST]" in rendered
    assert "Safari" in rendered and "YouTube" in rendered


# ── element matching ─────────────────────────────────────────────────


def test_find_element_exact_name() -> None:
    el, _ = cu._find_element(_SCREEN["elements"], "5")
    assert el is not None and el["name"] == "5"


def test_find_element_by_description() -> None:
    el, _ = cu._find_element(_SCREEN["elements"], "add")
    assert el is not None and el["name"] == "+"


def test_find_element_miss_returns_candidates() -> None:
    el, candidates = cu._find_element(_SCREEN["elements"], "nonexistent")
    assert el is None
    assert "5" in candidates and "+" in candidates


# ── controller-reply parsing ─────────────────────────────────────────


def test_parse_action_from_prose() -> None:
    act = cu._parse_action('I will click five.\n{"action": "click", "target": "5"}')
    assert act["action"] == "click" and act["target"] == "5"


def test_parse_action_last_valid_wins() -> None:
    act = cu._parse_action(
        '{"action": "click", "target": "5"} ... {"action": "done", "result": "10"}'
    )
    assert act["action"] == "done"


def test_parse_action_no_json_is_clean_error() -> None:
    act = cu._parse_action("not sure what to do")
    assert act["action"] is None and "error" in act


# ── action dispatch ──────────────────────────────────────────────────


def test_execute_unknown_action_fails_cleanly() -> None:
    res = cu._execute_action({"action": "teleport"})
    assert res["ok"] is False and "unknown" in res["error"]


def test_execute_click_empty_target_is_guarded() -> None:
    # dispatch → click("") → guarded before any OS interaction
    res = cu._execute_action({"action": "click", "target": ""})
    assert res["ok"] is False and "target" in res["error"]


# ── run_goal guards ──────────────────────────────────────────────────


def test_run_goal_requires_a_goal() -> None:
    res = cu.run_goal("", client=object())
    assert res["ok"] is False and "goal" in res["error"]


def test_run_goal_requires_a_client() -> None:
    res = cu.run_goal("do a thing", client=None)
    assert res["ok"] is False and "client" in res["error"]


# ── registration ─────────────────────────────────────────────────────


def test_register_attaches_all_tools() -> None:
    attached: list[str] = []

    class _FakeAgent:
        def tool_plain(self, fn):
            attached.append(fn.__name__)
            return fn

    cu.register(_FakeAgent())
    for name in ("computer_do", "computer_look", "computer_windows",
                 "computer_open", "computer_click", "computer_type",
                 "computer_key", "computer_menu", "computer_screenshot"):
        assert name in attached, f"{name} not registered"
