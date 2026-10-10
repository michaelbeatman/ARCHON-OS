"""
Operations API Router for Archon OS
Provides Kanban (Hermes kanban.db), Org-Chart, and Inter-Agent Communication Feed.
"""

import os
import sys
import json
import re
import sqlite3
import datetime
import subprocess
from typing import List, Dict, Optional, Any
from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel

router = APIRouter(prefix="/api/operations", tags=["operations"])

KANBAN_DB_PATH = "/opt/data/kanban.db" if os.path.exists("/opt/data/kanban.db") else "C:\\Users\\micha\\.hermes\\kanban.db"
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_FILE = os.path.join(WORKSPACE_DIR, "agent_profiles.json")


def _get_kanban_connection():
    if not os.path.exists(KANBAN_DB_PATH):
        raise HTTPException(status_code=503, detail=f"kanban.db nicht gefunden unter {KANBAN_DB_PATH}")
    conn = sqlite3.connect(KANBAN_DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _load_profiles_map() -> Dict[str, Dict]:
    profiles = {}
    if os.path.exists(PROFILES_FILE):
        try:
            with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    profiles[item.get("id")] = item
        except Exception as e:
            print(f"[OperationsAPI] Error loading profiles: {e}", file=sys.stderr)
    return profiles


def _get_fallback_avatar(aid: str) -> str:
    if not aid:
        return "/static/avatars/avatar_002.jpg"
    h = abs(hash(aid)) % 108 + 1
    if h == 1:
        h = 2
    return f"/static/avatars/avatar_{h:03d}.jpg"


# =========================================================================
# 1. KANBAN ENDPOINTS
# =========================================================================

class TaskCreateRequest(BaseModel):
    title: str
    body: Optional[str] = ""
    assignee: Optional[str] = None
    column: Optional[str] = "todo"
    priority: Optional[int] = 0
    model_override: Optional[str] = None
    provider_override: Optional[str] = None
    decompose: Optional[bool] = False
    team_id: Optional[str] = None


class TaskStatusUpdateRequest(BaseModel):
    status: str
    result: Optional[str] = None


@router.get("/kanban/tasks")
def get_kanban_tasks():
    """Gibt alle Tasks gruppiert nach den 6 Spalten von Hermes Kanban zurück."""
    conn = _get_kanban_connection()
    profiles = _load_profiles_map()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, title, body, assignee, status, priority, created_by, 
                   created_at, started_at, completed_at, result, model_override, provider_override
            FROM tasks
            ORDER BY priority DESC, created_at DESC
        """)
        rows = cursor.fetchall()
        
        columns = {
            "triage": [],
            "todo": [],
            "ready": [],
            "in_progress": [],
            "review": [],
            "done": [],
            "blocked": [],
            "scheduled": []
        }
        
        active_rows = 0
        for r in rows:
            task_dict = dict(r)
            st = (task_dict.get("status") or "todo").lower()
            if st == "archived":
                # 2-Stufen-Archiv (10.10.2026): archiviert gehoert nicht aufs Board
                # (vorher fiel archived still in den todo-Bucket)
                continue
            assignee_id = task_dict.get("assignee")
            prof = profiles.get(assignee_id, {})
            task_dict["assignee_name"] = prof.get("name") or assignee_id or "Nicht zugewiesen"
            task_dict["assignee_role"] = prof.get("category") or prof.get("role") or "Spezialist"
            task_dict["assignee_avatar"] = prof.get("avatar") or _get_fallback_avatar(assignee_id)
            
            if st in columns:
                columns[st].append(task_dict)
            else:
                columns["todo"].append(task_dict)
            active_rows += 1

        return {
            "status": "success",
            "columns": columns,
            "total_tasks": active_rows,
            "counts": {k: len(v) for k, v in columns.items()}
        }
    finally:
        conn.close()


@router.post("/kanban/tasks")
def create_kanban_task(req: TaskCreateRequest):
    """Erstellt eine neue Aufgabe im Hermes Kanban über CLI-Execution oder direkten Insert."""
    conn = _get_kanban_connection()
    try:
        now_iso = datetime.datetime.now().isoformat()
        cursor = conn.cursor()
        
        # Generiere kurze ID wie t-XXXX
        import secrets
        task_id = f"t-{secrets.token_hex(3)}"
        
        target_status = req.column if req.column in ["triage", "todo", "ready", "in_progress", "review", "done", "blocked", "scheduled"] else "todo"
        
        # Falls Team angegeben, aber kein spezifischer Agent: Auto-Routing zum Department Lead
        target_assignee = req.assignee
        team_name = ""
        if req.team_id:
            team_match = next((t for t in TEAMS_DEFINITION if t["id"] == req.team_id), None)
            if team_match:
                team_name = team_match["name"]
                if not target_assignee:
                    target_assignee = team_match["lead_id"]
                    
        # Optionales Team-Präfix im Body
        task_body = req.body or ""
        if team_name and f"[Team: {team_name}]" not in task_body:
            task_body = f"[Team: {team_name}]\n{task_body}".strip()
            
        cursor.execute("""
            INSERT INTO tasks (id, title, body, assignee, status, priority, created_by, created_at, model_override, provider_override)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task_id,
            req.title,
            task_body,
            target_assignee,
            target_status,
            req.priority or 0,
            "Archon-User",
            now_iso,
            req.model_override,
            req.provider_override
        ))
        
        # Log event
        cursor.execute("""
            INSERT INTO task_events (task_id, kind, payload, created_at)
            VALUES (?, ?, ?, ?)
        """, (task_id, "created", json.dumps({"title": req.title, "assignee": target_assignee, "team": req.team_id, "status": target_status}), now_iso))
        
        conn.commit()
        
        # Falls Decompose angefordert wurde und Hermes Container läuft:
        if req.decompose:
            try:
                subprocess.Popen(["docker", "exec", "hermes", "hermes", "kanban", "decompose", task_id])
            except Exception as e:
                print(f"[OperationsAPI] Decompose trigger error: {e}", file=sys.stderr)
                
        return {"status": "success", "task_id": task_id, "title": req.title, "assigned_to": target_assignee, "team": req.team_id}
    finally:
        conn.close()


