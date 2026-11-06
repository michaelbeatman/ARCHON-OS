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
from typing import Any, Dict, List, Optional

import httpx
import yaml
from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

import core_dispatcher  # noqa: F401
from archon.core.runtime import (  # noqa: F401
    WORKSPACE_DIR, MEMORY_DIR, DATA_DIR, SETTINGS_FILE, OBSIDIAN_VAULT_DIR,
    add_ticker, broadcast_event, ticker_entries, _load_json, _save_json,
    atomic_write_json,
)

router = APIRouter()

@router.post("/api/security/mask-secrets")
def api_mask_secrets(payload: Dict = Body(...)):
    from backend.secret_masker import mask_sensitive_text
    masked, count = mask_sensitive_text(payload.get("text", ""))
    return {"status": "success", "masked_text": masked, "redacted_count": count}


@router.post("/api/security/pii-scrub")
def api_pii_scrub(payload: Dict = Body(...)):
    from backend.pii_scrubber import pii_scrubber
    return pii_scrubber.scrub_text(
        text=payload.get("text", ""),
        session_id=payload.get("session_id", "")
    )


@router.post("/api/security/pii-rehydrate")
def api_pii_rehydrate(payload: Dict = Body(...)):
    from backend.pii_scrubber import pii_scrubber
    return pii_scrubber.rehydrate_text(
        response_text=payload.get("response_text", ""),
        session_id=payload.get("session_id", ""),
        custom_vault=payload.get("vault_map")
    )


@router.post("/api/security/egress-check")
def api_egress_firewall_check(payload: Dict = Body(...)):
    from backend.egress_firewall import egress_firewall
    return egress_firewall.check_url(
        target_url=payload.get("url", ""),
        agent_id=payload.get("agent_id", "agent-worker")
    )


@router.get("/api/security/egress-logs")
def api_egress_firewall_logs(limit: int = 25):
    from backend.egress_firewall import egress_firewall
    return {"status": "success", "logs": egress_firewall.get_logs(limit=limit)}


@router.post("/api/security/rbac-check")
def api_rbac_jail_check(payload: Dict = Body(...)):
    from backend.agent_rbac_jail import agent_rbac_jail
    return agent_rbac_jail.check_access(
        role=payload.get("role", "researcher"),
        tool_name=payload.get("tool_name", "read_file"),
        target_path=payload.get("target_path", "")
    )


@router.post("/api/security/lint-output")
def api_lint_agent_output(payload: Dict = Body(...)):
    from backend.output_policy_linter import output_policy_linter
    return output_policy_linter.lint_and_clean(
        output_text=payload.get("output_text", "")
    )


@router.post("/api/security/receipts/issue")
def api_issue_execution_receipt(payload: Dict = Body(...)):
    from backend.execution_receipt_ledger import execution_receipt_ledger
    return execution_receipt_ledger.issue_receipt(
        task_id=payload.get("task_id", "task-01"),
        agent_role=payload.get("agent_role", "backend_architect"),
        model_used=payload.get("model_used", "deepseek/deepseek-chat"),
        prompt_tokens=int(payload.get("prompt_tokens", 500)),
        completion_tokens=int(payload.get("completion_tokens", 250)),
        cost_usd=float(payload.get("cost_usd", 0.0012)),
        tools_invoked=payload.get("tools_invoked", [])
    )


@router.get("/api/security/receipts/verify")
def api_verify_execution_receipts():
    from backend.execution_receipt_ledger import execution_receipt_ledger
    return execution_receipt_ledger.verify_chain_integrity()
