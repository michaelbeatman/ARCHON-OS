"""Re-Audit Etappe 5 — D05 Anker-Laundering und D06 n8n-Webhook-Signatur."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import backend.audit_log as al
import scripts.mcp_n8n_driver as drv

ROOT = Path(__file__).resolve().parents[1]


def _record(monkeypatch, events, anchor):
    monkeypatch.setattr(al, "get_chain_anchor", lambda chain: anchor)
    monkeypatch.setattr(al.chained_audit_log, "record_event",
                        lambda **kw: events.append(kw) or {"event_id": "e-test"})


def test_d05_shorter_chain_anchor_is_rejected(monkeypatch):
    events: list[dict] = []
    _record(monkeypatch, events, {"head": "a" * 64, "count": 10})
    res = al.record_chain_anchor("gdpr_audit_log", "b" * 64, 5)
    assert res["violation"] is True
    assert res["written"] is False
    assert events and events[0]["action"] == "chain_anchor_violation"
    assert events[0]["payload"]["expected_count"] == 10


def test_d05_same_count_other_head_is_rejected(monkeypatch):
    events: list[dict] = []
    _record(monkeypatch, events, {"head": "a" * 64, "count": 10})
    res = al.record_chain_anchor("gdpr_audit_log", "c" * 64, 10)
    assert res["violation"] is True
    assert events and events[0]["action"] == "chain_anchor_violation"


def test_d05_normal_growing_anchor_still_written(monkeypatch):
    events: list[dict] = []
    _record(monkeypatch, events, {"head": "a" * 64, "count": 10})
    res = al.record_chain_anchor("gdpr_audit_log", "b" * 64, 11)
    assert res["written"] is True
    assert events and events[0]["action"] == "chain_head_anchor"


def test_d05_key_rotation_keeps_historical_anchors_verifiable(monkeypatch):
    """H-05-1/W1-A: Rollengetrennte Anker-/Audit-Keys mit Epochen.

    Die alte Anker-Erwartung kannte nur EINEN Key: nach Rotation waren alle
    historischen Anker ``valid=False``. Der Audit-Key und der Anker-Key sind
    jetzt getrennt und epochenbewusst; alte Bloecke werden mit dem Key
    verifiziert, der zum Schreibzeitpunkt galt.
    """
    monkeypatch.delenv("ARCHON_AUDIT_ANCHOR_EPOCHS", raising=False)
    monkeypatch.delenv("ARCHON_AUDIT_ANCHOR_EPOCH_FROM", raising=False)
    monkeypatch.setenv("ARCHON_AUDIT_ANCHOR_KEY", "anchor-key-epoch-0")
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "audit-key-epoch-0")
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_EPOCH_FROM", "0")
    monkeypatch.delenv("ARCHON_AUDIT_HMAC_EPOCHS", raising=False)

    old_key, old_epoch = al._anchor_signing_key(10)
    assert old_key == b"anchor-key-epoch-0"
    assert old_epoch == 0
    assert al._key_for_block(10) == b"audit-key-epoch-0"

    # Rotation NUR des Audit-Keys: der alte Key wird als Epoche 0 explizit
    # konfiguriert, damit alte Bloecke weiter verifizierbar bleiben.
    monkeypatch.setenv(
        "ARCHON_AUDIT_HMAC_EPOCHS",
        json.dumps([{"key": "audit-key-epoch-0", "from_block": 0}]),
    )
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "audit-key-epoch-20")
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_EPOCH_FROM", "20")
    assert al._key_for_block(10) == b"audit-key-epoch-0"
    assert al._key_for_block(20) == b"audit-key-epoch-20"

    # Rotation des Anker-Keys mit eigenem Epochen-Marker: der historische
    # Anker bleibt ueber _anchor_key_for_epoch() auffindbar.
    monkeypatch.setenv(
        "ARCHON_AUDIT_ANCHOR_EPOCHS",
        json.dumps([{"key": "anchor-key-epoch-0", "from_block": 0}]),
    )
    monkeypatch.setenv("ARCHON_AUDIT_ANCHOR_KEY", "anchor-key-epoch-30")
    monkeypatch.setenv("ARCHON_AUDIT_ANCHOR_EPOCH_FROM", "30")
    assert al._anchor_key_for_epoch(old_epoch) == b"anchor-key-epoch-0"
    assert al._anchor_key_for_epoch(30) == b"anchor-key-epoch-30"
    assert al._anchor_key_epochs()[0][1] != al._hmac_epochs()[0][1]


def test_d06_webhook_is_signed_over_compact_body(monkeypatch):
    monkeypatch.setenv("ARCHON_WEBHOOK_HMAC_SECRET", "test-secret")
    captured: dict = {}

    class _Resp:
        status = 200

        def read(self):
            return b'{"ok":true}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _Opener:
        def open(self, req, timeout=None):
            captured["headers"] = dict(req.header_items())
            captured["data"] = req.data
            return _Resp()

    # Die D06/MED-Egress-Pruefung ist echt und darf im Unit-Test nicht das
    # Netz kontaktieren.
    import utils.egress_guard as eg
    monkeypatch.setattr(eg, "check_target_url", lambda *a, **kw: None)
    monkeypatch.setattr(drv.urllib.request, "build_opener", lambda handler: _Opener())
    driver = drv.N8nMcpDriver.__new__(drv.N8nMcpDriver)
    driver.base_url = "http://archon-os:5678"
    driver.api_key = "key-test"

    driver._http_post_json("http://archon-os:5678/webhook/test", {"b": 2, "a": 1})

    assert captured["data"] == b'{"b":2,"a":1}'
    headers = {k.lower(): v for k, v in captured["headers"].items()}
    assert headers["x-archon-webhook-signature"].startswith("sha256=")
    assert headers["x-archon-webhook-algorithm"] == "HMAC-SHA256"


def test_d06_webhook_fails_closed_without_secret(monkeypatch):
    monkeypatch.delenv("ARCHON_WEBHOOK_HMAC_SECRET", raising=False)
    driver = drv.N8nMcpDriver.__new__(drv.N8nMcpDriver)
    driver.base_url = "http://archon-os:5678"
    driver.api_key = ""
    with pytest.raises(RuntimeError, match="ARCHON_WEBHOOK_HMAC_SECRET"):
        driver._http_post_json("http://archon-os:5678/webhook/test", {})


def test_d05_dispatch_proof_failure_is_not_swallowed(monkeypatch):
    import asyncio
    import core_dispatcher as cd

    def _boom(**kwargs):
        raise RuntimeError("HMAC-Key fehlt")

    monkeypatch.setattr("backend.llm_egress_guard.log_completed_llm_dispatch", _boom)
    with pytest.raises(RuntimeError, match="audit_write_failed"):
        asyncio.run(cd._audit_log_async(agent_id="test"))


def test_d06_sender_and_receiver_agree_on_compact_json():
    sender = (ROOT / "scripts" / "mcp_n8n_driver.py").read_text(encoding="utf-8")
    receiver = (ROOT / "scripts" / "deploy_n8n_routines.py").read_text(encoding="utf-8")
    assert 'separators=(",", ":")' in sender
    assert "JSON.stringify(body)" in receiver
    assert "webhook_signature_headers(body_bytes)" in sender