@router.patch("/kanban/tasks/{task_id}/status")
def update_task_status(task_id: str, req: TaskStatusUpdateRequest):
    """Verschiebt eine Aufgabe in eine neue Spalte / Status."""
    conn = _get_kanban_connection()
    try:
        now_iso = datetime.datetime.now().isoformat()
        cursor = conn.cursor()

        cursor.execute("SELECT id, status FROM tasks WHERE id = ?", (task_id,))
        existing = cursor.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Task nicht gefunden.")

        old_status = existing["status"]
        new_status = req.status.lower()

        completed_at = now_iso if new_status == "done" else None

        cursor.execute("""
            UPDATE tasks
            SET status = ?,
                completed_at = COALESCE(?, completed_at),
                result = COALESCE(?, result)
            WHERE id = ?
        """, (new_status, completed_at, req.result, task_id))

        cursor.execute("""
            INSERT INTO task_events (task_id, kind, payload, created_at)
            VALUES (?, ?, ?, ?)
        """, (task_id, "status_changed", json.dumps({"from": old_status, "to": new_status}), now_iso))

        conn.commit()
        return {"status": "success", "task_id": task_id, "old_status": old_status, "new_status": new_status}
    finally:
        conn.close()


# --- Kanban-Farbpalette (User-Wunsch 10.10.2026: einstellbar über Design-Tab) ---
_KANBAN_PALETTE_FILE = os.path.join(WORKSPACE_DIR, "data", "kanban_palette.json")

# Posteo-Naturpalette (Standard, wie fest im Kanban eingebaut)
KANBAN_PALETTE_DEFAULTS = {
    "triage":      {"header": "#FFF5EB", "text": "#7c6a56"},
    "todo":        {"header": "#F3E8DE", "text": "#6b5d4f"},
    "ready":       {"header": "#F1B56F", "text": "#7a4a12"},
    "in_progress": {"header": "#EED65B", "text": "#6b5c10"},
    "review":      {"header": "#7CA982", "text": "#2f4a33"},
    "blocked":     {"header": "#C15C53", "text": "#ffffff"},
    "done":        {"header": "#4A6D88", "text": "#ffffff"}
}

class KanbanPaletteUpdate(BaseModel):
    columns: Optional[Dict[str, Dict[str, str]]] = None
    reset: bool = False

