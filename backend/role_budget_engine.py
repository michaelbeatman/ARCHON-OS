# -*- coding: utf-8 -*-
"""
backend/role_budget_engine.py
=============================
Paperclip-inspired Hard Token & Euro Budget Governance + Complexity-Weighted
Subagent Budget Allocation + Autonomous CEO Hiring for Archon OS.

Capabilities:
1. Per-Role Daily & Monthly Token / EUR Budgets:
   - Enforces hard daily token and Euro limits per agent role in `core_dispatcher`.
   - Tracks daily consumption in SQLite WAL (`agentic_memory.db` -> `role_daily_budget_ledger`).
   - Auto-pauses roles (`status = 'paused_budget'`) when their daily hard cap is reached.
2. Complexity-Weighted Task Budget Splitting:
   - Splits a task's `token_budget` and `cost_limit_eur` (or `cost_limit_usd`) across
     subagents proportional to each subtask's complexity weight, reserving an
     orchestrator/synthesis buffer (15%).
3. Autonomous CEO Hiring (`allow_autonomous_hiring`):
   - Allows the CEO (`executive_decision_architect`) or Orchestrator to dynamically
     spawn and register temporary project specialists with dedicated token/EUR budgets
     and matching skills from `.agents/skills/`.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import uuid
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("archon.role_budget_engine")

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_FILE = os.path.join(WORKSPACE_DIR, "agent_profiles.json")
ORG_HIERARCHY_FILE = os.path.join(WORKSPACE_DIR, "config", "org_hierarchy.json")
USD_TO_EUR_RATE = 0.92

try:
    from backend.db_paths import resolve_db
    BUDGET_DB_PATH = resolve_db("agentic_memory.db")
except Exception:
    BUDGET_DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

_BUDGET_LOCK = threading.RLock()

_AUTHORITY_CACHE: Dict[str, Any] = {"mtime": 0.0, "exec": frozenset(), "lead": frozenset(), "aliases": {}}


def load_authority_registry() -> Dict[str, Any]:
    """D14/D15/MED: EINZIGE SSOT für Autoritäts-Tier ist org_hierarchy.json.

    Frueher standen hier hart codierte String-Sets, die dem Organigramm
    widersprachen (z.B. `labor_law_hr_governance` Tier 3 im Chart, aber
    `executive` im Konsens). Delegation, Konsens-Gewichte und Budget-Tier
    lesen jetzt alle diese Datei. Fail-closed: ohne lesbares Chart gibt es
    keine Executive-/Lead-Rechte.
    """
    try:
        mtime = os.path.getmtime(ORG_HIERARCHY_FILE)
        if _AUTHORITY_CACHE["mtime"] != mtime:
            with open(ORG_HIERARCHY_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            nodes = data.get("nodes") or []
            exec_ids = frozenset(
                str(n.get("id") or "").strip().lower()
                for n in nodes if int(n.get("tier") or 3) == 1 and n.get("id")
            )
            lead_ids = frozenset(
                str(n.get("id") or "").strip().lower()
                for n in nodes if int(n.get("tier") or 3) == 2 and n.get("id")
            )
            aliases = {
                str(k).strip().lower(): str(v).strip().lower()
                for k, v in (data.get("aliases") or {}).items()
                if str(k or "").strip() and str(v or "").strip()
            }
            # Alias-Handles erben den Tier ihres kanonischen Ziels, damit
            # z.B. 'robert' im Boardroom nicht als Spezialist zaehlt.
            exec_ids = frozenset(set(exec_ids) | {a for a, t in aliases.items() if t in exec_ids})
            lead_ids = frozenset(set(lead_ids) | {a for a, t in aliases.items() if t in lead_ids})
            _AUTHORITY_CACHE.update({"mtime": mtime, "exec": exec_ids, "lead": lead_ids, "aliases": aliases})
    except Exception as exc:
        logger.error(
            "[RoleBudget] Autoritäts-SSOT %s nicht lesbar — fail-closed ohne Tier-Rechte: %s",
            ORG_HIERARCHY_FILE, exc,
        )
        return {"exec": frozenset(), "lead": frozenset(), "aliases": {}}
    return {
        "exec": _AUTHORITY_CACHE["exec"],
        "lead": _AUTHORITY_CACHE["lead"],
        "aliases": _AUTHORITY_CACHE["aliases"],
    }


def canonical_tool_name(raw: str) -> str:
    """D15/MED: zentrale Legacy-Tool-Normalisierung aus der SSOT.

    `agent_profiles.json`/`roles.json` sind bereits migriert; dieser Resolver
    funktioniert fuer verbleibende externe/legacy Payloads (z.B. HERMES).
    """
    value = str(raw or "").strip()
    try:
        with open(ORG_HIERARCHY_FILE, "r", encoding="utf-8") as fh:
            aliases = (json.load(fh).get("tool_aliases") or {})
    except Exception:
        aliases = {"FileSystem_MCP": "filesystem", "Calculator": "execute_code", "WebSearch": "web_search"}
    return str(aliases.get(value, value))


def canonical_agent_id(raw: str, known_ids: Optional[set] = None) -> str:
    """Zentrale Alias-Auflösung (SSOT org_hierarchy.json) für alle Pfade."""
    value = str(raw or "").strip()
    if not value:
        return ""
    if value in (known_ids or set()):
        return value
    aliases = load_authority_registry()["aliases"]
    mapped = aliases.get(value.lower()) or aliases.get(value.lower().replace("-", "_"))
    mapped = str(mapped or "").strip()
    if not mapped:
        return value
    if known_ids and mapped not in known_ids:
        logger.warning("[RoleBudget] Alias '%s' zeigt auf unbekanntes Profil '%s'.", value, mapped)
        return value
    return mapped


def authority_tier(agent_id: str) -> str:
    """ executive | lead | specialist — aus der einzigen Autoritäts-SSOT."""
    registry = load_authority_registry()
    aid = str(agent_id or "").strip().lower()
    canonical = registry["aliases"].get(aid, aid)
    if canonical in registry["exec"] or aid in registry["exec"]:
        return "executive"
    if canonical in registry["lead"] or aid in registry["lead"]:
        return "lead"
    return "specialist"


# Rueckwaerts-kompatible Modulebene-Symbole (consensus_gate importiert sie).
_REGISTRY = load_authority_registry()
EXECUTIVE_ROLE_IDS = frozenset(_REGISTRY["exec"])
LEAD_ROLE_IDS = frozenset(_REGISTRY["lead"])

COMPLEXITY_KEYWORDS_HIGH = (
    "architektur", "architecture", "security", "audit", "refactor", "steuer", "tax",
    "vertrag", "contract", "legal", "haftung", "dcf", "valuation", "finanzmodell",
    "migration", "compliance", "dsgvo", "gdpr", "ai-act", "code", "fullstack",
    "datenbank", "database", "penetration", "red-team", "baugb", "medtech", "fda",
)

COMPLEXITY_KEYWORDS_MEDIUM = (
    "analyse", "analysis", "recherche", "research", "strategie", "strategy",
    "konzept", "concept", "wettbewerb", "competitor", "seo", "kampagne", "campaign",
    "outreach", "funnel", "copywriting", "linkedin", "carousel", "skript", "script",
)


def _today_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d")


def _month_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m")


class _ClosingBudgetConn(sqlite3.Connection):
    def __enter__(self):
        super().__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()


def _get_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    target = db_path or BUDGET_DB_PATH
    os.makedirs(os.path.dirname(target), exist_ok=True)
    conn = sqlite3.connect(target, timeout=15.0, factory=_ClosingBudgetConn)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


_INITIALIZED_BUDGET_DBS: set = set()


def init_budget_tables(db_path: Optional[str] = None) -> None:
    # Vorher wurde bei FAST JEDEM Aufruf (check/reserve/settle/usage) ein
    # executescript mit 5 CREATE TABLE + 2 CREATE INDEX ausgefuehrt — ein
    # Dispatch triggert das 5-8x und serialisiert alle Writer. Das Schema
    # aendert sich zur Laufzeit nicht, daher einmal pro DB-Pfad.
    target = db_path or BUDGET_DB_PATH
    if target in _INITIALIZED_BUDGET_DBS:
        return
    with _BUDGET_LOCK:
        if target in _INITIALIZED_BUDGET_DBS:
            return
        with _get_conn(db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS role_daily_budget_ledger (
                    agent_id TEXT NOT NULL,
                    usage_date TEXT NOT NULL,
                    tokens_used INTEGER NOT NULL DEFAULT 0,
                    cost_eur REAL NOT NULL DEFAULT 0.0,
                    cost_usd REAL NOT NULL DEFAULT 0.0,
                    dispatch_count INTEGER NOT NULL DEFAULT 0,
                    paused_at TEXT DEFAULT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (agent_id, usage_date)
                );

                CREATE TABLE IF NOT EXISTS role_budget_policies (
                    agent_id TEXT PRIMARY KEY,
                    daily_token_budget INTEGER NOT NULL DEFAULT 150000,
                    daily_cost_limit_eur REAL NOT NULL DEFAULT 1.50,
                    monthly_cost_limit_eur REAL NOT NULL DEFAULT 30.00,
                    hard_cap_enabled INTEGER NOT NULL DEFAULT 1,
                    auto_pause_on_exceed INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS task_budget_allocations (
                    task_id TEXT PRIMARY KEY,
                    parent_task_id TEXT DEFAULT NULL,
                    agent_id TEXT NOT NULL,
                    token_budget INTEGER NOT NULL DEFAULT 0,
                    tokens_used INTEGER NOT NULL DEFAULT 0,
                    cost_limit_eur REAL NOT NULL DEFAULT 0.0,
                    cost_used_eur REAL NOT NULL DEFAULT 0.0,
                    complexity_weight REAL NOT NULL DEFAULT 1.0,
                    budget_share_pct REAL NOT NULL DEFAULT 100.0,
                    allow_autonomous_hiring INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                -- Atomare Reservierungen für parallele DAG-Nodes: Reserve → Settle/Release.
                -- Ohne Reservierung passieren N Dispatches das Gate und buchen
                -- danach → hartes Cap wird überschritten.
                CREATE TABLE IF NOT EXISTS budget_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    task_id TEXT,
                    node_id TEXT,
                    tokens_reserved INTEGER NOT NULL DEFAULT 0,
                    cost_eur_reserved REAL NOT NULL DEFAULT 0.0,
                    status TEXT NOT NULL DEFAULT 'reserved',
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    settled_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_budget_res_agent ON budget_reservations(agent_id, status);
                CREATE INDEX IF NOT EXISTS idx_budget_res_expiry ON budget_reservations(expires_at);

                CREATE TABLE IF NOT EXISTS autonomous_hired_agents (
                    agent_id TEXT PRIMARY KEY,
                    parent_task_id TEXT NOT NULL,
                    subtask_id TEXT DEFAULT '',
                    person_name TEXT NOT NULL,
                    role_title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    skills_json TEXT NOT NULL DEFAULT '[]',
                    token_budget INTEGER NOT NULL DEFAULT 50000,
                    cost_limit_eur REAL NOT NULL DEFAULT 0.50,
                    status TEXT NOT NULL DEFAULT 'active',
                    hired_by TEXT NOT NULL DEFAULT 'executive_decision_architect',
                    created_at TEXT NOT NULL,
                    dissolved_at TEXT DEFAULT NULL
                );
                """
            )
            conn.commit()
            _INITIALIZED_BUDGET_DBS.add(target)


