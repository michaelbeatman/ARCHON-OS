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
)
from archon.core.orchestration import _fan_in_maybe_start_synthesis
from archon.core.profiles import api_get_hermes_profiles
from archon.core.paths import OPT_DATA_DIR
from archon.core.runtime import WORKSPACE_DIR, broadcast_event, logger
from archon.core.state_db import _get_state_db
from backend.platform_paths import OBSIDIAN_VAULT, PROJEKTE_DIR

_DEPS: Dict[str, Any] = {}


def configure(**deps: Any) -> None:
    """Registriert Abhaengigkeiten aus main.py (einmalig beim Import)."""
    _DEPS.update(deps)


def _get_obsidian_vault_dir() -> str:
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "OBSIDIAN_VAULT_DIR"):
        return getattr(main_mod, "OBSIDIAN_VAULT_DIR")
    return OBSIDIAN_VAULT


def _spawn_background(coro, name: str = ""):
    fn = _DEPS.get("_spawn_background")
    if fn:
        return fn(coro, name=name)
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "_spawn_background"):
        return main_mod._spawn_background(coro, name=name)
    return asyncio.create_task(coro, name=name)


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
        except Exception:
            pass
            
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
                "SELECT COUNT(*) FROM tasks WHERE project_id = ? AND status NOT IN ('done', 'review')",
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
            
            task_items_html = ""
            for r_id, r_title, r_assignee, r_res, r_stat in rows:
                snippet = (r_res or "").strip()[:500].replace("\n", "<br>")
                task_items_html += f"""
                <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 16px; margin-bottom: 14px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <strong style="color: #38bdf8;">Task #{r_id}: {r_title}</strong>
                        <span style="font-size: 11px; padding: 2px 8px; border-radius: 4px; background: rgba(16,185,129,0.2); color: #34d399; font-weight: bold;">@{r_assignee}</span>
                    </div>
                    <div style="font-size: 13px; color: #cbd5e1; line-height: 1.5;">{snippet}...</div>
                </div>
                """

            html_doc = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <title>Abschlussbericht: {clean_proj_name}</title>
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
    <h1>Projekt: {clean_proj_name} — Abschlussbericht</h1>
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


