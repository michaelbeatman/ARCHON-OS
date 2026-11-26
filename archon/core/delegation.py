"""
Delegation Engine v2 fuer Archon OS.
Strukturiertes Delegations-Protokoll: ```delegation```-JSON-Bloecke mit
Quittung, serverseitiger Hierarchie-Pruefung (APEX/LEAD/SPEZIALIST),
Kanban-Integration, Fan-In-Bruecke und Fehlerbehandlung.
Extrahiert aus main.py zur Modularisierung.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import hmac
import html as _html
import json
import os
import re
import secrets
import shutil
import sqlite3
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from archon.core.constants import DELEGATION_PROTOCOL_PROMPT
from backend.handoff_desk import mark_truncated


class HandoffDelegationPayload(BaseModel):
    """F030/H-11-1+2: EIN kanonisches Schema an der Orchestrator→Subagent-Kante.

    Ersetzt die beiden bisher konkurrierenden, ``extra="ignore"``-Schemas
    (`DelegationPayload` hier und `KanbanDelegationPayload` in
    `backend/operations_api.py`), deren aufeinanderfolgende ``model_dump()``-
    Projektionen M75-Isolation und A2A-Korrelation vor dem Child verloren.

    ``extra="forbid"` macht Schattenfelder sichtbar. Bekannte Legacy-Keys
    werden von :func:`canonicalize_delegation_payload` explizit nach
    ``extensions`` überführt und protokolliert — nie still verworfen.
    Tenant/Budget/Cancel/Taint werden serverseitig aufgelöst und signiert
    (siehe :func:`resolve_server_delegation_context` /
    :func:`sign_delegation_payload`).
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # Pflichtfelder des Delegationsprotokolls
    ziel_agent: str = Field(min_length=1)
    auftrag: str = Field(min_length=1)

    # Protokoll-/Modellfelder (altes DelegationPayload)
    modell: str = ""
    model: str = ""
    prioritaet: str = "normal"
    reasoning_level: str = "medium"
    reasoning: str = ""
    acceptance_criteria: str = ""
    reply_to: str = ""
    root_ticket_id: str = ""
    root_ticket: str = ""
    trajectory_id: str = ""
    parent_project_id: str = ""
    projekt: str = ""
    projekt_titel: str = ""
    titel: str = ""
    memory_scope: str = ""
    delegation_chain: List[str] = Field(default_factory=list)
    handed_off_via: str = ""

    # Kanban→Agent-Kante (altes KanbanDelegationPayload)
    task_id: str = ""
    title: str = ""
    assignee: str = ""
    via: str = ""
    delegator: str = ""
    tgt_session_id: str = ""
    origin_session_id: str = ""
    session_id: str = ""
    trace_id: str = ""
    correlation_id: str = ""
    isolated: bool = False
    allowed_tools: List[str] = Field(default_factory=list)
    allowed_skills: List[str] = Field(default_factory=list)
    memory_acl: List[str] = Field(default_factory=list)
    memory_ttl_seconds: int = 0
    hops_used: int = 0

    # F030: neue, serverseitig gesetzte Kontextfelder
    tenant_id: str = ""
    project_id: str = ""
    cancel_scope: str = ""
    taint_status: str = "unknown"
    budget_remaining_tokens: Optional[int] = None
    soul_mode: str = "compact"
    payload_signature: str = ""

    # D14/F033: strukturierte Hoheits-/Guardrail-Felder (vom Dispatch-Result)
    consensus_verdict: str = ""
    verdict: str = ""
    decision_status: str = ""
    policy_violation: bool = False
    guardrail_violation: bool = False

    # Explizites Auffangbecken für unbekannte (aber nicht verworfene) Keys.
    extensions: Dict[str, Any] = Field(default_factory=dict)


# Rückwärtskompatibles Symbol: alle bisherigen Importe (operations_api,
# chat.py, Tests) sehen jetzt dasselbe kanonische Schema.
DelegationPayload = HandoffDelegationPayload
KanbanDelegationPayload = HandoffDelegationPayload

# Nur diese Felder sind serverseitig authentifiziert und werden signiert.
_SIGNED_DELEGATION_FIELDS = (
    "ziel_agent", "auftrag", "tenant_id", "project_id", "cancel_scope",
    "taint_status", "budget_remaining_tokens", "soul_mode", "task_id",
    "trajectory_id", "delegation_chain",
)
_DELEGATION_HMAC_PREFIX = "dlg-hmac-sha256:"
_DELEGATION_HMAC_ENV = "ARCHON_DELEGATION_HMAC_KEY"
# Bekannte Legacy-/Schattenfelder, die in `extensions` landen dürfen (nie still
# verworfen). Alles andere löst `extra="forbid"` hart ab.
_DELEGATION_EXTENSION_KEYS = frozenset({
    "payload", "block_kind", "failure_reason", "status", "summary", "reason",
    "agent_id", "agent_name", "artifact_path", "severity", "source",
    "acceptance", "context", "metadata", "meta",
})


def _delegation_hmac_key() -> bytes:
    """HMAC-Key ausschließlich aus ENV, nie aus dem Payload (Zero-Trust)."""
    for env in (_DELEGATION_HMAC_ENV, "ARCHON_AUDIT_HMAC_KEY"):
        key = os.environ.get(env, "").strip().encode("utf-8")
        if key:
            return key
    raise RuntimeError(
        "[Delegation] Kein HMAC-Key: ARCHON_DELEGATION_HMAC_KEY bzw. "
        "ARCHON_AUDIT_HMAC_KEY muss gesetzt sein — Übergaben werden verweigert."
    )


def _delegation_signed_bytes(payload: Dict[str, Any]) -> bytes:
    canonical = {k: payload.get(k) for k in _SIGNED_DELEGATION_FIELDS}
    return json.dumps(
        canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def sign_delegation_payload(payload: Dict[str, Any]) -> str:
    """Signiert die serverseitig aufgelösten Kontextfelder einer Übergabe."""
    digest = hmac.new(
        _delegation_hmac_key(), _delegation_signed_bytes(payload), hashlib.sha256
    ).hexdigest()
    return f"{_DELEGATION_HMAC_PREFIX}{digest}"


def verify_delegation_payload(payload: Dict[str, Any]) -> bool:
    """Constant-time-Prüfung der Signatur gegen den ENV-Key (fail-closed)."""
    signature = str(payload.get("payload_signature") or "")
    if not signature.startswith(_DELEGATION_HMAC_PREFIX):
        return False
    try:
        expected = sign_delegation_payload(payload)
    except RuntimeError:
        return False
    return hmac.compare_digest(expected, signature)


def _server_tenant_id() -> str:
    """Mandant ausschließlich aus dem verifizierten Kontext, nie aus dem Body."""
    try:
        from backend.tenant_context import tenant_context
        return str(tenant_context.get_active_tenant_id() or "default")
    except Exception as exc:
        logger.error("[Delegation] Tenant-Kontext nicht verfügbar — fail-closed 'default': %s", exc)
        return "default"


def _server_budget_remaining_tokens(trajectory_id: str) -> Optional[int]:
    """Budget-Rest aus der echten Trajectory; ohne Ticket kein Minting."""
    if not trajectory_id:
        return 0
    try:
        from backend.trajectory_budget import get_trajectory
        row = get_trajectory(trajectory_id)
        if not row:
            return 0
        return max(0, int(row.get("max_tokens", 0)) - int(row.get("tokens_used", 0)))
    except Exception as exc:
        logger.error("[Delegation] Budget-Rest nicht lesbar — fail-closed 0: %s", exc)
        return 0


def _server_taint_status(session_id: str) -> str:
    """Taint aus der SSOT, nie aus dem LLM-Payload."""
    if not session_id:
        return "unknown"
    try:
        from backend.session_taint_guard import get_session_taint
        return "tainted" if get_session_taint(session_id) else "clean"
    except Exception as exc:
        logger.error("[Delegation] Taint-Status nicht lesbar — fail-closed 'unknown': %s", exc)
        return "unknown"


def resolve_server_delegation_context(
    payload: Dict[str, Any],
    *,
    trajectory_id: str = "",
    task_id: str = "",
    session_id: str = "",
) -> Dict[str, Any]:
    """Überschreibt client gelieferte Kontextfelder mit Server-Werten."""
    tid = trajectory_id or str(payload.get("trajectory_id") or "")
    return {
        "tenant_id": _server_tenant_id(),
        "project_id": str(
            payload.get("parent_project_id") or payload.get("projekt")
            or payload.get("project_id") or ""
        ),
        "cancel_scope": f"task:{task_id}" if task_id else str(payload.get("cancel_scope") or ""),
        "taint_status": _server_taint_status(session_id or str(payload.get("origin_session_id") or "")),
        "budget_remaining_tokens": _server_budget_remaining_tokens(tid),
        "soul_mode": str(payload.get("soul_mode") or "compact"),
    }


def canonicalize_delegation_payload(
    raw: Any,
    *,
    trajectory_id: str = "",
    task_id: str = "",
    session_id: str = "",
    require_signature: bool = False,
) -> Dict[str, Any]:
    """Einmalige, strikte Validierung an der Übergabekante.

    * Unknown Keys landen dokumentiert in ``extensions`` (statt still zu
      verschwinden);
    * Tenant/Budget/Taint/Cancel werden serverseitig aufgelöst;
    * die resultierende Übergabe wird signiert (HMAC-SHA256, ENV-Key).

    Diese Funktion ist die Kompatibilitätsschicht für `backend/operations_api.py`
    (W3-B): dort darf ``_load_kanban_delegation_payload`` durch genau einen
    Aufruf dieser Funktion ersetzt werden — ohne zweite ``model_dump()``-
    Projektion.
    """
    if raw is None:
        raise ValueError("Delegations-Payload fehlt (None)")
    if isinstance(raw, (str, bytes)):
        data = json.loads(raw)
    elif isinstance(raw, HandoffDelegationPayload):
        data = raw.model_dump()
    elif isinstance(raw, dict):
        data = dict(raw)
    else:
        raise ValueError("Delegations-Payload muss JSON-String oder Dict sein")
    if not isinstance(data, dict):
        raise ValueError("Delegations-Payload muss ein JSON-Objekt sein")

    # Legacy-Aliase kanonisch benennen, bevor extra="forbid" greift.
    _aliases = {
        "agent": "ziel_agent", "target_agent": "ziel_agent", "to_agent": "ziel_agent",
        "assignee": "assignee", "prompt": "auftrag", "task": "auftrag",
        "project": "project_id", "company_id": "tenant_id", "tenant": "tenant_id",
        "session": "session_id", "trace": "trace_id",
        "cancel_token": "cancel_scope", "taint": "taint_status",
    }
    normalized: Dict[str, Any] = {}
    extensions: Dict[str, Any] = {}
    for key, value in data.items():
        target = _aliases.get(key, key)
        if target in HandoffDelegationPayload.model_fields:
            # Serverseitig gesetzte Felder unten überschreiben, nie hier vertrauen.
            normalized[target] = value
        elif key in _DELEGATION_EXTENSION_KEYS or isinstance(value, (dict, list)):
            extensions[key] = value
        else:
            logger.warning(
                "[Delegation] Unbekanntes Payload-Feld '%s' → extensions (extra=forbid-Schutz aktiv)",
                key,
            )
            extensions[key] = value
    # Pflichtfelder fehlen? Nicht erfinden — harter Schemafehler.
    normalized.setdefault("ziel_agent", str(normalized.get("assignee") or ""))
    normalized.setdefault("auftrag", str(normalized.get("title") or ""))
    normalized["extensions"] = {**extensions, **dict(data.get("extensions") or {})}

    validated = HandoffDelegationPayload.model_validate(normalized).model_dump()
    validated.update(resolve_server_delegation_context(
        validated, trajectory_id=trajectory_id, task_id=task_id, session_id=session_id,
    ))
    validated["payload_signature"] = sign_delegation_payload(validated)
    if require_signature and not verify_delegation_payload(validated):
        raise ValueError("Delegations-Signatur konnte nicht verifiziert werden")
    return validated
from archon.core.mission_control import (
    mc_get_parent_context_sqlite,
    mc_link_subtask_sqlite,
    mc_update_task_sqlite,
    update_mission_control_data,
)
from archon.core.orchestration import _fan_in_maybe_start_synthesis, _run_synthesis_cascade
from archon.core.paths import OPT_DATA_DIR
from archon.core.profiles import api_get_hermes_profiles
from archon.core.runtime import (
    WORKSPACE_DIR,
    broadcast_event,
    logger,
    subscribe_events,
    unsubscribe_events,
)
from archon.core.state_db import _get_state_db
from backend.platform_paths import OBSIDIAN_VAULT, PROJEKTE_DIR

# Batch D/4: Supervisor-Rollover aus der Org-Hierarchie (links bleiben SSOT).
from backend.supervisor_rollover import on_supervisor_failure, resolve_supervisor

_DEPS: Dict[str, Any] = {}


def configure(**deps: Any) -> None:
    """Registriert Abhaengigkeiten aus main.py (einmalig beim Import)."""
    _DEPS.update(deps)


def _get_obsidian_vault_dir() -> str:
    # Pfad-SSOT: kein main.py-Fallback mehr, sondern der gemeinsame Resolver.
    from archon.core.runtime import resolve_obsidian_vault_path
    return resolve_obsidian_vault_path()


def _spawn_background(coro, name: str = ""):
    fn = _DEPS.get("_spawn_background")
    if fn:
        return fn(coro, name=name)
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "_spawn_background"):
        return main_mod._spawn_background(coro, name=name)
    return asyncio.create_task(coro, name=name)


async def _invoke_fan_in(parent_pid: str) -> None:
    """Startet die Fan-In-Synthese ueber den konfigurierten main-Wrapper (mit update_mc)."""
    fn = _DEPS.get("fan_in")
    if callable(fn):
        await fn(parent_pid)
        return
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "_fan_in_maybe_start_synthesis"):
        await main_mod._fan_in_maybe_start_synthesis(parent_pid)
        return
    await _fan_in_maybe_start_synthesis(
        parent_pid,
        run_cascade=lambda pid: _run_synthesis_cascade(pid, update_mc=update_mission_control_data),
    )


def _ensure_session_exists(conn: sqlite3.Connection, session_id: str, profile_id: str, model: str, title: str):
    fn = _DEPS.get("_ensure_session_exists")
    if fn:
        return fn(conn, session_id, profile_id, model, title)
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "_ensure_session_exists"):
        return main_mod._ensure_session_exists(conn, session_id, profile_id, model, title)
    now = time.time()
    cur = conn.cursor()
    cur.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
    if not cur.fetchone():
        try:
            cur.execute("""
                INSERT INTO sessions (
                    id, source, display_name, title, model, profile_name, started_at, message_count,
                    input_tokens, output_tokens, estimated_cost_usd, actual_cost_usd
                ) VALUES (?, 'master_chat', ?, ?, ?, ?, ?, 0, 0, 0, 0.0, 0.0)
            """, (session_id, title[:50], title[:50], model, profile_id, now))
            conn.commit()
        except sqlite3.IntegrityError:
            unique_title = f"{title[:36]} [{session_id[3:19]}]"
            try:
                cur.execute("""
                    INSERT INTO sessions (
                        id, source, display_name, title, model, profile_name, started_at, message_count,
                        input_tokens, output_tokens, estimated_cost_usd, actual_cost_usd
                    ) VALUES (?, 'master_chat', ?, ?, ?, ?, ?, 0, 0, 0, 0.0, 0.0)
                """, (session_id, unique_title, unique_title, model, profile_id, now))
                conn.commit()
            except sqlite3.IntegrityError:
                unique_title = f"{title[:30]} [{time.time_ns() % 1000000000}]"
                cur.execute("""
                    INSERT INTO sessions (
                        id, source, display_name, title, model, profile_name, started_at, message_count,
                        input_tokens, output_tokens, estimated_cost_usd, actual_cost_usd
                    ) VALUES (?, 'master_chat', ?, ?, ?, ?, ?, 0, 0, 0, 0.0, 0.0)
                """, (session_id, unique_title, unique_title, model, profile_id, now))
                conn.commit()


def _save_message_to_db(session_id: str, role: str, content: str, token_count: Optional[int] = None):
    fn = _DEPS.get("_save_message_to_db")
    if fn:
        return fn(session_id, role, content, token_count=token_count)
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "_save_message_to_db"):
        return main_mod._save_message_to_db(session_id, role, content, token_count=token_count)
    try:
        with _get_state_db() as conn:
            now = time.time()
            conn.execute("""
                INSERT INTO messages (
                    session_id, role, content, timestamp, token_count, active, compacted
                ) VALUES (?, ?, ?, ?, ?, 1, 0)
            """, (session_id, role, content, now, token_count))
            conn.execute("""
                UPDATE sessions 
                SET message_count = message_count + 1, last_activity_at = ?
                WHERE id = ?
            """, (now, session_id))
            conn.commit()
    except Exception as e:
        logger.error(f"[Delegation] Fehler beim Speichern der Nachricht: {e}")


def _register_decision(*args: Any, **kwargs: Any) -> Any:
    fn = _DEPS.get("register_decision")
    if fn:
        return fn(*args, **kwargs)
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "register_decision"):
        return main_mod.register_decision(*args, **kwargs)
    logger.warning("[Delegation] register_decision nicht verfuegbar.")
    return None


_ORG_HIERARCHY_CACHE = {"mtime": 0.0, "nodes": {}, "aliases": {}, "loaded": False}


def _load_org_hierarchy_map():
    path = os.path.join(WORKSPACE_DIR, "config", "org_hierarchy.json")
    if not os.path.exists(path):
        path = os.path.join("config", "org_hierarchy.json")
    try:
        mtime = os.path.getmtime(path)
        if not _ORG_HIERARCHY_CACHE["loaded"] or mtime != _ORG_HIERARCHY_CACHE["mtime"]:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            nodes = {}
            for n in data.get("nodes", []):
                try:
                    nodes[n.get("id")] = {"tier": int(n.get("tier") or 3), "team_id": n.get("team_id")}
                except Exception:
                    continue
            aliases = {
                str(k).strip().lower(): str(v).strip()
                for k, v in (data.get("aliases") or {}).items()
                if str(k or "").strip() and str(v or "").strip()
            }
            _ORG_HIERARCHY_CACHE.update(
                {"mtime": mtime, "nodes": nodes, "aliases": aliases, "loaded": True}
            )
        return _ORG_HIERARCHY_CACHE["nodes"]
    except Exception as e:
        logger.warning(f"[Delegation] org_hierarchy.json nicht lesbar: {e}")
        return {}


def resolve_isolated_scope_with_role_limits(
    target_agent_id: str, requested_model: str, profiles: list
) -> Dict[str, Any]:
    """H-15-1/F023: Isolation-Scope um die negativen Rollengrenzen ergaenzen.

    ``backend/delegation_isolation.py`` gehoert einem anderen W2-Agenten; die
    Anreicherung erfolgt daher am Produzenten (dieser Datei) und wird als
    System-Prompt verankert. DieProfile-Felder stammen aus der 71-ID-SSOT.
    """
    from backend.delegation_isolation import resolve_isolated_execution_scope

    scope = dict(resolve_isolated_execution_scope(target_agent_id, requested_model, profiles=profiles))
    prof = next((p for p in (profiles or []) if p.get("id") == target_agent_id), {}) or {}  # type: ignore[var-annotated]
    scope["negative_scope"] = str(prof.get("negative_scope") or "").strip()
    scope["negative_scope_en"] = str(prof.get("negative_scope_en") or "").strip()
    risk_tier = str(prof.get("risk_tier") or "").strip()
    compliance = str(prof.get("compliance_status") or "").strip()
    if not risk_tier:
        # SSOT: EU-AI-Act-Inventar (71 Rollen) — kein erfundenes Tier.
        try:
            from backend.eu_ai_act_inventory import eu_ai_act_inventory_manager
            item = next(
                (x for x in eu_ai_act_inventory_manager.get_inventory()
                 if x.get("agent_id") == target_agent_id),
                None,
            )
            if item:
                risk_tier = str(item.get("risk_tier") or "UNCLASSIFIED")
                compliance = compliance or str(item.get("compliance_status") or "")
        except Exception as exc:
            logger.debug("[Delegation] Risikotier nicht aus Inventar lesbar: %s", exc)
    scope["risk_tier"] = risk_tier or "UNCLASSIFIED"
    scope["compliance_status"] = compliance
    scope["soul_mode"] = str(prof.get("soul_mode") or "").strip()
    return scope


def build_isolation_header_with_negative_scope(
    scope: Dict[str, Any], known_id: bool = True
) -> str:
    """H-15-1/F023: Isolation-Header mit hartem NEGATIVE_SCOPE-Block."""
    from backend.delegation_isolation import build_isolated_system_prompt_header

    base = build_isolated_system_prompt_header(scope)
    negative = str(scope.get("negative_scope") or "").strip()
    negative_en = str(scope.get("negative_scope_en") or "").strip()
    if not negative and not negative_en:
        # Fail-closed: ohne dokumentierte Grenze darf der Subagent nichts
        # exekutives ableiten.
        negative = (
            "Keine Hoheits-, Freigabe-, Zahlungs- oder Deploy-Aktionen ohne "
            "verifizierte menschliche Freigabe; keine Rechte anderer Rollen annehmen."
        )
    lines = [
        "NEGATIVE_SCOPE (Strikt verboten): " + negative + (f" | {negative_en}" if negative_en else ""),
        f"RISK_TIER: {str(scope.get('risk_tier') or 'UNCLASSIFIED').strip()}",
    ]
    compliance = str(scope.get("compliance_status") or "").strip()
    if compliance:
        lines.append(f"COMPLIANCE_STATUS: {compliance}")
    lines.append(
        "HITL_RULE: Keine Freigabe im Namen anderer Rollen erteilen; "
        "Hoheitsakte erfordern eine identitaetsverschiedene zweite Person."
    )
    if not known_id:
        lines.append("UNKNOWN_AGENT: default-deny — nur MINIMAL_FALLBACK_TOOLS erlaubt.")
    return base + "\n" + "\n".join(lines)


_SOUL_TIER_FILES = {
    "compact": "SOUL_COMPACT.md",
    "pro": "SOUL_PRO.md",
    "full": "SOUL_FULL.md",
}


def resolve_effective_soul_mode(agent_id: str, profile_soul_mode: str = "") -> str:
    """F23 (D15): Produktive 3-Tier-Aufloesung (HIGH_RISK -> full, LEAD -> pro, Spezialist -> compact).

    Ein explizites Profil-Setting ('pro'/'full') bleibt vorrangig; bei Standard-
    'compact' oder leerem Wert wird die Rolle aus EU-AI-Act-Risikoklasse und
    Organigramm-Tier (config/org_hierarchy.json) aufgeloest.
    """
    explicit = str(profile_soul_mode or "").strip().lower()
    if explicit in ("pro", "full"):
        return explicit
    aid = str(agent_id or "").strip()
    if not aid:
        return "compact"
    try:
        from backend.eu_ai_act_inventory import HIGH_RISK_AGENT_IDS

        if aid in HIGH_RISK_AGENT_IDS:
            return "full"
    except Exception:
        pass
    try:
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        org_path = os.path.join(repo_root, "config", "org_hierarchy.json")
        if os.path.isfile(org_path):
            with open(org_path, "r", encoding="utf-8") as fh:
                org = json.load(fh)
            nodes = org.get("nodes") or {}
            node = None
            if isinstance(nodes, dict):
                node = nodes.get(aid)
            elif isinstance(nodes, list):
                node = next(
                    (
                        n for n in nodes
                        if isinstance(n, dict) and (n.get("id") == aid or n.get("agent_id") == aid)
                    ),
                    None,
                )
            if isinstance(node, dict) and int(node.get("tier") or 3) in (1, 2):
                return "pro"
    except Exception:
        pass
    return "compact"


def active_soul_tier_text(agent_id: str, soul_mode: str, max_chars: int = 6000) -> str:
    """D15/MED: `soul_mode` wird im Dispatch tatsaechlich konsumiert.

    Compact/Pro/Full sind drei Phasen einer SOUL.md. Der aktive Tier wird als
    System-Kontext an den Subagenten gegeben; kein stilles Ignorieren des
    Profilfeldes mehr. Fehlt die Datei, wird fail-closed auf SOUL.md (Compact)
    zurueckgegriffen.
    """
    tier = str(soul_mode or "compact").strip().lower()
    filename = _SOUL_TIER_FILES.get(tier, "SOUL_COMPACT.md")
    # `archon.core.runtime.WORKSPACE_DIR` zeigt auf agent_workspace; die
    # kanonischen SOUL-Dateien liegen im Repo-Root (siehe
    # backend.eu_ai_act_inventory._compute_soul_sha256). Beide Pfade pruefen.
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    candidates = [
        os.path.join(repo_root, "souls", str(agent_id or "").strip(), filename),
        os.path.join(repo_root, "souls", str(agent_id or "").strip(), "SOUL.md"),
        os.path.join(WORKSPACE_DIR, "souls", str(agent_id or "").strip(), filename),
        os.path.join(WORKSPACE_DIR, "souls", str(agent_id or "").strip(), "SOUL.md"),
    ]
    path = next((p for p in candidates if os.path.isfile(p)), "")
    if not path:
        logger.debug("[Delegation] Kein SOUL-Tier fuer %s gefunden.", agent_id)
        return ""
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            text = fh.read().replace("\r\n", "\n").replace("\r", "\n").strip()
        return text[:max_chars] if text else ""
    except Exception as exc:
        logger.warning("[Delegation] SOUL-Tier %s fuer %s nicht lesbar: %s", tier, agent_id, exc)
        return ""


def _apex_ids() -> frozenset:
    """D15/MED: APEX-Menge hat genau EINE SSOT — Tier 1 in org_hierarchy.json.

    Frueher standen hier hart codierte IDs, die der UI-Hierarchie widersprachen
    (z.B. `default` tier=3 aber APEX). Fail-closed: ohne lesbares Organigramm
    gibt es keine APEX-Rechte.
    """
    org = _load_org_hierarchy_map()
    if not org:
        logger.error("[Delegation] Organigramm nicht lesbar — keine APEX-Rechte (fail-closed).")
        return frozenset()
    return frozenset(
        agent_id for agent_id, node in org.items() if int(node.get("tier") or 3) == 1
    )


def _check_delegation_permission(delegator_id: str, target_id: str):
    """Hierarchie-Regeln: Tier 1 (APEX) -> alle; Tier 2 (LEAD) -> eigenes Team; Tier 3 -> keine Delegation."""
    org = _load_org_hierarchy_map()
    d = org.get(delegator_id)
    t = org.get(target_id)

    if delegator_id in _apex_ids():
        if delegator_id == target_id:
            return False, "Selbst-Delegation ist nicht erlaubt."
        return True, "APEX"

    if d is None:
        return False, f"Delegator '{delegator_id}' ist in der Organisationsstruktur nicht registriert."
    if delegator_id == target_id:
        return False, "Selbst-Delegation ist nicht erlaubt."
    if d["tier"] == 1:
        return True, "APEX"
    if d["tier"] == 2:
        if t and t.get("team_id") and t.get("team_id") == d.get("team_id"):
            return True, "LEAD->Team"
        return False, (f"LEAD '{delegator_id}' (Team {d.get('team_id')}) darf nur an das eigene Team delegieren — "
                       f"'{target_id}' gehört zu Team {(t or {}).get('team_id', 'unbekannt')}.")
    return False, f"Spezialist '{delegator_id}' (Tier 3) darf nicht delegieren. Bitte beim eigenen LEAD eskalieren."


# D11/MED (Re-Audit): die reply_to-Kette lag frueher in einem RAM-Dict und wurde
# unter task_id geschrieben, aber unter parent_pid (einer Projekt-ID!) gelesen.
# SSOT ist jetzt die SQLite-Spalte `agent_handoffs.reply_to`; Seele liest
# `handoff_desk.latest_handoff_id_for_task()` mit demselben Key (task_id/project_id).

# C09: Session -> Delegationskette. Verhindert A->B->A-Zirkel und unbegrenzte
# Tiefe im Hauptpfad (der Mission-Control-Pfad hatte bereits max_depth=3).
_DELEGATION_CHAIN_BY_SESSION: Dict[str, tuple] = {}
_CHAIN_LOCK = threading.Lock()

# D13/F032: EINZIGE Schranke — SSOT aus `backend.trajectory_budget` (W3-D).
try:
    from backend.trajectory_budget import MAX_DELEGATION_DEPTH as _SSOT_MAX_DELEGATION_DEPTH
except Exception as _depth_ssot_exc:
    logger.error(
        "[Delegation] Depth-SSOT nicht lesbar — fail-closed 3: %s", _depth_ssot_exc
    )
    _SSOT_MAX_DELEGATION_DEPTH = 3


def _delegation_depth_cap() -> int:
    return max(1, int(_SSOT_MAX_DELEGATION_DEPTH))


_MAX_DELEGATION_DEPTH = _delegation_depth_cap()
_MAX_TRACKED_CHAINS = 5000
# D13: ein stabiler trajectory_id-Key fuer Lesen, Schreiben UND Resume. Die
# alten Session-IDs waren nie der gesuchte Key (D13/BLOCKER).
MAX_DELEGATIONS_PER_RESPONSE = 5
_SESSION_TRAJECTORY: Dict[str, str] = {}
_CHAIN_TASK_BY_TRAJECTORY: Dict[str, str] = {}
_TRAJECTORY_ACTIVE: set[str] = set()


class DelegationReceipt(str):
    """Text-Quittung mit strukturiertem Status (rueckwaertskompatibel zu chat.py)."""

    status: str
    reason: str
    block_kind: str
    failure_reason: str
    trajectory_id: str

    def __new__(cls, text: str, **fields: Any):
        obj = super().__new__(cls, text)
        obj.status = str(fields.get("status") or "blocked")
        obj.reason = str(fields.get("reason") or "")
        obj.block_kind = str(fields.get("block_kind") or "")
        obj.failure_reason = str(fields.get("failure_reason") or fields.get("reason") or "")
        obj.trajectory_id = str(fields.get("trajectory_id") or "")
        return obj


def _resolve_trajectory_id(payload: Dict[str, Any], origin_session_id: Optional[str]) -> str:
    """Ein Key fuer die ganze Kette — root_ticket > payload > Session."""
    from backend.trajectory_budget import normalize_trajectory_id
    seed = (
        payload.get("trajectory_id")
        or payload.get("root_ticket_id")
        or payload.get("root_ticket")
        or origin_session_id
        or payload.get("parent_project_id")
    )
    tid = normalize_trajectory_id(
        str(seed) if seed else None,
        str(payload.get("root_ticket_id") or seed) if seed else None,
        str(origin_session_id or ""),
    )
    # Bekannte Sub-Session? Dann IMMER die Wurzel-Trajectory verwenden (A->B->A).
    if seed and str(seed) in _SESSION_TRAJECTORY:
        tid = _SESSION_TRAJECTORY[str(seed)]
    return tid


def _get_chain(tid: str) -> list:
    with _CHAIN_LOCK:
        return list(_DELEGATION_CHAIN_BY_SESSION.get(tid, ()))


def _put_chain(tid: str, chain: tuple, task_id: Optional[str] = None) -> None:
    with _CHAIN_LOCK:
        _DELEGATION_CHAIN_BY_SESSION[tid] = tuple(chain)
        _TRAJECTORY_ACTIVE.add(tid)
        if task_id:
            _CHAIN_TASK_BY_TRAJECTORY[tid] = str(task_id)
        if len(_DELEGATION_CHAIN_BY_SESSION) > _MAX_TRACKED_CHAINS:
            # Nur TERMINALE Ketten evictieren — laufende Watchers nie verlieren.
            for old in list(_DELEGATION_CHAIN_BY_SESSION):
                if len(_DELEGATION_CHAIN_BY_SESSION) <= _MAX_TRACKED_CHAINS // 2:
                    break
                linked_task = _CHAIN_TASK_BY_TRAJECTORY.get(old)
                if linked_task and linked_task in _ACTIVE_WATCHERS:
                    continue
                if linked_task:
                    try:
                        row = _poll_kanban_row(linked_task)
                        if row and str(row[0] or "") not in _TERMINAL_TASK_STATUSES:
                            continue
                    except Exception:
                        continue
                _DELEGATION_CHAIN_BY_SESSION.pop(old, None)
                _TRAJECTORY_ACTIVE.discard(old)
                _CHAIN_TASK_BY_TRAJECTORY.pop(old, None)


def _trajectory_for_task(task_id: str) -> str:
    """Inverse von _CHAIN_TASK_BY_TRAJECTORY: Task-ID -> Trajectory-Key.

    D02/MED: der Run-Abschluss darf nicht ``_SESSION_TRAJECTORY[task_id]``
    lesen — das Dict ist ausschließlich nach Session-IDs gekeysst. Ohne die
    Inverse wird eine frische trajectory_id abgeleitet und die eigentliche
    Trajectory bleibt aktiv (Zyklusschutz/Hop-Zaehler nicht geschlossen).
    """
    with _CHAIN_LOCK:
        return next(
            (tid for tid, linked in _CHAIN_TASK_BY_TRAJECTORY.items() if linked == str(task_id)),
            "",
        )


def _finalize_trajectory(tid: str, task_id: Optional[str] = None, status: str = "completed") -> None:
    with _CHAIN_LOCK:
        _TRAJECTORY_ACTIVE.discard(tid)
        if task_id:
            _CHAIN_TASK_BY_TRAJECTORY.pop(tid, None)
    try:
        from backend.trajectory_budget import close_trajectory
        close_trajectory(tid, "completed" if status in ("done", "review") else "failed")
    except Exception as exc:
        logger.debug("[Delegation] Trajectory-Abschluss nicht persistiert: %s", exc)


def delegation_chain_metrics() -> Dict[str, int]:
    with _CHAIN_LOCK:
        return {"active_chains": len(_TRAJECTORY_ACTIVE),
                "tracked_chains": len(_DELEGATION_CHAIN_BY_SESSION)}


def _block_receipt(tid: str, ziel: str, chain: list, reason: str, detail: str) -> "DelegationReceipt":
    """Harte Ablehnung: blocked + Audit + HITL-Hinweis statt Freitext-Quittung."""
    text = (f"❌ DELEGATION BLOCKIERT — Ziel: {ziel} | trajectory={tid} | "
            f"Kette: {' → '.join(chain + [ziel])} | Grund: {reason}: {detail} | HITL/escalate required.")
    try:
        from backend.trajectory_budget import _audit
        _audit(tid, f"{reason}: {detail} (chain={chain + [ziel]})")
    except Exception:
        logger.error("[Delegation] D13-Block: %s %s", reason, detail)
    try:
        from archon.core.mission_control import mc_update_task_sqlite
        root = str(payload_root(tid) or "")
        if root:
            mc_update_task_sqlite(root, {
                "status": "blocked", "block_kind": reason.lower(),
                "failure_reason": reason, "mc_status": "blocked",
            })
    except Exception:
        pass
    return DelegationReceipt(text, status="blocked", reason=reason,
                             block_kind=reason.lower(), failure_reason=reason,
                             trajectory_id=tid)


def payload_root(tid: str) -> str:
    """Root-Ticket aus der Trajectory-Tabelle (fuer Audit/Meta)."""
    try:
        from backend.trajectory_budget import get_trajectory
        row = get_trajectory(tid)
        return str((row or {}).get("root_ticket_id") or "")
    except Exception:
        return ""


def _resolve_handoff_criteria(criteria: Optional[str], prof_id: str, task_id: str) -> str:
    """Batch D/2: explizite Akzeptanzkriterien aus dem Delegations-Payload.

    Fehlt ``payload.get("acceptance_criteria")``, bleibt der generische
    Fallback erhalten — jetzt aber explizit benannt und niemals leer.
    """
    explicit = str(criteria or "").strip()
    if explicit:
        return explicit
    return (
        f"Ergebnis von @{prof_id} fuer Task {task_id} fachlich pruefen; "
        "Status, Artefakte und Quittung im Kanban/Obsidian gegennehmen."
    )


def _delegation_eval_gate_config() -> Dict[str, Any]:
    """Batch D/3: Konfigurationsblock ``delegation`` (require_eval_gate)."""
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("delegation") or {}
    except Exception:
        return {}


def _check_delegation_eval_gate(ziel: str, t_prof: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """Batch D/3: Eval-/Promotion-Gate vor dem Dispatch.

    Aktiv nur bei Profil-Flag ``require_eval_gate`` oder dem globalen
    Config-Flag ``delegation.require_eval_gate``. Ohne Gate bleibt das
    Verhalten unveraendert. Konsultiert werden ausschliesslich persistierte
    Eval-Ergebnisse und die Scorecard — ein neuer LLM-Lauf gehoert nicht in
    den Dispatch-Pfad. Unzureichende Daten fuehren fail-closed zur Ablehnung;
    es wird nie eine Erfolgsquote erfunden.
    """
    cfg = _delegation_eval_gate_config()
    if not (bool((t_prof or {}).get("require_eval_gate")) or bool(cfg.get("require_eval_gate"))):
        return True, ""
    try:
        min_score = float(cfg.get("min_eval_score") or (t_prof or {}).get("min_eval_score") or 70.0)
    except (TypeError, ValueError):
        min_score = 70.0

    try:
        from backend.eval_gates import list_eval_runs
        runs = list_eval_runs(target_id=ziel, limit=1) or []
    except Exception as exc:
        logger.warning(f"[Delegation] Eval-Gate nicht lesbar fuer {ziel}: {exc}")
        return False, "Eval-Gate-Daten nicht verfuegbar (Ablehnung aus Sicherheitsgruenden)."
    if runs:
        latest = runs[0]
        if bool(latest.get("passed")) and float(latest.get("overall_score") or 0.0) >= min_score:
            return True, ""
        return False, (
            f"letzter Eval-Lauf {latest.get('eval_id', '?')} nicht bestanden "
            f"({latest.get('overall_score')}/{min_score})."
        )

    try:
        from backend.agent_scorecard_engine import agent_scorecard_engine
        sc = agent_scorecard_engine.get_scorecard(ziel) or {}
    except Exception as exc:
        logger.warning(f"[Delegation] Scorecard nicht lesbar fuer {ziel}: {exc}")
        return False, "Keine Eval-Daten und keine Scorecard verfuegbar."
    if not sc.get("data_sufficient"):
        return False, "Keine Eval-Daten und unzureichende Scorecard-Daten (data_sufficient=false)."
    rate = sc.get("success_rate")
    if rate is None:
        return False, "Scorecard liefert keine belegte Erfolgsquote (success_rate=None)."
    try:
        rate_f = float(rate)
    except (TypeError, ValueError):
        return False, "Scorecard-Erfolgsquote nicht lesbar."
    if rate_f < min_score:
        return False, f"Scorecard-Erfolgsquote {rate_f}% unter Schwelle {min_score}%."
    return True, ""


def _canonical_aliases() -> Dict[str, str]:
    """D15/MED: einzige Alias-SSOT aus ``config/org_hierarchy.json``.

    Der frueher hier hart codierte Register widersprach ``backend/agent_aliases``
    und dem Compliance-Pfad. Delegation, Konsens (ueber role_budget_engine)
    und Compliance konsumieren jetzt dieselbe Map.
    """
    _load_org_hierarchy_map()  # refresst Cache inkl. aliases bei mtime-Aenderung
    return dict(_ORG_HIERARCHY_CACHE.get("aliases") or {})  # type: ignore[call-overload]


def canonical_agent_id(raw: str, known_ids: Optional[set] = None) -> str:
    """Kanonische ID — identisch mit der Compliance-/Budget-SSOT."""
    from backend.role_budget_engine import canonical_agent_id as _canonical

    return _canonical(raw, known_ids)


# Rueckwaerts-kompatibles Symbol (main.py importiert es); Inhalt ist die SSOT.
DELEGATION_ALIAS_MAP: Dict[str, str] = _canonical_aliases()


def _resolve_target_agent_id(ziel_raw: str, profiles: list):
    """Löst erfundene Namen, Skill-Namen, Rufnamen oder ungenaue IDs fehlertolerant in die echte Agent-ID auf."""
    raw = (ziel_raw or "").strip().lower()
    if not raw:
        return None, ""

    # 1. Exakter ID-Match
    for p in profiles:
        if p.get("id", "").lower() == raw:
            return p["id"], ""

    # 2. Normalisierter ID-Match (_ vs -)
    raw_norm = raw.replace("-", "_")
    for p in profiles:
        if p.get("id", "").lower().replace("-", "_") == raw_norm:
            return p["id"], f"ID normalisiert von '{ziel_raw}'"

    # 3. Kanonischer Alias-Lookup (SSOT: config/org_hierarchy.json)
    aliases = _canonical_aliases()
    if raw in aliases:
        mapped = aliases[raw]
        return mapped, f"Alias '{ziel_raw}' -> '{mapped}'"
    if raw_norm in aliases:
        mapped = aliases[raw_norm]
        return mapped, f"Alias '{ziel_raw}' -> '{mapped}'"

    # 4. Personenname / Rufname Match (z.B. 'Robert', 'Tobias', 'Sarah')
    for p in profiles:
        pname = (p.get("person_name") or "").strip().lower()
        if pname:
            first_name = pname.split()[0]
            if raw == pname or raw == first_name:
                pid = p["id"]
                return pid, f"Personenname '{pname}' -> '{pid}'"

    # H-02-1/F031: frueher griff hier eine Substring-Suche auf `role`/`name`.
    # Ein halluziniertes "orchestrator" landete damit auf `@default` (APEX,
    # terminal+filesystem) und eskalierte die Tool-Privilegien des Subagenten.
    # Entfernt — unbekannte Ziele werden NUR ueber explizite Whitelist
    # (Alias-SSOT, Schritt 3) oder exakte ID (Schritt 1/2) aufgeloest.
    # Alles andere wird vom Aufrufer fail-closed mit UNKNOWN_AGENT blockiert.

    return None, ""


def _build_kader_roster_summary():
    """Erstellt eine lesbare, gegliederte Liste aller real existierenden Agenten für das Delegations-Prompt."""
    try:
        profiles = api_get_hermes_profiles()
        lines = []
        for p in profiles:
            pid = p.get("id")
            # D02/MED: 'micha' ist aus der SSOT entfernt — nie wieder Sonderfall.
            if not pid or pid in ("founder", "telegram_bot"):
                continue
            pname = p.get("person_name") or p.get("name") or pid
            role = p.get("role") or p.get("name") or ""
            lines.append(f"  • {pid} ({pname} | {role})")
        return "\n".join(lines)
    except Exception:
        return ""


def _get_delegation_prompt_for(agent_id: str):
    """Liefert das Protokoll-Prompt für Tier 1/2-Agenten, sonst None."""
    try:
        node = _load_org_hierarchy_map().get(agent_id)
        if node and node.get("tier") in (1, 2):
            tier = node["tier"]
            prompt = DELEGATION_PROTOCOL_PROMPT.replace(
                '{"APEX: an alle Agenten" if TIER==1 else "LEAD: nur an dein eigenes Team"}',
                ("APEX: an alle Agenten" if tier == 1 else "LEAD: nur an dein eigenes Team")
            )
            roster = _build_kader_roster_summary()
            if roster:
                prompt += f"\n\n=== OFFIZIELLES KADER-REGISTER (NUR DIESE ECHTEN IDs IM FELD 'ziel_agent' NUTZEN!) ===\n{roster}\n"
            return prompt
    except Exception as e:
        logger.warning(f"[Delegation] Protokoll-Prompt-Aufbau fehlgeschlagen: {e}")
    return None


class DelegationIssueList(list):
    """Invalid-Liste mit D13-Fanout-Metadaten (2-Tupel-API bleibt kompatibel)."""

    fanout_cap: int = 0
    fanout_blocked: bool = False
    omitted_count: int = 0


def _parse_delegation_blocks(text: str, fanout_cap: Optional[int] = None):
    """Findet alle ```delegation```-JSON-Blöcke sowie Fallback-JSON-Zeilen.

    D13/HIGH: zentraler Fan-out-Cap (5). Ueberschuss wird NICHT stillschweigend
    gekuerzt, sondern als `FANOUT_CAP` im Invalid-Kanal quittiert. chat.py
    (anderer Agent) muss zusaetzlich die Legacy-Regex-Payloads in dieselbe
    Menge aufnehmen — siehe Handoff in backend/trajectory_budget.py.
    """
    cap = MAX_DELEGATIONS_PER_RESPONSE if fanout_cap is None else max(1, int(fanout_cap))
    valid, invalid = [], DelegationIssueList()
    seen_hashes = set()
    
    # 1. Standard: ```delegation ... ``` Blöcke
    for m in re.finditer(r"```(?:delegation|json)?\s*\n(.*?)```", text, re.DOTALL):
        raw = m.group(1).strip()
        if '"ziel_agent"' in raw:
            # D11: auch unvollständige Payloads (z. B. ohne `auftrag`) müssen
            # als Schemafehler sichtbar werden, nicht still verschwinden.
            try:
                # F030: EIN kanonisches Schema, EIN Aufruf, serverseitig
                # aufgelöst und signiert (kein Freitext, keine Doppelprojektion).
                payload = canonicalize_delegation_payload(raw)
                h = f"{payload['ziel_agent']}:{payload['auftrag'][:40]}"
                if h not in seen_hashes:
                    valid.append(payload)
                    seen_hashes.add(h)
            except Exception as e:
                # Fail-closed: Schemafehler ODER fehlender HMAC-Key => sichtbar.
                invalid.append({"raw": raw[:200], "error": f"DelegationPayload: {e}"})

    # 2. Fallback: Ungefenced JSON-Objekte mit "ziel_agent" und "auftrag"
    for m in re.finditer(r'\{[^{}]*"ziel_agent"\s*:\s*"[^"]+"[^{}]*"auftrag"\s*:\s*"[^"]+"[^{}]*\}', text, re.DOTALL):
        raw = m.group(0).strip()
        try:
            payload = canonicalize_delegation_payload(raw)
            h = f"{payload['ziel_agent']}:{payload['auftrag'][:40]}"
            if h not in seen_hashes:
                valid.append(payload)
                seen_hashes.add(h)
        except Exception as exc:
            logger.warning("[Delegation] Schema-ungueltiger Legacy-Payload verworfen: %s", exc)

    invalid.fanout_cap = cap
    invalid.fanout_blocked = len(valid) > cap
    invalid.omitted_count = max(0, len(valid) - cap)
    if invalid.fanout_blocked:
        omitted = valid[cap:]
        valid = valid[:cap]
        invalid.append({
            "raw": "", "error": "FANOUT_CAP", "blocked": True, "cap": cap,
            "omitted": len(omitted),
            "reason": f"MAX_DELEGATIONS_PER_RESPONSE={cap} überschritten",
            "handoff": "archon/routers/chat.py: Legacy-Payloads in dieselbe Dedup-Menge aufnehmen",
        })
        logger.error("[Delegation] FANOUT_CAP: %s von %s Delegationen blockiert.",
                     invalid.omitted_count, invalid.omitted_count + cap)
    return valid, invalid


def _project_approval_evidence(parent_project_id: str) -> Dict[str, str]:
    """H-15-6/F023: echten Freigabe-Nachweis aus der SSOT lesen.

    Es wird NIE eine Freigabe erfunden. Ohne persistierte ``approval_id``
    (Sidecar oder `task_events.kind='approved'`) bleibt der Nachweis leer und
    der Abschlussbericht wird als ENTWURF markiert.
    """
    empty = {"approval_id": "", "approver": ""}
    if not parent_project_id:
        return empty
    try:
        from backend.operations_api import _load_kanban_meta

        meta = _load_kanban_meta() or {}
        projects = meta.get("projects") or {}
        records = [projects.get(parent_project_id) or {}]
        tasks_meta = meta.get("tasks") or {}
        for t_meta in tasks_meta.values():
            if isinstance(t_meta, dict) and str(t_meta.get("parent_project_id") or "") == str(parent_project_id):
                records.append(t_meta)
        for rec in records:
            aid = str(rec.get("approval_id") or "").strip()
            if aid:
                return {"approval_id": aid, "approver": str(rec.get("approved_by") or rec.get("approver") or "")}
    except Exception as exc:
        logger.debug("[AutoOrchestrator] Approval-Sidecar nicht lesbar: %s", exc)

    try:
        from backend.operations_api import _get_kanban_connection

        conn = _get_kanban_connection()
        try:
            row = conn.execute(
                "SELECT e.payload FROM task_events e JOIN tasks t ON t.id = e.task_id "
                "WHERE t.project_id = ? AND e.kind = 'approved' ORDER BY e.created_at DESC LIMIT 1",
                (parent_project_id,),
            ).fetchone()
            if row:
                payload = row[0]
                if isinstance(payload, str):
                    payload = json.loads(payload)
                if isinstance(payload, dict):
                    aid = str(payload.get("approval_id") or "").strip()
                    if aid:
                        return {
                            "approval_id": aid,
                            "approver": str(payload.get("approved_by") or payload.get("by") or payload.get("approver") or ""),
                        }
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("[AutoOrchestrator] Approval-Event nicht lesbar: %s", exc)
    return empty


async def _trigger_autonomous_orchestrator_followup(delegator_id, session_id, task_id, status, result, final_title, parent_project_id=None):
    """Prüft, ob alle Teilaufgaben eines Projekts abgeschlossen sind.
    Wenn ja, synthetisiert Robert (executive_decision_architect) die Ergebnisse,
    erstellt das finale HTML-Dokument in 03_Endprodukte/ und informiert den Nutzer."""
    try:
        from backend.operations_api import _get_kanban_connection
        kc = _get_kanban_connection()
        try:
            if not parent_project_id:
                r = kc.execute("SELECT project_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
                parent_project_id = r[0] if r else None
            
            if not parent_project_id:
                return

            pending = kc.execute(
                "SELECT COUNT(*) FROM tasks WHERE project_id = ? AND status NOT IN ('done', 'review', 'failed', 'blocked')",
                (parent_project_id,)
            ).fetchone()[0]

            if pending > 0:
                logger.info(f"[AutoOrchestrator] Projekt {parent_project_id}: noch {pending} Aufgaben ausstehend.")
                return

            rows = kc.execute(
                "SELECT id, title, assignee, result, status FROM tasks WHERE project_id = ? ORDER BY rowid ASC",
                (parent_project_id,)
            ).fetchall()
        finally:
            kc.close()

        if not rows:
            return

        # H-15-6/F023: Freigabe NIE erfinden — nur mit echtem approval_id.
        _approval = _project_approval_evidence(parent_project_id)
        _is_approved = bool(_approval["approval_id"])
        if _is_approved:
            _approval_line = (
                f"Freigegeben durch <strong>{_html.escape(_approval['approver'] or 'verifizierter Approver')}</strong> "
                f"(approval_id: <code>{_html.escape(_approval['approval_id'])}</code>)"
            )
            _status_badge = "● Projekt freigegeben"
        else:
            _approval_line = "<strong>ENTWURF — nicht freigegeben</strong> (kein approval_id im Task-Kontext)"
            _status_badge = "◐ ENTWURF — keine Freigabe"

        obs_dir = None
        for cand in (PROJEKTE_DIR, os.path.join(WORKSPACE_DIR, "obsidian_vault", "01_PROJEKTE")):
            if os.path.isdir(cand):
                obs_dir = cand
                break
        
        proj_folder = None
        if obs_dir:
            for d in os.listdir(obs_dir):
                if parent_project_id.lower() in d.lower():
                    proj_folder = os.path.join(obs_dir, d)
                    break
            if not proj_folder:
                date_prefix = datetime.date.today().strftime("%Y%m%d")
                clean_name = parent_project_id.lower()
                if not clean_name.startswith("projekt-"):
                    clean_name = f"projekt-{clean_name}"
                proj_folder = os.path.join(obs_dir, f"{date_prefix}-{clean_name}")
                os.makedirs(os.path.join(proj_folder, "01_Zwischenberichte"), exist_ok=True)
                os.makedirs(os.path.join(proj_folder, "02_Medien"), exist_ok=True)
                os.makedirs(os.path.join(proj_folder, "03_Endprodukte"), exist_ok=True)

        # H-15-6: ohne echte Freigabe bleibt der Bericht ein Entwurf in
        # 01_Zwischenberichte — kein finales Artefakt in 03_Endprodukte.
        end_dir = (
            os.path.join(proj_folder, "03_Endprodukte" if _is_approved else "01_Zwischenberichte")
            if proj_folder else None
        )
        if end_dir:
            os.makedirs(end_dir, exist_ok=True)
            clean_proj_name = parent_project_id.replace("projekt-", "").title()
            html_filename = (
                f"{clean_proj_name}_Abschlussbericht.html" if _is_approved
                else f"{clean_proj_name}_ENTWURF.html"
            )
            html_full_path = os.path.join(end_dir, html_filename)
            
            safe_proj_name = _html.escape(clean_proj_name, quote=True)
            task_items_html = ""
            for r_id, r_title, r_assignee, r_res, r_stat in rows:
                safe_id = _html.escape(str(r_id or ""), quote=True)
                safe_title = _html.escape(str(r_title or ""), quote=True)
                safe_assignee = _html.escape(str(r_assignee or ""), quote=True)
                snippet = _html.escape((r_res or "").strip()[:500], quote=True).replace("\n", "<br>")
                task_items_html += f"""
                <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 16px; margin-bottom: 14px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <strong style="color: #38bdf8;">Task #{safe_id}: {safe_title}</strong>
                        <span style="font-size: 11px; padding: 2px 8px; border-radius: 4px; background: rgba(16,185,129,0.2); color: #34d399; font-weight: bold;">@{safe_assignee}</span>
                    </div>
                    <div style="font-size: 13px; color: #cbd5e1; line-height: 1.5;">{snippet}...</div>
                </div>
                """

            html_doc = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <title>Abschlussbericht: {safe_proj_name}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #09090b; color: #f4f4f5; line-height: 1.6; padding: 40px 20px; }}
    .container {{ max-width: 860px; margin: 0 auto; background: #18181b; border: 1px solid #27272a; border-radius: 12px; padding: 32px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
    h1 {{ font-size: 26px; font-weight: 800; color: #ffffff; margin-bottom: 6px; }}
    .badge {{ display: inline-block; padding: 4px 12px; border-radius: 9999px; font-size: 11px; font-weight: 700; background: rgba(16,185,129,0.15); color: #10b981; border: 1px solid #10b981; margin-bottom: 16px; text-transform: uppercase; }}
    .summary {{ background: rgba(14,165,233,0.08); border-left: 4px solid #0ea5e9; padding: 16px; border-radius: 6px; margin-bottom: 24px; font-size: 15px; color: #e0f2fe; }}
    h2 {{ font-size: 18px; border-bottom: 1px solid #27272a; padding-bottom: 8px; margin: 28px 0 16px 0; color: #f8fafc; }}
    footer {{ margin-top: 36px; padding-top: 16px; border-top: 1px solid #27272a; font-size: 12px; color: #71717a; display: flex; justify-content: space-between; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="badge">{_status_badge}</div>
    <h1>Projekt: {safe_proj_name} — {'Abschlussbericht' if _is_approved else 'Entwurf'}</h1>
    <div style="font-size: 13px; color: #a1a1aa; margin-bottom: 20px;">Autonom koordiniert durch <strong>Robert (Executive Decision Architect)</strong> | {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}</div>
    
    <div class="summary">
      <strong>Management Summary:</strong><br>
      Alle {len(rows)} Arbeitspakete des Projekts wurden von den spezialisierten Fachagenten erfolgreich ausgearbeitet, verifiziert und zusammengeführt. Das Vorhaben steht für die weitere Umsetzung bereit.
    </div>

    <h2>Abgeschlossene Teilaufgaben & Ergebnisse</h2>
    {task_items_html}

    <footer>
      <div>Archon OS — Autonome Orchestration</div>
      <div>{_approval_line}</div>
    </footer>
  </div>
</body>
</html>"""
            with open(html_full_path, "w", encoding="utf-8") as f:
                f.write(html_doc)

        if session_id:
            _final_dir = "03_Endprodukte" if _is_approved else "01_Zwischenberichte"
            _lead = (
                f"🎉 **Projekt '{parent_project_id}' ist vollständig abgeschlossen!**"
                if _is_approved else
                f"◐ **Projekt '{parent_project_id}': ENTWURF — keine Freigabe vorhanden.**\n\n"
                "Finalisierung blockiert: es existiert kein verifizierter `approval_id`-Nachweis. "
                "Bitte Freigabe über das HITL-Gate einholen."
            )
            summary_msg = (
                f"{_lead}\n\n"
                f"Alle {len(rows)} Teilaufgaben wurden von den Fachagenten erfolgreich abgearbeitet und von mir zusammengeführt.\n\n"
                f"📄 **{'Finaler Abschlussbericht' if _is_approved else 'Entwurfsbericht'}:**\n"
                f"- Gespeichert in: `01_PROJEKTE/{os.path.basename(proj_folder) if proj_folder else parent_project_id}/{_final_dir}/`\n"
                f"- Direkter Link im Showroom & Operations-Dashboard verfügbar.\n\n"
                f"Die Fachagenten wurden nach erfolgreichem Projektabschluss wieder in den Standby versetzt."
            )
            _save_message_to_db(session_id, "assistant", summary_msg)
            broadcast_event("chat_message_received", {
                "session_id": session_id,
                "agent_id": "executive_decision_architect",
                "content": summary_msg,
                "project_completed": parent_project_id
            })
            logger.info(f"[AutoOrchestrator] Projekt {parent_project_id} erfolgreich autonom abgeschlossen!")
    except Exception as e:
        logger.error(f"[AutoOrchestrator] Fehler bei autonomem Followup: {e}")


_ACTIVE_WATCHERS: set[str] = set()
# C10: Referenz auf den gestarteten Worker-Task, damit der Watcher bei
# Deadline-UEberschreitung wirklich abbrechen kann (vorher nur Textnachricht).
_DELEGATED_WORKER_TASKS: dict[str, Any] = {}

# Terminale Kanban-Status (auf die ein Delegations-Watcher wartet).
_TERMINAL_TASK_STATUSES = ("done", "blocked", "review", "failed", "cancelled")


def _poll_kanban_row(task_id: str):
    """Einzelner Kanban-DB-Read fuer den Watcher.

    Modul-Ebene statt Closure, damit der Safety-Poll in Tests ersetzt werden
    kann und nicht auf echte DB/Netzwerk zugreifen muss.
    """
    from backend.operations_api import _get_kanban_connection as _kgc
    kc = _kgc()
    try:
        return kc.execute("SELECT status, result, title FROM tasks WHERE id = ?", (task_id,)).fetchone()
    finally:
        kc.close()


def _mark_delegation_blocked(task_id: str, reason: str) -> None:
    """F-039: Task nach fehlgeschlagenem Worker-Spawn terminal blockieren."""
    try:
        from backend.operations_api import _get_kanban_connection
        kconn = _get_kanban_connection()
        try:
            cols = {r[1] for r in kconn.execute("PRAGMA table_info(tasks)").fetchall()}
            if "block_kind" in cols:
                kconn.execute(
                    "UPDATE tasks SET status='blocked', block_kind='worker_spawn_failed' WHERE id=?",
                    (task_id,),
                )
            else:
                kconn.execute("UPDATE tasks SET status='blocked' WHERE id=?", (task_id,))
            kconn.commit()
        finally:
            kconn.close()
    except Exception as exc:
        logger.error("[Delegation] Block-Markierung fuer '%s' fehlgeschlagen: %s", task_id, exc)


def _enqueue_delegation_failure(task_id: str, prof_id: str, status: str, result: str) -> Dict[str, Any]:
    """Fehlgeschlagene Delegation in die Shared Queue stellen (idempotent).

    Die Queue übernimmt damit attempt/dead_letter/priority für Aufträge, die
    bisher als Kanban-Ad-hoc-Eintrag endeten. Ein Fehler hier darf die
    Statusmeldung an den Delegator nicht verhindern.
    """
    try:
        from backend.dead_letter_queue import dead_letter_queue_manager
        return dead_letter_queue_manager.enqueue_task(
            job_type="delegation_result",
            source_module="archon.core.delegation",
            payload={
                "task_id": str(task_id),
                "agent_id": str(prof_id or ""),
                "status": str(status),
                "result": mark_truncated(result, 2000, artifact="original result"),
            },
            priority=2,
            idempotency_key=f"delegation-result:{task_id}:{status}",
        )
    except Exception as exc:
        logger.debug(f"[Delegation] Shared-Queue-Enqueue fehlgeschlagen: {exc}")
        return {"queued": False, "error": str(exc)}


def _mark_delegation_task_timed_out(task_id: str, reason: str) -> bool:
    """D (Härtungsaudit): Delegations-Timeout terminal im Kanban persistieren.

    Vorher blieb der Task trotz ``worker.cancel()`` auf ``in_progress``; der
    Deadlock-Supervisor setzte ihn nach 120 s auf ``todo`` und ein zweiter
    Worker lief mit doppelten Seiteneffekten. Fail-Closed: bereits terminale
    Status werden nie ueberschrieben. Nutzt exakt denselben
    ``_get_kanban_connection(maintenance=True)``-Mechanismus wie
    ``operations_api.py`` (inkl. ``task_events``- und Broadcast-Event).
    """
    now_iso = datetime.datetime.now().isoformat()
    from backend.operations_api import _get_kanban_connection as _kgc
    conn = _kgc(maintenance=True)
    changed = False
    try:
        cur = conn.execute(
            "UPDATE tasks SET status = 'cancelled', result = ?, completed_at = ? "
            "WHERE id = ? AND status NOT IN ('done', 'blocked', 'review', 'failed', 'cancelled')",
            (f"DELEGATION-TIMEOUT: {reason}"[:2000], now_iso, str(task_id)),
        )
        changed = bool(getattr(cur, "rowcount", 0))
        if changed:
            conn.execute(
                "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'cancelled', ?, ?)",
                (str(task_id), json.dumps({
                    "status": "cancelled",
                    "block_kind": "worker_timeout",
                    "reason": "delegation_timeout",
                    "summary": reason[:200],
                }), now_iso),
            )
        conn.commit()
    finally:
        conn.close()
    if changed:
        try:
            broadcast_event("kanban_updated", {
                "action": "status_changed",
                "task_id": str(task_id),
                "from": "in_progress",
                "to": "cancelled",
            })
        except Exception as exc:
            logger.debug(f"[Delegation] Timeout-Broadcast fehlgeschlagen: {exc}")
    return changed


async def _watch_delegated_task(
    task_id: str,
    s_id: str,
    prof_id: str,
    origin_sess_id: Optional[str] = None,
    orig_delegator: Optional[str] = None,
    parent_pid: Optional[str] = None,
    acceptance_criteria: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> None:
    """Beobachtet den Kanban-Task, während der Hermes-Agent-Worker ihn abarbeitet,
    und spiegelt das Endergebnis in die Sub-Session (Rücklauf ohne Doppel-Ausführung)."""
    if not task_id or task_id in _ACTIVE_WATCHERS:
        return
    _ACTIVE_WATCHERS.add(task_id)
    try:
        from utils.path_jail import safe_filename, safe_identifier, safe_path_within

        clean_tid = safe_identifier(task_id, "task_id")

        # Batch B/8: Event-Push statt Polling. Persistierte Konfiguration mit
        # rueckwaertskompatiblen Defaults des alten Watchdogs.
        try:
            from backend.autonomy_settings import get_module_config
            cfg = get_module_config("delegation") or {}
        except Exception:
            cfg = {}

        def _cfg_number(key: str, default: float, cast) -> float:
            try:
                value = cast(cfg.get(key, default))
            except (TypeError, ValueError):
                return default
            return value if value > 0 else default

        deadline_seconds = _cfg_number("watcher_deadline_seconds", 1200, float)
        fallback_poll_seconds = _cfg_number("watcher_fallback_poll_seconds", 60, float)
        retry_count = int(_cfg_number("watcher_retry_count", 3, float))

        # D: die Lease hat eine MIN-TTL von 120 s (deadlock_supervisor). Der
        # alte Konfigurations-Default lag weit darueber; der Heartbeat haelt die
        # Lease zwar, aber fail-closed bleiben wir unter der TTL, damit ein
        # verwaister Watcher nie in den Supervisor-Rollover (todo) laeuft.
        try:
            from backend.deadlock_supervisor import MIN_LEASE_TTL_SECONDS as _LEASE_TTL
        except Exception:
            _LEASE_TTL = 120
        deadline_seconds = min(deadline_seconds, max(30.0, float(_LEASE_TTL) - 30.0))

        deadline = time.time() + deadline_seconds
        final = None
        poll_retries = 0

        async def _safety_poll():
            """Ein DB-Read als Fallback fuer verpasste Events; liefert Zeile oder None."""
            try:
                row = await asyncio.to_thread(_poll_kanban_row, task_id)
                if row and row[0] in _TERMINAL_TASK_STATUSES:
                    return row
            except Exception as poll_err:
                logger.debug(f"[Delegation] Kanban-Poll fuer {task_id} fehlgeschlagen: {poll_err}")
            return None

        # Einmal abonnieren, ueber die gesamte Laufzeit warten, immer abmelden.
        events = subscribe_events()
        try:
            while time.time() < deadline:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                try:
                    payload = await asyncio.wait_for(
                        events.get(), timeout=min(fallback_poll_seconds, remaining)
                    )
                except asyncio.TimeoutError:
                    # Safety-Poll: ein verpasstes Event darf den Watcher nicht
                    # bis zum Deadline blockieren.
                    row = await _safety_poll()
                    if row is not None:
                        final = row
                        break
                    poll_retries += 1
                    if poll_retries > retry_count:
                        logger.warning(
                            f"[Delegation] Watcher {task_id}: {poll_retries} Safety-Polls "
                            f"ohne Endstatus (Toleranz {retry_count}) — warte weiter bis zum Deadline."
                        )
                    continue

                # Nur kanban_updated mit passender task_id und terminalem Status.
                try:
                    event = json.loads(payload) if isinstance(payload, str) else payload
                except (TypeError, ValueError):
                    continue
                if not isinstance(event, dict) or event.get("type") != "kanban_updated":
                    continue
                data = event.get("data") or {}
                if not isinstance(data, dict):
                    continue
                if str(data.get("task_id") or "") != str(task_id):
                    continue
                to_status = str(data.get("to") or data.get("status") or "").strip().lower()
                if to_status not in _TERMINAL_TASK_STATUSES:
                    continue

                # Genau EIN DB-Read bei passendem Terminal-Event.
                row = await _safety_poll()
                if row is not None:
                    final = row
                    break
                logger.debug(
                    f"[Delegation] Terminal-Event fuer {task_id} ({to_status}), "
                    "Kanban-Zeile noch nicht terminal — warte weiter."
                )
        finally:
            unsubscribe_events(events)

        if final is None:
            # C10: der "Timeout" war vorher kosmetisch — der Sub-Agent lief
            # ungebremst weiter und verbrauchte Budget. Jetzt Task abbrechen.
            timeout_text = (
                f"{deadline_seconds / 60:g} Minuten" if deadline_seconds >= 60
                else f"{deadline_seconds:g} Sekunden"
            )
            timeout_reason = (
                f"länger als {timeout_text} ohne Endstatus (Deadline {deadline_seconds:g}s)"
            )
            # D: ZUERST terminal markieren und in die DLQ stellen, DANN den
            # Worker abbrechen. Der Worker koennte in einem blockierenden Call
            # stecken und die CancelledError-Statusmeldung nie ausfuehren.
            timed_out = _mark_delegation_task_timed_out(task_id, timeout_reason)
            _enqueue_delegation_failure(task_id, prof_id, "cancelled", timeout_reason)
            logger.warning(
                "[Delegation] Timeout %s — Task terminal markiert: %s", task_id, timed_out
            )
            worker = _DELEGATED_WORKER_TASKS.pop(task_id, None)
            if worker is not None and not worker.done():
                worker.cancel()
                logger.warning("[Delegation] Worker-Task %s nach Deadline abgebrochen", task_id)
            _save_message_to_db(s_id, "assistant",
                f"⏱️ DELEGATION-TIMEOUT — Der Task läuft {timeout_reason}. "
                "Status im Kanban: fehlgeschlagen (kein automatischer Wiederholungslauf).")
            return
        _DELEGATED_WORKER_TASKS.pop(task_id, None)
        status, result = final[0], (final[1] or "").strip()
        final_title = (final[2] or "").strip()

        # Batch D/4: Supervisor-Rollover bei blockierten/fehlgeschlagenen Tasks.
        supervisor_hint = ""
        if status in ("blocked", "failed"):
            try:
                _current_supervisor = resolve_supervisor(str(prof_id))
                _rollover = on_supervisor_failure(
                    str(prof_id), _current_supervisor, reason=str(status)
                )
                _new_supervisor = str(_rollover.get("new_supervisor") or _current_supervisor)
                _chain_val = _rollover.get("chain")
                _chain_str = ", ".join(str(x) for x in _chain_val) if isinstance(_chain_val, (list, tuple)) else _new_supervisor
                supervisor_hint = (
                    f"\n\n**Supervisor-Rollover:** @{_new_supervisor} "
                    f"(Kette: {_chain_str})"
                )
                logger.info(
                    f"[Delegation] Rollover fuer {prof_id}: {_current_supervisor} -> {_new_supervisor} ({status})"
                )
            except Exception as rollover_exc:
                logger.debug(f"[Delegation] Supervisor-Rollover fehlgeschlagen: {rollover_exc}")

        if not result:
            try:
                from backend.operations_api import _get_kanban_connection as _kgc2
                kc = _kgc2()
                ev = kc.execute(
                    "SELECT payload FROM task_events WHERE task_id = ? AND kind IN ('completed','blocked') ORDER BY rowid DESC LIMIT 1",
                    (task_id,)).fetchone()
                kc.close()
                if ev and ev[0]:
                    try:
                        parsed_ev = json.loads(ev[0])
                        result = parsed_ev.get("summary") or parsed_ev.get("reason") or ""
                    except Exception:
                        result = mark_truncated(ev[0], 500, artifact="task_events.summary")
            except Exception as ev_exc:
                logger.debug(f"[Delegation] Fallback-Event-Lesen fuer {task_id} fehlgeschlagen: {ev_exc}")
        attach_note = ""
        try:
            attach_dir = os.path.join(OPT_DATA_DIR, "kanban", "attachments", clean_tid)
            if os.path.isdir(attach_dir):
                files = [safe_filename(f) for f in os.listdir(attach_dir) if os.path.isfile(os.path.join(attach_dir, f))]
                if files:
                    attach_note = "\n\n**Angehängte Artefakte:**\n" + "\n".join(f"- {f}" for f in files)
        except OSError as att_exc:
            logger.debug(f"[Delegation] Anhangsverzeichnis fuer {task_id} nicht lesbar: {att_exc}")
        obsidian_rel = None
        proj_folder = None  # Batch D/1: Artefaktpfad fuer das A2A-Envelope.
        try:
            title = (final_title or "Delegation")[:80]
            slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")[:50] or "auftrag"
            for cand in (PROJEKTE_DIR,
                          os.path.join(WORKSPACE_DIR, "obsidian_vault", "01_PROJEKTE")):
                try:
                    os.makedirs(cand, exist_ok=True)
                    obsidian_rel = cand
                    break
                except Exception:
                    continue
            if obsidian_rel:
                fan_parent = None
                fan_parent_title = None
                try:
                    fan_parent, fan_parent_title = await asyncio.to_thread(
                        mc_get_parent_context_sqlite, task_id
                    )
                except Exception as fp_exc:
                    logger.debug(f"[Delegation] Parent-Kontext fuer {task_id} nicht ladbar: {fp_exc}")
                try:
                    from backend.post_task_pipeline import project_folder_name
                    proj_name = project_folder_name({
                        "id": clean_tid, "title": final_title or "Delegation",
                        "parent_project_id": fan_parent or "",
                        "parent_project_title": fan_parent_title or "",
                    })
                except Exception:
                    proj_name = f"{datetime.datetime.now().strftime('%Y%m%d')}-{clean_tid}-{slug}"
                proj_folder = safe_path_within(os.path.join(obsidian_rel, proj_name), [obsidian_rel], allow_dirs=True)
                target_sub = "01_Zwischenberichte" if parent_pid else "03_Endprodukte"
                dest_dir = os.path.join(proj_folder, target_sub)
                os.makedirs(dest_dir, exist_ok=True)
                for sub in ("01_Zwischenberichte", "02_Medien", "03_Endprodukte"):
                    os.makedirs(os.path.join(proj_folder, sub), exist_ok=True)
                try:
                    att_src = os.path.join(OPT_DATA_DIR, "kanban", "attachments", clean_tid)
                    if os.path.isdir(att_src):
                        medien_dir = os.path.join(proj_folder, "02_Medien")
                        for f in os.listdir(att_src):
                            src_f = os.path.join(att_src, f)
                            if os.path.isfile(src_f):
                                sf_name = safe_filename(f)
                                dst_f = safe_path_within(os.path.join(medien_dir, sf_name), [medien_dir], allow_write=True, allow_dirs=False)
                                shutil.copy2(src_f, dst_f)
                except Exception as cp_exc:
                    logger.warning(f"[Delegation] Medien-Kopie fuer {task_id} fehlgeschlagen: {cp_exc}")
                result_fn = safe_filename(f"{clean_tid}-{slug}.md")
                result_path = safe_path_within(os.path.join(dest_dir, result_fn), [dest_dir], allow_write=True, allow_dirs=False)
                with open(result_path, "w", encoding="utf-8") as fh:
                    fh.write(f"# {title}\n\n"
                             f"**Task:** `{task_id}` | **Ziel-Agent:** `@{prof_id}` | **Status:** {status.upper()}\n\n"
                             f"{result or '(Ergebnis siehe Kanban-Task-Events und Anhänge in 02_Medien/.)'}\n")
                proj_title = fan_parent_title if (fan_parent and fan_parent_title) else title
                p_herkunft = (f"Teilauftrag von Projekt `{fan_parent}`" if fan_parent
                              else f"Delegation über Archon OS (Task `{task_id}`)")
                p_parent_line = f'parent_project: "{fan_parent}"\n' if fan_parent else ""
                try:
                    with open(os.path.join(proj_folder, "PROJEKT.md"), "x", encoding="utf-8") as fh:
                        fh.write("---\nproject_folder: \"" + os.path.basename(proj_folder) + "\"\ncreated_at: \""
                                + str(datetime.datetime.now().timestamp()) + "\"\n"
                                "title: \"" + proj_title + "\"\nstatus: \"" + str(status)
                                + "\"\nsource_task: \"" + task_id + "\"\n"
                                "source: \"delegation_engine_v2\"\n" + p_parent_line + "---\n\n"
                                "# Projekt: " + str(proj_title) + "\n\n"
                                "- **Herkunft:** " + p_herkunft + "\n"
                                "- **Ziel-Agent:** `@" + str(prof_id) + "` | **Status:** " + str(status).upper() + "\n"
                                "- **Hauptdokument:** [[" + clean_tid + "-" + slug + "]]\n\n"
                                "### 📁 Projekt-Struktur:\n"
                                "- `01_Zwischenberichte/`: Entwürfe und Arbeitsprotokolle\n"
                                "- `02_Medien/`: Artefakte der Fachagenten\n"
                                "- `03_Endprodukte/`: [[" + clean_tid + "-" + slug + "]]"
                                + ("+ Lisa-Synthese + finale Beschlussvorlage" if fan_parent else "")
                                + "\n\n---\n[[00_VAULT_KNOWLEDGE]] | [[Archiv-Hubs]]\n")
                except FileExistsError:
                    logger.debug(f"[Delegation] PROJEKT.md existiert bereits in {proj_folder}")
                obsidian_rel = os.path.basename(proj_folder)
        except Exception as oe:
            logger.warning(f"[Delegation] Obsidian-Export fehlgeschlagen: {oe}")
            obsidian_rel = None
        if status == "done":
            msg = ("✅ DELEGATION ABGESCHLOSSEN — Der Sub-Agent hat die Aufgabe erledigt.\n\n"
                   f"**Zusammenfassung/Ergebnis:**\n{result or '(siehe Kanban-Task und Anhänge)'}{attach_note}\n\n"
                   f"Task-ID: {task_id} | Status im Kanban: done"
                   + (f"\n📁 Obsidian-Projekt: `01_PROJEKTE/{obsidian_rel}` (auch im Showroom sichtbar)" if obsidian_rel else ""))
        elif status == "review":
            msg = ("🔍 DELEGATION IN REVIEW — Das Ergebnis liegt zur Prüfung bereit.\n\n"
                   f"**Ergebnis:**\n{result or '(siehe Kanban-Task)'}{attach_note}\n\nTask-ID: {task_id}")
        else:
            # Shared Queue: blockierte/failed Delegations werden mit attempt,
            # Idempotency-Key und Priorität weiterverarbeitet statt als
            # Kanban-Ad-hoc-Eintrag zu enden.
            _enqueue_delegation_failure(task_id, prof_id, status, result)
            msg = ("⛔ DELEGATION BLOCKIERT — Der Sub-Agent konnte die Aufgabe nicht abschließen.\n\n"
                   f"**Grund/Eskalation:**\n{result or 'Siehe Task-Events im Kanban (Kommentare des Agenten).'}{attach_note}\n\n"
                   f"Task-ID: {task_id} | Ggf. Kontextdaten nachliefern oder Aufgabe umformulieren."
                   + (f"\n📁 Dokumentation: `01_PROJEKTE/{obsidian_rel}`" if obsidian_rel else ""))
        msg += supervisor_hint
        _save_message_to_db(s_id, "assistant", msg)

        # D13: Trajectory terminal abschliessen + Flightlog-Event im
        # Run-Abschluss (Produzent im Tool-Chokepoint kommt von einem anderen
        # Agenten; hier nur der Abschluss-Aufruf, kein Coroutine-Replay).
        try:
            from backend.trajectory_budget import normalize_trajectory_id
            _w_tid = (
                _SESSION_TRAJECTORY.get(str(s_id))
                or _trajectory_for_task(str(task_id))
                or normalize_trajectory_id(None, origin_sess_id or task_id)
            )
            _finalize_trajectory(_w_tid, task_id, status)
            # D13/HIGH (A5-Nachlauf): derselbe Namensraum wie der Detektor in
            # core_dispatcher._guard_silent_failures() (flightlog_run_id).
            # Vorher `run_id=str(task_id)` — ein dritter, unlesbarer Raum.
            _flight_run_id = normalize_trajectory_id(
                str(task_id) if str(task_id).startswith("traj-") else None,
                root_ticket_id=str(task_id),
            )
            from backend.flightlog_backtester import record_flight_event
            record_flight_event(
                run_id=_flight_run_id, agent_id=str(prof_id),
                tool_name="delegation_run_complete",
                args={"trajectory_id": _w_tid, "status": status},
                tool_ok=str(status) in ("done", "review"), tokens_used=0,
            )
        except Exception as _w_exc:
            logger.debug("[Delegation] Run-Abschluss-Telemetrie nicht geschrieben: %s", _w_exc)

        if origin_sess_id and origin_sess_id != s_id:
            try:
                status_badge = "✅ ERLEDIGT" if status in ("done", "review") else "⛔ BLOCKIERT"
                # M-2/K-5: Formales A2A-Envelope statt "Message from 🤖" als
                # Freitext. Der Handoff-Desk existierte, wurde aber von keinem
                # Dispatcher-Pfad genutzt.
                handoff_id = ""
                try:
                    from backend.handoff_desk import handoff_desk
                    try:
                        from backend.trace_context import current_trace_id
                        _handoff_trace = str(current_trace_id() or "")
                    except Exception:
                        _handoff_trace = ""
                    # Batch D/1: vollständiges, typisiertes A2A-Envelope.
                    _status_key = str(status).strip().lower()
                    _confidence = 1.0 if _status_key == "done" else (0.6 if _status_key == "review" else 0.0)
                    _attachments = [
                        p for p in (
                            str(obsidian_rel or ""),
                            str(proj_folder or ""),
                        ) if p
                    ]
                    # D11/MED: Korrelation aus dem echten Trace-Kontext. Der
                    # Legacy-Fallback bleibt `correlation_id=f"task:{task_id}"`,
                    # greift aber nur ohne verfuegbaren Trace. Die reply_to-Kette
                    # kommt aus SQLite statt aus einem RAM-Dict.
                    correlation_id = f"task:{task_id}"
                    envelope = handoff_desk.create_handoff(
                        task_id=str(task_id),
                        from_agent=str(prof_id or "unknown"),
                        to_agent=str(orig_delegator or "default"),
                        deliverables={
                            # D11: vollständiges Ergebnis in der Datenbank,
                            # Kürzung nur explizit markiert in der Anzeige.
                            "result": str(result or ""),
                            "status": str(status),
                            "artifact_path": str(obsidian_rel or ""),
                        },
                        acceptance_criteria=_resolve_handoff_criteria(
                            acceptance_criteria, prof_id, task_id
                        ),
                        message_id=f"msg-{secrets.token_hex(6)}",
                        correlation_id=(f"trace:{_handoff_trace}" if _handoff_trace else f"task:{task_id}"),
                        reply_to=str(reply_to or handoff_desk.latest_handoff_id_for_task(parent_pid)),
                        confidence=_confidence,
                        attachments=_attachments,
                        trace_id=_handoff_trace,
                        session_id=str(origin_sess_id or s_id or ""),
                    )
                    handoff_id = str(envelope.get("handoff_id") or "")
                    # D11: HMAC wird nicht nur erzeugt, sondern im automatischen
                    # Delegationspfad auch konsumiert (verify_payload_hash liest
                    # den gespeicherten Envelope und vergleicht constant-time).
                    if handoff_id and not handoff_desk.verify_payload_hash(handoff_id):
                        logger.error(
                            "[Delegation] Handoff-HMAC ungueltig — %s wird nicht weitergegeben",
                            handoff_id,
                        )
                        handoff_id = ""
                    # D11/MED: kein RAM-Dict mehr. Der Envelope liegt bereits
                    # in `agent_handoffs` und wird dort unter task_id gelesen.
                except Exception as he:
                    logger.debug(f"[Delegation] Handoff-Envelope nicht angelegt: {he}")

                delegator_feedback = (
                    f"{status_badge}: Der Sub-Agent `@{prof_id}` hat Task `{task_id}` ({final_title}) abgeschlossen.\n\n"
                    f"**A2A-Handoff:** `{handoff_id or 'nicht protokolliert'}`\n"
                    f"**Ergebnis:**\n{mark_truncated(result, 4000, artifact='deliverables_json') if result else '(Ergebnis liegt im Projektordner/Kanban)'}\n"
                    f"{attach_note}\n\n"
                    f"*(Status im Kanban: `{status}`)*"
                    f"{supervisor_hint}"
                )
                # K-5: Das Ergebnis eines Sub-Agenten ist KEINE User-Aussage.
                # Vorher role='user' → Taint-/HITL-/Audit-Logik sah einen
                # Nutzer, der nie etwas gesagt hat.
                _save_message_to_db(origin_sess_id, "assistant", delegator_feedback)
                broadcast_event("chat_message_received", {
                    "session_id": origin_sess_id,
                    "agent_id": orig_delegator,
                    "task_id": task_id,
                    "status": status
                })
                if not parent_pid and orig_delegator in ("executive_decision_architect", "robert", "hermes-orchestrator", "founder", "default"):
                    _spawn_background(_trigger_autonomous_orchestrator_followup(
                        orig_delegator, origin_sess_id, task_id, status, result, final_title, parent_pid
                    ), name=f"followup_{task_id}")
            except Exception as feed_err:
                logger.warning(f"[Delegation] Feedback an Delegator-Session fehlgeschlagen: {feed_err}")

        try:
            _doss_dir = None
            vault_dir = _get_obsidian_vault_dir()
            if obsidian_rel:
                try:
                    _doss_dir = os.path.join(vault_dir, "01_PROJEKTE",
                                             obsidian_rel, "01_Zwischenberichte")
                except Exception:
                    _doss_dir = None
            if status in ("review", "blocked"):
                _doss = None
                if _doss_dir and (result or "").strip():
                    try:
                        from dossier_builder import build_dossier_from_report
                        _doss = build_dossier_from_report(
                            f"{'Review' if status == 'review' else 'Blockiert'}: {final_title}",
                            result, _doss_dir, f"{clean_tid}_{status}",
                            ref_id=task_id, quelle="Archon-Delegation")
                    except Exception as _de:
                        logger.warning(f"[Delegation] Dossier fehlgeschlagen: {_de}")
                await asyncio.to_thread(
                    _register_decision, task_id, "delegation_review",
                    final_title, result, task_id, _doss, "", None,
                    f"01_PROJEKTE/{obsidian_rel}" if obsidian_rel else None)
            else:
                from telegram_notify import notify_task_status
                notify_task_status(task_id, status, final_title, result, obsidian_rel or "",
                                   dossier_dir=_doss_dir or "")
        except Exception as tg_err:
            logger.warning(f"[Telegram] Delegations-Ping für Task {task_id} fehlgeschlagen: {tg_err}")

        # H-02-2/F031: `cancelled` ist ein real persistierbarer Terminalstatus
        # (Timeout-Pfad `_mark_delegation_task_timed_out`). Vorher fiel der
        # Watcher hier durch — kein MC-Ruecklauf, kein Fan-in, stummer Deadlock.
        if status in ("done", "review", "blocked", "failed", "cancelled"):
            try:
                fan_parent, _ = await asyncio.to_thread(mc_get_parent_context_sqlite, task_id)
                mc_status = (
                    "completed" if status in ("done", "review")
                    else ("blocked" if status == "blocked"
                          else ("cancelled" if status == "cancelled" else "failed"))
                )
                if status == "cancelled":
                    try:
                        from backend.operations_api import _get_kanban_connection as _kgc3
                        _kc = _kgc3()
                        _exists = _kc.execute(
                            "SELECT 1 FROM task_events WHERE task_id = ? AND kind = 'cancelled' LIMIT 1",
                            (task_id,),
                        ).fetchone()
                        if not _exists:
                            _kc.execute(
                                "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?,?,?,?)",
                                (task_id, "cancelled", json.dumps({
                                    "reason": (result or "Delegation abgebrochen")[:400],
                                    "via": "delegation_watcher",
                                    "mc_status": mc_status,
                                }), time.time()),
                            )
                            _kc.commit()
                        _kc.close()
                    except Exception as _cancelled_ev_exc:
                        logger.warning(
                            "[Delegation] cancelled-Event für %s nicht geschrieben: %s",
                            task_id, _cancelled_ev_exc,
                        )
                await asyncio.to_thread(
                    mc_update_task_sqlite,
                    task_id,
                    {
                        "status": mc_status,
                        "result_summary": (result or "")[:800],
                        "completed_at": time.time(),
                    },
                )
                if fan_parent:
                    _spawn_background(_invoke_fan_in(fan_parent), name=f"fan_in_{fan_parent}")
            except Exception as fan_err:
                logger.warning(f"[Delegation] Fan-in-Ruecklauf fehlgeschlagen: {fan_err}")
    except Exception as e:
        logger.error(f"[Delegation] Task-Watcher error: {e}")
    finally:
        _ACTIVE_WATCHERS.discard(task_id)


async def resume_pending_delegation_watchers() -> int:
    """Reaktiviert nach einem Neustart offene Delegations-Watcher aus kanban.db."""
    restarted = 0
    try:
        from backend.operations_api import _get_kanban_connection as _kgc
        kc = _kgc()
        try:
            rows = kc.execute(
                "SELECT t.id, t.assignee, t.project_id, te.payload "
                "FROM tasks t JOIN task_events te ON te.task_id = t.id "
                "WHERE te.kind = 'created' AND te.payload LIKE '%delegation_engine_v2%' "
                "AND t.status IN ('in_progress', 'todo')"
            ).fetchall()
        finally:
            kc.close()
        for tid, assignee, project_id, ev_payload in rows:
            if not tid or tid in _ACTIVE_WATCHERS:
                continue
            try:
                meta = json.loads(ev_payload or "{}")
            except Exception:
                meta = {}
            delegator = meta.get("delegator") or "executive_decision_architect"
            tgt_sess = meta.get("tgt_session_id") or f"sub_{delegator}_{assignee}_{tid}"
            origin_sess = meta.get("origin_session_id") or None
            # D13/BLOCKER: Kette unter demselben stabilen trajectory_id lesen,
            # schreiben und wiederherstellen — nicht unter tgt_sess.
            from backend.trajectory_budget import (
                ensure_trajectory,
                get_trajectory,
                normalize_trajectory_id,
            )
            _tid = normalize_trajectory_id(
                meta.get("trajectory_id"), meta.get("root_ticket_id") or origin_sess or tid,
                tgt_sess,
            )
            _SESSION_TRAJECTORY[tgt_sess] = _tid
            if origin_sess:
                _SESSION_TRAJECTORY[str(origin_sess)] = _tid
            ensure_trajectory(_tid, meta.get("root_ticket_id") or origin_sess or tid)
            # I: Kette aus dem persistierten created-Event wiederherstellen —
            # das RAM-Dict ueberlebt keinen Neustart.
            _restored_chain = meta.get("delegation_chain")
            if isinstance(_restored_chain, list) and _restored_chain:
                _put_chain(
                    _tid,
                    tuple(str(x) for x in _restored_chain if x)[:_MAX_DELEGATION_DEPTH + 1],
                    task_id=tid,
                )
            else:
                logger.warning(
                    "[Delegation] Keine persistierte Delegationskette fuer %s — "
                    "Zyklus-/Tiefenschranke wird aus trajectory_budgets wiederhergestellt.", tid
                )
                _row = get_trajectory(_tid)
                _visited = []
                try:
                    _visited = json.loads((_row or {}).get("visited_agents") or "[]")
                except Exception:
                    _visited = []
                _put_chain(_tid, tuple(str(x) for x in (_visited or [assignee]) if x), task_id=tid)
            _spawn_background(
                _watch_delegated_task(
                    tid, tgt_sess, assignee or "default", origin_sess, delegator, project_id or None,
                    acceptance_criteria=meta.get("acceptance_criteria"),
                    reply_to=meta.get("reply_to"),
                ),
                name=f"bg_watch_{tid}",
            )
            restarted += 1
        if restarted:
            logger.info(f"[Delegation] {restarted} offene(r) Delegations-Watcher nach Neustart fortgesetzt.")
    except Exception as e:
        logger.debug(f"[Delegation] Watcher-Recovery Hinweis: {e}")
    return restarted


def _execute_delegation(delegator_id, payload, provider, all_keys, origin_session_id=None):
    """Führt eine Delegation aus: Berechtigungsprüfung, Sub-Session, Kanban-Task,
    Hintergrund-Ausführung. Gibt eine Quittung als Text zurück (wird in die
    Delegator-Session geschrieben, damit der Agent sich erinnert)."""
    ziel_raw = str(payload.get("ziel_agent") or "").strip()
    auftrag = str(payload.get("auftrag") or "").strip()
    modell = str(payload.get("modell") or payload.get("model") or "").strip()
    prioritaet = str(payload.get("prioritaet") or "normal").strip().lower()
    reasoning_lvl = str(payload.get("reasoning_level") or payload.get("reasoning") or "medium").strip().lower()
    # Batch D/2: explizite Akzeptanzkriterien aus dem Delegations-Payload.
    acceptance_criteria = str(payload.get("acceptance_criteria") or "").strip()
    reply_to = str(payload.get("reply_to") or "").strip()

    profiles = api_get_hermes_profiles()
    ziel, resolve_note = _resolve_target_agent_id(ziel_raw, profiles)
    # H-02-1/F031: Default-Deny. Ein Alias darf niemals auf eine ID zeigen,
    # die nicht in der tier-geprüften SSOT liegt (sonst APEX-/Budget-Eskalation).
    _known_ids = {str(p.get("id") or "") for p in profiles}
    if ziel and ziel not in _known_ids:
        ziel = None
    _unknown_tid = _resolve_trajectory_id(payload, origin_session_id)
    if not ziel:
        return _block_receipt(
            _unknown_tid, ziel_raw or "?", [], "UNKNOWN_AGENT",
            "kein exakter ID-/Alias-Treffer in der verifizierten Profil-SSOT "
            "(Substring-Rollenauflösung ist gesperrt).",
        )

    # D13/BLOCKER: EIN stabiler trajectory_id-Key fuer Lesen+Schreiben+Resume.
    from backend.trajectory_budget import (
        ensure_trajectory,
        get_trajectory,
        reserve_hop,
    )
    _tid = _resolve_trajectory_id(payload, origin_session_id)
    if origin_session_id:
        _SESSION_TRAJECTORY[str(origin_session_id)] = _tid
    _root_ticket = str(payload.get("root_ticket_id") or origin_session_id or _tid)
    _had_parent_budget = get_trajectory(_tid) is not None
    # F032: vorhandene Tickets mit max_hops=5 werden hier auf die SSOT (3)
    # verschärft — `ensure_trajectory` darf nur verschärfen, nie erweitern.
    _traj = ensure_trajectory(_tid, _root_ticket, max_hops=_MAX_DELEGATION_DEPTH)
    _chain = _get_chain(_tid)
    _hard_depth = min(_MAX_DELEGATION_DEPTH, int(_traj.get("max_hops") or _MAX_DELEGATION_DEPTH))
    if not _had_parent_budget and not payload.get("root_ticket_id") and not origin_session_id:
        return _block_receipt(_tid, ziel, _chain, "NO_PARENT_BUDGET",
                              "Kein Root-Budget vorhanden — kein Budget-Minting pro Hop.")
    if ziel in _chain:
        return _block_receipt(_tid, ziel, _chain, "CYCLE_DETECTED",
                              f"{' → '.join(_chain + [ziel])}. Bitte eskalieren.")
    if len(_chain) >= _hard_depth:
        return _block_receipt(_tid, ziel, _chain, "DEPTH_EXCEEDED",
                              f"maximale Delegationstiefe ({_hard_depth}) erreicht.")

    allowed, reason = _check_delegation_permission(delegator_id, ziel)
    if not allowed:
        # Batch D/4: Eskalationshinweis aus der live aufgeloesten Hierarchie.
        return (f"❌ DELEGATION ABGELEHNT — Ziel: {ziel} ({ziel_raw}) | Grund: {reason} | "
                f"Eskalation an @{resolve_supervisor(ziel)}.")

    t_prof = next((p for p in profiles if p["id"] == ziel), None)
    if not t_prof:
        return f"❌ DELEGATION ABGELEHNT — Ziel-Agent '{ziel}' existiert nicht im Agenten-Kader."
    d_prof = next((p for p in profiles if p["id"] == delegator_id), None)
    t_name = (t_prof.get("person_name") or t_prof.get("name") or ziel)
    d_name = (d_prof.get("person_name") or d_prof.get("name") or delegator_id) if d_prof else delegator_id

    # Batch D/3: Eval-/Promotion-Gate vor dem Dispatch (nur wenn konfiguriert).
    gate_ok, gate_reason = _check_delegation_eval_gate(ziel, t_prof)
    if not gate_ok:
        logger.warning(f"[Delegation] Eval-Gate blockiert Delegation an {ziel}: {gate_reason}")
        return f"❌ DELEGATION ABGELEHNT — Eval-/Promotion-Gate für {ziel} nicht bestanden: {gate_reason}"

    # F22 (D02): Hop-Budget erst NACH allen Autorisierungs-, Profil- und Eval-Gates
    # reservieren, damit abgelehnte Delegationen keine Hops verbrauchen.
    _hop = reserve_hop(_tid, ziel, "delegation_switch", root_ticket_id=_root_ticket)
    if not _hop.get("allowed", False):
        return _block_receipt(_tid, ziel, _chain, str(_hop.get("reason") or "HOP_CAP_REACHED"),
                              f"hops_used={_hop.get('hops_used')}/{_hop.get('max_hops')}")

    # 3. Compute-optimierte Modell-Zuweisung für den Ziel-Agenten:
    # Verhindert, dass Subagenten unreflektiert teure Flaggschiff-Modelle (wie Opus) erben.
    if not modell:
        cat = (t_prof.get("category") or "").lower()
        role = (t_prof.get("role") or t_prof.get("name") or "").lower()
        t_id = ziel.lower()
        if any(w in t_id or w in role for w in ["vision", "design", "frontend", "ui", "ux"]):
            modell = "auto/best-vision"
        elif any(w in t_id or w in role for w in ["engineer", "developer", "coder", "devops", "security"]):
            modell = "auto/best-coding"
        elif any(w in t_id or w in role for w in ["strateg", "decision", "legal", "compliance", "law", "finance", "scrum", "board"]):
            modell = "auto/best-reasoning"
        else:
            p_mod = (t_prof.get("model") or "").strip()
            modell = p_mod if p_mod and p_mod not in ("", "free-forever") else "auto/best-coding"
    t_model = modell or "auto/best-coding"

    # M75/H-15-1: Strikte Rollen- & Tool-Isolation inkl. negativer Grenzen.
    isolated_scope = resolve_isolated_scope_with_role_limits(ziel, t_model, profiles)
    isolation_header = build_isolation_header_with_negative_scope(
        isolated_scope, known_id=bool(isolated_scope.get("found"))
    )

    # Batch C: Memory-Scope-Bindung pro Delegation. Sub-Agents operieren
    # standardmäßig im Projekt-Scope; der Delegator steht in der ACL und darf
    # die Ergebnisse mitlesen. TTL verhindert unbeschränktes Wachstum.
    try:
        from backend.core_memory_manager import SCOPE_PROJECT, normalize_scope
        memory_scope = normalize_scope(str(payload.get("memory_scope") or SCOPE_PROJECT))
    except Exception:
        memory_scope = "project"
    memory_acl = [str(delegator_id)] if delegator_id else []
    memory_ttl_seconds = 86400
    isolation_header += (
        f"\nMEMORY_SCOPE: {memory_scope} | ACL: {','.join(memory_acl) or '-'} "
        f"| TTL_SECONDS: {memory_ttl_seconds}"
    )

    tgt_sess = f"mc_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{ziel}_{secrets.token_hex(3)}"
    # I: ein Eintrag pro Hop; Wurzel-Agent zuerst, damit A->B->A als Zyklus
    # erkannt wird. Geschrieben wird unter EXAKT dem gelesenen trajectory_id-Key.
    _base_chain = list(_chain) or ([str(delegator_id)] if delegator_id else [])
    _persisted_chain = tuple(dict.fromkeys(_base_chain + [ziel]))
    _put_chain(_tid, _persisted_chain)
    _SESSION_TRAJECTORY[tgt_sess] = _tid
    # H-11-1/F030: Child-Cancel-Token an den Parent-Scope binden. Der Abbruch
    # des Parents erreicht damit den echten Child-Worker (frueher wurde mit
    # `_get_cancel_token("task:id")` ein neuer Root-Token erzeugt).
    _child_task_id = f"t-{secrets.token_hex(3)}"
    _cancel_scope = f"task:{_child_task_id}"
    try:
        from backend.cancellation import get_task_child_token
        _child_cancel_token = get_task_child_token(str(_root_ticket), _child_task_id)
    except Exception as _cancel_exc:
        logger.error("[Delegation] Child-Cancel-Token nicht verfügbar — fail-closed: %s", _cancel_exc)
        return _block_receipt(
            _tid, ziel, list(_persisted_chain), "CANCEL_SCOPE_UNAVAILABLE", str(_cancel_exc)
        )

    # F030: EIN kanonisches Schema, EINmal validiert, serverseitig aufgelöst
    # und HMAC-signiert. acceptance_criteria/reply_to/chain/memory_scope/
    # soul_mode/tenant/budget/cancel_scope gehen nicht an der Kante verloren.
    _handoff_payload = {
        **{k: v for k, v in payload.items() if k != "extensions"},
        "ziel_agent": ziel,
        "auftrag": auftrag,
        "task_id": _child_task_id,
        "acceptance_criteria": acceptance_criteria,
        "reply_to": reply_to,
        "delegation_chain": list(_persisted_chain),
        "memory_scope": memory_scope,
        "soul_mode": str(isolated_scope.get("soul_mode") or "compact"),
        "extensions": dict(payload.get("extensions") or {}),
    }
    try:
        _handoff_payload = canonicalize_delegation_payload(
            _handoff_payload,
            trajectory_id=_tid,
            task_id=_child_task_id,
            session_id=origin_session_id,
        )
        _handoff_json = json.dumps(_handoff_payload, ensure_ascii=False, default=str)
    except Exception as _schema_exc:
        # Fail-closed: ohne gültige, signierte Übergabe kein Dispatch.
        logger.error("[Delegation] Kanonische Übergabe fehlgeschlagen: %s", _schema_exc)
        return _block_receipt(
            _tid, ziel, list(_persisted_chain), "HANDOFF_SCHEMA_INVALID", str(_schema_exc)
        )
    msg_text = (
        f"STRUKTURIERTE ÜBERGABE (DelegationPayload v1, signiert) — JSON, kein Freitext:\n"
        f"{_handoff_json}"
    )
    with _get_state_db() as conn:
        _ensure_session_exists(conn, tgt_sess, ziel, t_model, auftrag[:50])
    # H-15-1/F023: der Isolations-Header ist eine SYSTEM-Vorgabe, keine
    # praependierte User-Nachricht — sonst kann der Subagent sie als Inhalt
    # der Aufgabe interpretieren und die Negativ-Grenze verwaessern.
    _save_message_to_db(tgt_sess, "system", isolation_header)
    _effective_soul_mode = resolve_effective_soul_mode(
        ziel, isolated_scope.get("soul_mode") or ""
    )
    _soul_tier_text = active_soul_tier_text(ziel, _effective_soul_mode)
    if _soul_tier_text:
        _save_message_to_db(
            tgt_sess, "system",
            f"[AKTIVER SOUL-TIER: {_effective_soul_mode.upper()}]\n"
            f"{_soul_tier_text}",
        )
    _save_message_to_db(tgt_sess, "user", msg_text)

    task_id = None
    delegation_error = None
    try:
        from backend.operations_api import _get_kanban_connection
        # F-039: die ID erst NACH erfolgreichem commit uebernehmen. Vorher war
        # sie bereits gesetzt, sodass ein fehlgeschlagener INSERT trotzdem eine
        # Erfolgs-Quittung und einen Watcher auf einen nie angelegten Task erzeugte.
        # F030: die vorab erzeugte Child-ID ist dieselbe, die auch in die
        # signierte Übergabe und den Cancel-Scope einging.
        new_task_id = _child_task_id
        now_iso = datetime.datetime.now().isoformat()
        prio_num = 2 if prioritaet in ("hoch", "high", "sofort", "critical", "urgent") else (1 if prioritaet in ("mittel", "normal", "medium") else 0)
        kconn = _get_kanban_connection()
        try:
            parent_pid = str(payload.get("parent_project_id") or "").strip()
            # H-5: Systeminterne Delegations-Subtasks sind keine externen
            # Seiteneffekte. Ohne Marker blockierte operations_api.py jeden
            # Subtask mit `awaiting_approval`, der Watchdog meldete nach 20 min
            # einen Timeout, obwohl nur eine Freigabe fehlte. Eigener,
            # konfigurierbarer Scope `delegation` mit Audit-Event.
            try:
                from backend.autonomy_settings import get_module_config
                _del_cfg = get_module_config("delegation") or {}
                _del_autonomy = str(_del_cfg.get("autonomy", "manual")).lower()
            except Exception as _aut_exc:
                # D07: fail-closed — ohne verifizierte Config KEIN HITL-Bypass.
                logger.error(
                    "[Delegation] Autonomie-Config nicht lesbar — fail-closed manual: %s", _aut_exc
                )
                try:
                    from backend.audit_log import chained_audit_log
                    chained_audit_log.record_event(
                        category="delegation", action="autonomy_config_unavailable",
                        agent_id="system", payload={"error": str(_aut_exc)[:300]},
                    )
                except Exception:
                    logger.error("[Delegation] Audit AUTONOMY_CONFIG_UNAVAILABLE fehlgeschlagen")
                _del_autonomy = "manual"
            _block_kind = "approval_granted" if _del_autonomy == "autonomous" else None
            try:
                _task_cols = {r[1] for r in kconn.execute("PRAGMA table_info(tasks)").fetchall()}
                if _task_cols and "block_kind" not in _task_cols:
                    kconn.execute("ALTER TABLE tasks ADD COLUMN block_kind TEXT")
            except Exception:
                pass
            kconn.execute(
                "INSERT INTO tasks (id, title, body, assignee, status, priority, created_by, created_at, started_at, model_override, project_id, block_kind) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (new_task_id, auftrag[:80] + ("..." if len(auftrag) > 80 else ""),
                 # Audit v3 2.1.3: isolation_header (M75 Tools/Skills) in tasks.body persistieren —
                 # er ging vorher nur in state.db.messages verloren und fehlte bei der Ausfuehrung.
                 f"Delegation von @{delegator_id} an @{ziel}:\n{isolation_header}\n{auftrag}", ziel, "in_progress", prio_num, delegator_id, now_iso, now_iso, t_model, parent_pid, _block_kind)
            )
            kconn.execute(
                "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?,?,?,?)",
                (new_task_id, "created", json.dumps({
                    "title": auftrag[:80],
                    "assignee": ziel,
                    "via": "delegation_engine_v2",
                    "delegator": delegator_id,
                    "tgt_session_id": tgt_sess,
                    "origin_session_id": origin_session_id,
                    # I: RAM-Kette persistieren, damit resume_pending_delegation_watchers()
                    # Zyklus-/Tiefenschranke nach einem Neustart wiederherstellen kann.
                    "delegation_chain": list(_persisted_chain),
                    "trajectory_id": _tid,
                    "root_ticket_id": _root_ticket,
                    "hops_used": int(_hop.get("hops_used") or 0),
                    "reasoning_level": reasoning_lvl,
                    "isolated": True,
                    "allowed_tools": isolated_scope["allowed_tools"],
                    "allowed_skills": isolated_scope["allowed_skills"],
                    "memory_scope": memory_scope,
                    "memory_acl": memory_acl,
                    "memory_ttl_seconds": memory_ttl_seconds,
                    "acceptance_criteria": acceptance_criteria,
                    "reply_to": reply_to,
                    # H-11-1/F030: Kind-Task trägt den kanonischen Kontext und
                    # den verifizierten Child-Cancel-Scope (SSOT: task:<id>).
                    "tenant_id": _handoff_payload.get("tenant_id", ""),
                    "project_id": _handoff_payload.get("project_id", ""),
                    "cancel_scope": _cancel_scope,
                    "taint_status": _handoff_payload.get("taint_status", "unknown"),
                    "budget_remaining_tokens": _handoff_payload.get("budget_remaining_tokens"),
                    "soul_mode": _handoff_payload.get("soul_mode", "compact"),
                    "payload_signature": _handoff_payload.get("payload_signature", ""),
                }), now_iso)
            )
            kconn.commit()
            task_id = new_task_id
        finally:
            kconn.close()
        try:
            from backend.operations_api import _execute_kanban_task_async
            worker_task = _spawn_background(
                _execute_kanban_task_async(task_id), name=f"kanban_{task_id}"
            )
            if worker_task is not None and hasattr(worker_task, "cancel"):
                _DELEGATED_WORKER_TASKS[task_id] = worker_task
                try:
                    _child_cancel_token.register_task(worker_task)
                except Exception as _reg_exc:
                    logger.error(
                        "[Delegation] Worker %s am Cancel-Scope %s nicht registriert: %s",
                        task_id, _cancel_scope, _reg_exc,
                    )
            # D16/MED: echte Kausalkante Parent -> Child im OTel-Baum. Ohne
            # diesen Produzenten existierten nur LLM-/Hop-Spans; Delegationen
            # waren in Trace-Baum und Replay-Fixture unsichtbar. Der aktive
            # Span des Dispatchers ist der Elternspan (kein Self-Parenting),
            # der Child-Task bekommt eine eigene Span-ID.
            try:
                from backend.trace_context import current_span_id, current_trace_id

                _parent_trace = str(current_trace_id() or "")
                _parent_span = str(current_span_id() or "")
                if _parent_trace and _parent_span and _parent_span != "0" * 16:
                    from backend.otel_tracer import tracer

                    tracer.record_span(
                        trace_id=_parent_trace,
                        name=f"delegation.{ziel}",
                        span_type="delegation",
                        parent_span_id=_parent_span,
                        agent_id=str(ziel),
                        attributes={
                            "delegation.parent_agent": str(delegator_id),
                            "delegation.child_task_id": str(task_id or ""),
                            "delegation.session_id": str(tgt_sess),
                            "delegation.trajectory_id": str(_tid),
                            "delegation.depth": len(_persisted_chain),
                        },
                        status="OK" if worker_task is not None else "ERROR",
                    )
            except Exception as _span_exc:
                try:
                    from backend.trace_context import note_local_trace_error

                    note_local_trace_error("delegation-span", _span_exc)
                except Exception:
                    logger.warning("[Delegation] Delegations-Span nicht geschrieben: %s", _span_exc)
        except Exception as exe_err:
            # F-039: Worker-Spawn-Fehler ist ein harter Fehler, kein Hinweis.
            delegation_error = f"Worker-Spawn fehlgeschlagen: {exe_err}"
            logger.error(f"[Delegation] {delegation_error}")
            _mark_delegation_blocked(task_id, delegation_error)
            _enqueue_delegation_failure(task_id, ziel, "blocked", delegation_error)
    except Exception as e:
        delegation_error = f"Kanban-Insert fehlgeschlagen: {e}"
        logger.error(f"[Delegation] {delegation_error}")
        if task_id:
            _enqueue_delegation_failure(task_id, ziel, "blocked", delegation_error)
        task_id = None

    # --- FAN-IN BRUECKE (nativ auf kanban.db + task_links) ---
    parent_pid = str(payload.get("parent_project_id") or payload.get("projekt") or "").strip()
    if parent_pid:
        try:
            parent_title_var = str(payload.get("projekt_titel") or payload.get("titel") or "").strip()
            mc_link_subtask_sqlite(
                parent_pid,
                task_id,  # type: ignore[arg-type]
                parent_defaults={
                    "id": parent_pid,
                    "title": parent_title_var or f"Delegationsprojekt {parent_pid}",
                    "agent_id": delegator_id,
                    "agent_name": d_name,
                    "status": "active",
                    "phase": "in_progress",
                    "created_via": "delegation_bridge",
                    "capture_input": auftrag[:400],
                    "target_action": "none",
                },
                child_updates={
                    "agent_name": t_name,
                    "phase": "in_progress",
                    "created_via": "delegation_bridge",
                    "capture_input": auftrag[:400],
                    "target_action": "none",
                } if task_id else None,
            )
            logger.info(f"[Delegation] Fan-in Link '{parent_pid}' -> '{task_id}' in kanban.db gespeichert")
        except Exception as fan_err:
            logger.warning(f"[Delegation] Fan-in-Anbindung fehlgeschlagen: {fan_err}")

    if task_id and not delegation_error:
        _spawn_background(
            _watch_delegated_task(
                task_id, tgt_sess, ziel, origin_session_id, delegator_id, parent_pid,
                acceptance_criteria=acceptance_criteria, reply_to=reply_to,
            ),
            name=f"bg_watch_{task_id}",
        )
    resolve_str = f" [aufgelöst von '{ziel_raw}']" if ziel_raw and ziel_raw != ziel else ""
    if delegation_error:
        # F-039: ehrlicher Fehlerstatus statt gruener Quittung.
        return (f"❌ DELEGATION BLOCKIERT — Ziel: {ziel} ({t_name}{resolve_str}) | "
                f"Kanban-Task: {task_id or 'n/a'} | Grund: {delegation_error} | "
                f"Der Fehler liegt in der DLQ (`delegation_result`). "
                f"Eskalation: @{resolve_supervisor(ziel)}")
    return (f"✅ DELEGATION QUITTUNG — Ziel: {ziel} ({t_name}{resolve_str}) | Kanban-Task: {task_id or 'n/a'} | "
            f"Sub-Session: {tgt_sess} | Modell (Empfehlung): {t_model} | "
            f"Ausführung: Hermes-Agent-Worker | Ergebnis erscheint im Kanban und wird automatisch in die Sub-Session gespiegelt."
            f" | Eskalation: @{resolve_supervisor(ziel)}")
