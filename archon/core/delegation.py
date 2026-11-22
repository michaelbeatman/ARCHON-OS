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
import html as _html
import json
import os
import re
import secrets
import shutil
import sqlite3
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from archon.core.constants import DELEGATION_PROTOCOL_PROMPT
from archon.core.mission_control import (
    mc_get_parent_context_sqlite,
    mc_link_subtask_sqlite,
    mc_update_task_sqlite,
    update_mission_control_data,
)
from archon.core.orchestration import _fan_in_maybe_start_synthesis, _run_synthesis_cascade
from archon.core.profiles import api_get_hermes_profiles
from archon.core.paths import OPT_DATA_DIR
from archon.core.runtime import (
    WORKSPACE_DIR,
    broadcast_event,
    subscribe_events,
    unsubscribe_events,
    logger,
)
from archon.core.state_db import _get_state_db
from backend.platform_paths import OBSIDIAN_VAULT, PROJEKTE_DIR
# Batch D/4: Supervisor-Rollover aus der Org-Hierarchie (links bleiben SSOT).
from backend.supervisor_rollover import resolve_supervisor, on_supervisor_failure

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


_ORG_HIERARCHY_CACHE = {"mtime": 0.0, "nodes": {}, "loaded": False}


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
            _ORG_HIERARCHY_CACHE.update({"mtime": mtime, "nodes": nodes, "loaded": True})
        return _ORG_HIERARCHY_CACHE["nodes"]
    except Exception as e:
        logger.warning(f"[Delegation] org_hierarchy.json nicht lesbar: {e}")
        return {}


def _check_delegation_permission(delegator_id: str, target_id: str):
    """Hierarchie-Regeln: Tier 1 (APEX) -> alle; Tier 2 (LEAD) -> eigenes Team; Tier 3 -> keine Delegation."""
    org = _load_org_hierarchy_map()
    d = org.get(delegator_id)
    t = org.get(target_id)

    # K-1: Der Root-Orchestrator war im UI-Org-Chart als Tier 3 gefuehrt und
    # durfte deshalb im Hauptpfad NICHT delegieren. Apex-Rechte gehoeren nicht
    # in ein UI-Layout — eigene, explizite Liste (auditierbar, unabhaengig vom
    # Chart). Tier-1-Knoten duerfen weiterhin delegieren.
    apex_ids = frozenset({
        "default", "executive_decision_architect", "system_architect_orchestrator",
    })
    if delegator_id in apex_ids:
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


# Batch D/1: Task -> Handoff-ID, damit verkettete Delegationen reply_to setzen koennen.
_HANDOFF_IDS_BY_TASK: Dict[str, str] = {}


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


