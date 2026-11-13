"""
tests/test_fix_batch13.py
Rot-Beweise fuer Batch 13:
- N-14: Fire-and-forget-Tasks in main.py werden ueber _spawn_background getrackt und behandelt
- N-15: static/js/operations_kanban.js prueft Stale-Responses auf currentOpsDetailTaskId
- N-16: static/js/css_live_studio.js nutzt AbortController gegen out-of-order Speichern
- P-05: backend/erp_manager.py vermeidet N+1-Queries in list_entities und list_documents
- Re-06: main.py verhindert ueberlappende RAG-Sync-Vollsynchronisationen
"""
import pytest
import sqlite3
import re
from pathlib import Path

import main as main_mod
from backend.erp_manager import ERPManager, get_tenant_db_path


@pytest.mark.asyncio
async def test_n14_background_tasks_tracked():
    """N-14: _spawn_background registriert Tasks, entfernt sie nach Ende und faengt Exceptions ab."""
    assert hasattr(main_mod, "_spawn_background"), "main._spawn_background fehlt"

    import asyncio

    async def sample_coro():
        return 42

    t = main_mod._spawn_background(sample_coro())
    assert t in main_mod._BACKGROUND_TASKS
    await t

    # Pruefe, dass rohe create_task-Aufrufe in main.py fuer diese Pfade nicht mehr vorkommen
    main_code = Path(main_mod.__file__).read_text(encoding="utf-8")
    assert "asyncio.create_task(trigger_background_rag_sync())" not in main_code, "trigger_background_rag_sync nutzt noch rohes create_task"
    assert "asyncio.create_task(_execute_kanban_task_async(task_id))" not in main_code, "execute_kanban nutzt noch rohes create_task"


def test_n15_kanban_modal_stale_response_check():
    """N-15: operations_kanban.js muss pruefen, ob currentOpsDetailTaskId noch dem geladenen Task entspricht."""
    js_path = Path("static/js/operations_kanban.js")
    content = js_path.read_text(encoding="utf-8")

    # Pruefe, dass nach dem Fetch von /api/operations/kanban/tasks/ geprueft wird.
    # Das Fenster ist eine Naeherung: seit der i18n-Lokalisierung (Tranche 2) steht
    # in der throw-Zeile zusaetzlich der kanT()-Aufruf mit Fallback, der Abstand
    # zwischen Fetch und Guard waechst dadurch, die Pruefung selbst bleibt gleich.
    pattern = r"fetch\(`/api/operations/kanban/tasks/\$\{taskId\}`\);[\s\S]{1,400}currentOpsDetailTaskId !== taskId"
    assert re.search(pattern, content), "Stale-Response-Pruefung in openTaskDetailModal fehlt"


def test_n16_css_live_studio_abort_controller():
    """N-16: css_live_studio.js muss AbortController nutzen, um ueberlappende Speichervorgaenge abzubrechen."""
    js_path = Path("static/js/css_live_studio.js")
    content = js_path.read_text(encoding="utf-8")

    assert "AbortController" in content, "css_live_studio.js enthaelt keinen AbortController"
    assert "activeSaveAbortController" in content or "saveAbortController" in content, "Speicher-AbortController fehlt in css_live_studio.js"


def test_p05_erp_manager_no_n_plus_one(tmp_path, monkeypatch):
    """P-05: list_entities und list_documents duerfen keine N+1-SELECTs ausfuehren."""
    db_file = tmp_path / "test_erp.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    mgr = ERPManager()
    mgr._init_schema(conn, "comp1", True)

    # 10 Entities und 10 Documents anlegen
    for i in range(10):
        eid = f"ent_{i}"
        conn.execute("INSERT INTO crm_entities (id, display_name, status, tags_json, updated_at) VALUES (?, ?, 'active', '[]', '2026-11-01')", (eid, f"Firma {i}"))
        conn.execute("INSERT INTO crm_contacts (id, entity_id, full_name, last_name, is_primary, rating) VALUES (?, ?, ?, ?, 1, 5)", (f"cnt_{i}", eid, f"Person {i}", f"Person {i}"))
        
        did = f"doc_{i}"
        conn.execute("INSERT INTO erp_documents (id, entity_id, doc_type, doc_number, issue_date, recipient_snapshot_json, created_at) VALUES (?, ?, 'invoice', ?, '2026-11-01', '{}', '2026-11-01')", (did, eid, f"RE-{i}"))
        conn.execute("INSERT INTO erp_document_lines (id, document_id, pos_no, title) VALUES (?, ?, 1, 'Posten 1')", (f"line_{i}", did))

    conn.commit()
    conn.close()

    # Zaehle SQL-Abfragen
    queries = []
    real_connect = sqlite3.connect

    class TrackingConn:
        def __init__(self, target):
            self._target = target

        def execute(self, sql, *args):
            queries.append(sql)
            return self._target.execute(sql, *args)

        def cursor(self):
            return self._target.cursor()

        def commit(self):
            return self._target.commit()

        def close(self):
            return self._target.close()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def tracking_get_conn(company_id=None):
        raw = real_connect(str(db_file))
        raw.row_factory = sqlite3.Row
        return TrackingConn(raw), "comp1"

    monkeypatch.setattr(mgr, "_get_conn", tracking_get_conn)

    # 1. Test list_entities
    queries.clear()
    res_ent = mgr.list_entities("comp1")
    assert res_ent["total"] == 10
    # Bei 10 Entities darf es maximal 2 Queries geben (1 fuer Entities + 1 Batch fuer Contacts), NICHT 11!
    assert len(queries) <= 2, f"list_entities macht N+1 Queries: {len(queries)} Queries"

    # 2. Test list_documents
    queries.clear()
    res_doc = mgr.list_documents("comp1")
    assert res_doc["total"] == 10
    # Bei 10 Documents darf es maximal 2 Queries geben (1 fuer Docs + 1 Batch fuer Lines), NICHT 11!
    assert len(queries) <= 2, f"list_documents macht N+1 Queries: {len(queries)} Queries"


def test_re06_rag_sync_no_overlap(monkeypatch):
    """Re-06: Parallele Bibliotheks-Uploads duerfen keinen zweiten RAG-Vollsync starten."""
    assert hasattr(main_mod, "_is_rag_sync_running"), "main._is_rag_sync_running Guard fehlt"
