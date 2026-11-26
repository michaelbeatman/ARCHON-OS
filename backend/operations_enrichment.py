"""Enrichment-, Profil- und Obsidian-Batch-Helfer fuer Operations API (D3/7).

Kapselt die zeitstempel-, profil-, avatar-, fuzzy-projekt- und
Obsidian-Zuordnungshelfer aus ``backend/operations_api.py`` per
S3-Call-Time-Injektion (``register_enrichment_deps_provider``), damit
``backend/operations_api.py`` keinen Rueckimport erzeugt und bestehende
Test-Monkeypatches (z. B. ``PROFILES_FILE``, ``_load_kanban_meta``) greifen.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path as _P
from typing import Any, Callable, Dict, List, NamedTuple, Optional


class EnrichmentDeps(NamedTuple):
    profiles_file: str
    load_kanban_meta: Callable[[], Dict[str, Any]]
    get_fallback_avatar: Callable[[str], str]
    resolve_task_obsidian_rel: Callable[..., Optional[str]]


_DEPS_PROVIDER: Optional[Callable[[], EnrichmentDeps]] = None


def register_enrichment_deps_provider(
    provider: Callable[[], EnrichmentDeps],
) -> None:
    """Registriert den Call-Time-Dependency-Provider aus operations_api.py (S3)."""
    global _DEPS_PROVIDER
    _DEPS_PROVIDER = provider


def _deps() -> EnrichmentDeps:
    if _DEPS_PROVIDER is None:
        raise RuntimeError(
            "EnrichmentDeps provider not registered "
            "(call register_enrichment_deps_provider first)"
        )
    return _DEPS_PROVIDER()


_PROFILES_MAP_CACHE: Dict[str, Any] = {"mtime": 0.0, "data": {}}


def _parse_kanban_ts(value: Any) -> Optional[float]:
    """Wandelt einen Kanban-Zeitstempel in Epoch-Sekunden um.

    Das Modul schreibt ISO-Strings (``datetime.now().isoformat()``), aeltere
    Zeilen koennen aber auch float-Epochs enthalten. Fuer die KPI-Berechnung
    (R-20/F-01) ist beides noetig — ``float('2026-11-08T09:00:00')`` wirft
    sonst ValueError und die KPIs bleiben dauerhaft leer.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    try:
        return float(s)
    except (TypeError, ValueError) as exc:
        print(
            f"[OperationsAPI] Fallback _parse_kanban_ts: Exception im Fehler-/Fallback-Pfad: {exc}",
            file=sys.stderr,
        )
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.datetime.fromisoformat(s).timestamp()
    except (TypeError, ValueError):
        return None


def _sync_to_memory_bridge(
    task_id: str,
    title: Optional[str],
    assignee: Optional[str],
    status: str,
    result: Optional[str] = None,
) -> None:
    """Synchronisiert Kanban-Aufgaben mit der zentralen agentic_memory.db (tasks-Tabelle)."""
    d = _deps()
    try:
        from local_memory_bridge import memory_bridge

        obsidian_rel = None
        try:
            meta = d.load_kanban_meta()
            obsidian_rel = ((meta.get("tasks") or {}).get(task_id) or {}).get("obsidian")
        except Exception as exc:
            print(
                f"[OperationsAPI] WARNUNG (MEDIUM) _sync_to_memory_bridge: Exception im Fehler-/Fallback-Pfad: {exc}",
                file=sys.stderr,
            )
        memory_bridge.sync_task(
            task_id=task_id,
            title=title or task_id,
            role=assignee or "unassigned",
            status=status,
            result=result,
            obsidian_note=obsidian_rel,
        )
    except Exception as e:
        print(f"[OperationsAPI] MemoryBridge task sync notice: {e}", file=sys.stderr)


