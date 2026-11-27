# -*- coding: utf-8 -*-
"""M100: Read-only-Aggregation der Output-Wirtschaftlichkeit.

Quellen (alle nur lesend, keine Schema- Mutation):
* ``agentic_memory.db`` -> ``tasks`` (status ``done``), ``agent_handoffs``
  (Deliverable-Nachweis), ``execution_receipts_ledger`` (SSOT fuer Tokens,
  Modell und tatsaechliche Kosten), ``task_budget_allocations`` (nur falls
  die Tabelle bereits lazy angelegt wurde).
* Sidecar ``config/kanban_meta.json`` ueber ``backend.kanban_sidecar``
  (geschätzte Kosten/Tokens sowie Output-Typ-Hinweise).

`task_budget_allocations` und `role_daily_budget_ledger` werden von
`role_budget_engine.init_budget_tables()` erst bei Bedarf angelegt. Fehlende
Tabellen duerfen diese Aggregation nicht scheitern lassen. Es wird bewusst
KEINE Tabelle angelegt und kein INSERT/UPDATE/DELETE ausgefuehrt.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import sqlite3
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import quote

logger = logging.getLogger("archon.output_economics")

GENERAL_OUTPUT_TYPE = "General"
DEFAULT_OUTPUT_TYPE = "Deliverable"
ALLOWED_GROUP_BY = ("project", "agent_profile", "period", "output_type")
ALLOWED_PERIODS = ("day", "week", "month")
_KNOWN_TABLES = (
    "tasks",
    "agent_handoffs",
    "execution_receipts_ledger",
    "task_budget_allocations",
    "role_daily_budget_ledger",
)


def _usd_to_eur_rate() -> float:
    """Wechselkurs aus der Budget-SSOT, defensiv mit lokalem Fallback."""
    try:
        from backend.role_budget_engine import USD_TO_EUR_RATE as _rate

        return float(_rate)
    except Exception:
        return 0.92


USD_TO_EUR_RATE = _usd_to_eur_rate()


def _default_memory_db_path() -> str:
    """Pfad der Memory-DB ueber den zentralen db_paths-Resolver (analog zum Budget-Engine)."""
    try:
        from backend.db_paths import resolve_db

        return resolve_db("agentic_memory.db")
    except Exception as exc:
        logger.warning("[OutputEconomics] resolve_db fehlgeschlagen: %s", exc)
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "agentic_memory.db")


def _load_kanban_meta() -> Dict[str, Any]:
    """Sidecar nur lesen; ein defekter Sidecar liefert eine leere Struktur."""
    try:
        from backend.kanban_sidecar import load_kanban_meta

        data = load_kanban_meta()
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("[OutputEconomics] Sidecar-Meta nicht lesbar: %s", exc)
        return {}


def _open_readonly(path: str) -> Optional[sqlite3.Connection]:
    """SQLite im reinen Lese-Modus oeffnen. Erzeugt keine Datei und kein Schema."""
    if not path:
        return None
    try:
        if not os.path.isfile(path):
            return None
        uri = "file:" + quote(path.replace("\\", "/"), safe="/:") + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        logger.warning("[OutputEconomics] DB nicht lesbar (%s): %s", path, exc)
        return None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone() is not None
    except sqlite3.Error:
        return False


def _rows(conn: sqlite3.Connection, sql: str) -> List[Dict[str, Any]]:
    try:
        return [dict(row) for row in conn.execute(sql).fetchall()]
    except sqlite3.Error as exc:
        logger.warning("[OutputEconomics] Query fehlgeschlagen (%s): %s", sql, exc)
        return []


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def _as_float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return result if result == result and abs(result) != float("inf") else 0.0


def _parse_ts(value: Any) -> Optional[datetime.datetime]:
    """ISO-Zeitstempel oder Unix-Epoch (s/ms) zu einem naiven datetime normalisieren."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if number <= 0:
            return None
        if number > 100_000_000_000:
            number /= 1000.0
        try:
            return datetime.datetime.fromtimestamp(number).replace(tzinfo=None)
        except (ValueError, OSError, OverflowError):
            return None
    text = _as_text(value)
    if not text:
        return None
    if text.replace(".", "", 1).lstrip("-").isdigit():
        return _parse_ts(float(text))
    try:
        parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None)
    except ValueError:
        return None


def _period_key(ts: Optional[datetime.datetime], period: str) -> str:
    if ts is None:
        return "ohne Datum"
    if period == "month":
        return ts.strftime("%Y-%m")
    if period == "week":
        iso = ts.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    return ts.strftime("%Y-%m-%d")


