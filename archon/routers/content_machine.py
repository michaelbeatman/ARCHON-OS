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
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from archon.routers._rbac import forbid_viewer_writes, require_admin_or_503, require_session_actor

logger = logging.getLogger("archon.routers.content_machine")
router = APIRouter(dependencies=[Depends(forbid_viewer_writes)], tags=["content_machine"])


def _mark_campaign_failed_sync(campaign_id: str) -> None:
    """D08-M5: Kampagnenstatus 'failed' ausserhalb des Event-Loops persistieren.

    Der Background-DAG ist eine asyncio-Task; ein SQLite-Lock im Fehlerpfad
    wuerde genau den Loop blockieren, der den Fehler melden soll.
    """
    from backend.content_machine import _conn

    with _conn() as conn:
        conn.execute(
            "UPDATE content_campaigns SET status = 'failed', updated_at = ? WHERE id = ?",
            (__import__("datetime").datetime.now().isoformat(), campaign_id),
        )
        conn.commit()


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


# --- Etappe 4: Pydantic-v2-Requestmodelle fuer die ersten 9 Raw-Body-Endpunkte ---
# Typing/Pydantic-Imports stehen jetzt am Dateianfang (Ruff E402/F811).

def _normalize_channels(value: Any) -> Any:
    """Einzelkanal als String ('linkedin') -> ['linkedin'] (alter Client-Shape)."""
    if isinstance(value, str):
        return [value] if value.strip() else []
    return value


class CampaignCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = Field(min_length=1, max_length=200)
    topic: str = Field(default="", max_length=300)
    channels: List[str] = Field(default_factory=list)
    status: str = Field(default="draft", max_length=40)
    target_audience: str = Field(default="", max_length=500)
    brand_voice: str = Field(default="", max_length=1000)
    pillar: str = Field(default="", max_length=200)
    source_url: str = Field(default="", max_length=2000)
    source_notes: str = Field(default="", max_length=20_000)

    @field_validator("channels", mode="before")
    @classmethod
    def _channels_from_str(cls, value: Any) -> Any:
        return _normalize_channels(value)


class CampaignGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    require_hitl_gate: bool = True
    dry_run: bool = False
    background: bool = False
    # gate_approvals bewusst entfernt: Freigaben muessen aus dem
    # verifizierten Decision-Store stammen, nicht aus dem Run-Request.


class AssetCreateRequest(BaseModel):
    """Pass-through an backend.create_asset — alle dort gelesenen Felder abbilden."""
    model_config = ConfigDict(extra="ignore")
    campaign_id: str = Field(default="", max_length=120)
    channel: str = Field(default="linkedin", max_length=60)
    title: str = Field(default="", max_length=300)
    status: str = Field(default="draft", max_length=40)
    hashtags: List[str] = Field(default_factory=list)
    hook: str = Field(default="", max_length=2000)
    body: str = Field(default="", max_length=2_000_000)
    cta: str = Field(default="", max_length=2000)
    sources: List[Any] = Field(default_factory=list)
    parse_failed: bool = False
    duration_sec: int = Field(default=0, ge=0, le=86_400)
    format_type: str = Field(default="", max_length=60)
    visual_brief: str = Field(default="", max_length=5000)
    scheduled_at: str = Field(default="", max_length=40)
    external_url: str = Field(default="", max_length=2000)
    decision_id: str = Field(default="", max_length=120)
    agent_id: str = Field(default="", max_length=120)
    dossier_path: str = Field(default="", max_length=1000)
    author: str = Field(default="", max_length=120)
    reviewer: str = Field(default="", max_length=120)
    publisher: str = Field(default="", max_length=120)
    plagiarism_corpus: Optional[Any] = None
    corpus: Optional[Any] = None


class AssetUpdateRequest(BaseModel):
    """Nur die von backend.update_asset erlaubten Patch-Felder; status-Sperre im Endpoint."""
    model_config = ConfigDict(extra="ignore")
    title: Optional[str] = Field(default=None, max_length=300)
    hook: Optional[str] = Field(default=None, max_length=2000)
    body: Optional[str] = Field(default=None, max_length=2_000_000)
    visual_brief: Optional[str] = Field(default=None, max_length=5000)
    cta: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[str] = Field(default=None, max_length=40)
    scheduled_at: Optional[str] = Field(default=None, max_length=40)
    published_at: Optional[str] = Field(default=None, max_length=40)
    external_url: Optional[str] = Field(default=None, max_length=2000)
    duration_sec: Optional[int] = Field(default=None, ge=0, le=86_400)
    format_type: Optional[str] = Field(default=None, max_length=60)
    hashtags: Optional[List[str]] = None


class AssetApproveRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    scheduled_at: str = Field(default="", max_length=40)
    decision_id: str = Field(default="", max_length=120)
    actor: str = Field(default="", max_length=120)
    role: str = Field(default="reviewer", max_length=60)


class AssetPublishRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    external_url: str = Field(default="", max_length=2000)
    actor: str = Field(default="", max_length=120)


class AssetMetricsRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    views: int = Field(default=0, ge=0)
    likes: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    shares: int = Field(default=0, ge=0)
    saves: int = Field(default=0, ge=0)
    watch_time_avg_sec: float = Field(default=0.0, ge=0)
    ctr_pct: float = Field(default=0.0, ge=0, le=100)
    conversions: int = Field(default=0, ge=0)


class SourceIngestRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    source_type: str = Field(default="transcript", max_length=40)
    title: str = Field(default="", max_length=200)
    source_url: str = Field(default="", max_length=2000)
    obsidian_path: str = Field(default="", max_length=1000)
    transcript: str = Field(default="", max_length=5_000_000)
    source_notes: Any = None
    license: str = Field(default="", max_length=120)
    rights: str = Field(default="", max_length=120)
    rights_status: str = Field(default="", max_length=60)
    topic: str = Field(default="", max_length=300)
    target_audience: str = Field(default="", max_length=500)
    brand_voice: str = Field(default="", max_length=1000)
    pillar: str = Field(default="", max_length=200)
    channels: List[str] = Field(default_factory=list)

    @field_validator("channels", mode="before")
    @classmethod
    def _channels_from_str(cls, value: Any) -> Any:
        return _normalize_channels(value)


class ClipMatrixRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    source_asset_id: Optional[str] = Field(default=None, max_length=120)
    script_text: Optional[str] = Field(default=None, max_length=2_000_000)
    clip_count: int = Field(default=3, ge=1, le=6)
    target_channels: Optional[List[str]] = None
    dry_run: bool = False


class DispatchWebhookRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    webhook_url: str = Field(default="", max_length=2000)
    dry_run: bool = False


class PublishDueRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    # Hier darf webhook_url bewusst None bleiben (Backend-Default greift).
    webhook_url: Optional[str] = Field(default=None, max_length=2000)
    dry_run: bool = False


@router.post("/api/v2/content-machine/campaigns")
def api_cm_campaign_create(request: Request, req: CampaignCreateRequest):
    require_admin_or_503(request)
    from backend.content_machine import create_campaign
    try:
        camp = create_campaign(req.model_dump(exclude_none=True))
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
    req: Optional[CampaignGenerateRequest] = Body(default=None),
):
    """Startet den Multi-Agenten-Repurposing-DAG (Research -> Skript -> Kanal-Fan-Out -> HITL-Gate)."""
    require_admin_or_503(request)
    from backend.content_machine import run_content_campaign_pipeline

    req = req or CampaignGenerateRequest()
    require_hitl = req.require_hitl_gate
    dry_run = req.dry_run
    # Keine client-gesteuerten Gate-Freigaben (Audit 23.11.2026).
    gate_approvals: Dict[str, Any] = {}
    background = req.background

    if background and not dry_run:
        from archon.core.task_registry import spawn as _spawn_tracked

        async def _run_tracked() -> None:
            try:
                await run_content_campaign_pipeline(
                    campaign_id=campaign_id,
                    require_hitl_gate=require_hitl,
                    gate_approvals=gate_approvals,
                    dry_run=False,
                )
            except Exception as exc:
                logger.error(
                    "[ContentMachine] Hintergrund-DAG '%s' fehlgeschlagen: %s",
                    campaign_id, exc, exc_info=exc,
                )
                # D08-M5: kein nacktes `except: pass` mehr — ein Scheitern des
                # Status-Updates wird selbst sichtbar protokolliert.
                try:
                    await asyncio.to_thread(_mark_campaign_failed_sync, campaign_id)
                except Exception as mark_exc:
                    logger.error(
                        "[ContentMachine] Status 'failed' fuer Kampagne '%s' nicht persistiert: %s",
                        campaign_id, mark_exc, exc_info=mark_exc,
                    )

        _spawn_tracked(_run_tracked(), name=f"content_dag_{campaign_id}")
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
def api_cm_asset_create(request: Request, req: AssetCreateRequest):
    require_admin_or_503(request)
    from backend.content_machine import create_asset
    try:
        return {"status": "ok", "asset": create_asset(req.model_dump(exclude_none=True))}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/api/v2/content-machine/assets/{asset_id}")
