"""Projekt-Zentrale, Projekt-Meta-Sidecar und Vault-/Projektdatei-Zugriff (D3/3).

Ausgelagert aus ``backend/operations_api.py`` nach dem S3-Muster
(Call-Time-Dependency-Injection):
* Kein Rueckimport auf ``backend.operations_api``.
* Kein Import aus ``archon.routers.*`` (wahrt Layer-Contract D09/H-09-2).
* Alle Monkeypatches auf ``backend.operations_api._get_kanban_connection``,
  ``_load_kanban_meta``, ``_fuzzy_project_exact_match`` und
  ``_PROJECTS_META_FILE`` greifen unveraendert zur Aufrufzeit.
"""

from __future__ import annotations

import datetime
import json
import mimetypes
import os
import sqlite3
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple

from fastapi import HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

_PROJECTS_META_LOCK = threading.Lock()
_PROJECTS_META_ALLOWED = ("description", "goal", "status", "lead_agent", "archived")


class ProjectsDeps(NamedTuple):
    """Zur Aufrufzeit injizierte Abhaengigkeiten aus backend.operations_api."""

    get_kanban_connection: Callable[..., Any]
    load_kanban_meta: Callable[[], Dict[str, Any]]
    fuzzy_project_exact_match: Callable[[str, List[Any]], Optional[str]]
    projects_meta_file: str


class ProjectMetaUpdate(BaseModel):
    description: Optional[str] = None
    goal: Optional[str] = None
    status: Optional[str] = None
    lead_agent: Optional[str] = None
    archived: Optional[bool] = None


def safe_path_within(base: Path, rel: str) -> Optional[Path]:
    """F13 (D03): Path-Jail via Path.is_relative_to (kein naiver startswith-Bypass)."""
    rel_clean = str(rel or "").strip()
    if not rel_clean:
        return None
    try:
        base_resolved = Path(base).resolve()
        cand = (base_resolved / rel_clean).resolve()
        if cand.is_relative_to(base_resolved):
            return cand
    except Exception:
        return None
    return None


