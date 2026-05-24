"""computer_use_v2 — drive any macOS app, with verification built in.

The v2 rebuild. v1 exposed raw primitives (``click(x, y)``) and left all
the planning, grounding and verification to the model — which clicked
blind and never checked the result. v2 fixes that *inside the skill*:

  • **Indexed, not coordinate-based.** ``click(element=5)`` — the skill
    reads the accessibility tree, assigns element indexes, and clicks the
    indexed target. Name matching remains as a compatibility fallback.
  • **Self-verifying.** Every action re-reads the screen afterwards and
    hands the new state back, plus a ``verified`` flag for whether the
    screen actually changed. The model cannot act blind — the result of
    each step is in its face before the next one.
  • **One verified call** replaces the v1 read → click → read dance, so
    a job is a third of the tool calls — and a third of the prompts.

The plan → act → verify discipline lives in SKILL.md, so it travels
with the skill. Zero extra dependencies — macOS ``osascript`` +
``screencapture`` built-ins only; jaeger_os imports are lazy in
``register()`` so the smoke test loads the module standalone.

SAFETY: the action tools (``click``, ``type``, ``key``, ``menu`` and
rich pointer/window actions) are
EXTERNAL_EFFECT — confirmation-gated under the ``computer_use`` skill,
so one grant covers them all. macOS also requires the host process to
hold **Accessibility** (and **Screen Recording** for screenshots).
"""

from __future__ import annotations

import json
import platform
import re
import subprocess
import time
from typing import Any

_IS_MAC = platform.system() == "Darwin"

# Named non-character keys → macOS virtual key codes.
_KEY_CODES = {
    "return": 36, "enter": 36, "tab": 48, "space": 49, "delete": 51,
    "backspace": 51, "escape": 53, "esc": 53, "left": 123, "right": 124,
    "down": 125, "up": 126, "home": 115, "end": 119, "pageup": 116,
    "pagedown": 121, "f1": 122, "f2": 120, "f3": 99, "f4": 118,
}
_MODIFIERS = {
    "cmd": "command down", "command": "command down",
    "shift": "shift down", "option": "option down", "alt": "option down",
    "control": "control down", "ctrl": "control down",
}
_KEY_ALIASES = {
    "command": "cmd", "control": "ctrl", "alt": "option",
    "return": "enter", "esc": "escape",
}
_BLOCKED_KEY_COMBOS = {
    frozenset({"cmd", "shift", "backspace"}),
    frozenset({"cmd", "option", "backspace"}),
    frozenset({"cmd", "ctrl", "q"}),
    frozenset({"cmd", "shift", "q"}),
    frozenset({"cmd", "option", "shift", "q"}),
}
_BLOCKED_TYPE_PATTERNS = [
    re.compile(r"curl\s+[^|]*\|\s*bash", re.IGNORECASE),
    re.compile(r"curl\s+[^|]*\|\s*sh", re.IGNORECASE),
    re.compile(r"wget\s+[^|]*\|\s*bash", re.IGNORECASE),
    re.compile(r"\bsudo\s+rm\s+-[rf]", re.IGNORECASE),
    re.compile(r"\brm\s+-rf\s+/\s*$", re.IGNORECASE),
    re.compile(r":\s*\(\)\s*\{\s*:\|:\s*&\s*\}", re.IGNORECASE),
]

# read_screen — dump the frontmost window's UI elements + their geometry.
_READ_SCREEN_SCRIPT = r'''
tell application "System Events"
	try
		set proc to first process whose frontmost is true
	on error
		return "ERROR: no frontmost process"
	end try
	set out to "app: " & (name of proc) & linefeed
	try
		set win to front window of proc
		set out to out & "window: " & (name of win) & linefeed
		set els to entire contents of win
		set n to 0
		repeat with el in els
			if n is greater than 80 then exit repeat
			try
				set r to (role of el) as text
				set nm to ""
				try
					set nm to (name of el) as text
				end try
				set ds to ""
				try
					set ds to (description of el) as text
				end try
				set vv to ""
				try
					set vv to (value of el) as text
				end try
				set px to "?"
				set py to "?"
				set sw to "0"
				set sh to "0"
				try
					set pos to position of el
					set px to (item 1 of pos) as text
					set py to (item 2 of pos) as text
					set sz to size of el
					set sw to (item 1 of sz) as text
					set sh to (item 2 of sz) as text
				end try
				set out to out & r & " ||| " & nm & " ||| " & ds & " ||| " & vv & " ||| " & px & " ||| " & py & " ||| " & sw & " ||| " & sh & linefeed
				set n to n + 1
			end try
		end repeat
	on error errMsg
		set out to out & "window-read-error: " & errMsg & linefeed
	end try
	return out
end tell
'''


# list_windows — every visible app and its window titles, with which is
# frontmost. This is how the skill stays aware of the WHOLE desktop, not
# just whatever window happens to be in front.
_LIST_WINDOWS_SCRIPT = r'''
tell application "System Events"
	set out to ""
	repeat with proc in (every process whose background only is false)
		set pn to (name of proc) as text
		set fg to "no"
		try
			if frontmost of proc then set fg to "yes"
		end try
		set out to out & "APP ||| " & pn & " ||| " & fg & linefeed
		try
			repeat with w in (windows of proc)
				set out to out & "WIN ||| " & pn & " ||| " & (name of w) & linefeed
			end repeat
		end try
	end repeat
	return out
end tell
'''