@router.get("/kanban/palette")
def get_kanban_palette():
    """Liefert die Kanban-Spaltenfarben (Gespeicherte, mit Posteo-Standard gemischt)."""
    if os.path.exists(_KANBAN_PALETTE_FILE):
        try:
            with open(_KANBAN_PALETTE_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            # Merge: Standard + gespeicherte Überschreibungen (gespeichert gewinnt)
            merged = {}
            for col_id, defaults in KANBAN_PALETTE_DEFAULTS.items():
                merged[col_id] = {**defaults, **(saved.get(col_id) or {})}
            return {"status": "ok", "custom": True, "columns": merged}
        except Exception as e:
            print(f"[OperationsAPI] Palette load error: {e}", file=sys.stderr)
    return {"status": "ok", "custom": False, "columns": KANBAN_PALETTE_DEFAULTS}

@router.post("/kanban/palette")
def save_kanban_palette(req: KanbanPaletteUpdate):
    """Speichert die Kanban-Farbpalette (oder setzt mit reset=true auf Standard zurück)."""
    if req.reset:
        if os.path.exists(_KANBAN_PALETTE_FILE):
            try:
                os.remove(_KANBAN_PALETTE_FILE)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Reset fehlgeschlagen: {e}")
        return {"status": "ok", "reset": True, "columns": KANBAN_PALETTE_DEFAULTS}
    if not req.columns:
        raise HTTPException(status_code=400, detail="columns erforderlich")
    # Sanitize: nur gültige Hex-Farben und bekannte Spalten-IDs
    cleaned = {}
    for col_id, colors in req.columns.items():
        if col_id not in KANBAN_PALETTE_DEFAULTS:
            continue
        entry = {}
        for key in ("header", "text"):
            val = str(colors.get(key, "")).strip()
            if re.fullmatch(r"#[0-9a-fA-F]{6}", val):
                entry[key] = val
        if entry:
            cleaned[col_id] = entry
    os.makedirs(os.path.dirname(_KANBAN_PALETTE_FILE), exist_ok=True)
    with open(_KANBAN_PALETTE_FILE, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, indent=2)
    return {"status": "ok", "saved": True, "columns": cleaned}


@router.get("/kanban/tasks/{task_id}")
def get_task_details(task_id: str):
    """Gibt Detailinformationen, Kommentare und Event-Logs eines Tasks zurück."""
    conn = _get_kanban_connection()
    profiles = _load_profiles_map()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        task_row = cursor.fetchone()
        if not task_row:
            raise HTTPException(status_code=404, detail="Task nicht gefunden.")
            
        task = dict(task_row)
        assignee_id = task.get("assignee")
        prof = profiles.get(assignee_id, {})
        task["assignee_name"] = prof.get("name") or assignee_id or "Nicht zugewiesen"
        task["assignee_avatar"] = prof.get("avatar") or _get_fallback_avatar(assignee_id)
        
        cursor.execute("SELECT * FROM task_comments WHERE task_id = ? ORDER BY created_at ASC", (task_id,))
        comments = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM task_events WHERE task_id = ? ORDER BY created_at ASC", (task_id,))
        events = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("""
            SELECT l.parent_id, l.child_id, t.title 
            FROM task_links l 
            JOIN tasks t ON l.child_id = t.id 
            WHERE l.parent_id = ?
        """, (task_id,))
        children = [dict(r) for r in cursor.fetchall()]
        
        return {
            "status": "success",
            "task": task,
            "comments": comments,
            "events": events,
            "subtasks": children
        }
    finally:
        conn.close()


@router.post("/kanban/tasks/{task_id}/comments")
def add_task_comment(task_id: str, author: str = Body(..., embed=True), body: str = Body(..., embed=True)):
    """Fügt einem Task einen Kommentar hinzu."""
    conn = _get_kanban_connection()
    try:
        now_iso = datetime.datetime.now().isoformat()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO task_comments (task_id, author, body, created_at)
            VALUES (?, ?, ?, ?)
        """, (task_id, author, body, now_iso))
        conn.commit()
        return {"status": "success", "task_id": task_id, "created_at": now_iso}
    finally:
        conn.close()


# =========================================================================
# 2. ORG-CHART & TEAMS ENDPOINT
# =========================================================================

TEAMS_DEFINITION = [
    {
        "id": "team_strategy",
        "name": "Geschäftsführung, Strategie & M&A",
        "lead_id": "executive_decision_architect",
        "color": "indigo",
        "members": [
            "executive_decision_architect",
            "micha",
            "default",
            "red_team_challenger",
            "tax_holding_advisor",
            "pricing_discount_governor",
            "pitchdeck_offer_designer",
            "personal_life_strategist",
            "agility_story",
            "analyze_claims",
            "gpts_automation_specialist",
            "gpts_critical_reviewer",
            "gpts_primary_synthesizer"
        ]
    },
    {
        "id": "team_tech",
        "name": "Software, Cloud & System-Architektur",
        "lead_id": "system_architect_orchestrator",
        "color": "blue",
        "members": [
            "system_architect_orchestrator",
            "senior_fullstack_engineer",
            "devops_cloud_sec_specialist",
            "database_performance_tuner",
            "enterprise_solutions_architect"
        ]
    },
    {
        "id": "team_legal",
        "name": "Recht, Verträge & Governance",
        "lead_id": "commercial_jurist_contracts",
        "color": "amber",
        "members": [
            "commercial_jurist_contracts",
            "liability_risk_analyst",
            "compliance_gdpr_auditor",
            "labor_law_hr_governance",
            "ip_patent_analyst",
            "vendor_contract_negotiator"
        ]
    },
    {
        "id": "team_realestate",
        "name": "Bau, Immobilien & ESG",
        "lead_id": "construction_project_manager",
        "color": "emerald",
        "members": [
            "construction_project_manager",
            "baugb_permit_expert",
            "realestate_dcf_calculator",
            "realestate_concept_strategist",
            "esg_kfw_efficiency_auditor",
            "urban_planning_architect",
            "vvgmbh_immo_tax_lead",
            "facility_asset_manager"
        ]
    },
    {
        "id": "team_growth",
        "name": "Vertrieb, Marketing & Media",
        "lead_id": "gtm_launch_strategist",
        "color": "rose",
        "members": [
            "gtm_launch_strategist",
            "growth_hacker_lead",
            "telegram_bot",
            "b2b_outreach_specialist",
            "direct_response_copywriter",
            "storyteller_ghostwriter",
            "video_script_architect",
            "content_repurposing_specialist",
            "speechwriter_keynote_designer",
            "pr_press_communicator",
            "affiliate_partner_manager",
            "ecommerce_shopify_lead",
            "lead_enrichment_analyst",
            "customer_retention_specialist",
            "brand_uiux_director"
        ]
    },
    {
        "id": "team_operations",
        "name": "Supply Chain, Einkauf & Scrum",
        "lead_id": "logistics_supply_chain_manager",
        "color": "teal",
        "members": [
            "logistics_supply_chain_manager",
            "procurement_sourcing_scout",
            "inventory_stock_forecaster",
            "agile_scrum_master",
            "product_requirements_engineer",
            "negotiation_master",
            "arbitrage_market_analyst",
            "competitive_intelligence_scout",
            "crisis_escalation_lead"
        ]
    }
]


@router.get("/org-chart")
def get_org_chart():
    """Gibt das vollständige hierarchische Organigramm mit den 3 Ebenen zurück."""
    profiles = _load_profiles_map()
    
    # Task counts pro Agent ermitteln
    task_counts = {}
    try:
        conn = _get_kanban_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT assignee, count(*) as cnt FROM tasks WHERE status != 'done' GROUP BY assignee")
        for row in cursor.fetchall():
            if row["assignee"]:
                task_counts[row["assignee"]] = row["cnt"]
        conn.close()
    except Exception:
        pass
        
    def _enrich(agent_id: str, is_lead: bool = False):
        p = profiles.get(agent_id, {})
        return {
            "id": agent_id,
            "name": p.get("name") or agent_id,
            "category": p.get("category") or "Spezialist",
            "role": p.get("role") or p.get("category") or "Experte",
            "avatar": p.get("avatar") or _get_fallback_avatar(agent_id),
            "model": p.get("model") or "deepseek/deepseek-chat",
            "provider": p.get("provider") or "omniroute",
            "is_lead": is_lead,
            "active_tasks": task_counts.get(agent_id, 0),
            "status": "active"
        }

    # Tier 1: Boardroom / Executive Apex
    chairman = _enrich("executive_decision_architect", is_lead=True)
    orchestrator = _enrich("system_architect_orchestrator", is_lead=True)
    
    # Tier 2 & 3: Teams
    teams = []
    for t in TEAMS_DEFINITION:
        lead = _enrich(t["lead_id"], is_lead=True)
        members = [_enrich(m_id) for m_id in t["members"] if m_id != t["lead_id"] and m_id in profiles]
        teams.append({
            "id": t["id"],
            "name": t["name"],
            "color": t["color"],
            "lead": lead,
            "member_count": len(members) + 1,
            "members": members
        })
        
    return {
        "status": "success",
        "tier1_executive": {
            "chairman": chairman,
            "orchestrator": orchestrator,
            "title": "Unternehmensführung & System-Architektur"
        },
        "teams": teams,
        "total_agents": len(profiles)
    }


# =========================================================================
# 3. INTER-AGENT COMMUNICATION FEED
# =========================================================================

@router.get("/comm-feed")
def get_communication_feed(limit: int = Query(50), agent_filter: Optional[str] = Query(None)):
    """Liefert den chronologischen internen Kommunikationsfluss aller Agenten."""
    profiles = _load_profiles_map()
    feed_items = []
    
    # 1. Aus kanban.db (task_comments & task_events)
    try:
        conn = _get_kanban_connection()
        cursor = conn.cursor()
        
        # Comments
        cursor.execute("""
            SELECT c.id, c.task_id, c.author, c.body, c.created_at, t.title as task_title, t.assignee
            FROM task_comments c
            JOIN tasks t ON c.task_id = t.id
            ORDER BY c.created_at DESC
            LIMIT ?
        """, (limit,))
        for r in cursor.fetchall():
            row = dict(r)
            author_id = row.get("author") or "agent"
            prof = profiles.get(author_id, {})
            feed_items.append({
                "id": f"comment_{row['id']}",
                "type": "task_comment",
                "timestamp": row["created_at"],
                "author_id": author_id,
                "author_name": prof.get("name") or author_id,
                "author_avatar": prof.get("avatar") or _get_fallback_avatar(author_id),
                "target_id": row.get("assignee"),
                "task_id": row["task_id"],
                "task_title": row["task_title"],
                "message": row["body"]
            })
            
        # Events (Handoffs & Status Changes)
        cursor.execute("""
            SELECT e.id, e.task_id, e.kind, e.payload, e.created_at, t.title as task_title, t.assignee
            FROM task_events e
            JOIN tasks t ON e.task_id = t.id
            WHERE e.kind IN ('created', 'status_changed', 'reassigned', 'completed', 'claimed')
            ORDER BY e.created_at DESC
            LIMIT ?
        """, (limit,))
        for r in cursor.fetchall():
            row = dict(r)
            payload_data = {}
            try:
                payload_data = json.loads(row["payload"])
            except Exception:
                pass
                
            feed_items.append({
                "id": f"event_{row['id']}",
                "type": "event_handoff",
                "timestamp": row["created_at"],
                "author_id": "system_dispatcher",
                "author_name": "Dispatcher / Orchestrator",
                "author_avatar": "/static/avatars/avatar_020.jpg",
                "target_id": row.get("assignee"),
                "task_id": row["task_id"],
                "task_title": row["task_title"],
                "kind": row["kind"],
                "message": f"Status-Update für '{row['task_title']}': {row['kind'].upper()} {json.dumps(payload_data, ensure_ascii=False)}"
            })
            
        conn.close()
    except Exception as e:
        print(f"[OperationsAPI] Comm-feed fetch error: {e}", file=sys.stderr)
        
    # Normalisiere Timestamps und sortiere nach Timestamp DESC
    def _parse_ts(val):
        if not val:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val) if val < 1e11 else float(val) / 1000.0
        if isinstance(val, str):
            try:
                if val.isdigit():
                    v = float(val)
                    return v if v < 1e11 else v / 1000.0
                dt = datetime.datetime.fromisoformat(val.replace("Z", "+00:00"))
                return dt.timestamp()
            except Exception:
                return 0.0
        return 0.0

    for item in feed_items:
        ts = item.get("timestamp")
        if isinstance(ts, (int, float)):
            try:
                sec = ts if ts < 1e11 else ts / 1000.0
                item["timestamp"] = datetime.datetime.fromtimestamp(sec).isoformat()
            except Exception:
                item["timestamp"] = str(ts)

    feed_items.sort(key=lambda x: _parse_ts(x.get("timestamp")), reverse=True)
    
    if agent_filter:
        feed_items = [item for item in feed_items if item.get("author_id") == agent_filter or item.get("target_id") == agent_filter]
        
    return {
        "status": "success",
        "feed": feed_items[:limit],
        "total": len(feed_items)
    }


# =========================================================================
# 4. INTERACTIVE ORG-CHART / FLOWCHART HIERARCHY PERSISTENCE
# =========================================================================

ORG_HIERARCHY_FILE = os.path.join(WORKSPACE_DIR, "config", "org_hierarchy.json")


def _generate_default_hierarchy():
    profiles = _load_profiles_map()
    nodes = []
    links = []

    # Task counts pro Agent
    task_counts = {}
    try:
        conn = _get_kanban_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT assignee, count(*) as cnt FROM tasks WHERE status != 'done' GROUP BY assignee")
        for row in cursor.fetchall():
            if row["assignee"]:
                task_counts[row["assignee"]] = row["cnt"]
        conn.close()
    except Exception:
        pass

    def _make_node(agent_id: str, x: int, y: int, tier: int = 3, team_id: str = "team_strategy"):
        p = profiles.get(agent_id, {})
        return {
            "id": agent_id,
            "x": x,
            "y": y,
            "tier": tier,
            "team_id": team_id,
            "name": p.get("name") or agent_id,
            "role": p.get("role") or p.get("category") or "Experte",
            "category": p.get("category") or "Spezialist",
            "avatar": p.get("avatar") or _get_fallback_avatar(agent_id),
            "model": p.get("model") or "deepseek/deepseek-chat",
            "active_tasks": task_counts.get(agent_id, 0),
            "status": "active"
        }

    # Tier 1: Apex (Chairman & CTO) - sauber zentriert
    nodes.append(_make_node("executive_decision_architect", 1320, 40, tier=1, team_id="team_strategy"))
    nodes.append(_make_node("system_architect_orchestrator", 1320, 200, tier=1, team_id="team_tech"))
    links.append({"from": "executive_decision_architect", "to": "system_architect_orchestrator"})

    # Tier 2: 6 Department Leads (je 460px Spalten-Abstand, 2 Spalten pro Team darunter)
    team_x_coords = {
        "team_strategy": 60,
        "team_tech": 520,
        "team_legal": 980,
        "team_realestate": 1440,
        "team_growth": 1900,
        "team_operations": 2360
    }

    for t in TEAMS_DEFINITION:
        tid = t["id"]
        tx = team_x_coords.get(tid, 500)
        lead_id = t["lead_id"]
        
        if lead_id not in ["executive_decision_architect", "system_architect_orchestrator"]:
            nodes.append(_make_node(lead_id, tx + 100, 380, tier=2, team_id=tid))
        
        if lead_id not in ["executive_decision_architect", "system_architect_orchestrator"]:
            parent_id = "system_architect_orchestrator" if tid in ["team_tech", "team_operations"] else "executive_decision_architect"
            links.append({"from": parent_id, "to": lead_id})

        # Tier 3: Specialists unter dem Lead in 2 Spalten ohne Überlappung
        specialists = [m for m in t["members"] if m != lead_id and m in profiles]
        for s_idx, s_id in enumerate(specialists):
            col = s_idx % 2
            row = s_idx // 2
            sx = tx + (col * 200)
            sy = 560 + (row * 180)
            nodes.append(_make_node(s_id, sx, sy, tier=3, team_id=tid))
            links.append({"from": lead_id, "to": s_id})

    # Keine Selbstreferenzen zulassen
    links = [l for l in links if l.get("from") and l.get("to") and l["from"] != l["to"]]

    return {
        "nodes": nodes,
        "links": links,
        "canvas_width": 2800,
        "canvas_height": 1800
    }


class OrgHierarchySaveRequest(BaseModel):
    nodes: List[Dict[str, Any]]
    links: List[Dict[str, Any]]
    canvas_width: Optional[int] = 3200
    canvas_height: Optional[int] = 3600


@router.get("/org-hierarchy")
def get_org_hierarchy():
    """Gibt das interaktive Organigramm (Nodes & Links) zurück."""
    if os.path.exists(ORG_HIERARCHY_FILE):
        try:
            with open(ORG_HIERARCHY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                profiles = _load_profiles_map()
                # Dynamisch sicherstellen, dass Avatare, Rollen und Namen dem aktuellen Stand entsprechen
                for node in data.get("nodes", []):
                    nid = node.get("id")
                    if nid in profiles:
                        p = profiles[nid]
                        if p.get("avatar"):
                            node["avatar"] = p["avatar"]
                        if p.get("person_name"):
                            node["person_name"] = p["person_name"]
                        if p.get("name"):
                            node["name"] = p["name"]
                        if p.get("role"):
                            node["role"] = p["role"]
                        if p.get("model"):
                            node["model"] = p["model"]
                        if p.get("provider"):
                            node["provider"] = p["provider"]
                
                # Selbstreferenzen strikt herausfiltern
                data["links"] = [
                    l for l in data.get("links", []) 
                    if l.get("from") and l.get("to") and l["from"] != l["to"]
                ]
                # Mindesthöhe und Mindestbreite sicherstellen
                data["canvas_width"] = max(data.get("canvas_width", 3200), 3200)
                data["canvas_height"] = max(data.get("canvas_height", 3600), 3600)
                return {"status": "success", "custom": True, "data": data}
        except Exception as e:
            print(f"[OperationsAPI] Error loading org_hierarchy: {e}", file=sys.stderr)
            
    return {"status": "success", "custom": False, "data": _generate_default_hierarchy()}


@router.post("/org-hierarchy")
def save_org_hierarchy(req: OrgHierarchySaveRequest):
    """Speichert die vom Nutzer interaktiv erstellten Verbindungen und Positionen."""
    try:
        os.makedirs(os.path.dirname(ORG_HIERARCHY_FILE), exist_ok=True)
        payload = {
            "updated_at": datetime.datetime.now().isoformat(),
            "nodes": req.nodes,
            "links": req.links,
            "canvas_width": max(req.canvas_width or 3200, 3200),
            "canvas_height": max(req.canvas_height or 3600, 3600)
        }
        with open(ORG_HIERARCHY_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return {"status": "success", "message": "Organigramm-Hierarchie gespeichert."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler beim Speichern: {str(e)}")


@router.delete("/org-hierarchy")
def reset_org_hierarchy():
    """Setzt die Hierarchie auf die 6 Standard-Teams zurück."""
    if os.path.exists(ORG_HIERARCHY_FILE):
        try:
            os.remove(ORG_HIERARCHY_FILE)
        except Exception:
            pass
    return {"status": "success", "message": "Auf Standard-Teams zurückgesetzt.", "data": _generate_default_hierarchy()}


# =========================================================================
# 5. GOVERNANCE & CONCURRENCY THROTTLE ENDPOINTS (Pillars 1, 2, 6)
# =========================================================================

class ConcurrencyUpdateRequest(BaseModel):
    max_tasks: int

@router.get("/governance/concurrency")
def get_concurrency_settings():
    """Liefert aktuellen Concurrency Throttle Status und Task-Semaphore."""
    import core_dispatcher
    return {
        "status": "success",
        "max_tasks": core_dispatcher.MAX_CONCURRENT_AGENT_TASKS,
        "active_semaphore_slots": core_dispatcher.MAX_CONCURRENT_AGENT_TASKS - core_dispatcher._TASK_SEMAPHORE._value,
        "available_slots": core_dispatcher._TASK_SEMAPHORE._value
    }

@router.post("/governance/concurrency")
def update_concurrency_settings(req: ConcurrencyUpdateRequest):
    """Passt das Limit für gleichzeitige LLM-Tasks dynamisch im laufenden System an."""
    import core_dispatcher
    val = max(1, min(20, req.max_tasks))
    core_dispatcher.MAX_CONCURRENT_AGENT_TASKS = val
    # Erneuere Semaphore
    import asyncio
    core_dispatcher._TASK_SEMAPHORE = asyncio.Semaphore(val)
    return {
        "status": "success",
        "message": f"Concurrency-Limit erfolgreich auf {val} Tasks gesetzt.",
        "max_tasks": val
    }

@router.get("/governance/audit-log")
def get_audit_log_entries(limit: int = 50):
    """Liefert die neuesten Einträge des manipulationssicheren SHA-256 Audit-Logs."""
    from local_memory_bridge import LocalMemoryBridge
    bridge = LocalMemoryBridge()
    with bridge._get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, agent_id, action, payload, prev_hash, hash, timestamp 
            FROM audit_log 
            ORDER BY id DESC 
            LIMIT ?
        """, (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        return {
            "status": "success",
            "entries": rows,
            "total_returned": len(rows)
        }

@router.post("/governance/audit-log/verify")
def verify_audit_log_chain():
    """Führt eine vollständige kryptografische Prüfung aller Verkettungen im Audit-Log durch."""
    from local_memory_bridge import LocalMemoryBridge
    bridge = LocalMemoryBridge()
    result = bridge.verify_audit_chain()
    return {
        "status": "success",
        "verification": result
    }


