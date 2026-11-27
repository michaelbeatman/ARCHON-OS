# -*- coding: utf-8 -*-
"""Remediation Welle 4 / W4-B — Integrationen (F040, Domäne 06).

Regressionstests fuer alle 8 W4-B-Fixes:
  1 Event-Bus-Circuit-Breaker      5 Inbound-Payload-Kontrolle + HMAC
  2 JEV-Redirect-SSRF              6 Retention der Integrations-Tabellen
  3 n8n-Outbox                     7 ehrlicher Sync-Status (run_email_matching)
  4 DNS-TOCTOU / IP-Pinning        8 Trace-Spalten + Event-Mesh-Handoff

Kein Test schreibt gegen ``./data``: alle DB-Pfade werden auf ``tmp_path``
umgestellt (ARCHON_DATA_DIR wird beim Lauf zusaetzlich via conftest/
ARCHON_TEST_DB_ISOLATION auf ein temporaeres Verzeichnis gesetzt).
Externe Systeme (HTTP, n8n, PocketBase/Outlook) werden gemockt.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import socket
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _validated(url, ip):
    from utils.egress_guard import ValidatedURL

    return ValidatedURL(url, pinned_ip=ip)


def _safe_sanitizer(monkeypatch):
    """Verhindert, dass der echte Injection-Scan harmlose Test-Texte blockt."""
    import backend.dual_llm_sanitizer as dls

    monkeypatch.setattr(
        dls, "sanitize_external_input",
        lambda text, **kw: {"is_safe": True, "clean_summary": text},
    )


# ---------------------------------------------------------------------------
# 1 — Event-Bus-Circuit-Breaker
# ---------------------------------------------------------------------------

def _schedules_db(monkeypatch, tmp_path):
    from backend import workflow_scheduler as ws

    db = tmp_path / "workflow_schedules.db"
    monkeypatch.setattr(ws, "SCHEDULES_DB_PATH", str(db))
    # Muss sich vom Default unterscheiden, sonst greift der DB-Resolver statt
    # des expliziten Testpfads (siehe _resolve_schedules_db_path).
    monkeypatch.setattr(ws, "_DEFAULT_SCHEDULES_DB_PATH", str(tmp_path / "default-sentinel.db"))
    ws.init_schedules_db()
    ws._init_policies_table()
    return db


def test_event_bus_circuit_breaker_trips_after_three_rate_limits(monkeypatch, tmp_path):
    from backend import workflow_scheduler as ws

    _schedules_db(monkeypatch, tmp_path)
    breaker = ws.EventBusCircuitBreaker(threshold=3, cooldown_seconds=30.0)
    monkeypatch.setattr(ws, "event_bus_breaker", breaker)
    monkeypatch.setattr(ws, "_enqueue_telemetry", lambda *a, **kw: None)

    # max_per_min=1 -> erster Event zaehlt, alle weiteren sind rate_limited.
    conn = ws._get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO event_bus_policies "
        "(id, source, target, policy, max_per_min, note, updated_at) "
        "VALUES (?,?,?,?,?,?,?)",
        ("watchdog__all", "watchdog", "all", "allow", 1, "", "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()

    statuses = [
        ws.dispatch_workflow_event(
            source="watchdog", event_type="finding", title=f"f{i}",
            correlation_id=f"corr-{i}", tenant_id="w4b",
        )["status"]
        for i in range(5)
    ]
    assert statuses[0] not in ("rate_limited", "circuit_open")
    assert statuses[1:4] == ["rate_limited", "rate_limited", "rate_limited"]
    assert statuses[4] == "circuit_open"
    assert ws.event_bus_circuit_open_total().get("watchdog|workflow", 0) >= 1
    assert ws.event_bus_circuit_blocked_total().get("watchdog|workflow", 0) >= 1


def test_event_bus_probe_expiry_allows_orphaned_half_open():
    from backend import workflow_scheduler as ws

    breaker = ws.EventBusCircuitBreaker(threshold=3, cooldown_seconds=0.01)
    for _ in range(3):
        breaker.record_rate_limited("inbox", "treasury", "t")
    # OPEN explizit setzen (Cooldown von 0.01 s waere sofort abgelaufen).
    state = breaker._state[("t", "inbox", "treasury")]
    state["open_until"] = time.time() + 60
    assert breaker.allow("inbox", "treasury", "t") is False
    # Verwaister HALF_OPEN-Probe: open_until abgelaufen, probe_at=0.
    breaker.cooldown = 30.0
    state["open_until"] = time.time() - 1.0  # abgelaufen, aber > 0 (echter Zustand)
    state["probing"] = True
    state["probe_at"] = time.time() - 100.0  # verwaister Probe, laenger als cooldown
    assert breaker.allow("inbox", "treasury", "t") is True
    # Genau ein Probe: zweiter Aufruf wird geblockt.
    state["probe_at"] = time.time()
    assert breaker.allow("inbox", "treasury", "t") is False
    breaker.record_success("inbox", "treasury", "t")
    assert breaker.allow("inbox", "treasury", "t") is True


# ---------------------------------------------------------------------------
# 2 — JEV-Redirect-SSRF
# ---------------------------------------------------------------------------

def _start_redirect_server(port_holder):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port_holder["port"] = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_jev_redirect_to_imds_is_blocked(monkeypatch):
    import jev_router
    import utils.egress_guard as eg

    ports: dict = {}
    srv = _start_redirect_server(ports)
    try:
        # Simuliert eine "oeffentliche" URL, die auf den lokalen Testserver
        # zeigt; der Redirect-Block muss trotzdem greifen.
        monkeypatch.setattr(
            eg, "check_public_url_with_ip",
            lambda url, **kw: _validated(url, "127.0.0.1"),
        )
        res = jev_router.test_jev_connection(
            api_key="test-key", base_url=f"http://127.0.0.1:{ports['port']}/jump"
        )
        assert res["status"] == "blocked"
        assert res["error_code"] == "REDIRECT_BLOCKED"
        assert res["code"] == 302
        assert "169.254" not in str(res)
    finally:
        srv.shutdown()
        srv.server_close()


def test_jev_blocked_result_becomes_http_400(monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request

    import archon.routers.core_settings as cs

    monkeypatch.setattr(cs, "_require_admin", lambda request: None)
    # Offline-deterministisch: die echte SSRF-Pruefung wuerde example.org per
    # DNS aufloesen und bei fehlendem Netz eine String-400 statt des
    # Dict-Details liefern. Der Block-Vertrag wird hier ueber den gemockten
    # Connect geprueft, nicht ueber DNS-Verfuegbarkeit.
    monkeypatch.setattr(
        "utils.egress_guard.check_public_url",
        lambda url, **kw: _validated(url, "93.184.216.34"),
    )
    monkeypatch.setattr(
        "jev_router.test_jev_connection",
        lambda **kw: {"status": "blocked", "error_code": "REDIRECT_BLOCKED", "code": 302},
    )
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b""})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(cs.api_test_jev(request, {"base_url": "https://example.org/api"}))  # type: ignore[arg-type]
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "REDIRECT_BLOCKED"  # type: ignore[index]


# ---------------------------------------------------------------------------
# 3 — n8n-Outbox
# ---------------------------------------------------------------------------

def _isolated_mesh(monkeypatch, tmp_path):
    from backend import event_mesh as em

    db = tmp_path / "mesh_w4b.db"
    monkeypatch.setattr(em, "DB_PATH", str(db))
    monkeypatch.setattr(em, "_LEGACY_DB_PATH", str(tmp_path / "legacy-not-used.db"))
    return db


class _FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self.content = json.dumps(payload).encode("utf-8")
        self.headers = {}

    def json(self):
        return json.loads(self.content)


def _fake_client(responses):
    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return responses.pop(0)

    return Client()


def test_n8n_outbox_persists_and_confirms_execution(monkeypatch, tmp_path):
    import core_dispatcher as cd

    db = _isolated_mesh(monkeypatch, tmp_path)
    responses = [
        _FakeResp(500, {"error": "down"}),
        _FakeResp(200, {"executionId": "exec-42", "status": "success"}),
    ]
    monkeypatch.setattr(cd.httpx, "AsyncClient", lambda *a, **kw: _fake_client(responses))

    first = asyncio.run(cd.trigger_n8n_execution("proj", "Titel", "", "content", "webhook_crm"))
    assert first["status"] == "blocked"
    assert first["outbox_id"] and first["outbox_id"] > 0
    assert first["idempotency_key"]

    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT idempotency_key, status, payload_json FROM event_mesh_outbox"
        ).fetchone()
    assert row is not None
    idem, outbox_status, payload_json = row
    assert outbox_status in ("delivery_failed", "dead")
    body = json.loads(payload_json)
    expected = hashlib.sha256(json.dumps(
        {"parent_project_id": "proj", "action": "webhook_crm", "executed_at": body["executed_at"]},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    assert idem.endswith(expected)

    second = asyncio.run(cd.trigger_n8n_execution("proj", "Titel", "", "content", "webhook_crm"))
    assert second["status"] == "success"
    assert second["execution_id"] == "exec-42"
    assert second["outbox_id"] and second["outbox_id"] > 0


def test_n8n_outbox_http200_without_ack_is_unconfirmed(monkeypatch, tmp_path):
    import core_dispatcher as cd

    _isolated_mesh(monkeypatch, tmp_path)
    monkeypatch.setattr(cd.httpx, "AsyncClient", lambda *a, **kw: _fake_client([_FakeResp(200, {})]))
    res = asyncio.run(cd.trigger_n8n_execution("p", "t", "", "c"))
    assert res["status"] == "unconfirmed"
    assert res["error_code"] == "N8N_DELIVERY_UNCONFIRMED"
    assert res["outbox_id"] and res["outbox_id"] > 0


# ---------------------------------------------------------------------------
# 4 — DNS-TOCTOU / IP-Pinning
# ---------------------------------------------------------------------------

def test_validated_url_carries_checked_ip(monkeypatch):
    import utils.egress_guard as eg

    url = "http://93.184.216.34/pfad"
    result = eg.check_public_url(url)
    assert str(result) == url
    assert result.pinned_ip == "93.184.216.34"

    calls = []
    real = socket.getaddrinfo

    def fake(host, port, *args, **kwargs):
        calls.append(host)
        if host == "rebind.example.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(eg.socket, "getaddrinfo", fake)
    result = eg.check_public_url_with_ip("https://rebind.example.com/x")
    assert result.pinned_ip == "93.184.216.34"
    assert "rebind.example.com" in calls


def test_safe_http_pins_ip_and_keeps_original_host_header(monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import utils.egress_guard as eg
    import utils.safe_http as sh

    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen["host"] = self.headers.get("Host")
            seen["path"] = self.path
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(
            eg, "check_public_url_with_ip",
            lambda url, **kw: _validated(url, "127.0.0.1"),
        )
        status, _headers, body = sh.safe_http_request(
            f"http://rebind.example.com:{port}/pinned", public_only=True, max_bytes=1024
        )
        assert status == 200 and body == b"ok"
        assert seen["host"] == f"rebind.example.com:{port}"
        assert seen["path"] == "/pinned"
    finally:
        srv.shutdown()
        srv.server_close()


def test_peer_ip_deviation_fails_closed():
    import utils.safe_http as sh

    class FakeSock:
        def getpeername(self):
            return ("169.254.169.254", 12345)

    conn = object.__new__(sh._PinnedHTTPConnection)
    conn._pinned_ip = "93.184.216.34"
    conn.sock = FakeSock()
    conn.close = lambda: None  # type: ignore[assignment,unused-ignore]
    with pytest.raises(sh._PinnedPeerError):
        conn._verify_pinned_peer()


# ---------------------------------------------------------------------------
# 5 — Inbound-Payload-Kontrolle + HMAC
# ---------------------------------------------------------------------------

def _request_with_body(raw: bytes, headers=None):
    from starlette.requests import Request

    hdrs = [(b"content-type", b"application/json")] + [
        (k.encode("latin1"), v.encode("latin1")) for k, v in (headers or {}).items()
    ]
    scope = {
        "type": "http", "method": "POST", "path": "/api/events/inbound/n8n",
        "headers": hdrs, "query_string": b"",
    }

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    return Request(scope, receive)


def test_inbound_requires_hmac_and_ignores_sender_keys(monkeypatch):
    import archon.routers.mesh as mesh

    monkeypatch.setattr(mesh, "_require_admin_or_503", lambda request: None)
    monkeypatch.setenv("ARCHON_WEBHOOK_HMAC_SECRET", "w4b-secret")
    captured = {}

    class FakeMesh:
        def ingest_inbound_event(self, **kwargs):
            captured.update(kwargs)
            return {"status": "success"}

    monkeypatch.setattr("backend.event_mesh.event_mesh", FakeMesh())
    monkeypatch.setattr("backend.event_mesh._current_tenant_id", lambda: "tenant-a")

    body = json.dumps({
        "event_type": "task", "title": "Echtes Event", "summary": "s",
        "idempotency_key": "attacker-controlled",
        "correlation_id": "attacker-loop", "admin": True,
    }, ensure_ascii=False).encode("utf-8")

    unsigned = _request_with_body(body)
    with pytest.raises(Exception) as exc:
        asyncio.run(mesh.api_ingest_inbound_event(unsigned, "n8n"))
    assert getattr(exc.value, "status_code", None) == 401

    sig = "sha256=" + hmac.new(b"w4b-secret", body, hashlib.sha256).hexdigest()
    signed = _request_with_body(body, {"x-archon-webhook-signature": sig})
    res = asyncio.run(mesh.api_ingest_inbound_event(signed, "n8n"))
    assert res["status"] == "success"
    payload = captured["payload"]
    assert "idempotency_key" not in payload and "correlation_id" not in payload
    assert "admin" not in payload
    assert payload["title"] == "Echtes Event"
    assert captured["idempotency_key"] != "attacker-controlled"
    assert captured["correlation_id"] != "attacker-loop"

    expected = hashlib.sha256(json.dumps(
        ["tenant-a", "n8n", "task", hashlib.sha256(body).hexdigest()],
        ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    assert captured["idempotency_key"] == expected


def test_event_mesh_derives_dedup_key_server_side(monkeypatch, tmp_path):
    from backend import event_mesh as em

    _safe_sanitizer(monkeypatch)
    db = tmp_path / "inbound.db"
    mesh = em.EventMesh(db_path=str(db))
    calls = []
    monkeypatch.setattr(
        "backend.workflow_scheduler.dispatch_workflow_event",
        lambda **kwargs: (calls.append(kwargs) or {"status": "no_match", "triggered": []}),  # type: ignore[func-returns-value]
    )
    monkeypatch.setattr(em, "_current_tenant_id", lambda: "tenant-a")

    first = mesh.ingest_inbound_event(
        "n8n", "task", {"title": "x", "idempotency_key": "attacker", "correlation_id": "attacker"},
    )
    second = mesh.ingest_inbound_event(
        "n8n", "task", {"title": "x", "idempotency_key": "other", "correlation_id": "other"},
    )
    assert first["status"] == "success", first
    assert second["status"] == "duplicate", second
    assert second.get("dedup_key")
    assert "attacker" not in second["dedup_key"]
    assert calls and "trace_columns" in calls[0]


# ---------------------------------------------------------------------------
# 6 — Retention
# ---------------------------------------------------------------------------

def test_purge_integration_retention_deletes_old_keeps_open(monkeypatch, tmp_path):
    from backend import dead_letter_queue as dlq
    from backend import event_mesh as em
    from backend import workflow_scheduler as ws

    db = tmp_path / "retention.db"
    monkeypatch.setattr(em, "DB_PATH", str(db))
    monkeypatch.setattr(dlq, "DB_PATH", str(db))
    monkeypatch.setattr(em, "_LEGACY_DB_PATH", str(tmp_path / "legacy-em.db"))
    monkeypatch.setattr(dlq, "_LEGACY_DB_PATH", str(tmp_path / "legacy-dlq.db"))
    EventMesh = em.EventMesh(db_path=str(db))
    dlq._init_db(str(db))

    old = "2020-01-01T00:00:00"
    old_space = "2020-01-01 00:00:00"
    new = "2099-01-01T00:00:00"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO event_mesh_log (channel,event_type,direction,payload_json,status,created_at) "
            "VALUES ('n8n','e','inbound','{}','processed',?)", (old_space,)
        )
        conn.execute(
            "INSERT INTO event_mesh_log (channel,event_type,direction,payload_json,status,created_at) "
            "VALUES ('n8n','e','inbound','{}','processed',?)", (new,)
        )
        conn.execute(
            "INSERT INTO event_mesh_outbox (idempotency_key,target_url,event_type,payload_json,status,created_at) "
            "VALUES ('old','http://x','e','{}','delivered',?)", (old,)
        )
        conn.execute(
            "INSERT INTO event_mesh_outbox (idempotency_key,target_url,event_type,payload_json,status,created_at) "
            "VALUES ('open','http://x','e','{}','pending',?)", (old,)
        )
        conn.execute(
            "INSERT INTO event_mesh_dedup (dedup_key,channel,event_type,first_seen) "
            "VALUES ('old','n8n','e',?)", (old,)
        )
        conn.execute(
            "INSERT INTO effect_ledger (effect_id,idempotency_key,tool,target,state,payload_hash,created_at,updated_at,resolved_at) "
            "VALUES ('e1','old','http_post','x','COMMITTED','h',?,?,?)", (old, old, old)
        )
        conn.execute(
            "INSERT INTO dead_letter_queue (dlq_id,job_type,status,created_at) "
            "VALUES ('d1','x','completed',?)", (old_space,)
        )
        conn.execute(
            "INSERT INTO dead_letter_queue (dlq_id,job_type,status,created_at) "
            "VALUES ('d2','x','queued',?)", (old_space,)
        )
        conn.commit()

    assert EventMesh is not None
    result = ws.purge_integration_retention(days=14, force=True)
    assert result["status"] == "ok", result["errors"]
    assert result["deleted"]["event_mesh_log"] == 1
    assert result["deleted"]["event_mesh_outbox"] == 1
    assert result["deleted"]["event_mesh_dedup"] == 1
    assert result["deleted"]["effect_ledger"] == 1
    assert result["deleted"]["dead_letter_queue"] == 1
    assert ws.integration_retention_deleted_total()["event_mesh_log"] >= 1

    with sqlite3.connect(db) as conn:
        logs = conn.execute("SELECT created_at FROM event_mesh_log").fetchall()
        outbox = conn.execute("SELECT idempotency_key FROM event_mesh_outbox").fetchall()
        dlq_rows = conn.execute("SELECT dlq_id FROM dead_letter_queue").fetchall()
    assert logs == [(new,)]
    assert outbox == [("open",)]
    assert dlq_rows == [("d2",)]


# ---------------------------------------------------------------------------
# 7 — ehrlicher Sync-Status
# ---------------------------------------------------------------------------

def test_email_matching_reports_real_error_status(monkeypatch, capsys):
    import scripts.run_email_matching as rem

    monkeypatch.setattr(
        rem, "get_all_contacts",
        lambda: {"status": "error", "contacts": [], "error_code": "CRM_HTTP_ERROR"},
    )
    monkeypatch.setattr(
        rem, "fetch_local_outlook_emails",
        lambda limit=200: {"status": "error", "emails": [], "error_code": "OUTLOOK_IMPORT_FAILED"},
    )
    res = rem.run_matching()
    out = capsys.readouterr().out
    assert res["status"] == "error"
    assert "ERFOLGREICH BEENDET" not in out
    assert "FEHLGESCHLAGEN" in out
    assert "CRM_HTTP_ERROR" in out


def test_email_matching_success_only_without_write_errors(monkeypatch, capsys):
    import scripts.run_email_matching as rem

    monkeypatch.setattr(rem, "get_all_contacts", lambda: {"status": "ok", "contacts": []})
    monkeypatch.setattr(rem, "fetch_local_outlook_emails", lambda limit=200: {"status": "ok", "emails": []})
    monkeypatch.setattr(rem, "update_contact_email", lambda *a: True)
    monkeypatch.setattr(rem, "append_email_to_history", lambda *a: True)
    monkeypatch.setattr(rem, "save_potential_contacts", lambda *a: None)
    res = rem.run_matching()
    out = capsys.readouterr().out
    assert res["status"] == "success"
    assert "ERFOLGREICH BEENDET" in out


def test_email_matching_partial_on_write_error(monkeypatch, capsys):
    import scripts.run_email_matching as rem

    monkeypatch.setattr(rem, "get_all_contacts", lambda: {"status": "ok", "contacts": []})
    monkeypatch.setattr(rem, "fetch_local_outlook_emails", lambda limit=200: {"status": "ok", "emails": []})
    monkeypatch.setattr(rem, "save_potential_contacts", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    res = rem.run_matching()
    out = capsys.readouterr().out
    assert res["status"] == "partial"
    assert "ERFOLGREICH BEENDET" not in out


# ---------------------------------------------------------------------------
# 8 — Trace-Spalten + Event-Mesh-Handoff
# ---------------------------------------------------------------------------

def test_workflow_events_store_trace_columns(monkeypatch, tmp_path):
    from backend import workflow_scheduler as ws

    db = _schedules_db(monkeypatch, tmp_path)
    monkeypatch.setattr(ws, "_enqueue_telemetry", lambda *a, **kw: None)
    trace = {
        "trace_id": "a" * 32, "span_id": "b" * 16,
        "traceparent": f"00-{'a' * 32}-{'b' * 16}-01", "tracestate": "vendor=1",
    }
    res = ws.dispatch_workflow_event(
        source="manual", event_type="trace_probe", title="trace",
        correlation_id="trace-corr", tenant_id="w4b-trace", trace_columns=trace,
    )
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT trace_id, span_id, traceparent, tracestate FROM workflow_events WHERE id = ?",
            (res["event_id"],),
        ).fetchone()
    assert row["trace_id"] == trace["trace_id"]
    assert row["span_id"] == trace["span_id"]
    assert row["traceparent"] == trace["traceparent"]
    assert row["tracestate"] == trace["tracestate"]

    cols = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(workflow_events)").fetchall()}
    assert {"trace_id", "span_id", "traceparent", "tracestate"}.issubset(cols)


def test_event_mesh_handoff_passes_trace_columns(monkeypatch, tmp_path):
    from backend import event_mesh as em

    _safe_sanitizer(monkeypatch)
    db = tmp_path / "handoff.db"
    mesh = em.EventMesh(db_path=str(db))
    monkeypatch.setattr(em, "_current_tenant_id", lambda: "tenant-trace")
    captured = {}

    def fake_dispatch(**kwargs):
        captured.update(kwargs)
        return {"status": "no_match", "triggered": []}

    monkeypatch.setattr("backend.workflow_scheduler.dispatch_workflow_event", fake_dispatch)
    trace = {
        "trace_id": "c" * 32, "span_id": "d" * 16,
        "traceparent": f"00-{'c' * 32}-{'d' * 16}-01", "tracestate": "vendor=2",
    }
    mesh.ingest_inbound_event("n8n", "task", {"title": "trace", **trace}, trace_columns=trace)
    assert captured["trace_columns"]["trace_id"] == trace["trace_id"]
    assert captured["trace_columns"]["span_id"] == trace["span_id"]
    assert captured["correlation_id"].startswith("tenant-trace::")
    assert "correlation_id" not in captured["payload"]
