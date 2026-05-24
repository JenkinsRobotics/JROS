"""Environment preflight — dependency + system-library verification.

pip can't install system libraries (PortAudio) or macOS binaries;
preflight checks the whole surface and reports the exact fix command,
so a missing dependency surfaces at boot, not mid-conversation.
"""

from __future__ import annotations

from jaeger_os.core.runtime.preflight import (
    Check,
    boot_warning,
    check_environment,
    fixable,
    format_report,
    missing,
)


def test_check_environment_covers_every_category():
    checks = check_environment()
    cats = {c.category for c in checks}
    # voice / vision / external / memory / messaging Python deps + system
    for expected in ("voice", "vision", "external", "system"):
        assert expected in cats, expected
    # PortAudio + git are always probed
    names = {c.name for c in checks}
    assert "PortAudio" in names and "git" in names


def test_missing_returns_only_failures():
    checks = [
        Check("a", "voice", ok=True),
        Check("b", "vision", ok=False, fix="pip install x"),
    ]
    bad = missing(checks)
    assert len(bad) == 1 and bad[0].name == "b"


def test_report_clean_when_all_ok():
    report = format_report([Check("a", "voice", ok=True, detail="installed")])
    assert "fully operational" in report
    assert boot_warning([Check("a", "voice", ok=True)]) == ""


def test_report_and_boot_warning_surface_fixes():
    checks = [
        Check("kokoro", "voice", ok=False, detail="not installed",
              fix='pip install "jaeger-os[voice]"',
              fix_cmd=["python", "-m", "pip", "install", "kokoro"]),
        Check("PortAudio", "system", ok=False, detail="native load failed",
              fix="brew install portaudio",
              fix_cmd=["brew", "install", "portaudio"]),
    ]
    report = format_report(checks)
    assert 'pip install "jaeger-os[voice]"' in report
    assert "brew install portaudio" in report

    warning = boot_warning(checks)
    assert "kokoro" in warning and "PortAudio" in warning
    assert "--doctor" in warning  # boot points at the doctor to fix


def test_fixable_dedups_runnable_commands():
    """fixable() returns the runnable argv for each missing check that
    has one — what --doctor offers to run. No fix_cmd → not offered."""
    checks = [
        Check("kokoro", "voice", ok=False,
              fix_cmd=["pip", "install", "kokoro"]),
        Check("kokoro", "voice", ok=False,            # dup → collapsed
              fix_cmd=["pip", "install", "kokoro"]),
        Check("git", "system", ok=False),             # no fix_cmd → skipped
        Check("scipy", "voice", ok=True),             # ok → skipped
    ]
    cmds = fixable(checks)
    assert cmds == [["pip", "install", "kokoro"]]
