"""Router fuer Internet-Watchdog, Alarmierung und Task-Dispatch."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Request

logger = logging.getLogger("archon.routers.watchdog")

router = APIRouter(prefix="/api/v1/watchdog", tags=["watchdog"])


def _require_admin(request: Request):
    import main as app_main
    if hasattr(app_main, "require_admin"):
        app_main.require_admin(request)


@router.get("/config")
def api_get_watchdog_config():
    from backend.internet_watchdog import get_watchdog_config

    return get_watchdog_config()


@router.post("/config")
def api_save_watchdog_config(request: Request, payload: Dict = Body(...)):
    _require_admin(request)
    from backend.internet_watchdog import get_watchdog_config, save_watchdog_config

    cfg = get_watchdog_config()
    if "enabled" in payload:
        cfg["enabled"] = bool(payload["enabled"])
    if "interval_minutes" in payload:
        try:
            cfg["interval_minutes"] = max(5, int(payload["interval_minutes"]))
        except (ValueError, TypeError):
            pass
    if "basket_threshold" in payload:
        try:
            cfg["basket_threshold"] = max(1, int(payload["basket_threshold"]))
        except (ValueError, TypeError):
            pass
    if "priority_keywords" in payload and isinstance(
        payload["priority_keywords"], list
    ):
        cfg["priority_keywords"] = [
            str(k).strip()
            for k in payload["priority_keywords"]
            if str(k).strip()
        ]
    if "basket" in payload and isinstance(payload["basket"], list):
        cfg["basket"] = payload["basket"]
    if "channels" in payload and isinstance(payload["channels"], dict):
        cfg.setdefault("channels", {}).update(payload["channels"])
    if "targets" in payload and isinstance(payload["targets"], list):
        cfg["targets"] = payload["targets"]
    save_watchdog_config(cfg)
    return {"ok": True, "config": cfg}


def _db_insert_watchdog_task(
    task_id: str, title: str, body: str, assignee: str, now_iso: str
) -> bool:
    import sqlite3

    for kanban_db in [
        "/mnt/raid/AgenticOS-2026/data/kanban.db",
        "/home/micha/.hermes/kanban.db",
        "/opt/data/kanban.db",
    ]:
        if not os.path.exists(kanban_db):
            continue
        try:
            with sqlite3.connect(kanban_db, timeout=5.0) as kconn:
                kconn.execute(
                    """
                    INSERT OR IGNORE INTO tasks (id, title, body, assignee, status, priority, created_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        task_id,
                        title,
                        body,
                        assignee,
                        "ready",
                        "normal",
                        "watchdog_action",
                        now_iso,
                    ),
                )
                kconn.commit()
                return True
        except Exception as e:
            logger.warning(f"[Watchdog] Action Kanban Insert Fehler: {e}")
    return False


