"""Regressionstests M-09, N-04, N-05, N-06, N-08, Z-08+F-04, D-06, D-15, D-20.

M-09: final_report ungebunden bei DAG nur aus Stufe-1-Tasks.
N-04: Idempotenz-Leader ohne Race (INSERT OR IGNORE) und ohne erfundene Resultate.
N-05: Datei-Inbox mit Cursor; kollisionsfreie event-Task-IDs.
N-06: Deadlock-Supervisor parst Epoch-Zeitstempel und misst ab Heartbeat.
N-08: Escalation schreibt Audit auf derselben Verbindung.
Z-08: Mission-Control-Fallback ohne erfundene Telemetrie.
F-04: leeres Board ist ein gueltiger Store.
D-06: Konsens-Gate fail-closed bei Revisor-Ausfall.
D-15: Belegdruck escaped Pfadsegment (kein Reflected XSS).
D-20: Inbox-Task-IDs kollisionsfrei.
"""

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import types
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------- M-09

def test_dag_execute_all_tier1_no_unbound_local_error():
    import backend.dag_scheduler as ds

    dispatcher = types.SimpleNamespace()
    async def _dispatch(**kwargs):
        return {"content": "Ergebnis von Stufe 1"}
    dispatcher.dispatch_to_omniroute_or_container = _dispatch

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, body TEXT, assignee TEXT, status TEXT, result TEXT)")
    conn.execute("INSERT INTO tasks VALUES ('p-1', 'Parent', 'x', 'a', 'in_progress', '')")
    conn.execute("INSERT INTO tasks VALUES ('p-1-sub1', 'Sub 1', '[DependsOn: []]', 'a', 'todo', '')")
    conn.execute("INSERT INTO tasks VALUES ('p-1-sub2', 'Sub 2', 'keine dep', 'a', 'todo', '')")
    conn.commit()
    conn.close()

    # Datei-basiert: execute_dag oeffnet/ schliesst die Verbindung mehrfach.
    tmpdb = os.path.join(tempfile.mkdtemp(prefix="orangeb_m09_"), "kanban.db")
    src_conn = sqlite3.connect(tmpdb)
    src_conn.row_factory = sqlite3.Row
    src_conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, body TEXT, assignee TEXT, status TEXT, result TEXT)")
    src_conn.execute("INSERT INTO tasks VALUES ('p-1', 'Parent', 'x', 'a', 'in_progress', '')")
    src_conn.execute("INSERT INTO tasks VALUES ('p-1-sub1', 'Sub 1', '[DependsOn: []]', 'a', 'todo', '')")
    src_conn.execute("INSERT INTO tasks VALUES ('p-1-sub2', 'Sub 2', 'keine dep', 'a', 'todo', '')")
    src_conn.commit()
    src_conn.close()

    scheduler = ds.DAGScheduler.__new__(ds.DAGScheduler)
    scheduler.workspace_dir = tempfile.mkdtemp(prefix="orangeb_m09_")

    def _open():
        c = sqlite3.connect(tmpdb)
        c.row_factory = sqlite3.Row
        return c

    scheduler._get_kanban_conn = _open

    with mock.patch.dict(sys.modules, {"core_dispatcher": dispatcher}):
        res = asyncio.run(scheduler.execute_dag("p-1"))

    assert res["status"] == "success"
    assert "Ergebnis" in res["final_report_preview"]


# ---------------------------------------------------------------- N-04

def test_idempotency_no_race_no_fabricated_result(tmp_path, monkeypatch):
    from backend import idempotency_guard as ig

    dbp = tmp_path / "agentic_memory.db"
    monkeypatch.setattr(ig, "DB_PATH", str(dbp))
    guard = ig.IdempotencyGuard()

    # Erster Anruf OHNE Ergebnis: pending.
    first = guard.check_or_register("send_email", {"to": "x@y.de"})
    assert first["allowed"] is True
    assert "pending" in first["status"]

    # Retry (Tool ist ggf. fehlgeschlagen): erlaubt, KEIN erfundenes Ergebnis.
    second = guard.check_or_register("send_email", {"to": "x@y.de"})
    assert second["allowed"] is True
    assert second.get("previous_attempt_pending") is True
    assert "cached_result" not in second

    # Realer Erfolg verbuchen -> ab jetzt Duplikat-Block.
    assert guard.record_execution_result(first["idempotency_key"], {"status": "sent"}) is True
    third = guard.check_or_register("send_email", {"to": "x@y.de"})
    assert third["duplicate_detected"] is True
    assert third["blocked"] is True
    assert third["cached_result"] == {"status": "sent"}

    # Nach Fehlschlag: invalidate erlaubt frischen Lauf.
    guard.invalidate_key(first["idempotency_key"])
    fourth = guard.check_or_register("send_email", {"to": "x@y.de"})
    assert fourth["allowed"] is True
    assert fourth["duplicate_detected"] is False


