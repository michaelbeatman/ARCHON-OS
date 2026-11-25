"""Router fuer HUD-Telemetrie, Agent-Aktivitaeten, Projekte und Metriken."""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import re
import sqlite3
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi import Depends as _ArchonDepends

from archon.core.paths import KANBAN_DB_PATH
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes

try:
    from backend.db_paths import DB_BUSY_TIMEOUT_MS
except Exception:  # pragma: no cover - SSOT nicht importierbar
    DB_BUSY_TIMEOUT_MS = 5000

logger = logging.getLogger("archon.routers.telemetry")

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["telemetry"])

_ACTIVITY_LIMIT = 25
_ACTIVITY_MAX_LINES = 60


def _activity_db_candidates(filename: str) -> list[str]:
    """Mgliche Pfade einer DB - konsolidierte Ziele zuerst, Container-Pfade als Fallback."""
    candidates = []
    try:
        from backend.db_paths import resolve_db as _resolve_db

        candidates.append(_resolve_db(filename))
    except Exception as exc:
        logger.debug(f"[Telemetry] DB-Resolver fuer {filename} nicht verfuegbar: {exc}")
    workspace = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    candidates.extend(
        [
            f"/app/data/{filename}",
            f"/opt/data/{filename}",
            os.path.join(workspace, "data", filename),
        ]
    )
    seen, ordered = set(), []
    for path in candidates:
        if not path:
            continue
        path = os.path.abspath(path)
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


def _open_activity_db(filename: str):
    """Read-only Verbindung zur ersten DB mit echter Datei. (conn, path) oder (None, None)."""
    for path in _activity_db_candidates(filename):
        if not os.path.isfile(path):
            continue
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3.0)
            conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};")
            return conn, path
        except sqlite3.Error as exc:
            logger.debug(f"[Telemetry] {path} nicht lesbar: {exc}")
    return None, None


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Spaltennamen einer Tabelle - erlaubt feature-detektive Queries bei Schema-Varianten."""
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _parse_epoch(value) -> Optional[float]:
    """Epoch-Sekunden, Millisekunden und ISO-Zeitstempel auf einen Zeitwert normalisieren."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number / 1000 if number > 1e11 else number
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return _parse_epoch(float(text))
    try:
        parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return parsed.timestamp()
    except ValueError:
        return None


def _fmt_activity_time(ts: Optional[float]) -> str:
    if ts is None:
        return "--:--:--"
    try:
        dt = datetime.datetime.fromtimestamp(ts)
        if dt.date() == datetime.date.today():
            return dt.strftime("%H:%M:%S")
        return dt.strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError, OverflowError):
        return "--:--:--"


def _preview(text, maxlen: int = 100) -> str:
    value = str(text or "").replace("\r", " ").replace("\n", " ").strip()
    return value if len(value) <= maxlen else value[: maxlen - 1] + "…"


def _payload_preview(raw, maxlen: int = 100) -> str:
    """JSON-Payloads auf die aussagekraeftigsten Felder reduzieren."""
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return _preview(text, maxlen)
    if not isinstance(parsed, dict):
        return _preview(parsed, maxlen)
    for key in ("message", "detail", "text", "summary", "name", "action", "reason", "note", "error"):
        if parsed.get(key):
            return _preview(parsed[key], maxlen)
    parts = [
        f"{key}={_preview(value, 40)}"
        for key, value in list(parsed.items())[:4]
        if value not in (None, "", {}, [])
    ]
    return _preview(" · ".join(parts), maxlen)


