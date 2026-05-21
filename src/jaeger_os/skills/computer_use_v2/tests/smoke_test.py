"""Smoke test for computer_use_v2.

Runs as a subprocess from the skill loader before registration. Loads the
module standalone and checks it is healthy — it does NOT run AppleScript
(no clicking the user's screen, no LLM loop, no permission needs), so it
passes on any host. The action tools self-check the platform at call time.
"""

import importlib.util
import sys
from pathlib import Path


def main() -> int:
    spec = importlib.util.spec_from_file_location(
        "computer_use",
        Path(__file__).resolve().parent.parent / "computer_use.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Primitive functions, the orchestrator, and register() are present.
    for fn in ("look", "list_windows", "open_app", "click", "type_text",
               "press_key", "menu_select", "screenshot", "run_goal",
               "register"):
        assert callable(getattr(mod, fn, None)), f"missing {fn}"

    # Pure helper — parse the all-windows dump (whole-desktop awareness).
    apps = mod._parse_windows(
        "APP ||| Code ||| yes\nWIN ||| Code ||| main.py\n"
        "APP ||| Safari ||| no\nWIN ||| Safari ||| YouTube\n"
    )
    assert len(apps) == 2 and apps[0]["frontmost"] is True, apps
    assert apps[1]["app"] == "Safari" and apps[1]["windows"] == ["YouTube"], apps

    # Pure helper — AppleScript string escaping.
    assert mod._esc('a"b\\c') == 'a\\"b\\\\c', mod._esc('a"b\\c')

    # Pure helper — parse a read_screen dump (8 fields incl. value).
    parsed = mod._parse_screen(
        "app: Calculator\nwindow: Calculator\n"
        "AXButton ||| 5 ||| ||| ||| 10 ||| 20 ||| 40 ||| 40\n"
        "AXStaticText ||| display ||| ||| 0 ||| 5 ||| 5 ||| 200 ||| 30\n"
    )
    assert parsed["app"] == "Calculator", parsed
    assert parsed["count"] == 2, parsed
    five = parsed["elements"][0]
    assert five["name"] == "5" and five["x"] == 30 and five["y"] == 40, five

    # Pure helper — element matching finds the button literally named "5".
    el, _cands = mod._find_element(parsed["elements"], "5")
    assert el is not None and el["name"] == "5", el

    # Pure helper — pull the action JSON out of a controller reply.
    act = mod._parse_action(
        'I should click the five key.\n{"action": "click", "target": "5"}'
    )
    assert act["action"] == "click" and act["target"] == "5", act

    # Pure helper — key-chord resolution.
    script, err = mod._build_press_script("cmd+c")
    assert err is None and "command down" in script, (script, err)

    print("computer_use_v2 smoke OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