def _esc(text: str) -> str:
    """Escape a Python string for use inside an AppleScript "..." literal."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _canon_key_combo(keys: str) -> frozenset[str]:
    parts = [p.strip().lower() for p in re.split(r"\s*\+\s*", keys or "") if p.strip()]
    return frozenset(_KEY_ALIASES.get(p, p) for p in parts)


def _blocked_type_pattern(text: str) -> str | None:
    for pat in _BLOCKED_TYPE_PATTERNS:
        if pat.search(text or ""):
            return pat.pattern
    return None


def _osascript(script: str, timeout: float = 20.0) -> tuple[bool, str]:
    """Run an AppleScript via ``osascript``. Returns (ok, output-or-error)."""
    if not _IS_MAC:
        return False, "computer_use is macOS-only"
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"osascript timed out after {timeout:.0f}s"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        if "assistive access" in err or "-25211" in err or "1002" in err:
            return False, (
                "macOS Accessibility permission is required. Grant it in "
                "System Settings → Privacy & Security → Accessibility for "
                "the app running Jaeger-OS (Terminal / your IDE), then retry."
            )
        return False, err or "osascript failed"
    return True, (proc.stdout or "").strip()


def _cg_mouse_event(event_type: int, x: int, y: int, button: int = 0) -> str | None:
    """Post one macOS CoreGraphics mouse event.

    Used for richer pointer actions that System Events handles inconsistently
    across apps. Returns None on success or an error string on failure.
    """
    if not _IS_MAC:
        return "computer_use is macOS-only"
    try:
        import ctypes

        class CGPoint(ctypes.Structure):
            _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

        lib = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/"
            "ApplicationServices"
        )
        lib.CGEventCreateMouseEvent.restype = ctypes.c_void_p
        lib.CGEventCreateMouseEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, CGPoint, ctypes.c_uint32,
        ]
        lib.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        lib.CFRelease.argtypes = [ctypes.c_void_p]
        event = lib.CGEventCreateMouseEvent(
            None, ctypes.c_uint32(event_type), CGPoint(float(x), float(y)),
            ctypes.c_uint32(button),
        )
        if not event:
            return "CGEventCreateMouseEvent returned null"
        lib.CGEventPost(0, event)
        lib.CFRelease(event)
    except Exception as exc:  # noqa: BLE001
        return f"CoreGraphics mouse event failed: {exc}"
    return None


def _cg_click(x: int, y: int, *, button: str = "left", clicks: int = 1) -> str | None:
    btn = 1 if button == "right" else 0
    down = 3 if button == "right" else 1
    up = 4 if button == "right" else 2
    for _ in range(max(1, clicks)):
        err = _cg_mouse_event(down, x, y, btn)
        if err:
            return err
        err = _cg_mouse_event(up, x, y, btn)
        if err:
            return err
        time.sleep(0.05)
    return None


def _cg_drag(x1: int, y1: int, x2: int, y2: int) -> str | None:
    err = _cg_mouse_event(1, x1, y1, 0)  # left down
    if err:
        return err
    steps = 12
    for i in range(1, steps + 1):
        x = round(x1 + (x2 - x1) * i / steps)
        y = round(y1 + (y2 - y1) * i / steps)
        err = _cg_mouse_event(6, x, y, 0)  # left dragged
        if err:
            _cg_mouse_event(2, x, y, 0)
            return err
        time.sleep(0.015)
    return _cg_mouse_event(2, x2, y2, 0)  # left up


# ── perceive ─────────────────────────────────────────────────────────


def _parse_screen(raw: str) -> dict[str, Any]:
    """Parse the read_screen AppleScript dump into structured elements.

    Each line is ``role ||| name ||| description ||| value ||| x ||| y |||
    w ||| h``. The element's click point is its centre."""
    app = window = ""
    elements: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if line.startswith("app: "):
            app = line[5:].strip()
        elif line.startswith("window: "):
            window = line[8:].strip()
        elif "|||" in line:
            parts = [p.strip() for p in line.split("|||")]
            if len(parts) != 8:
                continue
            role, name, desc, value, px, py, sw, sh = parts
            el: dict[str, Any] = {"role": role, "name": name,
                                  "description": desc, "value": value,
                                  "index": len(elements) + 1}
            try:  # clickable point = element centre
                x, y = int(px), int(py)
                w, h = int(sw), int(sh)
                el["x"] = x + w // 2
                el["y"] = y + h // 2
                el["bounds"] = [x, y, w, h]
            except ValueError:
                pass
            elements.append(el)
    return {"app": app, "window": window, "elements": elements,
            "count": len(elements)}


def read_screen() -> dict[str, Any]:
    """Read the frontmost window's accessibility tree — every element with
    its role, name, description, value and centre point."""
    ok, out = _osascript(_READ_SCREEN_SCRIPT)
    if not ok:
        return {"ok": False, "error": out}
    if out.startswith("ERROR:"):
        return {"ok": False, "error": out[6:].strip()}
    return {"ok": True, **_parse_screen(out)}


def _parse_windows(raw: str) -> list[dict[str, Any]]:
    """Parse the list_windows AppleScript dump into ``[{app, frontmost,
    windows}]``. Pure / unit-testable."""
    apps: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for line in raw.splitlines():
        parts = [p.strip() for p in line.split("|||")]
        if parts[0] == "APP" and len(parts) == 3:
            name = parts[1]
            if name and name not in apps:
                apps[name] = {"app": name, "frontmost": parts[2] == "yes",
                              "windows": []}
                order.append(name)
        elif parts[0] == "WIN" and len(parts) == 3:
            name, title = parts[1], parts[2]
            if name in apps and title:
                apps[name]["windows"].append(title)
    return [apps[n] for n in order]


def list_windows() -> dict[str, Any]:
    """Enumerate EVERY visible app and its windows — the whole desktop,
    not just the frontmost window. This is how the skill knows what is
    open and what it needs to focus."""
    ok, out = _osascript(_LIST_WINDOWS_SCRIPT)
    if not ok:
        return {"ok": False, "error": out}
    return {"ok": True, "apps": _parse_windows(out)}


def _screen_summary(scr: dict[str, Any]) -> dict[str, Any]:
    """The model-facing view of a screen read — element names/roles/values
    with stable per-observation indexes. Coordinates are hidden here; use
    capture(mode="som") when the model needs visual grounding."""
    if not scr.get("ok"):
        return {"ok": False, "error": scr.get("error", "screen read failed")}
    els = []
    for e in scr.get("elements", []):
        if not (e.get("name") or e.get("description") or e.get("value")):
            continue
        item = {
            "index": e.get("index"),
            "role": e.get("role", ""),
            "name": e.get("name", ""),
        }
        if e.get("value"):
            item["value"] = e["value"]
        if e.get("description"):
            item["description"] = e["description"]
        els.append(item)
    return {"ok": True, "app": scr.get("app", ""),
            "window": scr.get("window", ""), "elements": els}


def _screen_signature(scr: dict[str, Any]) -> Any:
    """A comparable fingerprint of a screen read — used to tell whether
    an action actually changed anything."""
    return (
        scr.get("window", ""),
        tuple(sorted(
            (e.get("role", ""), e.get("name", ""), e.get("value", ""))
            for e in scr.get("elements", [])
        )),
    )


def _verified(before: dict[str, Any], after: dict[str, Any]) -> bool | None:
    """Did the screen change between ``before`` and ``after``? ``None``
    when either read failed (verification indeterminate)."""
    if not (before.get("ok") and after.get("ok")):
        return None
    return _screen_signature(before) != _screen_signature(after)


