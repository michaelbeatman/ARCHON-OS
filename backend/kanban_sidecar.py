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
import logging
import os
import re
import tempfile
import threading
from contextlib import contextmanager

_archon_exc_logger = logging.getLogger("kanban_sidecar")

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KANBAN_META_FILE = os.path.join(WORKSPACE_DIR, "config", "kanban_meta.json")

_LOCK = threading.Lock()


@contextmanager
def _cross_process_lock():
    """D03/HIGH: prozessuebergreifender Lock (Uvicorn-Worker, Cron, CLI).

    Ein threading.Lock schuetzt nur innerhalb EINES Prozesses. Der OS-
    verwaltete SQLite-EXCLUSIVE-Lock wird zusaetzlich gehalten; ist er nicht
    verfuegbar, wird hart abgebrochen statt ungesperrt read-modify-write zu
    fahren (das war die Ursache fuer stillen Sidecar-Datenverlust).
    """
    try:
        from backend.process_lock import try_acquire_loop_lock
    except Exception as exc:
        raise RuntimeError(
            f"[KanbanSidecar] Cross-Prozess-Lock nicht verfuegbar: {exc}"
        ) from exc
    lock = try_acquire_loop_lock("kanban_meta", timeout=5.0)
    if lock is None:
        raise RuntimeError(
            "[KanbanSidecar] Sidecar wird von einem anderen Prozess geschrieben — "
            "Update abgebrochen (kein ungesperrtes Read-Modify-Write)."
        )
    try:
        yield
    finally:
        lock.release()


def _fingerprint():
    """mtime_ns+size als billiger TOCTOU-Guard gegen Fremdschreiber."""
    try:
        st = os.stat(KANBAN_META_FILE)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def load_kanban_meta():
    """Lesen mit harter Ablehnung defekter Bestandsdateien (D03/HIGH).

    Fehlt die Datei, ist eine leere Struktur korrekt. Existiert sie aber und
    ist nicht lesbar/kein Dict, wird abgebrochen: ein transienter Lese- oder
    Parsefehler durfte frueher als ``{"tasks": {}, "wip": {}}`` interpretiert
    und danach atomar zurueckgeschrieben werden — das loeschte den gesamten
    Sidecar dauerhaft.
    """
    if not os.path.exists(KANBAN_META_FILE):
        return {"tasks": {}, "wip": {}}
    try:
        with open(KANBAN_META_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise RuntimeError(
            f"[KanbanSidecar] Meta-Datei nicht lesbar, Update abgebrochen: {e}"
        ) from e
    if not isinstance(data, dict):
        raise RuntimeError(
            "[KanbanSidecar] Meta-Datei enthaelt kein Dict, Update abgebrochen."
        )
    data.setdefault("tasks", {})
    data.setdefault("wip", {})
    return data


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
        try:
            dir_fd = os.open(os.path.dirname(KANBAN_META_FILE), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError as _exc:
            _archon_exc_logger.debug("[kanban_sidecar] Ignorierte Ausnahme (Z.58): %s", _exc)
        raise


def update_kanban_meta(mutator):
    """Laedt, wendet mutator(meta) an, speichert — alles unter EINER Sperre.

    mutator erhaelt das Meta-Dict und gibt optional ein Ergebnis zurueck.
    Rueckgabe: (meta, mutator_ergebnis). Wirft mutator, wird NICHT gespeichert.
    """
    with _LOCK, _cross_process_lock():
        meta = load_kanban_meta()
        before = _fingerprint()
        result = mutator(meta)
        # Plausibilisierung: hat ein Fremdschreiber (ohne unseren Lock)
        # zwischen Lesen und Schreiben die Datei ersetzt, NICHT ueberschreiben.
        if before is not None and _fingerprint() != before:
            raise RuntimeError(
                "[KanbanSidecar] Sidecar wurde waehrend des Updates extern "
                "geaendert — Schreiben abgebrochen (kein Datenverlust)."
            )
        _write_atomic(meta)
        return meta, result


# D16/M5: Der Kanban-Sidecar ist die letzte Systemgrenze, an der ein
# Vault-/Entscheidungs-Artefakt ohne SQLite-Join einem Span zugeordnet werden
# kann. Nur validierte W3C-IDs — nie erfundene Roots.
_TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)
_SPAN_ID_RE = re.compile(r"^[0-9a-f]{16}$", re.IGNORECASE)
_TRACEPARENT_RE = re.compile(
    r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$", re.IGNORECASE
)


def set_task_trace_context(
    task_id,
    *,
    trace_id="",
    span_id="",
    traceparent="",
    source="",
):
    """D16/M5: Trace-Kontext an `meta["tasks"][task_id]["trace"]` anhaengen.

    Idempotent (skippt leere/ungueltige Werte), bestandskompatibel (bestehende
    Task-Eintraege und bereits gespeicherte Trace-Felder bleiben erhalten) und
    laeuft ueber den einzigen Besitzer des Sidecars (`update_kanban_meta`).
    """
    tid = str(task_id or "").strip()
    if not tid:
        return None
    trace: dict = {}
    v_tid = str(trace_id or "").strip().lower()
    v_sid = str(span_id or "").strip().lower()
    v_tp = str(traceparent or "").strip().lower()
    if _TRACE_ID_RE.fullmatch(v_tid):
        trace["trace_id"] = v_tid
    if _SPAN_ID_RE.fullmatch(v_sid):
        trace["span_id"] = v_sid
    if _TRACEPARENT_RE.fullmatch(v_tp):
        trace["traceparent"] = v_tp
    if source:
        trace["source"] = str(source)[:80]
    if not trace:
        return None

    def _mutator(meta):
        tasks = meta.setdefault("tasks", {})
        entry = tasks.get(tid)
        if not isinstance(entry, dict):
            entry = {} if entry in (None, "") else {"value": entry}
        existing = entry.get("trace")
        entry["trace"] = {**(existing if isinstance(existing, dict) else {}), **trace}
        tasks[tid] = entry
        return entry["trace"]

    _meta, result = update_kanban_meta(_mutator)
    return result