def _date_key(ts: Optional[datetime.datetime]) -> str:
    return ts.strftime("%Y-%m-%d") if ts is not None else ""


def _project_from_note(note: Any) -> str:
    """Projektordner aus ``obsidian_note``/Sidecar-Pfad ableiten."""
    parts = [p for p in _as_text(note).replace("\\", "/").split("/") if p]
    if "01_PROJEKTE" in parts:
        idx = parts.index("01_PROJEKTE")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return parts[0] if parts else ""


def _parse_deliverables(raw: Any) -> Tuple[bool, str]:
    """Prueft eine agent_handoffs-Zeile auf echten Deliverable-Inhalt.

    Rückgabe: (vorhanden, Output-Typ-Hinweis). Leere oder unparsebare
    ``deliverables_json`` zaehlen nicht als Deliverable.
    """
    if isinstance(raw, (dict, list)):
        data: Any = raw
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return False, ""
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return False, ""
    else:
        return False, ""
    payload = (data.get("deliverables") if isinstance(data, dict) and "deliverables" in data else data)
    if isinstance(payload, dict):
        present = any(
            bool(_as_text(value))
            for value in payload.values()
            if isinstance(value, (str, int, float, list, dict))
        )
        hint_source = payload
    elif isinstance(payload, list):
        present = bool(payload)
        hint_source = {}
    elif isinstance(payload, str):
        present = bool(payload.strip())
        hint_source = {}
    else:
        return False, ""
    hint = ""
    if isinstance(hint_source, dict):
        for key in ("output_type", "deliverable_type", "artifact_type", "type", "format"):
            hint = _as_text(hint_source.get(key))
            if hint:
                break
    return present, hint[:80]


def _empty_bucket() -> Dict[str, Any]:
    return {
        "task_count": 0,
        "tokens": 0,
        "estimated_cost_eur": 0.0,
        "actual_cost_eur": 0.0,
        "models": [],
    }


def _add_to_bucket(bucket: Dict[str, Any], record: Mapping[str, Any]) -> None:
    bucket["task_count"] += 1
    bucket["tokens"] += int(record["tokens"])
    bucket["estimated_cost_eur"] += float(record["estimated_cost_eur"])
    bucket["actual_cost_eur"] += float(record["actual_cost_eur"])
    for model in record["models"]:
        if model not in bucket["models"]:
            bucket["models"].append(model)


def _finalize_bucket(bucket: Mapping[str, Any], key_name: str = "", key_value: str = "") -> Dict[str, Any]:
    est = round(float(bucket["estimated_cost_eur"]), 4)
    actual = round(float(bucket["actual_cost_eur"]), 4)
    out: Dict[str, Any] = {}
    if key_name:
        out["key"] = key_value
        out[key_name] = key_value
    out.update(
        {
            "task_count": int(bucket["task_count"]),
            "tokens": int(bucket["tokens"]),
            "estimated_cost_eur": est,
            "actual_cost_eur": actual,
            "cost_delta_eur": round(actual - est, 4),
            "models": list(bucket["models"]),
        }
    )
    return out