def _find_element(
    elements: list[dict[str, Any]], target: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Pick the on-screen element best matching ``target`` (an element
    name or description). Pure and unit-testable.

    Returns ``(element_or_None, candidate_names)``. Scoring favours an
    exact name match, then prefix, then substring, then a description
    hit — so ``"5"`` lands the button literally named ``5``."""
    want = (target or "").strip().lower()
    candidates = [e.get("name", "") for e in elements if e.get("name")]
    if not want:
        return None, candidates
    best: dict[str, Any] | None = None
    best_score = 0
    for el in elements:
        name = (el.get("name") or "").strip().lower()
        desc = (el.get("description") or "").strip().lower()
        score = 0
        if name and name == want:
            score = 100
        elif name and (name.startswith(want) or want.startswith(name)):
            score = 80
        elif name and want in name:
            score = 60
        elif name and name in want:
            score = 50
        elif desc and want in desc:
            score = 40
        # An element with no click point can't be the click target.
        if score and "x" in el:
            score += 1
        if score > best_score:
            best, best_score = el, score
    return best, candidates


def _find_element_by_index(
    elements: list[dict[str, Any]], index: int | None,
) -> dict[str, Any] | None:
    if index is None:
        return None
    try:
        want = int(index)
    except (TypeError, ValueError):
        return None
    for el in elements:
        if el.get("index") == want and "x" in el:
            return el
    return None


def _resolve_clickable(
    screen: dict[str, Any],
    *,
    element: int | None = None,
    target: str = "",
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve an element index/name into a clickable AX element.

    Returns ``(element, error_result)`` so action functions can share the
    same indexed targeting behavior.
    """
    elements = screen.get("elements") or []
    want = (target or "").strip()
    el = _find_element_by_index(elements, element)
    if el is None and want:
        el, _ = _find_element(elements, want)
    if el is not None and "x" in el:
        return el, None
    available = _screen_summary(screen).get("elements", [])[:40]
    if element is not None:
        return None, {"ok": False,
                      "error": f"no clickable element with index {element!r}",
                      "available": available}
    return None, {"ok": False,
                  "error": f"no clickable element matching {want!r}",
                  "available": available}


# ── act — every action self-verifies ─────────────────────────────────


def _act_result(action: str, before: dict[str, Any], after: dict[str, Any],
                 **extra: Any) -> dict[str, Any]:
    """Shared shape for an action result: what was done, the screen
    AFTER it, and whether the screen actually changed."""
    return {
        "ok": True, "action": action,
        "screen": _screen_summary(after),
        "verified": _verified(before, after),
        **extra,
    }


def look() -> dict[str, Any]:
    """Perceive the desktop — the frontmost window's elements AND every
    other open window. The skill sees the whole desktop, so it can focus
    a background app itself instead of depending on what's in front."""
    summary = _screen_summary(read_screen())
    wins = list_windows()
    return {
        "ok": True, "action": "look",
        "screen": summary,
        "windows": wins.get("apps", []) if wins.get("ok") else [],
    }


def open_app(name: str) -> dict[str, Any]:
    """Launch / focus a macOS app, then read what's on screen."""
    clean = (name or "").strip()
    if not clean:
        return {"ok": False, "error": "app name is required"}
    ok, out = _osascript(f'tell application "{_esc(clean)}" to activate')
    if not ok:
        return {"ok": False, "error": out, "app": clean}
    # Give the window a beat to come up, then look.
    _osascript('delay 0.6')
    return {"ok": True, "action": "open", "app": clean,
            "screen": _screen_summary(read_screen())}


def focus_window(
    app: str,
    window: str = "",
    window_index: int | None = None,
) -> dict[str, Any]:
    """Bring a specific app/window forward by title substring or index."""
    clean_app = (app or "").strip()
    clean_window = (window or "").strip()
    if not clean_app:
        return {"ok": False, "error": "app is required"}
    before = read_screen()
    try:
        idx = int(window_index) if window_index is not None else 1
    except (TypeError, ValueError):
        return {"ok": False, "error": "window_index must be an integer"}
    if idx < 1:
        return {"ok": False, "error": "window_index must be >= 1"}
    script = (
        f'tell application "{_esc(clean_app)}" to activate\n'
        'delay 0.2\n'
        'tell application "System Events"\n'
        f'  tell process "{_esc(clean_app)}"\n'
        '    set frontmost to true\n'
    )
    if clean_window:
        script += (
            '    repeat with w in windows\n'
            f'      if (name of w as text) contains "{_esc(clean_window)}" then\n'
            '        perform action "AXRaise" of w\n'
            '        return "ok"\n'
            '      end if\n'
            '    end repeat\n'
            '    return "window not found"\n'
        )
    else:
        script += (
            f'    if (count of windows) is less than {idx} then return "window not found"\n'
            f'    perform action "AXRaise" of window {idx}\n'
            '    return "ok"\n'
        )
    script += '  end tell\nend tell'
    ok, out = _osascript(script)
    if not ok:
        return {"ok": False, "error": out, "app": clean_app, "window": clean_window}
    if out.strip().lower() != "ok":
        return {"ok": False, "error": out or "window not found",
                "app": clean_app, "window": clean_window,
                "available": list_windows().get("apps", [])}
    return _act_result(
        "focus_window", before, read_screen(), app=clean_app,
        window=clean_window, window_index=idx,
    )


def click(target: str = "", element: int | None = None) -> dict[str, Any]:
    """Click the on-screen element by capture index, or by fallback name.

    Element indexes are preferred because labels are often duplicated or
    missing. Reads → finds → clicks → re-reads."""
    if not _IS_MAC:
        return {"ok": False, "error": "computer_use is macOS-only"}
    want = (target or "").strip()
    if element is None and not want:
        return {"ok": False,
                "error": "target element name or element index is required"}
    before = read_screen()
    if not before.get("ok"):
        return {"ok": False, "error": before.get("error", "screen read failed")}
    el, err = _resolve_clickable(before, element=element, target=want)
    if err:
        return err
    ok, out = _osascript(
        f'tell application "System Events" to click at {{{el["x"]}, {el["y"]}}}'
    )
    if not ok:
        return {"ok": False, "error": out}
    after = read_screen()
    return _act_result(
        "click", before, after, target=want, element=el.get("index"),
        matched={"index": el.get("index"), "name": el.get("name"),
                 "role": el.get("role")},
    )


def double_click(target: str = "", element: int | None = None) -> dict[str, Any]:
    """Double-click an indexed element or fallback named target."""
    if not _IS_MAC:
        return {"ok": False, "error": "computer_use is macOS-only"}
    before = read_screen()
    if not before.get("ok"):
        return {"ok": False, "error": before.get("error", "screen read failed")}
    el, err = _resolve_clickable(before, element=element, target=target)
    if err:
        return err
    cg_err = _cg_click(el["x"], el["y"], clicks=2)
    if cg_err:
        ok, out = _osascript(
            f'tell application "System Events" to double click at {{{el["x"]}, {el["y"]}}}'
        )
        if not ok:
            return {"ok": False, "error": out, "cg_error": cg_err}
    return _act_result(
        "double_click", before, read_screen(), target=(target or "").strip(),
        element=el.get("index"),
        matched={"index": el.get("index"), "name": el.get("name"),
                 "role": el.get("role")},
    )


def right_click(target: str = "", element: int | None = None) -> dict[str, Any]:
    """Open the context menu on an indexed element via control-click."""
    if not _IS_MAC:
        return {"ok": False, "error": "computer_use is macOS-only"}
    before = read_screen()
    if not before.get("ok"):
        return {"ok": False, "error": before.get("error", "screen read failed")}
    el, err = _resolve_clickable(before, element=element, target=target)
    if err:
        return err
    cg_err = _cg_click(el["x"], el["y"], button="right")
    if not cg_err:
        return _act_result(
            "right_click", before, read_screen(), target=(target or "").strip(),
            element=el.get("index"),
            matched={"index": el.get("index"), "name": el.get("name"),
                     "role": el.get("role")},
        )
    script = (
        'tell application "System Events"\n'
        '  key down control\n'
        f'  click at {{{el["x"]}, {el["y"]}}}\n'
        '  key up control\n'
        'end tell'
    )
    ok, out = _osascript(script)
    if not ok:
        _osascript('tell application "System Events" to key up control')
        return {"ok": False, "error": out, "cg_error": cg_err}
    return _act_result(
        "right_click", before, read_screen(), target=(target or "").strip(),
        element=el.get("index"),
        matched={"index": el.get("index"), "name": el.get("name"),
                 "role": el.get("role")},
    )


def scroll(direction: str = "down", amount: int = 3) -> dict[str, Any]:
    """Scroll the frontmost app. Positive wheel values scroll up on macOS."""
    d = (direction or "down").strip().lower()
    if d not in {"up", "down", "left", "right"}:
        return {"ok": False, "error": "direction must be up, down, left, or right"}
    try:
        ticks = max(1, min(int(amount), 20))
    except (TypeError, ValueError):
        return {"ok": False, "error": "amount must be an integer"}
    if not _IS_MAC:
        return {"ok": False, "error": "computer_use is macOS-only"}
    wheel = ticks if d in {"up", "left"} else -ticks
    before = read_screen()
    if d in {"left", "right"}:
        script = (
            'tell application "System Events"\n'
            '  key down shift\n'
            f'  scroll wheel {wheel}\n'
            '  key up shift\n'
            'end tell'
        )
    else:
        script = f'tell application "System Events" to scroll wheel {wheel}'
    ok, out = _osascript(script)
    if not ok:
        _osascript('tell application "System Events" to key up shift')
        return {"ok": False, "error": out}
    return _act_result("scroll", before, read_screen(),
                       direction=d, amount=ticks)


def drag(
    from_element: int | None = None,
    to_element: int | None = None,
    *,
    target: str = "",
    to_target: str = "",
) -> dict[str, Any]:
    """Drag from one indexed element to another."""
    if not _IS_MAC:
        return {"ok": False, "error": "computer_use is macOS-only"}
    before = read_screen()
    if not before.get("ok"):
        return {"ok": False, "error": before.get("error", "screen read failed")}
    src, err = _resolve_clickable(before, element=from_element, target=target)
    if err:
        return err
    dst, err = _resolve_clickable(before, element=to_element, target=to_target)
    if err:
        return err
    cg_err = _cg_drag(src["x"], src["y"], dst["x"], dst["y"])
    if cg_err:
        script = (
            'tell application "System Events"\n'
            f'  drag from {{{src["x"]}, {src["y"]}}} to {{{dst["x"]}, {dst["y"]}}}\n'
            'end tell'
        )
        ok, out = _osascript(script)
        if not ok:
            return {"ok": False, "error": out, "cg_error": cg_err}
    return _act_result("drag", before, read_screen(),
                       from_element=src.get("index"), to_element=dst.get("index"))


def set_value(value: str, element: int | None = None, target: str = "") -> dict[str, Any]:
    """Set the AX value of an indexed element, with click/type fallback."""
    if not _IS_MAC:
        return {"ok": False, "error": "computer_use is macOS-only"}
    if value is None:
        return {"ok": False, "error": "value is required"}
    pat = _blocked_type_pattern(str(value))
    if pat:
        return {"ok": False,
                "error": f"blocked dangerous typed text pattern: {pat}"}
    before = read_screen()
    if not before.get("ok"):
        return {"ok": False, "error": before.get("error", "screen read failed")}
    el, err = _resolve_clickable(before, element=element, target=target)
    if err:
        return err
    if element is None:
        element = el.get("index")
    script = (
        'tell application "System Events"\n'
        '  set proc to first process whose frontmost is true\n'
        '  set win to front window of proc\n'
        '  set els to entire contents of win\n'
        '  set n to 0\n'
        '  repeat with el in els\n'
        '    set n to n + 1\n'
        f'    if n is {int(element)} then\n'
        f'      set value of el to "{_esc(str(value))}"\n'
        '      return "ok"\n'
        '    end if\n'
        '  end repeat\n'
        '  return "not found"\n'
        'end tell'
    )
    ok, out = _osascript(script)
    if not ok:
        # Many controls are not AXValue-settable. Fall back to the common
        # Mac path: focus it, select contents, type the new value.
        clicked = click(target=target, element=element)
        if not clicked.get("ok"):
            return {"ok": False, "error": out, "fallback": clicked}
        select_script, err2 = _build_press_script("cmd+a")
        if err2:
            return {"ok": False, "error": err2}
        _osascript(select_script)  # best effort
        typed = type_text(str(value))
        if not typed.get("ok"):
            return {"ok": False, "error": out, "fallback": typed}
        typed["action"] = "set_value"
        typed["fallback"] = "click_select_type"
        typed["element"] = element
        return typed
    if out.strip().lower() != "ok":
        return {"ok": False, "error": out or "element not found", "element": element}
    return _act_result("set_value", before, read_screen(),
                       element=element, value_length=len(str(value)))


def type_text(text: str) -> dict[str, Any]:
    """Type ``text`` into the focused field, then re-read the screen."""
    if not text:
        return {"ok": False, "error": "text is required"}
    pat = _blocked_type_pattern(text)
    if pat:
        return {"ok": False,
                "error": f"blocked dangerous typed text pattern: {pat}"}
    before = read_screen()
    ok, out = _osascript(
        f'tell application "System Events" to keystroke "{_esc(text)}"'
    )
    if not ok:
        return {"ok": False, "error": out}
    return _act_result("type", before, read_screen(), typed=len(text))


def _build_press_script(key: str) -> tuple[str | None, str | None]:
    """Pure: resolve a key / chord spec to an AppleScript string, or
    return ``(None, error)``. No OS interaction — unit-testable."""
    clean = (key or "").strip().lower()
    if not clean:
        return None, "key is required"
    combo = _canon_key_combo(clean)
    for blocked in _BLOCKED_KEY_COMBOS:
        if blocked.issubset(combo):
            return None, f"blocked destructive key combo: {'+'.join(sorted(blocked))}"
    parts = [p.strip() for p in clean.split("+") if p.strip()]
    mods = [_MODIFIERS[p] for p in parts[:-1] if p in _MODIFIERS]
    final = parts[-1] if parts else ""
    using = f" using {{{', '.join(mods)}}}" if mods else ""
    if final in _KEY_CODES:
        return (f'tell application "System Events" to key code '
                f"{_KEY_CODES[final]}{using}", None)
    if len(final) == 1:
        return (f'tell application "System Events" to keystroke '
                f'"{_esc(final)}"{using}', None)
    return None, (f"unknown key {key!r} — use a single character or one "
                  "of " + ", ".join(sorted(_KEY_CODES)))


def press_key(key: str) -> dict[str, Any]:
    """Press a key or chord — 'return', 'tab', 'cmd+c' — then re-read."""
    script, err = _build_press_script(key)
    if err:
        return {"ok": False, "error": err}
    before = read_screen()
    ok, out = _osascript(script)  # type: ignore[arg-type]
    if not ok:
        return {"ok": False, "error": out}
    return _act_result("key", before, read_screen(),
                       pressed=(key or "").strip().lower())


def menu_select(menu: str, item: str) -> dict[str, Any]:
    """Click a menu-bar item (``File`` → ``New``), then re-read. Menu
    paths are stable — the most reliable way to drive an app."""
    m, it = (menu or "").strip(), (item or "").strip()
    if not m or not it:
        return {"ok": False, "error": "both menu and item are required"}
    before = read_screen()
    script = (
        'tell application "System Events" to tell '
        '(first process whose frontmost is true) to click '
        f'menu item "{_esc(it)}" of menu "{_esc(m)}" of '
        f'menu bar item "{_esc(m)}" of menu bar 1'
    )
    ok, out = _osascript(script)
    if not ok:
        return {"ok": False, "error": out}
    return _act_result("menu", before, read_screen(), selected=f"{m} → {it}")


def _screenshot_file(path: str) -> tuple[dict[str, Any], Any]:
    from jaeger_os.core.tools._common import (  # lazy — keep module import-clean
        SandboxError, _require_layout, _resolve_under,
    )
    if not _IS_MAC:
        return {"ok": False, "error": "computer_use is macOS-only"}, None
    layout = _require_layout()
    try:
        target = _resolve_under(layout.skills_dir, path)
    except SandboxError as exc:
        return {"ok": False, "error": str(exc)}, None
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            ["screencapture", "-x", str(target)], capture_output=True, timeout=15,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}, None
    if proc.returncode != 0 or not target.exists():
        return {"ok": False, "error": ("screencapture failed — the host "
                "process may need Screen Recording permission.")}, None
    return {"ok": True, "path": str(target.relative_to(layout.root)),
            "bytes": target.stat().st_size}, target


