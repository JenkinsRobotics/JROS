"""Benchmark for computer_use_v2 — scored evaluation of the pure logic.

The action tools and the LLM loop need a live desktop + model, which
can't be scored deterministically. What CAN be scored is the logic the
skill's reliability rests on: accessibility-tree parsing, element
matching, controller-reply parsing, action dispatch, AppleScript
escaping and key-chord resolution. This exercises exactly those.

Prints one JSON object: {score, passed, total, cases, notes}.
"""

import importlib.util
import json
import sys
from pathlib import Path


def _load():
    spec = importlib.util.spec_from_file_location(
        "computer_use",
        Path(__file__).resolve().parent.parent / "computer_use.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    mod = _load()
    cases = []

    # A small Calculator-like screen used across several cases.
    screen = mod._parse_screen(
        "app: Calculator\nwindow: Calculator\n"
        "AXButton ||| 5 ||| ||| ||| 10 ||| 20 ||| 40 ||| 40\n"
        "AXButton ||| + ||| add ||| ||| 60 ||| 20 ||| 40 ||| 40\n"
        "AXButton ||| = ||| equals ||| ||| 110 ||| 20 ||| 40 ||| 40\n"
        "AXStaticText ||| ||| result display ||| 10 ||| 0 ||| 5 ||| 200 ||| 30\n"
    )

    # 1 — parsing: app + element count.
    cases.append({"name": "parse_screen",
                  "ok": screen["app"] == "Calculator" and screen["count"] == 4})

    # 2 — parsing: centre-point geometry.
    cases.append({"name": "parse_centre_point",
                  "ok": screen["elements"][0]["x"] == 30
                  and screen["elements"][0]["y"] == 40})

    # 3 — element match: exact name.
    el, _ = mod._find_element(screen["elements"], "5")
    cases.append({"name": "match_exact_name", "ok": el is not None and el["name"] == "5"})

    # 4 — element match: by description ("add" → the + button).
    el, _ = mod._find_element(screen["elements"], "add")
    cases.append({"name": "match_by_description", "ok": el is not None and el["name"] == "+"})

    # 5 — element match: no hit returns the candidate list.
    el, cands = mod._find_element(screen["elements"], "nonexistent")
    cases.append({"name": "match_miss_lists_candidates",
                  "ok": el is None and "5" in cands and "+" in cands})

    # 6 — controller reply: action JSON extracted from prose.
    act = mod._parse_action('Reasoning here.\n{"action": "click", "target": "+"}')
    cases.append({"name": "parse_action", "ok": act.get("action") == "click"
                  and act.get("target") == "+"})

    # 7 — controller reply: the LAST valid action wins.
    act = mod._parse_action('{"action": "click", "target": "5"} then '
                            '{"action": "done", "result": "10"}')
    cases.append({"name": "parse_action_last_wins",
                  "ok": act.get("action") == "done"})

    # 8 — controller reply: no JSON → a clean error, not a crash.
    act = mod._parse_action("I am not sure what to do.")
    cases.append({"name": "parse_action_no_json", "ok": act.get("action") is None})

    # 9 — action dispatch: an unknown action fails cleanly.
    res = mod._execute_action({"action": "teleport"})
    cases.append({"name": "dispatch_unknown_action",
                  "ok": res.get("ok") is False and "unknown" in res.get("error", "")})

    # 10 — AppleScript escaping.
    cases.append({"name": "applescript_escape",
                  "ok": mod._esc('say "hi"\\n') == 'say \\"hi\\"\\\\n'})

    # 11 — key-chord resolution.
    script, err = mod._build_press_script("shift+tab")
    cases.append({"name": "key_chord",
                  "ok": err is None and "shift down" in script
                  and "key code 48" in script})

    # 12 — run_goal guards: no client → clean error, no crash.
    res = mod.run_goal("do something", client=None)
    cases.append({"name": "run_goal_no_client",
                  "ok": res.get("ok") is False and "client" in res.get("error", "")})

    # 13 — window awareness: parse the whole-desktop dump.
    apps = mod._parse_windows(
        "APP ||| Code ||| yes\nWIN ||| Code ||| main.py\n"
        "APP ||| Safari ||| no\nWIN ||| Safari ||| YouTube\n"
        "WIN ||| Safari ||| News\n"
    )
    by = {a["app"]: a for a in apps}
    cases.append({"name": "parse_windows",
                  "ok": by.get("Code", {}).get("frontmost") is True
                  and by.get("Safari", {}).get("windows") == ["YouTube", "News"]})

    passed = sum(1 for c in cases if c["ok"])
    total = len(cases)
    print(json.dumps({
        "score": round(passed / total, 3) if total else 0.0,
        "passed": passed,
        "total": total,
        "cases": cases,
        "notes": "pure-logic benchmark — parsing, matching, dispatch, "
                 "controller-reply handling, key resolution.",
    }))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