DELEGATION_ALIAS_MAP = {
    # Apex / Leitung / Robert
    "robert": "executive_decision_architect",
    "ceo": "executive_decision_architect",
    "apex": "executive_decision_architect",
    "dr. robert neumann": "system_architect_orchestrator",
    "robert neumann": "system_architect_orchestrator",
    "cloud_architect": "system_architect_orchestrator",
    "system_architect": "system_architect_orchestrator",
    "system-architect": "system_architect_orchestrator",
    
    # Lisa / Aggregation / Synthese
    "lisa": "aggregation_lisa",
    "synthese": "aggregation_lisa",
    "aggregation": "aggregation_lisa",
    "aggregator": "aggregation_lisa",

    # Product Management / Requirements
    "cs-product-manager": "product_requirements_engineer",
    "product-manager": "product_requirements_engineer",
    "product_manager": "product_requirements_engineer",
    "produktmanager": "product_requirements_engineer",
    "product_owner": "product_requirements_engineer",
    "product-owner": "product_requirements_engineer",
    "requirements_engineer": "product_requirements_engineer",
    "tobias": "product_requirements_engineer",
    "tobias merz": "product_requirements_engineer",

    # Frontend / UI / UX / Design
    "cs-frontend-engineer": "brand_uiux_director",
    "frontend-engineer": "brand_uiux_director",
    "frontend_engineer": "brand_uiux_director",
    "frontend": "brand_uiux_director",
    "designer": "brand_uiux_director",
    "ui_designer": "brand_uiux_director",
    "ux_designer": "brand_uiux_director",
    "clara": "brand_uiux_director",
    "clara moreau": "brand_uiux_director",

    # Tech / Fullstack / Coding / Senior Engineer
    "cs-senior-engineer": "senior_fullstack_engineer",
    "senior-engineer": "senior_fullstack_engineer",
    "senior_engineer": "senior_fullstack_engineer",
    "fullstack_engineer": "senior_fullstack_engineer",
    "fullstack-engineer": "senior_fullstack_engineer",
    "fullstack": "senior_fullstack_engineer",
    "coder": "senior_fullstack_engineer",
    "senior_coder": "senior_fullstack_engineer",
    "niklas": "senior_fullstack_engineer",
    "niklas dorn": "senior_fullstack_engineer",

    # Scrum / Agile
    "agile-product-owner": "agile_scrum_master",
    "agile_product_owner": "agile_scrum_master",
    "scrum_master": "agile_scrum_master",
    "scrum-master": "agile_scrum_master",
    "scrum": "agile_scrum_master",
    "sarah": "agile_scrum_master",
    "sarah lindemann": "agile_scrum_master",

    # Compliance / Recht / DSGVO
    "compliance": "compliance_gdpr_auditor",
    "dsgvo": "compliance_gdpr_auditor",
    "compliance_auditor": "compliance_gdpr_auditor",
    "sabine": "compliance_gdpr_auditor",
    "sabine becker": "compliance_gdpr_auditor",
    "jurist": "commercial_jurist_contracts",
    "vertragspruefer": "commercial_jurist_contracts",
    "wirtschaftsjurist": "commercial_jurist_contracts",
    "dr. maximilian von walden": "commercial_jurist_contracts",
    "maximilian": "commercial_jurist_contracts",

    # Marketing / Sales
    "copywriter": "direct_response_copywriter",
    "david stein": "direct_response_copywriter",
    "david": "direct_response_copywriter",
    "b2b": "b2b_outreach_specialist",
    "outreach": "b2b_outreach_specialist",
    "patrick": "b2b_outreach_specialist",
    "patrick jensen": "b2b_outreach_specialist"
}


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

    # 3. Fester Alias-Lookup
    if raw in DELEGATION_ALIAS_MAP:
        mapped = DELEGATION_ALIAS_MAP[raw]
        return mapped, f"Alias '{ziel_raw}' -> '{mapped}'"
    if raw_norm in DELEGATION_ALIAS_MAP:
        mapped = DELEGATION_ALIAS_MAP[raw_norm]
        return mapped, f"Alias '{ziel_raw}' -> '{mapped}'"

    # 4. Personenname / Rufname Match (z.B. 'Robert', 'Tobias', 'Sarah')
    for p in profiles:
        pname = (p.get("person_name") or "").strip().lower()
        if pname:
            first_name = pname.split()[0]
            if raw == pname or raw == first_name:
                pid = p["id"]
                return pid, f"Personenname '{pname}' -> '{pid}'"

    # 5. Rollen- / Titelsuche (Substring)
    for p in profiles:
        role = (p.get("role") or p.get("name") or "").lower()
        if raw in role or raw_norm in role:
            pid = p["id"]
            return pid, f"Rollen-Treffer '{role}' -> '{pid}'"

    return None, ""


def _build_kader_roster_summary():
    """Erstellt eine lesbare, gegliederte Liste aller real existierenden Agenten für das Delegations-Prompt."""
    try:
        profiles = api_get_hermes_profiles()
        lines = []
        for p in profiles:
            pid = p.get("id")
            if not pid or pid in ("founder", "micha", "telegram_bot"):
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


