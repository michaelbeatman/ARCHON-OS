"""
Regression & Security Suite:
1. Audit-Log-Erweiterung: Pro LLM-Dispatch realer Ziel-Endpunkt, Provider, Modell & Ziel-Host.
2. Zero-Egress-Konfiguration: Keine Daten verlassen das Haus (insb. Cloud-Modelle & OmniRoute-Cloud-Proxying).
3. Privacy-Router-Design: Harter Fail-Closed Block bei sensiblen Kategorien (Finanzen, Verträge, CRM), falls Lokalmodell offline.
4. Docker-Netzwerk-Isolation: `archon-worker-zero-egress_net` & `archon-sandbox_net` mit `internal: true` (keine Internet-Route).
5. SHA-256-Hashkette: Manipulationssichere Verkettung & Spaltenkonsistenz für jeden einzelnen LLM-Call.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


# ============================================================================
# 1 & 5: Audit-Log-Erweiterung & SHA-256-Hashkette für LLM-Dispatches
# ============================================================================

def test_sanitize_llm_endpoint_zones_and_redaction():
    from backend.audit_log import sanitize_llm_endpoint

    ep, host, zone = sanitize_llm_endpoint("https://openrouter.ai/api/v1/chat/completions?api_key=sk-secret-123&foo=bar")
    assert ep == "https://openrouter.ai/api/v1/chat/completions?api_key=REDACTED&foo=bar"
    assert host == "openrouter.ai"
    assert zone == "EXTERNAL_CLOUD"
    assert "sk-secret-123" not in ep

    ep_loc, host_loc, zone_loc = sanitize_llm_endpoint("http://127.0.0.1:11434/v1/chat/completions")
    assert ep_loc == "http://127.0.0.1:11434/v1/chat/completions"
    assert host_loc == "127.0.0.1:11434"
    assert zone_loc == "LOCAL_ON_PREM"

    ep_gw, host_gw, zone_gw = sanitize_llm_endpoint("http://omniroute:20128/v1/chat/completions")
    assert ep_gw == "http://omniroute:20128/v1/chat/completions"
    assert host_gw == "omniroute:20128"
    assert zone_gw == "INTERNAL_GATEWAY"


def test_sha256_hash_chain_records_and_verifies_every_llm_dispatch(tmp_path):
    from backend.audit_log import ChainedAuditLog, GENESIS_HASH

    db_file = str(tmp_path / "audit_test.db")
    alog = ChainedAuditLog(db_path=db_file)

    r1 = alog.record_llm_dispatch(
        agent_id="tax_holding_advisor",
        provider="local",
        model="llama3.2",
        target_endpoint="http://127.0.0.1:11434/v1/chat/completions",
        data_category="finance",
        http_status=200,
        zero_egress_active=True,
    )
    r2 = alog.record_llm_dispatch(
        agent_id="fullstack_dev",
        provider="openrouter",
        model="deepseek/deepseek-chat",
        target_endpoint="https://openrouter.ai/api/v1/chat/completions",
        data_category="general",
        http_status=200,
        zero_egress_active=False,
    )

    assert r1["prev_hash"] == GENESIS_HASH
    assert r2["prev_hash"] == r1["current_hash"]
    assert r1["target_host"] == "127.0.0.1:11434"
    assert r2["target_host"] == "openrouter.ai"
    assert r2["target_endpoint"] == "https://openrouter.ai/api/v1/chat/completions"

    ver = alog.verify_integrity()
    assert ver["valid"] is True
    assert ver["total_records"] == 2
    assert ver["llm_dispatch_records"] == 2
    assert ver["latest_hash"] == r2["current_hash"]

    dispatches = alog.list_llm_dispatches(limit=10)
    assert len(dispatches) == 2
    assert dispatches[0]["provider"] == "openrouter"
    assert dispatches[0]["model"] == "deepseek/deepseek-chat"
    assert dispatches[0]["target_host"] == "openrouter.ai"
    assert dispatches[1]["provider"] == "local"
    assert dispatches[1]["egress_zone"] == "LOCAL_ON_PREM"

    # CSV-Compliance-Export enthält Provider, Modell, Ziel_Host, Ziel_Endpunkt
    csv_exp = alog.generate_compliance_export("csv")
    assert "Ziel_Host" in csv_exp["content"]
    assert "openrouter.ai" in csv_exp["content"]
    assert "127.0.0.1:11434" in csv_exp["content"]


def test_sha256_chain_detects_column_or_payload_tampering(tmp_path):
    from backend.audit_log import ChainedAuditLog

    db_file = str(tmp_path / "tamper_test.db")
    alog = ChainedAuditLog(db_path=db_file)
    alog.record_llm_dispatch(
        agent_id="crm_specialist",
        provider="local",
        model="llama3.2",
        target_endpoint="http://127.0.0.1:11434/v1/chat/completions",
        data_category="crm",
        http_status=200,
        zero_egress_active=True,
    )
    assert alog.verify_integrity()["valid"] is True

    # Manipuliere nur die Indexspalte target_host (ohne payload_json anzufassen)
    conn = sqlite3.connect(db_file)
    conn.execute("UPDATE audit_log SET target_host = 'evil.example.com' WHERE id = 1")
    conn.commit()
    conn.close()

    ver_col = alog.verify_integrity()
    assert ver_col["valid"] is False
    assert ver_col["corrupted_id"] == 1
    assert "target_host" in ver_col["reason"]


# ============================================================================
# 2 & 3: Zero-Egress-Konfiguration & Privacy-Router Hard-Block
# ============================================================================

@pytest.mark.parametrize("sens_cat", ["finance", "finanzen", "contracts", "verträge", "crm"])
def test_privacy_router_enforces_hard_block_for_sensitive_categories_when_local_offline(sens_cat, monkeypatch):
    from backend import privacy_router as pr

    # Selbst wenn ein Mistral-Key im System existiert, erzwingt hard_block_on_local_offline=True den harten Block!
    monkeypatch.setenv("MISTRAL_API_KEY", "mis_should_never_be_used")
    cfg = dict(pr.DEFAULT_PRIVACY_CONFIG)
    cfg["sensitive_local_routing"] = True
    cfg["hard_block_on_local_offline"] = True
    cfg["fallback_to_eu"] = True  # Sogar bei versehentlich gesetztem Flag gewinnt Hard-Block!

    with patch("backend.privacy_router.get_privacy_config", return_value=cfg), \
         patch("backend.privacy_router.check_local_llm_status", return_value={"available": False, "error": "Connection refused"}):
        decision = pr.route_sensitive_payload(
            category=sens_cat,
            messages=[{"role": "user", "content": "Geheimer Vertrag & Umsatzliste"}],
            default_provider="openrouter",
            default_model="deepseek/deepseek-chat",
        )

    assert decision["blocked"] is True
    assert decision["routed"] is False
    assert decision["provider"] is None
    assert decision["error_code"] == "LOCAL_LLM_OFFLINE_HARD_BLOCK"


def test_zero_egress_blocks_cloud_models_and_omniroute_cloud_proxy(tmp_path):
    from backend.audit_log import ChainedAuditLog
    from backend.llm_egress_guard import ZeroEgressBlockedError, evaluate_and_gate_llm_dispatch
    from backend import privacy_router as pr

    alog = ChainedAuditLog(db_path=str(tmp_path / "ze_gate.db"))
    cfg = dict(pr.DEFAULT_PRIVACY_CONFIG)
    cfg["zero_egress_strict"] = True
    cfg["sensitive_local_routing"] = True
    cfg["hard_block_on_local_offline"] = True
    cfg["fallback_to_eu"] = False

    # Fall A: Lokales Modell ist online, aber jemand versucht explizit OpenRouter-Endpunkt aufzurufen -> BLOCK
    with patch("backend.llm_egress_guard.get_privacy_config", return_value=cfg), \
         patch("backend.privacy_router.get_privacy_config", return_value=cfg), \
         patch("backend.privacy_router.check_local_llm_status", return_value={"available": True, "latency_ms": 2}):
        # Ohne erzwungene Cloud-URL wird sauber auf LOCAL_ON_PREM umgeleitet
        rerouted = evaluate_and_gate_llm_dispatch(
            agent_id="general_coder",
            provider="openrouter",
            model="deepseek/deepseek-chat",
            intended_url="",
            audit_logger=alog,
        )
        assert rerouted["allowed"] is True
        assert rerouted["routed_to_local"] is True
        assert rerouted["provider"] == "local"
        assert rerouted["target_url"].startswith("http://127.0.0.1:11434")

    # Fall B: Lokales Modell ist offline -> Harter Block + SHA-256 Block-Nachweis!
    with patch("backend.llm_egress_guard.get_privacy_config", return_value=cfg), \
         patch("backend.privacy_router.get_privacy_config", return_value=cfg), \
         patch("backend.privacy_router.check_local_llm_status", return_value={"available": False}):
        with pytest.raises(ZeroEgressBlockedError) as exc_info:
            evaluate_and_gate_llm_dispatch(
                agent_id="crm_sales_closer",
                provider="openrouter",
                model="openai/gpt-4o",
                audit_logger=alog,
            )
        assert exc_info.value.error_code == "LOCAL_LLM_OFFLINE_HARD_BLOCK"

    ver = alog.verify_integrity()
    assert ver["valid"] is True
    assert ver["llm_dispatch_records"] == 1
    dispatches = alog.list_llm_dispatches()
    assert dispatches[0]["action"] == "llm_dispatch_blocked_local_offline"


def test_verify_zero_egress_config_detects_misconfigured_cloud_local_url():
    from backend.privacy_router import DEFAULT_PRIVACY_CONFIG, verify_zero_egress_config

    bad_cfg = dict(DEFAULT_PRIVACY_CONFIG)
    bad_cfg["local_llm_url"] = "https://openrouter.ai/api/v1"
    check = verify_zero_egress_config(bad_cfg)
    assert check["zero_egress_verified"] is False
    assert check["local_egress_zone"] == "EXTERNAL_CLOUD"
    assert any("LOCAL_ON_PREM" in issue for issue in check["issues"])


def test_core_dispatcher_hard_blocks_crm_finance_contracts_without_cloud_leak(tmp_path, monkeypatch):
    import asyncio
    import core_dispatcher
    from backend.audit_log import ChainedAuditLog
    from backend import privacy_router as pr

    alog = ChainedAuditLog(db_path=str(tmp_path / "disp_block.db"))
    monkeypatch.setattr("backend.llm_egress_guard.chained_audit_log", alog)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-should-never-be-called")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-should-never-be-called")

    cfg = dict(pr.DEFAULT_PRIVACY_CONFIG)
    cfg["sensitive_local_routing"] = True
    cfg["hard_block_on_local_offline"] = True

    http_called = []
    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=lambda *a, **kw: http_called.append((a, kw)))

    with patch("backend.privacy_router.get_privacy_config", return_value=cfg), \
         patch("backend.llm_egress_guard.get_privacy_config", return_value=cfg), \
         patch("backend.privacy_router.check_local_llm_status", return_value={"available": False}), \
         patch.object(core_dispatcher, "_get_dispatcher_http_client", return_value=mock_client):
        res = asyncio.run(
            core_dispatcher._dispatch_to_omniroute_or_container_exec(
                agent_id="commercial_jurist_contracts",
                agent_name="Vertragsjurist",
                prompt="Prüfe diesen NDA-Vertrag",
                role="Legal & Contracts",
                model="deepseek/deepseek-chat",
                provider="openrouter",
            )
        )

    assert res["status"] == "blocked"
    assert res["error_code"] == "LOCAL_LLM_OFFLINE_HARD_BLOCK"
    # Beweis: KEIN EINZIGER ausgehender HTTP-Call an OpenRouter/Groq/OmniRoute wurde abgesetzt!
    assert http_called == []
    assert alog.verify_integrity()["valid"] is True
    assert alog.verify_integrity()["llm_dispatch_records"] == 1


def test_agent_router_logs_provider_model_and_target_host_in_sha256_chain(tmp_path, monkeypatch):
    import asyncio
    from backend.agent_router import AgentRouter
    from backend.audit_log import ChainedAuditLog
    from backend import privacy_router as pr

    alog = ChainedAuditLog(db_path=str(tmp_path / "router_audit.db"))
    monkeypatch.setattr("backend.llm_egress_guard.chained_audit_log", alog)

    cfg = dict(pr.DEFAULT_PRIVACY_CONFIG)
    cfg["zero_egress_strict"] = False
    cfg["sensitive_local_routing"] = True

    router = AgentRouter()
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json.return_value = {"choices": [{"message": {"content": "Verifizierte Antwort"}}]}

    fake_client = MagicMock()
    fake_client.post = AsyncMock(return_value=fake_resp)

    with patch("backend.privacy_router.get_privacy_config", return_value=cfg), \
         patch("backend.llm_egress_guard.get_privacy_config", return_value=cfg), \
         patch.object(router, "_get_shared_client", return_value=fake_client), \
         patch.object(router, "_daily_spend_usd", return_value=(0.0, True)):
        reply = asyncio.run(
            router.chat_completion(
                messages=[{"role": "user", "content": "Hallo Welt"}],
                provider="openrouter",
                model="deepseek/deepseek-chat",
                api_keys={"OPENROUTER_API_KEY": "sk-test-dummy"},
                agent_id="software_architect",
                role="Engineering",
            )
        )

    assert reply == "Verifizierte Antwort"
    ver = alog.verify_integrity()
    assert ver["valid"] is True
    assert ver["llm_dispatch_records"] == 1
    entry = alog.list_llm_dispatches()[0]
    assert entry["provider"] == "openrouter"
    assert entry["model"] == "deepseek/deepseek-chat"
    assert entry["target_host"] == "openrouter.ai"
    assert entry["target_endpoint"] == "https://openrouter.ai/api/v1/chat/completions"
    assert entry["egress_zone"] == "EXTERNAL_CLOUD"


# ============================================================================
# 4: Docker-Netzwerk-Isolation ohne Internet-Route für Worker
# ============================================================================

@pytest.mark.parametrize("compose_file", ["docker-compose.dev.yml", "docker-compose.yml"])
def test_compose_declares_internal_zero_egress_worker_network(compose_file):
    doc = yaml.safe_load((REPO_ROOT / compose_file).read_text(encoding="utf-8"))
    nets = doc.get("networks") or {}
    assert "archon-worker-zero-egress_net" in nets
    assert nets["archon-worker-zero-egress_net"].get("internal") is True
    assert "archon-sandbox_net" in nets
    assert nets["archon-sandbox_net"].get("internal") is True

    worker_svc = doc["services"]["archon-worker"]
    assert worker_svc["networks"] == ["archon-worker-zero-egress_net"]
    assert not worker_svc.get("ports"), "Worker darf keine Host-Ports publizieren"
    assert worker_svc.get("read_only") is True
    assert "ALL" in (worker_svc.get("cap_drop") or [])


def test_ephemeral_sandbox_rejects_non_internal_worker_network():
    from backend import ephemeral_sandbox as es

    non_internal_inspect = json.dumps([{"Name": "bad_net", "Internal": False}])
    with patch.object(es.subprocess, "run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # docker network create
            MagicMock(returncode=0, stdout=non_internal_inspect, stderr=""),  # docker network inspect
        ]
        with pytest.raises(es.ZeroEgressNetworkIsolationError):
            es._ensure_sandbox_network("bad_net")

    with pytest.raises(es.ZeroEgressNetworkIsolationError):
        es._ensure_sandbox_network("bridge")


# ============================================================================
# Einstellungen (System Control Center), Verfahrensdoku-PDF & Dokumentation
# ============================================================================

def test_autonomy_settings_enforces_immutable_sha256_audit_and_syncs_privacy(tmp_path, monkeypatch):
    from backend import autonomy_settings as aus
    from backend import privacy_router as pr

    tmp_settings = str(tmp_path / "settings.json")
    tmp_priv = str(tmp_path / "privacy_routing.json")
    monkeypatch.setattr(aus, "SETTINGS_FILE", tmp_settings)
    monkeypatch.setattr(pr, "PRIVACY_CFG_FILE", tmp_priv)
    monkeypatch.setattr(pr, "ROOT_SETTINGS_FILE", tmp_settings)

    saved = aus.save_autonomy_settings({
        "zero_egress_governance": {
            "zero_egress_strict": True,
            "sensitive_local_routing": False,  # Muss durch Strict-Invariante auf True gezwungen werden
            "hard_block_on_local_offline": False,  # Muss auf True gezwungen werden
            "sha256_dispatch_audit_enforced": False,  # Darf NIEMALS abschaltbar sein!
            "local_llm_url": "http://127.0.0.1:11434/v1",
            "local_llm_model": "qwen2.5",
        }
    })

    zeg = saved["zero_egress_governance"]
    assert zeg["sha256_dispatch_audit_enforced"] is True
    assert zeg["zero_egress_strict"] is True
    assert zeg["sensitive_local_routing"] is True
    assert zeg["hard_block_on_local_offline"] is True

    pcfg = pr.get_privacy_config()
    assert pcfg["zero_egress_strict"] is True
    assert pcfg["local_llm_model"] == "qwen2.5"
    assert pcfg["fallback_to_eu"] is False


def test_system_settings_ui_and_docs_contain_zero_egress_controls():
    modal_html = (REPO_ROOT / "static" / "views" / "system_settings_modal.html").read_text(encoding="utf-8")
    settings_js = (REPO_ROOT / "static" / "js" / "system_settings.js").read_text(encoding="utf-8")
    search_js = (REPO_ROOT / "static" / "js" / "settings_search.js").read_text(encoding="utf-8")

    for elem_id in (
        "sec4-zero-egress-governance-card",
        "sec4-ze-sensitive",
        "sec4-ze-hardblock",
        "sec4-ze-strict",
        "sec4-ze-noprefetch",
        "sec4-ze-worker-net",
        "aut-sandbox-zero-egress-net",
    ):
        assert elem_id in modal_html, f"Missing UI control {elem_id}"
        assert elem_id in settings_js or elem_id == "sec4-zero-egress-governance-card"

    assert "verifyZeroEgressSettingsPosture" in settings_js
    assert "sec4-zero-egress-governance-card" in search_js

    for doc_rel in (
        "docs/security/GOBD_ISO27001_AUDIT_LOG_GUIDE.md",
        "docs/security/LOCAL_LLM_PRIVACY_ROUTING_GUIDE.md",
        "docs/system/EU_AI_ACT_GOBD_COMPLIANCE_GUIDE.md",
        "SECURITY.md",
    ):
        txt = (REPO_ROOT / doc_rel).read_text(encoding="utf-8")
        assert "archon-worker-zero-egress_net" in txt or "llm_dispatch" in txt

