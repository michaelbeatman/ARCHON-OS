"""
tests/test_m47_demo_mode.py
Milestone 47 — Comprehensive tests for Read-Only Live-Demo Mode (`ARCHON_DEMO_MODE=true`):
- Pure pass-through when `ARCHON_DEMO_MODE` is unset/false
- Hard 403 (`demo_blocked`) on all sandbox/container/docker/raw_config/update/proxy routes across all methods
- Strict 403 (`demo_read_only`) on all non-preview POST/PUT/DELETE/PATCH mutations
- Instant zero-egress deterministic 200 OK simulation on chat/quickchat/agent-chat/boardroom/templates POSTs
- `/api/demo/status` and `/api/demo/showcase?lang=en|de` router contracts & dataset completeness
- `seed_demo_workspace()` ephemeral tmpfs seeder
- `docker-compose.demo.yml`, `static/js/demo_banner.js`, and `docs/system/LIVE_DEMO_MODE_GUIDE.md` validation
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pytest
import yaml
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from archon.routers.demo import router as demo_router  # noqa: E402
from backend.demo_mode import (  # noqa: E402
    DEMO_HARD_BLOCKED_PREFIXES,
    DEMO_REPO_URL,
    DemoModeMiddleware,
    build_demo_chat_response,
    is_demo_mode,
    seed_demo_workspace,
)


def _build_test_app() -> Tuple[FastAPI, List[Tuple[str, str]]]:
    """Build an isolated FastAPI app wrapped with DemoModeMiddleware and call spy."""
    calls: List[Tuple[str, str]] = []
    app = FastAPI()
    app.include_router(demo_router)

    @app.get("/health")
    def health():
        calls.append(("GET", "/health"))
        return {"ok": True}

    @app.get("/api/deals")
    def list_deals():
        calls.append(("GET", "/api/deals"))
        return {"deals": ["existing"]}

    @app.post("/api/deals")
    def create_deal():
        calls.append(("POST", "/api/deals"))
        return {"created": True}

    @app.put("/api/settings")
    def update_settings():
        calls.append(("PUT", "/api/settings"))
        return {"updated": True}

    @app.delete("/api/deals/{deal_id}")
    def delete_deal(deal_id: str):
        calls.append(("DELETE", f"/api/deals/{deal_id}"))
        return {"deleted": deal_id}

    @app.patch("/api/chat/sessions/{sid}")
    def patch_session(sid: str):
        calls.append(("PATCH", f"/api/chat/sessions/{sid}"))
        return {"patched": sid}

    @app.post("/api/templates")
    def save_template():
        calls.append(("POST", "/api/templates"))
        return {"saved": True}

    # Dangerous / exec / admin / proxy endpoints that must NEVER run in demo mode
    @app.api_route("/api/sandbox/run", methods=["GET", "POST"])
    def sandbox_run():
        calls.append(("EXEC", "/api/sandbox/run"))
        return {"executed": True}

    @app.api_route("/api/v1/container/exec", methods=["GET", "POST"])
    def container_exec():
        calls.append(("EXEC", "/api/v1/container/exec"))
        return {"executed": True}

    @app.get("/api/docker/containers")
    def docker_containers():
        calls.append(("GET", "/api/docker/containers"))
        return {"containers": []}

    @app.post("/api/v1/system/update")
    def system_update():
        calls.append(("POST", "/api/v1/system/update"))
        return {"updated": True}

    @app.get("/api/hermes/raw_config")
    def raw_config():
        calls.append(("GET", "/api/hermes/raw_config"))
        return {"api_key": "plaintext-secret"}

    @app.get("/n8n-proxy/rest/workflows")
    def n8n_proxy():
        calls.append(("GET", "/n8n-proxy/rest/workflows"))
        return {"proxied": True}

    @app.get("/omniroute-proxy/v1/models")
    def omniroute_proxy():
        calls.append(("GET", "/omniroute-proxy/v1/models"))
        return {"proxied": True}

    @app.get("/api/proxy")
    def ssrf_proxy():
        calls.append(("GET", "/api/proxy"))
        return {"proxied": True}

    # Real handlers behind demo-safe preview endpoints (must be bypassed in demo mode)
    @app.post("/api/quickchat")
    def real_quickchat():
        calls.append(("POST", "/api/quickchat"))
        return {"live_llm": True}

    @app.post("/api/chat")
    def real_chat():
        calls.append(("POST", "/api/chat"))
        return {"live_llm": True}

    @app.post("/api/agent-chat")
    def real_agent_chat():
        calls.append(("POST", "/api/agent-chat"))
        return {"live_llm": True}

    @app.post("/api/boardroom/run")
    def real_boardroom_run():
        calls.append(("POST", "/api/boardroom/run"))
        return {"live_llm": True}

    @app.post("/api/templates/{slug}/render")
    def real_template_render(slug: str):
        calls.append(("POST", f"/api/templates/{slug}/render"))
        return {"live_render": slug}

    @app.websocket("/api/v1/container/ws")
    async def container_ws(ws: WebSocket):
        await ws.accept()
        await ws.send_json({"shell": True})

    app.add_middleware(DemoModeMiddleware)
    return app, calls


# ---------------------------------------------------------------------------
# 1. Environment Flag & Pass-Through Behavior
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("val", ["", "0", "false", "FALSE", "no", "off", "random"])
def test_is_demo_mode_false_values(monkeypatch: pytest.MonkeyPatch, val: str):
    monkeypatch.setenv("ARCHON_DEMO_MODE", val)
    assert is_demo_mode() is False


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "YES", "on", "  true  "])
def test_is_demo_mode_true_values(monkeypatch: pytest.MonkeyPatch, val: str):
    monkeypatch.setenv("ARCHON_DEMO_MODE", val)
    assert is_demo_mode() is True


def test_passthrough_when_demo_mode_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ARCHON_DEMO_MODE", raising=False)
    app, calls = _build_test_app()
    client = TestClient(app)

    assert client.post("/api/deals").status_code == 200
    assert client.delete("/api/deals/d-1").status_code == 200
    assert client.post("/api/sandbox/run").status_code == 200
    assert client.get("/api/hermes/raw_config").status_code == 200
    assert client.post("/api/quickchat").json() == {"live_llm": True}

    assert ("POST", "/api/deals") in calls
    assert ("DELETE", "/api/deals/d-1") in calls
    assert ("EXEC", "/api/sandbox/run") in calls
    assert ("GET", "/api/hermes/raw_config") in calls
    assert ("POST", "/api/quickchat") in calls


# ---------------------------------------------------------------------------
# 2. Hard 403 Block on Dangerous / Exec / Secret / Proxy Paths
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/sandbox"),
        ("POST", "/api/sandbox/run"),
        ("GET", "/api/v1/container/exec"),
        ("POST", "/api/v1/container/exec"),
        ("GET", "/api/docker/containers"),
        ("GET", "/api/v1/system/update"),
        ("POST", "/api/v1/system/update"),
        ("GET", "/api/hermes/raw_config"),
        ("POST", "/api/hermes/raw_config"),
        ("GET", "/n8n-proxy/rest/workflows"),
        ("POST", "/n8n-proxy/rest/workflows"),
        ("GET", "/omniroute-proxy/v1/models"),
        ("GET", "/api/proxy"),
        ("POST", "/api/proxy"),
    ],
)
def test_hard_blocked_paths_return_403_demo_blocked(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str
):
    monkeypatch.setenv("ARCHON_DEMO_MODE", "true")
    app, calls = _build_test_app()
    client = TestClient(app)

    resp = client.request(method, path)
    assert resp.status_code == 403
    body = resp.json()
    assert body["status"] == "demo_blocked"
    assert body["demo_mode"] is True
    assert body["repo_url"] == DEMO_REPO_URL
    assert calls == [], f"Underlying handler must never execute for {method} {path}"


def test_hard_blocked_websocket_closed_in_demo_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ARCHON_DEMO_MODE", "true")
    app, _ = _build_test_app()
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/container/ws"):
            pass


# ---------------------------------------------------------------------------
# 3. Strict 403 Read-Only Guard on Mutations + Safe GET Pass-Through
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/deals"),
        ("PUT", "/api/settings"),
        ("DELETE", "/api/deals/deal-m47-01"),
        ("PATCH", "/api/chat/sessions/sess-1"),
        ("POST", "/api/templates"),  # Saving new template (exact path) must be blocked
    ],
)
def test_mutations_blocked_with_403_demo_read_only(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str
):
    monkeypatch.setenv("ARCHON_DEMO_MODE", "true")
    app, calls = _build_test_app()
    client = TestClient(app)

    resp = client.request(method, path, json={"test": 1})
    assert resp.status_code == 403
    body = resp.json()
    assert body["status"] == "demo_read_only"
    assert body["demo_mode"] is True
    assert body["repo_url"] == DEMO_REPO_URL
    assert calls == []


def test_safe_get_endpoints_allowed_in_demo_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ARCHON_DEMO_MODE", "true")
    app, calls = _build_test_app()
    client = TestClient(app)

    assert client.get("/health").status_code == 200
    assert client.get("/api/deals").status_code == 200
    assert ("GET", "/health") in calls
    assert ("GET", "/api/deals") in calls


# ---------------------------------------------------------------------------
# 4. Zero-Token Deterministic Interactive Preview Simulator
# ---------------------------------------------------------------------------

def test_deterministic_chat_response_generator_en_and_de():
    en_1 = build_demo_chat_response("Assess Benelux CAPEX ROI", "finance_lead", "en")
    en_2 = build_demo_chat_response("Assess Benelux CAPEX ROI", "finance_lead", "en")
    de_1 = build_demo_chat_response("Prüfe EU AI Act Risiken", "commercial_jurist_contracts", "de")

    assert en_1 == en_2
    assert "[DEMO SIMULATION — Zero Token Cost]" in en_1
    assert "[DEMO SIMULATION — Zero Token Cost]" in de_1
    assert "Clara" in en_1 and "Mittelstand Muster Precision GmbH" in en_1
    assert "Dr. Henrik Vogt" in de_1 and "Mittelstand Muster GmbH" in de_1


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/quickchat",
        "/api/v1/quickchat/send",
        "/api/chat",
        "/api/agent-chat",
        "/api/v1/agent/chat",
    ],
)
def test_interactive_chat_post_previews_return_200_zero_egress(
    monkeypatch: pytest.MonkeyPatch, endpoint: str
):
    monkeypatch.setenv("ARCHON_DEMO_MODE", "true")
    app, calls = _build_test_app()
    client = TestClient(app)

    resp = client.post(
        endpoint,
        json={
            "agent_id": "senior_fullstack_engineer",
            "message": "Explain local Ollama + SQLite WAL isolation",
            "lang": "en",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["demo_mode"] is True
    assert data["zero_token_cost"] is True
    assert "[DEMO SIMULATION — Zero Token Cost]" in data["reply"]
    assert "Lukas" in data["reply"]
    assert calls == [], "Real LLM handler must never be called in demo mode"


def test_chat_stream_preview_supports_sse_and_json(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ARCHON_DEMO_MODE", "true")
    app, calls = _build_test_app()
    client = TestClient(app)

    sse_resp = client.post(
        "/api/chat/stream",
        json={"agent_id": "red_team_challenger", "message": "Audit RFQ PDF security"},
    )
    assert sse_resp.status_code == 200
    assert sse_resp.headers["content-type"].startswith("text/event-stream")
    assert "[DEMO SIMULATION — Zero Token Cost]" in sse_resp.text
    assert '"type": "done"' in sse_resp.text

    json_resp = client.post(
        "/api/chat/stream",
        headers={"Accept": "application/json"},
        json={"agent_id": "red_team_challenger", "message": "Audit RFQ PDF security"},
    )
    assert json_resp.status_code == 200
    assert json_resp.json()["zero_token_cost"] is True
    assert calls == []


def test_boardroom_and_template_preview_posts(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ARCHON_DEMO_MODE", "true")
    app, calls = _build_test_app()
    client = TestClient(app)

    br = client.post(
        "/api/boardroom/run",
        json={"task": "Evaluate Benelux Expansion", "lang": "de"},
    )
    assert br.status_code == 200
    br_data = br.json()
    assert br_data["demo_mode"] is True
    assert br_data["zero_token_cost"] is True
    assert len(br_data["phases"]) == 6
    assert len(br_data["roi_table"]) >= 4
    assert "[DEMO SIMULATION — Zero Token Cost]" in br_data["synthesis"]

    tpl = client.post(
        "/api/templates/eu-ai-act-audit/render",
        json={"values": {"department": "CNC Metrology", "jurisdiction": "DE / EU"}},
    )
    assert tpl.status_code == 200
    tpl_data = tpl.json()
    assert tpl_data["status"] == "ok"
    assert tpl_data["demo_mode"] is True
    assert "CNC Metrology" in tpl_data["rendered_prompt"]
    assert "[DEMO SIMULATION — Zero Token Cost]" in tpl_data["rendered_prompt"]
    assert calls == []


# ---------------------------------------------------------------------------
# 5. Demo Status & Bilingual Showcase Router Endpoints
# ---------------------------------------------------------------------------

def test_demo_status_endpoint(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ARCHON_DEMO_MODE", "true")
    app, _ = _build_test_app()
    client = TestClient(app)

    resp = client.get("/api/demo/status?lang=en")
    assert resp.status_code == 200
    data = resp.json()
    assert data["demo_mode"] is True
    assert data["repo_url"] == "https://github.com/michaelbeatman/ARCHON-OS"
    assert "Mittelstand Muster" in data["tenant"]["name"]
    assert len(data["locked_features"]) >= 5


@pytest.mark.parametrize(
    "lang,expected_company_name",
    [
        ("en", "Mittelstand Muster Precision GmbH"),
        ("de", "Mittelstand Muster GmbH"),
    ],
)
def test_demo_showcase_bilingual_completeness(
    monkeypatch: pytest.MonkeyPatch, lang: str, expected_company_name: str
):
    monkeypatch.setenv("ARCHON_DEMO_MODE", "true")
    app, _ = _build_test_app()
    client = TestClient(app)

    resp = client.get(f"/api/demo/showcase?lang={lang}")
    assert resp.status_code == 200
    bundle = resp.json()

    assert bundle["lang"] == lang
    assert bundle["company"]["name"] == expected_company_name
    assert bundle["telemetry"]["local_ollama_share_pct"] > 70.0
    assert bundle["telemetry"]["monthly_saas_cost_avoided_eur"] > 4000.0

    # 6-phase Boardroom debate with required specialists + Chairman synthesis + ROI table
    assert len(bundle["boardroom_debates"]) == 1
    debate = bundle["boardroom_debates"][0]
    assert len(debate["phases"]) == 6
    handles = {p["agent_handle"] for p in debate["phases"]}
    assert {
        "@executive_decision_architect",
        "@finance_lead",
        "@commercial_jurist_contracts",
        "@red_team_challenger",
        "@senior_fullstack_engineer",
    }.issubset(handles)
    assert len(debate["roi_table"]) >= 4
    assert "|" in debate["synthesis"]

    # 8 Kanban tasks across all 5 statuses
    tasks = bundle["kanban_tasks"]
    assert len(tasks) == 8
    assert {t["status"] for t in tasks} == {"backlog", "todo", "in_progress", "review", "done"}

    # 6 B2B contacts, 5 pipeline deals, 5 GoBD invoices/quotes
    assert len(bundle["crm_contacts"]) == 6
    assert len(bundle["deals"]) == 5
    assert len(bundle["invoices"]) == 5
    for inv in bundle["invoices"]:
        assert inv["gobd_sha256_preview"].startswith("sha256:")


# ---------------------------------------------------------------------------
# 6. Ephemeral Workspace Seeding + Compose / JS / Docs Artifacts
# ---------------------------------------------------------------------------

def test_seed_demo_workspace_creates_valid_json_files(tmp_path: Path):
    summary = seed_demo_workspace(str(tmp_path), lang="de")
    assert summary["boardroom_count"] == 1
    assert summary["kanban_count"] == 8

    br_file = tmp_path / "boardroom_history.json"
    kb_file = tmp_path / "kanban_cards.json"
    assert br_file.is_file()
    assert kb_file.is_file()

    br_data = json.loads(br_file.read_text(encoding="utf-8"))
    kb_data = json.loads(kb_file.read_text(encoding="utf-8"))
    assert len(br_data) == 1 and len(br_data[0]["phases"]) == 6
    assert len(kb_data) == 8


def test_docker_compose_demo_yaml_hardening_invariants():
    compose_path = REPO_ROOT / "docker-compose.demo.yml"
    assert compose_path.is_file()
    raw_text = compose_path.read_text(encoding="utf-8")
    assert "docker.sock" not in raw_text

    parsed: Dict = yaml.safe_load(raw_text)
    services = parsed.get("services", {})
    assert len(services) == 1, "Demo compose must be a standalone single-container stack"

    svc = next(iter(services.values()))
    assert svc["read_only"] is True
    assert svc["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in svc["security_opt"]
    assert svc["mem_limit"] == "1g"

    env_joined = "\n".join(svc.get("environment", []))
    assert "ARCHON_DEMO_MODE=true" in env_joined
    for forbidden_key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "DOCKER_HOST"):
        assert forbidden_key not in env_joined

    tmpfs_joined = "\n".join(svc.get("tmpfs", []))
    for required_mount in ("/tmp", "/var/cache", "/app/data", "/app/agent_workspace"):
        assert required_mount in tmpfs_joined


def test_demo_banner_js_and_guide_present_and_valid():
    js_path = REPO_ROOT / "static" / "js" / "demo_banner.js"
    guide_path = REPO_ROOT / "docs" / "system" / "LIVE_DEMO_MODE_GUIDE.md"
    assert js_path.is_file()
    assert guide_path.is_file()

    js_src = js_path.read_text(encoding="utf-8")
    for token in ("/api/demo/status", "/api/demo/showcase", "demo_read_only", "demo_blocked", DEMO_REPO_URL):
        assert token in js_src

    node_bin = shutil.which("node")
    if node_bin:
        proc = subprocess.run([node_bin, "--check", str(js_path)], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr

    guide_text = guide_path.read_text(encoding="utf-8")
    assert "Caddy" in guide_text or "reverse_proxy" in guide_text
    assert "ARCHON_DEMO_MODE=true" in guide_text
    assert len(DEMO_HARD_BLOCKED_PREFIXES) >= 8