def get_default_role_budget(agent_id: str) -> Dict[str, Any]:
    aid = (agent_id or "default").strip().lower()
    tier = authority_tier(aid)
    if tier == "executive":
        return {
            "tier": "executive",
            "daily_token_budget": 500_000,
            "daily_cost_limit_eur": 5.00,
            "monthly_cost_limit_eur": 100.00,
            "hard_cap_enabled": True,
            "auto_pause_on_exceed": True,
        }
    if tier == "lead":
        return {
            "tier": "lead",
            "daily_token_budget": 250_000,
            "daily_cost_limit_eur": 2.50,
            "monthly_cost_limit_eur": 50.00,
            "hard_cap_enabled": True,
            "auto_pause_on_exceed": True,
        }
    return {
        "tier": "specialist",
        "daily_token_budget": 150_000,
        "daily_cost_limit_eur": 1.50,
        "monthly_cost_limit_eur": 30.00,
        "hard_cap_enabled": True,
        "auto_pause_on_exceed": True,
    }


def get_role_budget_policy(agent_id: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    init_budget_tables(db_path)
    aid = (agent_id or "default").strip()
    defaults = get_default_role_budget(aid)

    # 1. Check explicit DB policy override
    with _get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM role_budget_policies WHERE agent_id = ?",
            (aid,),
        ).fetchone()
        if row:
            return {
                "agent_id": aid,
                "tier": defaults["tier"],
                "daily_token_budget": int(row["daily_token_budget"]),
                "daily_cost_limit_eur": float(row["daily_cost_limit_eur"]),
                "monthly_cost_limit_eur": float(row["monthly_cost_limit_eur"]),
                "hard_cap_enabled": bool(row["hard_cap_enabled"]),
                "auto_pause_on_exceed": bool(row["auto_pause_on_exceed"]),
            }

    # 2. Check agent_profiles.json fields if present
    if os.path.exists(PROFILES_FILE):
        try:
            with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                profiles = json.load(f)
            prof = next((p for p in profiles if p.get("id") == aid), None)
            if prof:
                return {
                    "agent_id": aid,
                    "tier": defaults["tier"],
                    "daily_token_budget": int(prof.get("daily_token_budget") or defaults["daily_token_budget"]),
                    "daily_cost_limit_eur": float(
                        prof.get("daily_cost_limit_eur")
                        if prof.get("daily_cost_limit_eur") is not None
                        else defaults["daily_cost_limit_eur"]
                    ),
                    "monthly_cost_limit_eur": float(
                        prof.get("monthly_cost_limit_eur")
                        if prof.get("monthly_cost_limit_eur") is not None
                        else defaults["monthly_cost_limit_eur"]
                    ),
                    "hard_cap_enabled": bool(prof.get("hard_cap_enabled", True)),
                    "auto_pause_on_exceed": bool(prof.get("auto_pause_on_exceed", True)),
                }
        except Exception as exc:
            logger.debug(f"[RoleBudget] Konnte agent_profiles.json nicht lesen: {exc}")

    return {"agent_id": aid, **defaults}


