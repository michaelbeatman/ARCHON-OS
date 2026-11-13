"""
backend/kanban_sidecar.py — EINZIGER Besitzer der Sidecar-Datei config/kanban_meta.json.

Fix Punkt 1 (12.10.2026, Datenrisiko): Zwei Schreiber machten read-modify-write
ohne Sperre — backend/operations_api.py (Endpoint POST /api/operations/kanban/meta)
und backend/post_task_pipeline.py (direkter Dateizugriff). Bei parallelem Fan-in
konnten Entscheidungs-Metadaten verlorengehen (A liest, B liest, A schreibt,
B schreibt drueber). Zusaetzlich war das Schreiben nicht atomar.

Regeln:
- ALLE Load-Aendern-Speichern-Sequenzen laufen ueber update_kanban_meta(fn)
  unter einem prozessweiten threading.Lock (ein Prozess = ein Schreiberprozess).
- Schreiben ist atomar: Temp-Datei im SELBEN Verzeichnis + fsync + os.replace.
- Die Engine-DB (kanban.db) bleibt unberuehrt — nur der Sidecar.
- Dieses Modul importiert NICHTS aus backend (Blatt-Modul, keine Zyklen).
"""

import json
import os
import tempfile
import threading

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KANBAN_META_FILE = os.path.join(WORKSPACE_DIR, "config", "kanban_meta.json")

_LOCK = threading.Lock()


def load_kanban_meta():
    """Tolerantes Lesen (defekte/leere Datei -> leere Struktur, nie Exception)."""
    if os.path.exists(KANBAN_META_FILE):
        try:
            with open(KANBAN_META_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("tasks", {})
                data.setdefault("wip", {})
                return data
        except Exception as e:
            print(f"[KanbanSidecar] meta load error: {e}")
    return {"tasks": {}, "wip": {}}


def _write_atomic(meta):
    """Atomares Schreiben: Temp-Datei + fsync + os.replace (kein Halbstand)."""
    os.makedirs(os.path.dirname(KANBAN_META_FILE), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(KANBAN_META_FILE),
                               prefix=".kanban_meta_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, KANBAN_META_FILE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def update_kanban_meta(mutator):
    """Laedt, wendet mutator(meta) an, speichert — alles unter EINER Sperre.

    mutator erhaelt das Meta-Dict und gibt optional ein Ergebnis zurueck.
    Rueckgabe: (meta, mutator_ergebnis). Wirft mutator, wird NICHT gespeichert.
    """
    with _LOCK:
        meta = load_kanban_meta()
        result = mutator(meta)
        _write_atomic(meta)
        return meta, result