def screenshot(path: str = "screen.png") -> dict[str, Any]:
    """Capture the screen to a PNG under the instance's skills/ directory —
    for the rare app the accessibility tree can't describe."""
    result, _ = _screenshot_file(path)
    return result


def _capture_elements(scr: dict[str, Any], *, max_elements: int = 80) -> list[dict[str, Any]]:
    elements = []
    for e in (scr.get("elements") or [])[:max_elements]:
        if not (e.get("name") or e.get("description") or e.get("value")):
            continue
        item = {
            "index": e.get("index"),
            "role": e.get("role", ""),
            "name": e.get("name", ""),
            "description": e.get("description", ""),
            "value": e.get("value", ""),
        }
        if e.get("bounds"):
            item["bounds"] = e["bounds"]
        elements.append(item)
    return elements


def _draw_som_overlay(image_path: Any, elements: list[dict[str, Any]]) -> str | None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as exc:  # pragma: no cover - depends on optional Pillow
        return f"Pillow unavailable for SOM overlay: {exc}"
    try:
        img = Image.open(image_path).convert("RGBA")
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()
        for el in elements:
            bounds = el.get("bounds")
            idx = el.get("index")
            if not bounds or idx is None:
                continue
            x, y, w, h = [int(v) for v in bounds]
            draw.rectangle((x, y, x + w, y + h), outline=(255, 82, 82, 220), width=2)
            label = str(idx)
            box = draw.textbbox((x, y), label, font=font)
            pad = 3
            draw.rectangle(
                (x, y, box[2] + pad * 2, box[3] + pad * 2),
                fill=(255, 82, 82, 230),
            )
            draw.text((x + pad, y + pad), label, fill=(255, 255, 255, 255), font=font)
        img.convert("RGB").save(image_path)
    except Exception as exc:  # noqa: BLE001
        return f"SOM overlay failed: {exc}"
    return None