def api_cm_asset_update(request: Request, asset_id: str, req: AssetUpdateRequest):
    require_admin_or_503(request)
    from backend.content_machine import update_asset
    if "status" in req.model_fields_set:
        # Sonst könnte die HITL-State-Machine über den generischen Patch
        # umgangen werden (draft → published ohne Freigabe).
        raise HTTPException(status_code=409, detail="Status nur über /approve oder /publish ändern.")
    try:
        return {"status": "ok", "asset": update_asset(asset_id, req.model_dump(exclude_unset=True))}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/v2/content-machine/assets/{asset_id}/approve")
def api_cm_asset_approve(
    request: Request,
    asset_id: str,
    req: Optional[AssetApproveRequest] = Body(default=None),
):
    require_admin_or_503(request)
    from backend.content_machine import approve_asset

    req = req or AssetApproveRequest()
    # KRITISCH (Audit 23.11.2026): actor/role NIE aus dem Body — sonst lässt
    # sich ein Vier-Augen-Prinzip mit erfundenen Reviewern fälschen.
    actor = require_session_actor(request)
    user = getattr(request.state, "user", None) or {}
    role = str(user.get("role") or "admin").strip().lower() or "admin"
    try:
        asset = approve_asset(
            asset_id,
            scheduled_at=req.scheduled_at.strip(),
            decision_id=req.decision_id.strip(),
            actor=actor,
            role=role,
        )
        return {"status": "ok", "asset": asset}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/api/v2/content-machine/assets/{asset_id}/publish")
def api_cm_asset_publish(
    request: Request,
    asset_id: str,
    req: Optional[AssetPublishRequest] = Body(default=None),
):
    require_admin_or_503(request)
    from backend.content_machine import mark_asset_published

    req = req or AssetPublishRequest()
    try:
        asset = mark_asset_published(
            asset_id,
            external_url=req.external_url.strip(),
            actor=req.actor.strip(),
        )
        return {"status": "ok", "asset": asset}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/api/v2/content-machine/assets/{asset_id}/approvals")
def api_cm_asset_approvals(asset_id: str):
    """Batch D: Freigabe-Historie (reviewer/publisher, decision_id, actor, role)."""
    from backend.content_machine import approval_history
    return {"status": "ok", "approvals": approval_history(asset_id)}


@router.post("/api/v2/content-machine/assets/{asset_id}/metrics")
def api_cm_asset_metrics(request: Request, asset_id: str, req: AssetMetricsRequest):
    require_admin_or_503(request)
    from backend.content_machine import record_asset_metrics
    try:
        rec = record_asset_metrics(asset_id, req.model_dump(exclude_none=True))
        return {"status": "ok", "metrics": rec}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/api/v2/content-machine/analytics")
def api_cm_analytics():
    from backend.content_machine import get_content_analytics
    return {"status": "ok", **get_content_analytics()}


