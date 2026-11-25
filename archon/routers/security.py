from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes, require_admin_or_503
"""Router /api/security — ausgelagerte Routen.

Automatisch aus main.py extrahiert (Critical-Hardening / Modularisierung).
Enthaelt nur Endpunkte ohne Abhaengigkeit zu main.py-Interna; gemeinsame
Helfer kommen aus archon.core.runtime.
"""

import asyncio
import datetime
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, cast

import httpx
import yaml
from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

import core_dispatcher  # noqa: F401
from archon.core.runtime import (  # noqa: F401
    WORKSPACE_DIR, MEMORY_DIR, DATA_DIR, SETTINGS_FILE, OBSIDIAN_VAULT_DIR,
    add_ticker, broadcast_event, ticker_entries, _load_json, _save_json,
    atomic_write_json,
)

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])


# P0 / API_VALIDATION_ROADMAP Etappe 2c — extra="ignore" bewahrt Client-Kompatibilitaet.
class _SecurityRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")


class MaskSecretsRequest(_SecurityRequest):
    text: str = ""


class PiiScrubRequest(_SecurityRequest):
    text: str = ""
    session_id: str = ""


class PiiRehydrateRequest(_SecurityRequest):
    response_text: str = ""
    session_id: str = ""
    vault_map: Optional[Dict[str, Any]] = None


class EgressCheckRequest(_SecurityRequest):
    url: str = ""
    agent_id: str = "agent-worker"


class RbacCheckRequest(_SecurityRequest):
    role: str = "researcher"
    tool_name: str = "read_file"
    target_path: str = ""


class LintOutputRequest(_SecurityRequest):
    output_text: str = ""


class ExecutionReceiptIssueRequest(_SecurityRequest):
    task_id: str = "task-01"
    agent_role: str = "backend_architect"
    model_used: str = "deepseek/deepseek-chat"
    prompt_tokens: int = Field(default=500, ge=0)
    completion_tokens: int = Field(default=250, ge=0)
    cost_usd: float = Field(default=0.0012, ge=0)
    tools_invoked: List[str] = Field(default_factory=list)


@router.post("/api/security/mask-secrets")
def api_mask_secrets(payload: MaskSecretsRequest = Body(...)):
    data = payload.model_dump()
    from backend.secret_masker import mask_sensitive_text
    masked, count = mask_sensitive_text(data.get("text", ""))
    return {"status": "success", "masked_text": masked, "redacted_count": count}


@router.post("/api/security/pii-scrub")
def api_pii_scrub(payload: PiiScrubRequest = Body(...)):
    data = payload.model_dump()
    from backend.pii_scrubber import pii_scrubber
    return pii_scrubber.scrub_text(
        text=data.get("text", ""),
        session_id=data.get("session_id", "")
    )


@router.post("/api/security/pii-rehydrate")
def api_pii_rehydrate(request: Request, payload: PiiRehydrateRequest = Body(...)):
    require_admin_or_503(request)
    data = payload.model_dump()
    from backend.pii_scrubber import pii_scrubber
    return pii_scrubber.rehydrate_text(
        response_text=data.get("response_text", ""),
        session_id=data.get("session_id", ""),
        custom_vault=cast(Dict[str, str], data.get("vault_map"))
    )


@router.post("/api/security/egress-check")
def api_egress_firewall_check(payload: EgressCheckRequest = Body(...)):
    data = payload.model_dump()
    from backend.egress_firewall import egress_firewall
    return egress_firewall.check_url(
        target_url=data.get("url", ""),
        agent_id=data.get("agent_id", "agent-worker")
    )


@router.get("/api/security/egress-logs")
def api_egress_firewall_logs(request: Request, limit: int = 25):
    require_admin_or_503(request)  # Audit-Endpunkt: Admin only
    from backend.egress_firewall import egress_firewall
    return {"status": "success", "logs": egress_firewall.get_logs(limit=limit)}


@router.post("/api/security/rbac-check")
def api_rbac_jail_check(payload: RbacCheckRequest = Body(...)):
    data = payload.model_dump()
    from backend.agent_rbac_jail import agent_rbac_jail
    return agent_rbac_jail.check_access(
        role=data.get("role", "researcher"),
        tool_name=data.get("tool_name", "read_file"),
        target_path=data.get("target_path", "")
    )


@router.post("/api/security/lint-output")
def api_lint_agent_output(payload: LintOutputRequest = Body(...)):
    data = payload.model_dump()
    from backend.output_policy_linter import output_policy_linter
    return output_policy_linter.lint_and_clean(
        output_text=data.get("output_text", "")
    )


@router.post("/api/security/receipts/issue")
def api_issue_execution_receipt(request: Request, payload: ExecutionReceiptIssueRequest = Body(...)):
    require_admin_or_503(request)  # RBAC: Audit v3 Befund 2.2
    data = payload.model_dump()
    from backend.execution_receipt_ledger import execution_receipt_ledger
    return execution_receipt_ledger.issue_receipt(
        task_id=data.get("task_id", "task-01"),
        agent_role=data.get("agent_role", "backend_architect"),
        model_used=data.get("model_used", "deepseek/deepseek-chat"),
        prompt_tokens=int(data.get("prompt_tokens", 500)),
        completion_tokens=int(data.get("completion_tokens", 250)),
        cost_usd=float(data.get("cost_usd", 0.0012)),
        tools_invoked=data.get("tools_invoked", [])
    )


@router.get("/api/security/receipts/verify")
def api_verify_execution_receipts(request: Request):
    require_admin_or_503(request)  # Audit-Endpunkt: Admin only
    from backend.execution_receipt_ledger import execution_receipt_ledger
    return execution_receipt_ledger.verify_chain_integrity()