def _execute_delegation(delegator_id, payload, provider, all_keys, origin_session_id=None):
    """Führt eine Delegation aus: Berechtigungsprüfung, Sub-Session, Kanban-Task,
    Hintergrund-Ausführung. Gibt eine Quittung als Text zurück (wird in die
    Delegator-Session geschrieben, damit der Agent sich erinnert)."""
    ziel_raw = str(payload.get("ziel_agent") or "").strip()
    auftrag = str(payload.get("auftrag") or "").strip()
    modell = str(payload.get("modell") or payload.get("model") or "").strip()
    prioritaet = str(payload.get("prioritaet") or "normal").strip().lower()
    reasoning_lvl = str(payload.get("reasoning_level") or payload.get("reasoning") or "medium").strip().lower()

    profiles = api_get_hermes_profiles()
    ziel, resolve_note = _resolve_target_agent_id(ziel_raw, profiles)
    if not ziel:
        return f"❌ DELEGATION ABGELEHNT — Ziel-Agent '{ziel_raw}' existiert nicht im Agenten-Kader."

    allowed, reason = _check_delegation_permission(delegator_id, ziel)
    if not allowed:
        return f"❌ DELEGATION ABGELEHNT — Ziel: {ziel} ({ziel_raw}) | Grund: {reason}"

    t_prof = next((p for p in profiles if p["id"] == ziel), None)
    if not t_prof:
        return f"❌ DELEGATION ABGELEHNT — Ziel-Agent '{ziel}' existiert nicht im Agenten-Kader."
    d_prof = next((p for p in profiles if p["id"] == delegator_id), None)
    t_name = (t_prof.get("person_name") or t_prof.get("name") or ziel)
    d_name = (d_prof.get("person_name") or d_prof.get("name") or delegator_id) if d_prof else delegator_id
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

    tgt_sess = f"mc_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{ziel}"
    msg_text = f"Message from 🤖 {d_name} (@{delegator_id}): {auftrag}"
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
        parent_pid = str(payload.get("parent_project_id") or "").strip()
        kconn.execute(
            "INSERT INTO tasks (id, title, body, assignee, status, priority, created_by, created_at, started_at, model_override, project_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (task_id, auftrag[:80] + ("..." if len(auftrag) > 80 else ""),
             f"Delegation von @{delegator_id} an @{ziel}:\n{auftrag}", ziel, "in_progress", prio_num, delegator_id, now_iso, now_iso, t_model, parent_pid)
        )
        try:
            from backend.operations_api import _execute_kanban_task_async
            _spawn_background(_execute_kanban_task_async(task_id), name=f"kanban_{task_id}")
        except Exception as exe_err:
            logger.warning(f"[Delegation] Sofortige Ausfuehrung fehlgeschlagen: {exe_err}")
        kconn.execute(
            "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?,?,?,?)",
            (task_id, "created", json.dumps({"title": auftrag[:80], "assignee": ziel, "via": "delegation_engine_v2", "delegator": delegator_id, "reasoning_level": reasoning_lvl}), now_iso)
        )
        kconn.commit()
        kconn.close()
    except Exception as e:
        logger.warning(f"[Delegation] Kanban-Insert fehlgeschlagen: {e}")

    async def _bg_watch_task(task_id, s_id, prof_id, origin_sess_id=None, orig_delegator=None, parent_pid=None):
        """Beobachtet den Kanban-Task, während der Hermes-Agent-Worker ihn abarbeitet,
        und spiegelt das Endergebnis in die Sub-Session (Rücklauf ohne Doppel-Ausführung).
        WICHTIG: Kein eigener Modell-Aufruf mehr — die Ausführung macht der hermes-Worker
        (claim -> spawn -> heartbeats -> done/blocked). Kein vorzeitiges 'blocked' mehr."""
        try:
            deadline = time.time() + 1200  # max 20 Minuten beobachten
            final = None
            while time.time() < deadline:
                try:
                    from backend.operations_api import _get_kanban_connection as _kgc
                    kc = _kgc()
                    row = kc.execute("SELECT status, result, title FROM tasks WHERE id = ?", (task_id,)).fetchone()
                    kc.close()
                    if row and row[0] in ("done", "blocked", "review"):
                        final = row
                        break
                except Exception:
                    pass
                await asyncio.sleep(10)
            if final is None:
                _save_message_to_db(s_id, "assistant",
                    "⏱️ DELEGATION-TIMEOUT — Der Task läuft länger als 20 Minuten ohne Endstatus. "
                    "Aktueller Stand bitte im Kanban prüfen (Task-ID siehe Delegations-Quittung).")
                return
            status, result = final[0], (final[1] or "").strip()
            final_title = (final[2] or "").strip()
            # Fallback: Zusammenfassung aus dem completed/blocked-Event ziehen, wenn das Result-Feld leer ist
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
                            result = json.loads(ev[0]).get("summary") or json.loads(ev[0]).get("reason") or ""
                        except Exception:
                            result = ev[0][:500]
                except Exception:
                    pass
            # Ergebnis-Dateien des Hermes-Workers einsammeln (Attachments)
            attach_note = ""
            try:
                attach_dir = os.path.join(OPT_DATA_DIR, "kanban", "attachments", task_id)
                if os.path.isdir(attach_dir):
                    files = [f for f in os.listdir(attach_dir) if os.path.isfile(os.path.join(attach_dir, f))]
                    if files:
                        attach_note = "\n\n**Angehängte Artefakte:**\n" + "\n".join(f"- {f}" for f in files)
            except Exception:
                pass
            # --- Ergebnis nach Obsidian exportieren (01_PROJEKTE) -> Showroom-Rücklauf ---
            obsidian_rel = None
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
                    # EIN Ordner pro Projekt - hat der Subtask ein parent, TEILT er sich den Eltern-Ordner
                    fan_parent = None
                    fan_parent_title = None
                    try:
                        fan_parent, fan_parent_title = await asyncio.to_thread(
                            mc_get_parent_context_sqlite, task_id
                        )
                    except Exception:
                        pass
                    try:
                        from backend.post_task_pipeline import project_folder_name
                        proj_name = project_folder_name({
                            "id": task_id, "title": final_title or "Delegation",
                            "parent_project_id": fan_parent or "",
                            "parent_project_title": fan_parent_title or "",
                        })
                    except Exception:
                        proj_name = f"{datetime.datetime.now().strftime('%Y%m%d')}-{task_id}-{slug}"
                    proj_folder = os.path.join(obsidian_rel, proj_name)
                    target_sub = "01_Zwischenberichte" if parent_pid else "03_Endprodukte"
                    dest_dir = os.path.join(proj_folder, target_sub)
                    os.makedirs(dest_dir, exist_ok=True)
                    for sub in ("01_Zwischenberichte", "02_Medien", "03_Endprodukte"):
                        os.makedirs(os.path.join(proj_folder, sub), exist_ok=True)
                    try:
                        att_src = os.path.join(OPT_DATA_DIR, "kanban", "attachments", task_id)
                        if os.path.isdir(att_src):
                            for f in os.listdir(att_src):
                                src_f = os.path.join(att_src, f)
                                if os.path.isfile(src_f):
                                    shutil.copy2(src_f, os.path.join(proj_folder, "02_Medien", f))
                    except Exception:
                        pass
                    result_fn = f"{task_id}-{slug}.md"
                    with open(os.path.join(dest_dir, result_fn), "w", encoding="utf-8") as f:
                        f.write(f"# {title}\n\n"
                                f"**Task:** `{task_id}` | **Ziel-Agent:** `@{prof_id}` | **Status:** {status.upper()}\n\n"
                                f"{result or '(Ergebnis siehe Kanban-Task-Events und Anhänge in 02_Medien/.)'}\n")
                    # PROJEKT.md nur beim ERSTEN Schreiber
                    proj_title = fan_parent_title if (fan_parent and fan_parent_title) else title
                    p_herkunft = (f"Teilauftrag von Projekt `{fan_parent}`" if fan_parent
                                  else f"Delegation über Archon OS (Task `{task_id}`)")
                    p_parent_line = f'parent_project: "{fan_parent}"' if fan_parent else ""
                    try:
                        with open(os.path.join(proj_folder, "PROJEKT.md"), "x", encoding="utf-8") as f:
                            f.write("---\nproject_folder: \"" + proj_name + "\"\ncreated_at: \""
                                    + str(datetime.datetime.now().timestamp()) + "\"\n"
                                    "title: \"" + proj_title + "\"\nstatus: \"" + str(status)
                                    + "\"\nsource_task: \"" + task_id + "\"\n"
                                    "source: \"delegation_engine_v2\"\n" + p_parent_line + "---\n\n"
                                    "# Projekt: " + str(proj_title) + "\n\n"
                                    "- **Herkunft:** " + p_herkunft + "\n"
                                    "- **Ziel-Agent:** `@" + str(prof_id) + "` | **Status:** " + str(status).upper() + "\n"
                                    "- **Hauptdokument:** [[" + task_id + "-" + slug + "]]\n\n"
                                    "### 📁 Projekt-Struktur:\n"
                                    "- `01_Zwischenberichte/`: Entwürfe und Arbeitsprotokolle\n"
                                    "- `02_Medien/`: Artefakte der Fachagenten\n"
                                    "- `03_Endprodukte/`: [[" + task_id + "-" + slug + "]]"
                                    + ("+ Lisa-Synthese + finale Beschlussvorlage" if fan_parent else "")
                                    + "\n\n---\n[[00_VAULT_KNOWLEDGE]] | [[Archiv-Hubs]]\n")
                    except FileExistsError:
                        pass
                    obsidian_rel = proj_name
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
                msg = ("⛔ DELEGATION BLOCKIERT — Der Sub-Agent konnte die Aufgabe nicht abschließen.\n\n"
                       f"**Grund/Eskalation:**\n{result or 'Siehe Task-Events im Kanban (Kommentare des Agenten).'}{attach_note}\n\n"
                       f"Task-ID: {task_id} | Ggf. Kontextdaten nachliefern oder Aufgabe umformulieren."
                       + (f"\n📁 Dokumentation: `01_PROJEKTE/{obsidian_rel}`" if obsidian_rel else ""))
            _save_message_to_db(s_id, "assistant", msg)

            # --- Feedback an Delegator-Session (Robert / Orchestrator) & Autonomer Trigger ---
            if origin_sess_id and origin_sess_id != s_id:
                try:
                    status_badge = "✅ ERLEDIGT" if status in ("done", "review") else "⛔ BLOCKIERT"
                    delegator_feedback = (
                        f"{status_badge}: Der Sub-Agent `@{prof_id}` hat Task `{task_id}` ({final_title}) abgeschlossen.\n\n"
                        f"**Ergebnis:**\n{result or '(Ergebnis liegt im Projektordner/Kanban)'}\n"
                        f"{attach_note}\n\n"
                        f"*(Status im Kanban: `{status}`)*"
                    )
                    _save_message_to_db(origin_sess_id, "user", delegator_feedback)
                    broadcast_event("chat_message_received", {
                        "session_id": origin_sess_id,
                        "agent_id": orig_delegator,
                        "task_id": task_id,
                        "status": status
                    })
                    # Autonomen Folge-Turn auslösen, falls Orchestrator aktiv
                    if orig_delegator in ("executive_decision_architect", "hermes-orchestrator", "founder", "micha", "default"):
                        _spawn_background(_trigger_autonomous_orchestrator_followup(
                            orig_delegator, origin_sess_id, task_id, status, result, final_title, parent_pid
                        ), name=f"followup_{task_id}")
                except Exception as feed_err:
                    logger.warning(f"[Delegation] Feedback an Delegator-Session fehlgeschlagen: {feed_err}")

            # --- Telegram-Push (HITL-Kanal) ---
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
                                result, _doss_dir, f"{task_id}_{status}",
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

            # --- FAN-IN RUECKLAUF ---
            if status == "done":
                try:
                    fan_parent, _ = await asyncio.to_thread(mc_get_parent_context_sqlite, task_id)
                    await asyncio.to_thread(
                        mc_update_task_sqlite,
                        task_id,
                        {
                            "status": "completed",
                            "result_summary": (result or "")[:800],
                            "completed_at": time.time(),
                        },
                    )
                    if fan_parent:
                        _spawn_background(_fan_in_maybe_start_synthesis(fan_parent), name=f"fan_in_{fan_parent}")
                except Exception as fan_err:
                    logger.warning(f"[Delegation] Fan-in-Ruecklauf fehlgeschlagen: {fan_err}")
        except Exception as e:
            logger.error(f"[Delegation] Task-Watcher error: {e}")

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

    _spawn_background(_bg_watch_task(task_id, tgt_sess, ziel, origin_session_id, delegator_id, parent_pid), name=f"bg_watch_{task_id}")
    resolve_str = f" [aufgelöst von '{ziel_raw}']" if ziel_raw and ziel_raw != ziel else ""
    return (f"✅ DELEGATION QUITTUNG — Ziel: {ziel} ({t_name}{resolve_str}) | Kanban-Task: {task_id or 'n/a'} | "
            f"Sub-Session: {tgt_sess} | Modell (Empfehlung): {t_model} | "
            f"Ausführung: Hermes-Agent-Worker | Ergebnis erscheint im Kanban und wird automatisch in die Sub-Session gespiegelt.")
