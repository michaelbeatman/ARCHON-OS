"""M68 — Compliance-Inventar, DPIA-Register, Retention, Replay, Export & RBAC.

Alle Tests arbeiten mit ``tmp_path`` und beruehren keine produktiven SSOT-Dateien
oder Datenbanken. Der RBAC-Test baut eine isolierte FastAPI-App nur mit dem
neuen Router (wird absichtlich nicht in main.py registriert).
"""

from __future__ import annotations

import hashlib
import json
import sys
import types
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from archon.routers import _rbac
from archon.routers import compliance as compliance_router
from backend import compliance_inventory as m68


def _write_json(path: Path, payload: Any) -> str:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


@pytest.fixture()
def ssot(tmp_path: Path) -> Dict[str, str]:
    """Minimale, deterministische SSOT: 3 Profile + 1 Rolle + Org-Knoten."""
    profiles = [
        {
            "id": "alpha_strategist",
            "name": "Alpha Strategist",
            "category": "1. Strategie, Führung & Lebensplanung",
            "description": "Strategische Analyse ohne personenbezogene Daten.",
            "model": "model-alpha",
            "provider": "omniroute",
        },
        {
            "id": "beta_contract_auditor",
            "name": "Beta Contract Auditor",
            "category": "3. Recht, Steuern & Compliance",
            "description": "Prueft Vertraege und Rechnungen auf Compliance.",
            "model": "model-beta",
            "provider": "omniroute",
        },
        {
            "id": "gamma_secret_vault",
            "name": "Gamma Secret Vault",
            "category": "7. Tech, Software & Data",
            "description": "Verwaltet Passwoerter und API-Keys im lokalen Tresor.",
            "model": "model-gamma",
            "provider": "local",
        },
    ]
    roles = [
        {
            "id": "delta_auditor",
            "name": "Delta Auditor",
            "category": "7. Tech, Software & Data",
            "description": "Interne Pruefungsassistenz.",
            "model": "model-alpha",
        }
    ]
    org = {
        "nodes": [
            {"id": "beta_contract_auditor", "team_id": "team_legal", "is_approval_authority": True},
            {"id": "alpha_strategist", "team_id": "team_strategy"},
        ]
    }
    return {
        "profiles_file": _write_json(tmp_path / "agent_profiles.json", profiles),
        "roles_file": _write_json(tmp_path / "roles.json", roles),
        "org_file": _write_json(tmp_path / "org_hierarchy.json", org),
    }


def _inventory(ssot: Dict[str, str]) -> List[Dict[str, Any]]:
    return m68.build_inventory("tenant-1", **ssot)


# ---------------------------------------------------------------------------
# 1. Inventar-Vollstaendigkeit
# ---------------------------------------------------------------------------

def test_inventory_is_complete_and_uses_ssot(ssot: Dict[str, str]) -> None:
    items = _inventory(ssot)
    by_agent = {item["agent"]: item for item in items}

    assert len(items) == 4  # 3 Profile + 1 ergaenzende Rolle
    for item in items:
        assert {"agent", "datenklasse", "ziel", "freigabestufe", "retention"}.issubset(item)
        assert item["tenant_id"] == "tenant-1"
        assert item["ziel"] in {"lokal", "cloud"}
        assert item["retention"]
        assert item["datenklasse"] in {"PUBLIC", "INTERNAL", "CONFIDENTIAL", "STRICTLY_CONFIDENTIAL"}

    assert by_agent["alpha_strategist"]["datenklasse"] == "INTERNAL"
    assert by_agent["alpha_strategist"]["freigabestufe"] == "AUTO_SUPERVISED"
    assert by_agent["alpha_strategist"]["ziel"] == "cloud"
    assert by_agent["beta_contract_auditor"]["datenklasse"] == "CONFIDENTIAL"
    assert by_agent["beta_contract_auditor"]["freigabestufe"] == "HITL_4_AUGEN"  # Org-SSOT
    assert by_agent["beta_contract_auditor"]["retention"] == "10 Jahre"  # GoBD
    assert by_agent["gamma_secret_vault"]["datenklasse"] == "STRICTLY_CONFIDENTIAL"
    assert by_agent["gamma_secret_vault"]["ziel"] == "lokal"  # Zero-Egress
    assert "delta_auditor" in by_agent  # Rollen-SSOT ergaenzt Profile


