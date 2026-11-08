"""Cluster Spur A — utils/notebook_engine.py (D-19).

Rot gegen 3269f7e1:

* D-19: ``query_notebook`` las ``notebooks.json`` VOR dem LLM-``await`` und
  schrieb den alten Snapshot danach zurueck. Quellen oder parallele
  Chat-Turns, die waehrend der Synthese hinzukamen, wurden ueberschrieben
  (Lost Update). ``save_notebooks_data`` schrieb zudem direkt in die
  Zieldatei (kein tmp+replace) — ein Abbruch hinterliess eine kaputte Datei.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(os.environ.get("ARCHON_ROOT") or Path(__file__).resolve().parent.parent)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import utils.notebook_engine as ne  # noqa: E402


@pytest.fixture()
def notebook_store(tmp_path, monkeypatch):
    target = tmp_path / "notebooks.json"
    monkeypatch.setattr(ne, "NOTEBOOKS_FILE", str(target))
    return target


def _seed(path: Path, data: dict):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_chatverlauf_ueberschreibt_keine_parallelen_aenderungen(notebook_store, monkeypatch):
    """Waehrend der Synthese hinzugefuegte Quellen muessen erhalten bleiben."""
    _seed(notebook_store, {
        "nb1": {"id": "nb1", "name": "NB", "sources": [{"title": "A"}], "chat_history": []}
    })

    async def slow_llm(prompt, chunks, citations):
        # Waehrend der Synthese legt ein anderer Vorgang eine Quelle ab
        # und speichert einen weiteren Chat-Turn.
        current = json.loads(notebook_store.read_text(encoding="utf-8"))
        current["nb1"]["sources"].append({"title": "B"})
        current["nb1"]["chat_history"].append({"role": "user", "content": "parallel"})
        notebook_store.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
        await asyncio.sleep(0)
        return "Antwort"

    monkeypatch.setattr(ne, "generate_grounded_llm_response", slow_llm)
    monkeypatch.setattr(ne, "perform_grounded_retrieval", lambda nb, prompt: ([], []))

    result = asyncio.run(ne.query_notebook("nb1", "Frage"))

    assert result["response"] == "Antwort"
    stored = json.loads(notebook_store.read_text(encoding="utf-8"))
    titles = [s.get("title") for s in stored["nb1"]["sources"]]
    assert titles == ["A", "B"], f"parallel hinzugefuegte Quelle ging verloren: {titles}"
    roles = [m.get("content") for m in stored["nb1"]["chat_history"]]
    assert "parallel" in roles, "paralleler Chat-Turn ging verloren"
    assert "Frage" in roles and "Antwort" in roles, "eigene Nachricht fehlt"


def test_chatverlauf_haengt_an_den_aktuellen_stand_an(notebook_store):
    _seed(notebook_store, {
        "nb1": {"id": "nb1", "sources": [], "chat_history": [{"role": "user", "content": "x"}]}
    })

    ne._append_chat_history("nb1", [{"role": "assistant", "content": "y"}])

    stored = json.loads(notebook_store.read_text(encoding="utf-8"))
    assert [m["content"] for m in stored["nb1"]["chat_history"]] == ["x", "y"]


def test_speichern_ist_atomar(notebook_store, monkeypatch):
    _seed(notebook_store, {"nb1": {"id": "nb1", "chat_history": []}})

    def boom(*_args, **_kwargs):
        raise RuntimeError("Platte voll")

    monkeypatch.setattr(ne.os, "replace", boom)
    with pytest.raises(RuntimeError):
        ne.save_notebooks_data({"nb1": {"id": "nb1", "chat_history": []}})

    # Zieldatei unveraendert, keine Temp-Reste
    stored = json.loads(notebook_store.read_text(encoding="utf-8"))
    assert stored["nb1"]["chat_history"] == []
    leftovers = [p.name for p in notebook_store.parent.iterdir() if p.name.startswith("notebooks.json.tmp")]
    assert leftovers == [], f"Temp-Dateien liegen herum: {leftovers}"


def test_speichern_legt_keine_tmp_datei_bei_erfolg(notebook_store):
    ne.save_notebooks_data({"nb1": {"id": "nb1", "chat_history": []}})
    leftovers = [p.name for p in notebook_store.parent.iterdir() if p.name.startswith("notebooks.json.tmp")]
    assert leftovers == []
    assert json.loads(notebook_store.read_text(encoding="utf-8"))["nb1"]["id"] == "nb1"
