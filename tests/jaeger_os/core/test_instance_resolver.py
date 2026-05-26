"""Resolver priority + wheel-cleanliness — HYGIENE-4 / HYGIENE-5.

0.1.0 lost data both ways: the bundled dir won over ``~/.jaeger/``
whenever it was writable (which is always, on a normal pip install),
and the wheel itself shipped packager-machine state. These tests pin
the fix for both halves so the regression can't sneak back.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from jaeger_os.core.instance import instance as instance_module


# ── HYGIENE-4: resolver priority ────────────────────────────────────


def test_env_var_override_always_wins(tmp_path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "elsewhere"
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(target))
    resolved = instance_module.resolve_instance_dir("default")
    assert resolved == target.resolve()


def test_dev_checkout_picks_bundled_dir(monkeypatch: pytest.MonkeyPatch):
    """When the package is NOT under site-packages, the bundled dir
    wins — matches the live ``src/jaeger_os/`` layout used during dev."""
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    monkeypatch.delenv("JAEGER_INSTANCE_NAME", raising=False)
    # Sanity: the dev checkout where this test runs should NOT be flagged
    # as a pip install.
    assert instance_module.is_pip_installed() is False, (
        "test environment looks like site-packages — adjust fixture"
    )
    resolved = instance_module.resolve_instance_dir("default")
    expected = (instance_module.PACKAGE_ROOT / "instance" / "default").resolve()
    assert resolved == expected


def test_pip_install_prefers_user_root(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """When PACKAGE_ROOT sits under a ``site-packages`` component, the
    resolver MUST pick ``~/.jaeger/`` — never the bundled dir, even if
    the bundled dir is writable. This is the HYGIENE-4 fix."""
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    monkeypatch.delenv("JAEGER_INSTANCE_NAME", raising=False)

    fake_pkg = tmp_path / "venv" / "lib" / "python3.11" / "site-packages" / "jaeger_os"
    fake_pkg.mkdir(parents=True)
    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))
    # ``is_pip_installed()`` reads ``PACKAGE_ROOT`` from module globals
    # on every call, so a plain setattr suffices — no reload needed.
    monkeypatch.setattr(instance_module, "PACKAGE_ROOT", fake_pkg, raising=True)

    assert instance_module.is_pip_installed() is True
    resolved = instance_module.resolve_instance_dir("default")
    expected = (fake_home / ".jaeger" / "default").resolve()
    assert resolved == expected


def test_pip_install_detection_catches_dist_packages(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Debian-style installs put the package under ``dist-packages``;
    that path component should be flagged too."""
    fake_pkg = tmp_path / "usr" / "lib" / "python3" / "dist-packages" / "jaeger_os"
    fake_pkg.mkdir(parents=True)
    monkeypatch.setattr(instance_module, "PACKAGE_ROOT", fake_pkg, raising=True)
    assert instance_module.is_pip_installed() is True


def test_editable_install_still_treated_as_dev(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """``pip install -e .`` resolves the package back to the source
    checkout — no ``site-packages`` ancestor, so it must NOT trigger
    the pip-install branch."""
    fake_pkg = tmp_path / "GITHUB" / "JROS" / "src" / "jaeger_os"
    fake_pkg.mkdir(parents=True)
    monkeypatch.setattr(instance_module, "PACKAGE_ROOT", fake_pkg, raising=True)
    assert instance_module.is_pip_installed() is False


# ── HYGIENE-5: wheel-cleanliness audit ──────────────────────────────


def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for ancestor in [here, *here.parents]:
        if (ancestor / "pyproject.toml").exists() and (ancestor / "scripts").exists():
            return ancestor
    raise RuntimeError("could not locate repo root from test file")


REPO_ROOT = _find_repo_root()


@pytest.fixture(scope="module")
def check_wheel_module():
    """Import ``scripts/check_wheel.py`` without dragging it onto the
    install path — the script is intentionally not under ``src/``."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_check_wheel", REPO_ROOT / "scripts" / "check_wheel.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_fake_wheel(path: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, body in files.items():
            zf.writestr(name, body)


def test_check_wheel_passes_on_clean_skeleton(tmp_path, check_wheel_module):
    wheel = tmp_path / "clean-1.0-py3-none-any.whl"
    _build_fake_wheel(
        wheel,
        {
            "jaeger_os/__init__.py": b"",
            "jaeger_os/instance/.gitignore": b"# skeleton",
            "jaeger_os/instance/README.md": b"# instance",
            "jaeger_os/instance/default/.gitignore": b"# skeleton",
            "jaeger_os/instance/default/memory/.gitkeep": b"",
            "jaeger_os/instance/default/logs/.gitkeep": b"",
            "jaeger_os/instance/default/skills/.gitkeep": b"",
            "jaeger_os/instance/default/credentials/.gitkeep": b"",
        },
    )
    assert check_wheel_module.check_wheel(wheel) == []


@pytest.mark.parametrize(
    "leaked",
    [
        "jaeger_os/instance/default/config.yaml",
        "jaeger_os/instance/default/identity.yaml",
        "jaeger_os/instance/default/manifest.json",
        "jaeger_os/instance/default/memory/episodic.jsonl",
        "jaeger_os/instance/default/memory/facts.json",
        "jaeger_os/instance/default/logs/audit.log",
        "jaeger_os/instance/default/skills/some_skill.py",
        "jaeger_os/instance/default/credentials/external_model_api_key",
        "jaeger_os/instance/default/run/jaeger.pid",
    ],
)
def test_check_wheel_flags_each_banned_file(tmp_path, check_wheel_module, leaked):
    wheel = tmp_path / "dirty-1.0-py3-none-any.whl"
    _build_fake_wheel(
        wheel,
        {
            "jaeger_os/__init__.py": b"",
            "jaeger_os/instance/.gitignore": b"# skeleton",
            "jaeger_os/instance/default/memory/.gitkeep": b"",
            leaked: b"banned",
        },
    )
    assert check_wheel_module.check_wheel(wheel) == [leaked]


def test_check_wheel_main_returns_nonzero_on_dirty(tmp_path, check_wheel_module, capsys):
    wheel = tmp_path / "dirty-1.0-py3-none-any.whl"
    _build_fake_wheel(
        wheel,
        {
            "jaeger_os/instance/default/config.yaml": b"# packager state",
        },
    )
    code = check_wheel_module.main(["check_wheel.py", str(wheel)])
    assert code == 1
    err = capsys.readouterr().err
    assert "config.yaml" in err