# ---------------------------------------------------------------------------
# 2. DPIA-Change-Trigger & Fingerprint
# ---------------------------------------------------------------------------

def test_dpia_change_trigger_and_versioning(tmp_path: Path) -> None:
    register = m68.DPIARegister(str(tmp_path / "dpia_register.yaml"))

    first = register.ensure_entries(["model-a"], ["INTERNAL", "CONFIDENTIAL"])
    assert first["changed"] is True
    assert {t["typ"] for t in first["triggers"]} == {"new_model", "new_datenklasse"}
    assert first["register"]["version"] == 1

    unchanged = register.ensure_entries(["model-a"], ["INTERNAL", "CONFIDENTIAL"])
    assert unchanged["changed"] is False
    assert unchanged["triggers"] == []

    changed = register.ensure_entries(["model-a", "model-b"], ["INTERNAL", "CONFIDENTIAL", "STRICTLY_CONFIDENTIAL"])
    assert changed["changed"] is True
    assert changed["register"]["version"] == 2
    assert {t["wert"] for t in changed["triggers"]} == {"model-b", "STRICTLY_CONFIDENTIAL"}
    fingerprint = str(changed["register"]["fingerprint"])
    assert len(fingerprint) == 64 and fingerprint == m68.compute_fingerprint(
        ["model-a", "model-b"], ["INTERNAL", "CONFIDENTIAL", "STRICTLY_CONFIDENTIAL"]
    )
    assert changed["register"]["fingerprint"] == m68.compute_fingerprint(
        ["model-a", "model-b"], ["INTERNAL", "CONFIDENTIAL", "STRICTLY_CONFIDENTIAL"]
    )

    persisted = yaml.safe_load((tmp_path / "dpia_register.yaml").read_text(encoding="utf-8"))
    assert persisted["version"] == 2
    assert len(persisted["entries"]) == 4
    assert len(persisted["history"]) == 2
    assert all(e["status"] == "PENDING_ASSESSMENT" for e in persisted["entries"])


def test_sync_dpia_register_from_inventory(ssot: Dict[str, str], tmp_path: Path) -> None:
    target = tmp_path / "synced_dpia.yaml"
    result = m68.sync_dpia_register(
        "tenant-1", register_path=str(target), **ssot
    )
    assert result["changed"] is True
    assert target.is_file()
    values = {t["wert"] for t in result["triggers"]}
    assert "model-alpha" in values
    assert "STRICTLY_CONFIDENTIAL" in values


# ---------------------------------------------------------------------------
# 3. Retention-Grenzen
# ---------------------------------------------------------------------------

def test_retention_boundaries() -> None:
    financial = m68.retention_for_category("financial")
    assert financial["years"] == m68.GOBD_RETENTION_YEARS == 10
    assert financial["days"] == 3650
    assert financial["gobd_relevant"] is True

    debug = m68.retention_for_category("debug")
    assert debug["years"] == 0 and debug["days"] == 90
    assert debug["gobd_relevant"] is False

    assert m68.retention_for_category("health")["days"] == 30
    assert m68.retention_for_category("system")["days"] == 365
    assert m68.retention_for_category("voellig_unbekannt")["days"] == 90
    assert m68.retention_label("invoice") == "10 Jahre"
    assert m68.retention_label("system") == "365 Tage"


# ---------------------------------------------------------------------------
# 4. Deterministische Pseudonymisierung
# ---------------------------------------------------------------------------

def test_pseudonymization_is_deterministic_and_irreversible() -> None:
    token = m68.pseudonymize_field("alice@example.com", "email")
    assert token.startswith(m68.PSEUDONYM_PREFIX)
    assert "alice" not in token and "@" not in token
    assert token == m68.pseudonymize_field("alice@example.com", "email")
    assert token != m68.pseudonymize_field("bob@example.com", "email")
    assert token != m68.pseudonymize_field("alice@example.com", "phone")
    assert m68.pseudonymize_field("alice@example.com", "email", salt="other") != token

    payload = m68.pseudonymize_payload(
        {"email": "alice@example.com", "note": "Klartext ist erlaubt", "nested": {"name": "Alice"}}
    )
    assert payload["email"] == token
    assert payload["note"] == "Klartext ist erlaubt"
    assert payload["nested"]["name"].startswith(m68.PSEUDONYM_PREFIX)
    assert json.dumps(payload, ensure_ascii=False).find("alice@example.com") == -1