def set_role_budget_policy(
    agent_id: str,
    daily_token_budget: Optional[int] = None,
    daily_cost_limit_eur: Optional[float] = None,
    monthly_cost_limit_eur: Optional[float] = None,
    hard_cap_enabled: Optional[bool] = None,
    auto_pause_on_exceed: Optional[bool] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    init_budget_tables(db_path)
    aid = (agent_id or "").strip()
    if not aid:
        raise ValueError("agent_id_required")

    current = get_role_budget_policy(aid, db_path=db_path)
    new_tok = max(1000, int(daily_token_budget)) if daily_token_budget is not None else current["daily_token_budget"]
    new_eur = max(0.01, float(daily_cost_limit_eur)) if daily_cost_limit_eur is not None else current["daily_cost_limit_eur"]
    new_month = max(0.10, float(monthly_cost_limit_eur)) if monthly_cost_limit_eur is not None else current["monthly_cost_limit_eur"]
    new_hard = bool(hard_cap_enabled) if hard_cap_enabled is not None else current["hard_cap_enabled"]
    new_pause = bool(auto_pause_on_exceed) if auto_pause_on_exceed is not None else current["auto_pause_on_exceed"]
    now_iso = datetime.datetime.now().isoformat()

    with _BUDGET_LOCK:
        with _get_conn(db_path) as conn:
            conn.execute(
                """
                INSERT INTO role_budget_policies (
                    agent_id, daily_token_budget, daily_cost_limit_eur,
                    monthly_cost_limit_eur, hard_cap_enabled, auto_pause_on_exceed, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    daily_token_budget = excluded.daily_token_budget,
                    daily_cost_limit_eur = excluded.daily_cost_limit_eur,
                    monthly_cost_limit_eur = excluded.monthly_cost_limit_eur,
                    hard_cap_enabled = excluded.hard_cap_enabled,
                    auto_pause_on_exceed = excluded.auto_pause_on_exceed,
                    updated_at = excluded.updated_at
                """,
                (aid, new_tok, new_eur, new_month, int(new_hard), int(new_pause), now_iso),
            )
            # Clear paused_at for today if budget was raised
            today = _today_str()
            conn.execute(
                """
                UPDATE role_daily_budget_ledger
                SET paused_at = NULL, updated_at = ?
                WHERE agent_id = ? AND usage_date = ? AND tokens_used < ? AND cost_eur < ?
                """,
                (now_iso, aid, today, new_tok, new_eur),
            )
            conn.commit()

    return get_role_budget_policy(aid, db_path=db_path)


def get_role_usage_today(agent_id: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    init_budget_tables(db_path)
    aid = (agent_id or "default").strip()
    today = _today_str()
    month_prefix = _month_str()

    with _get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM role_daily_budget_ledger WHERE agent_id = ? AND usage_date = ?",
            (aid, today),
        ).fetchone()
        month_row = conn.execute(
            "SELECT COALESCE(SUM(tokens_used), 0) AS m_tok, COALESCE(SUM(cost_eur), 0.0) AS m_eur "
            "FROM role_daily_budget_ledger WHERE agent_id = ? AND usage_date LIKE ?",
            (aid, f"{month_prefix}%"),
        ).fetchone()

    tokens_today = int(row["tokens_used"]) if row else 0
    cost_eur_today = round(float(row["cost_eur"]), 4) if row else 0.0
    dispatches_today = int(row["dispatch_count"]) if row else 0
    paused_at = row["paused_at"] if row else None

    policy = get_role_budget_policy(aid, db_path=db_path)
    tok_limit = max(1, policy["daily_token_budget"])
    eur_limit = max(0.0001, policy["daily_cost_limit_eur"])

    tok_pct = round(min(100.0, (tokens_today / tok_limit) * 100.0), 1)
    eur_pct = round(min(100.0, (cost_eur_today / eur_limit) * 100.0), 1)
    # F-010: das Monatslimit ist kein Anzeigewert mehr, sondern hart.
    month_eur = float(month_row["m_eur"]) if month_row else 0.0
    exceeded = (
        (tokens_today >= tok_limit)
        or (cost_eur_today >= eur_limit)
        or (month_eur >= float(policy["monthly_cost_limit_eur"]))
    )

    return {
        "agent_id": aid,
        "date": today,
        "tier": policy["tier"],
        "tokens_used_today": tokens_today,
        "daily_token_budget": policy["daily_token_budget"],
        "token_utilization_pct": tok_pct,
        "cost_eur_today": cost_eur_today,
        "daily_cost_limit_eur": policy["daily_cost_limit_eur"],
        "cost_utilization_pct": eur_pct,
        "tokens_used_month": int(month_row["m_tok"]) if month_row else tokens_today,
        "cost_eur_month": round(float(month_row["m_eur"]), 4) if month_row else cost_eur_today,
        "monthly_cost_limit_eur": policy["monthly_cost_limit_eur"],
        "dispatches_today": dispatches_today,
        "hard_cap_enabled": policy["hard_cap_enabled"],
        "is_exceeded": exceeded,
        "paused_at": paused_at,
        "budget_status": "paused_budget" if (exceeded and policy["hard_cap_enabled"]) else (
            "warning" if max(tok_pct, eur_pct) >= 80.0 else "ok"
        ),
    }


def check_budget_gate(
    agent_id: str,
    task_id: Optional[str] = None,
    estimated_tokens: int = 500,
    estimated_cost_eur: float = 0.001,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Pre-Flight Gate for `core_dispatcher`:
    Checks both the role's daily hard token/EUR budget AND any task-level budget allocation.
    """
    # Zentrale BudgetBank: eine einzige Entscheidungsstelle, die auch aktive
    # Reservierungen paralleler DAG-Nodes berücksichtigt (kein TOCTOU mehr).
    bank = BudgetBank(db_path=db_path) if db_path else budget_bank
    return bank.check(
        agent_id=agent_id,
        task_id=task_id,
        estimated_tokens=estimated_tokens,
        estimated_cost_eur=estimated_cost_eur,
    )


def record_budget_usage(
    agent_id: str,
    tokens_used: int,
    cost_usd: float = 0.0,
    cost_eur: Optional[float] = None,
    task_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Duenner Alias auf ``BudgetBank.settle()``.

    Beide Gate-Funktionen gehen jetzt ueber die zentrale BudgetBank. Eine
    zweite, abweichende Ledger-Schreiblogik ausserhalb der Bank gab es frueher
    hier — genau das machte die Funktion tot und das Cap inkonsistent.
    """
    bank = BudgetBank(db_path=db_path) if db_path else budget_bank
    eur = max(0.0, float(cost_eur)) if cost_eur is not None else None
    return bank.settle(
        None,  # keine Reservierung -> Direktbuchung des echten Verbrauchs
        actual_tokens=tokens_used,
        actual_cost_usd=cost_usd,
        cost_eur=eur,
        agent_id=agent_id,
        task_id=task_id,
    )


# =========================================================================
# 2. COMPLEXITY-WEIGHTED SUBTASK BUDGET SPLITTING
# =========================================================================

def score_subtask_complexity(
    role_or_agent_id: str,
    mandate_text: str,
    explicit_complexity: Optional[str] = None,
) -> float:
    """
    Calculates a complexity weight (0.7 .. 2.0) for a subtask based on explicit
    complexity labels, specialist domain, and mandate keywords.
    """
    if explicit_complexity:
        low_c = str(explicit_complexity).strip().lower()
        if low_c in ("critical", "very_high", "sehr_hoch"):
            return 1.8
        if low_c in ("high", "hoch", "complex"):
            return 1.45
        if low_c in ("low", "niedrig", "simple"):
            return 0.8
        if low_c in ("medium", "mittel", "normal"):
            return 1.0

    combined = f"{role_or_agent_id} {mandate_text}".lower()
    high_hits = sum(1 for kw in COMPLEXITY_KEYWORDS_HIGH if kw in combined)
    med_hits = sum(1 for kw in COMPLEXITY_KEYWORDS_MEDIUM if kw in combined)

    weight = 1.0 + min(0.75, high_hits * 0.18) + min(0.25, med_hits * 0.08)
    if len(mandate_text or "") > 400:
        weight += 0.15
    elif len(mandate_text or "") < 80:
        weight -= 0.10

    return round(max(0.7, min(2.0, weight)), 2)


def _resolve_parent_budget(
    parent_task_id: str,
    trajectory_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Elternbudget NUR aus Root-Intake/Trajectory — niemals neu erfinden."""
    try:
        if trajectory_id:
            from backend.trajectory_budget import get_trajectory
            row = get_trajectory(trajectory_id, db_path=db_path) if db_path else get_trajectory(trajectory_id)
            if row and int(row.get("max_tokens") or 0) > 0:
                return {"token_budget": int(row["max_tokens"]), "cost_limit_eur": None,
                        "source": "trajectory_budgets"}
    except Exception:
        pass
    try:
        with _get_conn(db_path) as conn:
            row = conn.execute(
                "SELECT token_budget, cost_limit_eur FROM task_budget_allocations WHERE task_id = ?",
                (parent_task_id,),
            ).fetchone()
            if row and int(row["token_budget"] or 0) > 0:
                return {"token_budget": int(row["token_budget"]),
                        "cost_limit_eur": float(row["cost_limit_eur"] or 0.0) or None,
                        "source": "task_budget_allocations"}
    except Exception:
        pass
    return {}


def _no_parent_budget_result(parent_task_id: str) -> Dict[str, Any]:
    result = {
        "status": "blocked", "block_kind": "no_parent_budget",
        "failure_reason": "NO_PARENT_BUDGET", "parent_task_id": parent_task_id,
        "reason": "Kein Elternbudget vorhanden — Budget-Minting pro Hop ist untersagt.",
        "total_token_budget": 0, "total_cost_limit_eur": 0.0,
        "orchestrator_reserve_tokens": 0, "orchestrator_reserve_eur": 0.0,
        "allocations": [],
    }
    try:
        from backend.trajectory_budget import _audit
        _audit(str(parent_task_id), "NO_PARENT_BUDGET — Subagent-Allokation blockiert", str(parent_task_id))
    except Exception:
        pass
    return result


def allocate_task_budget_to_subagents(
    parent_task_id: str,
    total_token_budget: int,
    subtasks: List[Dict[str, Any]],
    total_cost_limit_eur: Optional[float] = None,
    orchestrator_reserve_pct: float = 0.15,
    db_path: Optional[str] = None,
    trajectory_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Splits a parent task's token & EUR budget across its subagents weighted by
    task complexity. Reserves `orchestrator_reserve_pct` (default 15%) for the
    Orchestrator triage & Lisa synthesis loop.

    D13/HIGH: fehlendes Elternbudget ist `blocked/NO_PARENT_BUDGET`, kein
    Fallback-Minting. Nur der Root-Intake darf ein Budget setzen.
    """
    init_budget_tables(db_path)
    tot_tokens = max(0, int(total_token_budget or 0))
    tot_eur_given = float(total_cost_limit_eur or 0.0)
    if tot_tokens <= 0:
        parent = _resolve_parent_budget(parent_task_id, trajectory_id, db_path)
        if not parent:
            return _no_parent_budget_result(parent_task_id)
        tot_tokens = int(parent["token_budget"])
        if tot_eur_given <= 0 and parent.get("cost_limit_eur"):
            tot_eur_given = float(parent["cost_limit_eur"])

    if tot_eur_given <= 0:
        # EUR-Wert ist eine Umrechnung des BESTEHENDEN Root-Budgets, kein neues
        # Budget: 1.25 EUR pro 100k Tokens (blended).
        tot_eur = round((tot_tokens / 100_000.0) * 1.25, 2)
    else:
        tot_eur = round(tot_eur_given, 2)

    if not subtasks:
        now_iso = datetime.datetime.now().isoformat()
        with _BUDGET_LOCK:
            with _get_conn(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO task_budget_allocations (
                        task_id, parent_task_id, agent_id, token_budget, cost_limit_eur,
                        complexity_weight, budget_share_pct, status, created_at, updated_at
                    )
                    VALUES (?, NULL, ?, ?, ?, 1.0, 100.0, 'active', ?, ?)
                    ON CONFLICT(task_id) DO UPDATE SET
                        token_budget = excluded.token_budget,
                        cost_limit_eur = excluded.cost_limit_eur,
                        updated_at = excluded.updated_at
                    """,
                    (parent_task_id, "default", tot_tokens, tot_eur, now_iso, now_iso),
                )
                conn.commit()
        return {
            "parent_task_id": parent_task_id,
            "total_token_budget": tot_tokens,
            "total_cost_limit_eur": tot_eur,
            "orchestrator_reserve_tokens": tot_tokens,
            "orchestrator_reserve_eur": tot_eur,
            "allocations": [
                {
                    "task_id": parent_task_id,
                    "agent_id": "default",
                    "token_budget": tot_tokens,
                    "cost_limit_eur": tot_eur,
                    "budget_share_pct": 100.0,
                }
            ],
        }

    reserve_pct = max(0.0, min(0.40, float(orchestrator_reserve_pct)))
    orch_tokens = int(round(tot_tokens * reserve_pct))
    orch_eur = round(tot_eur * reserve_pct, 4)

    pool_tokens = max(1000, tot_tokens - orch_tokens)
    pool_eur = max(0.01, tot_eur - orch_eur)

    weights: List[float] = []
    for sub in subtasks:
        w = sub.get("complexity_weight")
        if isinstance(w, (int, float)) and w > 0:
            weights.append(float(w))
        else:
            weights.append(
                score_subtask_complexity(
                    role_or_agent_id=str(sub.get("agent_id") or sub.get("role") or ""),
                    mandate_text=str(sub.get("mandate") or sub.get("body") or sub.get("title") or ""),
                    explicit_complexity=sub.get("complexity"),
                )
            )

    weight_sum = sum(weights) or 1.0
    now_iso = datetime.datetime.now().isoformat()
    allocations: List[Dict[str, Any]] = []

    with _BUDGET_LOCK:
        with _get_conn(db_path) as conn:
            # Record parent task allocation
            conn.execute(
                """
                INSERT INTO task_budget_allocations (
                    task_id, parent_task_id, agent_id, token_budget, cost_limit_eur,
                    complexity_weight, budget_share_pct, status, created_at, updated_at
                )
                VALUES (?, NULL, 'orchestrator', ?, ?, 1.0, ?, 'active', ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    token_budget = excluded.token_budget,
                    cost_limit_eur = excluded.cost_limit_eur,
                    updated_at = excluded.updated_at
                """,
                (parent_task_id, tot_tokens, tot_eur, round(reserve_pct * 100.0, 1), now_iso, now_iso),
            )

            for idx, (sub, w) in enumerate(zip(subtasks, weights)):
                share = w / weight_sum
                sub_tok = max(2000, int(round(pool_tokens * share)))
                sub_eur = max(0.01, round(pool_eur * share, 4))
                share_pct = round(share * (1.0 - reserve_pct) * 100.0, 1)
                sub_id = str(sub.get("id") or sub.get("task_id") or f"{parent_task_id}-sub{idx+1}")
                sub_agent = str(sub.get("agent_id") or sub.get("assignee") or "default")

                sub["token_budget"] = sub_tok
                sub["estimated_tokens"] = sub_tok
                sub["cost_limit_eur"] = round(sub_eur, 2)
                sub["estimated_cost_eur"] = round(sub_eur, 2)
                sub["cost_limit_usd"] = round(sub_eur / USD_TO_EUR_RATE, 2)
                sub["complexity_weight"] = w
                sub["budget_share_pct"] = share_pct

                conn.execute(
                    """
                    INSERT INTO task_budget_allocations (
                        task_id, parent_task_id, agent_id, token_budget, cost_limit_eur,
                        complexity_weight, budget_share_pct, status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                    ON CONFLICT(task_id) DO UPDATE SET
                        parent_task_id = excluded.parent_task_id,
                        agent_id = excluded.agent_id,
                        token_budget = excluded.token_budget,
                        cost_limit_eur = excluded.cost_limit_eur,
                        complexity_weight = excluded.complexity_weight,
                        budget_share_pct = excluded.budget_share_pct,
                        updated_at = excluded.updated_at
                    """,
                    (sub_id, parent_task_id, sub_agent, sub_tok, sub_eur, w, share_pct, now_iso, now_iso),
                )

                allocations.append({
                    "subtask_id": sub_id,
                    "agent_id": sub_agent,
                    "role": sub.get("role") or sub_agent,
                    "complexity_weight": w,
                    "budget_share_pct": share_pct,
                    "token_budget": sub_tok,
                    "cost_limit_eur": round(sub_eur, 2),
                })
            conn.commit()

    return {
        "parent_task_id": parent_task_id,
        "total_token_budget": tot_tokens,
        "total_cost_limit_eur": tot_eur,
        "orchestrator_reserve_tokens": orch_tokens,
        "orchestrator_reserve_eur": round(orch_eur, 2),
        "allocations": allocations,
    }


# =========================================================================
# 3. AUTONOMOUS CEO HIRING (DYNAMIC SPECIALIST RECRUITMENT FOR TASKS)
# =========================================================================

def _discover_matching_skills(text: str, max_skills: int = 8) -> List[str]:
    """Matches installed skills in `.agents/skills/` to a task description."""
    skills_dir = os.path.join(WORKSPACE_DIR, ".agents", "skills")
    low = (text or "").lower()
    matched: List[str] = []

    keyword_skill_map = [
        (("linkedin", "social", "hook", "post", "feed", "ghostwrit"), ["li-post", "li-human", "li-carousel", "li-comment", "li-plan", "anti-ai-slop"]),
        (("outreach", "dm", "akquise", "lead", "inbox"), ["li-dm", "li-inbox", "li-profile", "li-reply"]),
        (("seo", "geo", "keyword", "ranking", "schema"), ["seo", "seo-audit", "seo-geo", "seo-schema", "seo-content"]),
        (("video", "short", "tiktok", "youtube", "reel", "clip"), ["kinocut", "kinocut-repurpose", "li-repurpose"]),
        (("n8n", "webhook", "workflow", "automat"), ["n8n-automation-mesh", "agent-skills-hub"]),
        (("patent", "ip", "prior art", "marke"), ["patsnap-search"]),
        (("steuer", "ust", "mwst", "buchhaltung", "finanz"), ["auto-calculate-vat-split"]),
        (("browser", "scrape", "web", "formular"), ["agent-browser-navigator", "frontend-reverse-engineer"]),
        (("code", "python", "refactor", "test", "review"), ["simplify-code", "sdlc-review", "claude-code"]),
    ]

    for kws, skill_ids in keyword_skill_map:
        if any(k in low for k in kws):
            for sid in skill_ids:
                if sid not in matched:
                    matched.append(sid)

    if os.path.isdir(skills_dir):
        try:
            for entry in os.listdir(skills_dir):
                if len(matched) >= max_skills:
                    break
                if entry in matched:
                    continue
                tokens = [t for t in re.split(r"[-_]+", entry.lower()) if len(t) >= 4]
                if any(t in low for t in tokens):
                    matched.append(entry)
        except Exception as _exc:
            logger.debug("[role_budget_engine] Ignorierte Ausnahme (Z.713): %s", _exc)

    if "anti-ai-slop" not in matched:
        matched.append("anti-ai-slop")
    return matched[:max_skills]


def ceo_autonomous_hire_specialist(
    parent_task_id: str,
    role_title: str,
    mandate: str,
    person_name: Optional[str] = None,
    category: str = "1. Strategy, Leadership & Life Architecture",
    token_budget: int = 45_000,
    cost_limit_eur: float = 0.55,
    subtask_id: str = "",
    model: str = "deepseek/deepseek-chat",
    register_in_profiles_json: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Spawns a temporary specialist agent hired by the CEO (`executive_decision_architect`)
    for a specific task, complete with tailored skills, system prompt, and hard token/EUR budget.
    """
    init_budget_tables(db_path)
    clean_role = (role_title or "Project Task-Force Specialist").strip()
    slug = re.sub(r"[^a-z0-9]+", "_", clean_role.lower()).strip("_")[:24] or "specialist"
    short_hash = hashlib.sha256(f"{parent_task_id}:{clean_role}:{uuid.uuid4().hex[:6]}".encode()).hexdigest()[:6]
    agent_id = f"hired_{slug}_{short_hash}"

    first_names = ["Dr. Lukas", "Maya", "Jonas", "Elena", "Rafael", "Nora", "Leonard", "Viktor"]
    last_names = ["Vance", "Berg", "Keller", "Lindqvist", "Sterling", "Moreau", "Falk", "Novak"]
    h_idx = int(short_hash, 16)
    p_name = (person_name or f"{first_names[h_idx % len(first_names)]} {last_names[(h_idx // 8) % len(last_names)]}").strip()

    skills = _discover_matching_skills(f"{clean_role} {mandate}")
    now_iso = datetime.datetime.now().isoformat()

    sys_prompt = (
        f"# {p_name} — {clean_role} (`@{agent_id}`)\n"
        f"**Rekrutiert durch:** Robert (CEO — Autonomous Hiring) | **Projekt-Task:** `{parent_task_id}`\n"
        f"**Token-Budget:** {token_budget:,} Tokens | **Kosten-Limit:** {cost_limit_eur:.2f} €\n\n"
        f"Du wurdest als spezialisierter Ad-hoc-Experte für folgendes Mandat eingestellt:\n"
        f"{mandate}\n\n"
        f"Arbeite präzise, faktenbasiert, ohne KI-Floskeln und liefere ein direkt verwertbares Ergebnis."
    )

    with _BUDGET_LOCK:
        with _get_conn(db_path) as conn:
            conn.execute(
                """
                INSERT INTO autonomous_hired_agents (
                    agent_id, parent_task_id, subtask_id, person_name, role_title,
                    category, skills_json, token_budget, cost_limit_eur, status,
                    hired_by, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 'executive_decision_architect', ?)
                """,
                (
                    agent_id,
                    parent_task_id,
                    subtask_id,
                    p_name,
                    clean_role,
                    category,
                    json.dumps(skills, ensure_ascii=False),
                    int(token_budget),
                    float(cost_limit_eur),
                    now_iso,
                ),
            )
            conn.commit()

        set_role_budget_policy(
            agent_id=agent_id,
            daily_token_budget=int(token_budget),
            daily_cost_limit_eur=float(cost_limit_eur),
            monthly_cost_limit_eur=float(cost_limit_eur) * 5.0,
            hard_cap_enabled=True,
            auto_pause_on_exceed=True,
            db_path=db_path,
        )

    return {
        "agent_id": agent_id,
        "person_name": p_name,
        "name": clean_role,
        "role": clean_role,
        "category": category,
        "skills": skills,
        "model": model,
        "system_prompt": sys_prompt,
        "token_budget": int(token_budget),
        "cost_limit_eur": round(float(cost_limit_eur), 2),
        "parent_task_id": parent_task_id,
        "subtask_id": subtask_id,
        "hired_by": "executive_decision_architect",
        "ephemeral": True,
        "status": "active",
        "created_at": now_iso,
    }


def plan_and_decompose_task_with_budgets(
    parent_task_id: str,
    title: str,
    body: str,
    total_token_budget: Optional[int] = None,
    total_cost_limit_eur: Optional[float] = None,
    allow_autonomous_hiring: bool = False,
    db_path: Optional[str] = None,
    trajectory_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Analyzes a task, selects the optimal 2-3 existing roster specialists,
    optionally hires an ad-hoc specialist via CEO Autonomous Hiring if
    `allow_autonomous_hiring` is enabled, and splits the task's token/EUR
    budget across all subtasks by complexity.
    """
    init_budget_tables(db_path)
    text_low = f"{title} {body}".lower()

    nominated: List[Dict[str, Any]] = []

    # Domain routing rules to select best roster agents
    routing_rules = [
        (("linkedin", "social media", "hook", "carousel", "post", "thought leadership"), "linkedin_social_media_specialist", "LinkedIn & Social Media Growth Specialist", "Erstelle den LinkedIn-/Social-Media-Content nach voice.md mit Hook-Varianten und Human-Score-Prüfung."),
        (("ghostwrit", "story", "essay", "newsletter"), "storyteller_ghostwriter", "Executive Ghostwriter", "Verfasse den redaktionellen Haupttext mit starker Story-Struktur und Zahlenbelegen."),
        (("repurpos", "short", "tiktok", "youtube", "multi-channel"), "content_repurposing_specialist", "Multi-Channel Repurposing Strategist", "Adaptiere den Kerninhalt für Kurzvideo-, Thread- und Multi-Channel-Formate."),
        (("seo", "keyword", "geo", "ranking", "suchmaschine"), "seo_geo_specialist", "Technical SEO & GEO Lead", "Optimiere Struktur, Entitäten, Schema.org und Suchintention."),
        (("wettbewerb", "competitor", "markt", "radar", "recherche", "studie"), "research_scout", "Primary Market & Intelligence Scout", "Führe eine belastbare Quellen-, Markt- und Wettbewerbsanalyse mit Primärzitaten durch."),
        (("code", "python", "api", "frontend", "backend", "bug", "feature", "ui"), "senior_fullstack_engineer", "Staff Fullstack Software Engineer", "Implementiere und verifiziere die technische Lösung sauber im Code."),
        (("architektur", "system", "docker", "n8n", "orchestr"), "system_architect_orchestrator", "Chief Distributed Systems Architect", "Entwirf die System- und Schnittstellenarchitektur sowie die Governance-Grenzen."),
        (("vertrag", "recht", "agb", "haftung", "jurist"), "commercial_jurist_contracts", "Commercial Contracts Counsel", "Prüfe die vertraglichen und haftungsrechtlichen Rahmenbedingungen."),
        (("steuer", "holding", "ust", "finanz", "budget", "dcf", "kalkulation"), "finance_lead", "VP of Finance & Treasury", "Erstelle die kaufmännische Kalkulation, Budget- und Wirtschaftlichkeitsprüfung."),
        (("immobilie", "bau", "baugb", "kfw", "objekt"), "construction_project_manager", "Senior Construction & Delivery Director", "Bewerte Bau-, Genehmigungs- und Projektentwicklungsaspekte."),
    ]

    for kws, aid, role_label, default_mandate in routing_rules:
        if any(k in text_low for k in kws) and len(nominated) < 3:
            nominated.append({
                "agent_id": aid,
                "role": role_label,
                "mandate": f"{default_mandate}\n\nKontext: {title}\n{body}".strip(),
            })

    if not nominated:
        nominated.append({
            "agent_id": "research_scout",
            "role": "Primary Market & Intelligence Scout",
            "mandate": f"Recherchiere Fakten, Grundlagen und Lösungsoptionen für: {title}\n{body}".strip(),
        })
        nominated.append({
            "agent_id": "executive_decision_architect",
            "role": "CEO — Chief Executive Officer",
            "mandate": f"Erstelle die strategische Entscheidungsvorlage und Maßnahmenmatrix für: {title}".strip(),
        })

    hired_specialist: Optional[Dict[str, Any]] = None
    if allow_autonomous_hiring:
        # CEO hires a dedicated project specialist tailored specifically to this task's niche
        custom_role_title = f"Ad-hoc Task-Force Specialist: {title[:42]}"
        custom_mandate = (
            f"Spezialmandat (CEO Autonomous Hiring) für Aufgabe '{title}':\n"
            f"Bearbeite die spezifischen Fach- und Qualitätsanforderungen von '{body or title}' "
            f"und liefere ein direkt umsetzbares Spezial-Artefakt für die Endsynthese."
        )
        # Preliminary budget estimate for hired agent (will be refined by allocate_task_budget_to_subagents)
        hired_specialist = ceo_autonomous_hire_specialist(
            parent_task_id=parent_task_id,
            role_title=custom_role_title,
            mandate=custom_mandate,
            db_path=db_path,
        )
        nominated.append({
            "agent_id": hired_specialist["agent_id"],
            "person_name": hired_specialist["person_name"],
            "role": hired_specialist["role"],
            "mandate": custom_mandate,
            "complexity": "high",
            "is_autonomously_hired": True,
        })

    eff_tokens = int(total_token_budget) if (total_token_budget and total_token_budget > 0) else 0
    budget_plan = allocate_task_budget_to_subagents(
        parent_task_id=parent_task_id,
        total_token_budget=eff_tokens,
        subtasks=nominated,
        total_cost_limit_eur=total_cost_limit_eur,
        db_path=db_path,
        trajectory_id=trajectory_id,
    )
    if str(budget_plan.get("status") or "") == "blocked":
        return {
            "status": "blocked", "block_kind": "no_parent_budget",
            "failure_reason": "NO_PARENT_BUDGET", "parent_task_id": parent_task_id,
            "subtasks": [], "hired_specialist": None, "budget_plan": budget_plan,
        }

    # Update hired specialist's budget policy to match its exact complexity-weighted share
    if hired_specialist:
        alloc = next((a for a in budget_plan["allocations"] if a["agent_id"] == hired_specialist["agent_id"]), None)
        if alloc:
            set_role_budget_policy(
                agent_id=hired_specialist["agent_id"],
                daily_token_budget=alloc["token_budget"],
                daily_cost_limit_eur=alloc["cost_limit_eur"],
                db_path=db_path,
            )
            hired_specialist["token_budget"] = alloc["token_budget"]
            hired_specialist["cost_limit_eur"] = alloc["cost_limit_eur"]

    return {
        "parent_task_id": parent_task_id,
        "allow_autonomous_hiring": allow_autonomous_hiring,
        "hired_specialist": hired_specialist,
        "subtasks": nominated,
        "budget_plan": budget_plan,
    }


def list_all_role_budgets(
    profiles: Optional[List[Dict[str, Any]]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Returns budget policies and today's live token/EUR consumption across all roles."""
    init_budget_tables(db_path)
    if profiles is None:
        if os.path.exists(PROFILES_FILE):
            try:
                with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                    profiles = json.load(f)
            except Exception:
                profiles = []
        else:
            profiles = []

    items: List[Dict[str, Any]] = []
    seen_ids = set()
    for p in profiles:
        aid = p.get("id")
        if not aid:
            continue
        seen_ids.add(aid)
        u = get_role_usage_today(aid, db_path=db_path)
        u["person_name"] = p.get("person_name") or p.get("name") or aid
        u["role_name"] = p.get("name") or aid
        u["category"] = p.get("category") or "Spezialist"
        items.append(u)

    # Include any active autonomously hired agents
    with _get_conn(db_path) as conn:
        hired_rows = conn.execute(
            "SELECT * FROM autonomous_hired_agents WHERE status = 'active' ORDER BY created_at DESC"
        ).fetchall()
    for hr in hired_rows:
        aid = hr["agent_id"]
        if aid in seen_ids:
            continue
        u = get_role_usage_today(aid, db_path=db_path)
        u["person_name"] = hr["person_name"]
        u["role_name"] = hr["role_title"]
        u["category"] = hr["category"]
        u["ephemeral"] = True
        u["parent_task_id"] = hr["parent_task_id"]
        items.append(u)

    total_tokens_today = sum(i["tokens_used_today"] for i in items)
    total_eur_today = round(sum(i["cost_eur_today"] for i in items), 4)
    paused_count = sum(1 for i in items if i["budget_status"] == "paused_budget")

    return {
        "date": _today_str(),
        "total_roles": len(items),
        "total_tokens_today": total_tokens_today,
        "total_cost_eur_today": total_eur_today,
        "paused_roles_count": paused_count,
        "roles": items,
    }


# =========================================================================
# ZENTRALE BUDGET-BANK — Reserve → Settle/Release (atomar)
# =========================================================================

class BudgetBank:
    """Einzige Instanz, die Budget-Entscheidungen trifft.

    statt "check then use" (TOCTOU): jede side-effektive Ausführung reserviert
    ihr Budget unter BEGIN IMMEDIATE und settet/release danach. Parallele
    DAG-Nodes können damit das harte Cap nicht überschreiten.
    """

    # D13/MED: 30 min waren kuerzer als Delegations-Watcher (1200 s) + DAG
    # (900 s). Verlaengerter TTL + Heartbeat verhindert unterzählten Verbrauch.
    RESERVATION_TTL_SECONDS = 7200

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or BUDGET_DB_PATH

    def _policy(self, conn: sqlite3.Connection, aid: str) -> Dict[str, Any]:
        row = conn.execute(
            "SELECT * FROM role_budget_policies WHERE agent_id = ?", (aid,)
        ).fetchone()
        defaults = get_default_role_budget(aid)
        if not row:
            return defaults
        return {
            **defaults,
            "daily_token_budget": int(row["daily_token_budget"]),
            "daily_cost_limit_eur": float(row["daily_cost_limit_eur"]),
            "hard_cap_enabled": bool(row["hard_cap_enabled"]),
            "auto_pause_on_exceed": bool(row["auto_pause_on_exceed"]),
        }

    @staticmethod
    def _usage(conn: sqlite3.Connection, aid: str) -> Tuple[int, float]:
        row = conn.execute(
            "SELECT tokens_used, cost_eur FROM role_daily_budget_ledger "
            "WHERE agent_id = ? AND usage_date = ?",
            (aid, _today_str()),
        ).fetchone()
        return (
            int(row["tokens_used"] or 0) if row else 0,
            float(row["cost_eur"] or 0.0) if row else 0.0,
        )

    @staticmethod
    def _reserved(conn: sqlite3.Connection, aid: str, task_id: Optional[str], now: str) -> Tuple[int, float]:
        sql = (
            "SELECT COALESCE(SUM(tokens_reserved), 0), COALESCE(SUM(cost_eur_reserved), 0.0) "
            "FROM budget_reservations "
            "WHERE agent_id = ? AND status = 'reserved' AND expires_at > ?"
        )
        params: List[Any] = [aid, now]
        if task_id:
            sql += " AND task_id = ?"
            params.append(task_id)
        row = conn.execute(sql, tuple(params)).fetchone()
        return int(row[0] or 0), float(row[1] or 0.0)

    def check(
        self,
        agent_id: str,
        task_id: Optional[str] = None,
        estimated_tokens: int = 0,
        estimated_cost_eur: float = 0.0,
    ) -> Dict[str, Any]:
        """Pre-Flight-Prüfung inklusive aktiver Reservierungen (read-only)."""
        init_budget_tables(self.db_path)
        aid = (agent_id or "default").strip()
        now = datetime.datetime.now().isoformat()
        est_tok = max(0, int(estimated_tokens or 0))
        est_eur = max(0.0, float(estimated_cost_eur or 0.0))
        with _BUDGET_LOCK:
            with _get_conn(self.db_path) as conn:
                policy = self._policy(conn, aid)
                used_tok, used_eur = self._usage(conn, aid)
                # FRUEHER: nur Reservierungen DESSELBEN task_id -> parallele
                # Tasks desselben Agenten reservierten sich gegenseitig nicht
                # und das harte Tages-Cap war wirkungslos.
                res_tok, res_eur = self._reserved(conn, aid, None, now)
                usage = get_role_usage_today(aid, db_path=self.db_path)

                if policy["hard_cap_enabled"]:
                    if used_tok + res_tok + est_tok > policy["daily_token_budget"]:
                        return {
                            "allowed": False, "agent_id": aid, "task_id": task_id,
                            "error_code": "ROLE_TOKEN_BUDGET_EXCEEDED", "usage": usage,
                            "reason": f"Tages-Tokenbudget für Rolle '{aid}' einschließlich Reservierungen überschritten.",
                        }
                    if used_eur + res_eur + est_eur > policy["daily_cost_limit_eur"]:
                        return {
                            "allowed": False, "agent_id": aid, "task_id": task_id,
                            "error_code": "ROLE_EUR_BUDGET_EXCEEDED", "usage": usage,
                            "reason": f"Tages-Kostenbudget für Rolle '{aid}' einschließlich Reservierungen überschritten.",
                        }

                if task_id:
                    t = conn.execute(
                        "SELECT token_budget, cost_limit_eur, tokens_used, cost_used_eur "
                        "FROM task_budget_allocations WHERE task_id = ?",
                        (task_id,),
                    ).fetchone()
                    if t:
                        if int(t["token_budget"] or 0) > 0 and int(t["tokens_used"] or 0) + res_tok + est_tok > int(t["token_budget"]):
                            return {
                                "allowed": False, "agent_id": aid, "task_id": task_id,
                                "error_code": "TASK_TOKEN_BUDGET_EXCEEDED", "usage": usage,
                                "reason": f"Aufgaben-Tokenlimit für Task '{task_id}' überschritten.",
                            }
                        if float(t["cost_limit_eur"] or 0) > 0.0 and float(t["cost_used_eur"] or 0.0) + res_eur + est_eur > float(t["cost_limit_eur"]):
                            return {
                                "allowed": False, "agent_id": aid, "task_id": task_id,
                                "error_code": "TASK_EUR_BUDGET_EXCEEDED", "usage": usage,
                                "reason": f"Aufgaben-Kostenlimit für Task '{task_id}' überschritten.",
                            }
        return {"allowed": True, "agent_id": aid, "task_id": task_id, "usage": usage}

    def reserve(
        self,
        agent_id: str,
        task_id: Optional[str] = None,
        estimated_tokens: int = 0,
        estimated_cost_eur: float = 0.0,
        node_id: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Atomare Reservierung: prüft und bucht in EINER BEGIN-IMMEDIATE-Transaktion."""
        init_budget_tables(self.db_path)
        aid = (agent_id or "default").strip()
        est_tok = max(0, int(estimated_tokens or 0))
        est_eur = max(0.0, float(estimated_cost_eur or 0.0))
        now_dt = datetime.datetime.now()
        now = now_dt.isoformat()
        expires = (
            now_dt + datetime.timedelta(seconds=int(ttl_seconds or self.RESERVATION_TTL_SECONDS))
        ).isoformat()

        with _BUDGET_LOCK:
            conn = _get_conn(self.db_path)
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "UPDATE budget_reservations SET status = 'expired', settled_at = ? "
                    "WHERE status = 'reserved' AND expires_at <= ?",
                    (now, now),
                )
                policy = self._policy(conn, aid)
                used_tok, used_eur = self._usage(conn, aid)
                # FRUEHER: nur Reservierungen DESSELBEN task_id -> parallele
                # Tasks desselben Agenten reservierten sich gegenseitig nicht
                # und das harte Tages-Cap war wirkungslos.
                res_tok, res_eur = self._reserved(conn, aid, None, now)
                # FUND P0#10: Der Preflight prueft Task-Limits, reserve() aber
                # nur das Rollen-Cap -> parallele Reservierungen konnten das
                # Task-Budget umgehen. Gleiche Pruefung atomar in der Reserve.
                if task_id:
                    t = conn.execute(
                        "SELECT token_budget, cost_limit_eur, tokens_used, cost_used_eur "
                        "FROM task_budget_allocations WHERE task_id = ?",
                        (task_id,),
                    ).fetchone()
                    if t:
                        if int(t["token_budget"] or 0) > 0 and int(t["tokens_used"] or 0) + res_tok + est_tok > int(t["token_budget"]):
                            conn.rollback()
                            return {"allowed": False, "agent_id": aid, "task_id": task_id,
                                    "error_code": "TASK_TOKEN_BUDGET_EXCEEDED",
                                    "reason": f"Aufgaben-Tokenlimit für Task '{task_id}' überschritten."}
                        if float(t["cost_limit_eur"] or 0) > 0.0 and float(t["cost_used_eur"] or 0) + res_eur + est_eur > float(t["cost_limit_eur"]):
                            conn.rollback()
                            return {"allowed": False, "agent_id": aid, "task_id": task_id,
                                    "error_code": "TASK_EUR_BUDGET_EXCEEDED",
                                    "reason": f"Aufgaben-Kostenlimit für Task '{task_id}' überschritten."}
                    else:
                        # D13/F032-MED (Querschnitt mit W3-B operations_api.py):
                        # task_id OHNE Allokationszeile == kein hartes Ticket-Cap.
                        # Frueher griff nur das Rollen-Tagesbudget; fail-closed.
                        conn.rollback()
                        return {
                            "allowed": False, "agent_id": aid, "task_id": task_id,
                            "error_code": "TASK_BUDGET_NOT_REGISTERED",
                            "reason": f"Keine task_budget_allocations-Zeile für Task '{task_id}' — "
                                      "Reservierung ohne hartes Ticket-Cap verweigert.",
                        }
                if policy["hard_cap_enabled"]:
                    if used_tok + res_tok + est_tok > policy["daily_token_budget"]:
                        conn.rollback()
                        return {"allowed": False, "agent_id": aid, "task_id": task_id,
                                "error_code": "ROLE_TOKEN_BUDGET_EXCEEDED",
                                "reason": "Budget inklusive aktiver Reservierungen überschritten."}
                    if used_eur + res_eur + est_eur > policy["daily_cost_limit_eur"]:
                        conn.rollback()
                        return {"allowed": False, "agent_id": aid, "task_id": task_id,
                                "error_code": "ROLE_EUR_BUDGET_EXCEEDED",
                                "reason": "Budget inklusive aktiver Reservierungen überschritten."}
                    # F-010: Monatslimit atomar im selben BEGIN IMMEDIATE
                    # erzwingen (vorher nur Schema/Report/API-Setter).
                    m_row = conn.execute(
                        "SELECT COALESCE(SUM(cost_eur), 0.0) AS m_eur "
                        "FROM role_daily_budget_ledger WHERE agent_id = ? AND usage_date LIKE ?",
                        (aid, f"{_month_str()}%"),
                    ).fetchone()
                    m_eur = float(m_row["m_eur"]) if m_row else 0.0
                    m_limit = float(policy["monthly_cost_limit_eur"] or 0.0)
                    if m_limit > 0 and m_eur + res_eur + est_eur > m_limit:
                        conn.rollback()
                        return {"allowed": False, "agent_id": aid, "task_id": task_id,
                                "error_code": "ROLE_MONTHLY_EUR_BUDGET_EXCEEDED",
                                "reason": f"Monatsbudget von {m_limit:.2f} EUR überschritten."}
                # d02/d08: Optionales globales Tages-Kosten-Cap ueber alle Agenten
                # (verhindert unbegrenzte Summenkosten bei vielen parallelen Rollen).
                global_cap_raw = os.environ.get("ARCHON_GLOBAL_DAILY_COST_CAP_EUR", "").strip()
                if global_cap_raw:
                    try:
                        global_cap_eur = float(global_cap_raw)
                    except ValueError:
                        global_cap_eur = 0.0
                    if global_cap_eur > 0.0:
                        g_led = conn.execute(
                            "SELECT COALESCE(SUM(cost_eur), 0.0) AS g_eur "
                            "FROM role_daily_budget_ledger WHERE usage_date = ?",
                            (_today_str(),),
                        ).fetchone()
                        g_res = conn.execute(
                            "SELECT COALESCE(SUM(cost_eur_reserved), 0.0) AS r_eur "
                            "FROM budget_reservations WHERE status = 'reserved' AND expires_at > ?",
                            (now,),
                        ).fetchone()
                        g_total = float(g_led["g_eur"] if g_led else 0.0) + float(g_res["r_eur"] if g_res else 0.0) + est_eur
                        if g_total > global_cap_eur:
                            conn.rollback()
                            return {
                                "allowed": False, "agent_id": aid, "task_id": task_id,
                                "error_code": "GLOBAL_DAILY_EUR_BUDGET_EXCEEDED",
                                "reason": f"Globales Tagesbudget von {global_cap_eur:.2f} EUR überschritten.",
                            }
                reservation_id = f"res-{uuid.uuid4().hex[:12]}"
                conn.execute(
                    "INSERT INTO budget_reservations "
                    "(reservation_id, agent_id, task_id, node_id, tokens_reserved, cost_eur_reserved, status, created_at, expires_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'reserved', ?, ?)",
                    (reservation_id, aid, task_id or None, node_id or None, est_tok, est_eur, now, expires),
                )
                conn.commit()
                return {
                    "allowed": True, "reservation_id": reservation_id,
                    "agent_id": aid, "task_id": task_id,
                    "tokens_reserved": est_tok, "cost_eur_reserved": est_eur,
                }
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                return {"allowed": False, "agent_id": aid, "task_id": task_id,
                        "error_code": "BUDGET_RESERVATION_ERROR", "reason": str(exc)}
            finally:
                conn.close()

    def settle(
        self,
        reservation_id: Optional[str],
        actual_tokens: int = 0,
        actual_cost_usd: float = 0.0,
        cost_eur: Optional[float] = None,
        *,
        agent_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Bucht Verbrauch als echte Ledger-Zeile — alles in EINER Transaktion.

        Mit ``reservation_id`` wird eine bestehende Reservierung abgerechnet.
        Ohne Reservierung (``None``) wird direkt gebucht — das ist der Pfad fuer
        ``record_budget_usage`` und verhindert eine zweite, abweichende
        Ledger-Schreiblogik ausserhalb der BudgetBank.
        """
        init_budget_tables(self.db_path)
        tok = max(0, int(actual_tokens or 0))
        usd = max(0.0, float(actual_cost_usd or 0.0))
        eur = max(0.0, float(cost_eur)) if cost_eur is not None else round(usd * USD_TO_EUR_RATE, 6)
        now = datetime.datetime.now().isoformat()
        with _BUDGET_LOCK:
            conn = _get_conn(self.db_path)
            try:
                conn.execute("BEGIN IMMEDIATE")
                # D13/MED: Direktbuchungen haben keine Reservierung; ohne
                # Initialisierung schlaegt `if late_settlement:` mit
                # UnboundLocalError fehl (record_budget_usage war damit tot).
                late_settlement = False
                if reservation_id:
                    row = conn.execute(
                        "SELECT * FROM budget_reservations WHERE reservation_id = ? "
                        "AND status IN ('reserved', 'expired')",
                        (reservation_id,),
                    ).fetchone()
                    if not row:
                        conn.rollback()
                        return {"status": "not_found", "reservation_id": reservation_id}
                    late_settlement = str(row["status"]) == "expired"
                    aid = str(row["agent_id"] or "default")
                    tid = row["task_id"] or None
                else:
                    # Direktbuchung (record_budget_usage): kein Cap-Check,
                    # tatsaechlich angefallener Verbrauch MUSS gebucht werden.
                    aid = (agent_id or "default").strip()
                    tid = task_id or None
                conn.execute(
                    "INSERT INTO role_daily_budget_ledger "
                    "(agent_id, usage_date, tokens_used, cost_eur, cost_usd, dispatch_count, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, 1, ?) "
                    "ON CONFLICT(agent_id, usage_date) DO UPDATE SET "
                    "tokens_used = role_daily_budget_ledger.tokens_used + excluded.tokens_used, "
                    "cost_eur = role_daily_budget_ledger.cost_eur + excluded.cost_eur, "
                    "cost_usd = role_daily_budget_ledger.cost_usd + excluded.cost_usd, "
                    "dispatch_count = role_daily_budget_ledger.dispatch_count + 1, "
                    "updated_at = excluded.updated_at",
                    (aid, _today_str(), tok, eur, usd, now),
                )
                policy = self._policy(conn, aid)
                if policy["hard_cap_enabled"] and policy["auto_pause_on_exceed"]:
                    led = conn.execute(
                        "SELECT tokens_used, cost_eur, paused_at FROM role_daily_budget_ledger "
                        "WHERE agent_id = ? AND usage_date = ?",
                        (aid, _today_str()),
                    ).fetchone()
                    if led and not led["paused_at"] and (
                        int(led["tokens_used"] or 0) >= policy["daily_token_budget"]
                        or float(led["cost_eur"] or 0.0) >= policy["daily_cost_limit_eur"]
                    ):
                        conn.execute(
                            "UPDATE role_daily_budget_ledger SET paused_at = ? "
                            "WHERE agent_id = ? AND usage_date = ?",
                            (now, aid, _today_str()),
                        )
                if tid:
                    conn.execute(
                        "UPDATE task_budget_allocations "
                        "SET tokens_used = tokens_used + ?, cost_used_eur = cost_used_eur + ?, updated_at = ? "
                        "WHERE task_id = ?",
                        (tok, eur, now, tid),
                    )
                if reservation_id:
                    conn.execute(
                        "UPDATE budget_reservations SET status = 'settled', settled_at = ? WHERE reservation_id = ?",
                        (now, reservation_id),
                    )
                conn.commit()
                if late_settlement:
                    # D13/MED: trotz Ablauf REAL gebuchten Verbrauch melden.
                    logger.warning("[BudgetBank] late_settlement %s agent=%s task=%s tokens=%s",
                                   reservation_id, aid, tid, tok)
                return {"status": "settled", "reservation_id": reservation_id,
                        "agent_id": aid, "task_id": tid, "tokens_used": tok, "cost_eur": eur,
                        "late_settlement": late_settlement}
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                return {"status": "error", "reservation_id": reservation_id, "reason": str(exc)}
            finally:
                conn.close()

    def extend_reservation(
        self, reservation_id: str, extra_seconds: int = 600
    ) -> Dict[str, Any]:
        """Heartbeat: verlaengert eine noch aktive Reservierung (D13/MED)."""
        init_budget_tables(self.db_path)
        with _BUDGET_LOCK:
            conn = _get_conn(self.db_path)
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT expires_at FROM budget_reservations WHERE reservation_id = ? "
                    "AND status = 'reserved'", (reservation_id,),
                ).fetchone()
                if not row:
                    conn.rollback()
                    return {"status": "not_found", "reservation_id": reservation_id}
                extra = max(0, int(extra_seconds or 0))
                if extra:
                    from datetime import timedelta
                    new_exp = (
                        datetime.datetime.fromisoformat(str(row["expires_at"]))
                        + timedelta(seconds=extra)
                    ).isoformat()
                    conn.execute(
                        "UPDATE budget_reservations SET expires_at = ? WHERE reservation_id = ?",
                        (new_exp, reservation_id),
                    )
                conn.commit()
                return {"status": "extended", "reservation_id": reservation_id}
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                return {"status": "error", "reservation_id": reservation_id, "reason": str(exc)}
            finally:
                conn.close()

    def release(self, reservation_id: str, reason: str = "") -> Dict[str, Any]:
        """Gibt eine nicht ausgeführte Reservierung frei (z. B. bei Dispatch-Fehler)."""
        init_budget_tables(self.db_path)
        with _BUDGET_LOCK:
            conn = _get_conn(self.db_path)
            try:
                conn.execute("BEGIN IMMEDIATE")
                cur = conn.execute(
                    "UPDATE budget_reservations SET status = 'released', settled_at = ? "
                    "WHERE reservation_id = ? AND status = 'reserved'",
                    (datetime.datetime.now().isoformat(), reservation_id),
                )
                conn.commit()
                return {"status": "released" if cur.rowcount else "not_found",
                        "reservation_id": reservation_id, "reason": reason}
            finally:
                conn.close()


budget_bank = BudgetBank()
