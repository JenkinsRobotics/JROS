"""``jaeger bench compare`` — multi-model bench picker verb.

Pin the discovery + picker + arg-parsing contract. We don't actually
launch the sweep (it's a multi-minute subprocess); instead we stub
``subprocess.call`` and verify the verb assembles the right command.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

from jaeger_os.daemon import bench_compare_verb as bcv


# ── _discover_models ─────────────────────────────────────────────


def _make_gguf(parent: pathlib.Path, name: str, size_bytes: int = 1024):
    p = parent / name
    p.write_bytes(b"x" * size_bytes)
    return p


@pytest.fixture
def _isolate_default_dirs(monkeypatch):
    """Hide the real ``~/.lmstudio/models/`` directory from discovery
    so tests only see what they put in ``extra_dirs``. Required: the
    dev machine running this test suite has real models on disk."""
    monkeypatch.setattr(bcv, "_DEFAULT_MODEL_DIRS", ())
    monkeypatch.setattr(bcv, "_config_extra_gguf_dirs", lambda **_kw: [])
    return monkeypatch


def test_discover_models_finds_gguf_in_extra_dirs(tmp_path, _isolate_default_dirs):
    """Models living under ``--extra-dirs`` are discovered."""
    d = tmp_path / "model_zoo"
    d.mkdir()
    _make_gguf(d, "alpha-7b.gguf")
    _make_gguf(d, "beta-13b.gguf")

    out = bcv._discover_models(extra_dirs=[str(d)], instance_name=None)
    names = sorted(pathlib.Path(p).name for p in out)
    assert names == ["alpha-7b.gguf", "beta-13b.gguf"]


def test_discover_models_skips_mmproj_sidecars(tmp_path, _isolate_default_dirs):
    """Multimodal projection files share the .gguf suffix but aren't
    chat models — discovery must skip them."""
    d = tmp_path / "models"
    d.mkdir()
    _make_gguf(d, "gemma-4-E4B-it-Q4.gguf")
    _make_gguf(d, "mmproj-gemma-4-E4B-it-BF16.gguf")
    _make_gguf(d, "projector-anything.gguf")

    out = bcv._discover_models(extra_dirs=[str(d)], instance_name=None)
    names = {pathlib.Path(p).name for p in out}
    assert names == {"gemma-4-E4B-it-Q4.gguf"}


def test_discover_models_recurses_into_subdirs(tmp_path, _isolate_default_dirs):
    """LM Studio stores models under ``vendor/model-name/file.gguf`` —
    discovery must walk subdirs to find them."""
    nested = tmp_path / "vendor" / "gemma-4-26B"
    nested.mkdir(parents=True)
    _make_gguf(nested, "gemma-4-26B-Q4.gguf")

    out = bcv._discover_models(extra_dirs=[str(tmp_path)], instance_name=None)
    assert len(out) == 1
    assert "gemma-4-26B-Q4.gguf" in out[0]


def test_discover_models_returns_sorted_for_stable_picker(tmp_path, _isolate_default_dirs):
    """Numbered picker → stable numbering requires sorted output."""
    d = tmp_path / "m"
    d.mkdir()
    _make_gguf(d, "z.gguf")
    _make_gguf(d, "a.gguf")
    _make_gguf(d, "m.gguf")

    out = bcv._discover_models(extra_dirs=[str(d)], instance_name=None)
    names = [pathlib.Path(p).name for p in out]
    assert names == ["a.gguf", "m.gguf", "z.gguf"]


def test_discover_models_handles_missing_dir_silently(tmp_path, _isolate_default_dirs):
    """A non-existent extra-dir must not crash discovery."""
    out = bcv._discover_models(
        extra_dirs=[str(tmp_path / "does_not_exist")],
        instance_name=None,
    )
    assert out == []


# ── _interactive_pick ────────────────────────────────────────────


def test_picker_returns_empty_on_blank_input(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")
    out = bcv._interactive_pick(["/a.gguf", "/b.gguf"], current=None)
    assert out == []


def test_picker_returns_empty_on_ctrl_c(monkeypatch):
    def _raise(_=""):
        raise KeyboardInterrupt
    monkeypatch.setattr("builtins.input", _raise)
    out = bcv._interactive_pick(["/a.gguf"], current=None)
    assert out == []


def test_picker_all_returns_every_model(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _="": "all")
    out = bcv._interactive_pick(["/a.gguf", "/b.gguf"], current=None)
    assert out == ["/a.gguf", "/b.gguf"]


def test_picker_current_returns_active_only(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _="": "current")
    out = bcv._interactive_pick(
        ["/a.gguf", "/b.gguf"], current="/b.gguf",
    )
    assert out == ["/b.gguf"]


def test_picker_current_with_no_active_returns_empty(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _="": "current")
    out = bcv._interactive_pick(["/a.gguf"], current=None)
    assert out == []


def test_picker_comma_separated_indices(monkeypatch, capsys):
    """1-based, comma-separated."""
    monkeypatch.setattr("builtins.input", lambda _="": "1,3")
    out = bcv._interactive_pick(
        ["/a.gguf", "/b.gguf", "/c.gguf"], current=None,
    )
    assert out == ["/a.gguf", "/c.gguf"]


def test_picker_skips_non_numeric_input(monkeypatch, capsys):
    """Non-numeric chunks are skipped, valid ones still go through."""
    monkeypatch.setattr("builtins.input", lambda _="": "1, oops, 2")
    out = bcv._interactive_pick(["/a.gguf", "/b.gguf"], current=None)
    assert out == ["/a.gguf", "/b.gguf"]


def test_picker_skips_out_of_range(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _="": "1, 99")
    out = bcv._interactive_pick(["/a.gguf"], current=None)
    assert out == ["/a.gguf"]


def test_picker_dedupes_preserving_order(monkeypatch, capsys):
    """``1,2,1`` selects 2 unique models, in input order."""
    monkeypatch.setattr("builtins.input", lambda _="": "2,1,2")
    out = bcv._interactive_pick(["/a.gguf", "/b.gguf"], current=None)
    assert out == ["/b.gguf", "/a.gguf"]


# ── _resolve_paths ───────────────────────────────────────────────


def test_resolve_paths_keeps_existing(tmp_path):
    p = _make_gguf(tmp_path, "x.gguf")
    out = bcv._resolve_paths([str(p)])
    assert out == [str(p.resolve())]


def test_resolve_paths_drops_missing(tmp_path, capsys):
    out = bcv._resolve_paths([str(tmp_path / "ghost.gguf")])
    err = capsys.readouterr().err
    assert out == []
    assert "not found" in err


# ── argv dispatch ────────────────────────────────────────────────


def test_compare_help_returns_zero(capsys):
    rc = bcv._cmd_bench_compare_argv(["-h"])
    err = capsys.readouterr().err
    assert rc == 0
    assert "compare" in err.lower()
    assert "--models" in err


def test_compare_models_flag_skips_picker(tmp_path, monkeypatch, capsys):
    """Passing ``--models PATH,PATH`` bypasses the picker entirely.
    With ``--dry-run`` the sweep is not launched."""
    m1 = _make_gguf(tmp_path, "alpha.gguf")
    m2 = _make_gguf(tmp_path, "beta.gguf")
    # Picker must NOT be called when --models is given.
    monkeypatch.setattr(
        bcv, "_interactive_pick",
        lambda *_a, **_kw: pytest.fail("picker should not run with --models"),
    )
    rc = bcv._cmd_bench_compare_argv(
        ["--models", f"{m1},{m2}", "--dry-run"],
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "alpha.gguf" in out
    assert "beta.gguf" in out
    assert "dry-run" in out


def test_compare_dry_run_does_not_launch_subprocess(tmp_path, monkeypatch):
    """``--dry-run`` must not actually invoke the sweep — guard against
    accidental long-running spawns in CI."""
    m = _make_gguf(tmp_path, "x.gguf")
    called = {"flag": False}
    def _spy(*_a, **_kw):
        called["flag"] = True
        return 0
    monkeypatch.setattr(bcv.subprocess, "call", _spy)
    bcv._cmd_bench_compare_argv(["--models", str(m), "--dry-run"])
    assert called["flag"] is False


def test_compare_no_models_discovered_returns_one(tmp_path, monkeypatch, capsys):
    """Empty model dir + no --models flag → useful error, rc=1."""
    monkeypatch.setattr(
        bcv, "_DEFAULT_MODEL_DIRS", (str(tmp_path / "empty"),),
    )
    monkeypatch.setattr(
        bcv, "_config_extra_gguf_dirs", lambda **_: [],
    )
    rc = bcv._cmd_bench_compare_argv([])
    err = capsys.readouterr().err
    assert rc == 1
    assert "no .gguf" in err.lower()


def test_compare_picker_cancelled_returns_two(tmp_path, monkeypatch, capsys):
    """Blank picker input → user cancelled → rc=2 (matches the
    ``bad-input`` convention from argparse)."""
    d = tmp_path / "models"
    d.mkdir()
    _make_gguf(d, "alpha.gguf")
    monkeypatch.setattr(
        bcv, "_DEFAULT_MODEL_DIRS", (str(d),),
    )
    monkeypatch.setattr(
        bcv, "_config_extra_gguf_dirs", lambda **_: [],
    )
    monkeypatch.setattr(
        bcv, "_current_model_path", lambda **_: None,
    )
    monkeypatch.setattr("builtins.input", lambda _="": "")
    rc = bcv._cmd_bench_compare_argv([])
    err = capsys.readouterr().err
    assert rc == 2
    assert "cancelled" in err.lower()


def test_compare_forwards_tags_and_limit_via_env(tmp_path, monkeypatch, capsys):
    """``--tags`` / ``--limit`` get passed to the sweep script via env
    vars (the sweep forwards them to the inner ``run_flat_bench``)."""
    m = _make_gguf(tmp_path, "x.gguf")
    captured: dict[str, str] = {}
    def _spy(cmd, env=None, **_kw):
        if env is not None:
            captured["TAGS"] = env.get("JAEGER_BENCH_TAGS", "")
            captured["LIMIT"] = env.get("JAEGER_BENCH_LIMIT", "")
        return 0
    monkeypatch.setattr(bcv.subprocess, "call", _spy)
    # _repo_root must point at something with benchmark/run_model_sweep.py
    # — patch it to use the real repo so the "missing script" branch
    # doesn't fire.
    real_repo = pathlib.Path(__file__).resolve().parents[3]
    monkeypatch.setattr(bcv, "_repo_root", lambda: real_repo)
    rc = bcv._cmd_bench_compare_argv([
        "--models", str(m),
        "--tags", "routing,memory",
        "--limit", "5",
    ])
    assert rc == 0
    assert captured["TAGS"] == "routing,memory"
    assert captured["LIMIT"] == "5"


# ── dispatcher integration ───────────────────────────────────────


def test_cli_bench_dispatcher_routes_compare(monkeypatch):
    """``jaeger bench compare`` must route to the verb implementation
    inside the existing bench dispatcher."""
    from jaeger_os.daemon import cli
    captured: list[list[str]] = []
    def _spy(argv):
        captured.append(argv)
        return 0
    monkeypatch.setattr(
        "jaeger_os.daemon.bench_compare_verb._cmd_bench_compare_argv", _spy,
    )
    rc = cli._cmd_bench(["compare", "--dry-run"])
    assert rc == 0
    assert captured == [["--dry-run"]]