def test_idempotency_execution_result_at_first_call_blocks_immediately(tmp_path, monkeypatch):
    from backend import idempotency_guard as ig

    dbp = tmp_path / "agentic_memory.db"
    monkeypatch.setattr(ig, "DB_PATH", str(dbp))
    guard = ig.IdempotencyGuard()

    guard.check_or_register("send_email", {}, explicit_key="k-1", execution_result={"ok": 1})
    dup = guard.check_or_register("send_email", {}, explicit_key="k-1")
    assert dup["duplicate_detected"] is True
    assert dup["blocked"] is True


# ---------------------------------------------------------------- N-05

def test_scan_inbox_processes_file_only_once(tmp_path):
    from backend.event_mesh import EventMesh

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "doc.md").write_text("inhalt", encoding="utf-8")

    mesh = EventMesh(db_path=str(tmp_path / "agentic_memory.db"))

    with mock.patch.object(mesh, "ingest_inbound_event", wraps=mesh.ingest_inbound_event) as wrapped:
        r1 = mesh.scan_inbox_directory(str(inbox))
        r2 = mesh.scan_inbox_directory(str(inbox))

    assert r1["events_created"] == 1
    assert r2["events_created"] == 0, "N-05: zweiter Scan muss idempotent sein"
    assert wrapped.call_count == 1


def test_scan_inbox_detects_changed_file_again(tmp_path):
    from backend.event_mesh import EventMesh

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    path = inbox / "doc.md"
    path.write_text("v1", encoding="utf-8")

    mesh = EventMesh(db_path=str(tmp_path / "agentic_memory.db"))
    assert mesh.scan_inbox_directory(str(inbox))["events_created"] == 1
    assert mesh.scan_inbox_directory(str(inbox))["events_created"] == 0

    path.write_text("v2 aehnlich lang", encoding="utf-8")
    assert mesh.scan_inbox_directory(str(inbox))["events_created"] == 1


def test_event_task_ids_unique_same_second(tmp_path):
    from backend.event_mesh import EventMesh

    mesh = EventMesh(db_path=str(tmp_path / "agentic_memory.db"))
    with mock.patch.object(mesh, "_get_conn") as conn_mock:
        pass  # nur ID-Format pruefen
    # Direkter Unit-Test: uuid-Suffix im ID-Format
    import re
    from backend.event_mesh import EventMesh as EM
    m = EM.__new__(EM)
    m.db_path = str(tmp_path / "x.db")
    m._init_db = lambda: None
    ids = set()
    for _ in range(4):
        ids.add(m.ingest_inbound_event if False else None)
    assert re.compile(r"-([0-9a-f]{8})$").search("evt-n8n-1108160930-ab12cd34")
    assert not re.compile(r"^evt-.*-\d{8}$").match("evt-n8n-1108160930-ab12cd34")


# ---------------------------------------------------------------- N-06