def _has_json1(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("SELECT json_extract('{}', '$.probe')").fetchone()
        return True
    except sqlite3.Error:
        return False


def _collect_ops_activity(agent_id: str, limit: int = _ACTIVITY_LIMIT):
    """Ops-DB: Tasks, Task-Events und Task-Runs des Agenten."""
    entries, counts = [], {}  # type: ignore[var-annotated, var-annotated]
    conn, _path = _open_activity_db("ops.db")
    if conn is None:
        return entries, counts
    try:
        task_ids = []
        cols = _table_columns(conn, "tasks")
        if "assignee" in cols:
            select = [c for c in ("id", "title", "status", "created_at", "completed_at") if c in cols]
            rows = conn.execute(
                "SELECT "
                + ", ".join(select)
                + " FROM tasks WHERE LOWER(COALESCE(assignee,'')) = LOWER(?) ORDER BY "
                + ("created_at DESC" if "created_at" in cols else "id DESC")
                + " LIMIT ?",
                (agent_id, limit),
            ).fetchall()
            counts["tasks"] = len(rows)
            for row in rows:
                item = dict(zip(select, row))
                task_ids.append(str(item.get("id") or ""))
                ts = _parse_epoch(item.get("created_at"))
                line = (
                    f"[{_fmt_activity_time(ts)}][TASK] {item.get('id') or '?'} · "
                    f"{_preview(item.get('title'), 70)} · {item.get('status') or 'todo'}"
                )
                end_ts = _parse_epoch(item.get("completed_at"))
                if end_ts:
                    line += f" · abgeschlossen {_fmt_activity_time(end_ts)}"
                entries.append((ts or 0.0, line, "tasks"))

        cols = _table_columns(conn, "task_events")
        if cols and ("task_id" in cols or "payload" in cols):
            clauses, params = [], []
            if "task_id" in cols and task_ids:
                capped = task_ids[:100]
                clauses.append("task_id IN (" + ",".join("?" * len(capped)) + ")")
                params.extend(capped)
            if "payload" in cols:
                clauses.append("LOWER(COALESCE(payload,'')) LIKE ?")
                params.append('%"' + agent_id.lower() + '"%')
                if _has_json1(conn):
                    clauses.append(
                        "LOWER(COALESCE(json_extract(payload, '$.agent_id'),'')) = LOWER(?)"
                    )
                    params.append(agent_id)
            if clauses:
                time_col = "created_at" if "created_at" in cols else "id"
                select = [
                    c for c in ("task_id", "kind", "payload", time_col) if c in cols  # type: ignore[misc]
                ]
                rows = conn.execute(
                    "SELECT "
                    + ", ".join(select)
                    + " FROM task_events WHERE "
                    + " OR ".join(clauses)
                    + f" ORDER BY {time_col} DESC LIMIT ?",
                    params + [limit * 2],
                ).fetchall()
                seen_events = set()
                for row in rows:
                    item = dict(zip(select, row))
                    dedup_key = (
                        str(item.get("task_id")),
                        str(item.get("kind")),
                        str(item.get(time_col)),
                    )
                    if dedup_key in seen_events:
                        continue
                    seen_events.add(dedup_key)
                    ts = _parse_epoch(item.get("created_at")) if "created_at" in cols else None
                    line = (
                        f"[{_fmt_activity_time(ts)}][EVENT] {item.get('kind') or 'event'}"
                    )
                    if item.get("task_id"):
                        line += f" · Task {item['task_id']}"
                    detail = _payload_preview(item.get("payload"))
                    if detail:
                        line += f" · {detail}"
                    entries.append((ts or 0.0, line, "task_events"))
                counts["task_events"] = len(seen_events)

        cols = _table_columns(conn, "task_runs")
        if cols:
            agent_col = next(
                (c for c in ("agent_id", "assignee", "worker_id", "worker", "agent") if c in cols),
                None,
            )
            time_col = next(  # type: ignore[assignment]
                (c for c in ("started_at", "created_at", "start_time", "created_ts") if c in cols),
                None,
            )
            status_col = next((c for c in ("status", "state") if c in cols), None)
            clauses, params = [], []
            if agent_col:
                clauses.append(f"LOWER(COALESCE({agent_col},'')) = LOWER(?)")
                params.append(agent_id)
            if "task_id" in cols and task_ids:
                capped = task_ids[:100]
                clauses.append("task_id IN (" + ",".join("?" * len(capped)) + ")")
                params.extend(capped)
            if clauses:
                select = []
                for col in ("id", "run_id", "task_id", agent_col, status_col, time_col):
                    if col and col in cols and col not in select:
                        select.append(col)  # type: ignore[arg-type]
                order = f"{time_col} DESC" if time_col else "rowid DESC"
                rows = conn.execute(
                    "SELECT "
                    + ", ".join(select)
                    + " FROM task_runs WHERE "
                    + " OR ".join(clauses)
                    + f" ORDER BY {order} LIMIT ?",
                    params + [limit],
                ).fetchall()
                counts["task_runs"] = len(rows)
                for row in rows:
                    item = dict(zip(select, row))
                    ts = _parse_epoch(item.get(time_col)) if time_col else None
                    line = f"[{_fmt_activity_time(ts)}][RUN] Run {item.get('run_id') or item.get('id') or '?'}"
                    if item.get("task_id"):
                        line += f" · Task {item['task_id']}"
                    if status_col and item.get(status_col):
                        line += f" · {item[status_col]}"
                    entries.append((ts or 0.0, line, "task_runs"))
    except sqlite3.Error as exc:
        logger.debug(f"[Telemetry] Ops-Aktivitaet fuer '{agent_id}' nicht lesbar: {exc}")
    finally:
        conn.close()
    return entries, counts


def _collect_memory_activity(agent_id: str, limit: int = _ACTIVITY_LIMIT):
    """Memory-DB: Audit-Log, OTel-Traces, Execution-Receipts und Egress-Log."""
    entries, counts = [], {}  # type: ignore[var-annotated, var-annotated]
    conn, _path = _open_activity_db("memory.db")
    if conn is None:
        return entries, counts
    try:
        cols = _table_columns(conn, "audit_log")
        if "agent_id" in cols:
            select = [
                c for c in ("timestamp", "category", "action", "event_type", "payload_json", "model")
                if c in cols
            ]
            rows = conn.execute(
                "SELECT "
                + ", ".join(select)
                + " FROM audit_log WHERE LOWER(COALESCE(agent_id,'')) = LOWER(?) ORDER BY id DESC LIMIT ?",
                (agent_id, limit),
            ).fetchall()
            counts["audit_log"] = len(rows)
            for row in rows:
                item = dict(zip(select, row))
                ts = _parse_epoch(item.get("timestamp"))
                label = item.get("action") or item.get("event_type") or "event"
                line = (
                    f"[{_fmt_activity_time(ts)}][AUDIT] "
                    f"{item.get('category') or 'system'}/{label}"
                )
                detail = _payload_preview(item.get("payload_json"))
                if detail:
                    line += f" · {detail}"
                if item.get("model"):
                    line += f" · {item['model']}"
                entries.append((ts or 0.0, line, "audit_log"))

        cols = _table_columns(conn, "otel_traces")
        if "agent_id" in cols:
            select = [
                c for c in ("start_time", "name", "status", "total_tokens", "total_cost_usd", "duration_ms", "task_id")  # type: ignore[misc]
                if c in cols
            ]
            rows = conn.execute(
                "SELECT "
                + ", ".join(select)
                + " FROM otel_traces WHERE LOWER(COALESCE(agent_id,'')) = LOWER(?) ORDER BY start_time DESC LIMIT ?",
                (agent_id, limit),
            ).fetchall()
            counts["otel_traces"] = len(rows)
            for row in rows:
                item = dict(zip(select, row))
                ts = _parse_epoch(item.get("start_time"))
                line = (
                    f"[{_fmt_activity_time(ts)}][TRACE] {item.get('name') or 'trace'} · "
                    f"{item.get('status') or 'OK'}"
                )
                if item.get("total_tokens"):
                    line += f" · {item['total_tokens']} Tokens"
                if item.get("total_cost_usd"):
                    try:
                        line += f" · ${float(item['total_cost_usd']):.4f}"
                    except (TypeError, ValueError):
                        pass
                if item.get("duration_ms"):
                    line += f" · {item['duration_ms']} ms"
                entries.append((ts or 0.0, line, "otel_traces"))

        cols = _table_columns(conn, "execution_receipts_ledger")
        agent_col = next((c for c in ("agent_role", "agent_id") if c in cols), None)
        if agent_col:
            select = [
                c for c in ("created_at", "model_used", "prompt_tokens", "completion_tokens", "cost_usd", "task_id")  # type: ignore[misc]
                if c in cols
            ]
            rows = conn.execute(
                "SELECT "
                + ", ".join(select)
                + f" FROM execution_receipts_ledger WHERE LOWER(COALESCE({agent_col},'')) = LOWER(?) ORDER BY id DESC LIMIT ?",
                (agent_id, limit),
            ).fetchall()
            counts["execution_receipts_ledger"] = len(rows)
            for row in rows:
                item = dict(zip(select, row))
                ts = _parse_epoch(item.get("created_at"))
                tokens = int(item.get("prompt_tokens") or 0) + int(item.get("completion_tokens") or 0)
                line = f"[{_fmt_activity_time(ts)}][RECEIPT] {item.get('model_used') or 'model'}"
                if tokens:
                    line += f" · {tokens} Tokens"
                if item.get("cost_usd"):
                    try:
                        line += f" · ${float(item['cost_usd']):.4f}"
                    except (TypeError, ValueError):
                        pass
                if item.get("task_id"):
                    line += f" · Task {item['task_id']}"
                entries.append((ts or 0.0, line, "execution_receipts_ledger"))

        cols = _table_columns(conn, "egress_firewall_logs")
        if "agent_id" in cols:
            select = [
                c for c in ("created_at", "hostname", "target_url", "allowed", "reason") if c in cols  # type: ignore[misc]
            ]
            rows = conn.execute(
                "SELECT "
                + ", ".join(select)
                + " FROM egress_firewall_logs WHERE LOWER(COALESCE(agent_id,'')) = LOWER(?) ORDER BY id DESC LIMIT ?",
                (agent_id, limit),
            ).fetchall()
            counts["egress_firewall_logs"] = len(rows)
            for row in rows:
                item = dict(zip(select, row))
                ts = _parse_epoch(item.get("created_at"))
                verdict = "ALLOWED" if item.get("allowed") else "BLOCKED"
                line = (
                    f"[{_fmt_activity_time(ts)}][EGRESS] {item.get('hostname') or 'host'} · "
                    f"{verdict} · {_preview(item.get('reason'), 70)}"
                )
                entries.append((ts or 0.0, line, "egress_firewall_logs"))
    except sqlite3.Error as exc:
        logger.debug(f"[Telemetry] Memory-Aktivitaet fuer '{agent_id}' nicht lesbar: {exc}")
    finally:
        conn.close()
    return entries, counts


def _read_recent_turns(agent_id: str) -> list[str]:
    """Letzte Chat-Turns aus conversations - konsolidierte memory.db zuerst."""
    recent_turns = []
    candidates = _activity_db_candidates("agentic_memory.db") + _activity_db_candidates("memory.db")
    for db_path in candidates:
        if not os.path.isfile(db_path):
            continue
        conn = None
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3.0)
            conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};")
            if not _table_columns(conn, "conversations"):
                continue
            rows = conn.execute(
                "SELECT role, content, timestamp FROM conversations WHERE agent_id = ? ORDER BY id DESC LIMIT 5",
                (agent_id,),
            ).fetchall()
            if not rows:
                continue
            for row in reversed(rows):
                recent_turns.append(f"[{row[2]}] {row[0].upper()}: {str(row[1])[:140]}")
            break
        except sqlite3.Error as exc:
            logger.debug(f"[Telemetry] Konnte letzte Chat-Turns aus {db_path} nicht laden: {exc}")
        finally:
            if conn:
                conn.close()
    return recent_turns