def aggregate_output_economics(
    *,
    memory_db_path: Optional[str] = None,
    kanban_meta: Optional[Mapping[str, Any]] = None,
    group_by: str = "project",
    project: Optional[str] = None,
    agent: Optional[str] = None,
    output_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    period: str = "day",
) -> Dict[str, Any]:
    """Aggregiert abgeschlossene Tasks mit Costs-/Token-Rollups.

    Rein lesend: keine Schema- Aenderung, keine Schreiboperation, keine neue
    Tabelle. Fehlende Tabellen/Spalten oder DB-Fehler fuehren zu einer leeren,
    wohlgeformten Aggregation statt zu einem 500er.
    """
    warnings: List[str] = []
    group_norm = str(group_by or "").strip().lower()
    if group_norm not in ALLOWED_GROUP_BY:
        if group_by:
            warnings.append(f"Ungueltiges group_by '{group_by}' -> 'project'.")
        group_norm = "project"
    period_norm = str(period or "").strip().lower()
    if period_norm not in ALLOWED_PERIODS:
        if period:
            warnings.append(f"Ungueltiges period '{period}' -> 'day'.")
        period_norm = "day"

    project_filter = _as_text(project).lower()
    agent_filter = _as_text(agent).lower()
    output_filter = _as_text(output_type).lower()
    from_date = _as_text(date_from)[:10]
    to_date = _as_text(date_to)[:10]
    if from_date and _parse_ts(from_date) is None:
        warnings.append(f"Ungueltiges date_from '{date_from}' ignoriert.")
        from_date = ""
    if to_date and _parse_ts(to_date) is None:
        warnings.append(f"Ungueltiges date_to '{date_to}' ignoriert.")
        to_date = ""
    if from_date and to_date and from_date > to_date:
        warnings.append("date_from liegt nach date_to, Filter liefert keine Zeilen.")

    db_path = memory_db_path or _default_memory_db_path()
    meta = kanban_meta if kanban_meta is not None else _load_kanban_meta()
    meta_tasks: Dict[str, Any] = {}
    if isinstance(meta, dict) and isinstance(meta.get("tasks"), dict):
        meta_tasks = dict(meta["tasks"])

    summary = _empty_bucket()
    summary["deliverable_count"] = 0
    summary["general_count"] = 0
    groups: Dict[str, Dict[str, Any]] = {}
    series: Dict[str, Dict[str, Dict[str, Any]]] = {}
    scanned = 0

    conn = _open_readonly(db_path)
    if conn is None:
        warnings.append(f"Memory-DB nicht lesbar oder nicht vorhanden: {db_path}")
    try:
        if conn is None:
            table_flags = {name: False for name in _KNOWN_TABLES}
        else:
            table_flags = {name: _table_exists(conn, name) for name in _KNOWN_TABLES}
            if not table_flags["tasks"]:
                warnings.append("Tabelle 'tasks' fehlt, leere Aggregation.")

            # Deliverables: mind. eine agent_handoffs-Zeile mit nicht leerem JSON.
            handoffs: Dict[str, Dict[str, Any]] = {}
            if table_flags["agent_handoffs"]:
                for row in _rows(conn, "SELECT task_id, deliverables_json FROM agent_handoffs"):
                    tid = _as_text(row.get("task_id"))
                    if not tid:
                        continue
                    present, hint = _parse_deliverables(row.get("deliverables_json"))
                    info = handoffs.setdefault(tid, {"present": False, "hint": ""})
                    if present:
                        info["present"] = True
                    if hint and not info["hint"]:
                        info["hint"] = hint

            # SSOT fuer tatsaechliche Kosten, Tokens und Modell.
            receipts: Dict[str, Dict[str, Any]] = {}
            if table_flags["execution_receipts_ledger"]:
                for row in _rows(conn, "SELECT * FROM execution_receipts_ledger"):
                    tid = _as_text(row.get("task_id"))
                    if not tid:
                        continue
                    entry = receipts.setdefault(tid, {"count": 0, "tokens": 0, "cost_usd": 0.0, "models": []})
                    entry["count"] += 1
                    entry["tokens"] += _as_int(row.get("prompt_tokens")) + _as_int(row.get("completion_tokens"))
                    entry["cost_usd"] += _as_float(row.get("cost_usd"))
                    model = _as_text(row.get("model_used"))
                    if model and model not in entry["models"]:
                        entry["models"].append(model)

            # Geschaetzte Kosten/Tokens: nur lesen, Tabelle ist ggf. noch nicht angelegt.
            allocations: Dict[str, Dict[str, Any]] = {}
            if table_flags["task_budget_allocations"]:
                for row in _rows(conn, "SELECT * FROM task_budget_allocations"):
                    tid = _as_text(row.get("task_id"))
                    if tid:
                        allocations[tid] = row
            if not table_flags["task_budget_allocations"]:
                warnings.append("task_budget_allocations fehlt, Schätzung aus Sidecar/0.0.")

            task_rows = _rows(conn, "SELECT * FROM tasks") if table_flags["tasks"] else []
            for row in task_rows:
                if _as_text(row.get("status")).lower() != "done":
                    continue
                scanned += 1
                tid = _as_text(row.get("id"))
                if not tid:
                    continue
                tmeta = meta_tasks.get(tid) or {}
                if not isinstance(tmeta, dict):
                    tmeta = {}
                info = handoffs.get(tid) or {"present": False, "hint": ""}
                has_deliverable = bool(info.get("present"))

                if has_deliverable:
                    hint = _as_text(info.get("hint")) or _as_text(
                        tmeta.get("output_type") or tmeta.get("deliverable_type")
                    )
                    output_value = hint or DEFAULT_OUTPUT_TYPE
                else:
                    # M100: Tasks ohne Deliverable fallen immer in den General-Bucket.
                    output_value = GENERAL_OUTPUT_TYPE

                ts = _parse_ts(row.get("finished_at")) or _parse_ts(row.get("created_at"))
                date_value = _date_key(ts)
                period_value = _period_key(ts, period_norm)
                if (from_date or to_date) and not date_value:
                    continue
                if from_date and date_value < from_date:
                    continue
                if to_date and date_value > to_date:
                    continue

                project_value = _as_text(tmeta.get("project")) or _project_from_note(
                    row.get("obsidian_note") or tmeta.get("obsidian")
                ) or "ohne Projekt"
                agent_value = (
                    _as_text(row.get("role"))
                    or _as_text(tmeta.get("agent_profile") or tmeta.get("agent_id"))
                    or "unassigned"
                )
                if project_filter and project_value.lower() != project_filter:
                    continue
                if agent_filter and agent_value.lower() != agent_filter:
                    continue
                if output_filter and output_value.lower() != output_filter:
                    continue

                receipt = receipts.get(tid) or {"count": 0, "tokens": 0, "cost_usd": 0.0, "models": []}
                alloc = allocations.get(tid) or {}
                tokens = _as_int(receipt["tokens"]) or _as_int(alloc.get("tokens_used")) or _as_int(tmeta.get("tokens"))
                if int(receipt["count"]) > 0:
                    actual_eur = float(receipt["cost_usd"]) * USD_TO_EUR_RATE
                else:
                    actual_eur = (
                        _as_float(tmeta.get("actual_cost_eur"))
                        or _as_float(tmeta.get("cost"))
                        or _as_float(alloc.get("cost_used_eur"))
                    )
                est_eur = (
                    _as_float(tmeta.get("estimated_cost_eur"))
                    or _as_float(tmeta.get("cost_estimate_eur"))
                    or _as_float(tmeta.get("cost_limit_eur"))
                    or (_as_float(tmeta.get("cost_limit_usd")) * USD_TO_EUR_RATE)
                    or _as_float(alloc.get("cost_limit_eur"))
                )
                models = list(receipt["models"])
                for model in (_as_text(tmeta.get("model")), _as_text(row.get("model"))):
                    if model and model not in models:
                        models.append(model)

                record: Dict[str, Any] = {
                    "task_id": tid,
                    "project": project_value,
                    "agent_profile": agent_value,
                    "period": period_value,
                    "output_type": output_value,
                    "tokens": max(0, tokens),
                    "estimated_cost_eur": max(0.0, est_eur),
                    "actual_cost_eur": max(0.0, actual_eur),
                    "models": models,
                }
                _add_to_bucket(summary, record)
                if has_deliverable:
                    summary["deliverable_count"] += 1
                else:
                    summary["general_count"] += 1

                group_value = str(record[group_norm])
                _add_to_bucket(groups.setdefault(group_value, _empty_bucket()), record)
                type_period = series.setdefault(output_value, {})
                _add_to_bucket(type_period.setdefault(period_value, _empty_bucket()), record)
    finally:
        if conn is not None:
            conn.close()

    group_key = {"project": "project", "agent_profile": "agent_profile", "period": "period", "output_type": "output_type"}[group_norm]
    group_rows = [_finalize_bucket(bucket, group_key, key) for key, bucket in sorted(groups.items(), key=lambda item: item[0])]
    time_series: List[Dict[str, Any]] = []
    for output_value in sorted(series):
        for period_value in sorted(series[output_value]):
            point = _finalize_bucket(series[output_value][period_value])
            time_series.append(
                {
                    "output_type": output_value,
                    "period": period_value,
                    "task_count": point["task_count"],
                    "tokens": point["tokens"],
                    "estimated_cost_eur": point["estimated_cost_eur"],
                    "actual_cost_eur": point["actual_cost_eur"],
                    "cost_delta_eur": point["cost_delta_eur"],
                }
            )

    summary_out = _finalize_bucket(summary)
    summary_out["deliverable_count"] = int(summary["deliverable_count"])
    summary_out["general_count"] = int(summary["general_count"])

    return {
        "status": "ok",
        "summary": summary_out,
        "groups": group_rows,
        "time_series": time_series,
        "meta": {
            "group_by": group_norm,
            "period": period_norm,
            "filters": {
                "project": _as_text(project) or None,
                "agent": _as_text(agent) or None,
                "output_type": _as_text(output_type) or None,
                "date_from": from_date or None,
                "date_to": to_date or None,
            },
            "task_count_scanned": scanned,
            "sources": {
                "memory_db_path": db_path,
                "tables": table_flags,
                "kanban_meta_tasks": len(meta_tasks),
            },
            "warnings": warnings,
        },
    }