def _parse_delegation_blocks(text: str):
    """Findet alle ```delegation```-JSON-Blöcke sowie Fallback-JSON-Zeilen."""
    valid, invalid = [], []
    seen_hashes = set()
    
    # 1. Standard: ```delegation ... ``` Blöcke
    for m in re.finditer(r"```(?:delegation|json)?\s*\n(.*?)```", text, re.DOTALL):
        raw = m.group(1).strip()
        if '"ziel_agent"' in raw and '"auftrag"' in raw:
            try:
                payload = json.loads(raw)
                if isinstance(payload, dict) and payload.get("ziel_agent") and payload.get("auftrag"):
                    h = f"{payload.get('ziel_agent')}:{payload.get('auftrag')[:40]}"
                    if h not in seen_hashes:
                        valid.append(payload)
                        seen_hashes.add(h)
            except Exception as e:
                invalid.append({"raw": raw[:200], "error": str(e)})

    # 2. Fallback: Ungefenced JSON-Objekte mit "ziel_agent" und "auftrag"
    for m in re.finditer(r'\{[^{}]*"ziel_agent"\s*:\s*"[^"]+"[^{}]*"auftrag"\s*:\s*"[^"]+"[^{}]*\}', text, re.DOTALL):
        raw = m.group(0).strip()
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict) and payload.get("ziel_agent") and payload.get("auftrag"):
                h = f"{payload.get('ziel_agent')}:{payload.get('auftrag')[:40]}"
                if h not in seen_hashes:
                    valid.append(payload)
                    seen_hashes.add(h)
        except Exception as exc:
            logger.debug(f"[Delegation] Ungueltiger Delegations-JSON-Block uebersprungen: {exc}")
            
    return valid, invalid


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

        end_dir = os.path.join(proj_folder, "03_Endprodukte") if proj_folder else None
        if end_dir:
            os.makedirs(end_dir, exist_ok=True)
            clean_proj_name = parent_project_id.replace("projekt-", "").title()
            html_filename = f"{clean_proj_name}_Abschlussbericht.html"
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
    <div class="badge">● Projekt Vollständig Abgeschlossen</div>
    <h1>Projekt: {safe_proj_name} — Abschlussbericht</h1>
    <div style="font-size: 13px; color: #a1a1aa; margin-bottom: 20px;">Autonom koordiniert durch <strong>Robert (Executive Decision Architect)</strong> | {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}</div>
    
    <div class="summary">
      <strong>Management Summary:</strong><br>
      Alle {len(rows)} Arbeitspakete des Projekts wurden von den spezialisierten Fachagenten erfolgreich ausgearbeitet, verifiziert und zusammengeführt. Das Vorhaben steht für die weitere Umsetzung bereit.
    </div>

    <h2>Abgeschlossene Teilaufgaben & Ergebnisse</h2>
    {task_items_html}

    <footer>
      <div>Archon OS — Autonome Orchestration</div>
      <div>Freigegeben durch <strong>@executive_decision_architect</strong></div>
    </footer>
  </div>
