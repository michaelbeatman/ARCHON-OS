"""Router fuer Oracle News Radar und SEO Execution Agent."""
from __future__ import annotations
from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes

import datetime
import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from archon.routers._rbac import require_admin_or_503

logger = logging.getLogger("archon.routers.oracle_seo")

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["oracle_seo"])


class OracleTriageRequest(BaseModel):
    """Signal-ID alternativ als 'id' oder 'signal_id' (Kompatibilitaet)."""
    model_config = ConfigDict(extra="ignore")
    id: Optional[str] = Field(default=None, max_length=200)
    signal_id: Optional[str] = Field(default=None, max_length=200)


class SeoGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    topic: str = Field(default="", max_length=500)
    keyword: Optional[str] = Field(default=None, max_length=200)
    audience: str = Field(default="B2B / Tech", max_length=200)
    trigger_n8n: bool = False
    serp_analysis: Optional[Any] = None


# =====================================================================
# ORACLE NEWS RADAR (Hermes Intelligence Stream & Obsidian Sync)
# =====================================================================


@router.get("/api/oracle/feed")
def api_get_oracle_feed(limit: int = 50):
    try:
        import oracle_news_radar

        radar = oracle_news_radar.OracleNewsRadar()
        return {"status": "success", "feed": radar.get_feed(limit)}
    except Exception as e:
        raise HTTPException(status_code=502, detail={"code": "oracle_feed_unavailable", "params": {"error": str(e)}})


@router.post("/api/oracle/run")
def api_run_oracle_cycle():
    try:
        import oracle_news_radar

        radar = oracle_news_radar.OracleNewsRadar()
        return radar.run_radar_cycle()
    except Exception as e:
        raise HTTPException(status_code=502, detail={"code": "oracle_run_failed", "params": {"error": str(e)}})


@router.post("/api/oracle/triage")
def api_triage_oracle_signal(payload: OracleTriageRequest):
    if isinstance(payload, dict):  # direkte Aufrufe (Tests/Interop) weiterhin moeglich
        payload = OracleTriageRequest.model_validate(payload)
    try:
        import oracle_news_radar

        radar = oracle_news_radar.OracleNewsRadar()
        signal_id = payload.id or payload.signal_id
        if not signal_id:
            raise HTTPException(status_code=400, detail={"code": "oracle_signal_id_missing", "params": {}})
        return radar.triage_to_task(signal_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail={"code": "oracle_triage_failed", "params": {"error": str(e)}})


# =====================================================================
# SEO & EXECUTION AGENT (Programmatic Content & Webhook Pipeline)
# =====================================================================


@router.post("/api/seo/generate")
async def api_seo_generate(request: Request, payload: SeoGenerateRequest):
    require_admin_or_503(request)  # RBAC: Admin-Sache (HITL-Pfad)
    topic = payload.topic
    keyword = payload.keyword or topic
    audience = payload.audience
    trigger_n8n = payload.trigger_n8n
    serp_analysis = payload.serp_analysis
    if not topic:
        raise HTTPException(status_code=400, detail={"code": "oracle_topic_required", "params": {}})
    try:
        from seo_execution_agent import SEOExecutionAgent

        agent = SEOExecutionAgent()
        return await agent.execute_content_pipeline(
            topic, keyword, audience, trigger_n8n, serp_analysis=serp_analysis
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/seo/articles")
def api_seo_articles():
    import main as app_main

    workspace_dir = getattr(app_main, "WORKSPACE_DIR", "/app")
    content_dir = os.path.join(workspace_dir, "obsidian_vault", "05_Content")
    if not os.path.exists(content_dir):
        content_dir = os.path.join("obsidian_vault", "05_Content")
    articles = []
    if os.path.exists(content_dir):
        for f in os.listdir(content_dir):
            if f.endswith(".md"):
                fp = os.path.join(content_dir, f)
                articles.append(
                    {
                        "filename": f,
                        "path": fp,
                        "size_bytes": os.path.getsize(fp),
                        "modified": datetime.datetime.fromtimestamp(os.path.getmtime(fp)).isoformat(),
                    }
                )
    return {"status": "success", "articles": articles}
