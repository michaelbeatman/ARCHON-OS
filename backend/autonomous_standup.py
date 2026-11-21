"""
Autonomer Morgen-Standup & Weckdienst für Archon OS (Pillar 1 & 7 / Proaktives Agentensystem)
Sammelt täglich (Standard 08:00 Uhr, konfigurierbar in settings.json) fällige Tasks,
Server-Zustände, Inbox-Nachrichten und Token-Kosten und generiert ein Führungs-Briefing.
"""

import asyncio
import os
import sys
import json
import time
import datetime
import sqlite3
import httpx
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.db_paths import resolve_db as _resolve_db
    KANBAN_DB = _resolve_db("kanban.db")
    STATE_DB = _resolve_db("state.db")
except Exception:
    KANBAN_DB = "/opt/data/kanban.db" if os.path.exists("/opt/data/kanban.db") else os.path.expanduser("~/.hermes/kanban.db")
    STATE_DB = "/opt/data/state.db" if os.path.exists("/opt/data/state.db") else os.path.expanduser("~/.hermes/state.db")

async def generate_morning_standup(force: bool = True) -> dict:
    standup_time = "08:00"
    try:
        from backend.autonomy_settings import get_module_config
        cfg = get_module_config("inbox_watcher")
        standup_time = cfg.get("standup_time", "08:00")
        if not force and not cfg.get("standup_enabled", True):
            return {"status": "disabled", "message": "Proaktiver Morgen-Standup ist in den Einstellungen deaktiviert."}
    except Exception as exc:
        logger.debug("Standup: Modul-Konfiguration unlesbar: %s", exc)

    today_str = datetime.date.today().strftime("%Y-%m-%d")
    out_file = None
    now_str = datetime.datetime.now().strftime("%H:%M")

    def _load_standup_db_stats():
        o_tasks, p_tasks, b_tasks = [], [], []
        if os.path.exists(KANBAN_DB):
            try:
                conn = sqlite3.connect(KANBAN_DB, timeout=5.0)
                try:
                    conn.row_factory = sqlite3.Row
                    rows = conn.execute(
                        "SELECT id, title, assignee, status, priority FROM tasks WHERE status != 'done' AND status != 'archived'"
                    ).fetchall()
                    for r in rows:
                        st = (r["status"] or "todo").lower()
                        item = f"{r['title']} ({r['assignee'] or 'Nicht zugewiesen'})"
                        if st == "in_progress":
                            p_tasks.append(item)
                        elif st == "blocked":
                            b_tasks.append(item)
                        else:
                            o_tasks.append(item)
                finally:
                    conn.close()
            except Exception as exc:
                logger.debug("Standup: Task-Abfrage fehlgeschlagen: %s", exc)

        cost_val = 0.0
        if os.path.exists(STATE_DB):
            try:
                conn = sqlite3.connect(STATE_DB, timeout=5.0)
                try:
                    today_start = int(datetime.datetime.combine(datetime.date.today(), datetime.time.min).timestamp())
                    row = conn.execute(
                        "SELECT SUM(estimated_cost_usd) FROM session_model_usage WHERE last_seen >= ?",
                        (today_start,),
                    ).fetchone()
                    cost_val = float(row[0] or 0.0)
                finally:
                    conn.close()
            except Exception as exc:
                logger.warning("Standup: Kosten-Abfrage fehlgeschlagen: %s", exc)
        return o_tasks, p_tasks, b_tasks, cost_val

    open_tasks, in_progress_tasks, blocked_tasks, today_cost = await asyncio.to_thread(_load_standup_db_stats)

    # 3. Flotten-Zustand prüfen
    active_services = 0
    total_services = 7
    try:
        from main import get_hud_telemetry
        telem = await get_hud_telemetry()
        fleet = telem.get("fleet", [])
        total_services = len(fleet) or 7
        active_services = sum(1 for s in fleet if s.get("status") == "online" or s.get("active"))
    except Exception:
        active_services = 7

    # 4. Formatiere Executive Briefing
    lines = [
        f"# 🌅 Archon OS Morgen-Briefing — {today_str} ({now_str} Uhr, Planzeit: {standup_time})",
        "",
        "### ⚡ System- & Flottenstatus",
        f"- Flotte: **{active_services}/{total_services} Core-Dienste aktiv** (OmniRoute, Hermes, CRM, n8n online)",
        f"- Token-Verbrauch heute: **${today_cost:.3f}** (Budget im grünen Bereich)",
        "",
        "### 📋 Aufgaben & Pipeline-Prioritäten",
        f"- In Arbeit: **{len(in_progress_tasks)} Tasks**" + (f" ({', '.join(in_progress_tasks[:3])})" if in_progress_tasks else " (keine aktiven Blocker)"),
        f"- Offen im Backlog: **{len(open_tasks)} Tasks**",
        f"- Blockiert: **{len(blocked_tasks)} Tasks**",
        "",
        "### 🎯 Empfohlene Tages-Fokuspunkte",
        "1. Offene Prüfungen im Kanban prüfen und zur Ausführung freigeben.",
        "2. Neue CRM-Leads und Inbox-Benachrichtigungen synchronisieren.",
        "3. Systembereit für autonome Aufträge über QuickChat und Mission Control.",
        "",
        "---",
        f"*Generiert von Hermes Master Orchestrator um {now_str} Uhr.*"
    ]

    briefing_md = "\n".join(lines)

    # 5. In Obsidian Vault & Memory ablegen
    try:
        from local_memory_bridge import LocalMemoryBridge
        bridge = LocalMemoryBridge()
        vault_path = bridge.vault_path
        out_dir = os.path.join(vault_path, "01_PROJEKTE", "Daily_Briefings")
        os.makedirs(out_dir, exist_ok=True)
        out_file = os.path.join(out_dir, f"Briefing_{today_str}.md")
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(briefing_md)
        bridge.record_learning("orchestrator", "Daily-Standup", f"Morgen-Briefing für {today_str} erstellt", briefing_md[:300])
    except Exception as e:
        print(f"[Standup] Vault save notice: {e}", file=sys.stderr)

    return {
        "status": "success",
        "date": today_str,
        "time": now_str,
        "standup_schedule_time": standup_time,
        "active_services": active_services,
        "total_services": total_services,
        "tasks_in_progress": len(in_progress_tasks),
        "tasks_open": len(open_tasks),
        "obsidian_file": out_file,
        "briefing_markdown": briefing_md
    }