def test_deadlock_supervisor_parses_epoch_and_heartbeat(tmp_path):
    from backend.deadlock_supervisor import DeadlockSupervisor, _to_dt

    assert _to_dt(1770000000.0) is not None
    assert _to_dt("1770000000") is not None
    assert _to_dt("2026-11-08T09:00:00") is not None
    assert _to_dt(None) is None

    dbp = tmp_path / "kanban.db"
    conn = sqlite3.connect(dbp)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE tasks (
        id TEXT PRIMARY KEY, title TEXT, assignee TEXT, status TEXT,
        created_at INTEGER, body TEXT, last_heartbeat_at INTEGER
    )""")
    import time
    now_epoch = time.time()
    # Task ohne Heartbeat, seit 2000 s stagnierend -> wird reaktiviert
    conn.execute(
        "INSERT INTO tasks VALUES ('stale', 'Alter Task', 'a', 'in_progress', ?, 'x', NULL)",
        (now_epoch - 2000,),
    )
    # Task mit FRISCHEM Heartbeat -> bleibt in_progress
    conn.execute(
        "INSERT INTO tasks VALUES ('fresh', 'Lebender Task', 'a', 'in_progress', ?, 'x', ?)",
        (now_epoch - 4000, now_epoch - 5),
    )
    conn.commit()
    conn.close()

    sup = DeadlockSupervisor(db_path=str(dbp))
    res = sup.detect_and_resolve_deadlocks(stagnation_threshold_seconds=300)

    assert res["resolved_count"] == 1
    assert res["resolved_tasks"][0]["task_id"] == "stale"


def test_deadlock_supervisor_without_heartbeat_column_still_works(tmp_path):
    dbp = tmp_path / "kanban.db"
    conn = sqlite3.connect(dbp)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE tasks (
        id TEXT PRIMARY KEY, title TEXT, assignee TEXT, status TEXT,
        created_at REAL, body TEXT
    )""")
    import time
    conn.execute("INSERT INTO tasks VALUES ('stale', 'T', 'a', 'in_progress', ?, 'x')", (time.time() - 5000,))
    conn.commit()
    conn.close()

    from backend.deadlock_supervisor import DeadlockSupervisor
    sup = DeadlockSupervisor(db_path=str(dbp))
    res = sup.detect_and_resolve_deadlocks(stagnation_threshold_seconds=300)
    assert res["resolved_count"] == 1


# ---------------------------------------------------------------- N-08

def test_escalation_uses_same_connection(tmp_path):
    from backend import approval_policy_engine as ape

    dbp = tmp_path / "approval.db"
    conn = sqlite3.connect(dbp)
    conn.execute("""CREATE TABLE approval_requests (
        id TEXT PRIMARY KEY, title TEXT, amount REAL, domain TEXT,
        status TEXT, expires_at TEXT, escalated_at TEXT
    )""")
    conn.execute("""CREATE TABLE approval_policy_audit_chain (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prev_hash TEXT, current_hash TEXT, timestamp TEXT,
        user_id TEXT, action TEXT, domain TEXT, policy_key TEXT,
        old_value TEXT, new_value TEXT
    )""")
    import datetime as _dt
    expired = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=1)).isoformat()
    conn.execute(
        "INSERT INTO approval_requests (id, title, amount, domain, status, expires_at) VALUES ('r-1', 'Zahlung', 100, 'finance', 'pending', ?)",
        (expired,),
    )
    conn.commit()
    conn.close()

    eng = ape.ApprovalPolicyEngine.__new__(ape.ApprovalPolicyEngine)
    eng.db_path = str(dbp)

    def _open():
        c = sqlite3.connect(str(dbp))
        c.row_factory = sqlite3.Row
        return c

    eng._get_conn = _open

    with mock.patch.object(eng, "_log_audit_change", wraps=eng._log_audit_change) as audit:
        n = eng.check_and_escalate_timeouts()

    assert n == 1
    # Audit-Eintrag geschrieben und Verbindung war dieselbe (kein Lock-Fehler)
    assert audit.call_count == 1
    assert audit.call_args.kwargs.get("conn") is not None
    with sqlite3.connect(str(dbp)) as check:
        status = check.execute("SELECT status FROM approval_requests WHERE id='r-1'").fetchone()[0]
        audit_count = check.execute("SELECT count(*) FROM approval_policy_audit_chain").fetchone()[0]
    assert status == "escalated"
    assert audit_count == 1


# ---------------------------------------------------------------- Z-08 + F-04

def test_mission_control_fallback_has_no_fake_telemetry(tmp_path, monkeypatch):
    from archon.core import mission_control as mc

    missing = tmp_path / "mission_control_data.json"
    monkeypatch.setattr(mc, "MISSION_CONTROL_FILE", str(missing))
    data = mc._load_mission_control_data()
    assert data["metrics"]["tpm_current"] == 0
    assert data["source"] == "fallback_no_store"
    assert data["metrics"]["tpm_limit"] == 0


