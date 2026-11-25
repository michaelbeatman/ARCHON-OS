"""Router fuer Internet-Watchdog, Alarmierung und Task-Dispatch."""
from __future__ import annotations
import sqlite3

class _ArchonClosingConn(sqlite3.Connection):
    def __enter__(self):
        super().__enter__()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()
from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from archon.core.paths import KANBAN_DB_PATH

logger = logging.getLogger("archon.routers.watchdog")

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], prefix="/api/v1/watchdog", tags=["watchdog"])


class WatchdogConfigSave(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: Optional[bool] = None
    interval_minutes: Optional[int] = Field(default=None, ge=1, le=10080)
    basket_threshold: Optional[int] = Field(default=None, ge=1, le=100000)
    priority_keywords: Optional[List[str]] = None
    basket: Optional[List[Any]] = None
    channels: Optional[Dict[str, Any]] = None
    targets: Optional[List[Any]] = None


class WatchdogDispatchRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    action_type: str = Field(default="custom", max_length=80)
    findings: List[Dict[str, Any]] = Field(default_factory=list)
    custom_prompt: str = Field(default="", max_length=20000)
    target_profile: Optional[str] = Field(default=None, max_length=120)
    title: Optional[str] = Field(default=None, max_length=300)


class AcknowledgeAlarmRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    alarm_id: Optional[str] = Field(default=None, max_length=200)


def _require_admin(request: Request):
    # Zentraler Rollenzaun: eine Pruefung, ein Injectionspunkt, fail-closed.
    from archon.routers._rbac import require_admin_or_503

    require_admin_or_503(request)


@router.get("/config")
def api_get_watchdog_config():
    from backend.internet_watchdog import get_watchdog_config

    return get_watchdog_config()


@router.post("/config")
def api_save_watchdog_config(request: Request, payload: WatchdogConfigSave):
    _require_admin(request)
    from backend.internet_watchdog import get_watchdog_config, save_watchdog_config

    data = payload.model_dump(exclude_unset=True)
    cfg = get_watchdog_config()
    if "enabled" in data:
        cfg["enabled"] = bool(data["enabled"])
    if "interval_minutes" in data:
        try:
            cfg["interval_minutes"] = max(5, int(data["interval_minutes"]))
        except (ValueError, TypeError) as exc:
            logger.debug(f"Ungueltiger interval_minutes-Wert {data.get('interval_minutes')!r}, Uebernahme uebersprungen: {exc}")
    if "basket_threshold" in data:
        try:
            cfg["basket_threshold"] = max(1, int(data["basket_threshold"]))
        except (ValueError, TypeError) as exc:
            logger.debug(f"Ungueltiger basket_threshold-Wert {data.get('basket_threshold')!r}, Uebernahme uebersprungen: {exc}")
    if "priority_keywords" in data and isinstance(
        data["priority_keywords"], list
    ):
        cfg["priority_keywords"] = [
            str(k).strip()
            for k in data["priority_keywords"]
            if str(k).strip()
        ]
    if "basket" in data and isinstance(data["basket"], list):
        cfg["basket"] = data["basket"]
    if "channels" in data and isinstance(data["channels"], dict):
        cfg.setdefault("channels", {}).update(data["channels"])
    if "targets" in data and isinstance(data["targets"], list):
        cfg["targets"] = data["targets"]
    save_watchdog_config(cfg)
    return {"ok": True, "config": cfg}


def _db_insert_watchdog_task(
    task_id: str, title: str, body: str, assignee: str, now_iso: str
) -> bool:
    import sqlite3

    for kanban_db in [
        "/mnt/raid/AgenticOS-2026/data/kanban.db",
        os.path.expanduser("~/.hermes/kanban.db"),
        KANBAN_DB_PATH,
    ]:
        if not os.path.exists(kanban_db):
            continue
        try:
            with sqlite3.connect(kanban_db, timeout=5.0, factory=_ArchonClosingConn) as kconn:
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
    request: Request, payload: WatchdogDispatchRequest
):
    """Erzeugt eine gezielte Kanban-Aufgabe aus einem oder mehreren Watchdog-Funden."""
    _require_admin(request)

    action_type = payload.action_type
    findings = payload.findings
    custom_prompt = payload.custom_prompt.strip()
    target_profile = payload.target_profile

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
        title = payload.title or (
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
        except Exception as exc:
            logger.debug(f"Memory-Bridge-Sync fuer Task {task_id} fehlgeschlagen: {exc}")

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

    return await asyncio.to_thread(run_watchdog_scan, True)


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
    return JSONResponse(status_code=503, content={"status": "error", "message": "Watchdog not running"})


@router.post("/acknowledge")
def acknowledge_watchdog_alarm_endpoint(request: Request, payload: Optional[AcknowledgeAlarmRequest] = None):
    _require_admin(request)
    import main as app_main

    runner = getattr(app_main, "watchdog_runner", None)
    if runner:
        alarms = runner.load_alarms()
        alarm_id = payload.alarm_id if payload else None
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
    return JSONResponse(status_code=503, content={"status": "error", "message": "Watchdog not running"})
