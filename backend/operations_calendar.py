"""
backend/operations_calendar.py
==============================
M25 — Operativer Operations-Kalender (ERP, Kanban, n8n-Crons & Termine/Geburtstage).
"""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
import threading
import uuid
from typing import Any, Dict, List, Optional

from archon.core.runtime import WORKSPACE_DIR


class OperationsCalendarManager:
    """Aggregiert Fristen, Zahlungsziele, Cronjobs und eigene Termine in einer Timeline."""

    def __init__(
        self,
        data_dir: Optional[str] = None,
        kanban_db_path: Optional[str] = None,
        erp_db_path: Optional[str] = None,
    ) -> None:
        base_data = data_dir or os.path.join(WORKSPACE_DIR, "data")
        self.data_dir = os.path.realpath(base_data)
        os.makedirs(self.data_dir, exist_ok=True)
        self.custom_file = os.path.join(self.data_dir, "calendar_events.json")
        self.kanban_db_path = kanban_db_path
        self.erp_db_path = erp_db_path
        self._lock = threading.RLock()

    def _load_custom(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.custom_file):
            return []
        try:
            with open(self.custom_file, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return []

    def _save_custom(self, events: List[Dict[str, Any]]) -> None:
        tmp = f"{self.custom_file}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(events, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.custom_file)

    def create_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        title = str(payload.get("title") or "").strip()
        date_str = str(payload.get("date") or "").strip()
        if not title or not date_str:
            raise ValueError("title und date (YYYY-MM-DD) sind erforderlich.")
        ev = {
            "id": f"cal_{uuid.uuid4().hex[:8]}",
            "title": title,
            "date": date_str[:10],
            "time": str(payload.get("time") or ""),
            "category": str(payload.get("category") or "appointment"),
            "source": "custom",
            "notes": str(payload.get("notes") or ""),
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        with self._lock:
            events = self._load_custom()
            events.append(ev)
            self._save_custom(events)
        return ev

    def delete_event(self, event_id: str) -> bool:
        with self._lock:
            events = self._load_custom()
            new_events = [e for e in events if e.get("id") != event_id]
            if len(new_events) == len(events):
                return False
            self._save_custom(new_events)
            return True

    def _collect_kanban_deadlines(self) -> List[Dict[str, Any]]:
        candidates = [
            self.kanban_db_path,
            "/opt/data/kanban.db",
            os.path.join(self.data_dir, "kanban.db"),
        ]
        db_path = next((p for p in candidates if p and os.path.isfile(p)), None)
        if not db_path:
            return []
        out: List[Dict[str, Any]] = []
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3.0) as conn:
                conn.row_factory = sqlite3.Row
                cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
                date_col = "due_date" if "due_date" in cols else ("deadline" if "deadline" in cols else None)
                if not date_col:
                    return []
                rows = conn.execute(
                    f"SELECT id, title, status, {date_col} AS due FROM tasks WHERE {date_col} IS NOT NULL AND {date_col} != ''"
                ).fetchall()
                for r in rows:
                    out.append({
                        "id": f"kanban_{r['id']}",
                        "title": f"[Kanban] {r['title']}",
                        "date": str(r["due"])[:10],
                        "time": "",
                        "category": "deadline",
                        "source": "kanban",
                        "status": r["status"],
                    })
        except Exception:
            pass
        return out

    def _collect_erp_due_dates(self) -> List[Dict[str, Any]]:
        candidates = [self.erp_db_path] if self.erp_db_path else []
        try:
            from backend.tenant_context import tenant_context
            candidates.append(tenant_context.resolve_tenant_db("erp.db"))
        except Exception:
            pass
        db_path = next((p for p in candidates if p and os.path.isfile(p)), None)
        if not db_path:
            return []
        out: List[Dict[str, Any]] = []
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3.0) as conn:
                conn.row_factory = sqlite3.Row
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                if "erp_documents" not in tables:
                    return []
                rows = conn.execute(
                    "SELECT id, doc_number, doc_type, due_date, total_gross, status FROM erp_documents WHERE due_date IS NOT NULL AND due_date != ''"
                ).fetchall()
                for r in rows:
                    out.append({
                        "id": f"erp_{r['id']}",
                        "title": f"[ERP {r['doc_type']}] {r['doc_number']} ({r['total_gross']} EUR)",
                        "date": str(r["due_date"])[:10],
                        "time": "",
                        "category": "payment_due",
                        "source": "erp",
                        "status": r["status"],
                    })
        except Exception:
            pass
        return out

    def _collect_n8n_routines(self, start_date: Optional[str], end_date: Optional[str]) -> List[Dict[str, Any]]:
        today = datetime.date.today()
        base_d = datetime.date.fromisoformat(start_date[:10]) if start_date else today
        return [
            {
                "id": "n8n_morning_briefing",
                "title": "[n8n] Morning-Briefing Routine (Mo–Fr 07:30)",
                "date": base_d.isoformat(),
                "time": "07:30",
                "category": "cron",
                "source": "n8n",
                "recurrence": "weekdays",
            },
            {
                "id": "n8n_weekly_audit",
                "title": "[n8n] Weekly Maintenance & SQLite-Backup (So 23:00)",
                "date": (base_d + datetime.timedelta(days=(6 - base_d.weekday()) % 7)).isoformat(),
                "time": "23:00",
                "category": "cron",
                "source": "n8n",
                "recurrence": "weekly",
            },
        ]

    def list_events(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        source: str = "all",
    ) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        if source in ("all", "custom"):
            events.extend(self._load_custom())
        if source in ("all", "kanban"):
            events.extend(self._collect_kanban_deadlines())
        if source in ("all", "erp"):
            events.extend(self._collect_erp_due_dates())
        if source in ("all", "n8n"):
            events.extend(self._collect_n8n_routines(start_date, end_date))

        filtered: List[Dict[str, Any]] = []
        for ev in events:
            d = str(ev.get("date") or "")[:10]
            if start_date and d and d < start_date[:10]:
                continue
            if end_date and d and d > end_date[:10]:
                continue
            filtered.append(ev)

        filtered.sort(key=lambda x: (str(x.get("date") or ""), str(x.get("time") or "")))
        return filtered


operations_calendar = OperationsCalendarManager()