def capture(mode: str = "som", path: str = "computer_capture.png") -> dict[str, Any]:
    """Capture the current computer state.

    Modes:
    - ax: accessibility tree only.
    - vision: screenshot plus accessibility index.
    - som: screenshot with numbered boxes plus accessibility index.
    """
    mode = (mode or "som").strip().lower()
    if mode not in {"som", "vision", "ax"}:
        return {"ok": False, "error": "mode must be one of: som, vision, ax"}
    scr = read_screen()
    if not scr.get("ok"):
        return {"ok": False, "error": scr.get("error", "screen read failed")}
    elements = _capture_elements(scr)
    result: dict[str, Any] = {
        "ok": True,
        "action": "capture",
        "mode": mode,
        "app": scr.get("app", ""),
        "window": scr.get("window", ""),
        "elements": elements,
        "text_summary": "\n".join(
            f"#{e.get('index')} {e.get('role', '')} "
            f"{(e.get('name') or e.get('description') or e.get('value') or '').strip()!r}"
            for e in elements[:50]
        ),
    }
    if mode == "ax":
        return result
    shot, target = _screenshot_file(path)
    if not shot.get("ok"):
        return {**result, "ok": False, "error": shot.get("error")}
    if mode == "som" and target is not None:
        overlay_error = _draw_som_overlay(target, elements)
        if overlay_error:
            result["overlay_error"] = overlay_error
    result.update({"path": shot["path"], "bytes": shot["bytes"]})
    return result


# ── orchestrator — the LLM-driven plan / act / verify loop ───────────
# `computer_do(goal)` runs its OWN loop with the model: look at the
# screen, decide the single next action, do it, check the result,
# repeat. The loop runs inside the agent turn — which already holds the
# model lock — so it calls client.chat directly (re-acquiring the
# non-reentrant lock would deadlock).

_MAX_STEPS = 14

_CONTROLLER_SYSTEM = """You are the controller of a macOS computer-use loop. \
You get a GOAL, the OPEN WINDOWS on the desktop, and the CURRENT SCREEN (the \
accessibility tree of the frontmost app). Decide the SINGLE next action toward \
the goal.

You FULLY control the desktop — you are NOT limited to whatever window is in \
front. If the app or window you need is not frontmost, your next action is \
{"action":"open","app":"<name>"} to bring it forward, then look. NEVER ask the \
user to switch windows, change focus, click, or move anything — if you need to \
be somewhere, navigate there yourself.

Think briefly, step by step — then output EXACTLY ONE action as a JSON object \
on the FINAL line, with nothing after it. Valid actions:
  {"action": "open",  "app": "Calculator"}
  {"action": "focus_window", "app": "Safari", "window": "Downloads"}
  {"action": "click", "element": 12}
  {"action": "double_click", "element": 12}
  {"action": "right_click", "element": 12}
  {"action": "scroll", "direction": "down", "amount": 4}
  {"action": "drag", "from_element": 3, "to_element": 8}
  {"action": "set_value", "element": 7, "value": "<new value>"}
  {"action": "type",  "text": "<text>"}
  {"action": "key",   "key": "<key or chord, e.g. return, cmd+c>"}
  {"action": "menu",  "menu": "<menu>", "item": "<item>"}
  {"action": "done",  "result": "<the outcome / answer>"}

Rules:
- A click element MUST be an element index from the CURRENT SCREEN list.
- If the CURRENT SCREEN is the wrong app, "open" the right one first.
- Exactly one action per step — you will see the new screen after it runs.
- When the goal is met, use "done" and read the answer off the screen for
  "result" — never state a result from memory.
- "done" is for SUCCESS only. If you are blocked, do NOT "done" with an
  excuse and do NOT ask the user — take an action that unblocks you.
"""


