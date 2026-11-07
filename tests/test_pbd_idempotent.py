"""Regressionstest: PbD-Synthese schreibt unveränderte Skills/Skripte nicht neu.

Zweiter Schreiber neben der Voyager-Engine: die Programmier-durch-Demonstration-
Synthese schrieb `Erstellt am: …` (Python-Skript) und `created_at: …` (SKILL.md)
bei jedem Lauf neu. Inhalt identisch, Datei "geändert" — dieselbe Krankheit, nur
mit anderen Header-Schlüsseln.
"""
import os
import time

from backend.computer_use_pbd import _write_if_changed


SCRIPT_TEMPLATE = (
    '# -*- coding: utf-8 -*-\n'
    '"""Autonome Ausführung für Skill: demo\n'
    'Synthetisiert aus Demonstration: Demo\n'
    'Erstellt am: {ts}\n'
    '"""\n'
    'print("hallo")\n'
)

SKILL_TEMPLATE = (
    '---\n'
    'name: demo\n'
    'created_at: {ts}\n'
    '---\n'
    '# Demo\n'
)


def test_same_content_keeps_mtime(tmp_path):
    path = tmp_path / "demo.py"
    first = SCRIPT_TEMPLATE.format(ts="2026-11-05T14:06:05")
    assert _write_if_changed(str(path), first, ("Erstellt am: ",)) is True

    mtime_before = path.stat().st_mtime_ns
    time.sleep(0.05)

    # Zweiter Lauf: identischer Inhalt, nur neuer Zeitstempel
    second = SCRIPT_TEMPLATE.format(ts="2026-11-07T12:40:37")
    assert _write_if_changed(str(path), second, ("Erstellt am: ",)) is False

    assert path.stat().st_mtime_ns == mtime_before, "Datei wurde trotz identischem Inhalt geschrieben"
    assert "2026-11-05T14:06:05" in path.read_text(encoding="utf-8"), "Zeitstempel wurde erneuert"
    assert "2026-11-07T12:40:37" not in path.read_text(encoding="utf-8")


def test_changed_content_is_written(tmp_path):
    path = tmp_path / "demo.py"
    assert _write_if_changed(str(path), SCRIPT_TEMPLATE.format(ts="2026-11-05T14:06:05"), ("Erstellt am: ",))

    changed = SCRIPT_TEMPLATE.format(ts="2026-11-07T12:40:37").replace('print("hallo")', 'print("tschuess")')
    assert _write_if_changed(str(path), changed, ("Erstellt am: ",)) is True

    text = path.read_text(encoding="utf-8")
    assert 'print("tschuess")' in text
    # Auch bei echter Änderung bleibt der ursprüngliche Zeitstempel erhalten.
    assert "2026-11-05T14:06:05" in text


def test_skill_md_uses_created_at_key(tmp_path):
    path = tmp_path / "SKILL.md"
    assert _write_if_changed(str(path), SKILL_TEMPLATE.format(ts="2026-11-05T14:06:05"), ("created_at: ",))
    mtime_before = path.stat().st_mtime_ns
    time.sleep(0.05)

    assert _write_if_changed(str(path), SKILL_TEMPLATE.format(ts="2026-11-07T12:40:37"), ("created_at: ",)) is False
    assert path.stat().st_mtime_ns == mtime_before


def test_new_file_is_created(tmp_path):
    path = tmp_path / "neu.py"
    assert _write_if_changed(str(path), SCRIPT_TEMPLATE.format(ts="2026-11-07"), ("Erstellt am: ",)) is True
    assert os.path.exists(path)