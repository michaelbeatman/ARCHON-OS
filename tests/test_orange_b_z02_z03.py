"""Regressionstests Z-02 + Z-03 fuer archon/routers/templates.py.

Z-02: Template-IDs kollidierten im 100-Sekunden-Takt
(int(time.time()*1000) % 100000) — zwei Vorlagen im selben Fenster teilten die
ID und /schema + /render lieferten die falsche Vorlage.

Z-03: Der Save schrieb vier Ziele (Fehler einzeln geschluckt) und meldete
immer ok, gelesen wurde nur die erste existierende Datei.
"""

import json
import os
import sys
from unittest import mock

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archon.routers import templates as tpl  # noqa: E402
from archon.routers.templates import (  # noqa: E402
    TemplateSaveRequest,
    _load_prompt_templates,
    _save_prompt_templates,
    save_prompt_template,
)


# ---------------------------------------------------------------- Z-02

@pytest.mark.asyncio
async def test_template_ids_are_unique_even_in_same_window(tmp_path):
    store = tmp_path / "prompt_templates.json"
    store.write_text(json.dumps({"categories": ["Strategie & Business"], "templates": []}), encoding="utf-8")
    with mock.patch.object(tpl, "require_admin_or_503", return_value=None), \
         mock.patch.object(tpl, "PROMPT_TEMPLATES_PATHS", [str(store)]):
        ids = set()
        for i in range(8):
            req = TemplateSaveRequest(
                category="Strategie & Business", title=f"Vorlage {i}",
                fields={}, raw_text=f"text {i}"
            )
            res = await save_prompt_template(mock.Mock(), req)
            ids.add(res["template"]["id"])
    assert len(ids) == 8


@pytest.mark.asyncio
async def test_template_id_not_derived_from_short_modulo():
    """Der Modulo-Wertebereich (100000) darf nicht mehr als ID-Quelle dienen."""
    import ast
    import inspect
    src = inspect.getsource(tpl.save_prompt_template)
    tree = ast.parse(src)
    # Kein Ausdruck der Form `... % 100000` im Funktionsrumpf.
    assert not any(
        isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mod)
        and isinstance(n.right, ast.Constant) and n.right.value == 100000
        for n in ast.walk(tree)
    )


# ---------------------------------------------------------------- Z-03

def test_save_writes_only_to_the_file_the_reader_uses(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps({"templates": []}), encoding="utf-8")

    paths = [str(a), str(b), os.path.join(tmp_path.name, "c.json")]
    with mock.patch.object(tpl, "PROMPT_TEMPLATES_PATHS", paths):
        target = _save_prompt_templates({"templates": [{"id": "x"}]})

    assert target == str(a)
    assert not b.exists(), "Z-03: es darf nur das Leseziel beschrieben werden"
    with open(a, "r", encoding="utf-8") as f:
        assert json.load(f)["templates"][0]["id"] == "x"


@pytest.mark.asyncio
async def test_save_failure_returns_503_not_ok():
    with mock.patch.object(tpl, "require_admin_or_503", return_value=None), \
         mock.patch.object(tpl, "_save_prompt_templates", side_effect=OSError("read-only volume")):
        req = TemplateSaveRequest(category="c", title="T", fields={}, raw_text="x")
        with pytest.raises(HTTPException) as e:
            await save_prompt_template(mock.Mock(), req)
    assert e.value.status_code == 503


def test_load_and_save_target_are_consistent(tmp_path):
    """Bei mehreren vorhandenen Dateien liest und schreibt der Save dieselbe."""
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps({"templates": [{"id": "alt"}]}), encoding="utf-8")
    b.write_text(json.dumps({"templates": [{"id": "b"}]}), encoding="utf-8")

    with mock.patch.object(tpl, "PROMPT_TEMPLATES_PATHS", [str(a), str(b)]):
        gelesen = _load_prompt_templates()
        assert gelesen["templates"][0]["id"] == "alt"
        target = _save_prompt_templates(gelesen)
        assert target == str(a)
    with open(a, "r", encoding="utf-8") as f:
        assert json.load(f)["templates"][0]["id"] == "alt"
