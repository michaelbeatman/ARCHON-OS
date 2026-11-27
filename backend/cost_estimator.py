"""
backend/cost_estimator.py
Pre-Flight Kosten-Schätzer & Budget-Prognose (Pillar 5 / FinOps).
Schätzt vor dem Start einer Aufgabe anhand von Prompt-Länge, Zielmodell und
erwarteten Output-Tokens die voraussichtlichen Kosten in USD ab.
"""

import datetime
import math
import os
import sqlite3
from typing import Any, Dict, Optional

MODEL_PRICING = {
    "deepseek/deepseek-chat": {"in_per_m": 0.14, "out_per_m": 0.28},
    "deepseek-chat": {"in_per_m": 0.14, "out_per_m": 0.28},
    "anthropic/claude-3-5-sonnet": {"in_per_m": 3.00, "out_per_m": 15.00},
    "claude-3-5-sonnet": {"in_per_m": 3.00, "out_per_m": 15.00},
    "anthropic/claude-3-haiku": {"in_per_m": 0.25, "out_per_m": 1.25},
    "openai/gpt-4o-mini": {"in_per_m": 0.15, "out_per_m": 0.60},
    "openai/gpt-4o": {"in_per_m": 2.50, "out_per_m": 10.00},
    "free-forever": {"in_per_m": 0.0, "out_per_m": 0.0}
}

def estimate_prompt_cost(
    prompt: str,
    model_name: str = "deepseek/deepseek-chat",
    expected_output_tokens: int = 1000,
    task_budget_usd: float = 0.25
) -> Dict[str, Any]:
    """Berechnet die voraussichtlichen Token und Dollar-Kosten eines Auftrags."""
    input_tokens = max(1, len(prompt) // 4)
    m_key = model_name.lower().strip()

    rates = None
    for k, v in MODEL_PRICING.items():
        if k in m_key:
            rates = v
            break

    if rates is None:
        # Fallback: Kostenfrei nur wenn explizit lokal / free im Modellnamen
        if any(tok in m_key for tok in ("free", "local", "ollama")):
            rates = MODEL_PRICING["free-forever"]
        else:
            # Konservativer Standardtarif fuer unbekannte kommerzielle Modelle (Pillar 5 / FinOps)
            rates = {"in_per_m": 2.50, "out_per_m": 10.00}

    in_cost = (input_tokens / 1_000_000.0) * rates["in_per_m"]
    out_cost = (expected_output_tokens / 1_000_000.0) * rates["out_per_m"]
    total_est = in_cost + out_cost

    fits_budget = total_est <= task_budget_usd

    return {
        "status": "success",
        "model": model_name,
        "input_tokens_est": input_tokens,
        "expected_output_tokens": expected_output_tokens,
        "total_tokens_est": input_tokens + expected_output_tokens,
        "estimated_cost_usd": round(total_est, 5),
        "task_budget_usd": task_budget_usd,
        "fits_budget": fits_budget,
        "warning": None if fits_budget else f"Geschätzte Kosten (${total_est:.4f}) überschreiten das Budget (${task_budget_usd:.2f})!"
    }


# ---------------------------------------------------------------------------
# M69: Rollierende 24h-Vendor-Limits.
# Die Reservierung ist atomar (BEGIN IMMEDIATE) und erfolgt VOR der Ausfuehrung.
# Die bestehende Budget-Pruefung in estimate_prompt_cost() bleibt unberuehrt —
# dieser Chokepoint ergaenzt sie, er umgeht sie nicht.
# ---------------------------------------------------------------------------


class VendorLimitError(ValueError):
    """Rollierendes Vendor-Limit ueberschritten — Ausfuehrung blockieren."""


try:
    from backend.db_paths import resolve_db

    VENDOR_DB_FILE = resolve_db("agentic_memory.db")
except Exception:
    VENDOR_DB_FILE = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "agentic_memory.db",
    )