# ---------------------------------------------------------------------------
# 5. Audit-Replay: Reihenfolge, Luecken, M112-Interface & Fallback
# ---------------------------------------------------------------------------

def test_replay_from_registry_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "m68-test-" + "b" * 64)
    from backend.audit_log import ChainedAuditLog

    db_path = str(tmp_path / "audit.db")
    log = ChainedAuditLog(db_path=db_path, start_anchor=False)
    for idx in range(3):
        log.record_event(
            "system", f"step_{idx}", "agent-x", {"company_id": "tenant-1", "seq": idx}
        )

    result = m68.replay_from_ledger("tenant-1", ledger_path=db_path)
    assert result["status"] == "ok"
    assert result["count"] == 3
    assert result["first_id"] == 1 and result["last_id"] == 3
    assert result["order_ok"] is True
    assert result["gaps"] == []
    assert result["chain_checked"] is True and result["chain_ok"] is True
    assert result["tenant_id"] == "tenant-1"


def test_replay_detects_order_violation_and_gaps() -> None:
    reversed_events = [
        {"id": 3, "timestamp": "2026-11-27T00:03:00Z", "category": "system", "action": "c"},
        {"id": 2, "timestamp": "2026-11-27T00:02:00Z", "category": "system", "action": "b"},
        {"id": 1, "timestamp": "2026-11-27T00:01:00Z", "category": "system", "action": "a"},
    ]
    reversed_result = m68.replay_from_ledger("tenant-1", events=reversed_events)
    assert reversed_result["status"] == "error"
    assert "order_violation" in reversed_result["errors"]
    assert reversed_result["order_ok"] is False
    assert reversed_result["gaps"]

    gapped = [
        {"id": 1, "timestamp": "2026-11-27T00:01:00Z", "category": "system", "action": "a"},
        {"id": 3, "timestamp": "2026-11-27T00:03:00Z", "category": "system", "action": "c"},
    ]
    gap_result = m68.replay_from_ledger("tenant-1", events=gapped)
    assert "ledger_gap" in gap_result["errors"]
    assert gap_result["gaps"][0]["expected"] == 2
    assert gap_result["gaps"][0]["actual"] == 3