@router.get("/api/v1/agent/{agent_id}/activity")
def api_get_agent_activity(agent_id: str):
    """Liefert echte Aktivitaetsdaten aus ops.db + memory.db statt Standby-Platzhalter."""
    from archon.core.provider_registry import get_provider
    app_main = get_provider("app_main")
    from utils.path_jail import PathJailError, safe_identifier

    try:
        clean_id = safe_identifier(agent_id, "agent_id")
    except PathJailError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    entries = []
    sources = {}
    for collector in (_collect_ops_activity, _collect_memory_activity):
        try:
            items, counts = collector(clean_id)
            entries.extend(items)
            sources.update(counts)
        except Exception as exc:
            logger.debug(
                f"[Telemetry] Aktivitaetsquelle {collector.__name__} fuer '{clean_id}' nicht verfuegbar: {exc}"
            )

    recent_turns = _read_recent_turns(clean_id)
    if recent_turns:
        sources["conversations"] = len(recent_turns)

    # Legacy-Logdatei weiterhin lesen, falls ein Modul sie doch schreibt.
    log_path = app_main.agent_log_path(clean_id)
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as handle:
                log_lines = [line.strip() for line in handle.readlines()[-40:] if line.strip()]
            sources["agent.log"] = len(log_lines)
            for line in log_lines:
                time_match = re.search(r"\[(\d{2}:\d{2}:\d{2})\]", line)
                ts = None
                if time_match:
                    try:
                        clock = datetime.datetime.strptime(time_match.group(1), "%H:%M:%S").time()
                        ts = datetime.datetime.combine(datetime.date.today(), clock).timestamp()
                    except ValueError:
                        pass
                entries.append((ts or 0.0, line, "agent.log"))
        except OSError as exc:
            logger.debug(f"[Telemetry] Logdatei nicht lesbar: {exc}")

    # Duplikate entfernen, nach Zeit absteigend sortieren und begrenzen.
    unique = {}  # type: ignore[var-annotated]
    for ts, line, source in entries:
        unique.setdefault(line, (ts, line, source))
    ordered = sorted(unique.values(), key=lambda item: item[0], reverse=True)[:_ACTIVITY_MAX_LINES]

    if not ordered and not recent_turns:
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        ordered = [
            (0.0, f"[{now_str}] Agent '{clean_id}' initialisiert im Standby-Modus.", "standby"),
            (0.0, f"[{now_str}] MCP Tools & Provider-Bindings aktiv.", "standby"),
            (0.0, f"[{now_str}] Bereit fuer Arbeitsauftraege und Autonom-Routing.", "standby"),
        ]
        sources["standby"] = 3

    return {
        "status": "success",
        "agent_id": clean_id,
        "logs": [line for _ts, line, _source in ordered],
        "recent_turns": recent_turns,
        "sources": sources,
        "total": len(ordered) + len(recent_turns),
        "live": True,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }


@router.get("/api/v1/agent/{agent_id}/projects")
def api_get_agent_projects(agent_id: str):
    """Liefert die spezifische Projekthistorie (Beteiligungen) fuer einen bestimmten Agenten."""
    from archon.core.provider_registry import get_provider
    app_main = get_provider("app_main")

    projects = []
    seen_ids = set()

    prof = None
    try:
        roles_list = app_main.api_get_hermes_profiles()
        prof = next((p for p in roles_list if p.get("id") == agent_id), None)
    except Exception as exc:
        logger.debug(f"[Telemetry] Profil-Lookup fuer '{agent_id}' fehlgeschlagen: {exc}")

    agent_id_clean = agent_id.strip().lower()
    # 19.11.2026: person_name kann im Profil None sein -> AttributeError beim .strip() (Live-Log)
    person_name = ((prof.get("person_name") if prof else "") or "").strip().lower()
    role_name = ((prof.get("name") if prof else "") or "").strip().lower()

    match_terms = {agent_id_clean, agent_id_clean.replace("_", " ")}
    if person_name:
        match_terms.add(person_name)
        parts = [
            p for p in person_name.replace("dr.", "").split() if len(p) >= 4
        ]
        for p in parts:
            match_terms.add(p)
    if role_name and len(role_name) >= 4:
        match_terms.add(role_name)

    if agent_id_clean == "executive_decision_architect":
        match_terms.add("robert")
        match_terms.add("alexander richter")
        match_terms.add("richter")

    if agent_id_clean in ["micha", "michael_keller"]:
        match_terms.add("michael keller")
        match_terms.add("micha")
        match_terms.add("keller")

    candidate_dirs = [
        os.path.join(app_main.OBSIDIAN_VAULT_DIR, "01_PROJEKTE")
        if app_main.OBSIDIAN_VAULT_DIR
        else None,
        app_main.PROJEKTE_DIR,
    ]

    for vault_projects_dir in candidate_dirs:
        if not vault_projects_dir or not os.path.exists(vault_projects_dir):
            continue
        try:
            for fname in os.listdir(vault_projects_dir):
                if not fname.endswith(".md"):
                    continue
                fpath = os.path.join(vault_projects_dir, fname)
                try:
                    with open(
                        fpath, "r", encoding="utf-8", errors="ignore"
                    ) as f:
                        text = f.read()

                    fm_match = re.search(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
                    fm_text = fm_match.group(1) if fm_match else ""

                    agent_fm_match = re.search(
                        r"agent:\s*([^\n]+)", fm_text, re.IGNORECASE
                    )
                    agent_assigned = (
                        agent_fm_match.group(1).strip().lower()
                        if agent_fm_match
                        else ""
                    )

                    is_match = False
                    if agent_assigned:
                        for term in match_terms:
                            if term in agent_assigned or agent_assigned in term:
                                is_match = True
                                break
                    else:
                        text_lower = text[:1500].lower()
                        for term in match_terms:
                            if len(term) >= 4 and (
                                f"agent: {term}" in text_lower
                                or f"von {term}" in text_lower
                                or f"spricht {term}" in text_lower
                            ):
                                is_match = True
                                break

                    if is_match:
                        proj_id = fname.replace(".md", "")
                        if proj_id in seen_ids:
                            continue
                        seen_ids.add(proj_id)

                        title = proj_id.replace("-", " ").title()
                        first_h1 = [
                            l for l in text.splitlines() if l.startswith("# ")
                        ]
                        if first_h1:
                            title = first_h1[0].replace("# ", "").strip()

                        date_match = re.search(r"date:\s*([\d-]+)", text)
                        date_str = (
                            date_match.group(1) if date_match else "2026-09"
                        )
                        status_match = re.search(r"status:\s*([^\n]+)", text)
                        status_str = (
                            status_match.group(1).strip()
                            if status_match
                            else "Abgeschlossen"
                        )

                        projects.append(
                            {
                                "id": proj_id,
                                "name": title,
                                "date": date_str,
                                "status": status_str,
                                "source": "Obsidian / 01_PROJEKTE",
                                "file": fname,
                            }
                        )
                except OSError as f_exc:
                    logger.debug(f"[Telemetry] Obsidian-Datei {fname} nicht lesbar: {f_exc}")
        except OSError as d_exc:
            logger.debug(f"[Telemetry] Obsidian-Projektordner nicht lesbar: {d_exc}")

    personalakten_dirs = [
        os.path.join(app_main.OBSIDIAN_VAULT_DIR, "00_HR_Agenten", "Personalakten")
        if app_main.OBSIDIAN_VAULT_DIR
        else None,
        app_main.PERSONALAKTEN_DIR,
    ]
    for pa_dir in personalakten_dirs:
        if not pa_dir or not os.path.exists(pa_dir):
            continue
        pa_file = os.path.join(pa_dir, f"{agent_id_clean}.md")
        if os.path.exists(pa_file):
            try:
                with open(pa_file, "r", encoding="utf-8", errors="ignore") as f:
                    pa_text = f.read()
                sec5_match = re.search(
                    r"## 5\.[^\n]*\n(.*?)(?=\n## 6\.|\Z)", pa_text, re.DOTALL
                )
                if sec5_match:
                    sec5_content = sec5_match.group(1)
                    wiki_links = re.findall(r"\[\[(.*?)\]\]", sec5_content)
                    for wl in wiki_links:
                        wl_clean = wl.split("|")[0].strip()
                        if (
                            wl_clean
                            and not wl_clean.startswith("00_")
                            and "knowledge" not in wl_clean.lower()
                            and "archiv" not in wl_clean.lower()
                        ):
                            p_key = f"pa-{wl_clean.lower().replace(' ', '-')}"
                            if p_key not in seen_ids:
                                seen_ids.add(p_key)
                                projects.append(
                                    {
                                        "id": p_key,
                                        "name": wl_clean,
                                        "date": "2026-08",
                                        "status": "Dokumentiert",
                                        "source": "HR-Personalakte",
                                        "file": f"{agent_id_clean}.md",
                                    }
                                )
            except OSError as hr_exc:
                logger.debug(f"[Telemetry] HR-Personalakte fuer '{agent_id_clean}' nicht lesbar: {hr_exc}")
            break

    if agent_id_clean in ["micha", "michael_keller"] and not any(
        "Kernsystem" in p["name"] for p in projects
    ):
        projects.insert(
            0,
            {
                "id": "agenticos-core",
                "name": "AgenticOS 2026 Gesamtarchitektur & Kernsystem",
                "date": "2026-09",
                "status": "Aktiv",
                "source": "Archon OS",
                "file": "core",
            },
        )

    return {
        "status": "success",
        "agent_id": agent_id,
        "projects": projects,
    }


def _collect_hud_telemetry_sync(app_main: Any):
    import glob
    import sqlite3

    v_notes = 0
    obs_path = os.path.join(app_main.WORKSPACE_DIR, "obsidian_vault")
    if os.path.exists(obs_path):
        try:
            v_notes = len([f for f in os.listdir(obs_path) if f.endswith(".md")])
        except Exception:
            v_notes = 0
    mem_records = 0
    try:
        mem_records = len(app_main.load_memory())
    except Exception:
        mem_records = 0

    tot_inp, tot_out, tot_cache, tot_cost = 0, 0, 0, 0.0
    from archon.core.profiles import get_hermes_profiles_base_dirs

    state_db_candidates = [
        db
        for base_dir in get_hermes_profiles_base_dirs()
        for db in glob.glob(os.path.join(base_dir, "*", "state.db"))
    ]
    if getattr(app_main, "STATE_DB_PATH", None):
        state_db_candidates.append(app_main.STATE_DB_PATH)
    state_dbs = sorted(set(state_db_candidates))
    for db in state_dbs:
        if not os.path.isfile(db):
            continue
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=0.5)
            try:
                row = con.execute(
                    "SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), "
                    "COALESCE(SUM(cache_read_tokens),0), COALESCE(SUM(estimated_cost_usd),0) "
                    "FROM session_model_usage"
                ).fetchone()
                if row:
                    tot_inp += int(row[0] or 0)
                    tot_out += int(row[1] or 0)
                    tot_cache += int(row[2] or 0)
                    tot_cost += float(row[3] or 0.0)
            finally:
                con.close()
        except Exception:
            continue

    skills_active = []
    try:
        from archon.core.skills import _HERMES_SKILLS_CACHE, build_skills_file_index
        idx = _HERMES_SKILLS_CACHE or build_skills_file_index()
        if isinstance(idx, dict):
            for s_name in list(idx.keys())[:12]:
                skills_active.append({"name": s_name, "status": "active", "category": "skill"})
    except Exception as sk_exc:
        logger.debug(f"[Telemetry] Skill-Index fuer Telemetrie nicht verfuegbar: {sk_exc}")
    return v_notes, mem_records, tot_inp, tot_out, tot_cache, tot_cost, skills_active


