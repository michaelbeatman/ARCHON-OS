from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
"""Sub-Router fuer Org-Chart, Teams, Comm-Feed, Hierarchie und Concurrency Governance.

Ausgelagert aus backend/operations_api.py.
"""

import asyncio
import datetime
import json
import os
import sys
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from archon.routers._rbac import require_admin_or_503

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])


def _get_ops_deps():
    from backend.operations_api import (
        _get_fallback_avatar,
        _get_kanban_connection,
        _load_profiles_map,
        _PROFILES_MAP_CACHE,
        PROFILES_FILE,
        WORKSPACE_DIR,
    )
    return _load_profiles_map, _get_fallback_avatar, _get_kanban_connection, PROFILES_FILE, WORKSPACE_DIR, _PROFILES_MAP_CACHE


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
            "finance_lead",
            "debt_financing_specialist",
            "pricing_discount_governor",
            "pitchdeck_offer_designer",
            "personal_life_strategist",
            "research_scout",
            "hr_recruiter",
            "aggregation_lisa",
            "knowledge_librarian",
        ],
    },
    {
        "id": "team_tech",
        "name": "Software, Cloud, QA & Data",
        "lead_id": "system_architect_orchestrator",
        "color": "blue",
        "members": [
            "system_architect_orchestrator",
            "senior_fullstack_engineer",
            "qa_test_engineer",
            "devops_cloud_sec_specialist",
            "database_performance_tuner",
            "enterprise_solutions_architect",
            "bi_controller",
        ],
    },
    {
        "id": "team_legal",
        "name": "Recht, Versicherung & Governance",
        "lead_id": "commercial_jurist_contracts",
        "color": "amber",
        "members": [
            "commercial_jurist_contracts",
            "legal_counsel",
            "insurance_claims_manager",
            "liability_risk_analyst",
            "compliance_gdpr_auditor",
            "labor_law_hr_governance",
            "ip_patent_analyst",
            "vendor_contract_negotiator",
        ],
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
            "facility_asset_manager",
        ],
    },
    {
        "id": "team_growth",
        "name": "Vertrieb, Marketing, SEO & Media",
        "lead_id": "gtm_launch_strategist",
        "color": "rose",
        "members": [
            "gtm_launch_strategist",
            "growth_hacker_lead",
            "paid_ads_manager",
            "seo_geo_specialist",
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
            "customer_support_lead",
            "brand_uiux_director",
        ],
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
            "crisis_escalation_lead",
        ],
    },
    {
        "id": "team_science",
        "name": "Medizin, Chemie, Wissenschaft & Engineering",
        "lead_id": "clinical_medical_advisor",
        "color": "purple",
        "members": [
            "clinical_medical_advisor",
            "medtech_regulatory_lead",
            "chemistry_materials_specialist",
            "pharma_biotech_scientist",
            "scientific_literature_synthesizer",
            "industrial_process_engineer",
        ],
    },
]


@router.get("/org-chart")
def get_org_chart():
    """Gibt das vollständige hierarchische Organigramm mit den 3 Ebenen zurück."""
    _load_profiles_map, _get_fallback_avatar, _get_kanban_connection, _, _, _ = _get_ops_deps()
    profiles = _load_profiles_map()

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
            "status": "active",
        }

    chairman = _enrich("executive_decision_architect", is_lead=True)
    orchestrator = _enrich("system_architect_orchestrator", is_lead=True)

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
            "members": members,
        })

    return {
        "status": "success",
        "tier1_executive": {
            "chairman": chairman,
            "orchestrator": orchestrator,
            "title": "Unternehmensführung & System-Architektur",
        },
        "teams": teams,
        "total_agents": len(profiles),
    }


# =========================================================================
# 3. INTER-AGENT COMMUNICATION FEED
# =========================================================================

class CommBroadcastRequest(BaseModel):
    author: str = "commander"
    message: str
    task_id: Optional[str] = None
    target: Optional[str] = None


@router.post("/comm-feed/broadcast")
def broadcast_comm_message(req: CommBroadcastRequest):
    """Sendet eine Funkmeldung oder Agenten-Kommunikation in den Feed."""
    _, _, _get_kanban_connection, _, _, _ = _get_ops_deps()
    conn = _get_kanban_connection()
    try:
        now_iso = datetime.datetime.now().isoformat()
        cur = conn.cursor()
        payload = json.dumps({
            "author": req.author,
            "message": req.message,
            "target": req.target or "all",
            "broadcast": True,
        }, ensure_ascii=False)
        task_id = req.task_id or "system_broadcast"
        cur.execute("""
            INSERT INTO task_events (task_id, kind, payload, created_at)
            VALUES (?, 'broadcast', ?, ?)
        """, (task_id, payload, now_iso))
        conn.commit()
        return {"status": "success", "created_at": now_iso}
    finally:
        conn.close()


