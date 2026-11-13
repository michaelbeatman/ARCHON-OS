"""Router fuer Security Scanner (Prompt Injection, Output Validation, Stats)."""
from __future__ import annotations
from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes

import logging
from typing import Dict, Optional

from fastapi import APIRouter, Body

logger = logging.getLogger("archon.routers.security_scanner")

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["security_scanner"])


@router.post("/api/v1/security/scan-email")
def api_scan_email_security(payload: Optional[Dict] = Body(None)):
    from local_security_guard import scan_prompt_injection

    payload = payload or {}
    text = payload.get("text") or payload.get("body") or ""
    subject = payload.get("subject", "")
    sender = payload.get("sender", "")
    sensitivity = payload.get("sensitivity", "moderate")
    use_llm = bool(payload.get("use_llm", False))
    model = payload.get("model", "omniroute/free-forever")
    res = scan_prompt_injection(
        text,
        subject=subject,
        sender=sender,
        sensitivity=sensitivity,
        use_llm=use_llm,
        model=model,
    )
    return {"status": "success", **res}


@router.post("/api/v1/security/validate-output")
def api_validate_output_security(payload: Optional[Dict] = Body(None)):
    from local_security_guard import validate_ai_output

    payload = payload or {}
    task = payload.get("task", "")
    result = payload.get("result", "")
    model_used = payload.get("model_used", "default")
    min_score = int(payload.get("min_score", 7))
    use_llm = bool(payload.get("use_llm", False))
    judge_model = payload.get("judge_model", "omniroute/free-forever")
    res = validate_ai_output(
        task,
        result,
        model_used=model_used,
        min_score=min_score,
        use_llm=use_llm,
        judge_model=judge_model,
    )
    return {"status": "success", **res}


@router.get("/api/v1/security/stats")
def api_get_security_stats():
    from views.view_inbox import load_email_messages, load_telegram_messages

    emails = load_email_messages()
    telegrams = load_telegram_messages()
    all_items = emails + telegrams
    blocked_cnt = sum(1 for m in all_items if m.get("security_status") == "blocked")
    suspicious_cnt = sum(1 for m in all_items if m.get("security_status") == "suspicious")
    safe_cnt = sum(1 for m in all_items if m.get("security_status") == "safe")
    return {
        "status": "success",
        "total_scanned": len(all_items),
        "blocked_count": blocked_cnt,
        "suspicious_count": suspicious_cnt,
        "safe_count": safe_cnt,
    }