def _parse_action(text: str) -> dict[str, Any]:
    """Extract the controller's action JSON from its reply. Scans for
    brace-balanced ``{…}`` blocks and takes the last one that parses and
    carries an ``action`` key. Pure / unit-testable."""
    if not text:
        return {"action": None, "error": "empty controller reply"}
    found: dict[str, Any] | None = None
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    obj = json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    obj = None
                if isinstance(obj, dict) and "action" in obj:
                    found = obj
    if found is None:
        return {"action": None, "error": "no action JSON in controller reply"}
    return found


def _execute_action(decision: dict[str, Any]) -> dict[str, Any]:
    """Dispatch one parsed action to the matching v2 primitive."""
    a = decision.get("action")
    if a == "open":
        return open_app(decision.get("app", ""))
    if a in {"focus_window", "focus_app"}:
        return focus_window(
            decision.get("app", ""),
            decision.get("window", ""),
            decision.get("window_index"),
        )
    if a == "click":
        return click(decision.get("target", ""), decision.get("element"))
    if a == "double_click":
        return double_click(decision.get("target", ""), decision.get("element"))
    if a in {"right_click", "context_click"}:
        return right_click(decision.get("target", ""), decision.get("element"))
    if a == "scroll":
        return scroll(decision.get("direction", "down"), decision.get("amount", 3))
    if a == "drag":
        return drag(
            decision.get("from_element"),
            decision.get("to_element"),
            target=decision.get("target", ""),
            to_target=decision.get("to_target", ""),
        )
    if a == "set_value":
        return set_value(
            decision.get("value", ""),
            decision.get("element"),
            decision.get("target", ""),
        )
    if a == "type":
        return type_text(decision.get("text", ""))
    if a == "key":
        return press_key(decision.get("key", ""))
    if a == "menu":
        return menu_select(decision.get("menu", ""), decision.get("item", ""))
    return {"ok": False, "error": f"unknown action {a!r}"}


def wait(seconds: float = 1.0) -> dict[str, Any]:
    """Pause briefly, then read the screen."""
    try:
        delay = float(seconds)
    except (TypeError, ValueError):
        return {"ok": False, "error": "seconds must be a number"}
    delay = max(0.0, min(delay, 30.0))
    time.sleep(delay)
    return {"ok": True, "action": "wait", "seconds": delay,
            "screen": _screen_summary(read_screen())}


def use_computer(
    action: str,
    *,
    mode: str = "som",
    app: str = "",
    window: str = "",
    window_index: int | None = None,
    element: int | None = None,
    from_element: int | None = None,
    to_element: int | None = None,
    target: str = "",
    to_target: str = "",
    text: str = "",
    key: str = "",
    menu: str = "",
    item: str = "",
    value: str = "",
    direction: str = "down",
    amount: int = 3,
    path: str = "computer_capture.png",
    seconds: float = 1.0,
    goal: str = "",
    capture_after: bool = False,
    client: Any = None,
) -> dict[str, Any]:
    """Consolidated computer-use dispatcher.

    This keeps model routing simple while the compatibility wrappers stay
    available for older prompts and benchmarks.
    """
    a = (action or "").strip().lower()
    if a == "capture":
        return capture(mode=mode, path=path)
    if a == "look":
        return look()
    if a in {"windows", "list_apps"}:
        return list_windows()
    if a == "open":
        return open_app(app)
    if a in {"focus_window", "focus_app"}:
        return focus_window(app, window, window_index)
    if a == "click":
        result = click(target=target, element=element)
    elif a == "double_click":
        result = double_click(target=target, element=element)
    elif a in {"right_click", "context_click"}:
        result = right_click(target=target, element=element)
    elif a == "scroll":
        result = scroll(direction=direction, amount=amount)
    elif a == "drag":
        result = drag(from_element=from_element, to_element=to_element,
                      target=target, to_target=to_target)
    elif a == "set_value":
        result = set_value(value=value, element=element, target=target)
    elif a == "type":
        result = type_text(text)
    elif a == "key":
        result = press_key(key)
    elif a == "menu":
        result = menu_select(menu, item)
    elif a == "screenshot":
        return screenshot(path)
    elif a == "wait":
        return wait(seconds)
    elif a == "do":
        if client is None:
            return {"ok": False, "error": "no LLM client available for action='do'"}
        return run_goal(goal, client)
    else:
        return {"ok": False, "error": f"unknown computer_use action {action!r}"}

    if capture_after and result.get("ok"):
        result["capture"] = capture(mode=mode, path=path)
    return result


def _format_windows(windows: list[dict[str, Any]]) -> str:
    """Render the open-windows list for the controller prompt."""
    rows = []
    for a in (windows or [])[:25]:
        tag = "  [FRONTMOST]" if a.get("frontmost") else ""
        titles = ", ".join(w for w in a.get("windows", [])[:4] if w)
        rows.append(f"  - {a.get('app', '')}{tag}"
                    + (f": {titles}" if titles else ""))
    return "\n".join(rows) or "  (none read)"


def _decide_next(client: Any, goal: str, screen: dict[str, Any],
                 windows: list[dict[str, Any]], steps: list[dict[str, Any]],
                 *, reconsider: bool = False) -> dict[str, Any]:
    """One controller turn — ask the model for the next action given the
    goal, the open windows, the front screen and the history.
    ``reconsider`` adds a deliberate 'think about the failure' directive."""
    elements = (screen.get("elements") or [])[:50]
    el_lines = "\n".join(
        f"  - #{e.get('index')} {e.get('role', '')}: "
        f"{e.get('name') or e.get('description') or ''}"
        + (f"  = {e['value']}" if e.get("value") else "")
        for e in elements
    ) or "  (nothing read yet — you probably need to 'open' an app first)"
    history = "\n".join(
        f"  {s['step']}. {s['action']} {s.get('args', {})} — "
        + ("ok" if s["ok"] else "FAILED: " + str(s.get("error", "")))
        for s in steps[-8:]
    ) or "  (none yet)"
    user = (
        f"GOAL: {goal}\n\n"
        f"OPEN WINDOWS (focus any of these yourself with the 'open' "
        f"action):\n{_format_windows(windows)}\n\n"
        f"CURRENT SCREEN — app: {screen.get('app', '?')}  "
        f"window: {screen.get('window', '?')}\n"
        f"ELEMENTS:\n{el_lines}\n\n"
        f"STEPS SO FAR:\n{history}\n\n"
        "What is the next action?"
    )
    if reconsider:
        user += (
            "\n\nThe last action FAILED. Think carefully about the cause — "
            "a wrong element name, the wrong app focused, a step skipped — "
            "and choose a corrected next action."
        )
    try:
        res = client.chat(
            [{"role": "system", "content": _CONTROLLER_SYSTEM},
             {"role": "user", "content": user}],
            max_tokens=320, temperature=0.2, top_p=0.9, stream=False,
        )
    except Exception as exc:  # noqa: BLE001
        return {"action": None, "error": f"controller call failed: {exc}"}
    text = (getattr(res, "text", "") or "").strip()
    parsed = _parse_action(text)
    parsed.setdefault("reason", text[:200])
    return parsed


