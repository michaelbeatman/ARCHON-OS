"""Router fuer Oracle News Radar und SEO Execution Agent."""
from __future__ import annotations

import datetime
import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException

logger = logging.getLogger("archon.routers.oracle_seo")

router = APIRouter(tags=["oracle_seo"])


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
        raise HTTPException(status_code=502, detail=f"Oracle-Feed nicht verfuegbar: {e}")


@router.post("/api/oracle/run")
def api_run_oracle_cycle():
    try:
        import oracle_news_radar

        radar = oracle_news_radar.OracleNewsRadar()
        return radar.run_radar_cycle()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Oracle-Lauf fehlgeschlagen: {e}")


@router.post("/api/oracle/triage")
def api_triage_oracle_signal(payload: Dict[str, Any] = Body(...)):
    try:
        import oracle_news_radar

        radar = oracle_news_radar.OracleNewsRadar()
        signal_id = payload.get("id") or payload.get("signal_id")
        if not signal_id:
            raise HTTPException(status_code=400, detail="Signal-ID fehlt im Payload")
        return radar.triage_to_task(signal_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Oracle-Triage fehlgeschlagen: {e}")


# =====================================================================
# SEO & EXECUTION AGENT (Programmatic Content & Webhook Pipeline)
# =====================================================================


@router.post("/api/seo/generate")
async def api_seo_generate(payload: Dict[str, Any] = Body(...)):
    topic = payload.get("topic", "")
    keyword = payload.get("keyword", topic)
    audience = payload.get("audience", "B2B / Tech")
    trigger_n8n = payload.get("trigger_n8n", True)
    if not topic:
        raise HTTPException(status_code=400, detail="Thema (topic) ist erforderlich")
    try:
        from seo_execution_agent import SEOExecutionAgent

        agent = SEOExecutionAgent()
        return await agent.execute_content_pipeline(topic, keyword, audience, trigger_n8n)
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
