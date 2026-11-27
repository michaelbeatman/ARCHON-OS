# -*- coding: utf-8 -*-
"""Welle W5 / Partition A — Regressionstests fuer D06-H1 und D06-M1.

D06-H1: der 30-s-Instanzhaltungszyklus muss Outbox, DLQ und Retention fuer
        ALLE Mandanten ausfuehren (nicht nur den aktiven).
D06-M1: der Container-Hop muss Firewall UND Payload-Sanitizer anwenden;
        ``is_local`` kommt ausschliesslich aus ``sanitize_llm_endpoint``.

Alle Testdaten liegen unter ``tmp_path``. Es werden keine echten Secrets
verwendet — der Maskierungstest nutzt ein neutrales GitHub-Token-Format.
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Neutrales Token-Format (passt auf das Secret-Masker-Muster, kein 'sk-').
TEST_TOKEN = "ghp_" + "A" * 30
MASKED_TOKEN = "[GESCHÜTZTER_GITHUB_TOKEN]"


# ---------------------------------------------------------------------------
# D06-M1 — Container-Hop: Firewall + Sanitizer, is_local aus der SSOT
# ---------------------------------------------------------------------------


@pytest.fixture()
def container_gate(monkeypatch):
    """Minimale, deterministische Abhaengigkeiten fuer den echten Gate/Hop."""
    import backend.compliance_engine as ce
    import backend.data_classifier as dc
    import backend.execution_receipt_ledger as erl
    import backend.llm_egress_guard as eg
    import core_dispatcher as cd

    monkeypatch.setattr(
        ce.compliance_engine, "check_activation_allowed",
        lambda *a, **k: {"allowed": True},
    )
    monkeypatch.setattr(
        dc.DataClassifier, "classify",
        classmethod(lambda cls, text, filename=None: {"cloud_llm_allowed": True}),
    )
    monkeypatch.setattr(eg, "enforce_egress_firewall_for_url", lambda *a, **k: {"allowed": True})
    monkeypatch.setattr(
        eg, "evaluate_and_gate_llm_dispatch",
        lambda **kw: {
            "data_category": "general",
            "zero_egress_active": True,
            "routed_to_local": False,
        },
    )
    monkeypatch.setattr(
        erl.execution_receipt_ledger, "issue_receipt", lambda *a, **k: None
    )
    monkeypatch.setattr(cd, "HERMES_URL", "http://hermes:9119")
    monkeypatch.setattr(cd, "ODYSSEUS_URL", "http://odysseus:7000")
    monkeypatch.setattr(cd, "OPENCLAW_URL", "http://openclaw:8080")
    monkeypatch.setenv("HERMES_API_TOKEN", "")
    return cd


def _capture_posts(monkeypatch, cd):
    """Echter AsyncClient-Ersatz: zeichnet den gesendeten Body auf."""
    captured: dict = {}

    class _Resp:
        status_code = 200
        text = "{}"

        def json(self):
            # Alle drei extract_fn-Varianten bedienen (Hermes/Odysseus/OpenClaw).
            return {
                "choices": [{"message": {"content": "ok"}}],
                "result": "ok",
                "output": "ok",
            }

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            captured["url"] = url
            captured["json"] = kwargs["json"]
            return _Resp()

    monkeypatch.setattr(cd.httpx, "AsyncClient", lambda *a, **k: _Client())

    async def _no_audit(**kwargs):
        captured["audit"] = kwargs
        return None

    monkeypatch.setattr(cd, "_audit_log_async", _no_audit)
    return captured


def test_gate_container_dispatch_derives_is_local_from_endpoint_zone(container_gate):
    """D06-M1: interne Container sind NICHT lokal, Loopback schon."""
    cd = container_gate
    internal = cd._gate_container_dispatch(
        "agent-x", "hermes", "hermes-gateway", "prompt", "http://hermes:9119/api/chat"
    )
    local = cd._gate_container_dispatch(
        "agent-x", "hermes", "hermes-gateway", "prompt", "http://127.0.0.1:9119/api/chat"
    )
    assert internal["is_local"] is False
    assert local["is_local"] is True
    # Die Firewall-Pruefung laeuft in beiden Faellen unverändert (kein Widerspruch).
    assert internal["data_category"] == "general"
    assert local["zero_egress_active"] is True


async def test_container_hop_masks_secret_for_all_three_providers(monkeypatch, container_gate):
    """D06-M1: Produzent -> gesanitisierter POST -> Audit (alle Container-Hops)."""
    cd = container_gate
    captured = _capture_posts(monkeypatch, cd)
    prompt = f"Nutze {TEST_TOKEN} fuer den Aufruf."

    cases = (
        (cd.dispatch_to_hermes, "http://hermes:9119", "messages"),
        (cd.dispatch_to_odysseus, "http://odysseus:7000", "prompt"),
        (cd.dispatch_to_openclaw, "http://openclaw:8080", "task"),
    )
    for send, url, field in cases:
        captured.clear()
        res = await send("agent-x", prompt)
        assert res["status"] == "success", (url, res)
        assert captured["url"].startswith(url)
        body = captured["json"]
        assert field in body, (url, body)
        assert TEST_TOKEN not in str(body), (url, body)
        assert MASKED_TOKEN in str(body), (url, body)
        assert captured["audit"]["extra"]["secret_mask_applied"] is True
        # Urspruenglicher Payload des Aufrufers darf nicht mutiert werden.
        assert prompt.count(TEST_TOKEN) == 1


async def test_container_hop_keeps_local_payload_unmasked(monkeypatch, container_gate):
    """D06-M1: echte lokale Zonen bleiben unverändert (is_local=True)."""
    cd = container_gate
    captured = _capture_posts(monkeypatch, cd)
    monkeypatch.setattr(cd, "HERMES_URL", "http://127.0.0.1:9119")

    res = await cd.dispatch_to_hermes("agent-x", f"Nutze {TEST_TOKEN} lokal.")
    assert res["status"] == "success", res
    assert TEST_TOKEN in str(captured["json"])
    assert captured["audit"]["extra"]["secret_mask_applied"] is False


# ---------------------------------------------------------------------------
# D06-H1 — tenant-aware Wartungsschleife (Produktivkonsument geprüft)
# ---------------------------------------------------------------------------


@pytest.fixture()
def two_tenants(monkeypatch, tmp_path):
    """Zwei physisch isolierte Mandanten-DBs ueber die echte Tenant-SSOT."""
    import backend.db_paths as db_paths
    import backend.tenant_context as tc
    from backend import dead_letter_queue as dlq
    from backend import event_mesh as em
    from backend.tenant_context import TenantContextManager

    workspace = tmp_path / "ws"
    manager = TenantContextManager(workspace_dir=str(workspace))
    monkeypatch.setattr(tc, "tenant_context", manager)
    monkeypatch.setattr(db_paths, "APP_DATA_DIR", str(workspace / "data"))

    tids = ("tenant-a", "tenant-b")
    paths = {}
    for tid in tids:
        path = Path(manager.resolve_tenant_db("memory.db", tid, create_dirs=True))
        # Schema exakt wie produktiv anlegen (Singleton nutzt danach den Resolver).
        em.EventMesh(db_path=str(path))
        dlq._init_db(str(path))
        paths[tid] = path
    return tids, paths


def test_secondary_tenant_outbox_is_delivered_in_scheduler_cycle(monkeypatch, two_tenants):
    """D06-H1: Outbox-Zeile in Tenant B erreicht im 30-s-Zyklus ihren Konsumenten."""
    tids, paths = two_tenants
    assert tids == ("tenant-a", "tenant-b")
    import backend.workflow_scheduler as ws
    from backend import event_mesh as em

    idem = "w5a-b-outbox-1"
    url = "http://webhook.example.test/hook"
    now = "2026-11-27T00:00:00"
    with sqlite3.connect(paths["tenant-b"]) as conn:
        conn.execute(
            "INSERT INTO effect_ledger "
            "(effect_id, idempotency_key, tool, target, state, payload_hash, created_at, updated_at, tenant_id) "
            "VALUES (?, ?, 'http_post', ?, 'PENDING', ?, ?, ?, ?)",
            ("eff-w5a-b", idem, url, "hash", now, now, "tenant-b"),
        )
        conn.execute(
            "INSERT INTO event_mesh_outbox "
            "(idempotency_key, target_url, event_type, payload_json, status, attempts, "
            " next_try_at, created_at, tenant_id) "
            "VALUES (?, ?, 'webhook', '{}', 'pending', 0, ?, ?, ?)",
            (idem, url, time.time() - 1, now, "tenant-b"),
        )
        conn.commit()

    delivered = []

    def _fake_deliver(*args, **kwargs):
        delivered.append(args[0])
        with sqlite3.connect(paths["tenant-b"]) as conn:
            conn.execute(
                "UPDATE event_mesh_outbox SET status = 'delivered' WHERE idempotency_key = ?",
                (args[0],),
            )
            conn.commit()
        return {"status": "delivered", "http_status": 200, "response": "{}"}

    monkeypatch.setattr(em.event_mesh, "_deliver_outbox", _fake_deliver)

    result = asyncio.run(ws.run_integration_maintenance_cycle())
    assert result["telemetry"]["tenant_ids"] == list(tids)
    assert result["tenants"]["tenant-b"]["outbox"].get("delivered") == 1
    assert delivered == [idem]

    with sqlite3.connect(paths["tenant-b"]) as conn:
        status_b = conn.execute(
            "SELECT status FROM event_mesh_outbox WHERE idempotency_key = ?", (idem,)
        ).fetchone()[0]
    assert status_b == "delivered"
    # Kein Cross-Tenant-Bleed: Tenant A wurde nicht mit B's Webhook bedient.
    with sqlite3.connect(paths["tenant-a"]) as conn:
        delivered_a = conn.execute(
            "SELECT COUNT(*) FROM event_mesh_outbox WHERE status = 'delivered'"
        ).fetchone()[0]
    assert delivered_a == 0


def test_secondary_tenant_dlq_job_is_consumed_in_scheduler_cycle(monkeypatch, two_tenants):
    """D06-H1: DLQ-Job in Tenant B wird geclaimt, ausgeführt und completed."""
    _, paths = two_tenants
    import archon.core.runtime as runtime
    import backend.dead_letter_queue as dlq
    import backend.workflow_scheduler as ws

    monkeypatch.setattr(runtime, "broadcast_event", lambda *a, **k: None)
    monkeypatch.setattr(runtime, "add_ticker", lambda *a, **k: None)

    seen = []

    async def _handler(payload, item):
        # Produktionsvertrag: Handler sind async (workflow_scheduler.py:1830).
        seen.append(item["dlq_id"])
        return {"ok": True}

    monkeypatch.setitem(ws._SHARED_QUEUE_HANDLERS, "w5a_probe", _handler)
    queued = dlq.dead_letter_queue_manager.enqueue_task(
        job_type="w5a_probe",
        source_module="test_w5_a",
        payload={"marker": "tenant-b"},
        priority=2,
        idempotency_key="w5a-dlq-b",
        tenant_id="tenant-b",
    )
    assert queued["queued"] is True

    result = asyncio.run(ws.run_integration_maintenance_cycle())
    assert result["tenants"]["tenant-b"]["dlq"].get("handled") == 1
    assert seen == [queued["dlq_id"]]

    with sqlite3.connect(paths["tenant-b"]) as conn:
        status_b = conn.execute(
            "SELECT status FROM dead_letter_queue WHERE dlq_id = ?", (queued["dlq_id"],)
        ).fetchone()[0]
    assert status_b == "completed"


def test_integration_retention_throttle_is_per_tenant(monkeypatch, two_tenants):
    """D06-H1: der Retention-Throttle darf Tenant B nicht nach A ueberspringen."""
    tids, paths = two_tenants
    import backend.workflow_scheduler as ws

    monkeypatch.setattr(ws, "_INTEGRATION_RETENTION_LAST_TS", {})
    old_space = "2020-01-01 00:00:00"
    for tid in tids:
        with sqlite3.connect(paths[tid]) as conn:
            conn.execute(
                "INSERT INTO event_mesh_log "
                "(channel, event_type, direction, payload_json, status, created_at, tenant_id) "
                "VALUES ('n8n', 'e', 'inbound', '{}', 'processed', ?, ?)",
                (old_space, tid),
            )
            conn.execute(
                "INSERT INTO dead_letter_queue (dlq_id, job_type, status, created_at, tenant_id) "
                "VALUES (?, 'x', 'completed', ?, ?)",
                (f"d-{tid}", old_space, tid),
            )
            conn.commit()

    result = asyncio.run(ws.run_integration_maintenance_cycle())
    for tid in tids:
        assert result["tenants"][tid]["retention"].get("status") == "ok"
        assert result["tenants"][tid]["retention"]["deleted"]["event_mesh_log"] == 1
        with sqlite3.connect(paths[tid]) as conn:
            logs = conn.execute("SELECT COUNT(*) FROM event_mesh_log").fetchone()[0]
            dlqs = conn.execute("SELECT COUNT(*) FROM dead_letter_queue").fetchone()[0]
        assert logs == 0, tid
        assert dlqs == 0, tid