@router.post("/api/v2/content-machine/ingest")
def api_cm_ingest_source(request: Request, req: SourceIngestRequest):
    require_admin_or_503(request)
    from backend.content_machine import ingest_source_to_campaign
    from utils.egress_guard import EgressBlocked
    from utils.path_jail import PathJailError
    try:
        res = ingest_source_to_campaign(req.model_dump(exclude_none=True))
        return {"status": "ok", **res}
    except (EgressBlocked, PathJailError) as sec_err:
        raise HTTPException(status_code=403, detail=str(sec_err))
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/v2/content-machine/campaigns/{campaign_id}/clip-matrix")
async def api_cm_clip_matrix(
    request: Request,
    campaign_id: str,
    req: Optional[ClipMatrixRequest] = Body(default=None),
):
    require_admin_or_503(request)
    from backend.content_machine import generate_video_clip_matrix

    req = req or ClipMatrixRequest()
    try:
        res = await generate_video_clip_matrix(
            campaign_id=campaign_id,
            source_asset_id=req.source_asset_id,
            script_text=req.script_text,
            clip_count=req.clip_count,
            target_channels=req.target_channels,
            dry_run=req.dry_run,
        )
        return {"status": "ok", **res}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/v2/content-machine/assets/{asset_id}/dispatch-webhook")
def api_cm_dispatch_webhook(request: Request, asset_id: str, req: DispatchWebhookRequest):
    require_admin_or_503(request)
    from backend.content_machine import dispatch_asset_to_webhook
    from utils.egress_guard import EgressBlocked
    try:
        res = dispatch_asset_to_webhook(
            asset_id=asset_id,
            webhook_url=req.webhook_url,
            dry_run=req.dry_run,
        )
        return res
    except EgressBlocked as sec_err:
        raise HTTPException(status_code=403, detail=str(sec_err))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/v2/content-machine/publish-due")
def api_cm_publish_due(request: Request, req: Optional[PublishDueRequest] = Body(default=None)):
    require_admin_or_503(request)
    from backend.content_machine import publish_scheduled_due_assets

    req = req or PublishDueRequest()
    res = publish_scheduled_due_assets(
        webhook_url=req.webhook_url,
        dry_run=req.dry_run,
    )
    return res


# ---------------------------------------------------------------------------
# ETAPPE 5: typisierte Request-Modelle (ab crm-inbox-preview bis Dateiende)
# ---------------------------------------------------------------------------

class ImportCrmIdeasRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sync_to_kanban: bool = True
    include_media_batch_idea: bool = True


class VoiceProfileSaveRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    content: Optional[str] = None


class HumanizeScoreRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: Optional[str] = None
    body: Optional[str] = None
    hook: Optional[str] = None
    cta: Optional[str] = None
    channel: Optional[str] = None


class CreateVariantRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    variant_label: Optional[str] = None
    hook: Optional[str] = None
    title: Optional[str] = None
    body: Optional[str] = None


class DecideExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    metric: Optional[str] = None


class ValidateChannelRequest(BaseModel):
    """Pass-through an validate_channel_constraints/evaluate_fact_check/evaluate_asset_quality.

    Alle von diesen drei Backend-Funktionen gelesenen Keys sind explizit
    typisiert; weitere Keys werden gemäss Konvention ignoriert.
    """
    model_config = ConfigDict(extra="ignore")
    channel: Optional[str] = None
    hook: Optional[str] = None
    body: Optional[str] = None
    cta: Optional[str] = None
    parse_failed: bool = False
    duration_sec: Optional[float] = None
    sources: Optional[Union[List[Any], str]] = None


class GeoCitationCheckRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    hours: Optional[int] = None


class DbConsolidationRunRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    dry_run: bool = True
    activate: bool = False
    create_backup: bool = True


@router.get("/api/v2/content-machine/crm-inbox-preview")
def api_cm_crm_inbox_preview():
    from backend.competitor_idea_bridge import read_crm_telegram_inbox_items
    return {"status": "ok", **read_crm_telegram_inbox_items()}