</body>
</html>"""
            with open(html_full_path, "w", encoding="utf-8") as f:
                f.write(html_doc)

        if session_id:
            summary_msg = (
                f"🎉 **Projekt '{parent_project_id}' ist vollständig abgeschlossen!**\n\n"
                f"Alle {len(rows)} Teilaufgaben wurden von den Fachagenten erfolgreich abgearbeitet und von mir zusammengeführt.\n\n"
                f"📄 **Finaler Abschlussbericht:**\n"
                f"- Gespeichert in: `01_PROJEKTE/{os.path.basename(proj_folder) if proj_folder else parent_project_id}/03_Endprodukte/`\n"
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

# Terminale Kanban-Status (auf die ein Delegations-Watcher wartet).
_TERMINAL_TASK_STATUSES = ("done", "blocked", "review", "failed")


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
                "result": str(result or "")[:2000],
            },
            priority=2,
            idempotency_key=f"delegation-result:{task_id}:{status}",
        )
    except Exception as exc:
        logger.debug(f"[Delegation] Shared-Queue-Enqueue fehlgeschlagen: {exc}")
        return {"queued": False, "error": str(exc)}


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
            timeout_text = (
                f"{deadline_seconds / 60:g} Minuten" if deadline_seconds >= 60
                else f"{deadline_seconds:g} Sekunden"
            )
            _save_message_to_db(s_id, "assistant",
                f"⏱️ DELEGATION-TIMEOUT — Der Task läuft länger als {timeout_text} ohne Endstatus. "
                "Aktueller Stand bitte im Kanban prüfen (Task-ID siehe Delegations-Quittung).")
            return
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
                supervisor_hint = (
                    f"\n\n**Supervisor-Rollover:** @{_new_supervisor} "
                    f"(Kette: {', '.join(_rollover.get('chain') or []) or _new_supervisor})"
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
                        result = ev[0][:500]
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
                with open(result_path, "w", encoding="utf-8") as f:
                    f.write(f"# {title}\n\n"
                            f"**Task:** `{task_id}` | **Ziel-Agent:** `@{prof_id}` | **Status:** {status.upper()}\n\n"
                            f"{result or '(Ergebnis siehe Kanban-Task-Events und Anhänge in 02_Medien/.)'}\n")
                proj_title = fan_parent_title if (fan_parent and fan_parent_title) else title
                p_herkunft = (f"Teilauftrag von Projekt `{fan_parent}`" if fan_parent
                              else f"Delegation über Archon OS (Task `{task_id}`)")
                p_parent_line = f'parent_project: "{fan_parent}"\n' if fan_parent else ""
                try:
                    with open(os.path.join(proj_folder, "PROJEKT.md"), "x", encoding="utf-8") as f:
                        f.write("---\nproject_folder: \"" + os.path.basename(proj_folder) + "\"\ncreated_at: \""
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

        if origin_sess_id and origin_sess_id != s_id:
            try:
                status_badge = "✅ ERLEDIGT" if status in ("done", "review") else "⛔ BLOCKIERT"
                # M-2/K-5: Formales A2A-Envelope statt "Message from 🤖" als
                # Freitext. Der Handoff-Desk existierte, wurde aber von keinem
                # Dispatcher-Pfad genutzt.
                handoff_id = ""
                try:
                    from backend.handoff_desk import handoff_desk
                    # Batch D/1: vollständiges, typisiertes A2A-Envelope.
                    _status_key = str(status).strip().lower()
                    _confidence = 1.0 if _status_key == "done" else (0.6 if _status_key == "review" else 0.0)
                    _attachments = [
                        p for p in (
                            str(obsidian_rel or ""),
                            str(proj_folder or ""),
                        ) if p
                    ]
                    envelope = handoff_desk.create_handoff(
                        task_id=str(task_id),
                        from_agent=str(prof_id or "unknown"),
                        to_agent=str(orig_delegator or "default"),
                        deliverables={
                            "result": str(result or "")[:4000],
                            "status": str(status),
                            "artifact_path": str(obsidian_rel or ""),
                        },
                        acceptance_criteria=_resolve_handoff_criteria(
                            acceptance_criteria, prof_id, task_id
                        ),
                        message_id=f"msg-{secrets.token_hex(6)}",
                        correlation_id=f"task:{task_id}",
                        reply_to=str(reply_to or _HANDOFF_IDS_BY_TASK.get(str(parent_pid or ""), "")),
                        confidence=_confidence,
                        attachments=_attachments,
                    )
                    handoff_id = str(envelope.get("handoff_id") or "")
                    _HANDOFF_IDS_BY_TASK[str(task_id)] = handoff_id
                except Exception as he:
                    logger.debug(f"[Delegation] Handoff-Envelope nicht angelegt: {he}")

                delegator_feedback = (
                    f"{status_badge}: Der Sub-Agent `@{prof_id}` hat Task `{task_id}` ({final_title}) abgeschlossen.\n\n"
                    f"**A2A-Handoff:** `{handoff_id or 'nicht protokolliert'}`\n"
                    f"**Ergebnis:**\n{result or '(Ergebnis liegt im Projektordner/Kanban)'}\n"
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
                if not parent_pid and orig_delegator in ("executive_decision_architect", "hermes-orchestrator", "founder", "micha", "default"):
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
                notify_task_status(task_id, status, final_title, result, obsidian_rel,
                                   dossier_dir=_doss_dir)
        except Exception as tg_err:
            logger.warning(f"[Telegram] Delegations-Ping für Task {task_id} fehlgeschlagen: {tg_err}")

        if status in ("done", "review", "blocked", "failed"):
            try:
                fan_parent, _ = await asyncio.to_thread(mc_get_parent_context_sqlite, task_id)
                mc_status = "completed" if status in ("done", "review") else ("blocked" if status == "blocked" else "failed")
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
    if not ziel:
        return f"❌ DELEGATION ABGELEHNT — Ziel-Agent '{ziel_raw}' existiert nicht im Agenten-Kader."

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

    # M75: Strikte Rollen- & Tool-Isolation (keine implizite Vererbung von Parent-Tools)
    from backend.delegation_isolation import (
        build_isolated_system_prompt_header,
        resolve_isolated_execution_scope,
    )
    isolated_scope = resolve_isolated_execution_scope(ziel, requested_model=t_model, profiles=profiles)
    isolation_header = build_isolated_system_prompt_header(isolated_scope)

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
    msg_text = f"{isolation_header}\nMessage from 🤖 {d_name} (@{delegator_id}): {auftrag}"
    with _get_state_db() as conn:
        _ensure_session_exists(conn, tgt_sess, ziel, t_model, auftrag[:50])
    _save_message_to_db(tgt_sess, "user", msg_text)

    task_id = None
    try:
        from backend.operations_api import _get_kanban_connection
        task_id = f"t-{secrets.token_hex(3)}"
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
                _del_autonomy = str(_del_cfg.get("autonomy", "autonomous")).lower()
            except Exception:
                _del_autonomy = "autonomous"
            _block_kind = "approval_granted" if _del_autonomy == "autonomous" else None
            try:
                _task_cols = {r[1] for r in kconn.execute("PRAGMA table_info(tasks)").fetchall()}
                if _task_cols and "block_kind" not in _task_cols:
                    kconn.execute("ALTER TABLE tasks ADD COLUMN block_kind TEXT")
            except Exception:
                pass
            kconn.execute(
                "INSERT INTO tasks (id, title, body, assignee, status, priority, created_by, created_at, started_at, model_override, project_id, block_kind) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (task_id, auftrag[:80] + ("..." if len(auftrag) > 80 else ""),
                 # Audit v3 2.1.3: isolation_header (M75 Tools/Skills) in tasks.body persistieren —
                 # er ging vorher nur in state.db.messages verloren und fehlte bei der Ausfuehrung.
                 f"Delegation von @{delegator_id} an @{ziel}:\n{isolation_header}\n{auftrag}", ziel, "in_progress", prio_num, delegator_id, now_iso, now_iso, t_model, parent_pid, _block_kind)
            )
            kconn.execute(
                "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?,?,?,?)",
                (task_id, "created", json.dumps({
                    "title": auftrag[:80],
                    "assignee": ziel,
                    "via": "delegation_engine_v2",
                    "delegator": delegator_id,
                    "tgt_session_id": tgt_sess,
                    "origin_session_id": origin_session_id,
                    "reasoning_level": reasoning_lvl,
                    "isolated": True,
                    "allowed_tools": isolated_scope["allowed_tools"],
                    "allowed_skills": isolated_scope["allowed_skills"],
                    "memory_scope": memory_scope,
                    "memory_acl": memory_acl,
                    "memory_ttl_seconds": memory_ttl_seconds,
                    "acceptance_criteria": acceptance_criteria,
                    "reply_to": reply_to,
                }), now_iso)
            )
            kconn.commit()
        finally:
            kconn.close()
        try:
            from backend.operations_api import _execute_kanban_task_async
            _spawn_background(_execute_kanban_task_async(task_id), name=f"kanban_{task_id}")
        except Exception as exe_err:
            logger.warning(f"[Delegation] Sofortige Ausfuehrung fehlgeschlagen: {exe_err}")
    except Exception as e:
        logger.warning(f"[Delegation] Kanban-Insert fehlgeschlagen: {e}")

    # --- FAN-IN BRUECKE (nativ auf kanban.db + task_links) ---
    parent_pid = str(payload.get("parent_project_id") or payload.get("projekt") or "").strip()
    if parent_pid:
        try:
            parent_title_var = str(payload.get("projekt_titel") or payload.get("titel") or "").strip()
            mc_link_subtask_sqlite(
                parent_pid,
                task_id,
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

    if task_id:
        _spawn_background(
            _watch_delegated_task(
                task_id, tgt_sess, ziel, origin_session_id, delegator_id, parent_pid,
                acceptance_criteria=acceptance_criteria, reply_to=reply_to,
            ),
            name=f"bg_watch_{task_id}",
        )
    resolve_str = f" [aufgelöst von '{ziel_raw}']" if ziel_raw and ziel_raw != ziel else ""
    return (f"✅ DELEGATION QUITTUNG — Ziel: {ziel} ({t_name}{resolve_str}) | Kanban-Task: {task_id or 'n/a'} | "
            f"Sub-Session: {tgt_sess} | Modell (Empfehlung): {t_model} | "
            f"Ausführung: Hermes-Agent-Worker | Ergebnis erscheint im Kanban und wird automatisch in die Sub-Session gespiegelt."
            f" | Eskalation: @{resolve_supervisor(ziel)}")