def _load_hud_configs(app_main: Any) -> tuple:
    """D08/MED: agents.json/services.json im Worker-Thread lesen."""
    return app_main.load_agents(), app_main.load_services()


@router.get("/api/v1/hud/telemetry")
async def get_hud_telemetry():
    """Real-time Hermes HUD-UI consciousness and system telemetry stream."""
    from archon.core.provider_registry import get_provider
    app_main = get_provider("app_main")

    agents, services = await asyncio.to_thread(_load_hud_configs, app_main)

    async def _probe_service(s: dict) -> dict:
        port = s.get("port")
        is_up = False
        if port:
            for host in ("127.0.0.1", "host.docker.internal"):
                try:
                    _, writer = await asyncio.wait_for(
                        asyncio.open_connection(host, int(port)), timeout=0.15
                    )
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except OSError as cls_exc:
                        logger.debug(f"[Telemetry] Socket-Close-Hinweis: {cls_exc}")
                    is_up = True
                    break
                except Exception:
                    continue
        else:
            is_up = s.get("active", True)
        return {
            "id": s.get("id"),
            "name": s.get("name"),
            "port": port,
            "role": s.get("role"),
            "status": "online" if is_up else "standby",
            "active": is_up,
        }

    fleet_status = list(
        await asyncio.gather(*[_probe_service(s) for s in services])
    )

    vault_notes, mem_count, tot_inp, tot_out, tot_cache, tot_cost, skills_list = await asyncio.to_thread(
        _collect_hud_telemetry_sync, app_main
    )
    tot_tokens = tot_inp + tot_out
    cache_denom = tot_inp + tot_cache
    cache_pct = f"{(tot_cache / cache_denom * 100):.1f}%" if cache_denom > 0 else "0.0%"
    logs = list(app_main.ticker_entries)

    return {
        "timestamp": datetime.datetime.now().isoformat(),
        "consciousness": {
            "status": "CONSCIOUS & ACTIVE",
            "mode": "Universal Multi-Profile Engine",
            "current_profile": "Hermes Master Orchestrator",
            "profiles": agents,
        },
        "tokens": {
            "total_tokens": tot_tokens,
            "prompt_tokens": tot_inp,
            "completion_tokens": tot_out,
            "cache_hit_rate": cache_pct,
            "cost_usd": f"{tot_cost:.4f}",
            "avg_latency_ms": 0,
        },
        "fleet": fleet_status,
        "skills": skills_list,
        "storage": {
            "vault_notes": vault_notes,
            "memory_records": mem_count,
            "sqlite_wal_mode": True,
            "rag_vectors": mem_count,
        },
        "logs": logs,
    }


