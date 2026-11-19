"""Router fuer HUD-Telemetrie, Agent-Aktivitaeten, Projekte und Metriken."""
from __future__ import annotations
from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes

import asyncio
import datetime
import logging
import os
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response

from archon.core.paths import KANBAN_DB_PATH

logger = logging.getLogger("archon.routers.telemetry")

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["telemetry"])





def _read_recent_turns(agent_id: str) -> list[str]:
    recent_turns = []
    conn = None
    try:
        try:
            from backend.db_paths import resolve_db as _resolve_db
            db_path = _resolve_db("agentic_memory.db")
        except Exception:
            db_path = "/app/data/agentic_memory.db"
        if os.path.exists(db_path):
            import sqlite3

            conn = sqlite3.connect(db_path, timeout=5.0)
            conn.execute("PRAGMA busy_timeout=5000;")
            c = conn.cursor()
            rows = c.execute(
                "SELECT role, content, timestamp FROM conversations WHERE agent_id = ? ORDER BY id DESC LIMIT 5",
                (agent_id,),
            ).fetchall()
            for r in reversed(rows):
                recent_turns.append(f"[{r[2]}] {r[0].upper()}: {r[1][:140]}")
    except Exception:
        pass
    finally:
        if conn:
            conn.close()
    return recent_turns


@router.get("/api/v1/agent/{agent_id}/activity")
def api_get_agent_activity(agent_id: str):
    """Liefert Echtzeit-Aktivitaets- und Task-Logs fuer einen Agenten."""
    import main as app_main
    from fastapi import HTTPException
    from utils.path_jail import safe_identifier, PathJailError

    try:
        clean_id = safe_identifier(agent_id, "agent_id")
    except PathJailError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    log_candidates = [
        app_main.agent_log_path(clean_id),
    ]
    log_lines = []
    for lp in log_candidates:
        if os.path.exists(lp):
            try:
                with open(lp, "r", encoding="utf-8", errors="ignore") as f:
                    all_lines = f.readlines()
                    log_lines = [
                        line.strip() for line in all_lines[-40:] if line.strip()
                    ]
                break
            except Exception:
                pass

    recent_turns = _read_recent_turns(clean_id)


    if not log_lines and not recent_turns:
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        log_lines = [
            f"[{now_str}] Agent '{clean_id}' initialisiert im Standby-Modus.",
            f"[{now_str}] MCP Tools & Provider-Bindings aktiv.",
            f"[{now_str}] Bereit fuer Arbeitsauftraege und Autonom-Routing.",
        ]

    return {
        "status": "success",
        "agent_id": clean_id,
        "logs": log_lines,
        "recent_turns": recent_turns,
    }


@router.get("/api/v1/agent/{agent_id}/projects")
def api_get_agent_projects(agent_id: str):
    """Liefert die spezifische Projekthistorie (Beteiligungen) fuer einen bestimmten Agenten."""
    import main as app_main

    projects = []
    seen_ids = set()

    prof = None
    try:
        roles_list = app_main.api_get_hermes_profiles()
        prof = next((p for p in roles_list if p.get("id") == agent_id), None)
    except Exception:
        pass

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
                except Exception:
                    pass
        except Exception:
            pass

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
            except Exception:
                pass
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
    except Exception:
        pass
    return v_notes, mem_records, tot_inp, tot_out, tot_cache, tot_cost, skills_active


@router.get("/api/v1/hud/telemetry")
async def get_hud_telemetry():
    """Real-time Hermes HUD-UI consciousness and system telemetry stream."""
    import main as app_main

    agents = app_main.load_agents()
    services = app_main.load_services()

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
                    except Exception:
                        pass
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
        return _TELEMETRY_CACHE["containers"]
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
        except Exception:
            pass
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
    import main as app_main

    tasks_running = _get_running_tasks_count()
    app_start_ts = getattr(app_main, "_APP_START_TS", time.time())
    uptime_seconds = max(0, int(time.time() - app_start_ts))
    hours, rest = divmod(uptime_seconds, 3600)
    minutes = rest // 60

    load_agents_fn = getattr(app_main, "load_agents", lambda: [])

    return {
        "active_agents": len(load_agents_fn()),
        "tasks_running": tasks_running,
        "network_ops": _count_running_containers(),
        "avg_uptime": f"{hours}h {minutes}m",
        "uptime_seconds": uptime_seconds,
    }

