"""Categorised memory — remember(category=…) and grouped list_facts.

Memory stays organised: a fact can carry a category ('contacts',
'preferences', …); list_facts_by_category groups them; the flat
list_facts contract is unchanged so existing callers keep working; and
a facts.json written before categories existed still reads cleanly.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jaeger_os.core import memory as mem


@pytest.fixture()
def bound(tmp_path: Path):
    mem.bind(SimpleNamespace(memory_dir=tmp_path / "memory"))
    yield


def test_uncategorised_fact_lands_in_general(bound) -> None:
    mem.remember("sky_color", "blue")
    assert mem.list_facts_by_category() == {"general": {"sky_color": "blue"}}


def test_category_groups_facts(bound) -> None:
    mem.remember("sara_phone", "555-0142", category="contacts")
    mem.remember("fav_color", "teal", category="preferences")
    mem.remember("misc_thing", "whatever")
    grouped = mem.list_facts_by_category()
    assert grouped["contacts"] == {"sara_phone": "555-0142"}
    assert grouped["preferences"] == {"fav_color": "teal"}
    assert grouped["general"] == {"misc_thing": "whatever"}


def test_list_facts_stays_flat_for_back_compat(bound) -> None:
    # Existing callers expect a flat {key: value} map — must not change.
    mem.remember("a", "1", category="contacts")
    mem.remember("b", "2")
    assert mem.list_facts() == {"a": "1", "b": "2"}


def test_recall_works_regardless_of_category(bound) -> None:
    mem.remember("sara_phone", "555-0142", category="contacts")
    assert mem.recall("sara_phone") == "555-0142"


def test_forget_drops_the_category_entry_too(bound) -> None:
    mem.remember("sara_phone", "555-0142", category="contacts")
    assert mem.forget("sara_phone") is True
    assert mem.list_facts_by_category() == {}
    assert mem._read_categories_raw() == {}


def test_general_category_sorts_last(bound) -> None:
    mem.remember("z_fact", "1")                       # general
    mem.remember("a_fact", "2", category="contacts")
    assert list(mem.list_facts_by_category())[-1] == "general"


def test_legacy_flat_facts_file_reads_as_general(bound) -> None:
    # A facts.json from before categories existed — a plain {k: v} doc.
    facts_path = mem._require("facts_path")
    facts_path.parent.mkdir(parents=True, exist_ok=True)
    facts_path.write_text(json.dumps({"old_key": "old_val"}), encoding="utf-8")
    assert mem.list_facts_by_category() == {"general": {"old_key": "old_val"}}
