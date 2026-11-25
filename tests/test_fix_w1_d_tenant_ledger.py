"""F014 / H-06-1 — Tenant-Scope der Integrations-Ledger.

Zwei Mandanten mit identischem ``correlation_id`` / ``idempotency_key`` duerfen
sich weder im Event-Bus noch im Event-Mesh, in der Outbox, im Effect-Ledger,
in der DLQ noch im Idempotency-Guard gegenseitig unterdruecken. Reads duerfen
keine fremden Mandantenzeilen liefern (kein Cross-Tenant-Read).

Alle Tests sind bestandskompatibel: sie nutzen explizite DB-Pfade (tmp_path)
und setzen den Mandanten ueber den tenant_context-ContextVar — keine echte
Produktiv-DB wird beruehrt.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TENANT_A = "tenant_a"
TENANT_B = "tenant_b"
SHARED_CORR = "corr-identical"
SHARED_IDEM = "idem-identical"


def _use_tenant(tenant_id: str):
    """Setzt den aktiven Mandanten direkt im ContextVar (deterministisch)."""
    from backend import tenant_context as tc

    return tc._REQUEST_TENANT_VAR.set(tc.sanitize_tenant_id(tenant_id))


def _reset_tenant(token) -> None:
    from backend import tenant_context as tc

    tc._REQUEST_TENANT_VAR.reset(token)


# ---------------------------------------------------------------------------
# DB-Pfad: SSOT + fail-closed Legacy-Modus
# ---------------------------------------------------------------------------


def test_ledger_modules_resolve_tenant_db_ssot(monkeypatch):
    """Alle drei Ledger-Module muessen resolve_tenant_db("memory.db") nutzen."""
    import backend.db_paths as dbp
    import backend.dead_letter_queue as dlq
    import backend.event_mesh as em
    import backend.idempotency_guard as ig

    calls: list[str] = []

    def _fake_resolve(filename: str) -> str:
        calls.append(filename)
        return str(REPO_ROOT / "data" / "tenants" / "tenant_a" / "memory.db")

    monkeypatch.setattr(dbp, "resolve_tenant_db", _fake_resolve)
    for module in (em, dlq, ig):
        assert module.DB_PATH == module._LEGACY_DB_PATH  # kein expliziter Override aktiv
        assert module._db_path() == str(
            REPO_ROOT / "data" / "tenants" / "tenant_a" / "memory.db"
        )
    assert calls == ["memory.db"] * 3


def test_ledger_db_path_fails_closed_without_explicit_legacy_mode(monkeypatch):
    """Ohne Opt-in darf der Resolver nicht auf die globale DB zurueckfallen."""
    import backend.db_paths as dbp
    import backend.event_mesh as em

    def _broken_resolver(filename: str) -> str:
        raise RuntimeError("tenant resolver unavailable")

    monkeypatch.setattr(dbp, "resolve_tenant_db", _broken_resolver)
    monkeypatch.delenv("ARCHON_LEDGER_LEGACY_SHARED_DB", raising=False)
    with pytest.raises(RuntimeError, match="F014"):
        em._db_path()

    # Expliziter, dokumentierter Legacy-Modus erlaubt den Fallback.
    monkeypatch.setenv("ARCHON_LEDGER_LEGACY_SHARED_DB", "1")
    assert em._db_path() == em._LEGACY_DB_PATH


# ---------------------------------------------------------------------------
# Event-Bus (workflow_scheduler)
# ---------------------------------------------------------------------------


def test_workflow_events_correlation_dedup_is_tenant_scoped(tmp_path, monkeypatch):
    import backend.workflow_scheduler as ws

    db_file = str(tmp_path / "sched.db")
    monkeypatch.setattr(ws, "SCHEDULES_DB_PATH", db_file)
    ws.init_schedules_db()

    def _dispatch(tenant: str, title: str):
        token = _use_tenant(tenant)
        try:
            return ws.dispatch_workflow_event(
                source="inbox",
                event_type="document_received",
                title=title,
                correlation_id=SHARED_CORR,
                tenant_id=tenant,
            )
        finally:
            _reset_tenant(token)

    a = _dispatch(TENANT_A, "A")
    b = _dispatch(TENANT_B, "B")
    assert a["status"] != "skipped_loop", "erster Event darf nicht dedupliziert werden"
    assert b["status"] != "skipped_loop", (
        "Mandant B darf nicht durch Mandanten A unterdrueckt werden"
    )
    a_again = _dispatch(TENANT_A, "A-again")
    assert a_again["status"] == "skipped_loop", "innerhalb von A muss Dedup greifen"

    with sqlite3.connect(db_file) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(workflow_events)").fetchall()}
        rows = conn.execute(
            "SELECT title, tenant_id, company_id, correlation_id FROM workflow_events"
        ).fetchall()
    assert {"company_id", "tenant_id"} <= cols
    titles_by_tenant: dict[str, set[str]] = {}
    for title, tenant, company, corr in rows:
        titles_by_tenant.setdefault(tenant, set()).add(title)
        assert company == tenant
        assert corr.startswith(f"{tenant}::")
    assert titles_by_tenant[TENANT_A] == {"A", "A-again"}
    assert titles_by_tenant[TENANT_B] == {"B"}


def test_workflow_events_reads_are_tenant_scoped(tmp_path, monkeypatch):
    import backend.workflow_scheduler as ws

    db_file = str(tmp_path / "sched.db")
    monkeypatch.setattr(ws, "SCHEDULES_DB_PATH", db_file)
    ws.init_schedules_db()

    for tenant in (TENANT_A, TENANT_B):
        token = _use_tenant(tenant)
        try:
            ws.dispatch_workflow_event(
                source="inbox",
                event_type="document_received",
                title=f"title-{tenant}",
                tenant_id=tenant,
            )
        finally:
            _reset_tenant(token)

    token = _use_tenant(TENANT_A)
    try:
        seen_a = ws.list_workflow_events(limit=50, tenant_id=TENANT_A)
    finally:
        _reset_tenant(token)
    token = _use_tenant(TENANT_B)
    try:
        seen_b = ws.list_workflow_events(limit=50, tenant_id=TENANT_B)
    finally:
        _reset_tenant(token)

    assert {e["tenant_id"] for e in seen_a} == {TENANT_A}
    assert {e["tenant_id"] for e in seen_b} == {TENANT_B}
    assert {e["title"] for e in seen_a} == {"title-tenant_a"}
    assert {e["title"] for e in seen_b} == {"title-tenant_b"}


# ---------------------------------------------------------------------------
# Dead-Letter-Queue
# ---------------------------------------------------------------------------


def test_dlq_idempotency_key_is_tenant_scoped(tmp_path, monkeypatch):
    import backend.dead_letter_queue as dlq

    monkeypatch.setattr(dlq, "DB_PATH", str(tmp_path / "dlq.db"))
    mgr = dlq.DeadLetterQueueManager()

    def _enqueue(tenant: str):
        token = _use_tenant(tenant)
        try:
            return mgr.enqueue_task(
                "webhook_delivery",
                "pytest",
                {"target": tenant},
                idempotency_key=SHARED_IDEM,
                tenant_id=tenant,
            )
        finally:
            _reset_tenant(token)

    a = _enqueue(TENANT_A)
    b = _enqueue(TENANT_B)
    assert a["queued"] is True
    assert b["queued"] is True, "gleicher Key darf Mandant B nicht blockieren"
    a_dup = _enqueue(TENANT_A)
    assert a_dup["duplicate"] is True and a_dup["dlq_id"] == a["dlq_id"]

    with sqlite3.connect(dlq.DB_PATH) as conn:
        rows = conn.execute(
            "SELECT idempotency_key, tenant_id FROM dead_letter_queue"
        ).fetchall()
    assert {r[1] for r in rows} == {TENANT_A, TENANT_B}
    assert {r[0] for r in rows} == {
        f"{TENANT_A}::{SHARED_IDEM}",
        f"{TENANT_B}::{SHARED_IDEM}",
    }

    # Kein Cross-Tenant-Read ueber die oeffentliche List-Funktion.
    token = _use_tenant(TENANT_A)
    try:
        listed_a = mgr.list_dlq()
    finally:
        _reset_tenant(token)
    assert {item["tenant_id"] for item in listed_a["items"]} == {TENANT_A}


# ---------------------------------------------------------------------------
# Event-Mesh / Outbox / Effect-Ledger
# ---------------------------------------------------------------------------


def test_event_mesh_dedup_is_tenant_scoped(tmp_path, monkeypatch):
    import backend.workflow_scheduler as ws
    from backend.event_mesh import EventMesh

    monkeypatch.setattr(ws, "SCHEDULES_DB_PATH", str(tmp_path / "sched.db"))
    mesh = EventMesh(db_path=str(tmp_path / "mesh.db"))
    # Keine Textfelder -> Sanitizer-Pfad bleibt unberuehrt, kein Kanban-Task.
    payload = {"idempotency_key": SHARED_IDEM, "correlation_id": SHARED_CORR}

    def _ingest(tenant: str):
        token = _use_tenant(tenant)
        try:
            return mesh.ingest_inbound_event(
                channel="mail", event_type="document_received", payload=dict(payload)
            )
        finally:
            _reset_tenant(token)

    a = _ingest(TENANT_A)
    b = _ingest(TENANT_B)
    assert a["status"] not in ("duplicate", "blocked")
    assert b["status"] not in ("duplicate", "blocked"), (
        "Mandant B darf nicht durch Mandanten A unterdrueckt werden"
    )
    a_dup = _ingest(TENANT_A)
    assert a_dup["status"] == "duplicate", "innerhalb von A muss Dedup greifen"

    with sqlite3.connect(mesh.db_path) as conn:
        dedup_keys = [r[0] for r in conn.execute("SELECT dedup_key FROM event_mesh_dedup")]

    # W4-B: Sender-Keys aus dem Payload werden verworfen. Der Dedup-Key ist ein
    # tenant-praefigierter SHA-256-Hash ueber (Mandant, Kanal, Event-Typ, Body).
    # Struktur statt konkreten Hash-Wert pruefen — der Hash ist nicht stabil
    # gegenueber kanonischen Aenderungen, die Isolation muss es sein.
    assert len(dedup_keys) == 2, f"genau zwei Dedup-Eintraege erwartet: {dedup_keys}"
    assert len(set(dedup_keys)) == 2, (
        "identischer idempotency_key/correlation_id darf mandantenuebergreifend "
        f"nicht kollidieren: {dedup_keys}"
    )
    key_by_tenant: dict[str, str] = {}
    for tenant in (TENANT_A, TENANT_B):
        prefix = f"{tenant}::"
        matching = [k for k in dedup_keys if k.startswith(prefix)]
        assert len(matching) == 1, (
            f"genau ein dedup_key mit Praefix {prefix!r} erwartet: {dedup_keys}"
        )
        digest = matching[0][len(prefix):]
        assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), (
            f"tenant-praefigierter SHA-256-Hash erwartet, erhalten: {matching[0]!r}"
        )
        assert SHARED_IDEM not in digest and SHARED_CORR not in digest, (
            "Roh-Keys aus dem Payload duerfen nie direkt im dedup_key stehen"
        )
        key_by_tenant[tenant] = matching[0]
    assert a_dup["dedup_key"] == key_by_tenant[TENANT_A], (
        "Duplicate-Pfad muss den gespeicherten Key des eigenen Mandanten melden"
    )

    token = _use_tenant(TENANT_A)
    try:
        events_a = mesh.list_events(tenant_id=TENANT_A)
    finally:
        _reset_tenant(token)
    token = _use_tenant(TENANT_B)
    try:
        events_b = mesh.list_events(tenant_id=TENANT_B)
    finally:
        _reset_tenant(token)
    assert events_a and all(e["tenant_id"] == TENANT_A for e in events_a)
    assert events_b and all(e["tenant_id"] == TENANT_B for e in events_b)


def test_outbox_key_and_effect_ledger_are_tenant_scoped(tmp_path):
    from backend.event_mesh import EffectLedger, EventMesh

    key_a = EventMesh._outbox_key(
        "https://example.invalid/hook", "evt", {"idempotency_key": SHARED_IDEM},
        tenant_id=TENANT_A,
    )
    key_b = EventMesh._outbox_key(
        "https://example.invalid/hook", "evt", {"idempotency_key": SHARED_IDEM},
        tenant_id=TENANT_B,
    )
    assert key_a != key_b
    assert key_a == f"{TENANT_A}::{SHARED_IDEM}"
    assert key_b == f"{TENANT_B}::{SHARED_IDEM}"

    db_path = str(tmp_path / "effects.db")
    ledger = EffectLedger(db_path=db_path)
    ledger.reserve(key_a, tool="http_post", target="https://example.invalid/hook",
                   payload_hash="h", tenant_id=TENANT_A)
    ledger.reserve(key_b, tool="http_post", target="https://example.invalid/hook",
                   payload_hash="h", tenant_id=TENANT_B)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT idempotency_key, tenant_id FROM effect_ledger"
        ).fetchall()
    assert {r[1] for r in rows} == {TENANT_A, TENANT_B}
    assert {r[0] for r in rows} == {key_a, key_b}


# ---------------------------------------------------------------------------
# Idempotency-Guard
# ---------------------------------------------------------------------------


def test_idempotency_guard_explicit_key_is_tenant_scoped(tmp_path, monkeypatch):
    import backend.idempotency_guard as ig

    monkeypatch.setattr(ig, "DB_PATH", str(tmp_path / "idem.db"))
    guard = ig.IdempotencyGuard()

    def _check(tenant: str, result=None):
        token = _use_tenant(tenant)
        try:
            return guard.check_or_register(
                "send_email", {}, explicit_key=SHARED_IDEM, execution_result=result
            )
        finally:
            _reset_tenant(token)

    a = _check(TENANT_A, {"tenant": TENANT_A})
    b = _check(TENANT_B, {"tenant": TENANT_B})
    assert a["duplicate_detected"] is False
    assert b["duplicate_detected"] is False
    a_dup = _check(TENANT_A)
    assert a_dup["duplicate_detected"] is True
    assert a_dup["cached_result"] == {"tenant": TENANT_A}
    b_dup = _check(TENANT_B)
    assert b_dup["duplicate_detected"] is True
    assert b_dup["cached_result"] == {"tenant": TENANT_B}

    with sqlite3.connect(ig.DB_PATH) as conn:
        keys = [r[0] for r in conn.execute("SELECT idempotency_key FROM idempotency_ledger")]
    assert f"{TENANT_A}::{SHARED_IDEM}" in keys
    assert f"{TENANT_B}::{SHARED_IDEM}" in keys
