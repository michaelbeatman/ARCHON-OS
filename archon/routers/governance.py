"""Router /api/governance/ — ausgelagerte Routen (Modularisierung main.py -> archon/routers)."""

import asyncio
import datetime
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

import httpx
import yaml
from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Request, UploadFile

from archon.routers._rbac import require_admin_or_503
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

import core_dispatcher  # noqa: F401
from archon.core.runtime import (  # noqa: F401
    WORKSPACE_DIR, MEMORY_DIR, DATA_DIR, SETTINGS_FILE, OBSIDIAN_VAULT_DIR, APP_ROOT,
    add_ticker, broadcast_event, ticker_entries, _load_json, _save_json, atomic_write_json,
    logger,
)


from utils.docker_client import docker_client as _docker_client, parse_docker_stream  # noqa: F401


# --------------------------------------------------
# Dependency-Injektion statt Kopie
# --------------------------------------------------
# _load_mission_control_data, _save_mission_control_data, api_get_hermes_profiles
# werden aus main.py per configure() injiziert
_DEPS: Dict[str, Any] = {}

def configure(**deps: Any) -> None:
    """Registriert die aus main.py injizierten Abhängigkeiten (einmalig beim Import)."""
    _DEPS.update(deps)
    _missing = {"_load_mission_control_data", "_save_mission_control_data", "api_get_hermes_profiles"} - set(_DEPS)
    if _missing:
        logger.warning(f"[Router] governance: fehlende Dependencies {sorted(_missing)}")


def docker_socket_request(method: str, path: str, payload: dict = None, timeout: float = 1.0) -> bytes:
    """Lokale Fassade auf den abgesicherten DockerClient (Allowlist)."""
    try:
        return _docker_client.request(method, path, payload, timeout=timeout)
    except Exception as e:
        print(f"[Docker] {e}", file=sys.stderr)
        return b""

router = APIRouter()

@router.get("/api/governance/ai-act/inventory")
@router.get("/api/v1/governance/ai-act/inventory")
def api_ai_act_inventory():
    from backend.eu_ai_act_inventory import eu_ai_act_inventory_manager
    return {"status": "success", "inventory": eu_ai_act_inventory_manager.get_inventory()}


@router.get("/api/governance/ai-act/stats")
@router.get("/api/v1/governance/ai-act/stats")
def api_ai_act_stats():
    from backend.eu_ai_act_inventory import eu_ai_act_inventory_manager
    return {"status": "success", "stats": eu_ai_act_inventory_manager.get_stats()}