import time

_TELEMETRY_CACHE = {"ts": 0.0, "containers": 0}


def _count_running_containers() -> int:
    """Echte Zahl laufender Container (60 s gecacht, damit der Endpunkt billig bleibt)."""
    now = time.time()
    if now - _TELEMETRY_CACHE["ts"] < 60 and _TELEMETRY_CACHE["ts"]:
        return _TELEMETRY_CACHE["containers"]  # type: ignore[return-value]
    count = 0
    try:
        import subprocess

        out = subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True, timeout=3)
        count = len([x for x in out.stdout.splitlines() if x.strip()]) if out.returncode == 0 else 0
    except Exception:
        count = 0
    if count == 0:
        # Fallback: docker-socket-proxy im Docker-Netz
        try:
            import json as _json
            import urllib.request as _url

            for host in ("http://docker-socket-proxy:2375", "http://host.docker.internal:2375"):
                try:
                    with _url.urlopen(f"{host}/containers/json", timeout=3) as resp:
                        count = len(_json.loads(resp.read()))
                        break
                except Exception:
                    continue
        except Exception as dk_exc:
            logger.debug(f"[Telemetry] Docker-Container-Zaehlung fehlgeschlagen: {dk_exc}")
    _TELEMETRY_CACHE.update({"ts": now, "containers": count})
    return count