def run_goal(goal: str, client: Any, *,
             max_steps: int = _MAX_STEPS) -> dict[str, Any]:
    """Drive a whole computer task: plan → act → verify, looping with the
    model until the goal is met or a limit is hit.

    Runs inside the agent turn (the model lock is already held), so it
    calls ``client.chat`` directly. Returns ``{ok, goal, steps, result}``.
    """
    goal = (goal or "").strip()
    if not goal:
        return {"ok": False, "error": "a goal is required"}
    if client is None or not hasattr(client, "chat"):
        return {"ok": False, "error": "no LLM client available for the loop"}

    steps: list[dict[str, Any]] = []
    first = look()
    screen: dict[str, Any] = (first.get("screen")
                              if isinstance(first.get("screen"), dict) else {})
    windows: list[dict[str, Any]] = first.get("windows", [])
    consecutive_fail = 0

    for i in range(1, max_steps + 1):
        decision = _decide_next(client, goal, screen, windows, steps,
                                reconsider=consecutive_fail > 0)
        action = decision.get("action")
        if action is None:
            # One stricter retry before giving up on a mute controller.
            decision = _decide_next(client, goal, screen, windows, steps,
                                    reconsider=True)
            action = decision.get("action")
            if action is None:
                return {"ok": False, "goal": goal, "steps": steps,
                        "error": decision.get("error", "controller stalled")}
        if action == "done":
            return {"ok": True, "goal": goal, "steps": steps,
                    "result": decision.get("result", ""), "screen": screen}

        result = _execute_action(decision)
        args = {k: v for k, v in decision.items()
                if k in (
                    "app", "window", "window_index", "element", "from_element",
                    "to_element", "target", "to_target", "text", "key",
                    "menu", "item", "direction", "amount", "value",
                )}
        ok = bool(result.get("ok"))
        steps.append({"step": i, "action": action, "args": args, "ok": ok,
                      "reason": decision.get("reason", ""),
                      "error": result.get("error")})
        print(f"  [computer] step {i}: {action} {args} "
              + ("✓" if ok else "✗ " + str(result.get("error", ""))[:80]),
              flush=True)

        if ok:
            consecutive_fail = 0
            new_screen = result.get("screen")
            if isinstance(new_screen, dict) and new_screen.get("ok"):
                screen = new_screen
            # The window list only changes when an app is opened/focused
            # or a menu acts — re-enumerating after every click/keystroke
            # is wasted osascript time, so refresh only when it matters.
            if action in ("open", "focus_window", "focus_app", "menu"):
                windows = list_windows().get("apps", [])
        else:
            consecutive_fail += 1
            if consecutive_fail >= 3:
                return {"ok": False, "goal": goal, "steps": steps,
                        "error": "three actions failed in a row — stopping"}

    return {"ok": False, "goal": goal, "steps": steps,
            "error": f"reached the {max_steps}-step limit without finishing"}


# ── registration ─────────────────────────────────────────────────────


