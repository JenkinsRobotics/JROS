"""macOS background-automation engine — the graceful-degradation contract.

`computer_use_v2/macos_background.py` drives the Mac via the Accessibility
API. The live AX behaviour can only be verified on a real macOS GUI
session with Accessibility granted — but the *contract* that matters here
is env-independent: **every entry point returns a well-formed
`{ok: bool, ...}` dict and never raises**, whether or not PyObjC is
installed, the host is trusted, or the target app exists.

The skill folder is not on `sys.path` (skill_loader loads modules by
path), so the module is loaded the same way here.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

_MOD_PATH = (
    pathlib.Path(__file__).resolve().parents[3]
    / "src/jaeger_os/skills/computer_use_v2/macos_background.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("_mb_test", _MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mb = _load()


# ── module shape ────────────────────────────────────────────────────


def test_module_loads_and_exports_the_engine():
    for name in ("is_available", "list_running_apps", "list_windows",
                 "move_window", "resize_window", "press_element",
                 "run_background_browser_js"):
        assert name in mb.__all__, name
        assert callable(getattr(mb, name)), name


def test_is_available_returns_a_bool_and_a_reason():
    ready, detail = mb.is_available()
    assert isinstance(ready, bool)
    assert isinstance(detail, str) and detail


# ── every entry point degrades gracefully ───────────────────────────
# These hold whether or not PyObjC / Accessibility / the app are present:
# the result is always a dict with `ok`, and nothing raises.


def test_list_running_apps_returns_a_dict():
    out = mb.list_running_apps()
    assert isinstance(out, dict) and "ok" in out


def test_list_windows_unknown_app_fails_clean():
    out = mb.list_windows("NoSuchApp_ZZ_12345")
    assert out["ok"] is False
    assert "error" in out


def test_move_window_unknown_app_fails_clean():
    out = mb.move_window("NoSuchApp_ZZ_12345", 10, 20)
    assert isinstance(out, dict) and out["ok"] is False


def test_resize_window_unknown_app_fails_clean():
    out = mb.resize_window("NoSuchApp_ZZ_12345", 800, 600)
    assert isinstance(out, dict) and out["ok"] is False


def test_press_element_unknown_app_fails_clean():
    out = mb.press_element("NoSuchApp_ZZ_12345", "Some Button")
    assert isinstance(out, dict) and out["ok"] is False


# ── browser JS — deterministic, no AX permission needed ─────────────


def test_browser_js_rejects_empty_script():
    out = mb.run_background_browser_js("")
    assert out["ok"] is False
    assert "JavaScript" in out["error"]


def test_browser_js_unknown_browser_fails_clean():
    out = mb.run_background_browser_js(
        "document.title;", browser="NoSuchBrowser_ZZ")
    assert isinstance(out, dict) and out["ok"] is False


def test_browser_js_with_quotes_and_backslashes_does_not_crash():
    """The JS → AppleScript escaping must not raise on a script that
    itself contains quotes and backslashes."""
    tricky = r'document.querySelector(".x").title = "a\"b\\c";'
    out = mb.run_background_browser_js(tricky, browser="NoSuchBrowser_ZZ")
    assert isinstance(out, dict) and out["ok"] is False  # no exception


# ── nothing raises, ever ────────────────────────────────────────────


@pytest.mark.parametrize("call", [
    lambda: mb.list_running_apps(),
    lambda: mb.list_windows("X"),
    lambda: mb.move_window("X", 0, 0),
    lambda: mb.resize_window("X", 1, 1),
    lambda: mb.press_element("X", "Y"),
    lambda: mb.run_background_browser_js("x", browser="X"),
])
def test_no_entry_point_ever_raises(call):
    result = call()                      # must not raise
    assert isinstance(result, dict)
