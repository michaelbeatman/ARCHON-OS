# -*- coding: utf-8 -*-
"""
archon/routers/content_machine.py
=================================
Phase 2 API-Router fuer:
1. Multi-Channel Content-Maschine v1 (/api/v2/content-machine/*)
   - LinkedIn, YouTube Longform, YouTube Shorts, TikTok, X/Threads, Newsletter
   - Multi-Agenten-Repurposing-DAG mit HITL-Redaktionsfreigabe
   - Publishing-Queue & Performance-Feedback-Loop
2. Datenbank-Konsolidierung 28 -> 3 (/api/v2/system/db-consolidation/*)
   - Dry-Run-Plan & Admin-gesteuerte Online-Migration mit Backup
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from archon.routers._rbac import forbid_viewer_writes, require_admin_or_503

logger = logging.getLogger("archon.routers.content_machine")
router = APIRouter(dependencies=[Depends(forbid_viewer_writes)], tags=["content_machine"])


# =========================================================================
# CONTENT-MASCHINE v1 (LinkedIn, YouTube, TikTok, X/Threads, Newsletter)
# =========================================================================

@router.get("/api/v2/content-machine/channels")
def api_cm_channels():
    from backend.content_machine import list_channel_specs
    return {"status": "ok", "channels": list_channel_specs()}


@router.get("/api/v2/content-machine/overview")
def api_cm_overview():
    from backend.content_machine import get_content_overview
    return {"status": "ok", **get_content_overview()}


@router.get("/api/v2/content-machine/campaigns")
def api_cm_campaigns_list(limit: int = 50):
    from backend.content_machine import list_campaigns
    return {"status": "ok", "campaigns": list_campaigns(limit=limit)}


@router.post("/api/v2/content-machine/campaigns")
def api_cm_campaign_create(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.content_machine import create_campaign
    try:
        camp = create_campaign(payload)
        return {"status": "ok", "campaign": camp}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/v2/content-machine/campaigns/{campaign_id}")
def api_cm_campaign_get(campaign_id: str):
    from backend.content_machine import get_campaign
    camp = get_campaign(campaign_id)
    if not camp:
        raise HTTPException(status_code=404, detail="Kampagne nicht gefunden")
    return {"status": "ok", "campaign": camp}


@router.delete("/api/v2/content-machine/campaigns/{campaign_id}")
def api_cm_campaign_delete(request: Request, campaign_id: str):
    require_admin_or_503(request)
    from backend.content_machine import delete_campaign
    if not delete_campaign(campaign_id):
        raise HTTPException(status_code=404, detail="Kampagne nicht gefunden")
    return {"status": "ok", "deleted": campaign_id}


@router.post("/api/v2/content-machine/campaigns/{campaign_id}/generate")
async def api_cm_campaign_generate(
    request: Request,
    campaign_id: str,
    payload: Dict[str, Any] = Body(default={}),
):
    """Startet den Multi-Agenten-Repurposing-DAG (Research -> Skript -> Kanal-Fan-Out -> HITL-Gate)."""
    require_admin_or_503(request)
    from backend.content_machine import run_content_campaign_pipeline

    require_hitl = bool(payload.get("require_hitl_gate", True))
    dry_run = bool(payload.get("dry_run", False))
    gate_approvals = payload.get("gate_approvals") if isinstance(payload.get("gate_approvals"), dict) else None
    background = bool(payload.get("background", False))

    if background and not dry_run:
        asyncio.create_task(
            run_content_campaign_pipeline(
                campaign_id=campaign_id,
                require_hitl_gate=require_hitl,
                gate_approvals=gate_approvals,
                dry_run=False,
            ),
            name=f"content_dag_{campaign_id}",
        )
        return {"status": "accepted", "campaign_id": campaign_id, "execution": "background_dag"}

    try:
        res = await run_content_campaign_pipeline(
            campaign_id=campaign_id,
            require_hitl_gate=require_hitl,
            gate_approvals=gate_approvals,
            dry_run=dry_run,
        )
        return {"status": "ok", **res}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/v2/content-machine/assets")
def api_cm_assets_list(
    campaign_id: Optional[str] = None,
    channel: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
):
    from backend.content_machine import list_assets
    return {
        "status": "ok",
        "assets": list_assets(campaign_id=campaign_id, channel=channel, status=status, limit=limit),
    }


@router.post("/api/v2/content-machine/assets")
def api_cm_asset_create(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.content_machine import create_asset
    try:
        return {"status": "ok", "asset": create_asset(payload)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/api/v2/content-machine/assets/{asset_id}")
def api_cm_asset_update(request: Request, asset_id: str, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.content_machine import update_asset
    if "status" in payload:
        # Sonst könnte die HITL-State-Machine über den generischen Patch
        # umgangen werden (draft → published ohne Freigabe).
        raise HTTPException(status_code=409, detail="Status nur über /approve oder /publish ändern.")
    try:
        return {"status": "ok", "asset": update_asset(asset_id, payload)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/v2/content-machine/assets/{asset_id}/approve")
def api_cm_asset_approve(request: Request, asset_id: str, payload: Dict[str, Any] = Body(default={})):
    require_admin_or_503(request)
    from backend.content_machine import approve_asset
    try:
        asset = approve_asset(asset_id, scheduled_at=str(payload.get("scheduled_at") or "").strip())
        return {"status": "ok", "asset": asset}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/api/v2/content-machine/assets/{asset_id}/publish")
def api_cm_asset_publish(request: Request, asset_id: str, payload: Dict[str, Any] = Body(default={})):
    require_admin_or_503(request)
    from backend.content_machine import mark_asset_published
    try:
        asset = mark_asset_published(asset_id, external_url=str(payload.get("external_url") or "").strip())
        return {"status": "ok", "asset": asset}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/api/v2/content-machine/assets/{asset_id}/metrics")
def api_cm_asset_metrics(request: Request, asset_id: str, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.content_machine import record_asset_metrics
    try:
        rec = record_asset_metrics(asset_id, payload)
        return {"status": "ok", "metrics": rec}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/api/v2/content-machine/analytics")
def api_cm_analytics():
    from backend.content_machine import get_content_analytics
    return {"status": "ok", **get_content_analytics()}


@router.post("/api/v2/content-machine/ingest")
def api_cm_ingest_source(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.content_machine import ingest_source_to_campaign
    from utils.egress_guard import EgressBlocked
    from utils.path_jail import PathJailError
    try:
        res = ingest_source_to_campaign(payload)
        return {"status": "ok", **res}
    except (EgressBlocked, PathJailError) as sec_err:
        raise HTTPException(status_code=403, detail=str(sec_err))
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/v2/content-machine/campaigns/{campaign_id}/clip-matrix")
async def api_cm_clip_matrix(request: Request, campaign_id: str, payload: Dict[str, Any] = Body(default={})):
    require_admin_or_503(request)
    from backend.content_machine import generate_video_clip_matrix
    try:
        res = await generate_video_clip_matrix(
            campaign_id=campaign_id,
            source_asset_id=payload.get("source_asset_id"),
            script_text=payload.get("script_text"),
            clip_count=int(payload.get("clip_count") or 3),
            target_channels=payload.get("target_channels"),
            dry_run=bool(payload.get("dry_run", False)),
        )
        return {"status": "ok", **res}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/v2/content-machine/assets/{asset_id}/dispatch-webhook")
def api_cm_dispatch_webhook(request: Request, asset_id: str, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.content_machine import dispatch_asset_to_webhook
    from utils.egress_guard import EgressBlocked
    try:
        res = dispatch_asset_to_webhook(
            asset_id=asset_id,
            webhook_url=str(payload.get("webhook_url") or ""),
            dry_run=bool(payload.get("dry_run", False)),
        )
        return res
    except EgressBlocked as sec_err:
        raise HTTPException(status_code=403, detail=str(sec_err))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/v2/content-machine/publish-due")
def api_cm_publish_due(request: Request, payload: Dict[str, Any] = Body(default={})):
    require_admin_or_503(request)
    from backend.content_machine import publish_scheduled_due_assets
    res = publish_scheduled_due_assets(
        webhook_url=payload.get("webhook_url"),
        dry_run=bool(payload.get("dry_run", False)),
    )
    return res


@router.get("/api/v2/content-machine/crm-inbox-preview")
def api_cm_crm_inbox_preview():
    from backend.competitor_idea_bridge import read_crm_telegram_inbox_items
    return {"status": "ok", **read_crm_telegram_inbox_items()}


@router.post("/api/v2/content-machine/import-crm-ideas")
def api_cm_import_crm_ideas(request: Request, payload: Dict[str, Any] = Body(default={})):
    require_admin_or_503(request)
    from backend.competitor_idea_bridge import import_crm_telegram_ideas_to_archon
    sync_kb = bool(payload.get("sync_to_kanban", True))
    inc_media = bool(payload.get("include_media_batch_idea", True))
    return import_crm_telegram_ideas_to_archon(
        sync_to_kanban=sync_kb,
        include_media_batch_idea=inc_media,
    )


@router.get("/api/v2/content-machine/voice-profile")
def api_cm_get_voice_profile():
    import os
    from archon.core.runtime import APP_ROOT
    voice_path = os.path.join(APP_ROOT, "config", "voice.md")
    content = ""
    if os.path.exists(voice_path):
        with open(voice_path, "r", encoding="utf-8") as f:
            content = f.read()
    return {"status": "ok", "path": "config/voice.md", "content": content}


@router.post("/api/v2/content-machine/voice-profile")
def api_cm_save_voice_profile(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    import os
    from archon.core.runtime import APP_ROOT
    content = str(payload.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="voice.md Inhalt darf nicht leer sein.")
    targets = [
        os.path.join(APP_ROOT, "config", "voice.md"),
        os.path.join(APP_ROOT, "obsidian_vault", "00_SYSTEM", "voice.md"),
    ]
    for t in targets:
        try:
            os.makedirs(os.path.dirname(t), exist_ok=True)
            with open(t, "w", encoding="utf-8") as f:
                f.write(content + "\n")
        except OSError as exc:
            logger.warning(f"[ContentMachine] voice.md Ziel {t} nicht beschreibbar: {exc}")
    return {"status": "ok", "path": "config/voice.md", "bytes": len(content)}


@router.post("/api/v2/content-machine/humanize-score")
def api_cm_humanize_and_score(payload: Dict[str, Any] = Body(...)):
    from backend.content_machine import evaluate_asset_quality
    text = str(payload.get("text") or payload.get("body") or "").strip()
    hook = str(payload.get("hook") or (text.splitlines()[0] if text else "")).strip()
    cta = str(payload.get("cta") or (text.splitlines()[-1] if text else "")).strip()
    channel = str(payload.get("channel") or "linkedin").strip().lower()
    if not text:
        raise HTTPException(status_code=400, detail="Text darf nicht leer sein.")
    report = evaluate_asset_quality({"channel": channel, "hook": hook, "body": text, "cta": cta})
    return {"status": "ok", **report}



# =========================================================================
# DATENBANK-KONSOLIDIERUNG (28 -> 3: ops.db, business.db, memory.db)
# =========================================================================

@router.get("/api/v2/system/db-consolidation/plan")
def api_db_consolidation_plan(request: Request):
    require_admin_or_503(request)
    from backend.db_consolidation import plan_consolidation
    return {"status": "ok", **plan_consolidation()}


@router.post("/api/v2/system/db-consolidation/run")
def api_db_consolidation_run(request: Request, payload: Dict[str, Any] = Body(default={})):
    require_admin_or_503(request)
    from backend.db_consolidation import run_consolidation
    dry_run = bool(payload.get("dry_run", True))
    activate = bool(payload.get("activate", False))
    create_backup = bool(payload.get("create_backup", True))
    res = run_consolidation(dry_run=dry_run, create_backup=create_backup, activate=activate)
    return {"status": "ok", **res}
