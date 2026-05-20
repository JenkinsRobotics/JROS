"""edit_file + search_files + paginated file_read.

The 2026-05 Hermes-parity pass added two file tools the framework was
missing: a surgical find/replace edit (``edit_file``, ≈ Hermes
``patch``) and a recursive content grep (``search_files``, ≈ Hermes
``search_files``). ``file_read`` also gained line-range pagination.

``edit_file`` directly mitigates the truncated-overwrite failure mode:
changing one region of a long file no longer means regenerating — and
risking losing — the whole thing.
"""

from __future__ import annotations

import pytest

from jaeger_os.core import tools
from jaeger_os.core.instance import InstanceLayout


@pytest.fixture()
def bound_instance(tmp_path):
    """A temp instance with tools bound to it. Yields the layout."""
    layout = InstanceLayout(root=tmp_path / "inst")
    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    tools.bind(layout)
    return layout


# ── edit_file ────────────────────────────────────────────────────────


def test_edit_file_replaces_unique_snippet(bound_instance):
    tools.file_write("m.py", "x = 1\ny = 2\n")
    result = tools.edit_file("m.py", "y = 2", "y = 99")
    assert result["edited"] is True
    assert result["replacements"] == 1
    assert tools.file_read("skills/m.py")["content"] == "x = 1\ny = 99\n"


def test_edit_file_rejects_missing_old(bound_instance):
    tools.file_write("m.py", "x = 1\n")
    result = tools.edit_file("m.py", "nope", "z")
    assert result["edited"] is False
    assert "not found" in result["error"]


def test_edit_file_rejects_ambiguous_old(bound_instance):
    tools.file_write("m.py", "a = 0\na = 0\n")
    result = tools.edit_file("m.py", "a = 0", "a = 1")
    assert result["edited"] is False
    assert "not unique" in result["error"]


def test_edit_file_replace_all(bound_instance):
    tools.file_write("m.py", "a = 0\na = 0\n")
    result = tools.edit_file("m.py", "a = 0", "a = 1", replace_all=True)
    assert result["edited"] is True
    assert result["replacements"] == 2
    assert tools.file_read("skills/m.py")["content"] == "a = 1\na = 1\n"


def test_edit_file_runs_syntax_check(bound_instance):
    tools.file_write("m.py", "value = 1\n")
    result = tools.edit_file("m.py", "value = 1", "value = (")
    assert result["edited"] is True
    assert result["syntax_ok"] is False


def test_edit_file_rejects_sandbox_escape(bound_instance):
    result = tools.edit_file("../identity.yaml", "a", "b")
    assert result["edited"] is False


# ── search_files ─────────────────────────────────────────────────────


def test_search_files_finds_content(bound_instance):
    tools.file_write("a.py", "def hello():\n    return 1\n")
    tools.file_write("b.py", "def world():\n    return 2\n")
    result = tools.search_files("def hello")
    assert result["searched"] is True
    assert result["count"] == 1
    assert result["matches"][0]["file"].endswith("a.py")
    assert result["matches"][0]["line"] == 1


def test_search_files_is_case_insensitive(bound_instance):
    tools.file_write("a.py", "RETURN_VALUE = 7\n")
    assert tools.search_files("return_value")["count"] == 1


def test_search_files_empty_query(bound_instance):
    assert tools.search_files("")["searched"] is False


# ── file_read pagination ─────────────────────────────────────────────


def test_file_read_pagination(bound_instance):
    tools.file_write("big.txt", "".join(f"line{i}\n" for i in range(100)))
    page = tools.file_read("skills/big.txt", offset=10, limit=5)
    assert page["read"] is True
    assert page["content"] == "line10\nline11\nline12\nline13\nline14\n"
    assert page["total_lines"] == 100
    assert page["offset"] == 10


def test_file_read_whole_file_unchanged(bound_instance):
    """No offset/limit → original behaviour, no pagination keys."""
    tools.file_write("s.txt", "hello\n")
    result = tools.file_read("skills/s.txt")
    assert result["content"] == "hello\n"
    assert "total_lines" not in result
