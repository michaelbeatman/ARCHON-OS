"""
backend/workflow_scheduler.py — Cron- & Watchdog-Workflow-Scheduler (M102b)

Verwaltet zeitgesteuerte (Cron mit Startzeitpunkt, Endzeitpunkt, Start-/Endbedingungen)
sowie Watchdog-getriggerte Workflow-Automationen in SQLite WAL (`data/workflow_schedules.db`).
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEDULES_DB_PATH = os.path.join(WORKSPACE_DIR, "data", "workflow_schedules.db")


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(SCHEDULES_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(SCHEDULES_DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_schedules_db() -> None:
    conn = _get_conn()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_schedules (
                id TEXT PRIMARY KEY,
                template_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                trigger_type TEXT NOT NULL DEFAULT 'cron',
                cron_expr TEXT NOT NULL DEFAULT '',
                start_at TEXT DEFAULT '',
                end_at TEXT DEFAULT '',
                start_condition TEXT NOT NULL DEFAULT 'always',
                end_condition TEXT NOT NULL DEFAULT 'none',
                max_runs INTEGER DEFAULT NULL,
                run_count INTEGER NOT NULL DEFAULT 0,
                watchdog_keyword TEXT DEFAULT '',
                inputs_json TEXT NOT NULL DEFAULT '{}',
                n8n_webhook_url TEXT DEFAULT '',
                last_run_at TEXT DEFAULT '',
                next_run_at TEXT DEFAULT '',
                last_run_id TEXT DEFAULT '',
                last_status TEXT DEFAULT 'idle',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_events (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                correlation_id TEXT DEFAULT '',
                matched_schedule_ids_json TEXT NOT NULL DEFAULT '[]',
                triggered_run_ids_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'received',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _init_policies_table() -> None:
    conn = _get_conn()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS event_bus_policies (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                policy TEXT NOT NULL DEFAULT 'allow',
                max_per_min INTEGER NOT NULL DEFAULT 20,
                note TEXT DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _expand_cron_field(expr: str, min_v: int, max_v: int) -> Set[int]:
    out: Set[int] = set()
    for part in str(expr or "*").split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        if "/" in part:
            base, step_str = part.split("/", 1)
            step = max(1, int(step_str))
        else:
            base = part
        if base == "*":
            lo, hi = min_v, max_v
        elif "-" in base:
            a, b = base.split("-", 1)
            lo, hi = max(min_v, int(a)), min(max_v, int(b))
        else:
            val = int(base)
            lo, hi = val, val
        for v in range(lo, hi + 1, step):
            if min_v <= v <= max_v:
                out.add(v)
    return out or set(range(min_v, max_v + 1))


def parse_cron_next(cron_expr: str, after_dt: Optional[datetime] = None) -> Optional[str]:
    raw = (cron_expr or "").strip()
    if not raw:
        return None
    aliases = {
        "@every_5m": "*/5 * * * *",
        "@every_15m": "*/15 * * * *",
        "@hourly": "0 * * * *",
        "@daily": "0 8 * * *",
        "@weekly": "0 8 * * 1",
    }
    raw = aliases.get(raw.lower(), raw)
    parts = raw.split()
    if len(parts) != 5:
        return None
    try:
        mins = _expand_cron_field(parts[0], 0, 59)
        hours = _expand_cron_field(parts[1], 0, 23)
        doms = _expand_cron_field(parts[2], 1, 31)
        months = _expand_cron_field(parts[3], 1, 12)
        dows = _expand_cron_field(parts[4], 0, 6)
    except Exception:
        return None

    base = (after_dt or datetime.now(timezone.utc)).replace(second=0, microsecond=0) + timedelta(minutes=1)
    # Maximal 366 Tage vorausschauen (527.040 Minuten, aber stunden-/tageweise springen)
    cur = base
    limit = base + timedelta(days=366)
    while cur <= limit:
        if cur.month not in months:
            cur = (cur.replace(day=1, hour=0, minute=0) + timedelta(days=32)).replace(day=1, hour=0, minute=0)
            continue
        # Python weekday: Mon=0..Sun=6 -> Cron: Sun=0..Sat=6
        cron_dow = (cur.weekday() + 1) % 7
        if cur.day not in doms or cron_dow not in dows:
            cur = (cur + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if cur.hour not in hours:
            cur = (cur + timedelta(hours=1)).replace(minute=0)
            continue
        if cur.minute in mins:
            return cur.isoformat()
        cur += timedelta(minutes=1)
    return None


def _parse_iso(val: Optional[str]) -> Optional[datetime]:
    txt = (val or "").strip()
    if not txt:
        return None
    try:
        dt = datetime.fromisoformat(txt.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["enabled"] = bool(d.get("enabled"))
    try:
        d["inputs"] = json.loads(d.pop("inputs_json", "{}") or "{}")
    except Exception:
        d["inputs"] = {}
    return d


def list_schedules(template_id: Optional[str] = None) -> List[Dict[str, Any]]:
    init_schedules_db()
    conn = _get_conn()
    try:
        if template_id:
            rows = conn.execute(
                "SELECT * FROM workflow_schedules WHERE template_id = ? ORDER BY created_at DESC",
                (template_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM workflow_schedules ORDER BY created_at DESC").fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def upsert_schedule(payload: Dict[str, Any]) -> Dict[str, Any]:
    init_schedules_db()
    template_id = str(payload.get("template_id") or "").strip()
    if not template_id:
        raise ValueError("template_id_required")

    sid = str(payload.get("id") or f"sched-{uuid.uuid4().hex[:8]}").strip()
    trigger_type = str(payload.get("trigger_type") or "cron").strip()
    if trigger_type not in {"cron", "watchdog", "cron_and_watchdog", "inbox", "research", "boardroom", "calendar", "approval", "any_event"}:
        trigger_type = "cron"

    cron_expr = str(payload.get("cron_expr") or "").strip()
    start_at = str(payload.get("start_at") or "").strip()
    end_at = str(payload.get("end_at") or "").strip()
    start_condition = str(payload.get("start_condition") or "always").strip()
    end_condition = str(payload.get("end_condition") or "none").strip()
    max_runs_raw = payload.get("max_runs")
    max_runs = int(max_runs_raw) if max_runs_raw not in (None, "", 0, "0") else None
    enabled = 1 if payload.get("enabled", True) else 0
    inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}

    now = datetime.now(timezone.utc)
    start_dt = _parse_iso(start_at)
    anchor = start_dt if (start_dt and start_dt > now) else now
    next_run = parse_cron_next(cron_expr, anchor - timedelta(minutes=1)) if (enabled and cron_expr and "cron" in trigger_type) else ""

    conn = _get_conn()
    try:
        existing = conn.execute("SELECT run_count, created_at FROM workflow_schedules WHERE id = ?", (sid,)).fetchone()
        run_count = int(existing["run_count"]) if existing else 0
        created_at = existing["created_at"] if existing else now.isoformat()
        conn.execute(
            """
            INSERT INTO workflow_schedules (
                id, template_id, title, enabled, trigger_type, cron_expr,
                start_at, end_at, start_condition, end_condition, max_runs, run_count,
                watchdog_keyword, inputs_json, n8n_webhook_url, next_run_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                template_id=excluded.template_id,
                title=excluded.title,
                enabled=excluded.enabled,
                trigger_type=excluded.trigger_type,
                cron_expr=excluded.cron_expr,
                start_at=excluded.start_at,
                end_at=excluded.end_at,
                start_condition=excluded.start_condition,
                end_condition=excluded.end_condition,
                max_runs=excluded.max_runs,
                watchdog_keyword=excluded.watchdog_keyword,
                inputs_json=excluded.inputs_json,
                n8n_webhook_url=excluded.n8n_webhook_url,
                next_run_at=excluded.next_run_at
            """,
            (
                sid,
                template_id,
                str(payload.get("title") or template_id).strip(),
                enabled,
                trigger_type,
                cron_expr,
                start_at,
                end_at,
                start_condition,
                end_condition,
                max_runs,
                run_count,
                str(payload.get("watchdog_keyword") or "").strip(),
                json.dumps(inputs, ensure_ascii=False),
                str(payload.get("n8n_webhook_url") or "").strip(),
                next_run or "",
                created_at,
            ),
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_events (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                correlation_id TEXT DEFAULT '',
                matched_schedule_ids_json TEXT NOT NULL DEFAULT '[]',
                triggered_run_ids_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'received',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        row = conn.execute("SELECT * FROM workflow_schedules WHERE id = ?", (sid,)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def delete_schedule(schedule_id: str) -> bool:
    init_schedules_db()
    conn = _get_conn()
    try:
        cur = conn.execute("DELETE FROM workflow_schedules WHERE id = ?", (schedule_id,))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_events (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                correlation_id TEXT DEFAULT '',
                matched_schedule_ids_json TEXT NOT NULL DEFAULT '[]',
                triggered_run_ids_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'received',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _has_open_workflow_run(template_id: str) -> bool:
    try:
        from backend.kanban_sidecar import load_kanban_meta
        from backend.operations_api import _get_active_kanban_db_path

        meta = load_kanban_meta().get("tasks", {})
        matching_tids = [tid for tid, tm in meta.items() if isinstance(tm, dict) and tm.get("workflow_tpl_id") == template_id]
        if not matching_tids:
            return False
        db_path = _get_active_kanban_db_path()
        if not os.path.exists(db_path):
            return False
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            placeholders = ",".join("?" for _ in matching_tids)
            row = conn.execute(
                f"SELECT COUNT(*) FROM tasks WHERE id IN ({placeholders}) AND status IN ('todo', 'in_progress', 'backlog', 'ready')",
                matching_tids,
            ).fetchone()
            return bool(row and row[0] > 0)
        finally:
            conn.close()
    except Exception:
        return False


def _execute_schedule_row(conn: sqlite3.Connection, row: sqlite3.Row, now: datetime, extra_inputs: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    sched = _row_to_dict(row)
    sid = sched["id"]
    tpl_id = sched["template_id"]

    start_dt = _parse_iso(sched.get("start_at"))
    if start_dt and now < start_dt:
        return None

    end_dt = _parse_iso(sched.get("end_at"))
    if end_dt and now > end_dt:
        conn.execute("UPDATE workflow_schedules SET enabled = 0, last_status = 'expired' WHERE id = ?", (sid,))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_events (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                correlation_id TEXT DEFAULT '',
                matched_schedule_ids_json TEXT NOT NULL DEFAULT '[]',
                triggered_run_ids_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'received',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        return None

    if sched.get("end_condition") == "max_runs" and sched.get("max_runs") and sched["run_count"] >= int(sched["max_runs"]):
        conn.execute("UPDATE workflow_schedules SET enabled = 0, last_status = 'completed_max_runs' WHERE id = ?", (sid,))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_events (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                correlation_id TEXT DEFAULT '',
                matched_schedule_ids_json TEXT NOT NULL DEFAULT '[]',
                triggered_run_ids_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'received',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        return None

    if sched.get("start_condition") == "no_active_run" and _has_open_workflow_run(tpl_id):
        conn.execute("UPDATE workflow_schedules SET last_status = 'skipped_active_run' WHERE id = ?", (sid,))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_events (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                correlation_id TEXT DEFAULT '',
                matched_schedule_ids_json TEXT NOT NULL DEFAULT '[]',
                triggered_run_ids_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'received',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        return None

    merged_inputs = {**(sched.get("inputs") or {}), **(extra_inputs or {})}
    try:
        from backend.workflow_templates import launch_workflow_run

        res = launch_workflow_run(
            tpl_id=tpl_id,
            inputs=merged_inputs,
            cron_schedule=sched.get("cron_expr") or None,
            n8n_webhook_url=sched.get("n8n_webhook_url") or None,
        )
        new_count = sched["run_count"] + 1
        next_run = parse_cron_next(sched.get("cron_expr") or "", now) if ("cron" in sched["trigger_type"] and sched.get("cron_expr")) else ""
        should_disable = (
            sched.get("end_condition") == "max_runs"
            and sched.get("max_runs")
            and new_count >= int(sched["max_runs"])
        )
        conn.execute(
            """
            UPDATE workflow_schedules
            SET run_count = ?, last_run_at = ?, next_run_at = ?, last_run_id = ?, last_status = ?, enabled = ?
            WHERE id = ?
            """,
            (
                new_count,
                now.isoformat(),
                next_run or "",
                res.get("run_id", ""),
                "completed_max_runs" if should_disable else "triggered",
                0 if should_disable else 1,
                sid,
            ),
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_events (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                correlation_id TEXT DEFAULT '',
                matched_schedule_ids_json TEXT NOT NULL DEFAULT '[]',
                triggered_run_ids_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'received',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        return res
    except Exception as exc:
        disable_on_err = sched.get("end_condition") == "on_error_stop"
        conn.execute(
            "UPDATE workflow_schedules SET last_status = ?, enabled = ? WHERE id = ?",
            (f"error: {str(exc)[:120]}", 0 if disable_on_err else 1, sid),
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_events (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                correlation_id TEXT DEFAULT '',
                matched_schedule_ids_json TEXT NOT NULL DEFAULT '[]',
                triggered_run_ids_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'received',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        return None


def evaluate_due_schedules(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    init_schedules_db()
    cur_now = now or datetime.now(timezone.utc)
    triggered: List[Dict[str, Any]] = []
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM workflow_schedules WHERE enabled = 1 AND trigger_type IN ('cron', 'cron_and_watchdog')"
        ).fetchall()
        for row in rows:
            next_dt = _parse_iso(row["next_run_at"])
            if not next_dt:
                computed = parse_cron_next(row["cron_expr"] or "", cur_now - timedelta(minutes=1))
                if computed:
                    conn.execute("UPDATE workflow_schedules SET next_run_at = ? WHERE id = ?", (computed, row["id"]))
                    conn.commit()
                    next_dt = _parse_iso(computed)
            if next_dt and cur_now >= next_dt:
                res = _execute_schedule_row(conn, row, cur_now)
                if res:
                    triggered.append(res)

        cal_subs = conn.execute(
            "SELECT COUNT(*) FROM workflow_schedules WHERE enabled = 1 AND trigger_type IN ('calendar', 'any_event')"
        ).fetchone()
        if cal_subs and cal_subs[0] > 0:
            try:
                from backend.operations_calendar import operations_calendar

                today_str = cur_now.date().isoformat()
                cal_events = operations_calendar.list_events(start_date=today_str, end_date=today_str)
                for cev in cal_events:
                    cid = f"cal-{cev.get('id', '')}-{today_str}"
                    ev_res = dispatch_workflow_event(
                        source="calendar",
                        event_type="due",
                        title=str(cev.get("title") or "Kalender-Termin"),
                        summary=f"Quelle: {cev.get('source', '')} | Kategorie: {cev.get('category', '')}",
                        payload={"date": cev.get("date"), "time": cev.get("time", ""), "category": cev.get("category", "")},
                        correlation_id=cid,
                    )
                    triggered.extend(ev_res.get("triggered") or [])
            except Exception:
                pass
        return triggered
    finally:
        conn.close()


def dispatch_workflow_event(
    source: str,
    event_type: str,
    title: str,
    summary: str = "",
    payload: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Zentraler Event-Bus für Watchdog, Posteingang, Research Lab und AI Boardroom."""
    init_schedules_db()
    _init_policies_table()
    now = datetime.now(timezone.utc)
    event_id = f"evt-{uuid.uuid4().hex[:10]}"
    src = str(source or "manual").strip().lower()
    corr = str(correlation_id or "").strip()
    payload_dict = payload if isinstance(payload, dict) else {}

    source_triggers = {
        "watchdog": ("watchdog", "cron_and_watchdog", "any_event"),
        "inbox": ("inbox", "any_event"),
        "research": ("research", "any_event"),
        "boardroom": ("boardroom", "any_event"),
        "calendar": ("calendar", "any_event"),
        "approval": ("approval", "any_event"),
    }.get(src, ("any_event",))

    conn = _get_conn()
    try:
        if corr:
            dup = conn.execute(
                "SELECT id FROM workflow_events WHERE correlation_id = ? AND source = ? LIMIT 1",
                (corr, src),
            ).fetchone()
            if dup:
                conn.execute(
                    """
                    INSERT INTO workflow_events (id, source, event_type, title, summary, payload_json, correlation_id, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'skipped_loop', ?)
                    """,
                    (event_id, src, event_type, title, summary, json.dumps(payload_dict, ensure_ascii=False), corr, now.isoformat()),
                )
                conn.commit()
                return {"event_id": event_id, "status": "skipped_loop", "triggered": []}

        # Rate-Limit / Circuit-Breaker pro Quelle
        one_min_ago = (now - timedelta(minutes=1)).isoformat()
        recent_cnt = conn.execute(
            "SELECT COUNT(*) FROM workflow_events WHERE source = ? AND created_at >= ?",
            (src, one_min_ago),
        ).fetchone()[0]
        pol_rows = conn.execute("SELECT * FROM event_bus_policies WHERE source = ?", (src,)).fetchall()
        pol_map = {r["target"]: dict(r) for r in pol_rows}
        max_pm = min([int(r["max_per_min"] or 20) for r in pol_rows] or [20])
        if recent_cnt >= max_pm:
            conn.execute(
                """
                INSERT INTO workflow_events (id, source, event_type, title, summary, payload_json, correlation_id, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'rate_limited', ?)
                """,
                (event_id, src, event_type, title, summary, json.dumps(payload_dict, ensure_ascii=False), corr, now.isoformat()),
            )
            conn.commit()
            return {"event_id": event_id, "status": "rate_limited", "triggered": []}

        placeholders = ",".join("?" for _ in source_triggers)
        rows = conn.execute(
            f"SELECT * FROM workflow_schedules WHERE enabled = 1 AND trigger_type IN ({placeholders})",
            source_triggers,
        ).fetchall()

        haystack = f"{title} {summary} {json.dumps(payload_dict, ensure_ascii=False)}".lower()
        matched_ids: List[str] = []
        triggered_runs: List[Dict[str, Any]] = []
        blocked_by_policy = False

        for row in rows:
            kw_raw = (row["watchdog_keyword"] or "").strip()
            keywords = [k.strip().lower() for k in kw_raw.split(",") if k.strip()]
            if keywords and not any(k in haystack for k in keywords):
                continue
            target_dom = _infer_target_domain(row["template_id"])
            rule = pol_map.get(target_dom) or pol_map.get("all") or _default_policy_for(src, target_dom)
            if rule["policy"] == "deny":
                blocked_by_policy = True
                continue
            matched_ids.append(row["id"])
            extra = {
                "topic": str(title or event_type),
                "event_source": src,
                "event_type": event_type,
                "event_summary": str(summary or "")[:800],
                "policy_mode": rule["policy"],
            }
            for k, v in payload_dict.items():
                if isinstance(v, (str, int, float)):
                    extra[f"event_{k}"] = v
            res = _execute_schedule_row(conn, row, now, extra_inputs=extra)
            if res:
                triggered_runs.append(res)

        status = "triggered" if triggered_runs else ("blocked_policy" if blocked_by_policy else ("matched_skipped" if matched_ids else "no_match"))
        conn.execute(
            """
            INSERT INTO workflow_events (
                id, source, event_type, title, summary, payload_json, correlation_id,
                matched_schedule_ids_json, triggered_run_ids_json, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                src,
                str(event_type or "event"),
                str(title or "")[:300],
                str(summary or "")[:1000],
                json.dumps(payload_dict, ensure_ascii=False),
                corr,
                json.dumps(matched_ids),
                json.dumps([r.get("run_id") for r in triggered_runs if r.get("run_id")]),
                status,
                now.isoformat(),
            ),
        )
        conn.commit()
        return {"event_id": event_id, "status": status, "triggered": triggered_runs}
    finally:
        conn.close()


def list_workflow_events(limit: int = 100, source: Optional[str] = None) -> List[Dict[str, Any]]:
    init_schedules_db()
    conn = _get_conn()
    try:
        if source and source != "all":
            rows = conn.execute(
                "SELECT * FROM workflow_events WHERE source = ? ORDER BY created_at DESC LIMIT ?",
                (source, int(limit)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM workflow_events ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            for jf in ("payload_json", "matched_schedule_ids_json", "triggered_run_ids_json"):
                try:
                    d[jf.replace("_json", "")] = json.loads(d.pop(jf, "null") or "null")
                except Exception:
                    d[jf.replace("_json", "")] = None
            out.append(d)
        return out
    finally:
        conn.close()


def dispatch_watchdog_triggers(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not findings:
        return []
    triggered: List[Dict[str, Any]] = []
    for f in findings:
        ev_res = dispatch_workflow_event(
            source="watchdog",
            event_type="finding",
            title=f"{f.get('title', 'Watchdog-Fund')} ({f.get('link', '')})".strip(),
            summary=f.get("summary", ""),
            payload={"category": f.get("category", ""), "link": f.get("link", "")},
            correlation_id=str(f.get("id") or f.get("link") or ""),
        )
        triggered.extend(ev_res.get("triggered") or [])
    return triggered


EVENT_BUS_SOURCES = ["watchdog", "inbox", "calendar", "research", "boardroom", "approval", "manual"]
EVENT_BUS_TARGETS = ["workflow", "treasury", "comms", "system"]


def _infer_target_domain(template_id: str) -> str:
    low = (template_id or "").lower()
    if any(k in low for k in ("invoice", "cost", "dunning", "pay", "dropshipping_order", "tax", "treasury")):
        return "treasury"
    if any(k in low for k in ("email", "outreach", "newsletter", "social", "influencer", "followup")):
        return "comms"
    if any(k in low for k in ("code_review", "compliance", "release", "security")):
        return "system"
    return "workflow"


def _default_policy_for(source: str, target: str) -> Dict[str, Any]:
    if source == "watchdog" and target in ("treasury", "system"):
        return {"source": source, "target": target, "policy": "deny", "max_per_min": 20, "note": "Standard-Schutz: Watchdog darf keine Finanzen/Systeme triggern"}
    if source in ("inbox", "calendar") and target == "treasury":
        return {"source": source, "target": target, "policy": "require_hitl", "max_per_min": 20, "note": "Standard-Schutz: Zahlungen erfordern HITL-Freigabe"}
    return {"source": source, "target": target, "policy": "allow", "max_per_min": 20, "note": ""}


def list_event_policies() -> List[Dict[str, Any]]:
    init_schedules_db()
    _init_policies_table()
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT * FROM event_bus_policies").fetchall()
        saved = {(r["source"], r["target"]): dict(r) for r in rows}
        out: List[Dict[str, Any]] = []
        for src in EVENT_BUS_SOURCES:
            for tgt in EVENT_BUS_TARGETS:
                out.append(saved.get((src, tgt)) or _default_policy_for(src, tgt))
        return out
    finally:
        conn.close()


def upsert_event_policy(source: str, target: str, policy: str, max_per_min: int = 20, note: str = "") -> Dict[str, Any]:
    init_schedules_db()
    _init_policies_table()
    src = str(source or "").strip().lower()
    tgt = str(target or "").strip().lower()
    pol = str(policy or "allow").strip().lower()
    if pol not in {"allow", "require_hitl", "deny"}:
        pol = "allow"
    pid = f"{src}__{tgt}"
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO event_bus_policies (id, source, target, policy, max_per_min, note, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                policy=excluded.policy,
                max_per_min=excluded.max_per_min,
                note=excluded.note,
                updated_at=excluded.updated_at
            """,
            (pid, src, tgt, pol, max(1, int(max_per_min or 20)), str(note or "").strip(), now_iso),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM event_bus_policies WHERE id = ?", (pid,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def replay_workflow_event(event_id: str) -> Dict[str, Any]:
    init_schedules_db()
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM workflow_events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            raise KeyError("event_not_found")
        payload = json.loads(row["payload_json"] or "{}")
    finally:
        conn.close()
    return dispatch_workflow_event(
        source=row["source"],
        event_type=f"{row['event_type']}_replay",
        title=row["title"],
        summary=row["summary"],
        payload=payload,
        correlation_id=None,
    )


async def workflow_scheduler_background_loop() -> None:
    await asyncio.sleep(8)
    while True:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, evaluate_due_schedules)
        except Exception as exc:
            print(f"[WorkflowScheduler] Loop-Fehler: {exc}", file=sys.stderr)
        await asyncio.sleep(30)
