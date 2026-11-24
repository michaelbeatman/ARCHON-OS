"""
Regressionstests fuer Phase 1 (Security-Hardening & P0-Logik-Fixes).
Laeuft synchron (mit asyncio.run) ohne pytest-asyncio-Abhaengigkeit.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import sys
import time

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _registration_auth_data(rp_id: str, *, flags: int = 0x05,
                            sign_count: int = 0, aaguid: bytes = b"\x00" * 16) -> bytes:
    """32 Byte rpIdHash + Flags(UP|UV) + 4 Byte Counter + 16 Byte AAGUID = 53 Byte.

    Seit der Haertung ist authenticatorData bei der Registrierung zwingend und
    muss mindestens 53 Byte enthalten — alte Fixtures ohne authData sind nicht
    mehr gueltig.
    """
    return (
        hashlib.sha256(rp_id.encode("utf-8")).digest()
        + bytes([flags])
        + int(sign_count).to_bytes(4, "big")
        + aaguid
    )


# Minimales Attestation-Statement (CBOR 'fmt': 'packed'); verhindert, dass der
# Registrierungspfad wegen fehlender Attestation fail-closed abbricht.
_ATTESTATION_OBJECT = _b64u(b"\xa3\x63fmt\x66packed")


# ---------------------------------------------------------------------------
# 1. Passkey-HITL: UV-Enforcement & serverseitiges Einmal-Proof-Token
# ---------------------------------------------------------------------------

def test_passkey_hitl_requires_uv_for_payments_and_mints_single_use_token(tmp_path, monkeypatch):
    import backend.passkey_hitl as pk

    monkeypatch.setattr(pk, "PASSKEY_FILE", str(tmp_path / "passkey_hitl.json"))
    monkeypatch.setattr(pk, "CONFIG_DIR", str(tmp_path))

    priv = ec.generate_private_key(ec.SECP256R1())
    pub_spki = priv.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    reg_opts = pk.create_registration_options("u1", "admin", "localhost")
    reg_client_data = json.dumps({
        "type": "webauthn.create",
        "challenge": reg_opts["challenge"],
        "origin": "http://localhost:8420",
    }).encode("utf-8")
    pk.verify_and_store_registration(
        user_id="u1",
        credential_id="cred-1",
        client_data_b64=_b64u(reg_client_data),
        public_key_spki_b64=_b64u(pub_spki),
        alg=-7,
        label="TestKey",
        expected_origin="http://localhost:8420",
        authenticator_data_b64=_b64u(_registration_auth_data("localhost")),
        attestation_object_b64=_ATTESTATION_OBJECT,
    )
    pk.update_user_passkey_config("u1", enabled=True, scope="all")

    # 1) Ohne UV-Flag (0x01 = nur UP) muss Kategorie 'payments' scheitern
    opts_no_uv = pk.create_hitl_assertion_options("u1", "localhost", category="payments")
    assert opts_no_uv["userVerification"] == "required"
    cd_no_uv = json.dumps({
        "type": "webauthn.get",
        "challenge": opts_no_uv["challenge"],
        "origin": "http://localhost:8420",
    }).encode("utf-8")
    auth_no_uv = hashlib.sha256(b"localhost").digest() + bytes([0x01]) + (1).to_bytes(4, "big")
    sig_no_uv = priv.sign(auth_no_uv + hashlib.sha256(cd_no_uv).digest(), ec.ECDSA(hashes.SHA256()))

    with pytest.raises(ValueError, match="User-Verification-Flag"):
        pk.verify_hitl_assertion(
            user_id="u1",
            credential_id="cred-1",
            client_data_b64=_b64u(cd_no_uv),
            authenticator_data_b64=_b64u(auth_no_uv),
            signature_b64=_b64u(sig_no_uv),
            expected_origin="http://localhost:8420",
        )

    # 2) Mit UP+UV (0x05) wird ein einmaliges serverseitiges proof_token ausgestellt
    opts_ok = pk.create_hitl_assertion_options(
        "u1", "localhost", category="payments",
        action_label="Zahlung freigeben", resource="tx-1",
    )
    cd_ok = json.dumps({
        "type": "webauthn.get",
        "challenge": opts_ok["challenge"],
        "origin": "http://localhost:8420",
    }).encode("utf-8")
    auth_ok = hashlib.sha256(b"localhost").digest() + bytes([0x05]) + (2).to_bytes(4, "big")
    sig_ok = priv.sign(auth_ok + hashlib.sha256(cd_ok).digest(), ec.ECDSA(hashes.SHA256()))

    proof = pk.verify_hitl_assertion(
        user_id="u1",
        credential_id="cred-1",
        client_data_b64=_b64u(cd_ok),
        authenticator_data_b64=_b64u(auth_ok),
        signature_b64=_b64u(sig_ok),
        expected_origin="http://localhost:8420",
    )
    tok = proof["proof_token"]
    assert tok and proof["uv_verified"] is True

    # Falscher User oder falsche Kategorie abgelehnt (Token wird dabei nicht an Fremde vergeben)
    assert pk.consume_hitl_proof_token("forged-token", "u1", category="payments") is False
    assert pk.consume_hitl_proof_token(
        tok, "u1", category="payments",
        action="Zahlung freigeben", resource="tx-1",
    ) is True
    # Replay desselben Tokens muss scheitern (single-use)
    assert pk.consume_hitl_proof_token(
        tok, "u1", category="payments",
        action="Zahlung freigeben", resource="tx-1",
    ) is False


def test_hitl_proof_action_and_resource_binding_fail_closed():
    """Ein Proof für Zahlung A darf nicht Zahlung B freigeben (Audit 23.11.2026)."""
    from backend import passkey_hitl as pk

    def _proof(action: str, resource: str) -> str:
        token = f"binding-{action}-{resource}-{time.time_ns()}"
        with pk._LOCK:
            pk._PROOF_TOKENS[token] = {
                "user_id": "u1",
                "category": "payments",
                "uv_verified": True,
                "created_ts": time.time(),
                "action": action,
                "resource": resource,
            }
        return token

    # Falsche Ressource → ablehnen (auch bei korrekter Aktion)
    assert pk.consume_hitl_proof_token(
        _proof("Zahlung freigeben", "tx-A"), "u1", category="payments",
        action="Zahlung freigeben", resource="tx-B",
    ) is False
    # Falsche Aktion → ablehnen
    assert pk.consume_hitl_proof_token(
        _proof("Zahlung freigeben", "tx-A"), "u1", category="payments",
        action="Konto loeschen", resource="tx-A",
    ) is False
    # Fehlende Bindung beim Verbrauch → ablehnen (fail-closed)
    assert pk.consume_hitl_proof_token(
        _proof("Zahlung freigeben", "tx-A"), "u1", category="payments",
    ) is False


# ---------------------------------------------------------------------------
# 2. Showroom RCE: fail-closed wenn Docker-Sandbox nicht verfuegbar
# ---------------------------------------------------------------------------

def test_showroom_run_code_blocks_host_execution_fail_closed(monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request
    import views_core
    import backend.ephemeral_sandbox as es

    monkeypatch.setattr(views_core, "require_admin_or_503", lambda req: None)
    monkeypatch.setattr(
        es.ephemeral_sandbox,
        "execute_in_sandbox",
        lambda **kw: {
            "status": "error",
            "engine": "unavailable",
            "error": "Docker not available; host execution prohibited by S6 policy.",
        },
    )

    dummy_req = Request({"type": "http", "method": "POST", "path": "/showroom/run-code", "headers": []})
    payload = views_core.CodeRunPayload(code="print(1+1)", language="python")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(views_core.run_showroom_code(dummy_req, payload))
    assert exc.value.status_code == 501


# ---------------------------------------------------------------------------
# 3. SSRF & Path-Traversal-Schutz (EgressGuard, VisualWebAgent, VisionPipeline)
# ---------------------------------------------------------------------------

def test_egress_guard_check_public_url_blocks_internal_and_file():
    from utils.egress_guard import EgressBlocked, check_public_url

    for bad in (
        "file:///etc/passwd",
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1:8420/api/auth/users",
        "http://10.0.0.1/admin",
        "http://192.168.1.1/",
        "http://localhost:2375/containers/json",
        "http://user:pass@example.com/",
    ):
        with pytest.raises(EgressBlocked):
            check_public_url(bad)


def test_visual_web_agent_blocks_ssrf_and_path_traversal(tmp_path):
    from backend.visual_web_agent import VisualWebAgent

    agent = VisualWebAgent(traces_dir=str(tmp_path))
    res_ssrf = agent.browse_and_capture("task-1", "http://169.254.169.254/latest/meta-data/")
    assert res_ssrf["status"] == "blocked"

    res_file = agent.browse_and_capture("task-1", "file:///etc/passwd")
    assert res_file["status"] == "blocked"

    res_trav = agent.browse_and_capture("../../evil", "http://93.184.216.34")
    assert res_trav["status"] == "blocked"


def test_vision_pipeline_blocks_paths_outside_jail(tmp_path):
    from backend.vision_pipeline import analyze_image_file

    outside_img = tmp_path / "secret.png"
    outside_img.write_bytes(b"\x89PNG\r\n\x1a\n")
    res = analyze_image_file(str(outside_img))
    assert res["status"] == "blocked"


# ---------------------------------------------------------------------------
# 4. Offline Memory Vault: AES-256-GCM AEAD + Manipulationsschutz
# ---------------------------------------------------------------------------

def test_offline_memory_vault_uses_aesgcm_and_detects_tampering(tmp_path):
    from backend.offline_memory_vault import aead_decrypt, aead_encrypt, recall_memory, store_memory

    key = b"0123456789abcdef0123456789abcdef"
    ct = aead_encrypt(key, b"vertrauliche notiz", aad=b"finance")
    assert ct.startswith(b"AGCM1")
    assert aead_decrypt(key, ct, aad=b"finance") == b"vertrauliche notiz"

    with pytest.raises(ValueError):
        aead_decrypt(key, ct, aad=b"wrong_aad")
    tampered = bytearray(ct)
    tampered[-1] ^= 0xFF
    with pytest.raises(ValueError):
        aead_decrypt(key, bytes(tampered), aad=b"finance")

    db_file = str(tmp_path / "vault.db")
    eid = store_memory("ops", "Strategie 2026 Content Pipeline", ["content"], db_path=db_file, key=key)
    assert eid.startswith("mem-")
    hits = recall_memory("ops", "Content Pipeline", db_path=db_file, key=key)
    assert len(hits) == 1 and "Content Pipeline" in hits[0]["content"]


# ---------------------------------------------------------------------------
# 5. Agent-Router: Interaktive Chats > 15 Runden + Provider-Payloads
# ---------------------------------------------------------------------------

def test_agent_router_circuit_breaker_allows_long_interactive_chat(monkeypatch):
    from backend.agent_router import AgentRouter

    router = AgentRouter()
    monkeypatch.setattr(
        router,
        "_get_guardian_policy",
        lambda: {
            "loop_detection_enabled": True,
            "max_steps_per_task": 15,
            "max_identical_turns": 3,
            "jaccard_similarity_threshold": 0.90,
        },
    )
    # 25 normale User/Assistant-Runden (50 Nachrichten) duerfen NICHT den Circuit-Breaker ausloesen
    msgs = [{"role": "system", "content": "Du bist Assistent."}]
    for i in range(25):
        msgs.append({"role": "user", "content": f"Frage Nummer {i} zu Thema {i * 7}"})
        msgs.append({"role": "assistant", "content": f"Antwort Nummer {i} mit komplett neuem Inhalt {i * 13}."})
    res = router.check_loop_or_circuit_breaker(msgs)
    assert res["tripped"] is False

    # 20 aufeinanderfolgende Assistant/Tool-Schritte ohne neue User-Nachricht muessen ausloesen
    runaway = [{"role": "user", "content": "Starte Autonomie"}] + [
        {"role": "assistant", "content": f"Autonomer Schritt {i} mit eigenem Ergebnis {i * 19}."}
        for i in range(20)
    ]
    res_runaway = router.check_loop_or_circuit_breaker(runaway)
    assert res_runaway["tripped"] is True


def test_agent_router_only_attaches_reasoning_to_capable_models():
    from backend.agent_router import AgentRouter

    router = AgentRouter()
    msgs = [{"role": "user", "content": "Hallo"}]
    keys = {"OPENAI_API_KEY": "sk-test", "ANTHROPIC_API_KEY": "sk-ant-test"}

    _, _, payload_4o = router._build_request_payload(
        msgs, "openai", "gpt-4o-mini", keys, False, 1024, "high"
    )
    assert "reasoning_effort" not in payload_4o

    _, _, payload_o3 = router._build_request_payload(
        msgs, "openai", "o3-mini", keys, False, 1024, "high"
    )
    assert payload_o3.get("reasoning_effort") == "high"

    _, _, payload_haiku3 = router._build_request_payload(
        msgs, "anthropic", "claude-3-5-haiku-20241022", keys, False, 1024, "high"
    )
    assert "thinking" not in payload_haiku3

    _, _, payload_sonnet4 = router._build_request_payload(
        msgs, "anthropic", "claude-sonnet-4-20250514", keys, False, 1024, "high"
    )
    assert payload_sonnet4.get("thinking", {}).get("type") == "enabled"


# ---------------------------------------------------------------------------
# 6. Orchestrierung: Fan-In eskaliert bei fehlgeschlagenen Geschwistern
# ---------------------------------------------------------------------------

def test_fan_in_blocks_parent_when_sibling_fails(tmp_path):
    from archon.core.orchestration import _fan_in_maybe_start_synthesis

    state = {
        "tasks": [
            {"id": "proj-1", "title": "Hauptprojekt", "status": "active", "synthesis_started": False},
            {"id": "sub-1", "parent_project_id": "proj-1", "status": "completed"},
            {"id": "sub-2", "parent_project_id": "proj-1", "status": "failed"},
        ]
    }
    saved = {}
    cascade_called = []

    def _load():
        return json.loads(json.dumps(state))

    def _write(new_data):
        saved.clear()
        saved.update(new_data)

    async def _cascade(pid):
        cascade_called.append(pid)

    asyncio.run(
        _fan_in_maybe_start_synthesis(
            "proj-1",
            load_mc=_load,
            write_mc_atomic=_write,
            update_mc=None,  # Legacy-Pfad: Test-Fixture statt Produktions-DB
            mc_async_lock=asyncio.Lock(),
            run_cascade=_cascade,
        )
    )
    assert cascade_called == []
    parent = next(t for t in saved["tasks"] if t["id"] == "proj-1")
    assert parent["status"] == "blocked"
    assert "sub-2" in parent.get("failure_reason", "")


# ---------------------------------------------------------------------------
# 7. LocalMemoryBridge schliesst SQLite-Verbindungen sauber
# ---------------------------------------------------------------------------

def test_local_memory_bridge_closes_connection_on_context_exit(tmp_path):
    from local_memory_bridge import LocalMemoryBridge

    db_file = str(tmp_path / "mem.db")
    bridge = LocalMemoryBridge(db_path=db_file, vault_path=str(tmp_path))
    with bridge._get_conn() as conn:
        conn.execute("SELECT 1")
    # Nach Verlassen des with-Blocks muss die Connection geschlossen sein
    with pytest.raises(Exception):
        conn.execute("SELECT 1")


# ---------------------------------------------------------------------------
# 8. Agent-Aliases fuer Workflow-Templates auf echte Kader-IDs
# ---------------------------------------------------------------------------

def test_agent_aliases_map_workflow_roles_to_real_profiles():
    from backend.agent_aliases import resolve_agent_id

    profiles_path = os.path.join(ROOT, "agent_profiles.json")
    raw = json.loads(open(profiles_path, encoding="utf-8").read())
    real_ids = {p["id"] for p in (raw if isinstance(raw, list) else raw.get("agents", [])) if isinstance(p, dict) and p.get("id")}

    for short_role in ("research", "writer", "qa", "engineer", "analyst", "security", "seo", "video", "repurposing"):
        mapped = resolve_agent_id(short_role)
        assert mapped in real_ids, f"Alias {short_role!r} -> {mapped!r} existiert nicht in agent_profiles.json"


def test_passkey_hardening_system_category_uv_and_authdata(tmp_path, monkeypatch):
    import base64
    import hashlib
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    import backend.passkey_hitl as pk

    monkeypatch.setattr(pk, "PASSKEY_FILE", str(tmp_path / "passkey.json"))
    assert pk.DEFAULT_CATEGORIES.get("system") is True

    # Ohne Credentials sind Hochrisiko-Kategorien hart fail-closed. Die
    # ERSTREGISTRIERUNG bleibt davon ausgenommen (kein Lockout).
    for category in ("system", "destructive_actions", "payments"):
        assert pk.is_passkey_required("u_ohne_cred", category) is True
    assert pk.is_additional_passkey_registration_protected("u_ohne_cred") is False
    with pytest.raises(ValueError, match="Kein Passkey"):
        pk.create_hitl_assertion_options("u_ohne_cred", "localhost", category="system")

    priv = ec.generate_private_key(ec.SECP256R1())
    spki_b64 = base64.urlsafe_b64encode(
        priv.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    ).decode().rstrip("=")

    def _client_data():
        opts = pk.create_registration_options("u_hard", "hard", "localhost")
        return base64.urlsafe_b64encode(json.dumps({
            "type": "webauthn.create",
            "challenge": opts["challenge"],
            "origin": "http://localhost:8501",
        }).encode()).decode().rstrip("=")

    # Falscher rpIdHash bei korrekter Laenge (53 Byte inkl. AAGUID) -> ablehnen.
    bad_auth = _registration_auth_data("evil.example.com", flags=0x05)
    assert len(bad_auth) >= 53
    with pytest.raises(ValueError, match="rpIdHash"):
        pk.verify_and_store_registration(
            user_id="u_hard",
            credential_id="cred_1",
            client_data_b64=_client_data(),
            public_key_spki_b64=spki_b64,
            authenticator_data_b64=_b64u(bad_auth),
            attestation_object_b64=_ATTESTATION_OBJECT,
        )

    # Alte Fixtures OHNE authenticatorData werden heute hart abgelehnt.
    with pytest.raises(ValueError, match="authenticatorData"):
        pk.verify_and_store_registration(
            user_id="u_hard",
            credential_id="cred_1",
            client_data_b64=_client_data(),
            public_key_spki_b64=spki_b64,
            authenticator_data_b64="",
            attestation_object_b64=_ATTESTATION_OBJECT,
        )

    # Korrektes rpIdHash + UP|UV (0x05) + AAGUID -> akzeptiert.
    good_auth = _registration_auth_data("localhost", flags=0x05)
    cfg = pk.verify_and_store_registration(
        user_id="u_hard",
        credential_id="cred_1",
        client_data_b64=_client_data(),
        public_key_spki_b64=spki_b64,
        authenticator_data_b64=_b64u(good_auth),
        attestation_object_b64=_ATTESTATION_OBJECT,
    )
    assert len(cfg["credentials"]) == 1

    # Auch nach Registrierung bleibt system/destructive_actions hart erforderlich.
    assert pk.is_passkey_required("u_hard", "system") is True
    assert pk.is_passkey_required("u_hard", "destructive_actions") is True

    # UV-Downgrade-Schutz: Token ohne uv_verified darf nicht fuer payments/system eingelöst werden
    pk._PROOF_TOKENS["tok_no_uv"] = {
        "user_id": "u_hard",
        "credential_id": "cred_1",
        "category": "all",
        "uv_verified": False,
        "created_ts": 9999999999.0,
    }
    assert pk.consume_hitl_proof_token("tok_no_uv", "u_hard", category="payments") is False
    assert pk.consume_hitl_proof_token("tok_no_uv", "u_hard", category="system") is False


def test_approval_policy_hmac_mixed_chain_and_fail_closed(tmp_path, monkeypatch):
    import sqlite3
    import backend.approval_policy_engine as ape
    import backend.audit_log as al

    db_file = str(tmp_path / "approval.db")
    monkeypatch.delenv("ARCHON_AUDIT_HMAC_KEY", raising=False)
    monkeypatch.delenv("ARCHON_AUDIT_HMAC_EPOCHS", raising=False)
    monkeypatch.delenv("ARCHON_AUDIT_LEGACY_MAX_BLOCK", raising=False)

    # Der Abschalter ist restlos entfernt: ohne Key wirft jeder Schreibversuch.
    with pytest.raises(RuntimeError, match="ARCHON_AUDIT_HMAC_KEY"):
        al.sign_block("legacy-attempt")

    # Historische Legacy-Bloecke (nacktes SHA-256) als SQLite-Fixture anlegen.
    # Der Produktionspfad darf sie ohne HMAC-Key nicht mehr erzeugen.
    conn = sqlite3.connect(db_file)
    conn.execute("""CREATE TABLE approval_policies (
        id INTEGER PRIMARY KEY AUTOINCREMENT, domain TEXT NOT NULL,
        policy_key TEXT NOT NULL UNIQUE, policy_value TEXT NOT NULL,
        label TEXT, description TEXT, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE approval_policy_audit_chain (
        id INTEGER PRIMARY KEY AUTOINCREMENT, prev_hash TEXT NOT NULL,
        current_hash TEXT NOT NULL, timestamp TEXT NOT NULL, user_id TEXT NOT NULL,
        action TEXT NOT NULL, domain TEXT, policy_key TEXT, old_value TEXT,
        new_value TEXT, signature_valid INTEGER DEFAULT 1)""")
    conn.execute("""INSERT INTO approval_policies
        (domain, policy_key, policy_value, label, description, updated_at, updated_by)
        VALUES ('finance', 'finance_auto_approval_max', '50.00', 'Legacy', 'Legacy', '2026-01-01', 'system')""")
    genesis, ts = ape.GENESIS_HASH, "2026-01-01T00:00:00+00:00"
    legacy_payload = f"{genesis}|{ts}|system|INIT|finance|finance_auto_approval_max|50.00"
    legacy_hash = hashlib.sha256(legacy_payload.encode("utf-8")).hexdigest()
    conn.execute("""INSERT INTO approval_policy_audit_chain
        (id, prev_hash, current_hash, timestamp, user_id, action, domain, policy_key, old_value, new_value)
        VALUES (1, ?, ?, ?, 'system', 'INIT', 'finance', 'finance_auto_approval_max', '', '50.00')""",
                 (genesis, legacy_hash, ts))
    conn.commit()
    conn.close()

    # HMAC-Key setzen und Legacy-Grenze markieren -> gemischte Kette bleibt gueltig.
    monkeypatch.setenv("ARCHON_AUDIT_LEGACY_MAX_BLOCK", "1")
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "0123456789abcdef0123456789abcdef")
    eng = ape.ApprovalPolicyEngine(db_path=db_file)
    v1 = eng.verify_audit_integrity()
    assert v1["valid"] is True
    assert v1["hmac_blocks"] == 0

    h_hmac = eng._log_audit_change("admin", "UPDATE", "finances", "max_auto", "100", "250")
    assert h_hmac.startswith(al.HMAC_PREFIX)

    v2 = eng.verify_audit_integrity()
    assert v2["valid"] is True
    assert v2["hmac_active"] is True
    assert v2["hmac_blocks"] == 1

    # Fehlt der HMAC-Key spaeter, schlaegt verify_audit_integrity() fail-closed fehl.
    monkeypatch.delenv("ARCHON_AUDIT_HMAC_KEY", raising=False)
    v3 = eng.verify_audit_integrity()
    assert v3["valid"] is False
    with pytest.raises(RuntimeError, match="ARCHON_AUDIT_HMAC_KEY"):
        eng._log_audit_change("admin", "UPDATE", "finances", "max_auto", "250", "300")