@router.post("/api/governance/ai-act/reclassify/{agent_id}")
@router.post("/api/v1/governance/ai-act/reclassify/{agent_id}")
def api_ai_act_reclassify(request: Request, agent_id: str, payload: dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    from backend.eu_ai_act_inventory import eu_ai_act_inventory_manager
    updated = eu_ai_act_inventory_manager.set_manual_override(agent_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' nicht gefunden.")
    return {"status": "success", "agent": updated}


@router.get("/api/governance/ai-act/export")
@router.get("/api/v1/governance/ai-act/export")
def api_ai_act_export():
    from backend.eu_ai_act_inventory import eu_ai_act_inventory_manager
    return {"status": "success", "markdown_report": eu_ai_act_inventory_manager.export_report_markdown()}


@router.post("/api/governance/data-classification/classify")
@router.post("/api/v1/governance/data-classification/classify")
def api_classify_content(payload: dict = Body(...)):
    from backend.data_classifier import DataClassifier
    text = payload.get("text", "")
    filename = payload.get("filename")
    res = DataClassifier.classify(text, filename=filename)
    return {"status": "success", "classification": res}


@router.get("/api/governance/data-classification/taxonomy")
@router.get("/api/v1/governance/data-classification/taxonomy")
def api_classification_taxonomy():
    from backend.data_classifier import CLASSIFICATION_METADATA
    tax = {lvl.value: meta for lvl, meta in CLASSIFICATION_METADATA.items()}
    return {"status": "success", "taxonomy": tax}


@router.post("/api/governance/data-classification/tag")
@router.post("/api/v1/governance/data-classification/tag")
def api_tag_classification(payload: dict = Body(...)):
    from backend.data_classifier import DataClassifier
    item_id = payload.get("item_id", "")
    item_type = payload.get("item_type", "task")
    text = payload.get("text", "")
    filename = payload.get("filename")
    if not item_id:
        raise HTTPException(status_code=400, detail="item_id erforderlich.")
    res = DataClassifier.tag_item(item_id, item_type, text, filename=filename)
    return {"status": "success", "tagged_item": res}


@router.get("/api/governance/data-classification/items")
@router.get("/api/v1/governance/data-classification/items")
def api_list_classifications(item_type: Optional[str] = None):
    from backend.data_classifier import DataClassifier
    items = DataClassifier.get_classifications(item_type=item_type)
    return {"status": "success", "items": items, "count": len(items)}


@router.post("/api/governance/promptfoo/run-eval")
def api_run_promptfoo_eval(request: Request, config_path: str = "/app/tests/promptfooconfig.yaml"):
    """
    Führt die vollständige Promptfoo Testmatrix im Docker-Container aus.

    RBAC: Container-Exec mit frei uebergebenem ``config_path`` — Admin-Sache.
    Der Zaun steht bewusst vor der ersten fachlichen Anweisung.
    """
    require_admin_or_503(request)  # RBAC: Codeausfuehrung im Container ist Admin-Sache
    exec_create_payload = {
        "AttachStdout": True,
        "AttachStderr": True,
        "Cmd": ["promptfoo", "eval", "-c", config_path, "--output", "/app/tests/eval_result.json"],
        "WorkingDir": "/app"
    }
    create_raw = docker_socket_request("POST", "/containers/promptfoo/exec", exec_create_payload, timeout=5.0)
    if not create_raw:
        return {"status": "error", "message": "Docker Proxy nicht erreichbar."}
    try:
        exec_id = json.loads(create_raw.decode('utf-8')).get("Id")
        if not exec_id:
            return {"status": "error", "message": "Exec-Instanz konnte nicht erstellt werden."}
    except Exception as e:
        return {"status": "error", "message": f"Ungültige Exec-Antwort: {str(e)}"}

    start_payload = {"Detach": False, "Tty": False}
    start_raw = docker_socket_request("POST", f"/exec/{exec_id}/start", start_payload, timeout=120.0)
    output = parse_docker_stream(start_raw).strip()
    return {"status": "success", "output": output}


@router.post("/api/governance/test-profile/{agent_id}")
async def test_agent_profile_governance(agent_id: str):
    """
    Führt die Governance-Testsuite (Anti-Floskel, Markdown, JSON-Format)
    für das angegebene Agentenprofil aus und liefert die Erfolgsquote zurück.
    """
    profiles = _DEPS["api_get_hermes_profiles"]() if "api_get_hermes_profiles" in _DEPS else []
    prof = next((p for p in profiles if p.get("id") == agent_id or p.get("person_name") == agent_id), None)
    agent_name = prof.get("person_name", agent_id) if prof else agent_id
    role = prof.get("name", "Spezialist") if prof else "Spezialist"
    system_prompt = (prof.get("system_prompt") if prof else None) or (prof.get("prompt") if prof else None) or f"Du bist {agent_name} in Archon OS."
    model = (prof.get("model") if prof else None) or "auto/best-fast"

    test_cases = [
        {
            "id": 1,
            "name": "Anti-Floskel Test (Strategie)",
            "prompt": "Erstelle eine kurze Strategieübersicht für die Internationalisierung unserer B2B-Plattform. Halte dich an striktes Markdown.",
            "not_contains": ["Möchten Sie", "Soll ich", "Gerne helfe ich", "Wie kann ich"],
            "contains": ["## "]
        },
        {
            "id": 2,
            "name": "Executive Decision Test (Headline & Klarheit)",
            "prompt": "Bewerte das Risiko einer Verlagerung von Cloud-Workloads nach Frankfurt mit klaren Handlungsschritten.",
            "not_contains": ["Gerne helfe ich", "Möchten Sie", "Soll ich"],
            "contains": ["## "]
        },
        {
            "id": 3,
            "name": "Outreach Test (Keine Werbephrasen)",
            "prompt": "Formuliere 3 klare Kernbotschaften für den Launch unserer API als Markdown.",
            "not_contains": ["Gerne helfe ich", "Möchten Sie"],
            "contains": ["## "]
        },
        {
            "id": 4,
            "name": "Subtask Output Test (Striktes JSON)",
            "prompt": "Gib mir eine Liste von 2 Arbeitspaketen mit den Keys task_id und title im validen JSON-Format zurück. Antworte ausschließlich mit dem JSON-Objekt.",
            "is_json": True,
            "not_contains": ["Gerne helfe ich"]
        },
        {
            "id": 5,
            "name": "Governance Prüfbericht (Fakten ohne Füllwörter)",
            "prompt": "Erstelle einen kurzen Prüfbericht zur DSGVO-Konformität von IP-Logging in Archon OS.",
            "not_contains": ["Wie kann ich", "Gerne helfe ich"],
            "contains": ["## "]
        }
    ]

    results = []
    passed_count = 0

    for tc in test_cases:
        try:
            res = await core_dispatcher.dispatch_to_omniroute_or_container(
                agent_id=agent_id,
                agent_name=agent_name,
                prompt=tc["prompt"],
                role=role,
                system_prompt=system_prompt,
                model=model,
                timeout=20
            )
            content = res.get("content", "").strip()
            
            assertions = []
            test_passed = True
            
            for nc in tc.get("not_contains", []):
                failed = nc.lower() in content.lower()
                assertions.append({
                    "type": "not-contains",
                    "value": nc,
                    "passed": not failed
                })
                if failed:
                    test_passed = False
                    
            for c in tc.get("contains", []):
                passed = c.lower() in content.lower()
                assertions.append({
                    "type": "contains",
                    "value": c,
                    "passed": passed
                })
                if not passed:
                    test_passed = False

            if tc.get("is_json"):
                valid_json = False
                try:
                    clean_c = content
                    if "```json" in clean_c:
                        clean_c = clean_c.split("```json")[1].split("```")[0].strip()
                    elif "```" in clean_c:
                        clean_c = clean_c.split("```")[1].split("```")[0].strip()
                    json.loads(clean_c)
                    valid_json = True
                except Exception:
                    valid_json = False
                assertions.append({
                    "type": "is-json",
                    "passed": valid_json
                })
                if not valid_json:
                    test_passed = False

            if test_passed:
                passed_count += 1

            results.append({
                "test_id": tc["id"],
                "name": tc["name"],
                "passed": test_passed,
                "assertions": assertions,
                "sample_output": content[:120] + "..." if len(content) > 120 else content
            })
        except Exception as ex:
            results.append({
                "test_id": tc["id"],
                "name": tc["name"],
                "passed": False,
                "error": str(ex)
            })

    total_count = len(test_cases)
    score_str = f"{passed_count}/{total_count} Tests bestanden"
    
    now_t = datetime.datetime.now().strftime("%H:%M:%S")
    mc_data = _DEPS["_load_mission_control_data"]()
    mc_data.setdefault("audit_logs", []).insert(0, {
        "time": now_t,
        "source": "Governance",
        "msg": f"Promptfoo Evaluierung für {agent_name}: {score_str}"
    })
    add_ticker("Governance", f"Testsuite für {agent_name}: {score_str}")
    _DEPS["_save_mission_control_data"](mc_data)

    return {
        "status": "ok",
        "agent_id": agent_id,
        "agent_name": agent_name,
        "score": score_str,
        "passed_count": passed_count,
        "total_count": total_count,
        "pass_rate_pct": round((passed_count / total_count) * 100, 1),
        "details": results
    }