VENDOR_TABLE = "m69_vendor_spend_events"
VENDOR_WINDOW_HOURS = 24
_LIMIT_EPSILON = 1e-9


def _vendor_now_epoch() -> float:
    return datetime.datetime.now(datetime.timezone.utc).timestamp()


def _vendor_db_path(db_path: Optional[str] = None) -> str:
    return str(db_path or VENDOR_DB_FILE)


def _init_vendor_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    with conn:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {VENDOR_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor TEXT NOT NULL,
                model TEXT DEFAULT '',
                amount_usd REAL NOT NULL,
                request_id TEXT DEFAULT '',
                occurred_at TEXT NOT NULL,
                occurred_at_epoch REAL NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{VENDOR_TABLE}_vendor_time "
            f"ON {VENDOR_TABLE}(vendor, occurred_at_epoch)"
        )
    return conn


def _vendor_limits(
    vendor: str,
    *,
    policy: Optional[Dict[str, Any]] = None,
    policy_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Liest die Vendor-Limits aus der M69-Policy; unbekannte Vendor -> fail-closed."""
    from backend.approval_policy_engine import load_approval_policy

    cfg = policy or load_approval_policy(policy_path)
    entry = cfg["vendor_limits"]["vendors"].get(vendor)
    if entry is None:
        raise VendorLimitError(
            f"Vendor '{vendor}' ist in der Policy nicht freigegeben (fail-closed)."
        )
    return {
        "vendor": vendor,
        "window_hours": int(entry["window_hours"]),
        "max_spend_usd": float(entry["max_spend_usd"]),
        "max_calls": int(entry["max_calls"]),
    }


def _vendor_usage(
    conn: sqlite3.Connection, vendor: str, window_hours: int, now: float
) -> Dict[str, float]:
    cutoff = now - window_hours * 3600
    row = conn.execute(
        f"SELECT COALESCE(SUM(amount_usd), 0.0) AS spent, COUNT(*) AS calls "
        f"FROM {VENDOR_TABLE} "
        "WHERE vendor = ? AND occurred_at_epoch >= ? AND occurred_at_epoch <= ?",
        (vendor, cutoff, now),
    ).fetchone()
    return {"spent_usd": float(row["spent"] or 0.0), "calls": int(row["calls"] or 0)}


def _vendor_result(
    vendor: str,
    limits: Dict[str, Any],
    usage: Dict[str, float],
    planned: float,
) -> Dict[str, Any]:
    limit_usd = float(limits["max_spend_usd"])
    max_calls = int(limits["max_calls"])
    allowed = (
        usage["spent_usd"] + planned <= limit_usd + _LIMIT_EPSILON
        and usage["calls"] + 1 <= max_calls
    )
    return {
        "allowed": bool(allowed),
        "reason": "" if allowed else "limit_exceeded",
        "vendor": vendor,
        "window_hours": int(limits["window_hours"]),
        "spent_usd": round(float(usage["spent_usd"]), 5),
        "planned_usd": round(planned, 5),
        "limit_usd": limit_usd,
        "remaining_usd": round(max(0.0, limit_usd - float(usage["spent_usd"]) - planned), 5),
        "calls": int(usage["calls"]),
        "max_calls": max_calls,
    }


def check_vendor_limit(
    vendor: str,
    *,
    planned_cost_usd: float = 0.0,
    policy: Optional[Dict[str, Any]] = None,
    policy_path: Optional[str] = None,
    db_path: Optional[str] = None,
    now_epoch: Optional[float] = None,
) -> Dict[str, Any]:
    """Reine Lesepruefung des rollierenden 24h-Fensters (kein Schreibzugriff)."""
    v = str(vendor or "").strip().lower()
    result: Dict[str, Any] = {
        "allowed": False,
        "reason": "invalid_input",
        "vendor": v,
        "window_hours": VENDOR_WINDOW_HOURS,
        "spent_usd": 0.0,
        "planned_usd": 0.0,
        "limit_usd": 0.0,
        "remaining_usd": 0.0,
        "calls": 0,
        "max_calls": 0,
    }
    try:
        planned = float(planned_cost_usd)
        if not v or not math.isfinite(planned) or planned < 0:
            return result
        limits = _vendor_limits(v, policy=policy, policy_path=policy_path)
        now = _vendor_now_epoch() if now_epoch is None else float(now_epoch)
        conn = _init_vendor_db(_vendor_db_path(db_path))
        try:
            usage = _vendor_usage(conn, v, limits["window_hours"], now)
        finally:
            conn.close()
        return _vendor_result(v, limits, usage, planned)
    except Exception as exc:
        result["reason"] = f"policy_or_store_error: {exc}"
        return result


def reserve_vendor_budget(
    vendor: str,
    planned_cost_usd: float,
    *,
    request_id: str = "",
    model: str = "",
    policy: Optional[Dict[str, Any]] = None,
    policy_path: Optional[str] = None,
    db_path: Optional[str] = None,
    now_epoch: Optional[float] = None,
) -> Dict[str, Any]:
    """Atomare Pruefen-und-Reservieren-Operation vor der Ausfuehrung."""
    v = str(vendor or "").strip().lower()
    planned = float(planned_cost_usd)
    if not v or not math.isfinite(planned) or planned < 0:
        raise VendorLimitError("Vendor und Kostenbetrag muessen gueltig sein.")
    limits = _vendor_limits(v, policy=policy, policy_path=policy_path)
    now = _vendor_now_epoch() if now_epoch is None else float(now_epoch)
    timestamp = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).isoformat()
    conn = _init_vendor_db(_vendor_db_path(db_path))
    event_id = 0
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            usage = _vendor_usage(conn, v, limits["window_hours"], now)
            result = _vendor_result(v, limits, usage, planned)
            if not result["allowed"]:
                return result
            cur = conn.execute(
                f"""
                INSERT INTO {VENDOR_TABLE}
                (vendor, model, amount_usd, request_id, occurred_at,
                 occurred_at_epoch, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (v, str(model or ""), planned, str(request_id or ""), timestamp, now, timestamp),
            )
            event_id = int(cur.lastrowid or 0)
    finally:
        conn.close()
    result["event_id"] = event_id
    return result


def enforce_vendor_limit(
    vendor: str,
    planned_cost_usd: float = 0.0,
    *,
    policy: Optional[Dict[str, Any]] = None,
    policy_path: Optional[str] = None,
    db_path: Optional[str] = None,
    now_epoch: Optional[float] = None,
) -> Dict[str, Any]:
    """Chokepoint: wirft bei Ueberschreitung, bevor ein Task dispatcht wird."""
    result = check_vendor_limit(
        vendor,
        planned_cost_usd=planned_cost_usd,
        policy=policy,
        policy_path=policy_path,
        db_path=db_path,
        now_epoch=now_epoch,
    )
    if not result["allowed"]:
        raise VendorLimitError(
            f"Vendor-Limit blockiert '{vendor}': {result['reason']} "
            f"({result['spent_usd']}/{result['limit_usd']} USD, {result['calls']}/{result['max_calls']} Calls)."
        )
    return result


def finalize_vendor_cost(
    event_id: int, actual_cost_usd: float, *, db_path: Optional[str] = None
) -> bool:
    """Korrigiert eine Reservierung auf die tatsaechlichen Kosten (nach Ausfuehrung)."""
    actual = float(actual_cost_usd)
    if not math.isfinite(actual) or actual < 0:
        raise VendorLimitError("actual_cost_usd muss endlich und >= 0 sein.")
    conn = _init_vendor_db(_vendor_db_path(db_path))
    try:
        with conn:
            cur = conn.execute(
                f"UPDATE {VENDOR_TABLE} SET amount_usd = ? WHERE id = ?",
                (actual, int(event_id)),
            )
            return cur.rowcount == 1
    finally:
        conn.close()