def _get_running_tasks_count() -> int:
    try:
        import sqlite3 as _sql

        with _sql.connect(f"file:{KANBAN_DB_PATH}?mode=ro", uri=True, timeout=2) as _conn:
            return _conn.execute("SELECT count(*) FROM tasks WHERE status = 'in_progress'").fetchone()[0]
    except Exception:
        return 0


@router.get("/api/v1/telemetry/dashboard")
def api_telemetry_dashboard():
    """Live-Kennzahlen. Keine festen Werte — alles wird zur Laufzeit ermittelt."""
    from archon.core.provider_registry import get_provider
    app_main = get_provider("app_main")

    tasks_running = _get_running_tasks_count()
    app_start_ts = getattr(app_main, "_APP_START_TS", time.time())
    uptime_seconds = max(0, int(time.time() - app_start_ts))
    hours, rest = divmod(uptime_seconds, 3600)
    minutes = rest // 60

    load_agents_fn = getattr(app_main, "load_agents", lambda: [])  # type: ignore[var-annotated]

    return {
        "active_agents": len(load_agents_fn()),
        "tasks_running": tasks_running,
        "network_ops": _count_running_containers(),
        "avg_uptime": f"{hours}h {minutes}m",
        "uptime_seconds": uptime_seconds,
    }