def register(agent: Any) -> None:
    """Attach the computer-use tools to the agent.

    READ_ONLY: look, open, screenshot. EXTERNAL_EFFECT (confirmation-gated
    under the single ``computer_use`` skill — one grant covers all):
    click, type, key, menu."""
    from jaeger_os.core.safety.permissions import PermissionTier, requires_tier

    def _gated(tier: PermissionTier, op: str, summary: str):
        return requires_tier(tier, skill="computer_use", operation=op,
                             summary=summary)

    @agent.tool_plain
    @_gated(PermissionTier.READ_ONLY, "look", "read the screen")
    def computer_look() -> dict:
        """Perceive the desktop — the frontmost window's elements AND
        every other open window. Returns {screen, windows}. Look before
        you plan, look to confirm."""
        return look()

    @agent.tool_plain
    @_gated(PermissionTier.READ_ONLY, "capture", "capture the screen")
    def computer_capture(mode: str = "som", path: str = "computer_capture.png") -> dict:
        """Capture the current app for grounding. mode='som' returns a
        screenshot with numbered boxes plus an element index; mode='vision'
        returns a plain screenshot plus indexes; mode='ax' returns only the
        accessibility tree. Prefer SOM indexes for clicks."""
        return capture(mode=mode, path=path)

    @agent.tool_plain
    @_gated(PermissionTier.READ_ONLY, "windows", "list open windows")
    def computer_windows() -> dict:
        """List EVERY open app and its windows, with which is frontmost.
        Use this to find where something is — you can then `computer_open`
        that app to bring it forward. You are not limited to whatever
        window happens to be in front."""
        return list_windows()

    @agent.tool_plain
    @_gated(PermissionTier.READ_ONLY, "open", "open a macOS app")
    def computer_open(app: str) -> dict:
        """Launch or focus a macOS app (e.g. 'Calculator', 'Safari') and
        return what's on its screen, so you can see what to act on."""
        return open_app(name=app)

    @agent.tool_plain
    @_gated(PermissionTier.EXTERNAL_EFFECT, "click", "click an element")
    def computer_click(element: int | None = None, target: str = "") -> dict:
        """Click an element by index from computer_capture/computer_look.
        Prefer element indexes, e.g. computer_click(element=12). `target`
        name matching is kept only as a fallback for older prompts."""
        return click(target=target, element=element)

    @agent.tool_plain
    @_gated(PermissionTier.EXTERNAL_EFFECT, "type", "type text")
    def computer_type(text: str) -> dict:
        """Type `text` into the focused field, then return the screen
        after so you can verify it landed."""
        return type_text(text=text)

    @agent.tool_plain
    @_gated(PermissionTier.EXTERNAL_EFFECT, "key", "press a key")
    def computer_key(key: str) -> dict:
        """Press a key or chord — 'return', 'tab', 'escape', 'cmd+c' —
        then return the screen after."""
        return press_key(key=key)

    @agent.tool_plain
    @_gated(PermissionTier.EXTERNAL_EFFECT, "menu", "click a menu item")
    def computer_menu(menu: str, item: str) -> dict:
        """Click a menu-bar item — computer_menu('File', 'New'). The most
        reliable way to drive an app; returns the screen after."""
        return menu_select(menu=menu, item=item)

    @agent.tool_plain
    @_gated(PermissionTier.READ_ONLY, "screenshot", "capture the screen")
    def computer_screenshot(path: str = "screen.png") -> dict:
        """Save a PNG screenshot under skills/ — for an app the element
        tree can't describe (canvas, video, a game)."""
        return screenshot(path=path)

    @agent.tool_plain
    @_gated(PermissionTier.EXTERNAL_EFFECT, "computer_use", "use the computer")
    def computer_use(
        action: str,
        mode: str = "som",
        app: str = "",
        window: str = "",
        window_index: int | None = None,
        element: int | None = None,
        from_element: int | None = None,
        to_element: int | None = None,
        target: str = "",
        to_target: str = "",
        text: str = "",
        key: str = "",
        menu: str = "",
        item: str = "",
        value: str = "",
        direction: str = "down",
        amount: int = 3,
        path: str = "computer_capture.png",
        seconds: float = 1.0,
        goal: str = "",
        capture_after: bool = False,
    ) -> dict:
        """Primary computer-control tool. Use action='capture' first
        (mode='som') to get numbered elements, then action='click' with
        element=<index>. Supported actions: capture, look, windows,
        list_apps, open, focus_window, click, double_click, right_click,
        scroll, drag, set_value, type, key, menu, screenshot, wait, do.
        Use capture_after=true on actions when visual verification is useful."""
        from jaeger_os.main import _pipeline
        return use_computer(
            action, mode=mode, app=app, window=window,
            window_index=window_index, element=element,
            from_element=from_element, to_element=to_element,
            target=target, to_target=to_target, text=text, key=key,
            menu=menu, item=item, value=value, direction=direction,
            amount=amount, path=path, seconds=seconds, goal=goal,
            capture_after=capture_after,
            client=_pipeline.get("client"),
        )

    @agent.tool_plain
    @_gated(PermissionTier.EXTERNAL_EFFECT, "do", "run a computer-use task")
    def computer_do(goal: str) -> dict:
        """Accomplish a whole computer task end to end. Give it a plain
        goal — "compute 5+5 in Calculator and report the result", "open
        Safari and search for otters". The skill runs its OWN loop with
        the model: it looks at the screen, decides the next action, does
        it, verifies the new screen, and repeats until done.

        Prefer this for ANY multi-step computer task — it plans and
        verifies so you don't have to drive the primitives by hand.
        Returns {ok, goal, steps, result}."""
        from jaeger_os.main import _pipeline
        return run_goal(goal, _pipeline.get("client"))

    # ── Background mode — focus-preserving, no cursor, no focus steal ──
    # The quiet complement to the tools above: drive the Mac as an object
    # tree (Accessibility API) instead of moving the real cursor. The
    # engine is the sibling macos_background.py; skill_loader does not put
    # the skill folder on sys.path, so it is loaded by absolute path.
    def _bg() -> Any:
        import importlib.util
        import pathlib
        import sys as _sys
        key = "_jaeger_macos_background"
        cached = _sys.modules.get(key)
        if cached is not None:
            return cached
        path = pathlib.Path(__file__).resolve().parent / "macos_background.py"
        spec = importlib.util.spec_from_file_location(key, path)
        mod = importlib.util.module_from_spec(spec)
        _sys.modules[key] = mod
        spec.loader.exec_module(mod)
        return mod

    def _bg_audit(op: str, detail: dict) -> None:
        """Record a silent background manipulation in the audit log —
        an op the user cannot see still belongs in the trail."""
        try:
            from jaeger_os.core.tools._common import _audit
            _audit(f"computer_bg_{op}", detail)
        except Exception:  # noqa: BLE001 — audit is best-effort
            pass

    @agent.tool_plain
    @_gated(PermissionTier.READ_ONLY, "bg_apps", "list running apps")
    def computer_bg_apps() -> dict:
        """List every running app with its PID — the starting point for
        background (focus-preserving) automation. Read-only."""
        return _bg().list_running_apps()

    @agent.tool_plain
    @_gated(PermissionTier.READ_ONLY, "bg_windows", "list an app's windows")
    def computer_bg_windows(app: str) -> dict:
        """List an app's windows — index, title, position, size — without
        touching them. Read-only. The index feeds computer_bg_move /
        computer_bg_resize."""
        return _bg().list_windows(app)

    @agent.tool_plain
    @_gated(PermissionTier.EXTERNAL_EFFECT, "bg_move", "move a window silently")
    def computer_bg_move(app: str, x: float, y: float,
                         window_index: int = 0) -> dict:
        """Move a window to (x, y) SILENTLY — it does not come forward,
        the cursor does not move, the user keeps their focus. For
        rearranging windows in the background."""
        res = _bg().move_window(app, x, y, window_index=window_index)
        if res.get("ok"):
            _bg_audit("move", {"app": app, "x": x, "y": y,
                               "window_index": window_index})
        return res

    @agent.tool_plain
    @_gated(PermissionTier.EXTERNAL_EFFECT, "bg_resize", "resize a window silently")
    def computer_bg_resize(app: str, width: float, height: float,
                           window_index: int = 0) -> dict:
        """Resize a window SILENTLY, in place — no focus change, no
        cursor movement."""
        res = _bg().resize_window(app, width, height,
                                  window_index=window_index)
        if res.get("ok"):
            _bg_audit("resize", {"app": app, "width": width,
                                 "height": height,
                                 "window_index": window_index})
        return res

    @agent.tool_plain
    @_gated(PermissionTier.EXTERNAL_EFFECT, "bg_press",
            "press an element in the background")
    def computer_bg_press(app: str, label: str, role: str = "") -> dict:
        """Press a button / menu item in a BACKGROUND window via the
        Accessibility API — no cursor travel, the window need not be
        frontmost. `label` matches the element's title/description;
        `role` ('AXButton', 'AXMenuItem') narrows it."""
        res = _bg().press_element(app, label, role=role)
        if res.get("ok"):
            _bg_audit("press", {"app": app, "label": label, "role": role})
        return res

    @agent.tool_plain
    @_gated(PermissionTier.EXTERNAL_EFFECT, "bg_js",
            "run JavaScript in a background browser tab")
    def computer_bg_js(js: str, browser: str = "Google Chrome",
                       window_index: int = 1, tab_index: int = 1) -> dict:
        """Run JavaScript in a browser tab WITHOUT activating the browser
        — skip a track, click a web control — while the user stays in
        their current app. Chrome/Safari must have 'Allow JavaScript from
        Apple Events' enabled (a clear error says so if not)."""
        res = _bg().run_background_browser_js(
            js, browser=browser, window_index=window_index,
            tab_index=tab_index)
        if res.get("ok"):
            _bg_audit("js", {"browser": browser, "js": js[:200]})
        return res