@router.post("/dispatch_action")
async def api_watchdog_dispatch_action(
    request: Request, payload: Dict = Body(...)
):
    """Erzeugt eine gezielte Kanban-Aufgabe aus einem oder mehreren Watchdog-Funden."""
    _require_admin(request)

    action_type = payload.get("action_type", "custom")
    findings = payload.get("findings", [])
    custom_prompt = payload.get("custom_prompt", "").strip()
    target_profile = payload.get("target_profile")

    if not findings:
        return {"ok": False, "error": "Keine Funde uebergeben"}

    now_iso = datetime.now().isoformat()

    if action_type == "linkedin_post":
        f = findings[0]
        assignee = "storyteller_ghostwriter"
        title = f"✍️ LinkedIn-Post: {f['title'][:60]}"
        prompt_instruction = custom_prompt or (
            "Analysiere diesen Fund, arbeite die Kern-Relevanz fuer den deutschen Markt heraus "
            "und formuliere einen ansprechenden LinkedIn-Beitrag (Hook, Story, 3 Takeaways, Call-to-Action). "
            "ZITATIONS-PFLICHT: Bette die Primaerquelle als sauberen Markdown-Link [Quelle: Name](URL) "
            "direkt im Text oder am Beitragsende ein."
        )
        body = (
            f"📱 **LinkedIn-Content Auftrag**\n\n"
            f"• **Thema:** {f['title']}\n"
            f"• **Quelle:** {f.get('target_name')} ({f.get('category')})\n"
            f"• **Link:** {f.get('link')}\n\n"
            f"**Anweisung:**\n{prompt_instruction}\n\n"
            f"**Roh-Inhalt:**\n{f.get('snippet', '')}"
        )
    elif action_type == "robert_dossier":
        f = findings[0]
        assignee = "executive_decision_architect"
        title = f"📊 Strategie-Dossier: {f['title'][:60]}"
        prompt_instruction = custom_prompt or (
            "Pruefe die strategische Tragweite dieser Meldung fuer unsere Bau-, Investitions- und Projektentwicklungen "
            "und erstelle eine 1-Seiten-Entscheidungsvorlage mit Handlungsoptionen. "
            "ZITATIONS-PFLICHT: Zitiere die Primaerquelle mit offiziellem Link [Quelle: Name](URL) und Einstufung (Amtlich/Leitmedium)."
        )
        body = (
            f"🏛️ **Strategische Vorlage fuer Robert (CEO)**\n\n"
            f"• **Gegenstand:** {f['title']}\n"
            f"• **Quelle:** {f.get('target_name')}\n"
            f"• **Referenz:** {f.get('link')}\n\n"
            f"**Pruefungsauftrag:**\n{prompt_instruction}\n\n"
            f"**Fundauszug:**\n{f.get('snippet', '')}"
        )
    elif action_type == "bundle_content":
        assignee = target_profile or "content_repurposing_specialist"
        title = f"🧺 Trend-Synthese aus {len(findings)} Radar-Funden"
        items_text = "\n".join(
            [
                f"- **{it['title']}** ({it.get('category')}): {it.get('link')}\n  {it.get('snippet', '')[:180]}"
                for it in findings
            ]
        )
        prompt_instruction = custom_prompt or (
            f"Erstelle aus diesen {len(findings)} gesammelten Trend-Meldungen eine zusammenfassende Branchen- und Investitions-Synthese "
            "sowie zwei darauf aufbauende Content-Ideen. "
            "ZITATIONS-PFLICHT: Zitiere alle herangezogenen Quellen als anklickbare Hyperlinks [Quelle: Name](URL) in einem abschliessenden Quellenverzeichnis."
        )
        body = (
            f"🧺 **Sammelkorb-Synthese ({len(findings)} Quellen)**\n\n"
            f"**Zusammenstellung:**\n{items_text}\n\n"
            f"**Auftrag:**\n{prompt_instruction}"
        )
    else:
        assignee = target_profile or "executive_decision_architect"
        title = payload.get("title") or (
            f"Aufgabe: {findings[0]['title'][:60]}"
            if len(findings) == 1
            else f"Sammel-Aufgabe ({len(findings)} Funde)"
        )
        body = (
            custom_prompt
            or f"Fund verarbeiten: {findings[0].get('link') if len(findings) == 1 else ''}"
        )

    task_id = f"task-{int(datetime.now().timestamp())}"

    inserted = await asyncio.to_thread(
        _db_insert_watchdog_task, task_id, title, body, assignee, now_iso
    )

    if not inserted:
        def _bridge_sync():
            from local_memory_bridge import LocalMemoryBridge

            LocalMemoryBridge().sync_task(
                task_id=task_id, title=title, role=assignee, status="ready"
            )

        try:
            await asyncio.to_thread(_bridge_sync)
        except Exception:
            pass

    return {
        "ok": True,
        "task_id": task_id,
        "title": title,
        "assignee": assignee,
        "status": "ready",
    }


@router.post("/run_now")
async def api_trigger_watchdog_run(request: Request):
    _require_admin(request)
    from backend.internet_watchdog import run_watchdog_scan

    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, run_watchdog_scan, True)
    return res


@router.get("/alarms")
def get_watchdog_alarms_endpoint():
    import main as app_main

    runner = getattr(app_main, "watchdog_runner", None)
    if runner:
        return {"alarms": runner.load_alarms()}
    return {"alarms": []}


@router.post("/test-alarm")
def trigger_test_watchdog_alarm_endpoint(request: Request):
    _require_admin(request)
    import main as app_main

    runner = getattr(app_main, "watchdog_runner", None)
    if runner:
        runner.save_alarm(
            "telegram_bot",
            "Token Usage Limit Exceeded (14.200 > 10.000 tok/min) - Der Watchdog hat den Thread per SIGTERM isoliert, um weitere API-Kosten und Systemblockaden zu unterbinden.",
            {
                "container": "hermes",
                "task": "tk_test_sandbox",
                "measured_rate": "12.500 tok/min",
                "status": "Gestoppt (0 Tok/s)",
                "log_excerpt": "> 2026-08-27 19:41:17.185563315 | Messaging platforms + cron scheduler |\n> 2026-08-27 19:41:17.185564107 | Press Ctrl+C to stop |\n> 2026-08-27 19:41:17.185565209 |\n> 2026-08-27 19:41:17.185565590",
            },
        )
        return {"status": "ok", "alarms": runner.load_alarms()}
    return {"status": "error", "message": "Watchdog not running"}


@router.post("/acknowledge")
def acknowledge_watchdog_alarm_endpoint(payload: dict = None):
    import main as app_main

    runner = getattr(app_main, "watchdog_runner", None)
    if runner:
        alarms = runner.load_alarms()
        alarm_id = payload.get("alarm_id") if payload else None
        if alarm_id:
            alarms = [a for a in alarms if a.get("id") != alarm_id]
        else:
            alarms = []
        try:
            from watchdog_daemon import ALARMS_FILE

            with open(ALARMS_FILE, "w", encoding="utf-8") as f:
                json.dump(alarms, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Error saving alarms after ack: {e}")
        return {"status": "ok", "alarms": alarms}
    return {"status": "error", "message": "Watchdog not running"}