@router.get("/comm-feed")
def get_communication_feed(limit: int = Query(50), agent_filter: Optional[str] = Query(None)):
    """Liefert den chronologischen internen Kommunikationsfluss aller Agenten."""
    if hasattr(limit, "default"):
        limit = limit.default
    try:
        limit = int(limit)
    except Exception:
        limit = 50
    if hasattr(agent_filter, "default"):
        agent_filter = agent_filter.default

    _load_profiles_map, _get_fallback_avatar, _get_kanban_connection, _, _, _ = _get_ops_deps()
    conn = _get_kanban_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT e.id, e.task_id, e.kind, e.payload, e.created_at, t.title as task_title, t.assignee
        FROM task_events e
        LEFT JOIN tasks t ON e.task_id = t.id
        WHERE e.kind IN ('task_comment', 'broadcast', 'status_change', 'agent_started', 'agent_completed', 'human_takeover_requested', 'human_takeover_resolved', 'emergency_abort')
        ORDER BY e.created_at DESC
        LIMIT ?
    """, (limit * 2,))

    events = cursor.fetchall()
    conn.close()

    profiles = _load_profiles_map()
    feed_items = []

    for r in events:
        row = dict(r)
        payload_data = {}
        try:
            payload_data = json.loads(row["payload"])
        except Exception:
            pass

        kind = row.get("kind") or "comment"
        author_id = payload_data.get("author") or payload_data.get("agent") or "system"
        target_id = payload_data.get("target") or row.get("assignee")

        prof = profiles.get(author_id, {})
        author_name = prof.get("name") or author_id
        author_avatar = prof.get("avatar") or _get_fallback_avatar(author_id)

        target_prof = profiles.get(target_id, {}) if target_id else {}
        target_name = target_prof.get("name") or target_id

        msg_text = payload_data.get("message") or payload_data.get("comment") or ""
        if not msg_text and kind == "status_change":
            msg_text = f"Status geändert auf '{payload_data.get('to_status', 'unbekannt')}'"
        elif not msg_text and kind == "agent_started":
            msg_text = f"Agent {author_name} hat die Bearbeitung begonnen."
        elif not msg_text and kind == "agent_completed":
            msg_text = f"Agent {author_name} hat den Auftrag abgeschlossen."

        is_broadcast = payload_data.get("broadcast", False) or kind == "broadcast"

        item = {
            "id": f"event_{row['id']}",
            "timestamp": row["created_at"],
            "author_id": author_id,
            "author_name": author_name,
            "author_avatar": author_avatar,
            "target_id": target_id,
            "target_name": target_name,
            "task_id": row["task_id"],
            "task_title": row.get("task_title") or "System",
            "kind": kind,
            "message": msg_text,
            "is_broadcast": is_broadcast,
            "takeover_requested": kind == "human_takeover_requested",
            "takeover_resolved": kind == "human_takeover_resolved",
            "emergency_abort": kind == "emergency_abort",
        }

        if kind == "human_takeover_requested":
            item["author_name"] = "Hermes Bot Desktop"
            item["author_avatar"] = "/static/avatars/avatar_002.jpg"
            item["target_name"] = "Commander (Leitstand)"
        elif kind == "human_takeover_resolved":
            item["author_name"] = "Commander (Leitstand)"
            item["author_avatar"] = "/static/avatars/avatar_001.jpg"
            item["target_name"] = "Alle Agenten"
        elif kind == "emergency_abort":
            item["author_name"] = "Commander (Not-Aus)"
            item["author_avatar"] = "/static/avatars/avatar_001.jpg"
            item["target_name"] = "System-Sicherheit"

        feed_items.append(item)

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
        "total": len(feed_items),
    }


@router.get("/comm-feed/stream")
async def stream_comm_feed(request: Request):
    """Server-Sent Events (SSE) Stream für Realtime-Inter-Agenten-Kommunikation."""
    _load_profiles_map, _get_fallback_avatar, _get_kanban_connection, _, _, _ = _get_ops_deps()

    async def sse_event_generator():
        last_seen_time = datetime.datetime.now().isoformat()
        yield f"data: {json.dumps({'type': 'init', 'timestamp': last_seen_time, 'message': 'Comm-Feed Stream verbunden'})}\n\n"

        while True:
            if await request.is_disconnected():
                break

            try:
                conn = _get_kanban_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT e.id, e.task_id, e.kind, e.payload, e.created_at, t.title as task_title, t.assignee
                    FROM task_events e
                    LEFT JOIN tasks t ON e.task_id = t.id
                    WHERE e.created_at > ?
                    ORDER BY e.created_at ASC
                    LIMIT 20
                """, (last_seen_time,))
                new_events = cursor.fetchall()
                profiles = _load_profiles_map()

                for r in new_events:
                    row = dict(r)
                    last_seen_time = max(last_seen_time, row["created_at"])
                    payload_data = {}
                    try:
                        payload_data = json.loads(row["payload"])
                    except Exception:
                        pass

                    kind = row.get("kind") or "event"
                    author_id = payload_data.get("author") or "commander"
                    prof = profiles.get(author_id, {})
                    author_name = prof.get("name") or ("Commander (Leitstand)" if author_id == "commander" else author_id)
                    author_avatar = prof.get("avatar") or ("/static/avatars/avatar_001.jpg" if author_id == "commander" else _get_fallback_avatar(author_id))

                    item = {
                        "type": "new_message",
                        "id": f"event_{row['id']}",
                        "timestamp": row["created_at"],
                        "author_id": author_id,
                        "author_name": author_name,
                        "author_avatar": author_avatar,
                        "target_id": payload_data.get("target") or row.get("assignee"),
                        "task_id": row["task_id"],
                        "task_title": row.get("task_title") or "System",
                        "kind": kind,
                        "message": payload_data.get("message") or str(payload_data),
                        "takeover_requested": kind == "human_takeover_requested",
                    }
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

                conn.close()
            except Exception:
                pass

            await asyncio.sleep(1.2)

    return StreamingResponse(
        sse_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# =========================================================================
# 4. INTERACTIVE ORG-CHART / FLOWCHART HIERARCHY PERSISTENCE
# =========================================================================

def _get_org_hierarchy_file() -> str:
    _, _, _, _, workspace_dir, _ = _get_ops_deps()
    return os.path.join(workspace_dir, "config", "org_hierarchy.json")


def _generate_default_hierarchy():
    _load_profiles_map, _get_fallback_avatar, _get_kanban_connection, _, _, _ = _get_ops_deps()
    profiles = _load_profiles_map()
    nodes = []
    links = []

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
            "status": "active",
        }

    nodes.append(_make_node("executive_decision_architect", 1320, 40, tier=1, team_id="team_strategy"))
    nodes.append(_make_node("system_architect_orchestrator", 1320, 200, tier=1, team_id="team_tech"))
    links.append({"from": "executive_decision_architect", "to": "system_architect_orchestrator"})

    team_x_coords = {
        "team_strategy": 60,
        "team_tech": 520,
        "team_legal": 980,
        "team_realestate": 1440,
        "team_growth": 1900,
        "team_operations": 2360,
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

        specialists = [m for m in t["members"] if m != lead_id and m in profiles]
        for s_idx, s_id in enumerate(specialists):
            col = s_idx % 2
            row = s_idx // 2
            sx = tx + (col * 200)
            sy = 560 + (row * 180)
            nodes.append(_make_node(s_id, sx, sy, tier=3, team_id=tid))
            links.append({"from": lead_id, "to": s_id})

    links = [l for l in links if l.get("from") and l.get("to") and l["from"] != l["to"]]

    return {
        "nodes": nodes,
        "links": links,
        "canvas_width": 2800,
        "canvas_height": 1800,
    }


class OrgHierarchySaveRequest(BaseModel):
    nodes: List[Dict[str, Any]]
    links: List[Dict[str, Any]]
    canvas_width: Optional[int] = 3200
    canvas_height: Optional[int] = 3600


@router.get("/org-hierarchy")
def get_org_hierarchy():
    """Gibt das interaktive Organigramm (Nodes & Links) zurück."""
    org_file = _get_org_hierarchy_file()
    if os.path.exists(org_file):
        try:
            with open(org_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                _load_profiles_map, _, _, _, _, _ = _get_ops_deps()
                profiles = _load_profiles_map()
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

                data["links"] = [
                    l for l in data.get("links", [])
                    if l.get("from") and l.get("to") and l["from"] != l["to"]
                ]
                data["canvas_width"] = max(data.get("canvas_width", 3200), 3200)
                data["canvas_height"] = max(data.get("canvas_height", 3600), 3600)
                return {"status": "success", "custom": True, "data": data}
        except Exception as e:
            print(f"[OperationsAPI] Error loading org_hierarchy: {e}", file=sys.stderr)

    return {"status": "success", "custom": False, "data": _generate_default_hierarchy()}


@router.post("/org-hierarchy")
def save_org_hierarchy(request: Request, req: OrgHierarchySaveRequest):
    """Speichert die vom Nutzer interaktiv erstellten Verbindungen und Positionen."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    org_file = _get_org_hierarchy_file()
    _, _, _, profiles_file, _, _profiles_map_cache = _get_ops_deps()
    try:
        os.makedirs(os.path.dirname(org_file), exist_ok=True)
        payload = {
            "updated_at": datetime.datetime.now().isoformat(),
            "nodes": req.nodes,
            "links": req.links,
            "canvas_width": max(req.canvas_width or 3200, 3200),
            "canvas_height": max(req.canvas_height or 3600, 3600),
        }
        with open(org_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

        try:
            if os.path.exists(profiles_file):
                with open(profiles_file, "r", encoding="utf-8") as pf:
                    plist = json.load(pf)
                nodes_by_id = {n.get("id"): n for n in (req.nodes or []) if isinstance(n, dict) and n.get("id")}
                changed_any = False
                for p in plist:
                    pid = p.get("id")
                    if pid in nodes_by_id:
                        nd = nodes_by_id[pid]
                        for k in ("name", "person_name", "model", "provider", "avatar", "reasoning_level"):
                            if nd.get(k) and nd.get(k) != p.get(k):
                                p[k] = nd[k]
                                changed_any = True
                if changed_any:
                    with open(profiles_file, "w", encoding="utf-8") as pf:
                        json.dump(plist, pf, indent=2, ensure_ascii=False)
                    _profiles_map_cache["mtime"] = 0.0
        except Exception as sync_e:
            print(f"[OperationsAPI] Profile sync notice: {sync_e}", file=sys.stderr)
        return {"status": "success", "message": "Organigramm-Hierarchie gespeichert."}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "org_save_failed", "params": {"error": str(e)}})


@router.delete("/org-hierarchy")
def reset_org_hierarchy(request: Request):
    """Setzt die Hierarchie auf die 6 Standard-Teams zurück."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    org_file = _get_org_hierarchy_file()
    if os.path.exists(org_file):
        try:
            os.remove(org_file)
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
        "available_slots": core_dispatcher._TASK_SEMAPHORE._value,
    }


@router.post("/governance/concurrency")
def update_concurrency_settings(request: Request, req: ConcurrencyUpdateRequest):
    """Passt das Limit für gleichzeitige LLM-Tasks dynamisch im laufenden System an."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    import core_dispatcher
    val = max(1, min(20, req.max_tasks))
    core_dispatcher.MAX_CONCURRENT_AGENT_TASKS = val
    core_dispatcher._TASK_SEMAPHORE = asyncio.Semaphore(val)
    return {
        "status": "success",
        "message": f"Concurrency-Limit erfolgreich auf {val} Tasks gesetzt.",
        "max_tasks": val,
    }


@router.get("/governance/audit-log")
def get_audit_log_entries(
    category: Optional[str] = None,
    search: Optional[str] = None,
    provider: Optional[str] = None,
    target_host: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """Liefert die Einträge des revisionssicheren SHA-256 GoBD/ISO 27001 Audit-Logs mit Filterung (inkl. Provider & Ziel-Host)."""
    from backend.audit_log import chained_audit_log
    res = chained_audit_log.list_events(
        category=category,
        search=search,
        provider=provider,
        target_host=target_host,
        limit=limit,
        offset=offset,
    )
    return {
        "status": "success",
        "total": res["total"],
        "limit": res["limit"],
        "offset": res["offset"],
        "entries": res["entries"],
    }


@router.get("/governance/audit-log/llm-dispatches")
def get_audit_llm_dispatches(
    provider: Optional[str] = None,
    target_host: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """Liefert alle kryptografisch verketteten LLM-Dispatch-Nachweise (Provider, Modell, Ziel-Host, realer Ziel-Endpunkt)."""
    from backend.audit_log import chained_audit_log
    dispatches = chained_audit_log.list_llm_dispatches(
        limit=limit,
        offset=offset,
        provider=provider,
        target_host=target_host,
    )
    return {
        "status": "success",
        "count": len(dispatches),
        "dispatches": dispatches,
    }


@router.get("/governance/zero-egress-audit")
def get_zero_egress_posture_audit():
    """Live-Prüfbericht für Zero-Egress-Konfiguration, Privacy-Router Hard-Block, Docker-Worker-Netzwerk (Internal=true) und SHA-256-Hashkette."""
    from backend.llm_egress_guard import audit_zero_egress_posture
    return {
        "status": "success",
        "posture": audit_zero_egress_posture(),
    }


@router.post("/governance/audit-log/verify")
def verify_audit_log_chain():
    """Führt eine vollständige kryptografische Prüfung aller Verkettungen im Audit-Log durch."""
    from backend.audit_log import chained_audit_log
    result = chained_audit_log.verify_integrity()
    return {
        "status": "success",
        "verification": result,
    }


@router.get("/governance/audit-log/export")
def export_audit_log(format: str = Query(default="json")):
    """Generiert einen revisionssicheren Prüfbericht für GoBD / ISO 27001 Auditoren als JSON oder CSV."""
    from backend.audit_log import chained_audit_log
    res = chained_audit_log.generate_compliance_export(format_type=format)
    return Response(
        content=res["content"],
        media_type=res["content_type"],
        headers={"Content-Disposition": f'attachment; filename="{res["filename"]}"'},
    )