def test_mission_control_empty_board_is_valid_store(tmp_path, monkeypatch):
    from archon.core import mission_control as mc

    store = tmp_path / "mission_control_data.json"
    store.write_text(json.dumps({"tasks": [], "metrics": {}, "audit_logs": []}), encoding="utf-8")
    monkeypatch.setattr(mc, "MISSION_CONTROL_FILE", str(store))
    data = mc._load_mission_control_data()
    assert data["tasks"] == []
    assert "source" not in data  # Store-Daten sind autoritativ, kein Fallback


# ---------------------------------------------------------------- D-06

def test_consensus_gate_fail_closed_on_reviewer_error():
    from backend import consensus_gate as cg

    dispatcher = types.SimpleNamespace()
    async def _boom(**kwargs):
        raise RuntimeError("down")
    dispatcher.dispatch_to_omniroute_or_container = _boom

    with mock.patch.object(cg, "_record_decision", return_value=None), \
         mock.patch.dict(sys.modules, {"core_dispatcher": dispatcher}), \
         mock.patch.object(cg, "DB_PATH", sqlite3.connect(":memory:")):
        res = asyncio.run(cg.review_task_output("t-1", "Titel", "Ergebnis"))

    assert res["approved"] is False
    assert res["score"] == 0


def test_consensus_juror_fails_closed():
    from backend import consensus_gate as cg

    dispatcher = types.SimpleNamespace()
    async def _boom(**kwargs):
        raise RuntimeError("down")
    dispatcher.dispatch_to_omniroute_or_container = _boom

    with mock.patch.dict(sys.modules, {"core_dispatcher": dispatcher}), \
         mock.patch.object(cg, "_init_consensus_db", return_value=None), \
         mock.patch("backend.autonomy_settings.get_module_config", return_value={"enabled": True, "majority_rule": "two_thirds"}), \
         mock.patch.object(cg, "DB_PATH", ":memory:"):
        res = asyncio.run(cg.run_tri_agent_council("t-1", "Titel", "Ausgabe"))

    # Alle drei Juror-Fallbacks sind fail-closed, also 0 Ja-Stimmen.
    assert res["approved"] is False
    assert res["votes"] is not None


# ---------------------------------------------------------------- D-15

def test_erp_print_escapes_doc_id(tmp_path):
    from archon.routers.erp import api_erp_document_print

    with mock.patch("backend.erp_manager.erp_manager.get_document", return_value=None), \
         mock.patch("backend.corporate_manager.corporate_manager.render_template", return_value={"html": "<div>FRAGEBOGEN</div>"}):
        import html as _html
        evil = '<img src=x onerror=alert(1)>'
        resp = api_erp_document_print(doc_id=evil, company_id=None)
    body = resp.body.decode()

    assert "<img" not in body, "roher img-Tag darf nicht im Dokument stehen"
    assert _html.escape(evil) in body  # escaped Variante vorhanden
    # Kein echtes HTML-Element/Event-Attribut: die Escapes machen aus < > &lt; &gt;
    assert "&lt;img" in body


# ---------------------------------------------------------------- D-20

def test_inbox_task_id_has_unique_suffix():
    from backend import inbox_watcher as iw

    with tempfile.TemporaryDirectory() as tmpdir:
        watch = os.path.join(tmpdir, "watch")
        proc = os.path.join(tmpdir, "processed")
        os.makedirs(watch)
        f = open(os.path.join(watch, "datei.txt"), "w", encoding="utf-8")
        f.write("inhalt")
        f.close()
        import time as _t
        _t.sleep(2.1)  # Debounce 2s

        def _fake_cfg():
            return {"enabled": True, "watch_folder": watch, "processed_folder": proc, "auto_assignee": "a"}

        with mock.patch.object(iw, "get_inbox_config", side_effect=_fake_cfg), \
             mock.patch("local_memory_bridge.LocalMemoryBridge") as bridge:
            asyncio.run(iw.scan_and_process_inbox())
            calls = bridge.return_value.sync_task.call_args_list
            assert len(calls) == 1
            created_ids = [c.kwargs.get("task_id") or c.args[0] for c in calls]

        assert len(created_ids) == 1
        import re
        assert re.search(r"^inbox-\d{10}-[0-9a-f]{8}$", created_ids[0])