def _load_profiles_map() -> Dict[str, Dict[str, Any]]:
    d = _deps()
    profiles_file = d.profiles_file
    if os.path.exists(profiles_file):
        try:
            mtime = os.path.getmtime(profiles_file)
            if _PROFILES_MAP_CACHE["data"] and _PROFILES_MAP_CACHE["mtime"] == mtime:
                return _PROFILES_MAP_CACHE["data"]
            profiles: Dict[str, Dict[str, Any]] = {}
            with open(profiles_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    profiles[item.get("id")] = item
            _PROFILES_MAP_CACHE["mtime"] = mtime
            _PROFILES_MAP_CACHE["data"] = profiles
            return profiles
        except Exception as e:
            print(f"[OperationsAPI] Error loading profiles: {e}", file=sys.stderr)
    # Audit v3 2.1.4: profile.yaml/SOUL.md des Profilordners als Ergänzung einlesen,
    # damit Profile die NUR dort existieren nicht unsichtbar bleiben.
    try:
        import yaml as _yaml

        from archon.core.profiles import get_primary_hermes_profiles_dir

        base = get_primary_hermes_profiles_dir()
        if os.path.isdir(base):
            _map: Dict[str, Dict[str, Any]] = _PROFILES_MAP_CACHE["data"]
            for pid in os.listdir(base):
                pdir = os.path.join(base, pid)
                if not os.path.isdir(pdir) or pid.startswith("."):
                    continue
                entry = dict(_map.get(pid) or {})
                ypath = os.path.join(pdir, "profile.yaml")
                if os.path.exists(ypath):
                    try:
                        with open(ypath, "r", encoding="utf-8") as f:
                            ydata = _yaml.safe_load(f) or {}
                        for k in (
                            "name",
                            "person_name",
                            "category",
                            "model",
                            "tools",
                            "skills",
                            "status",
                        ):
                            v = ydata.get(k)
                            if v is not None and k not in entry:
                                entry[k] = v
                    except Exception as exc:
                        print(
                            f"[OperationsAPI] profile.yaml {pid} unlesbar: {exc}",
                            file=sys.stderr,
                        )
                spath = os.path.join(pdir, "SOUL.md")
                if os.path.exists(spath) and not entry.get("prompt"):
                    try:
                        with open(spath, "r", encoding="utf-8", errors="ignore") as f:
                            entry["prompt"] = f.read().strip()
                    except OSError:
                        pass
                if entry:
                    _map.setdefault(pid, entry)
    except Exception as exc:
        print(
            f"[OperationsAPI] profile.yaml-Ergänzung fehlgeschlagen: {exc}",
            file=sys.stderr,
        )
    return _PROFILES_MAP_CACHE["data"]


def _get_fallback_avatar(aid: str) -> str:
    if not aid:
        return "/static/avatars/avatar_002.jpg"
    h = int(hashlib.sha256(str(aid).encode("utf-8")).hexdigest(), 16) % 108 + 1
    if h == 1:
        h = 2
    return f"/static/avatars/avatar_{h:03d}.jpg"


def _fuzzy_project_exact_match(
    needle: str, folder_names: List[Any]
) -> Optional[str]:
    """Fix-Sprint Paket A (Punkt 9): exakter Match zuerst; Substring-Match nur
    bei Mindestlaenge >= 4 UND eindeutigem Treffer (genau 1), sonst kein Match
    plus sichtbarer Log-Hinweis."""
    n = str(needle or "").strip()
    if not n:
        return None
    for name in folder_names:
        if name == n:
            return str(name)
    if len(n) < 4:
        if n:
            print(
                f"[OperationsAPI] Hinweis: Fuzzy-Projekt-Match für '{n}' abgelehnt (Mindestlänge 4 unterschritten).",
                file=sys.stderr,
            )
        return None
    subs = [name for name in folder_names if n in name]
    if len(subs) == 1:
        return str(subs[0])
    if len(subs) > 1:
        print(
            f"[OperationsAPI] Hinweis: Fuzzy-Projekt-Match für '{n}' mehrdeutig ({len(subs)} Treffer) — kein Match.",
            file=sys.stderr,
        )
    return None


def _build_kanban_obsidian_map(
    conn: sqlite3.Connection, rows: List[Any], meta: Dict[str, Any]
) -> Dict[str, Optional[str]]:
    """Loest alle Obsidian-Projektordner fuer ein Kanban-Board einmalig im Batch auf (statt O(N) DB/FS-Scans)."""
    from backend.post_task_pipeline import get_vault_dir

    result: Dict[str, Optional[str]] = {}
    meta_tasks = meta.get("tasks") or {}
    vault = _P(get_vault_dir()).resolve()
    proj_root = vault / "01_PROJEKTE"

    # Einmalig alle Projektordner & bekannte Artefakt-Dateinamen einlesen
    proj_dirs: List[_P] = []
    if proj_root.is_dir():
        try:
            for d in proj_root.iterdir():
                if d.is_dir():
                    proj_dirs.append(d)
        except Exception:
            proj_dirs = []
    valid_proj_names = {d.name for d in proj_dirs}

    # Einmalig Parent-Child-Verknuepfungen laden
    parent_by_child: Dict[str, str] = {}
    try:
        for child_id, parent_id in conn.execute(
            "SELECT child_id, parent_id FROM task_links WHERE COALESCE(kind, 'subtask') = 'subtask'"
        ).fetchall():
            if child_id and parent_id and child_id != parent_id and child_id not in parent_by_child:
                parent_by_child[child_id] = parent_id
    except Exception as exc:
        print(
            f"[OperationsAPI] WARNUNG (MEDIUM) _build_kanban_obsidian_map: Exception im Fehler-/Fallback-Pfad: {exc}",
            file=sys.stderr,
        )

    # Einmalig Endprodukte/Zwischenberichte nach Task-IDs durchsuchen, falls noetig
    file_hits: Dict[str, str] = {}
    for p_dir in proj_dirs:
        rel_p = f"01_PROJEKTE/{p_dir.name}"
        for sub in ("03_Endprodukte", "01_Zwischenberichte"):
            s_dir = p_dir / sub
            if s_dir.is_dir():
                try:
                    for f in s_dir.iterdir():
                        fname = f.name
                        file_hits[fname] = rel_p
                except Exception as exc:
                    print(
                        f"[OperationsAPI] Fallback _build_kanban_obsidian_map: Exception im Fehler-/Fallback-Pfad: {exc}",
                        file=sys.stderr,
                    )

    proj_slug_parts: List[tuple[str, str, List[str]]] = []
    for p_dir in proj_dirs:
        parts = [
            pt
            for pt in p_dir.name.lower().split("-")
            if len(pt) >= 4 and pt not in ("projekt", "delegationsprojekt", "2026")
        ]
        proj_slug_parts.append((f"01_PROJEKTE/{p_dir.name}", p_dir.name, parts))

    row_by_id: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        rd = dict(r)
        tid = rd.get("id")
        if tid:
            row_by_id[str(tid)] = rd

    def _resolve_one(tid: str, depth: int = 0) -> Optional[str]:
        if tid in result:
            return result[tid]
        if depth > 4:
            return None
        t_entry = meta_tasks.get(tid) or {}
        rel = t_entry.get("obsidian")
        if rel and str(rel).strip():
            rel_s = str(rel).strip()
            if rel_s.startswith("01_PROJEKTE/") and rel_s.split("/", 2)[1] in valid_proj_names:
                result[tid] = rel_s
                return rel_s
            cand = (vault / rel_s).resolve()
            if str(cand).startswith(str(vault)) and cand.is_dir():
                result[tid] = rel_s
                return rel_s

        dossier = (t_entry.get("decision") or {}).get("dossier") or ""
        if "01_PROJEKTE/" in dossier:
            sub = dossier.split("01_PROJEKTE/")[1].split("/")[0]
            if sub in valid_proj_names:
                rel_s = f"01_PROJEKTE/{sub}"
                result[tid] = rel_s
                return rel_s

        pid_parent = parent_by_child.get(tid)
        if pid_parent:
            p_rel = _resolve_one(pid_parent, depth + 1)
            if p_rel:
                result[tid] = p_rel
                return p_rel

        rd = row_by_id.get(tid) or {}
        proj_id = rd.get("project_id")
        if proj_id:
            _pl = str(proj_id).strip()
            exact = next((sp for sp in proj_slug_parts if sp[1] == _pl), None)
            if exact:
                result[tid] = exact[0]
                return exact[0]
            if len(_pl) >= 4:
                subs = [sp for sp in proj_slug_parts if _pl in sp[1]]
                if len(subs) == 1:
                    result[tid] = subs[0][0]
                    return subs[0][0]
                if len(subs) > 1:
                    print(
                        f"[OperationsAPI] Hinweis: Fuzzy-Projekt-Match für '{_pl}' mehrdeutig ({len(subs)} Treffer) — kein Match.",
                        file=sys.stderr,
                    )

        _tid_hits = [sp for sp in proj_slug_parts if len(tid) >= 4 and tid in sp[1]]
        if len(_tid_hits) == 1:
            result[tid] = _tid_hits[0][0]
            return _tid_hits[0][0]
        if len(_tid_hits) > 1:
            print(
                f"[OperationsAPI] Hinweis: Fuzzy-Projekt-Match für Task-ID '{tid}' mehrdeutig ({len(_tid_hits)} Treffer) — kein Match.",
                file=sys.stderr,
            )

        for fname, rel_p in file_hits.items():
            if tid in fname:
                result[tid] = rel_p
                return rel_p

        combined = ((rd.get("title") or "") + " " + (rd.get("body") or "")).lower()
        if combined.strip():
            for rel_p, _dname, parts in proj_slug_parts:
                if any(pt in combined for pt in parts):
                    result[tid] = rel_p
                    return rel_p

        result[tid] = None
        return None

    for tid in list(row_by_id.keys()):
        _resolve_one(tid)
    return result


def _enrich_task(
    task_dict: Dict[str, Any],
    profiles: Dict[Any, Any],
    meta: Dict[str, Any],
    obsidian_map: Optional[Dict[str, Optional[str]]] = None,
) -> Dict[str, Any]:
    d = _deps()
    assignee_id = task_dict.get("assignee")
    prof = profiles.get(assignee_id, {})
    task_dict["assignee_name"] = prof.get("name") or assignee_id or "Nicht zugewiesen"
    task_dict["assignee_role"] = prof.get("category") or prof.get("role") or "Spezialist"
    task_dict["assignee_avatar"] = prof.get("avatar") or d.get_fallback_avatar(assignee_id or "")
    tmeta = (meta.get("tasks") or {}).get(task_dict.get("id")) or {}
    task_dict["due_date"] = tmeta.get("due") or None
    task_dict["tags"] = tmeta.get("tags") or []
    tid = task_dict.get("id")
    if obsidian_map is not None:
        task_dict["obsidian"] = obsidian_map.get(tid)  # type: ignore[arg-type]
    else:
        task_dict["obsidian"] = d.resolve_task_obsidian_rel(tid, meta)
    task_dict["tokens"] = tmeta.get("tokens") or None
    task_dict["cost"] = tmeta.get("cost") or None
    task_dict["quality_review"] = tmeta.get("quality_review") or None
    task_dict["soul_mode"] = tmeta.get("soul_mode") or None
    task_dict["reasoning_effort"] = tmeta.get("reasoning_effort") or None
    task_dict["tool_preset"] = tmeta.get("tool_preset") or None
    task_dict["token_budget"] = tmeta.get("token_budget") or None
    task_dict["cost_limit_usd"] = tmeta.get("cost_limit_usd") or None
    task_dict["require_hitl"] = bool(tmeta.get("require_hitl"))
    task_dict["cron_schedule"] = tmeta.get("cron_schedule") or None
    task_dict["depends_on"] = tmeta.get("depends_on") or None
    task_dict["trusted_input"] = bool(tmeta.get("trusted_input"))
    _dec = tmeta.get("decision") or None
    task_dict["decision"] = (
        {
            "typ": _dec.get("typ"),
            "status": _dec.get("status") or "offen",
            "titel": _dec.get("titel"),
        }
        if isinstance(_dec, dict)
        else None
    )
    return task_dict