def resolve_task_obsidian_rel(
    task_id: str,
    deps: ProjectsDeps,
    meta: Optional[Dict[str, Any]] = None,
    auto_heal: bool = False,
) -> Optional[str]:
    """Ermittelt den relativen Obsidian-Projektordner fuer eine Task mit automatischer Reparatur/Fallback."""
    from backend.post_task_pipeline import get_vault_dir

    if meta is None:
        meta = deps.load_kanban_meta()
    t_entry = (meta.get("tasks") or {}).get(task_id) or {}
    rel: Optional[str] = t_entry.get("obsidian")
    vault = Path(get_vault_dir()).resolve()
    if rel and str(rel).strip():
        cand = safe_path_within(vault, str(rel).strip())
        if cand is not None and cand.is_dir():
            return str(rel).strip()
        # F13: Ungueltiger oder ausserhalb des Vaults liegender Pfad darf nicht
        # als Rueckgabewert ueberleben.
        rel = None

    # Fallback 1: Pruefe ob in decision ein dossier liegt
    dossier = (t_entry.get("decision") or {}).get("dossier") or ""
    if "01_PROJEKTE/" in dossier:
        try:
            sub = dossier.split("01_PROJEKTE/")[1].split("/")[0]
            cand = safe_path_within(vault, f"01_PROJEKTE/{sub}")
            if cand is not None and cand.is_dir():
                rel = f"01_PROJEKTE/{sub}"
        except Exception as exc:
            print(
                f"[OperationsAPI] Fallback _resolve_task_obsidian_rel: Exception im Fehler-/Fallback-Pfad: {exc}",
                file=sys.stderr,
            )

    # Fallback 1b: Falls Subtask, erbe Projekt vom Parent aus task_links
    if not rel:
        try:
            conn = deps.get_kanban_connection()
            try:
                r_parent = conn.execute(
                    "SELECT parent_id FROM task_links WHERE child_id = ? AND COALESCE(kind, 'subtask') = 'subtask'",
                    (task_id,),
                ).fetchone()
                parent_id = r_parent[0] if r_parent else None
            finally:
                conn.close()
            if parent_id and parent_id != task_id:
                parent_rel = resolve_task_obsidian_rel(parent_id, deps, meta)
                if parent_rel:
                    return parent_rel
        except Exception as exc:
            print(
                f"[OperationsAPI] Fallback _resolve_task_obsidian_rel: Exception im Fehler-/Fallback-Pfad: {exc}",
                file=sys.stderr,
            )

    # Fallback 2: Pruefe kanban.db nach project_id
    if not rel:
        try:
            conn = deps.get_kanban_connection()
            try:
                r = conn.execute("SELECT project_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
                pid = r[0] if r else None
            finally:
                conn.close()
            if pid and (vault / "01_PROJEKTE").is_dir():
                for d in (vault / "01_PROJEKTE").iterdir():
                    if d.is_dir() and pid in d.name:
                        rel = f"01_PROJEKTE/{d.name}"
                        break
        except Exception as exc:
            print(
                f"[OperationsAPI] Fallback _resolve_task_obsidian_rel: Exception im Fehler-/Fallback-Pfad: {exc}",
                file=sys.stderr,
            )

    # Fallback 3: Pruefe ob Ordner mit task_id in 01_PROJEKTE existiert
    if not rel and (vault / "01_PROJEKTE").is_dir():
        try:
            for d in (vault / "01_PROJEKTE").iterdir():
                if d.is_dir() and task_id in d.name:
                    rel = f"01_PROJEKTE/{d.name}"
                    break
        except Exception as exc:
            print(
                f"[OperationsAPI] Fallback _resolve_task_obsidian_rel: Exception im Fehler-/Fallback-Pfad: {exc}",
                file=sys.stderr,
            )

    # Fallback 4: Durchsuche 01_PROJEKTE nach Dateien mit task_id (in 03_Endprodukte oder 01_Zwischenberichte)
    if not rel and (vault / "01_PROJEKTE").is_dir():
        try:
            for p_dir in (vault / "01_PROJEKTE").iterdir():
                if not p_dir.is_dir():
                    continue
                for sub in ("03_Endprodukte", "01_Zwischenberichte"):
                    s_dir = p_dir / sub
                    if s_dir.is_dir():
                        for f in s_dir.iterdir():
                            if task_id in f.name:
                                rel = f"01_PROJEKTE/{p_dir.name}"
                                break
                    if rel:
                        break
                if rel:
                    break
        except Exception as exc:
            print(
                f"[OperationsAPI] Fallback _resolve_task_obsidian_rel: Exception im Fehler-/Fallback-Pfad: {exc}",
                file=sys.stderr,
            )

    # Fallback 5: Titel/Body Keyword-Match gegen Ordnernamen in 01_PROJEKTE
    if not rel and (vault / "01_PROJEKTE").is_dir():
        try:
            conn = deps.get_kanban_connection()
            try:
                r_tb = conn.execute("SELECT title, body FROM tasks WHERE id = ?", (task_id,)).fetchone()
                t_title = (r_tb[0] or "") if r_tb else ""
                t_body = (r_tb[1] or "") if r_tb else ""
            finally:
                conn.close()
            combined = (t_title + " " + t_body).lower()
            for p_dir in (vault / "01_PROJEKTE").iterdir():
                if not p_dir.is_dir():
                    continue
                p_slug = p_dir.name.lower()
                for part in p_slug.split("-"):
                    if len(part) >= 4 and part in combined and part not in ("projekt", "delegationsprojekt", "2026"):
                        rel = f"01_PROJEKTE/{p_dir.name}"
                        break
                if rel:
                    break
        except Exception as exc:
            print(
                f"[OperationsAPI] Fallback _resolve_task_obsidian_rel: Exception im Fehler-/Fallback-Pfad: {exc}",
                file=sys.stderr,
            )

    # In-Memory Cache im uebergebenen meta-Dict aktualisieren (vermeidet N-fache Lookups)
    if rel and meta is not None:
        try:
            meta.setdefault("tasks", {}).setdefault(task_id, {})["obsidian"] = rel
        except Exception as exc:
            print(
                f"[OperationsAPI] Fallback _resolve_task_obsidian_rel: Exception im Fehler-/Fallback-Pfad: {exc}",
                file=sys.stderr,
            )

    # P-03: Nur bei explizitem auto_heal=True (z.B. Task-Mutation) Sidecar-fsync ausfuehren
    if rel and auto_heal:
        try:
            from backend.kanban_sidecar import update_kanban_meta

            def _heal(m: Dict[str, Any]) -> None:
                m.setdefault("tasks", {}).setdefault(task_id, {})["obsidian"] = rel

            update_kanban_meta(_heal)
        except Exception as exc:
            print(
                f"[OperationsAPI] WARNUNG (MEDIUM) _resolve_task_obsidian_rel: Exception im Fehler-/Fallback-Pfad: {exc}",
                file=sys.stderr,
            )

    return rel


def get_agent_cadre_map() -> Dict[str, Dict[str, Any]]:
    """Liest Agenten-Klarnamen, Rollen, Avatare, Modelle und Tools aus org_hierarchy.json + Hermes-Profilen."""
    mapping: Dict[str, Dict[str, Any]] = {}
    cfg = Path("config/org_hierarchy.json")
    if cfg.is_file():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            for node in data.get("nodes", []):
                nid = node.get("id")
                if not nid:
                    continue
                p_name = (node.get("person_name") or "").strip()
                r_name = (node.get("name") or node.get("role") or "").strip()
                short_role = r_name.split("(")[0].strip() if r_name else ""
                display = (
                    f"{p_name}, {short_role}"
                    if p_name and short_role and p_name != short_role
                    else (p_name or short_role or nid)
                )
                mapping[nid] = {
                    "id": nid,
                    "person_name": p_name or nid,
                    "role": short_role,
                    "display": display,
                    "avatar_url": "/static/avatars/hermes_default_avatar.png",
                    "tools": [],
                    "model": "",
                    "provider": "",
                }
        except Exception as exc:
            print(
                f"[OperationsAPI] Fallback _get_agent_cadre_map: Exception im Fehler-/Fallback-Pfad: {exc}",
                file=sys.stderr,
            )
    try:
        from archon.core.profiles import api_get_hermes_profiles

        for p in api_get_hermes_profiles() or []:
            pid = p.get("id")
            if not pid:
                continue
            entry = mapping.setdefault(
                pid,
                {
                    "id": pid,
                    "person_name": p.get("name") or pid,
                    "role": "",
                    "display": p.get("name") or pid,
                    "avatar_url": "",
                    "tools": [],
                    "model": "",
                    "provider": "",
                },
            )
            if p.get("avatar_url"):
                entry["avatar_url"] = p["avatar_url"]
            elif not entry.get("avatar_url"):
                entry["avatar_url"] = "/static/avatars/hermes_default_avatar.png"
            if isinstance(p.get("tools"), list):
                entry["tools"] = list(p["tools"])
            if p.get("model"):
                entry["model"] = p["model"]
            if p.get("provider"):
                entry["provider"] = p["provider"]
    except Exception as exc:
        print(
            f"[OperationsAPI] Fallback _get_agent_cadre_map: Exception im Fehler-/Fallback-Pfad: {exc}",
            file=sys.stderr,
        )
    return mapping


def get_session_usage_map() -> Dict[str, Any]:
    """Liest Token-, Modell-, Kosten- und Tool-Nutzung pro session_id aus state.db."""
    usage: Dict[str, Any] = {}
    db_path = (
        "/opt/data/state.db"
        if os.path.exists("/opt/data/state.db")
        else os.path.join("data", "state.db")
    )
    if not os.path.exists(db_path):
        return usage
    try:
        conn = sqlite3.connect(db_path, timeout=2.0)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, model, input_tokens, output_tokens, estimated_cost_usd, actual_cost_usd, tool_names, tool_call_count FROM sessions"
            )
            for sid, model, inp, out, est_c, act_c, tnames, tcalls in cur.fetchall():
                if not sid:
                    continue
                tools_list: List[str] = []
                if tnames:
                    try:
                        parsed = json.loads(tnames)
                        if isinstance(parsed, list):
                            tools_list = [str(x) for x in parsed if x]
                    except Exception:
                        tools_list = [x.strip() for x in str(tnames).split(",") if x.strip()]
                inp_i = int(inp or 0)
                out_i = int(out or 0)
                cost = float(act_c if act_c is not None else (est_c or 0.0))
                usage[sid] = {
                    "model": model or "",
                    "tokens_input": inp_i,
                    "tokens_output": out_i,
                    "tokens_total": inp_i + out_i,
                    "cost_usd": round(cost, 6),
                    "tools_used": tools_list,
                    "tool_call_count": int(tcalls or 0),
                }
        finally:
            conn.close()
    except Exception as exc:
        print(
            f"[OperationsAPI] Fallback _get_session_usage_map: Exception im Fehler-/Fallback-Pfad: {exc}",
            file=sys.stderr,
        )
    return usage