@router.post("/api/v2/content-machine/import-crm-ideas")
def api_cm_import_crm_ideas(request: Request, payload: ImportCrmIdeasRequest = Body(default_factory=ImportCrmIdeasRequest)):
    require_admin_or_503(request)
    from backend.competitor_idea_bridge import import_crm_telegram_ideas_to_archon
    return import_crm_telegram_ideas_to_archon(
        sync_to_kanban=payload.sync_to_kanban,
        include_media_batch_idea=payload.include_media_batch_idea,
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
def api_cm_save_voice_profile(request: Request, payload: VoiceProfileSaveRequest):
    require_admin_or_503(request)
    import os

    from archon.core.runtime import APP_ROOT
    content = str(payload.content or "").strip()
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
def api_cm_humanize_and_score(payload: HumanizeScoreRequest):
    from backend.content_machine import evaluate_asset_quality
    text = str(payload.text or payload.body or "").strip()
    hook = str(payload.hook or (text.splitlines()[0] if text else "")).strip()
    cta = str(payload.cta or (text.splitlines()[-1] if text else "")).strip()
    channel = str(payload.channel or "linkedin").strip().lower()
    if not text:
        raise HTTPException(status_code=400, detail="Text darf nicht leer sein.")
    report = evaluate_asset_quality({"channel": channel, "hook": hook, "body": text, "cta": cta})
    return {"status": "ok", **report}


# ---------------------------------------------------------------------------
# CONTENT-MACHINE 2.0: A/B-Varianten, Kanalvalidierung, Fact-Check, GEO
# ---------------------------------------------------------------------------

@router.post("/api/v2/content-machine/assets/{asset_id}/variants")
def api_cm_create_variant(request: Request, asset_id: str, payload: CreateVariantRequest):
    require_admin_or_503(request)
    from backend.content_machine import create_variant
    try:
        res = create_variant(
            asset_id,
            str(payload.variant_label or "B"),
            str(payload.hook or ""),
            title=str(payload.title or ""),
            body=str(payload.body or ""),
        )
        return {"status": "ok", **res}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/api/v2/content-machine/assets/{asset_id}/variants")
def api_cm_list_variants(asset_id: str):
    from backend.content_machine import list_variants
    return {"status": "ok", "variants": list_variants(asset_id)}


@router.post("/api/v2/content-machine/assets/{asset_id}/experiments/decide")
def api_cm_decide_experiment(request: Request, asset_id: str, payload: DecideExperimentRequest = Body(default_factory=DecideExperimentRequest)):
    require_admin_or_503(request)
    from backend.content_machine import decide_experiment
    return {"status": "ok", **decide_experiment(asset_id, metric=str(payload.metric or "ctr_pct"))}


@router.post("/api/v2/content-machine/validate-channel")
def api_cm_validate_channel(payload: ValidateChannelRequest):
    from backend.content_machine import (
        evaluate_asset_quality,
        evaluate_fact_check,
        validate_channel_constraints,
    )
    asset = payload.model_dump()
    return {
        "status": "ok",
        "channel_validation": validate_channel_constraints(asset),
        "fact_check": evaluate_fact_check(asset),
        "quality": evaluate_asset_quality(asset),
    }


@router.get("/api/v2/content-machine/assets/{asset_id}/geo-jsonld")
def api_cm_geo_jsonld(asset_id: str):
    from backend.content_machine import _conn, _row_to_asset, build_geo_jsonld
    with _conn() as conn:
        row = conn.execute("SELECT * FROM content_assets WHERE id = ?", (asset_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Asset nicht gefunden")
    asset = _row_to_asset(row)
    return {"status": "ok", "jsonld": build_geo_jsonld(asset, external_url=str(asset.get("external_url") or ""))}


@router.post("/api/v2/content-machine/geo/citation-check")
def api_cm_geo_citation_check(payload: GeoCitationCheckRequest = Body(default_factory=GeoCitationCheckRequest)):
    """Batch D: deterministische Offline-Zitatpruefung 48h nach Publish."""
    from backend.content_machine import check_geo_citations
    return {"status": "ok", **check_geo_citations(hours=int(payload.hours or 48))}



# =========================================================================
# DATENBANK-KONSOLIDIERUNG (28 -> 3: ops.db, business.db, memory.db)
# =========================================================================

@router.get("/api/v2/system/db-consolidation/plan")
def api_db_consolidation_plan(request: Request):
    require_admin_or_503(request)
    from backend.db_consolidation import plan_consolidation
    return {"status": "ok", **plan_consolidation()}


@router.post("/api/v2/system/db-consolidation/run")
def api_db_consolidation_run(request: Request, payload: DbConsolidationRunRequest = Body(default_factory=DbConsolidationRunRequest)):
    require_admin_or_503(request)
    from backend.db_consolidation import run_consolidation
    res = run_consolidation(
        dry_run=payload.dry_run,
        create_backup=payload.create_backup,
        activate=payload.activate,
    )
    return {"status": "ok", **res}
