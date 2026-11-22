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

from archon.core.runtime import WORKSPACE_DIR, logger


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

    @staticmethod
    def _active_cid(company_id: Optional[str] = None) -> str:
        if company_id:
            try:
                from backend.tenant_context import sanitize_tenant_id
                return sanitize_tenant_id(company_id)
            except Exception:
                return str(company_id).strip() or "default"
        try:
            from backend.tenant_context import tenant_context, sanitize_tenant_id
            return sanitize_tenant_id(tenant_context.get_active_tenant_id() or "default")
        except Exception:
            return "default"

    def create_event(self, payload: Dict[str, Any], company_id: Optional[str] = None) -> Dict[str, Any]:
        title = str(payload.get("title") or "").strip()
        start_raw = str(payload.get("start") or "").strip()
        date_str = str(payload.get("date") or (start_raw[:10] if start_raw else "")).strip()
        if not title or not date_str:
            raise ValueError("title und date/start sind erforderlich.")
        time_str = str(payload.get("time") or (start_raw[11:16] if len(start_raw) >= 16 else "")).strip()
        end_raw = str(payload.get("end") or "").strip()
        all_day = bool(payload.get("all_day", not bool(time_str) and "T" not in start_raw))
        if not start_raw:
            start_raw = f"{date_str[:10]}T{time_str}:00" if time_str and not all_day else date_str[:10]
        if not end_raw and not all_day and len(start_raw) >= 16:
            try:
                sdt = datetime.datetime.fromisoformat(start_raw[:19])
                end_raw = (sdt + datetime.timedelta(minutes=60)).isoformat(timespec="minutes")
            except Exception:
                end_raw = ""

        cid = self._active_cid(company_id or payload.get("company_id"))
        res_name = str(payload.get("resource") or "").strip()
        if res_name and not all_day and time_str and not payload.get("allow_conflict"):
            conflicts = self.check_resource_conflict(res_name, date_str[:10], start_raw, end_raw, company_id=cid)
            if conflicts:
                c0 = conflicts[0]
                raise ValueError(f"Ressourcen-Konflikt: '{res_name}' ist bereits belegt ({c0.get('title')} {c0.get('time')}).")
        ev = {
            "id": f"cal_{uuid.uuid4().hex[:8]}",
            "company_id": cid,
            "title": title,
            "date": date_str[:10],
            "time": time_str,
            "start": start_raw,
            "end": end_raw,
            "all_day": all_day,
            "category": str(payload.get("category") or "appointment"),
            "source": "custom",
            "location": str(payload.get("location") or "").strip(),
            "meeting_url": str(payload.get("meeting_url") or "").strip(),
            "attendees": str(payload.get("attendees") or "").strip(),
            "resource": str(payload.get("resource") or "").strip(),
            "reminder_min": int(payload.get("reminder_min") or 15),
            "recurrence": str(payload.get("recurrence") or "none").strip(),
            "recurrence_days": [int(x) for x in (payload.get("recurrence_days") or []) if str(x).isdigit()],
            "recurrence_until": str(payload.get("recurrence_until") or "").strip()[:10],
            "color": str(payload.get("color") or "").strip(),
            "trigger_workflow_id": str(payload.get("trigger_workflow_id") or "").strip(),
            "notes": str(payload.get("notes") or ""),
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        with self._lock:
            events = self._load_custom()
            events.append(ev)
            self._save_custom(events)
        try:
            from backend.workflow_scheduler import dispatch_workflow_event
            dispatch_workflow_event(
                source="calendar",
                event_type="created",
                title=ev["title"],
                summary=f"Datum: {ev['date']} {ev['time']} | Kategorie: {ev['category']}",
                payload={"event_id": ev["id"], "date": ev["date"], "time": ev["time"], "trigger_workflow_id": ev["trigger_workflow_id"]},
                correlation_id=f"cal-create-{ev['id']}",
            )
        except Exception as exc:
            logger.debug(f"[Calendar] Event-Bus-Benachrichtigung (create) uebersprungen: {exc}")
        return ev

    def update_event(self, event_id: str, payload: Dict[str, Any], company_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        cid = self._active_cid(company_id)
        occ_date = str(payload.get("occurrence_date") or "").strip()[:10]
        with self._lock:
            events = self._load_custom()
            updated = None
            for ev in events:
                if ev.get("id") == event_id and (ev.get("company_id") in (None, "", cid) or company_id is None):
                    if occ_date:
                        overrides = ev.setdefault("occurrence_overrides", {})
                        ov = overrides.setdefault(occ_date, {})
                        for field in ("title", "start", "end", "date", "time", "category", "location", "meeting_url", "resource", "notes"):
                            if field in payload and payload[field] is not None:
                                ov[field] = str(payload[field]).strip() if field != "notes" else str(payload[field])
                        if payload.get("start"):
                            ov["date"] = str(payload["start"])[:10]
                            if len(str(payload["start"])) >= 16:
                                ov["time"] = str(payload["start"])[11:16]
                        ev["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                        updated = ev
                        break

                    for field in ("title", "start", "end", "date", "time", "category", "location", "meeting_url", "attendees", "resource", "recurrence", "recurrence_until", "color", "trigger_workflow_id", "notes"):
                        if field in payload and payload[field] is not None:
                            ev[field] = str(payload[field]).strip() if field != "notes" else str(payload[field])
                    if "recurrence_days" in payload and isinstance(payload["recurrence_days"], list):
                        ev["recurrence_days"] = [int(x) for x in payload["recurrence_days"] if str(x).isdigit()]
                    if "rsvp_status" in payload and isinstance(payload["rsvp_status"], dict):
                        ev["rsvp_status"] = payload["rsvp_status"]
                    if "all_day" in payload:
                        ev["all_day"] = bool(payload["all_day"])
                    if "reminder_min" in payload and payload["reminder_min"] is not None:
                        ev["reminder_min"] = int(payload["reminder_min"])
                    if payload.get("start"):
                        ev["date"] = str(payload["start"])[:10]
                        if len(str(payload["start"])) >= 16 and not ev.get("all_day"):
                            ev["time"] = str(payload["start"])[11:16]
                    res_chk = str(ev.get("resource") or "").strip()
                    if res_chk and not ev.get("all_day") and ev.get("time") and not payload.get("allow_conflict"):
                        conflicts = self.check_resource_conflict(
                            res_chk, ev["date"], ev.get("start") or "", ev.get("end") or "", exclude_id=ev["id"], company_id=cid
                        )
                        if conflicts:
                            c0 = conflicts[0]
                            raise ValueError(f"Ressourcen-Konflikt: '{res_chk}' ist bereits belegt ({c0.get('title')} {c0.get('time')}).")
                    ev["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    updated = ev
                    break
            if updated:
                self._save_custom(events)
                try:
                    from backend.workflow_scheduler import dispatch_workflow_event
                    dispatch_workflow_event(
                        source="calendar",
                        event_type="updated",
                        title=updated["title"],
                        summary=f"Aktualisiert: {updated['date']} {updated.get('time', '')}",
                        payload={"event_id": updated["id"], "date": updated["date"], "time": updated.get("time", "")},
                    )
                except Exception as exc:
                    logger.debug(f"[Calendar] Event-Bus-Benachrichtigung (update) uebersprungen: {exc}")
                self._auto_writeback(updated)
            return updated

    def delete_event(self, event_id: str, company_id: Optional[str] = None, occurrence_date: Optional[str] = None) -> bool:
        cid = self._active_cid(company_id)
        occ = str(occurrence_date or "").strip()[:10]
        with self._lock:
            events = self._load_custom()
            if occ:
                for ev in events:
                    if ev.get("id") == event_id and (ev.get("company_id") in (None, "", cid) or company_id is None):
                        ex = ev.setdefault("excluded_dates", [])
                        if occ not in ex:
                            ex.append(occ)
                        self._save_custom(events)
                        return True
                return False
            new_events = [
                e for e in events
                if not (e.get("id") == event_id and (e.get("company_id") in (None, "", cid) or company_id is None))
            ]
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
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3.0)
            try:
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
            finally:
                conn.close()
        except Exception as exc:
            logger.debug(f"[Calendar] Kanban-Fristen konnten nicht geladen werden: {exc}")
        return out

    def _collect_erp_due_dates(self, company_id: Optional[str] = None) -> List[Dict[str, Any]]:
        candidates = [self.erp_db_path] if self.erp_db_path else []
        try:
            from backend.tenant_context import tenant_context
            candidates.append(tenant_context.resolve_tenant_db("erp.db", company_id=company_id))
        except Exception as exc:
            logger.debug(f"[Calendar] Tenant-ERP-Pfad konnte nicht aufgeloest werden: {exc}")
        db_path = next((p for p in candidates if p and os.path.isfile(p)), None)
        if not db_path:
            return []
        out: List[Dict[str, Any]] = []
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3.0)
            try:
                conn.row_factory = sqlite3.Row
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                if "erp_documents" not in tables:
                    return []
                rows = conn.execute(
                    "SELECT id, doc_number, doc_type, due_date, amount_gross, status FROM erp_documents WHERE due_date IS NOT NULL AND due_date != ''"
                ).fetchall()
                for r in rows:
                    out.append({
                        "id": f"erp_{r['id']}",
                        "title": f"[ERP {r['doc_type']}] {r['doc_number']} ({r['amount_gross']} EUR)",
                        "date": str(r["due_date"])[:10],
                        "time": "",
                        "category": "payment_due",
                        "source": "erp",
                        "status": r["status"],
                    })
            finally:
                conn.close()
        except Exception as exc:
            logger.debug(f"[Calendar] ERP-Faelligkeiten konnten nicht geladen werden: {exc}")
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

    def _collect_workflow_schedules(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            from backend.workflow_scheduler import list_schedules
            for s in list_schedules():
                if not s.get("enabled"):
                    continue
                nxt = str(s.get("next_run_at") or "").strip()
                if len(nxt) >= 10:
                    out.append({
                        "id": f"wfsched_{s['id']}",
                        "title": f"[Workflow] {s.get('title') or s['template_id']}",
                        "date": nxt[:10],
                        "time": nxt[11:16] if len(nxt) >= 16 else "08:00",
                        "start": nxt[:16],
                        "category": "cron",
                        "source": "workflow",
                        "notes": f"Trigger: {s.get('trigger_type')} | Cron: {s.get('cron_expr') or '-'}",
                    })
        except Exception as exc:
            logger.debug(f"[Calendar] Workflow-Schedules konnten nicht geladen werden: {exc}")
        return out

    def _sources_path(self) -> str:
        return os.path.join(WORKSPACE_DIR, "config", "calendar_sources.json")

    def _external_cache_path(self) -> str:
        return os.path.join(self.data_dir, "calendar_external_events.json")

    def list_sources(self) -> List[Dict[str, Any]]:
        p = self._sources_path()
        if not os.path.isfile(p):
            return []
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def save_sources(self, sources: List[Dict[str, Any]]) -> None:
        p = self._sources_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(sources, f, ensure_ascii=False, indent=2)

    def upsert_source(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        url = str(payload.get("url") or "").strip()
        if not name or not url:
            raise ValueError("name und url erforderlich")
        sid = str(payload.get("id") or f"calsrc_{uuid.uuid4().hex[:8]}").strip()
        src = {
            "id": sid,
            "name": name,
            "provider": str(payload.get("provider") or "ics_feed").strip(),
            "url": url,
            "username": str(payload.get("username") or "").strip(),
            "password": str(payload.get("password") or "").strip(),
            "access_token": str(payload.get("access_token") or "").strip(),
            "refresh_token": str(payload.get("refresh_token") or "").strip(),
            "expires_at": payload.get("expires_at") or "",
            "two_way_sync": bool(payload.get("two_way_sync", False)),
            "color": str(payload.get("color") or "#0ea5e9").strip(),
            "enabled": bool(payload.get("enabled", True)),
            "last_sync": "",
            "event_count": 0,
        }
        with self._lock:
            existing = next((s for s in self.list_sources() if s.get("id") == sid), None)
            if existing:
                for sec_k in ("password", "access_token", "refresh_token", "expires_at"):
                    if not src.get(sec_k) and existing.get(sec_k):
                        src[sec_k] = existing[sec_k]
            sources = [s for s in self.list_sources() if s.get("id") != sid]
            sources.append(src)
            self.save_sources(sources)
        return {k: v for k, v in src.items() if k not in ("password", "access_token", "refresh_token")}

    def delete_source(self, src_id: str) -> bool:
        with self._lock:
            sources = self.list_sources()
            filtered = [s for s in sources if s.get("id") != src_id]
            if len(filtered) == len(sources):
                return False
            self.save_sources(filtered)
        return True

    def _load_external_events(self) -> List[Dict[str, Any]]:
        p = self._external_cache_path()
        if not os.path.isfile(p):
            return []
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def sync_source(self, src_id: str) -> Dict[str, Any]:
        import base64
        import urllib.request
        from backend.calendar_sync_blocker import parse_ics_events

        sources = self.list_sources()
        src = next((s for s in sources if s.get("id") == src_id), None)
        if not src:
            raise KeyError("source_not_found")
        prov = str(src.get("provider") or "")
        mapped: List[Dict[str, Any]] = []

        if prov == "google_oauth":
            token = self._ensure_fresh_oauth_token(src)
            req = urllib.request.Request(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events?maxResults=100&singleEvents=true",
                headers={"Authorization": f"Bearer {token}"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                items = json.loads(resp.read().decode("utf-8")).get("items") or []
            for it in items:
                st = str((it.get("start") or {}).get("dateTime") or (it.get("start") or {}).get("date") or "")
                en = str((it.get("end") or {}).get("dateTime") or (it.get("end") or {}).get("date") or "")
                if not st:
                    continue
                mapped.append({
                    "id": f"ext_{src_id}_{it.get('id', len(mapped))}",
                    "source_id": src_id,
                    "title": f"[{src['name']}] {it.get('summary') or 'Termin'}",
                    "date": st[:10],
                    "time": st[11:16] if "T" in st else "",
                    "start": st[:16],
                    "end": en[:16],
                    "all_day": "T" not in st,
                    "category": "external",
                    "source": "external",
                    "color": src.get("color") or "#0ea5e9",
                    "location": it.get("location") or "",
                })
        elif prov == "outlook_oauth":
            token = self._ensure_fresh_oauth_token(src)
            req = urllib.request.Request(
                "https://graph.microsoft.com/v1.0/me/events?$top=100",
                headers={"Authorization": f"Bearer {token}"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                items = json.loads(resp.read().decode("utf-8")).get("value") or []
            for it in items:
                st = str((it.get("start") or {}).get("dateTime") or "")
                en = str((it.get("end") or {}).get("dateTime") or "")
                if not st:
                    continue
                is_all = bool(it.get("isAllDay"))
                mapped.append({
                    "id": f"ext_{src_id}_{it.get('id', len(mapped))}",
                    "source_id": src_id,
                    "title": f"[{src['name']}] {it.get('subject') or 'Termin'}",
                    "date": st[:10],
                    "time": "" if is_all else st[11:16],
                    "start": st[:10] if is_all else st[:16],
                    "end": en[:16],
                    "all_day": is_all,
                    "category": "external",
                    "source": "external",
                    "color": src.get("color") or "#0ea5e9",
                    "location": str(((it.get("location") or {}).get("displayName")) or ""),
                })
        else:
            from utils.safe_http import safe_http_request
            headers = {"User-Agent": "ArchonOS-Calendar/1.0"}
            if src.get("username") and src.get("password"):
                tok = base64.b64encode(f"{src['username']}:{src['password']}".encode("utf-8")).decode("ascii")
                headers["Authorization"] = f"Basic {tok}"
            resp_ics = safe_http_request(src["url"], method="GET", headers=headers, timeout=15.0, max_bytes=8 * 1024 * 1024)
            ics_text = (resp_ics.get("body") or b"").decode("utf-8", errors="ignore")
            parsed = parse_ics_events(ics_text)
            for idx, pe in enumerate(parsed):
                st = str(pe.get("start") or "")
                en = str(pe.get("end") or "")
                d = f"{st[:4]}-{st[4:6]}-{st[6:8]}" if len(st) >= 8 and "-" not in st else st[:10]
                t = f"{st[9:11]}:{st[11:13]}" if len(st) >= 13 and "T" in st and ":" not in st else (st[11:16] if len(st) >= 16 else "")
                end_iso = f"{en[:4]}-{en[4:6]}-{en[6:8]}T{en[9:11]}:{en[11:13]}" if len(en) >= 13 and "T" in en and "-" not in en else en
                if not d:
                    continue
                mapped.append({
                    "id": f"ext_{src_id}_{idx}",
                    "source_id": src_id,
                    "title": f"[{src['name']}] {pe.get('summary') or 'Termin'}",
                    "date": d,
                    "time": t,
                    "start": f"{d}T{t}" if t else d,
                    "end": end_iso,
                    "all_day": not bool(t),
                    "category": "external",
                    "source": "external",
                    "color": src.get("color") or "#0ea5e9",
                    "location": pe.get("location") or "",
                })
        with self._lock:
            existing = [e for e in self._load_external_events() if e.get("source_id") != src_id]
            existing.extend(mapped)
            cp = self._external_cache_path()
            os.makedirs(os.path.dirname(cp), exist_ok=True)
            with open(cp, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
            src["last_sync"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            src["event_count"] = len(mapped)
            self.save_sources(sources)
        try:
            from backend.workflow_scheduler import dispatch_workflow_event
            dispatch_workflow_event(
                source="calendar",
                event_type="synced",
                title=f"Kalender-Sync: {src['name']}",
                summary=f"{len(mapped)} Termine synchronisiert ({src.get('provider')})",
                payload={"source_id": src_id, "imported": len(mapped)},
            )
        except Exception as exc:
            logger.debug(f"[Calendar] Event-Bus-Benachrichtigung (sync) uebersprungen: {exc}")
        return {"source_id": src_id, "imported": len(mapped)}

    def import_ics_text(self, ics_text: str, company_id: Optional[str] = None) -> List[Dict[str, Any]]:
        from backend.calendar_sync_blocker import parse_ics_events
        parsed = parse_ics_events(ics_text)
        created: List[Dict[str, Any]] = []
        for pe in parsed:
            st = str(pe.get("start") or "")
            d = f"{st[:4]}-{st[4:6]}-{st[6:8]}" if len(st) >= 8 and "-" not in st else st[:10]
            t = f"{st[9:11]}:{st[11:13]}" if len(st) >= 13 and "T" in st and ":" not in st else (st[11:16] if len(st) >= 16 else "")
            if not d:
                continue
            created.append(self.create_event({
                "title": pe.get("summary") or "Importierter Termin",
                "date": d,
                "time": t,
                "location": pe.get("location") or "",
                "category": "appointment",
            }, company_id=company_id))
        return created

    def export_ics_text(self, company_id: Optional[str] = None) -> str:
        from backend.calendar_sync_blocker import export_ics_events
        evs = self.list_events(source="custom", company_id=company_id)
        mapped = [
            {
                "uid": e.get("id"),
                "summary": e.get("title"),
                "start": str(e.get("start") or e.get("date") or "").replace("-", "").replace(":", ""),
                "end": str(e.get("end") or e.get("date") or "").replace("-", "").replace(":", ""),
                "location": e.get("location") or "",
            }
            for e in evs
        ]
        return export_ics_events(mapped)

    def find_focus_slots(self, duration_min: int = 90, days_ahead: int = 5) -> List[Dict[str, Any]]:
        today = datetime.date.today()
        end_d = today + datetime.timedelta(days=days_ahead)
        busy = self.list_events(start_date=today.isoformat(), end_date=end_d.isoformat())
        busy_by_day: Dict[str, List[tuple]] = {}
        for ev in busy:
            d = str(ev.get("date") or "")[:10]
            t = str(ev.get("time") or "")
            if d and len(t) == 5 and ":" in t:
                try:
                    hh, mm = int(t[:2]), int(t[3:5])
                    s_min = hh * 60 + mm
                    busy_by_day.setdefault(d, []).append((s_min, s_min + 60))
                except (ValueError, TypeError) as exc:
                    logger.debug(f"[Calendar] Ungueltige Terminzeit {t!r} uebersprungen: {exc}")
        slots: List[Dict[str, Any]] = []
        for offset in range(days_ahead + 1):
            day = today + datetime.timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            d_str = day.isoformat()
            intervals = busy_by_day.get(d_str, [])
            for start_m in range(9 * 60, 17 * 60 - duration_min + 1, 30):
                end_m = start_m + duration_min
                if not any(not (end_m <= bs or start_m >= be) for bs, be in intervals):
                    slots.append({
                        "date": d_str,
                        "start": f"{d_str}T{start_m // 60:02d}:{start_m % 60:02d}",
                        "end": f"{d_str}T{end_m // 60:02d}:{end_m % 60:02d}",
                        "label": f"{d_str} · {start_m // 60:02d}:{start_m % 60:02d}–{end_m // 60:02d}:{end_m % 60:02d}",
                    })
                    break
        return slots

    def _expand_recurring(self, ev: Dict[str, Any], start_date: Optional[str], end_date: Optional[str]) -> List[Dict[str, Any]]:
        rec = str(ev.get("recurrence") or "none").lower()
        if rec in ("", "none") or not start_date or not end_date:
            return [ev]
        try:
            base_d = datetime.date.fromisoformat(str(ev.get("date") or "")[:10])
            win_s = datetime.date.fromisoformat(start_date[:10])
            win_e = datetime.date.fromisoformat(end_date[:10])
            until_raw = str(ev.get("recurrence_until") or "").strip()[:10]
            if until_raw:
                win_e = min(win_e, datetime.date.fromisoformat(until_raw))
        except Exception:
            return [ev]

        ex_dates = set(ev.get("excluded_dates") or [])
        overrides = ev.get("occurrence_overrides") or {}
        rec_days = [int(x) for x in (ev.get("recurrence_days") or []) if 0 <= int(x) <= 6]
        out: List[Dict[str, Any]] = []
        cur = base_d
        step = 0
        if rec == "weekly" and rec_days:
            # Tagweise ueber den Zeitraum iterieren und gewaehlte Wochentage (Mo=0..So=6) matchen
            while cur <= win_e and step < 366:
                d_iso = cur.isoformat()
                if cur >= win_s and cur.weekday() in rec_days and d_iso not in ex_dates:
                    clone = dict(ev)
                    clone["date"] = d_iso
                    clone["start"] = f"{d_iso}T{clone['time']}" if clone.get("time") else d_iso
                    if d_iso in overrides and isinstance(overrides[d_iso], dict):
                        clone.update(overrides[d_iso])
                    if cur != base_d:
                        clone["id"] = f"{ev['id']}__occ_{d_iso}"
                        clone["parent_id"] = ev["id"]
                        clone["occurrence_date"] = d_iso
                    out.append(clone)
                cur = cur + datetime.timedelta(days=1)
                step += 1
            return out

        while cur <= win_e and step < 120:
            d_iso = cur.isoformat()
            if cur >= win_s and d_iso not in ex_dates:
                clone = dict(ev)
                clone["date"] = d_iso
                clone["start"] = f"{d_iso}T{clone['time']}" if clone.get("time") else d_iso
                if d_iso in overrides and isinstance(overrides[d_iso], dict):
                    clone.update(overrides[d_iso])
                if step > 0:
                    clone["id"] = f"{ev['id']}__occ_{d_iso}"
                    clone["parent_id"] = ev["id"]
                    clone["occurrence_date"] = d_iso
                out.append(clone)
            step += 1
            if rec == "daily":
                cur = cur + datetime.timedelta(days=1)
            elif rec == "weekly":
                cur = cur + datetime.timedelta(days=7)
            elif rec == "monthly":
                m = cur.month + 1
                y = cur.year + (1 if m > 12 else 0)
                m = 1 if m > 12 else m
                d_num = min(cur.day, 28)
                cur = datetime.date(y, m, d_num)
            else:
                break
        return out or [ev]

    def _easter_sunday(self, year: int) -> datetime.date:
        a = year % 19
        b = year // 100
        c = year % 100
        d = b // 4
        e = b % 4
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30
        i = c // 4
        k = c % 4
        l = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * l) // 451
        month = (h + l - 7 * m + 114) // 31
        day = ((h + l - 7 * m + 114) % 31) + 1
        return datetime.date(year, month, day)

    def _collect_german_holidays(self, start_date: Optional[str], end_date: Optional[str], state: str = "BY") -> List[Dict[str, Any]]:
        st = (state or "BY").upper()
        try:
            y_start = int((start_date or datetime.date.today().isoformat())[:4])
            y_end = int((end_date or datetime.date.today().isoformat())[:4])
        except Exception:
            y_start = y_end = datetime.date.today().year

        out: List[Dict[str, Any]] = []
        for year in range(y_start, min(y_end + 1, y_start + 3)):
            easter = self._easter_sunday(year)
            items = [
                (datetime.date(year, 1, 1), "Neujahr"),
                (easter - datetime.timedelta(days=2), "Karfreitag"),
                (easter + datetime.timedelta(days=1), "Ostermontag"),
                (datetime.date(year, 5, 1), "Tag der Arbeit"),
                (easter + datetime.timedelta(days=39), "Christi Himmelfahrt"),
                (easter + datetime.timedelta(days=50), "Pfingstmontag"),
                (datetime.date(year, 10, 3), "Tag der Deutschen Einheit"),
                (datetime.date(year, 12, 25), "1. Weihnachtstag"),
                (datetime.date(year, 12, 26), "2. Weihnachtstag"),
            ]
            if st in ("BW", "BY", "ST"):
                items.append((datetime.date(year, 1, 6), "Heilige Drei Koenige"))
            if st in ("BW", "BY", "HE", "NW", "RP", "SL"):
                items.append((easter + datetime.timedelta(days=60), "Fronleichnam"))
            if st in ("BY", "SL"):
                items.append((datetime.date(year, 8, 15), "Mariae Himmelfahrt"))
            if st in ("BB", "HB", "HH", "MV", "NI", "SH", "SN", "ST", "TH"):
                items.append((datetime.date(year, 10, 31), "Reformationstag"))
            if st in ("BW", "BY", "NW", "RP", "SL"):
                items.append((datetime.date(year, 11, 1), "Allerheiligen"))
            if st == "BE":
                items.append((datetime.date(year, 3, 8), "Internationaler Frauentag"))

            for d_obj, label in items:
                d_iso = d_obj.isoformat()
                out.append({
                    "id": f"hol_{st}_{d_iso}",
                    "title": f"{label} ({st})",
                    "date": d_iso,
                    "time": "",
                    "start": d_iso,
                    "all_day": True,
                    "category": "holiday",
                    "source": "holiday",
                    "color": "#64748b",
                })
        return out

    def send_invites(self, event_id: str, company_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            events = self._load_custom()
            ev = next((e for e in events if e.get("id") == event_id), None)
            if not ev:
                raise KeyError("event_not_found")
            attendees = [a.strip() for a in str(ev.get("attendees") or "").split(",") if "@" in a]
            if not attendees:
                raise ValueError("no_valid_attendees")
            rsvp = ev.setdefault("rsvp_status", {})
            for a in attendees:
                rsvp.setdefault(a, "pending")
            self._save_custom(events)

        ics_body = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Archon OS//Calendar//DE\r\nMETHOD:REQUEST\r\n"
            f"BEGIN:VEVENT\r\nUID:{ev['id']}@archon.local\r\nSUMMARY:{ev['title']}\r\n"
            f"DTSTART:{str(ev.get('start') or ev['date']).replace('-', '').replace(':', '')}\r\n"
            f"DTEND:{str(ev.get('end') or ev['date']).replace('-', '').replace(':', '')}\r\n"
            f"LOCATION:{ev.get('location') or ev.get('meeting_url') or ''}\r\n"
            + "".join(f"ATTENDEE;PARTSTAT=NEEDS-ACTION:mailto:{a}\r\n" for a in attendees)
            + "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        draft_ids = []
        try:
            from backend.email_draft_engine import email_draft_engine
            for a in attendees:
                d = email_draft_engine.create_draft(
                    recipient=a,
                    subject=f"Einladung: {ev['title']} ({ev['date']} {ev.get('time', '')})",
                    body_text=(
                        f"Hallo,\n\nhiermit lade ich dich zum Termin '{ev['title']}' ein.\n"
                        f"Datum: {ev['date']} {ev.get('time', '')}\n"
                        f"Ort/Link: {ev.get('meeting_url') or ev.get('location') or '-'}\n\n"
                        f"--- .ics Kalendereinladung ---\n{ics_body}"
                    ),
                    source="calendar_invite",
                )
                if isinstance(d, dict) and d.get("id"):
                    draft_ids.append(d["id"])
        except Exception as exc:
            logger.warning(f"[Calendar] Einladungs-E-Mail-Entwurf fehlgeschlagen ({event_id}): {exc}")
        return {"event_id": event_id, "attendees": attendees, "rsvp_status": ev["rsvp_status"], "draft_ids": draft_ids, "ics": ics_body}

    def update_rsvp(self, event_id: str, email: str, status: str) -> Dict[str, Any]:
        st = status if status in ("pending", "accepted", "declined", "tentative") else "pending"
        with self._lock:
            events = self._load_custom()
            ev = next((e for e in events if e.get("id") == event_id), None)
            if not ev:
                raise KeyError("event_not_found")
            rsvp = ev.setdefault("rsvp_status", {})
            rsvp[email.strip()] = st
            self._save_custom(events)
            return {"event_id": event_id, "rsvp_status": rsvp}

    def _booking_types_path(self) -> str:
        cfg = os.path.join(os.path.dirname(self.data_dir), "config")
        os.makedirs(cfg, exist_ok=True)
        return os.path.join(cfg, "calendar_booking_types.json")

    def list_booking_types(self) -> List[Dict[str, Any]]:
        defaults = [
            {
                "slug": "intro-15",
                "title": "15-Min Intro Call",
                "duration_min": 15,
                "buffer_before_min": 5,
                "buffer_after_min": 5,
                "max_per_day": 6,
                "brand_name": "Archon OS",
                "brand_color": "#0ea5e9",
                "welcome_text": "Kurzes 15-Minuten-Kennenlernen.",
            },
            {
                "slug": "mein-termin",
                "title": "30-Min Beratung",
                "duration_min": 30,
                "buffer_before_min": 10,
                "buffer_after_min": 10,
                "max_per_day": 4,
                "brand_name": "Archon OS",
                "brand_color": "#6366f1",
                "welcome_text": "Waehle einen passenden 30-Minuten-Termin.",
            },
            {
                "slug": "workshop-60",
                "title": "60-Min Deep-Dive Workshop",
                "duration_min": 60,
                "buffer_before_min": 15,
                "buffer_after_min": 15,
                "max_per_day": 2,
                "brand_name": "Archon OS",
                "brand_color": "#10b981",
                "welcome_text": "Ausfuehrliche Strategie- & Architektur-Session.",
            },
        ]
        p = self._booking_types_path()
        if not os.path.isfile(p):
            return defaults
        try:
            with open(p, "r", encoding="utf-8") as f:
                rows = json.load(f)
            return rows if isinstance(rows, list) and rows else defaults
        except Exception:
            return defaults

    def get_booking_type(self, slug: str) -> Dict[str, Any]:
        items = self.list_booking_types()
        found = next((x for x in items if x.get("slug") == slug), None)
        if found:
            return found
        return {
            "slug": slug or "mein-termin",
            "title": f"Termin ({slug})",
            "duration_min": 30,
            "buffer_before_min": 0,
            "buffer_after_min": 0,
            "max_per_day": 8,
            "brand_name": "Archon OS",
            "brand_color": "#6366f1",
            "welcome_text": "Waehle einen freien Zeitslot.",
        }

    def upsert_booking_type(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        slug = str(payload.get("slug") or "").strip().lower().replace(" ", "-")
        if not slug:
            raise ValueError("slug erforderlich")
        raw_tm = payload.get("team_members")
        if isinstance(raw_tm, str):
            team_members = [x.strip() for x in raw_tm.split(",") if x.strip()]
        elif isinstance(raw_tm, list):
            team_members = [str(x).strip() for x in raw_tm if str(x).strip()]
        else:
            team_members = []
        raw_q = payload.get("questions")
        if isinstance(raw_q, str):
            questions = [x.strip() for x in raw_q.split(",") if x.strip()]
        elif isinstance(raw_q, list):
            questions = [str(x).strip() for x in raw_q if str(x).strip()]
        else:
            questions = []
        item = {
            "slug": slug,
            "title": str(payload.get("title") or slug).strip(),
            "duration_min": max(15, min(240, int(payload.get("duration_min") or 30))),
            "buffer_before_min": max(0, min(60, int(payload.get("buffer_before_min") or 0))),
            "buffer_after_min": max(0, min(60, int(payload.get("buffer_after_min") or 0))),
            "max_per_day": max(1, min(24, int(payload.get("max_per_day") or 4))),
            "brand_name": str(payload.get("brand_name") or "Archon OS").strip(),
            "brand_color": str(payload.get("brand_color") or "#6366f1").strip(),
            "welcome_text": str(payload.get("welcome_text") or "").strip(),
            "team_members": team_members,
            "price_eur": max(0.0, float(payload.get("price_eur") or 0)),
            "questions": questions,
        }
        with self._lock:
            items = self.list_booking_types()
            idx = next((i for i, x in enumerate(items) if x.get("slug") == slug), -1)
            if idx >= 0:
                items[idx] = item
            else:
                items.append(item)
            p = self._booking_types_path()
            tmp = f"{p}.tmp.{os.getpid()}"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
            os.replace(tmp, p)
        return item

    def delete_booking_type(self, slug: str) -> bool:
        with self._lock:
            items = self.list_booking_types()
            filtered = [x for x in items if x.get("slug") != slug]
            if len(filtered) == len(items):
                return False
            p = self._booking_types_path()
            tmp = f"{p}.tmp.{os.getpid()}"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(filtered, f, ensure_ascii=False, indent=2)
            os.replace(tmp, p)
            return True

    def get_booking_slots_for_slug(self, slug: str, duration_min: Optional[int] = None) -> List[Dict[str, Any]]:
        bt = self.get_booking_type(slug)
        dur = int(duration_min or bt.get("duration_min") or 30)
        buf_b = int(bt.get("buffer_before_min") or 0)
        buf_a = int(bt.get("buffer_after_min") or 0)
        max_per_day = int(bt.get("max_per_day") or 8)

        today = datetime.date.today()
        end_d = today + datetime.timedelta(days=7)
        evs = self.list_events(start_date=today.isoformat(), end_date=end_d.isoformat())

        def _parse_hhmm(val: str) -> Optional[int]:
            t = val[11:16] if "T" in val else val[:5]
            if ":" not in t:
                return None
            try:
                h, m = t.split(":")
                return int(h) * 60 + int(m)
            except Exception:
                return None

        slots: List[Dict[str, Any]] = []
        for offset in range(0, 8):
            cur_d = today + datetime.timedelta(days=offset)
            if cur_d.weekday() >= 5:
                continue
            d_iso = cur_d.isoformat()
            day_evs = [e for e in evs if e.get("date") == d_iso and e.get("source") not in ("holiday", "school_holiday")]
            booked_count = sum(1 for e in day_evs if f"Buchung ({slug})" in str(e.get("title") or ""))
            if booked_count >= max_per_day:
                continue

            busy_ranges: List[tuple] = []
            for e in day_evs:
                if e.get("all_day"):
                    continue
                s_m = _parse_hhmm(e.get("time") or str(e.get("start") or ""))
                if s_m is None:
                    continue
                e_m = _parse_hhmm(str(e.get("end") or "")) or (s_m + 60)
                if e_m <= s_m:
                    e_m = s_m + 60
                busy_ranges.append((s_m, e_m))

            for cand_s in range(9 * 60, 17 * 60 - dur + 1, 30):
                cand_e = cand_s + dur
                chk_s = cand_s - buf_b
                chk_e = cand_e + buf_a
                if any(not (chk_e <= bs or chk_s >= be) for bs, be in busy_ranges):
                    continue
                slots.append({
                    "date": d_iso,
                    "start": f"{d_iso}T{cand_s // 60:02d}:{cand_s % 60:02d}",
                    "end": f"{d_iso}T{cand_e // 60:02d}:{cand_e % 60:02d}",
                    "duration_min": dur,
                })
        return slots[:32]

    def _next_round_robin_member(self, slug: str, members: List[str], date_str: str, start_str: str, end_str: str) -> str:
        if not members:
            return ""
        rr_path = os.path.join(self.data_dir, "booking_rr_cursor.json")
        state: Dict[str, int] = {}
        if os.path.isfile(rr_path):
            try:
                with open(rr_path, "r", encoding="utf-8") as f:
                    state = json.load(f) or {}
            except Exception:
                state = {}
        idx = int(state.get(slug, 0)) % len(members)
        chosen = ""
        for step in range(len(members)):
            cand = members[(idx + step) % len(members)]
            if not self.check_resource_conflict(cand, date_str, start_str, end_str):
                chosen = cand
                state[slug] = (idx + step + 1) % len(members)
                break
        if not chosen:
            chosen = members[idx]
            state[slug] = (idx + 1) % len(members)
        try:
            tmp = f"{rr_path}.tmp.{os.getpid()}"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f)
            os.replace(tmp, rr_path)
        except OSError as exc:
            logger.warning(f"[Calendar] Round-Robin-Zustand konnte nicht gespeichert werden: {exc}")
        return chosen

    def book_public_slot(self, slug: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        email = str(payload.get("email") or "").strip()
        start = str(payload.get("start") or "").strip()
        end = str(payload.get("end") or "").strip()
        if not name or not start:
            raise ValueError("name und start erforderlich")
        bt = self.get_booking_type(slug)
        price = float(bt.get("price_eur") or 0)
        pay_ref = str(payload.get("payment_reference") or "").strip()
        if price > 0 and not pay_ref:
            raise ValueError(f"Bezahlung erforderlich ({price:.2f} EUR). Bitte Payment-Referenz bestaetigen.")
        d_iso = start[:10]
        day_evs = self.list_events(start_date=d_iso, end_date=d_iso, source="custom")
        booked_count = sum(1 for e in day_evs if f"Buchung ({slug})" in str(e.get("title") or ""))
        if booked_count >= int(bt.get("max_per_day") or 8):
            raise ValueError(f"Tageslimit ({bt.get('max_per_day')}) fuer '{slug}' am {d_iso} erreicht.")
        members = [str(m).strip() for m in (bt.get("team_members") or []) if str(m).strip()]
        assigned = self._next_round_robin_member(slug, members, d_iso, start, end) if members else ""
        answers = payload.get("answers") if isinstance(payload.get("answers"), dict) else {}
        ans_text = " | ".join(f"{k}: {v}" for k, v in answers.items() if str(v).strip())
        extra = []
        if assigned:
            extra.append(f"Zuweisung (Round-Robin): {assigned}")
        if price > 0:
            extra.append(f"Bezahlt: {price:.2f} EUR (Ref: {pay_ref})")
        if ans_text:
            extra.append(f"Fragebogen: {ans_text}")
        ev = self.create_event({
            "title": f"Buchung ({slug}): {name}",
            "start": start,
            "end": end,
            "date": d_iso,
            "time": start[11:16] if len(start) >= 16 else "09:00",
            "attendees": email,
            "resource": assigned,
            "allow_conflict": True,
            "category": "appointment",
            "notes": f"Oeffentliche Terminbuchung ueber Link '{slug}' von {name} ({email}). {payload.get('notes') or ''} {' | '.join(extra)}".strip(),
        })
        try:
            from backend.workflow_scheduler import dispatch_workflow_event
            dispatch_workflow_event(
                source="calendar",
                event_type="booking_created",
                title=ev["title"],
                summary=f"Gebucht von {name} ({email}) am {ev['date']} {ev['time']}",
                payload={"event_id": ev["id"], "slug": slug, "email": email},
                correlation_id=f"book-{ev['id']}",
            )
        except Exception as exc:
            logger.debug(f"[Calendar] Buchungs-Event-Dispatch uebersprungen: {exc}")
        return ev

    def push_event_to_source(self, src_id: str, ev: Dict[str, Any]) -> Dict[str, Any]:
        import base64
        import urllib.request

        src = next((s for s in self.list_sources() if s.get("id") == src_id), None)
        if not src:
            raise KeyError("source_not_found")
        prov = str(src.get("provider") or "").lower()

        from utils.safe_http import safe_http_request
        if prov == "caldav":
            target_url = f"{src['url'].rstrip('/')}/{ev['id']}.ics"
            ics = (
                "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Archon OS//CalDAV//DE\r\nBEGIN:VEVENT\r\n"
                f"UID:{ev['id']}@archon.local\r\nSUMMARY:{ev['title']}\r\n"
                f"DTSTART:{str(ev.get('start') or ev['date']).replace('-', '').replace(':', '')}\r\n"
                f"DTEND:{str(ev.get('end') or ev['date']).replace('-', '').replace(':', '')}\r\n"
                "END:VEVENT\r\nEND:VCALENDAR\r\n"
            ).encode("utf-8")
            headers = {"Content-Type": "text/calendar; charset=utf-8"}
            if src.get("username") and src.get("password"):
                tok = base64.b64encode(f"{src['username']}:{src['password']}".encode("utf-8")).decode("ascii")
                headers["Authorization"] = f"Basic {tok}"
            resp = safe_http_request(target_url, method="PUT", headers=headers, data=ics, timeout=12.0)
            return {"pushed": True, "provider": prov, "status_code": resp.get("status", 200)}

        if prov == "google_oauth":
            token = self._ensure_fresh_oauth_token(src)
            body = json.dumps({
                "summary": ev["title"],
                "description": ev.get("notes") or "",
                "location": ev.get("location") or ev.get("meeting_url") or "",
                "start": {"date": ev["date"]} if ev.get("all_day") else {"dateTime": f"{ev['start'][:16]}:00Z"},
                "end": {"date": ev["date"]} if ev.get("all_day") else {"dateTime": f"{(ev.get('end') or ev['start'])[:16]}:00Z"},
            }).encode("utf-8")
            resp = safe_http_request(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                method="POST",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                data=body,
                timeout=12.0,
            )
            return {"pushed": True, "provider": prov, "status_code": resp.get("status", 200)}

        if prov == "outlook_oauth":
            token = self._ensure_fresh_oauth_token(src)
            body = json.dumps({
                "subject": ev["title"],
                "body": {"contentType": "Text", "content": ev.get("notes") or ""},
                "start": {"dateTime": f"{ev['start'][:16]}:00", "timeZone": "Europe/Berlin"},
                "end": {"dateTime": f"{(ev.get('end') or ev['start'])[:16]}:00", "timeZone": "Europe/Berlin"},
            }).encode("utf-8")
            resp = safe_http_request(
                "https://graph.microsoft.com/v1.0/me/events",
                method="POST",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                data=body,
                timeout=12.0,
            )
            return {"pushed": True, "provider": prov, "status_code": resp.get("status", 200)}

        return {"pushed": False, "reason": "read_only_ics_provider"}

    # ── Ressourcen / Raeume ─────────────────────────────────────────────────
    def _resources_path(self) -> str:
        cfg = os.path.join(os.path.dirname(self.data_dir), "config")
        os.makedirs(cfg, exist_ok=True)
        return os.path.join(cfg, "calendar_resources.json")

    def list_resources(self) -> List[str]:
        p = self._resources_path()
        default_res = ["Konferenzraum A", "Konferenzraum B", "Beamer / Fahrzeug", "Team: Micha", "Team: Robert"]
        if not os.path.isfile(p):
            return default_res
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [str(x).strip() for x in data if str(x).strip()] if isinstance(data, list) else default_res
        except Exception:
            return default_res

    def save_resources(self, items: List[str]) -> List[str]:
        cleaned = [str(x).strip() for x in (items or []) if str(x).strip()]
        p = self._resources_path()
        tmp = f"{p}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
        return cleaned

    # ── Schulferien-API je Bundesland (mit lokalem Cache) ───────────────────
    def _school_cache_path(self) -> str:
        return os.path.join(self.data_dir, "school_holidays_cache.json")

    def _collect_school_holidays(self, start_date: Optional[str], end_date: Optional[str], state: str = "BY") -> List[Dict[str, Any]]:
        import urllib.request

        if not start_date or not end_date:
            return []
        st_code = (state or "BY").upper()[:2]
        try:
            win_s = datetime.date.fromisoformat(start_date[:10])
            win_e = datetime.date.fromisoformat(end_date[:10])
        except Exception:
            return []

        cache_path = self._school_cache_path()
        cache: Dict[str, Any] = {}
        if os.path.isfile(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cache = json.load(f) or {}
            except Exception:
                cache = {}

        now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
        years = sorted({win_s.year, win_e.year})
        cache_dirty = False
        periods: List[Dict[str, Any]] = []
        for yr in years:
            key = f"{st_code}_{yr}"
            entry = cache.get(key)
            if not entry or (now_ts - float(entry.get("fetched_at", 0))) > 30 * 86400:
                try:
                    url = f"https://ferien-api.de/api/v1/holidays/{st_code}/{yr}"
                    req = urllib.request.Request(url, headers={"User-Agent": "ArchonOS-Calendar/1.0"})
                    with urllib.request.urlopen(req, timeout=4) as resp:
                        rows = json.loads(resp.read().decode("utf-8"))
                    if isinstance(rows, list):
                        entry = {"fetched_at": now_ts, "periods": rows}
                        cache[key] = entry
                        cache_dirty = True
                except Exception as exc:
                    logger.debug(f"[Calendar] Feiertags-Abruf fuer {key} fehlgeschlagen: {exc}")
            if entry and isinstance(entry.get("periods"), list):
                periods.extend(entry["periods"])

        if cache_dirty:
            try:
                tmp = f"{cache_path}.tmp.{os.getpid()}"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(cache, f, ensure_ascii=False, indent=2)
                os.replace(tmp, cache_path)
            except OSError as exc:
                logger.warning(f"[Calendar] Feiertags-Cache konnte nicht gespeichert werden: {exc}")

        out: List[Dict[str, Any]] = []
        seen = set()
        for per in periods:
            try:
                ps = datetime.date.fromisoformat(str(per.get("start") or "")[:10])
                pe = datetime.date.fromisoformat(str(per.get("end") or "")[:10])
            except Exception:
                continue
            cur = max(ps, win_s)
            end_d = min(pe, win_e)
            name = str(per.get("name") or "Schulferien").title()
            while cur <= end_d:
                iso = cur.isoformat()
                k = f"{iso}_{name}"
                if k not in seen:
                    seen.add(k)
                    out.append({
                        "id": f"school_{st_code}_{iso}",
                        "title": f"Schulferien: {name} ({st_code})",
                        "date": iso,
                        "time": "",
                        "start": iso,
                        "end": iso,
                        "all_day": True,
                        "category": "school_holiday",
                        "source": "school_holiday",
                        "color": "#14b8a6",
                    })
                cur += datetime.timedelta(days=1)
        return out

    # ── OAuth2 Redirect-Flow & Token-Refresh (Google / Microsoft 365) ───────
    _oauth_states: Dict[str, Dict[str, Any]] = {}

    def _oauth_cfg_path(self) -> str:
        cfg = os.path.join(os.path.dirname(self.data_dir), "config")
        os.makedirs(cfg, exist_ok=True)
        return os.path.join(cfg, "calendar_oauth.json")

    def get_oauth_config(self, mask_secret: bool = True) -> Dict[str, Any]:
        p = self._oauth_cfg_path()
        data: Dict[str, Any] = {"google": {"client_id": "", "client_secret": ""}, "outlook": {"client_id": "", "client_secret": ""}}
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data.update(loaded)
            except (OSError, ValueError) as exc:
                logger.warning(f"[Calendar] Kalender-Einstellungen {p} nicht lesbar: {exc}")
        if mask_secret:
            out = {}
            for k, v in data.items():
                if isinstance(v, dict):
                    out[k] = {
                        "client_id": v.get("client_id") or "",
                        "has_secret": bool(v.get("client_secret")),
                    }
            return out
        return data

    def save_oauth_config(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        cur = self.get_oauth_config(mask_secret=False)
        for prov in ("google", "outlook"):
            if isinstance(payload.get(prov), dict):
                entry = cur.setdefault(prov, {})
                if "client_id" in payload[prov]:
                    entry["client_id"] = str(payload[prov]["client_id"] or "").strip()
                if payload[prov].get("client_secret"):
                    entry["client_secret"] = str(payload[prov]["client_secret"]).strip()
        p = self._oauth_cfg_path()
        tmp = f"{p}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
        return self.get_oauth_config(mask_secret=True)

    def build_oauth_authorize_url(self, provider: str, redirect_uri: str, source_name: str = "") -> str:
        import urllib.parse

        prov = "google" if "google" in provider else "outlook"
        cfg = self.get_oauth_config(mask_secret=False).get(prov) or {}
        cid = str(cfg.get("client_id") or "").strip()
        if not cid:
            raise ValueError(f"OAuth client_id fuer {prov} fehlt in Settings -> Kalender.")
        state = uuid.uuid4().hex
        self._oauth_states[state] = {
            "provider": prov,
            "redirect_uri": redirect_uri,
            "source_name": source_name or ("Google Calendar" if prov == "google" else "Microsoft 365"),
            "created_at": datetime.datetime.now(datetime.timezone.utc).timestamp(),
        }
        if prov == "google":
            qs = urllib.parse.urlencode({
                "client_id": cid,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "https://www.googleapis.com/auth/calendar",
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
            })
            return f"https://accounts.google.com/o/oauth2/v2/auth?{qs}"
        qs = urllib.parse.urlencode({
            "client_id": cid,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "offline_access Calendars.ReadWrite",
            "state": state,
        })
        return f"https://login.microsoftonline.com/common/oauth2/v2.0/authorize?{qs}"

    def complete_oauth_callback(self, code: str, state: str) -> Dict[str, Any]:
        import urllib.parse
        import urllib.request

        st = self._oauth_states.pop(state, None)
        if not st:
            raise ValueError("invalid_or_expired_oauth_state")
        prov = st["provider"]
        cfg = self.get_oauth_config(mask_secret=False).get(prov) or {}
        token_url = (
            "https://oauth2.googleapis.com/token"
            if prov == "google"
            else "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        )
        form = urllib.parse.urlencode({
            "client_id": cfg.get("client_id") or "",
            "client_secret": cfg.get("client_secret") or "",
            "code": code,
            "redirect_uri": st["redirect_uri"],
            "grant_type": "authorization_code",
        }).encode("utf-8")
        req = urllib.request.Request(token_url, data=form, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            tok = json.loads(resp.read().decode("utf-8"))
        expires_in = int(tok.get("expires_in") or 3600)
        expires_at = datetime.datetime.now(datetime.timezone.utc).timestamp() + expires_in
        src = self.upsert_source({
            "name": st["source_name"],
            "provider": "google_oauth" if prov == "google" else "outlook_oauth",
            "url": "https://www.googleapis.com/calendar/v3/calendars/primary/events" if prov == "google" else "https://graph.microsoft.com/v1.0/me/events",
            "access_token": tok.get("access_token") or "",
            "refresh_token": tok.get("refresh_token") or "",
            "expires_at": expires_at,
            "two_way_sync": True,
            "enabled": True,
        })
        return src

    def _ensure_fresh_oauth_token(self, src: Dict[str, Any]) -> str:
        import urllib.parse
        import urllib.request

        token = str(src.get("access_token") or src.get("password") or "").strip()
        refresh = str(src.get("refresh_token") or "").strip()
        expires_at = float(src.get("expires_at") or 0)
        now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
        if refresh and expires_at and (now_ts >= expires_at - 60):
            prov = "google" if src.get("provider") == "google_oauth" else "outlook"
            cfg = self.get_oauth_config(mask_secret=False).get(prov) or {}
            token_url = (
                "https://oauth2.googleapis.com/token"
                if prov == "google"
                else "https://login.microsoftonline.com/common/oauth2/v2.0/token"
            )
            form = urllib.parse.urlencode({
                "client_id": cfg.get("client_id") or "",
                "client_secret": cfg.get("client_secret") or "",
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            }).encode("utf-8")
            req = urllib.request.Request(token_url, data=form, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
            with urllib.request.urlopen(req, timeout=12) as resp:
                tok = json.loads(resp.read().decode("utf-8"))
            if tok.get("access_token"):
                token = str(tok["access_token"])
                new_exp = now_ts + int(tok.get("expires_in") or 3600)
                with self._lock:
                    sources = self.list_sources()
                    for item in sources:
                        if item.get("id") == src.get("id"):
                            item["access_token"] = token
                            item["expires_at"] = new_exp
                            if tok.get("refresh_token"):
                                item["refresh_token"] = tok["refresh_token"]
                            break
                    self.save_sources(sources)
        if not token:
            raise ValueError(f"{src.get('provider')}_token_missing")
        return token

    # ── Team-Verfuegbarkeit (Find a Time) ────────────────────────────────────
    def find_team_availability(
        self,
        resources: List[str],
        date_str: str,
        duration_min: int = 30,
        company_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        target_d = (date_str or datetime.date.today().isoformat())[:10]
        targets = [r.strip() for r in (resources or []) if r and r.strip()]
        if not targets:
            targets = self.list_resources()
        day_events = self.list_events(start_date=target_d, end_date=target_d, company_id=company_id)

        def _to_min(hhmm: str) -> Optional[int]:
            if ":" not in (hhmm or ""):
                return None
            h, m = hhmm[:5].split(":")
            return int(h) * 60 + int(m)

        busy_map: Dict[str, List[Dict[str, str]]] = {t: [] for t in targets}
        for t in targets:
            tl = t.lower()
            for ev in day_events:
                if ev.get("source") in ("holiday", "school_holiday") or ev.get("all_day"):
                    continue
                match = tl in str(ev.get("resource") or "").lower() or tl in str(ev.get("attendees") or "").lower()
                if not match:
                    continue
                st_t = ev.get("time") or (str(ev.get("start") or "")[11:16] if "T" in str(ev.get("start") or "") else "")
                en_t = str(ev.get("end") or "")[11:16] if "T" in str(ev.get("end") or "") else ""
                s_min = _to_min(st_t)
                if s_min is None:
                    continue
                e_min = _to_min(en_t) or (s_min + 60)
                busy_map[t].append({
                    "start": f"{s_min // 60:02d}:{s_min % 60:02d}",
                    "end": f"{e_min // 60:02d}:{e_min % 60:02d}",
                    "title": ev.get("title") or "",
                })

        common_free: List[Dict[str, str]] = []
        for s_min in range(8 * 60, 18 * 60 - duration_min + 1, 30):
            e_min = s_min + duration_min
            conflict = False
            for t in targets:
                for b in busy_map[t]:
                    bs = _to_min(b["start"]) or 0
                    be = _to_min(b["end"]) or 0
                    if not (e_min <= bs or s_min >= be):
                        conflict = True
                        break
                if conflict:
                    break
            if not conflict:
                common_free.append({
                    "start": f"{target_d}T{s_min // 60:02d}:{s_min % 60:02d}",
                    "end": f"{target_d}T{e_min // 60:02d}:{e_min % 60:02d}",
                    "label": f"{s_min // 60:02d}:{s_min % 60:02d} – {e_min // 60:02d}:{e_min % 60:02d}",
                })

        return {"date": target_d, "duration_min": duration_min, "busy": busy_map, "common_free_slots": common_free}

    # ── Quick-Add Parser (Natuerliche Sprache DE/EN) ─────────────────────────
    def parse_and_create_quick_add(self, text: str, company_id: Optional[str] = None) -> Dict[str, Any]:
        import re

        raw = str(text or "").strip()
        if not raw:
            raise ValueError("Text fuer Quick-Add fehlt.")
        low = raw.lower()
        today = datetime.date.today()
        target_date = today

        if re.search(r"\b(uebermorgen|übermorgen)\b", low):
            target_date = today + datetime.timedelta(days=2)
        elif re.search(r"\b(morgen|tomorrow)\b", low):
            target_date = today + datetime.timedelta(days=1)
        elif re.search(r"\b(heute|today)\b", low):
            target_date = today
        else:
            wd_map = {"montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3, "freitag": 4, "samstag": 5, "sonntag": 6}
            for wname, widx in wd_map.items():
                if re.search(rf"\b{wname}\b", low):
                    delta = (widx - today.weekday()) % 7
                    if delta == 0 or "naechst" in low or "nächst" in low:
                        delta = delta or 7
                    target_date = today + datetime.timedelta(days=delta)
                    break
            m_iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", raw)
            m_de = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})?\b", raw)
            if m_iso:
                target_date = datetime.date.fromisoformat(m_iso.group(1))
            elif m_de:
                dd, mm = int(m_de.group(1)), int(m_de.group(2))
                yy = int(m_de.group(3)) if m_de.group(3) else today.year
                target_date = datetime.date(yy, mm, dd)

        hour, minute = 9, 0
        has_time = False
        m_time = re.search(r"\b(?:um\s+)?(\d{1,2})(?:[:.](\d{2}))?\s*(?:uhr|h)?\b", low)
        if m_time and (m_time.group(2) is not None or "uhr" in m_time.group(0) or re.search(r"\bum\s+\d", low)):
            hh = int(m_time.group(1))
            mm = int(m_time.group(2) or 0)
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                hour, minute, has_time = hh, mm, True

        duration_min = 60
        m_dur_m = re.search(r"\b(\d{1,3})\s*(?:min|minuten|m)\b", low)
        m_dur_h = re.search(r"\b(\d{1,2})\s*(?:std|stunden|h)\b", low)
        if m_dur_m:
            duration_min = max(15, min(480, int(m_dur_m.group(1))))
        elif m_dur_h:
            duration_min = max(15, min(480, int(m_dur_h.group(1)) * 60))

        cat = "appointment"
        if any(k in low for k in ("fokus", "deep work", "deep-work", "focus")):
            cat = "focus"
        elif any(k in low for k in ("frist", "deadline", "abgabe")):
            cat = "deadline"

        cleaned = re.sub(
            r"\b(heute|morgen|uebermorgen|übermorgen|tomorrow|today|nächsten|naechsten|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|um)\b",
            "",
            raw,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\b20\d{2}-\d{2}-\d{2}\b|\b\d{1,2}\.\d{1,2}\.(?:20\d{2})?\b", "", cleaned)
        cleaned = re.sub(r"\b\d{1,2}(?:[:.]\d{2})?\s*(?:uhr|h)?\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b\d{1,3}\s*(?:min|minuten|m|std|stunden|h)\b", "", cleaned, flags=re.IGNORECASE)
        title = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.-:") or raw

        d_iso = target_date.isoformat()
        t_str = f"{hour:02d}:{minute:02d}"
        start_dt = datetime.datetime.combine(target_date, datetime.time(hour, minute))
        end_dt = start_dt + datetime.timedelta(minutes=duration_min)
        return self.create_event({
            "title": title,
            "date": d_iso,
            "time": t_str if has_time else "09:00",
            "start": start_dt.isoformat(timespec="minutes"),
            "end": end_dt.isoformat(timespec="minutes"),
            "all_day": False,
            "category": cat,
        }, company_id=company_id)

    # ── Konfliktpruefung fuer Raeume / Ressourcen ────────────────────────────
    def check_resource_conflict(
        self,
        resource: str,
        date_str: str,
        start_str: str,
        end_str: str,
        exclude_id: str = "",
        company_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        res_l = str(resource or "").strip().lower()
        d_iso = str(date_str or "")[:10]
        if not res_l or not d_iso:
            return []

        def _parse_min(val: str, fallback: Optional[int] = None) -> Optional[int]:
            t = val[11:16] if "T" in val else val[:5]
            if ":" not in t:
                return fallback
            try:
                hh, mm = t.split(":")
                return int(hh) * 60 + int(mm)
            except Exception:
                return fallback

        s_min = _parse_min(start_str)
        if s_min is None:
            return []
        e_min = _parse_min(end_str, s_min + 60) or (s_min + 60)
        if e_min <= s_min:
            e_min = s_min + 60

        day_evs = self.list_events(start_date=d_iso, end_date=d_iso, source="custom", company_id=company_id)
        conflicts: List[Dict[str, Any]] = []
        for ev in day_evs:
            if ev.get("id") == exclude_id or ev.get("parent_id") == exclude_id:
                continue
            if str(ev.get("resource") or "").strip().lower() != res_l or ev.get("all_day"):
                continue
            es = _parse_min(ev.get("time") or str(ev.get("start") or ""))
            if es is None:
                continue
            ee = _parse_min(str(ev.get("end") or ""), es + 60) or (es + 60)
            if ee <= es:
                ee = es + 60
            if s_min < ee and e_min > es:
                conflicts.append(ev)
        return conflicts

    # ── Push-Webhooks (Google Watch & Microsoft Graph Subscriptions) ────────
    def register_webhook_watch(self, src_id: str, webhook_url: str) -> Dict[str, Any]:
        import urllib.request

        sources = self.list_sources()
        src = next((s for s in sources if s.get("id") == src_id), None)
        if not src:
            raise KeyError("source_not_found")
        prov = str(src.get("provider") or "")
        token = self._ensure_fresh_oauth_token(src)
        watch_id = f"archon_{src_id}_{uuid.uuid4().hex[:8]}"

        if prov == "google_oauth":
            body = json.dumps({"id": watch_id, "type": "web_hook", "address": webhook_url}).encode("utf-8")
            req = urllib.request.Request(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events/watch",
                data=body,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            exp = data.get("expiration")
        elif prov == "outlook_oauth":
            exp_dt = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
            body = json.dumps({
                "changeType": "created,updated,deleted",
                "notificationUrl": webhook_url,
                "resource": "me/events",
                "expirationDateTime": exp_dt,
                "clientState": watch_id,
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://graph.microsoft.com/v1.0/subscriptions",
                data=body,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            watch_id = str(data.get("id") or watch_id)
            exp = data.get("expirationDateTime") or exp_dt
        else:
            raise ValueError("Webhook Watch wird nur fuer google_oauth und outlook_oauth unterstuetzt.")

        with self._lock:
            all_s = self.list_sources()
            for item in all_s:
                if item.get("id") == src_id:
                    item["watch_id"] = watch_id
                    item["watch_expires_at"] = exp
                    break
            self.save_sources(all_s)
        return {"watch_id": watch_id, "expires_at": exp, "provider": prov}

    def handle_webhook_push(self, channel_id: str = "", client_state: str = "") -> Dict[str, Any]:
        sources = self.list_sources()
        matched = [
            s for s in sources
            if s.get("enabled") and (
                (channel_id and s.get("watch_id") == channel_id)
                or (client_state and s.get("watch_id") == client_state)
                or s.get("provider") in ("google_oauth", "outlook_oauth")
            )
        ]
        synced = []
        for s in matched:
            try:
                res = self.sync_source(s["id"])
                synced.append({"source_id": s["id"], "imported": res.get("imported", 0)})
            except Exception as exc:
                synced.append({"source_id": s["id"], "error": str(exc)})
        try:
            from backend.workflow_scheduler import dispatch_workflow_event
            dispatch_workflow_event(
                source="calendar",
                event_type="webhook_synced",
                title=f"Push-Webhook Sync ({len(synced)} Quelle(n))",
                summary=str(synced),
                payload={"synced": synced},
            )
        except Exception as exc:
            logger.debug(f"[Calendar] Push-Webhook Event-Dispatch uebersprungen: {exc}")
        return {"synced": synced}

    # ── Eingehende .ics-RSVP-Antworten (METHOD:REPLY / IMAP) ────────────────
    def process_rsvp_ics_text(self, ics_text: str) -> List[Dict[str, Any]]:
        import re

        txt = str(ics_text or "").replace("\r\n ", "").replace("\n ", "")
        if "METHOD:REPLY" not in txt.upper() and "PARTSTAT=" not in txt.upper():
            return []
        uid_m = re.search(r"UID:([^\r\n]+)", txt, re.IGNORECASE)
        if not uid_m:
            return []
        uid_raw = uid_m.group(1).strip()
        ev_id = uid_raw.replace("archon-", "").split("@")[0]

        updates: List[Dict[str, Any]] = []
        for m in re.finditer(r"ATTENDEE([^:\r\n]*):mailto:([^\r\n]+)", txt, re.IGNORECASE):
            params, email = m.group(1).upper(), m.group(2).strip().lower()
            p_m = re.search(r"PARTSTAT=(ACCEPTED|DECLINED|TENTATIVE|NEEDS-ACTION)", params)
            partstat = p_m.group(1).lower() if p_m else "pending"
            if partstat == "needs-action":
                partstat = "pending"
            try:
                res = self.update_rsvp(ev_id, email=email, status=partstat)
                updates.append({"event_id": ev_id, "email": email, "status": partstat, "rsvp_status": res.get("rsvp_status")})
            except KeyError as exc:
                logger.debug(f"[Calendar] RSVP-Event {ev_id} nicht gefunden: {exc}")
        return updates

    def poll_imap_rsvp_replies(self) -> Dict[str, Any]:
        import email as py_email
        import imaplib

        host = os.environ.get("IMAP_HOST", "").strip()
        user = os.environ.get("IMAP_USER", "").strip()
        pw = os.environ.get("IMAP_PASS", "").strip()
        port = int(os.environ.get("IMAP_PORT", "993") or 993)

        cfg_path = os.path.join(os.path.dirname(self.data_dir), "config", "email_config.json")
        if (not host or not user or not pw) and os.path.isfile(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f) or {}
                host = host or str(cfg.get("imap_host") or "")
                user = user or str(cfg.get("imap_user") or cfg.get("email") or "")
                pw = pw or str(cfg.get("imap_pass") or cfg.get("password") or "")
            except (OSError, ValueError) as exc:
                logger.warning(f"[Calendar] IMAP-Konfiguration konnte nicht gelesen werden: {exc}")

        if not host or not user or not pw:
            return {"polled": 0, "updated": [], "reason": "imap_not_configured"}

        all_updates: List[Dict[str, Any]] = []
        polled = 0
        with imaplib.IMAP4_SSL(host, port) as imap:
            imap.login(user, pw)
            imap.select("INBOX")
            _, data = imap.search(None, "UNSEEN")
            ids = (data[0] or b"").split()[-25:]
            for msg_id in ids:
                polled += 1
                _, msg_data = imap.fetch(msg_id, "(RFC822)")
                if not msg_data or not isinstance(msg_data[0], tuple):
                    continue
                msg = py_email.message_from_bytes(msg_data[0][1])
                for part in msg.walk():
                    ctype = part.get_content_type()
                    fname = str(part.get_filename() or "").lower()
                    if ctype == "text/calendar" or fname.endswith(".ics"):
                        payload_b = part.get_payload(decode=True)
                        if payload_b:
                            all_updates.extend(self.process_rsvp_ics_text(payload_b.decode("utf-8", errors="ignore")))
        return {"polled": polled, "updated": all_updates}

    # ── Vollstaendige NL-Kalenderabfragen (Lesen, Frei/Belegt, Verschieben) ──
    def handle_calendar_nl_query(self, text: str, company_id: Optional[str] = None) -> str:
        import re

        raw = str(text or "").strip()
        low = raw.lower()
        today = datetime.date.today()

        # 1. Freie Slots abfragen ("wann ... frei", "freie zeit")
        if ("wann" in low and "frei" in low) or "freie zeit" in low or "freier slot" in low:
            dur = 60
            m_h = re.search(r"(\d{1,2})\s*(?:std|stunde|stunden|h)\b", low)
            m_m = re.search(r"(\d{1,3})\s*(?:min|minuten)\b", low)
            if m_h:
                dur = max(15, min(240, int(m_h.group(1)) * 60))
            elif m_m:
                dur = max(15, min(240, int(m_m.group(1))))
            days = 10 if ("naechste" in low or "nächste" in low or "woche" in low) else 5
            slots = self.find_focus_slots(duration_min=dur, days_ahead=days)[:6]
            if not slots:
                return f"Keine freien {dur}-Minuten-Slots in den naechsten {days} Tagen gefunden."
            lines = "\n".join(f"- **{s['date']}**: {s['start'][11:16]} – {s['end'][11:16]} Uhr" for s in slots)
            return f"Hier sind freie **{dur}-Minuten-Zeitfenster**:\n{lines}"

        # 2. Termine auflisten ("welche termine", "was steht an", "agenda")
        if any(k in low for k in ("welche termine", "was steht an", "meine termine", "agenda", "terminplan")):
            s_d = today + datetime.timedelta(days=1) if "morgen" in low else today
            e_d = s_d + datetime.timedelta(days=7 if "woche" in low else 0)
            evs = self.list_events(start_date=s_d.isoformat(), end_date=e_d.isoformat(), company_id=company_id)
            evs = [e for e in evs if e.get("source") not in ("holiday", "school_holiday")]
            if not evs:
                return f"Keine Termine zwischen {s_d.isoformat()} und {e_d.isoformat()}."
            lines = "\n".join(f"- **{e['date']} {e.get('time') or 'Ganztaegig'}**: {e['title']}" for e in evs[:15])
            return f"Deine Termine ({s_d.isoformat()} bis {e_d.isoformat()}):\n{lines}"

        # 3. Termin verschieben ("verschiebe ... auf ...")
        if low.startswith("verschieb") or " verschieben" in low:
            m_new_t = re.search(r"auf\s+(?:(heute|morgen|uebermorgen|übermorgen)\s+)?(?:um\s+)?(\d{1,2})(?:[:.](\d{2}))?\s*(?:uhr)?", low)
            if not m_new_t:
                return "Bitte Zielzeit angeben, z. B.: `Verschiebe Call mit Max auf morgen 16:30`."
            new_d = today
            if m_new_t.group(1) == "morgen":
                new_d = today + datetime.timedelta(days=1)
            elif m_new_t.group(1) in ("uebermorgen", "übermorgen"):
                new_d = today + datetime.timedelta(days=2)
            new_t = f"{int(m_new_t.group(2)):02d}:{int(m_new_t.group(3) or 0):02d}"

            all_custom = self.list_events(
                start_date=today.isoformat(),
                end_date=(today + datetime.timedelta(days=30)).isoformat(),
                source="custom",
                company_id=company_id,
            )
            search_part = re.sub(r"^verschiebe\s+(?:meinen\s+|den\s+)?", "", low.split(" auf ")[0]).strip()
            search_tokens = [w for w in re.split(r"[\s\-]+", search_part) if len(w) >= 2 and w not in ("uhr", "termin", "den", "das")]
            match_ev = next(
                (
                    e for e in all_custom
                    if any(tok in f"{e.get('title', '')} {e.get('time', '')}".lower() for tok in search_tokens)
                ),
                None,
            )
            if not match_ev:
                return f"Keinen passenden Termin fuer '{search_part}' gefunden."
            if not m_new_t.group(1):
                new_d = datetime.date.fromisoformat(match_ev["date"][:10])
            start_dt = datetime.datetime.combine(new_d, datetime.time(int(new_t[:2]), int(new_t[3:5])))
            end_dt = start_dt + datetime.timedelta(minutes=60)
            target_id = match_ev.get("parent_id") or match_ev["id"]
            updated = self.update_event(
                target_id,
                {
                    "date": new_d.isoformat(),
                    "time": new_t,
                    "start": start_dt.isoformat(timespec="minutes"),
                    "end": end_dt.isoformat(timespec="minutes"),
                    **({"occurrence_date": match_ev["date"]} if match_ev.get("parent_id") else {}),
                },
                company_id=company_id,
            )
            return f"Termin verschoben: **{updated['title']}** neu am **{new_d.isoformat()}** um **{new_t} Uhr**."

        # 4. Standard: Neuen Termin per Quick-Add anlegen
        ev = self.parse_and_create_quick_add(raw, company_id=company_id)
        return f"Termin im Operations-Kalender angelegt: **{ev['title']}** am **{ev['date']}** um **{ev.get('time') or '09:00'} Uhr**."

    def _auto_writeback(self, ev: Dict[str, Any]) -> None:
        for s in self.list_sources():
            if s.get("enabled") and s.get("two_way_sync"):
                try:
                    self.push_event_to_source(s["id"], ev)
                except Exception as exc:
                    logger.warning(f"[Calendar] Two-Way-Writeback fuer Quelle '{s.get('id')}' fehlgeschlagen: {exc}")

    def list_events(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        source: str = "all",
        company_id: Optional[str] = None,
        holiday_state: str = "BY",
    ) -> List[Dict[str, Any]]:
        cid = self._active_cid(company_id)
        events: List[Dict[str, Any]] = []
        if source in ("all", "custom"):
            for ev in self._load_custom():
                if ev.get("company_id") in (None, "", cid) or company_id is None:
                    events.extend(self._expand_recurring(ev, start_date, end_date))
        if source in ("all", "kanban"):
            events.extend(self._collect_kanban_deadlines())
        if source in ("all", "erp"):
            events.extend(self._collect_erp_due_dates(company_id=cid))
        if source in ("all", "n8n"):
            events.extend(self._collect_n8n_routines(start_date, end_date))
        if source in ("all", "workflow"):
            events.extend(self._collect_workflow_schedules())
        if source in ("all", "external"):
            events.extend(self._load_external_events())
        if source in ("all", "holiday"):
            events.extend(self._collect_german_holidays(start_date, end_date, state=holiday_state))
        if source in ("all", "school_holiday"):
            events.extend(self._collect_school_holidays(start_date, end_date, state=holiday_state))

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


    # ── Hintergrund-Wartung (IMAP-RSVP & Webhook-Subscription-Renewal) ──────
    _maint_started: bool = False

    def run_maintenance_cycle(self) -> Dict[str, Any]:
        imap_res: Dict[str, Any] = {"polled": 0, "updated": []}
        try:
            imap_res = self.poll_imap_rsvp_replies()
        except Exception as exc:
            imap_res = {"error": str(exc)}

        renewed: List[Dict[str, Any]] = []
        now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
        for src in self.list_sources():
            if not src.get("enabled") or not src.get("watch_id"):
                continue
            exp_raw = src.get("watch_expires_at")
            exp_ts = 0.0
            try:
                if isinstance(exp_raw, (int, float)) or (isinstance(exp_raw, str) and exp_raw.isdigit()):
                    val = float(exp_raw)
                    exp_ts = val / 1000.0 if val > 1e12 else val
                elif isinstance(exp_raw, str) and exp_raw:
                    exp_ts = datetime.datetime.fromisoformat(exp_raw.replace("Z", "+00:00")).timestamp()
            except Exception:
                exp_ts = 0.0
            if exp_ts and (exp_ts - now_ts) < 12 * 3600:
                try:
                    base_url = os.environ.get("ARCHON_PUBLIC_URL", "http://localhost:8501").rstrip("/")
                    res = self.register_webhook_watch(src["id"], f"{base_url}/api/v1/calendar/webhooks/push")
                    renewed.append({"source_id": src["id"], **res})
                except Exception as exc:
                    renewed.append({"source_id": src["id"], "error": str(exc)})
        return {"imap": imap_res, "webhooks_renewed": renewed}

    def start_background_maintenance(self, interval_sec: int = 900) -> None:
        import time as _t

        if OperationsCalendarManager._maint_started:
            return
        OperationsCalendarManager._maint_started = True

        def _loop():
            _t.sleep(45)
            while True:
                try:
                    self.run_maintenance_cycle()
                except Exception as exc:
                    logger.warning(f"[Calendar] Wartungszyklus fehlgeschlagen: {exc}")
                _t.sleep(max(60, interval_sec))

        t = threading.Thread(target=_loop, name="calendar-maintenance", daemon=True)
        t.start()


operations_calendar = OperationsCalendarManager()