def load_projects_meta(projects_meta_file: str) -> Dict[str, Any]:
    try:
        with open(projects_meta_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def save_projects_meta(projects_meta_file: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(projects_meta_file), exist_ok=True)
    tmp = projects_meta_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, projects_meta_file)


def _parse_ts_and_num(val: Any, fallback_ts: float) -> Tuple[float, str, str]:
    ts: Optional[float] = None
    if val is not None and str(val).strip() != "":
        s = str(val).strip()
        try:
            num = float(s)
            if num > 1e12:
                num = num / 1000.0
            if num > 1e8:
                ts = num
        except Exception:
            try:
                dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
                ts = dt.timestamp()
            except Exception as exc:
                print(
                    f"[OperationsAPI] Fallback get_projects_overview: Exception im Fehler-/Fallback-Pfad: {exc}",
                    file=sys.stderr,
                )
    if ts is None:
        ts = fallback_ts
    dt_obj = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
    return ts, dt_obj.strftime("%Y%m%d%H%M%S"), dt_obj.isoformat()


def build_projects_overview(deps: ProjectsDeps) -> Dict[str, Any]:
    """Liefert die konsolidierte Projekt-Zentrale fuer Operations."""
    from backend.post_task_pipeline import get_vault_dir

    vault = Path(get_vault_dir()).resolve()
    p_root = vault / "01_PROJEKTE"
    cadre_map = get_agent_cadre_map()
    session_usage = get_session_usage_map()

    # 1. Hole alle Tasks aus kanban.db gruppiert nach project_id
    tasks_by_project: Dict[str, List[Dict[str, Any]]] = {}
    conn = deps.get_kanban_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, title, assignee, status, priority, created_at, completed_at, result, project_id, session_id, model_override, skills FROM tasks ORDER BY rowid ASC"
        )
        for r in cur.fetchall():
            tid, title, assignee, status, prio, cat, comp, res, pid, sid, mod_ov, skills_raw = r
            if not pid:
                continue
            su = session_usage.get(sid or "", {})
            a_info = cadre_map.get(assignee or "", {})
            model_used = su.get("model") or mod_ov or a_info.get("model") or ""
            tools_used = list(su.get("tools_used") or [])
            if not tools_used and skills_raw:
                try:
                    parsed_sk = json.loads(skills_raw)
                    if isinstance(parsed_sk, list):
                        tools_used = [str(x) for x in parsed_sk if x]
                except Exception as exc:
                    print(
                        f"[OperationsAPI] Fallback get_projects_overview: Exception im Fehler-/Fallback-Pfad: {exc}",
                        file=sys.stderr,
                    )
            tasks_by_project.setdefault(pid, []).append({
                "id": tid,
                "title": title,
                "assignee": assignee,
                "status": status,
                "created_at": cat,
                "completed_at": comp,
                "result": res or "",
                "result_preview": (res or "")[:200],
                "model": model_used,
                "tokens_input": su.get("tokens_input", 0),
                "tokens_output": su.get("tokens_output", 0),
                "tokens_total": su.get("tokens_total", 0),
                "cost_usd": su.get("cost_usd", 0.0),
                "tools_used": tools_used,
                "tool_call_count": su.get("tool_call_count", 0),
            })
    finally:
        conn.close()

    # 2. Scanne Obsidian 01_PROJEKTE
    projects: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()

    if p_root.is_dir():
        for p_dir in sorted(p_root.iterdir(), key=lambda d: d.stat().st_mtime, reverse=True):
            if not p_dir.is_dir() or p_dir.name.startswith((".", "_")):
                continue

            folder_name = p_dir.name
            proj_title = folder_name
            status = "in_progress"
            lead_agent = "executive_decision_architect"
            assignees: set[str] = set()
            primary_doc: Optional[str] = None
            has_html = False

            p_md = p_dir / "PROJEKT.md"
            if p_md.is_file():
                try:
                    txt = p_md.read_text(encoding="utf-8")
                    for line in txt.splitlines():
                        if line.startswith("title:"):
                            proj_title = line.replace("title:", "").strip().strip('"').strip("'")
                        elif line.startswith("# ") and proj_title == folder_name:
                            proj_title = line.replace("# ", "").replace("📂 Projekt:", "").strip()
                        elif line.startswith("status:"):
                            st_val = line.replace("status:", "").strip().strip('"').strip("'").lower()
                            if "complete" in st_val or "abgeschlossen" in st_val:
                                status = "completed"
                            elif "plan" in st_val:
                                status = "planned"
                except Exception as exc:
                    print(
                        f"[OperationsAPI] Fallback get_projects_overview: Exception im Fehler-/Fallback-Pfad: {exc}",
                        file=sys.stderr,
                    )

            end_dir = p_dir / "03_Endprodukte"
            if end_dir.is_dir():
                for f in sorted(end_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                    if f.suffix.lower() == ".html":
                        primary_doc = f"01_PROJEKTE/{folder_name}/03_Endprodukte/{f.name}"
                        has_html = True
                        break
                    elif f.suffix.lower() == ".md" and not primary_doc:
                        primary_doc = f"01_PROJEKTE/{folder_name}/03_Endprodukte/{f.name}"

            subtasks: List[Dict[str, Any]] = []
            _all_folder_names = list(tasks_by_project.keys())
            for pid, t_list in tasks_by_project.items():
                if pid and pid.lower() == folder_name.lower():
                    matched = True
                else:
                    matched = deps.fuzzy_project_exact_match(pid, [folder_name]) is not None
                if not matched:
                    for part in folder_name.lower().split("-"):
                        if len(part) >= 4 and part not in ("projekt", "2026"):
                            _containing = [d2 for d2 in _all_folder_names if part in d2.lower()]
                            if len(_containing) == 1 and pid and part in str(pid).lower():
                                matched = True
                                break
                if matched:
                    subtasks.extend(t_list)
                    seen_ids.add(pid)
                    for st in t_list:
                        if st.get("assignee"):
                            assignees.add(st["assignee"])

            t_total = len(subtasks)
            t_done = sum(1 for st in subtasks if st.get("status") in ("done", "review", "completed"))
            progress = int((t_done / t_total) * 100) if t_total > 0 else (100 if status == "completed" else 0)
            if t_total > 0 and t_done == t_total:
                status = "completed"

            z_count = (
                len(list((p_dir / "01_Zwischenberichte").iterdir()))
                if (p_dir / "01_Zwischenberichte").is_dir()
                else 0
            )
            m_count = (
                len(list((p_dir / "02_Medien").iterdir()))
                if (p_dir / "02_Medien").is_dir()
                else 0
            )
            e_count = len(list(end_dir.iterdir())) if end_dir.is_dir() else 0

            if proj_title == folder_name:
                clean_parts = [
                    p
                    for p in folder_name.split("-")
                    if not p.isdigit() and p not in ("projekt", "delegationsprojekt")
                ]
                proj_title = " ".join(clean_parts).title() or folder_name

            assignee_objs: List[Dict[str, Any]] = []
            approved_tools_set: set[str] = set(cadre_map.get(lead_agent, {}).get("tools") or [])
            for a in sorted(assignees):
                a_info = cadre_map.get(
                    a,
                    {
                        "id": a,
                        "person_name": a,
                        "role": "",
                        "display": a,
                        "avatar_url": f"/static/img/cadre_icons/{a}.png",
                        "tools": [],
                    },
                )
                assignee_objs.append(a_info)
                approved_tools_set.update(a_info.get("tools") or [])

            enriched_subtasks: List[Dict[str, Any]] = []
            proj_tokens = 0
            proj_cost = 0.0
            used_tools_set: set[Any] = set()
            subtask_dates: List[str] = []
            for st in subtasks:
                st_c = dict(st)
                asg = st_c.get("assignee") or ""
                a_info = cadre_map.get(
                    asg,
                    {
                        "id": asg,
                        "person_name": asg,
                        "role": "",
                        "display": asg,
                        "avatar_url": f"/static/img/cadre_icons/{asg}.png",
                    },
                )
                st_c["assignee_person_name"] = a_info["person_name"]
                st_c["assignee_title"] = a_info["role"]
                st_c["assignee_display"] = a_info["display"]
                st_c["assignee_avatar"] = a_info.get("avatar_url") or ""
                proj_tokens += int(st_c.get("tokens_total") or 0)
                proj_cost += float(st_c.get("cost_usd") or 0.0)
                used_tools_set.update(st_c.get("tools_used") or [])
                if st_c.get("created_at"):
                    subtask_dates.append(str(st_c["created_at"]))
                enriched_subtasks.append(st_c)

            folder_ts = p_dir.stat().st_mtime
            raw_created = min(subtask_dates) if subtask_dates else None
            created_ts, task_num, proj_created = _parse_ts_and_num(raw_created, folder_ts)

            projects.append({
                "id": folder_name,
                "title": proj_title,
                "status": status,
                "folder": f"01_PROJEKTE/{folder_name}",
                "created_at": proj_created,
                "created_ts": created_ts,
                "task_number": task_num,
                "lead_agent": lead_agent,
                "lead_agent_display": cadre_map.get(lead_agent, {}).get("display", lead_agent),
                "assignees": sorted(assignees),
                "assignee_objects": assignee_objs,
                "progress": progress,
                "tasks_total": t_total,
                "tasks_completed": t_done,
                "subtasks": enriched_subtasks,
                "total_tokens": proj_tokens,
                "total_cost_usd": round(proj_cost, 6),
                "approved_tools": sorted(approved_tools_set),
                "used_tools": sorted(used_tools_set),
                "primary_document": primary_doc,
                "has_html_report": has_html,
                "files_summary": {
                    "zwischenberichte": z_count,
                    "medien": m_count,
                    "endprodukte": e_count,
                },
            })

    for pid, t_list in tasks_by_project.items():
        if pid not in seen_ids:
            t_total = len(t_list)
            t_done = sum(1 for st in t_list if st.get("status") in ("done", "review", "completed"))
            progress = int((t_done / t_total) * 100) if t_total > 0 else 0
            asg_set = sorted({str(st.get("assignee")) for st in t_list if st.get("assignee")})
            assignee_objs = [
                cadre_map.get(
                    a,
                    {
                        "id": a,
                        "person_name": a,
                        "role": "",
                        "display": a,
                        "avatar_url": f"/static/img/cadre_icons/{a}.png",
                        "tools": [],
                    },
                )
                for a in asg_set
            ]
            approved_tools_set = set(cadre_map.get("executive_decision_architect", {}).get("tools") or [])
            for a_obj in assignee_objs:
                approved_tools_set.update(a_obj.get("tools") or [])
            enriched_subtasks = []
            proj_tokens = 0
            proj_cost = 0.0
            used_tools_set = set()
            subtask_dates = []
            for st in t_list:
                st_c = dict(st)
                asg = st_c.get("assignee") or ""
                a_info = cadre_map.get(
                    asg,
                    {
                        "id": asg,
                        "person_name": asg,
                        "role": "",
                        "display": asg,
                        "avatar_url": f"/static/img/cadre_icons/{asg}.png",
                    },
                )
                st_c["assignee_person_name"] = a_info["person_name"]
                st_c["assignee_title"] = a_info["role"]
                st_c["assignee_display"] = a_info["display"]
                st_c["assignee_avatar"] = a_info.get("avatar_url") or ""
                proj_tokens += int(st_c.get("tokens_total") or 0)
                proj_cost += float(st_c.get("cost_usd") or 0.0)
                used_tools_set.update(st_c.get("tools_used") or [])
                if st_c.get("created_at"):
                    subtask_dates.append(str(st_c["created_at"]))
                enriched_subtasks.append(st_c)

            now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
            raw_created = min(subtask_dates) if subtask_dates else None
            created_ts, task_num, proj_created = _parse_ts_and_num(raw_created, now_ts)

            projects.append({
                "id": pid,
                "title": pid.replace("projekt-", "").replace("-", " ").title(),
                "status": "planned" if progress == 0 else ("completed" if t_done == t_total else "in_progress"),
                "folder": f"01_PROJEKTE/{pid}",
                "created_at": proj_created,
                "created_ts": created_ts,
                "task_number": task_num,
                "lead_agent": "executive_decision_architect",
                "lead_agent_display": cadre_map.get("executive_decision_architect", {}).get("display", "Robert, CEO"),
                "assignees": asg_set,
                "assignee_objects": assignee_objs,
                "progress": progress,
                "tasks_total": t_total,
                "tasks_completed": t_done,
                "subtasks": enriched_subtasks,
                "total_tokens": proj_tokens,
                "total_cost_usd": round(proj_cost, 6),
                "approved_tools": sorted(approved_tools_set),
                "used_tools": sorted(used_tools_set),
                "primary_document": None,
                "has_html_report": False,
                "files_summary": {"zwischenberichte": 0, "medien": 0, "endprodukte": 0},
            })

    # Sidecar config/projects_meta.json mergen
    _projects_meta = load_projects_meta(deps.projects_meta_file)
    for p in projects:
        p["archived"] = False
        m = _projects_meta.get(p["id"])
        if not m:
            continue
        if m.get("description") is not None:
            p["description"] = m["description"]
        if m.get("goal") is not None:
            p["goal"] = m["goal"]
        if m.get("status") in ("in_progress", "completed", "planned"):
            p["status"] = m["status"]
        if m.get("lead_agent"):
            p["lead_agent"] = m["lead_agent"]
            p["lead_agent_display"] = cadre_map.get(m["lead_agent"], {}).get("display", m["lead_agent"])
        if m.get("archived") is not None:
            p["archived"] = bool(m["archived"])

    projects.sort(key=lambda x: float(x.get("created_ts") or 0.0), reverse=True)
    for idx, proj_item in enumerate(projects, start=1):
        proj_item["seq_number"] = idx

    active_projects = [p for p in projects if not p.get("archived")]
    archived_projects = [p for p in projects if p.get("archived")]

    return {
        "status": "success",
        "total": len(active_projects),
        "in_progress": [p for p in active_projects if p["status"] == "in_progress"],
        "completed": [p for p in active_projects if p["status"] == "completed"],
        "planned": [p for p in active_projects if p["status"] == "planned"],
        "archived": archived_projects,
        "all": projects,
        "cadre_options": [
            {"id": aid, "display": info.get("display", aid), "person_name": info.get("person_name", aid)}
            for aid, info in sorted(cadre_map.items())
        ],
    }


def update_project_meta_entry(
    project_id: str,
    upd: ProjectMetaUpdate,
    projects_meta_file: str,
) -> Dict[str, Any]:
    patch = {k: v for k, v in upd.model_dump().items() if v is not None and k in _PROJECTS_META_ALLOWED}
    if "status" in patch and patch["status"] not in ("in_progress", "completed", "planned"):
        raise HTTPException(status_code=422, detail="status muss in_progress|completed|planned sein.")
    with _PROJECTS_META_LOCK:
        data = load_projects_meta(projects_meta_file)
        entry = data.get(project_id) or {}
        entry.update(patch)
        data[project_id] = entry
        save_projects_meta(projects_meta_file, data)
    return {"status": "success", "project_id": project_id, "meta": entry}


def list_project_folder_files(project_id: str) -> Dict[str, Any]:
    """Listet alle Dateien des Projektordners 01_PROJEKTE/<id> im Obsidian-Vault (traversal-geschuetzt)."""
    from backend.post_task_pipeline import get_vault_dir

    vault = Path(get_vault_dir()).resolve()
    proj_root = (vault / "01_PROJEKTE").resolve()
    proj = (proj_root / project_id).resolve()
    if not proj.is_relative_to(proj_root):
        raise HTTPException(status_code=400, detail="Ungueltiger Projekt-Pfad.")
    if not proj.is_dir():
        return {"status": "success", "project_id": project_id, "folder": f"01_PROJEKTE/{project_id}", "files": []}
    files: List[Dict[str, Any]] = []
    for f in sorted(proj.rglob("*")):
        if f.is_file() and not f.name.startswith("."):
            files.append({
                "name": f.name,
                "path": str(f.relative_to(vault)).replace("\\", "/"),
                "dir": str(f.parent.relative_to(proj)).replace("\\", "/") or "Root",
                "size": f.stat().st_size,
            })
    return {"status": "success", "project_id": project_id, "folder": f"01_PROJEKTE/{project_id}", "files": files}


def list_kanban_project_files(task_id: str, deps: ProjectsDeps) -> Dict[str, Any]:
    """Listet die Dateien des verknuepften Obsidian-Projekts einer Task (Sidecar-Bruecke)."""
    from backend.post_task_pipeline import get_vault_dir

    meta = deps.load_kanban_meta()
    rel = resolve_task_obsidian_rel(task_id, deps, meta)
    if not rel:
        raise HTTPException(status_code=404, detail="Kein Obsidian-Projekt verknuepft.")
    vault = Path(get_vault_dir()).resolve()
    proj = (vault / rel).resolve()
    if not proj.is_relative_to(vault) or not proj.is_dir():
        raise HTTPException(status_code=404, detail=f"Projektordner fehlt: {rel}")
    files: List[Dict[str, Any]] = []
    for p in sorted(proj.rglob("*")):
        if p.is_file():
            relp = p.relative_to(proj)
            files.append({
                "path": relp.as_posix(),
                "name": p.name,
                "dir": relp.parent.as_posix() if str(relp.parent) != "." else "",
                "size": p.stat().st_size,
            })
    return {"task_id": task_id, "relative": rel, "project_dir": str(proj), "files": files}


def read_raw_original_response(path: str) -> Response:
    """'Original oeffnen' fuer systeminterne Pfade (/opt/data, /app) mit Traversal-Schutz."""
    from utils.path_jail import PathJailError, safe_path_within

    raw = (path or "").strip()
    p = Path(raw)
    if not p.is_absolute():
        raise HTTPException(status_code=400, detail="Absoluter Pfad erwartet (z.B. /opt/data/...).")
    try:
        resolved_str = safe_path_within(str(p), ["/opt/data", "/app"], must_exist=True, allow_dirs=False)
    except PathJailError as exc:
        msg = str(exc)
        if "existiert nicht" in msg:
            raise HTTPException(status_code=404, detail=f"Datei nicht gefunden: {raw}")
        raise HTTPException(
            status_code=403,
            detail="Nur systeminterne Pfade sind oeffenbar (/opt/data, /app). "
                   "Host-Dateien ausserhalb der Container-Binds: Pfad kopieren.",
        )
    rp = Path(resolved_str)
    try:
        data = rp.read_bytes()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lesen fehlgeschlagen: {e}")
    mime = mimetypes.guess_type(rp.name)[0] or "application/octet-stream"
    safe_cd_name = rp.name.replace('"', "").replace("\r", "").replace("\n", "")
    return Response(
        content=data,
        media_type=mime,
        headers={"Content-Disposition": f'inline; filename="{safe_cd_name}"'},
    )


def read_vault_file_text(path: str) -> Dict[str, Any]:
    """SYSTEMWEITER Datei-Reader: liefert EINE Vault-Datei (01_PROJEKTE/...) als Text."""
    from backend.post_task_pipeline import get_vault_dir
    from utils.path_jail import PathJailError, safe_path_within

    rel = path.strip().lstrip("/\\")
    vault = Path(get_vault_dir()).resolve()
    try:
        target = Path(safe_path_within(str(vault / rel), [str(vault)], must_exist=True, allow_dirs=False))
    except PathJailError:
        raise HTTPException(status_code=404, detail=f"Datei nicht gefunden: {rel}")
    if target.suffix.lower() not in (".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".html", ".log"):
        raise HTTPException(status_code=415, detail="Nur Textdateien (.md/.txt/...).")
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lesen fehlgeschlagen: {e}")
    return {"path": rel, "size": target.stat().st_size, "content": content}


def search_vault_files(q: str, limit: int = 8) -> Dict[str, Any]:
    """Findet Vault-Dateien per Name/Teilstring (fuer nackte .md-Namen aus Chat-Texten)."""
    from backend.post_task_pipeline import get_vault_dir

    q = (q or "").strip().lower()
    if not q or len(q) < 3:
        raise HTTPException(status_code=400, detail="Suchbegriff zu kurz.")
    vault = Path(get_vault_dir()).resolve()
    treffer: List[Dict[str, Any]] = []
    scanned = 0
    try:
        for raum in (vault / "01_PROJEKTE", vault):
            if treffer:
                break
            if not raum.is_dir():
                continue
            for p in raum.rglob("*.md"):
                scanned += 1
                if scanned > 2500:
                    break
                rel = p.relative_to(vault).as_posix()
                if q in p.name.lower() or q in rel.lower():
                    treffer.append({"path": rel, "name": p.name, "size": p.stat().st_size})
                    if len(treffer) >= limit:
                        break
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Suche fehlgeschlagen: {e}")
    return {"query": q, "files": treffer}


def read_kanban_project_file_text(task_id: str, path: str, deps: ProjectsDeps) -> Dict[str, Any]:
    """Liefert EINE Projektdatei als Text - nur innerhalb des Projektordners (Traversal-Schutz)."""
    from backend.post_task_pipeline import get_vault_dir
    from utils.path_jail import PathJailError, safe_path_within

    meta = deps.load_kanban_meta()
    rel = resolve_task_obsidian_rel(task_id, deps, meta)
    if not rel:
        raise HTTPException(status_code=404, detail="Kein Obsidian-Projekt verknuepft.")
    vault = Path(get_vault_dir()).resolve()
    try:
        proj = Path(safe_path_within(str(vault / rel), [str(vault)], allow_dirs=True))
    except PathJailError:
        raise HTTPException(status_code=400, detail="Pfad ausserhalb des Vaults.")
    try:
        target = Path(safe_path_within(str(proj / path), [str(proj)], must_exist=True, allow_dirs=False))
    except PathJailError:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden.")
    if target.suffix.lower() not in (".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".html", ".log"):
        raise HTTPException(status_code=415, detail="Nur Textdateien (.md/.txt/.csv/...).")
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lesen fehlgeschlagen: {e}")
    return {"task_id": task_id, "path": path, "size": target.stat().st_size, "content": content}