def test_replay_uses_m112_interface_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.ModuleType("backend.event_ledger")

    def replay_events(events: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {"ok": True, "seen": len(events)}

    def verify_ledger(events: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {"valid": True, "verified": len(events)}

    fake.replay_events = replay_events  # type: ignore[attr-defined]
    fake.verify_ledger = verify_ledger  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "backend.event_ledger", fake)

    events = [
        {"id": 1, "timestamp": "2026-11-27T00:01:00Z", "category": "system", "action": "a"}
    ]
    result = m68.replay_from_ledger("tenant-1", events=events)
    assert result["replay_backend"] == "event_ledger"
    assert result["m112"]["replay"] == {"ok": True, "seen": 1}
    assert result["m112"]["verify"] == {"valid": True, "verified": 1}
    assert result["status"] == "ok"


def test_replay_pseudonymizes_payloads_in_response(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "m68-test-" + "c" * 64)
    from backend.audit_log import ChainedAuditLog

    db_path = str(tmp_path / "pii_audit.db")
    log = ChainedAuditLog(db_path=db_path, start_anchor=False)
    log.record_event(
        "system", "pii_probe", "agent-x",
        {"company_id": "tenant-1", "email": "alice@example.com"},
    )
    result = m68.replay_from_ledger("tenant-1", ledger_path=db_path)
    assert "alice@example.com" not in json.dumps(result["events"], ensure_ascii=False)


# ---------------------------------------------------------------------------
# 6. Einseitiger Policy-Export & Art.-50-Kennzeichnung
# ---------------------------------------------------------------------------

def test_policy_export_is_one_page_and_art50_marked(ssot: Dict[str, str]) -> None:
    inventory = _inventory(ssot)
    snapshot = {"version": 1, "fingerprint": "f" * 64, "entries": []}
    proof = {"status": "ok", "count": 3}
    markdown = m68.export_policy_markdown(
        "tenant-1", inventory=inventory, dpia=snapshot, replay=proof
    )
    assert "Art. 50" in markdown
    assert "KI-generiert" in markdown
    assert "M68-POLICY" not in markdown
    assert "tenant-1" in markdown

    pdf_bytes, sha256 = m68.export_policy_pdf(
        "tenant-1", inventory=inventory, dpia=snapshot, replay=proof
    )
    assert pdf_bytes.startswith(b"%PDF")
    assert sha256 == hashlib.sha256(pdf_bytes).hexdigest()
    try:
        import io

        from pypdf import PdfReader

        pages = len(PdfReader(io.BytesIO(pdf_bytes)).pages)
    except Exception:
        # Fallback ohne pypdf: Seite-Typ exakt zaehlen (nicht /Pages).
        import re

        pages = len(re.findall(rb"/Type\s*/Page(?![s])", pdf_bytes))
    assert pages == 1


def test_inventory_pdf_export(ssot: Dict[str, str]) -> None:
    inventory = _inventory(ssot)
    pdf_bytes, sha256 = m68.export_inventory_pdf("tenant-1", inventory=inventory)
    assert pdf_bytes.startswith(b"%PDF")
    assert sha256 == hashlib.sha256(pdf_bytes).hexdigest()
    assert b"Tenant-Compliance-Inventar" in pdf_bytes
    assert b"gamma_secret_vault" in pdf_bytes


def test_artifact_annotation_art50() -> None:
    tagged = m68.annotate_artifact({"title": "Bericht"}, "agent-7")
    disclosure = tagged["art50_disclosure"]
    assert disclosure["machine_generated"] is True
    assert disclosure["agent_id"] == "agent-7"
    assert "Art. 50" in disclosure["label"]
    assert tagged["title"] == "Bericht"
    assert m68.art50_label() == disclosure["label"]


# ---------------------------------------------------------------------------
# 7. RBAC: 403 fuer Viewer, 200 fuer Admin (isolierte App)
# ---------------------------------------------------------------------------

def test_router_rbac_403_and_200(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.audit_log import chained_audit_log

    # Kein echtes Audit-Log waehrend des Denial-Tests beschreiben.
    monkeypatch.setattr(chained_audit_log, "record_event", lambda *a, **k: {})

    def _deny(_request: Any) -> None:
        raise HTTPException(status_code=403, detail="viewer_denied")

    app = FastAPI()
    app.include_router(compliance_router.router)
    client = TestClient(app, raise_server_exceptions=False)

    monkeypatch.setattr(_rbac, "_checker", _deny)
    denied = client.get("/api/compliance/retention")
    assert denied.status_code == 403
    assert client.get("/api/v1/compliance/inventory").status_code == 403

    def _allow(_request: Any) -> None:
        return None

    monkeypatch.setattr(_rbac, "_checker", _allow)
    fake_items = [{"agent": "a", "datenklasse": "INTERNAL", "ziel": "cloud", "freigabestufe": "AUTO_SUPERVISED", "retention": "365 Tage"}]
    monkeypatch.setattr(m68, "build_inventory", lambda _tenant: list(fake_items))
    allowed = client.get("/api/compliance/inventory")
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["status"] == "success"
    assert body["count"] == 1
    assert body["inventory"][0]["agent"] == "a"

    # Nur Lese-Endpunkte: keine POST/PUT/DELETE/PATCH im Router.
    methods = {method for route in compliance_router.router.routes for method in getattr(route, "methods", set())}
    assert "GET" in methods
    assert not (methods & {"POST", "PUT", "DELETE", "PATCH"})


def test_shipped_dpia_register_is_valid_and_versioned() -> None:
    """Die ausgelieferte config/dpia_register.yaml ist versioniert und fingerprint-konsistent."""
    path = Path(m68.DPIA_REGISTER_FILE)
    assert path.is_file()
    register = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert register["schema"] == "archon-m68-dpia/v1"
    assert int(register["version"]) >= 1
    assert len(str(register["fingerprint"])) == 64
    assert register["fingerprint"] == m68.compute_fingerprint([], [])
    assert isinstance(register["entries"], list)
    assert isinstance(register["history"], list)


def test_no_new_pdf_dependency() -> None:
    """M68 nutzt nur vorhandene Libs (yaml + vorhandener Pure-Python-PDF-Generator)."""
    source = Path(str(m68.__file__)).read_text(encoding="utf-8")
    for forbidden in ("reportlab", "weasyprint", "fpdf", "xhtml2pdf"):
        assert forbidden not in source
    assert hasattr(m68, "export_policy_pdf")
