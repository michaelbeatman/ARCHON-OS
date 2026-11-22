# -*- coding: utf-8 -*-
"""
backend/workflow_dag_runner.py
==============================
Meilenstein 77: Agenten-Workflow-DAGs mit Fan-Out/Quorum, Edge-Bedingungen,
Datenfluss-Modi, HITL-Gates, Kanban-Synchronisation & Resume.

Unterstuetzt:
- JSON-DAGs mit `agent`, `fanout` (mit Quorum), `gate` (HITL-Gate) und `require_hitl`
- Kanten-Bedingungen (`always`, `on_success`, `on_failure`) & Datenfluss-Modi
  (`full`, `summary`, `artifact_only`, `none`)
- Parallele Ausfuehrung bereiter Knoten mit Retry- und Timeout-Limits
- Live-Kanban-Status-Synchronisation fuer materialisierte Workflow-Tasks
- Persistentes Fingerprint-basiertes Replay-Skip-Resume ueber SQLite WAL (data/workflow_dags.db)
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import datetime
import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from typing import Any, Awaitable, Callable, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger("archon.workflow_dag")


async def _otel_start(name: str, run_id: str) -> Optional[str]:
    try:
        from backend.otel_tracer import tracer
        return await asyncio.to_thread(tracer.start_trace, name, run_id, "workflow_engine")
    except Exception as exc:
        logger.debug("[WorkflowDAG] OTel-Trace-Start fehlgeschlagen: %s", exc)
        return None


async def _otel_span(trace_id: str, **kwargs: Any) -> None:
    try:
        from backend.otel_tracer import tracer
        await asyncio.to_thread(tracer.record_span, trace_id, **kwargs)
    except Exception as exc:
        logger.debug("[WorkflowDAG] OTel-Span fehlgeschlagen: %s", exc)


async def _otel_end(trace_id: str, status: str) -> None:
    try:
        from backend.otel_tracer import tracer
        await asyncio.to_thread(tracer.end_trace, trace_id, status)
    except Exception as exc:
        logger.debug("[WorkflowDAG] OTel-Trace-Ende fehlgeschlagen: %s", exc)


# M110: harter Deckel für Replans — ein Agent darf nicht unbegrenzt neu
# planen und damit Budget/Deadline endlos umgehen.
MAX_REPLAN_COUNT = 2

_PRIVILEGED_NODE_TOOLS = frozenset({
    "pay", "terminal", "execute_code", "filesystem", "computer_use", "mcp", "pay-cli",
})


def validate_dag_def(
    dag_def: Dict[str, Any],
    *,
    now: Optional[float] = None,
    max_nodes: int = 100,
) -> Dict[str, Any]:
    """M110 Pre-Execution Plan Validator.

    Prüft Schema, Zyklen, Input-Mapping, Budget, Deadline, RBAC/HITL und
    Replan-Count, BEVOR irgendein Node ausgeführt wird. Fehler sind immer
    `valid=False` mit klarer Diagnose (nie stilles Weiterlaufen).
    """
    errors: List[str] = []
    nodes = dag_def.get("nodes") or []
    if not isinstance(nodes, list) or not nodes:
        return {"valid": False, "errors": ["DAG enthält keine Nodes."]}
    if len(nodes) > max_nodes:
        errors.append(f"Zu viele Nodes: {len(nodes)} > {max_nodes}")

    node_map: Dict[str, Dict[str, Any]] = {}
    for n in nodes:
        if not isinstance(n, dict) or not n.get("id"):
            errors.append("Node ohne id oder falscher Typ.")
            continue
        nid = str(n["id"])
        if nid in node_map:
            errors.append(f"Doppelte Node-ID: {nid}")
        node_map[nid] = n

    edge_map = _extract_edge_map(dag_def)
    for src, targets in edge_map.items():
        if src not in node_map:
            errors.append(f"Kante von unbekannter Quelle: {src}")
        for e in targets or []:
            dst = str(e.get("to") or "")
            if dst and dst not in node_map:
                errors.append(f"Kante zu unbekanntem Ziel: {dst}")

    # Zyklus-Erkennung via Kahn — vor dem Start, nicht als Restgröße.
    deps: Dict[str, set] = {}
    for nid, node in node_map.items():
        deps[nid] = {
            str(d) for d in _all_dependencies_for_node(node, edge_map.get(nid, []))
        }
        for d in deps[nid]:
            if d not in node_map:
                errors.append(f"Unbekannte Abhängigkeit '{d}' bei Node '{nid}'")
    remaining = set(node_map)
    progress = True
    while remaining and progress:
        progress = False
        for nid in sorted(remaining):
            if not (deps.get(nid, set()) & remaining):
                remaining.discard(nid)
                progress = True
    if remaining:
        errors.append(f"Zyklus in DAG erkannt: {', '.join(sorted(remaining))}")

    # Input-Mapping: {{upstream.<node>.<field>}} nur aus deklarierten Deps.
    ref_re = re.compile(r"\{\{\s*upstream\.([A-Za-z0-9_-]+)\.")
    for nid, node in node_map.items():
        blob = json.dumps(node, ensure_ascii=False)
        for ref in set(ref_re.findall(blob)):
            if ref not in deps.get(nid, set()):
                errors.append(f"Node '{nid}' referenziert '{ref}', das keine deklarierte Abhängigkeit ist.")

    # Budget: Summe der Node-Caps gegen den Run-Cap.
    cap = dag_def.get("max_budget_eur")
    if cap is not None:
        try:
            total = sum(
                float(n.get("max_budget_eur") or 0.0)
                for n in node_map.values()
            )
            if total > float(cap) * 1.15:
                errors.append(f"Node-Budgets ({total:.2f} EUR) überschreiten Run-Cap ({float(cap):.2f} EUR).")
        except (TypeError, ValueError):
            errors.append("Ungültiger max_budget_eur-Wert.")

    # Deadline
    deadline = dag_def.get("deadline")
    if deadline:
        try:
            dl = datetime.datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
            if dl.timestamp() <= (now if now is not None else time.time()):
                errors.append("Deadline liegt in der Vergangenheit.")
        except (TypeError, ValueError):
            errors.append("Ungültige Deadline.")

    # RBAC/HITL: privilegierte Tools brauchen ein Gate.
    has_gate = any(
        str(n.get("type") or "").lower() in ("gate", "require_hitl") or n.get("require_hitl")
        for n in node_map.values()
    )
    for nid, node in node_map.items():
        tool = str(node.get("tool") or node.get("plugin_id") or "")
        if any(tool.lower().startswith(p) for p in _PRIVILEGED_NODE_TOOLS):
            if not has_gate and not node.get("require_hitl"):
                errors.append(f"Node '{nid}' nutzt privilegiertes Tool '{tool}' ohne HITL-Gate.")

    # Replan-Cap
    replan_count = int(dag_def.get("_replan_count") or 0)
    if replan_count > MAX_REPLAN_COUNT:
        errors.append(f"replan_count {replan_count} überschreitet den Deckel ({MAX_REPLAN_COUNT}).")

    return {"valid": not errors, "errors": errors, "node_count": len(node_map)}


def request_dag_replan(
    run_id: str,
    new_dag_def: Dict[str, Any],
    reason: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Kontrollierter Replan-Pfad — nur bis MAX_REPLAN_COUNT."""
    existing = get_workflow_run(run_id, db_path=db_path)
    if not existing:
        return {"allowed": False, "reason": "run_not_found"}
    count = int((existing.get("dag") or {}).get("_replan_count") or 0)
    if count >= MAX_REPLAN_COUNT:
        return {"allowed": False, "reason": "replan_cap_reached", "replan_count": count}
    candidate = dict(new_dag_def or {})
    candidate["_replan_count"] = count + 1
    candidate["_replan_reason"] = str(reason or "")[:500]
    validation = validate_dag_def(candidate)
    if not validation["valid"]:
        return {"allowed": False, "reason": "invalid_plan", "errors": validation["errors"]}
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE workflow_runs SET dag_json = ?, updated_at = ? WHERE run_id = ?",
            (json.dumps(candidate, ensure_ascii=False), time.time(), run_id),
        )
        conn.commit()
    return {"allowed": True, "replan_count": count + 1, "dag_def": candidate}


WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(WORKSPACE_DIR, "data", "workflow_dags.db")
_INITIAL_DEFAULT_DB_PATH = DEFAULT_DB_PATH

ExecutorFn = Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[Dict[str, Any]]]

TERMINAL_NODE_STATES = {"completed", "skipped_cached", "skipped_condition", "failed", "rejected"}
SUCCESS_NODE_STATES = {"completed", "skipped_cached"}
FAILURE_NODE_STATES = {"failed", "rejected"}

# Per-run_id-Locks: verhindert doppelte/parallele Ausfuehrung desselben Runs.
# Erzeugung neuer Locks geschuetzt ueber threading.Lock (Sync-Kontext, async-sicher).
_RUN_LOCKS: Dict[str, asyncio.Lock] = {}
_locks_guard = threading.Lock()
_MAX_RUN_LOCKS = 512


def _get_run_lock(run_id: str) -> asyncio.Lock:
    with _locks_guard:
        lock = _RUN_LOCKS.get(run_id)
        if lock is None:
            if len(_RUN_LOCKS) >= _MAX_RUN_LOCKS:
                for k in list(_RUN_LOCKS.keys()):
                    if not _RUN_LOCKS[k].locked():
                        _RUN_LOCKS.pop(k, None)
                        if len(_RUN_LOCKS) < _MAX_RUN_LOCKS:
                            break
            lock = asyncio.Lock()
            _RUN_LOCKS[run_id] = lock
        return lock


def _resolve_dag_db_path(db_path: Optional[str] = None) -> str:
    if db_path:
        return db_path
    if DEFAULT_DB_PATH != _INITIAL_DEFAULT_DB_PATH:
        return DEFAULT_DB_PATH
    try:
        from backend.db_paths import resolve_db
        return resolve_db("workflow_dags.db")
    except Exception:
        return DEFAULT_DB_PATH


@contextmanager
def _connect(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    path = _resolve_dag_db_path(db_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workflow_runs (
                run_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                status TEXT NOT NULL,
                dag_json TEXT DEFAULT '{}',
                gate_approvals_json TEXT DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workflow_node_states (
                run_id TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                output_json TEXT DEFAULT '{}',
                updated_at REAL NOT NULL
            )
        """) if False else conn.execute("""
            CREATE TABLE IF NOT EXISTS workflow_node_states (
                run_id TEXT NOT NULL,
                node_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                output_json TEXT DEFAULT '{}',
                updated_at REAL NOT NULL,
                PRIMARY KEY (run_id, node_id)
            )
        """)
        # Sichere Migration fuer bestehende workflow_dags.db ohne dag_json / gate_approvals_json
        run_cols = {r[1] for r in conn.execute("PRAGMA table_info(workflow_runs)").fetchall()}
        if "dag_json" not in run_cols:
            conn.execute("ALTER TABLE workflow_runs ADD COLUMN dag_json TEXT DEFAULT '{}'")
        if "gate_approvals_json" not in run_cols:
            conn.execute("ALTER TABLE workflow_runs ADD COLUMN gate_approvals_json TEXT DEFAULT '{}'")
        if "total_cost_usd" not in run_cols:
            conn.execute("ALTER TABLE workflow_runs ADD COLUMN total_cost_usd REAL DEFAULT 0.0")
        conn.commit()
        yield conn
    finally:
        conn.close()


def compute_node_fingerprint(node: Dict[str, Any], upstream_outputs: Dict[str, Any]) -> str:
    # Transiente Laufzeit-Metadaten fuer stabilen Cache-Fingerprint ignorieren
    stable_node = {
        k: v for k, v in (node or {}).items()
        if k not in ("kanban_task_id", "_edge_inputs")
    }
    payload = json.dumps({"node": stable_node, "upstream": upstream_outputs}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _extract_edge_map(dag_def: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Ordnet jedem Ziel-Knoten seine eingehenden Kanten zu."""
    incoming: Dict[str, List[Dict[str, Any]]] = {}
    for edge in (dag_def.get("edges") or []):
        if not isinstance(edge, dict):
            continue
        src = str(edge.get("from") or edge.get("source") or "").strip()
        dst = str(edge.get("to") or edge.get("target") or "").strip()
        if not src or not dst:
            continue
        incoming.setdefault(dst, []).append({
            "from": src,
            "to": dst,
            "condition": str(edge.get("condition") or "always").strip().lower(),
            "data_mode": str(edge.get("data_mode") or "full").strip().lower(),
            "label": str(edge.get("label") or "").strip(),
        })
    return incoming


def _all_dependencies_for_node(node: Dict[str, Any], incoming_edges: List[Dict[str, Any]]) -> List[str]:
    deps: List[str] = []
    for d in (node.get("depends_on") or []):
        ds = str(d).strip()
        if ds and ds not in deps:
            deps.append(ds)
    for e in incoming_edges:
        src = e["from"]
        if src and src not in deps:
            deps.append(src)
    return deps


def _edge_condition_matches(condition: str, parent_status: str) -> bool:
    cond = (condition or "always").strip().lower()
    if cond in ("on_failure", "failed", "error"):
        return parent_status in FAILURE_NODE_STATES
    if cond in ("on_success", "success"):
        return parent_status in SUCCESS_NODE_STATES
    # Default "always": bereit sobald der Upstream IRGENDEINEN Terminal-Status
    # erreicht hat (completed, skipped_cached, failed, rejected, skipped_condition)
    return parent_status in TERMINAL_NODE_STATES


def _shape_upstream_output(raw_out: Any, data_mode: str) -> Any:
    mode = (data_mode or "full").strip().lower()
    if mode == "none":
        if isinstance(raw_out, dict):
            return {"status": raw_out.get("status", "success")}
        return {"status": "success"}
    if mode == "artifact_only":
        if isinstance(raw_out, dict):
            return {
                "status": raw_out.get("status", "success"),
                "artifacts": raw_out.get("artifacts") or raw_out.get("files") or [],
                "obsidian_path": raw_out.get("obsidian_path") or "",
            }
        return {"artifacts": []}
    if mode == "summary":
        if isinstance(raw_out, dict):
            txt = str(raw_out.get("content") or raw_out.get("result") or json.dumps(raw_out, ensure_ascii=False))
            return {
                "status": raw_out.get("status", "success"),
                "summary": txt[:1200],
            }
        return {"summary": str(raw_out or "")[:1200]}
    return raw_out


def _update_kanban_task_status(
    task_id: Optional[str],
    status: str,
    *,
    result: Optional[str] = None,
    block_kind: Optional[str] = None,
    event_kind: Optional[str] = None,
    event_payload: Optional[Dict[str, Any]] = None,
) -> None:
    if not task_id:
        return
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    # Ein transienter SQLite-Lock (z. B. paralleler Task-Write) darf den Kanban-Sync
    # NICHT still schlucken — sonst bleibt ein wartender Gate-Task sichtbar falsch.
    # Deshalb: 1 Retry mit kurzem Backoff, erst danach sichtbarer DEBUG-Log.
    last_exc: Exception = RuntimeError("nicht ausgefuehrt")
    for _attempt in range(2):
        try:
            from backend.operations_api import _get_kanban_connection

            conn = _get_kanban_connection()
            try:
                if status == "in_progress":
                    conn.execute(
                        "UPDATE tasks SET status = 'in_progress', started_at = COALESCE(started_at, ?) WHERE id = ?",
                        (now_iso, task_id),
                    )
                elif status == "done":
                    conn.execute(
                        "UPDATE tasks SET status = 'done', completed_at = ?, result = ?, block_kind = NULL WHERE id = ?",
                        (now_iso, (result or "")[:12000], task_id),
                    )
                elif status in ("blocked", "failed", "review"):
                    conn.execute(
                        "UPDATE tasks SET status = ?, result = COALESCE(?, result), block_kind = COALESCE(?, block_kind) WHERE id = ?",
                        (status, (result or "")[:12000] if result is not None else None, block_kind, task_id),
                    )
                else:
                    conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))

                if event_kind:
                    conn.execute(
                        "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                        (task_id, event_kind, json.dumps(event_payload or {}, ensure_ascii=False), now_iso),
                    )
                conn.commit()
            finally:
                conn.close()
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            if _attempt == 0:
                time.sleep(0.5)
    if last_exc is not None:
        logger.debug(f"[WorkflowDAG] Kanban-Sync fuer {task_id} fehlgeschlagen (2 Versuche): {last_exc}")

    try:
        from archon.core.runtime import broadcast_event
        broadcast_event("kanban_updated", {"action": "workflow_node", "task_id": task_id, "status": status})
    except Exception as exc:
        logger.debug(f"[WorkflowDAG] broadcast_event fuer {task_id} fehlgeschlagen (Fallback): {exc}")


def _register_hitl_gate_decision(
    run_id: str,
    wf_id: str,
    node: Dict[str, Any],
    upstream: Dict[str, Any],
    db_path: Optional[str] = None,
) -> Optional[str]:
    node_id = str(node.get("id") or "")
    # Doppelte HITL-Decisions verhindern: falls fuer (run_id, node_id) bereits
    # eine Decision existiert, diese wiederverwenden statt neu anzulegen.
    try:
        with _connect(db_path) as conn:
            row = conn.execute(
                "SELECT output_json FROM workflow_node_states WHERE run_id = ? AND node_id = ?",
                (run_id, node_id),
            ).fetchone()
        if row:
            prev_out = json.loads(row["output_json"] or "{}")
            prev_id = prev_out.get("decision_id")
            if prev_id:
                return str(prev_id)
    except Exception as exc:
        logger.debug(f"[WorkflowDAG] HITL-Decision-Dedupe-Check fehlgeschlagen: {exc}")
    try:
        from archon.routers.decisions import create_decision
        title = f"Workflow-Freigabe: {node.get('title') or node.get('id')} ({run_id})"
        upstream_preview = json.dumps(upstream, ensure_ascii=False)[:1500]
        deci = create_decision(
            "workflow_hitl_gate",
            title,
            f"Workflow '{wf_id}' (Run `{run_id}`) wartet am Knoten `{node.get('id')}` auf Freigabe.\n\nVorlauf-Ergebnisse:\n{upstream_preview}",
            ref_id=f"{run_id}:{node.get('id')}",
        )
        if isinstance(deci, dict):
            return str(deci.get("id") or deci.get("task_id") or "")
    except Exception as exc:
        logger.debug(f"[WorkflowDAG] HITL-Decision konnte nicht angelegt werden: {exc}")
    return None


async def default_agent_node_executor(node: Dict[str, Any], upstream: Dict[str, Any]) -> Dict[str, Any]:
    """Echter Standard-Executor fuer DAG-Knoten: loest Agenten-Profil auf, reicht
    Upstream-Outputs weiter, ruft core_dispatcher auf und synchronisiert Kanban."""
    import core_dispatcher
    from backend.agent_aliases import resolve_agent_id

    raw_agent = str(node.get("agent_id") or node.get("branch") or "default").strip()
    agent_id = resolve_agent_id(raw_agent)
    kanban_task_id = node.get("kanban_task_id")

    # Agenten-Profil laden
    prof: Dict[str, Any] = {}
    try:
        from archon.core.profiles import api_get_hermes_profiles
        profiles = await asyncio.to_thread(api_get_hermes_profiles) or []
        prof = next((p for p in profiles if p.get("id") == agent_id), {})
    except Exception:
        prof = {}

    node_type = str(node.get("type") or "agent").strip().lower()
    kanban_task_id = node.get("kanban_task_id")

    # Standardisierte Node-Plugins ("VST-Schnittstelle": ffmpeg, kinocut, tts, suno, image_gen, calendar_publish, 3rd-Party)
    from backend.workflow_node_plugins import is_workflow_node_plugin, execute_workflow_node_plugin
    if is_workflow_node_plugin(node_type):
        await asyncio.to_thread(
            _update_kanban_task_status,
            kanban_task_id,
            "in_progress",
            event_kind="workflow_node_started",
            event_payload={"node_id": node.get("id"), "type": node_type},
        )
        try:
            pres = await execute_workflow_node_plugin(node_type, node, upstream)
        except Exception as pexc:
            logger.error("[WorkflowDAG] Node-Plugin '%s' abgestuerzt: %s", node_type, pexc, exc_info=pexc)
            pres = {"status": "error", "error": f"Plugin-Ausfuehrungsfehler: {pexc}", "content": ""}
        p_err = str(pres.get("status") or "success").lower() in ("error", "failed", "blocked")
        await asyncio.to_thread(
            _update_kanban_task_status,
            kanban_task_id,
            "blocked" if p_err else "done",
            result=str(pres.get("content") or pres.get("error") or ""),
            block_kind="workflow_error" if p_err else None,
            event_kind="workflow_node_failed" if p_err else "workflow_node_completed",
            event_payload={"node_id": node.get("id"), "type": node_type, "status": pres.get("status", "success")},
        )
        return {
            **pres,
            "node_id": node.get("id"),
            "agent_id": str(node.get("agent_id") or node_type),
            "kanban_task_id": kanban_task_id,
        }

    # Nativer Media-Render / Clip-Matrix Knoten (Content-Maschine im DAG)
    if node_type in ("media_render", "clip_matrix"):
        await asyncio.to_thread(
            _update_kanban_task_status,
            kanban_task_id,
            "in_progress",
            event_kind="workflow_node_started",
            event_payload={"node_id": node.get("id"), "type": node_type},
        )
        try:
            from backend.content_machine import generate_video_clip_matrix
            mcfg = dict(node.get("media_config") or {})
            up_texts = []
            for _dv in (upstream or {}).values():
                if isinstance(_dv, dict):
                    up_texts.append(str(_dv.get("content") or _dv.get("summary") or ""))
                elif _dv:
                    up_texts.append(str(_dv))
            script_text = str(mcfg.get("script") or "\n\n".join(t for t in up_texts if t) or node.get("prompt") or node.get("title") or "")
            campaign_id = str(mcfg.get("campaign_id") or node.get("workflow_id") or "wf_media")
            target_channels = mcfg.get("target_channels")
            if not isinstance(target_channels, list) or not target_channels:
                target_channels = [str(mcfg.get("target_platform") or node.get("channel") or "youtube_shorts")]
            matrix = await generate_video_clip_matrix(
                campaign_id=campaign_id,
                script_text=script_text,
                clip_count=int(mcfg.get("clip_count") or 3),
                target_channels=target_channels,
                dry_run=bool(mcfg.get("dry_run", False)),
            )
            rendered_md = json.dumps(matrix, ensure_ascii=False, indent=2)
            await asyncio.to_thread(
                _update_kanban_task_status,
                kanban_task_id,
                "done",
                result=rendered_md,
                event_kind="workflow_node_completed",
                event_payload={"node_id": node.get("id"), "type": node_type, "status": "success"},
            )
            return {
                "status": "success",
                "node_id": node.get("id"),
                "agent_id": str(node.get("agent_id") or "media_engine"),
                "content": rendered_md,
                "media_matrix": matrix,
                "kanban_task_id": kanban_task_id,
            }
        except Exception as mexc:
            await asyncio.to_thread(
                _update_kanban_task_status,
                kanban_task_id,
                "blocked",
                result=str(mexc),
                block_kind="workflow_error",
                event_kind="workflow_node_failed",
                event_payload={"node_id": node.get("id"), "type": node_type, "error": str(mexc)},
            )
            return {
                "status": "error",
                "node_id": node.get("id"),
                "error": str(mexc),
                "content": "",
                "kanban_task_id": kanban_task_id,
            }

    agent_name = str(prof.get("person_name") or prof.get("name") or agent_id)
    role = str(prof.get("role") or prof.get("category") or "Fach-Spezialist")
    system_prompt = str(
        prof.get("system_prompt")
        or prof.get("prompt")
        or f"Du bist {agent_name} in Archon OS. Bearbeite deinen Workflow-Schritt praezise und strukturiert."
    )
    model = str(node.get("model") or prof.get("model") or "deepseek/deepseek-chat").strip()
    # Punkt 3.2.6: Cheap-First -> Frontier-Escalation pro Node
    _esc_model = str(node.get("escalation_model") or "").strip()
    reasoning_level = str(node.get("reasoning_effort") or "medium").strip()

    # Optionale Markenstimme (config/voice.md) automatisch fuer Content-/Marketing-Schritte injizieren
    _voice_block = ""
    _channel_hint = str(node.get("channel") or "").strip().lower()
    _is_content_node = bool(
        _channel_hint
        or node.get("quality_gate")
        or any(
            kw in f"{agent_id} {role} {node.get('title', '')}".lower()
            for kw in ("writer", "content", "linkedin", "youtube", "tiktok", "shorts", "social", "storyteller", "newsletter", "blog")
        )
    )
    if _is_content_node:
        try:
            from archon.core.runtime import APP_ROOT
            _voice_path = os.path.join(APP_ROOT, "config", "voice.md")
            if os.path.isfile(_voice_path):
                with open(_voice_path, "r", encoding="utf-8", errors="ignore") as _vf:
                    _voice_txt = _vf.read(3000).strip()
                if _voice_txt:
                    _voice_block = f"\n\n[BRAND VOICE & STIL-VORGABEN (config/voice.md)]\n{_voice_txt}"
        except OSError as _vexc:
            logger.debug("[WorkflowDAG] config/voice.md nicht lesbar: %s", _vexc)

    # Prompt inkl. Upstream-Kontext & Guardrails aufbauen
    sections: List[str] = []
    node_title = str(node.get("title") or node.get("id") or "Workflow-Schritt")
    sections.append(f"WORKFLOW-SCHRITT: {node_title}")
    if node.get("prompt"):
        sections.append(str(node["prompt"]))
    if node.get("expected_output"):
        sections.append(f"[ERWARTETES ERGEBNIS]\n{node['expected_output']}")
    if node.get("allowed_tools"):
        _allowed_list = [str(t) for t in node["allowed_tools"] if str(t).strip()]
        sections.append(
            f"[ERLAUBTE TOOLS]\n{', '.join(_allowed_list)}\n"
            "Wenn du ein Tool ausfuehren musst, antworte exakt mit einem JSON-Objekt: "
            '{"tool_call": {"name": "<tool_name>", "args": {...}}}'
        )
    if node.get("forbidden_actions"):
        sections.append("[VERBOTEN / GUARDRAILS]\n- " + "\n- ".join(str(f) for f in node["forbidden_actions"]))
    if node.get("map_item") is not None:
        item_val = node["map_item"]
        item_str = json.dumps(item_val, ensure_ascii=False) if isinstance(item_val, (dict, list)) else str(item_val)
        sections.append(f"[AKTUELLER MAP-EINTRAG ({int(node.get('map_index', 0)) + 1}/{int(node.get('map_total', 1))})]\n{item_str}")
        if node.get("prompt") and "{{item}}" in str(node.get("prompt")):
            for p_idx, p_sec in enumerate(sections):
                if "{{item}}" in p_sec:
                    sections[p_idx] = p_sec.replace("{{item}}", item_str)
    if upstream:
        up_blocks = []
        for dep_id, dep_val in upstream.items():
            if isinstance(dep_val, dict):
                txt = dep_val.get("content") or dep_val.get("summary") or dep_val.get("result") or json.dumps(dep_val, ensure_ascii=False)
            else:
                txt = str(dep_val)
            up_blocks.append(f"### Vorlauf-Schritt `{dep_id}`:\n{str(txt)[:4000]}")
        sections.append("[UPSTREAM-ERGEBNISSE AUS VORHERIGEN SCHRITTEN]\n" + "\n\n".join(up_blocks))

    full_prompt = "\n\n".join(sections)
    eff_system_prompt = system_prompt + _voice_block

    await asyncio.to_thread(
        _update_kanban_task_status,
        kanban_task_id,
        "in_progress",
        event_kind="workflow_node_started",
        event_payload={"node_id": node.get("id"), "agent_id": agent_id, "model": model},
    )

    res = await core_dispatcher.dispatch_to_omniroute_or_container(
        agent_id=agent_id,
        agent_name=agent_name,
        prompt=full_prompt,
        role=role,
        system_prompt=eff_system_prompt,
        model=model,
        reasoning_level=reasoning_level,
        task_id=str(kanban_task_id or node.get("id") or ""),
    )

    status_raw = str(res.get("status") or "success").lower()
    content = str(res.get("content") or "").strip()
    is_error = status_raw in ("error", "failed", "blocked") or (not content and bool(res.get("error")))

    # Multi-Turn Tool-Calling Loop ueber zentralen ToolRuntime-Chokepoint
    tool_trace: List[Dict[str, Any]] = []
    allowed_tool_set = {str(t).strip() for t in (node.get("allowed_tools") or []) if str(t).strip()}
    if not is_error and content and allowed_tool_set:
        max_turns = max(1, min(6, int(node.get("max_turns") or 3)))
        turn_prompt = full_prompt
        for _turn in range(max_turns):
            _tc = None
            try:
                _stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE | re.DOTALL).strip()
                if _stripped.startswith("{") and '"tool_call"' in _stripped:
                    _parsed_tc = json.loads(_stripped)
                    if isinstance(_parsed_tc, dict) and isinstance(_parsed_tc.get("tool_call"), dict):
                        _tc = _parsed_tc["tool_call"]
            except Exception:
                _tc = None
            if not _tc:
                break
            _tname = str(_tc.get("name") or "").strip()
            _targs = _tc.get("args") if isinstance(_tc.get("args"), dict) else {}
            if _tname not in allowed_tool_set:
                _tres = {"status": "blocked", "error": f"Tool '{_tname}' ist in diesem DAG-Node nicht unter allowed_tools freigegeben."}
            else:
                from backend.tool_runtime import execute_agent_tool
                _tres = await execute_agent_tool(
                    tool_name=_tname,
                    args=_targs,
                    agent_id=agent_id,
                    session_id=str(kanban_task_id or node.get("id") or "dag_session"),
                )
            tool_trace.append({"turn": _turn + 1, "tool": _tname, "args": _targs, "result": _tres})
            _ckpt_rid = str(node.get("_dag_run_id") or "")
            _ckpt_db = node.get("_dag_db_path")
            if _ckpt_rid and node.get("id"):
                try:
                    with _connect(_ckpt_db) as conn:
                        conn.execute(
                            """
                            INSERT INTO workflow_node_states (run_id, node_id, fingerprint, status, output_json, updated_at)
                            VALUES (?, ?, ?, 'running', ?, ?)
                            ON CONFLICT(run_id, node_id) DO UPDATE SET
                                status='running', output_json=excluded.output_json, updated_at=excluded.updated_at
                            """,
                            (
                                _ckpt_rid,
                                str(node["id"]),
                                "running_checkpoint",
                                json.dumps({"partial_tool_trace": tool_trace, "turn": _turn + 1}, ensure_ascii=False),
                                time.time(),
                            ),
                        )
                        conn.commit()
                except Exception as _cexc:
                    logger.debug("[WorkflowDAG] Tool-Checkpoint fehlgeschlagen: %s", _cexc)
            turn_prompt = (
                f"{turn_prompt}\n\n[TOOL-AUFRUF #{_turn + 1}: {_tname}]\n"
                f"Ergebnis:\n{json.dumps(_tres, ensure_ascii=False)[:3500]}\n\n"
                "Nutze dieses Ergebnis. Wenn kein weiterer Tool-Aufruf noetig ist, liefere jetzt deine finale Antwort ohne tool_call-Wrapper."
            )
            _next_res = await core_dispatcher.dispatch_to_omniroute_or_container(
                agent_id=agent_id,
                agent_name=agent_name,
                prompt=turn_prompt,
                role=role,
                system_prompt=eff_system_prompt,
                model=model,
                reasoning_level=reasoning_level,
                task_id=str(kanban_task_id or node.get("id") or ""),
            )
            res["input_tokens"] = int(res.get("input_tokens") or 0) + int(_next_res.get("input_tokens") or 0)
            res["output_tokens"] = int(res.get("output_tokens") or 0) + int(_next_res.get("output_tokens") or 0)
            _next_status = str(_next_res.get("status") or "success").lower()
            _next_content = str(_next_res.get("content") or "").strip()
            if _next_status in ("error", "failed", "blocked") or not _next_content:
                is_error = True
                res["error"] = _next_res.get("error") or "Tool-Loop Folgeschritt fehlgeschlagen"
                break
            content = _next_content

    # JSON/Schema-Contract-Validierung zwischen DAG-Nodes (inkl. 1 Repair-Retry)
    parsed_output: Optional[Any] = None
    output_schema = node.get("output_schema")
    if not is_error and content and isinstance(output_schema, dict):
        def _validate_contract(raw_txt: str, schema: Dict[str, Any]) -> Tuple[bool, Any, str]:
            _clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_txt.strip(), flags=re.IGNORECASE | re.DOTALL).strip()
            try:
                _obj = json.loads(_clean)
            except Exception as _jerr:
                return False, None, f"Kein gueltiges JSON: {_jerr}"
            if not isinstance(_obj, dict):
                return False, None, "JSON-Root muss ein Objekt sein."
            req_keys = schema.get("required") if isinstance(schema.get("required"), list) else list(schema.keys())
            missing = [k for k in req_keys if k not in _obj]
            if missing:
                return False, _obj, f"Fehlende Pflichtfelder: {', '.join(str(m) for m in missing)}"
            return True, _obj, ""

        _ok_schema, _parsed_obj, _schema_err = _validate_contract(content, output_schema)
        if not _ok_schema:
            _repair_prompt = (
                f"{full_prompt}\n\n[SCHEMA-VALIDIERUNG FEHLGESCHLAGEN]\n"
                f"Fehler: {_schema_err}\n"
                f"Erwartetes Schema: {json.dumps(output_schema, ensure_ascii=False)}\n"
                f"Deine bisherige Ausgabe:\n{content[:3000]}\n\n"
                "Gib ausschliesslich ein valides JSON-Objekt zurueck, das alle Pflichtfelder erfuellt."
            )
            _repair_model_used = _esc_model or model
            _rep_res = await core_dispatcher.dispatch_to_omniroute_or_container(
                agent_id=agent_id,
                agent_name=agent_name,
                prompt=_repair_prompt,
                role=role,
                system_prompt=eff_system_prompt,
                model=_repair_model_used,
                reasoning_level=reasoning_level,
                task_id=str(kanban_task_id or node.get("id") or ""),
            )
            _repair_in = int(_rep_res.get("input_tokens") or 0)
            _repair_out = int(_rep_res.get("output_tokens") or 0)
            res["input_tokens"] = int(res.get("input_tokens") or 0) + _repair_in
            res["output_tokens"] = int(res.get("output_tokens") or 0) + _repair_out
            _rep_content = str(_rep_res.get("content") or "").strip()
            if _rep_content:
                content = _rep_content
                _ok_schema, _parsed_obj, _schema_err = _validate_contract(content, output_schema)
        # Punkt 3.2.6: Frontier-Eskalation, wenn der Repair-Retry am billigen Modell scheitert
        _esc_in = 0
        _esc_out = 0
        if not _ok_schema and _esc_model and _esc_model != model:
            _esc_prompt = (
                f"{full_prompt}\n\n"
                f"[SCHEMA-VALIDIERUNG FEHLGESCHLAGEN — FRONTIER-ESKALATION]\n"
                f"Fehler: {_schema_err}\n"
                f"Erwartetes Schema: {json.dumps(output_schema, ensure_ascii=False)}\n"
                f"Vorheriger Versuch:\n{content[:3000]}\n\n"
                "Liefere ausschliesslich das korrekte JSON-Objekt."
            )
            _esc_res = await core_dispatcher.dispatch_to_omniroute_or_container(
                agent_id=agent_id,
                agent_name=agent_name,
                prompt=_esc_prompt,
                role=role,
                system_prompt=eff_system_prompt,
                model=_esc_model,
                reasoning_level="high",
                task_id=str(kanban_task_id or node.get("id") or ""),
            )
            _esc_in = int(_esc_res.get("input_tokens") or 0)
            _esc_out = int(_esc_res.get("output_tokens") or 0)
            res["input_tokens"] = int(res.get("input_tokens") or 0) + _esc_in
            res["output_tokens"] = int(res.get("output_tokens") or 0) + _esc_out
            _esc_content = str(_esc_res.get("content") or "").strip()
            if _esc_content:
                content = _esc_content
                _ok_schema, _parsed_obj, _schema_err = _validate_contract(content, output_schema)
        if _ok_schema:
            parsed_output = _parsed_obj
        else:
            is_error = True
            res["error"] = f"Output-Schema-Verletzung: {_schema_err}"

    # Self-Critique / Anti-AI-Slop-Revisionsschleife fuer Content- & Quality-Gate-Knoten
    # Wichtig: Bei aktivem output_schema niemals validiertes JSON durch Prosa-Revision ueberschreiben.
    quality_report: Optional[Dict[str, Any]] = None
    revisions_used = 0
    if not is_error and content and _is_content_node:
        try:
            from backend.content_machine import evaluate_asset_quality
            if isinstance(output_schema, dict) and isinstance(parsed_output, dict):
                _q_hook = str(parsed_output.get("hook") or parsed_output.get("title") or "")
                _q_body = str(parsed_output.get("body") or parsed_output.get("content") or parsed_output.get("summary") or content)
                _q_cta = str(parsed_output.get("cta") or "")
                quality_report = evaluate_asset_quality({
                    "channel": _channel_hint or "linkedin",
                    "hook": _q_hook,
                    "body": _q_body,
                    "cta": _q_cta,
                })
            else:
                max_rev = max(0, min(2, int(node.get("max_revisions") if node.get("max_revisions") is not None else 1)))
                min_q = int(node.get("min_quality_score") or 75)
                lines_c = [ln.strip() for ln in content.splitlines() if ln.strip()]
                quality_report = evaluate_asset_quality({
                    "channel": _channel_hint or "linkedin",
                    "hook": lines_c[0] if lines_c else "",
                    "body": content,
                    "cta": lines_c[-1] if len(lines_c) > 1 else "",
                })
                while revisions_used < max_rev and (not quality_report.get("passed") or int(quality_report.get("score", 0)) < min_q):
                    revisions_used += 1
                    rev_issues = "; ".join(quality_report.get("issues") or [])
                    rev_sugg = "; ".join(quality_report.get("suggestions") or [])
                    rev_prompt = (
                        f"{full_prompt}\n\n"
                        f"[SELBST-KRITIK / ANTI-AI-SLOP-PRUEFUNG (Revision {revisions_used}/{max_rev})]\n"
                        f"Dein bisheriger Entwurf erreichte nur Quality-Score {quality_report.get('score')}/100.\n"
                        f"Befunde: {rev_issues}\n"
                        f"Konkrete Korrektur-Aufgaben: {rev_sugg}\n\n"
                        f"BISHERIGER ENTWURF:\n{content[:4500]}\n\n"
                        "Ueberarbeite den Text direkt, konkret, faktenbasiert (mit Zahlen-Anker & klarem CTA) und komplett ohne KI-Floskeln."
                    )
                    rev_res = await core_dispatcher.dispatch_to_omniroute_or_container(
                        agent_id=agent_id,
                        agent_name=agent_name,
                        prompt=rev_prompt,
                        role=role,
                        system_prompt=eff_system_prompt,
                        model=model,
                        reasoning_level=reasoning_level,
                        task_id=str(kanban_task_id or node.get("id") or ""),
                    )
                    rev_content = str(rev_res.get("content") or "").strip()
                    if rev_content and str(rev_res.get("status") or "success").lower() not in ("error", "failed", "blocked"):
                        content = rev_content
                        res["input_tokens"] = int(res.get("input_tokens") or 0) + int(rev_res.get("input_tokens") or 0)
                        res["output_tokens"] = int(res.get("output_tokens") or 0) + int(rev_res.get("output_tokens") or 0)
                        lines_c = [ln.strip() for ln in content.splitlines() if ln.strip()]
                        quality_report = evaluate_asset_quality({
                            "channel": _channel_hint or "linkedin",
                            "hook": lines_c[0] if lines_c else "",
                            "body": content,
                            "cta": lines_c[-1] if len(lines_c) > 1 else "",
                        })
                    else:
                        break
        except Exception as _qexc:
            logger.debug("[WorkflowDAG] Anti-Slop-Quality-Check uebersprungen: %s", _qexc)

    # Automatisches Deliverable-Export-Handling (Showroom / Obsidian 03_Endprodukte)
    deliverable_path = ""
    if not is_error and content and (bool(node.get("save_to_showroom")) or _is_content_node):
        try:
            from archon.core.paths import PROJEKTE_DIR
            wf_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(node.get("workflow_id") or "workflow_deliverables")).strip("_")[:48] or "workflow_deliverables"
            node_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(node.get("id") or "step")).strip("_")[:40] or "step"
            target_dir = os.path.join(PROJEKTE_DIR, f"WF_{wf_slug}", "03_Endprodukte")
            os.makedirs(target_dir, exist_ok=True)
            ts_tag = time.strftime("%Y%m%d_%H%M%S")
            deliverable_path = os.path.join(target_dir, f"{ts_tag}_{node_slug}.md")
            header_md = f"# {node_title}\n\n- **Agent:** `{agent_id}`\n- **Modell:** `{res.get('model') or model}`\n"
            if quality_report is not None:
                header_md += f"- **Anti-Slop Quality-Score:** `{quality_report.get('score')}/100` (Revisionen: {revisions_used})\n"
            header_md += "\n---\n\n"
            with open(deliverable_path, "w", encoding="utf-8") as _df:
                _df.write(header_md + content + "\n")
        except OSError as _dexc:
            logger.debug("[WorkflowDAG] Showroom-Deliverable nicht geschrieben: %s", _dexc)

    # Punkt 3.2.6: exakte Kosten pro Node (Basis-/Repair-/Eskalations-Modell getrennt)
    _cost_usd = 0.0
    try:
        from backend.llm_kernel import estimate_model_cost_usd as _est_cost
        _rep_in_tok = int(locals().get("_repair_in", 0) or 0)
        _rep_out_tok = int(locals().get("_repair_out", 0) or 0)
        _esc_in_tok = int(locals().get("_esc_in", 0) or 0)
        _esc_out_tok = int(locals().get("_esc_out", 0) or 0)
        _base_in = int(res.get("input_tokens") or 0) - _rep_in_tok - _esc_in_tok
        _base_out = int(res.get("output_tokens") or 0) - _rep_out_tok - _esc_out_tok
        if _base_in or _base_out:
            _cost_usd += _est_cost(model, _base_in, _base_out)
        if _rep_in_tok or _rep_out_tok:
            _cost_usd += _est_cost(locals().get("_repair_model_used") or model, _rep_in_tok, _rep_out_tok)
        if _esc_in_tok or _esc_out_tok:
            _cost_usd += _est_cost(_esc_model or model, _esc_in_tok, _esc_out_tok)
        _cost_usd = round(_cost_usd, 6)
    except Exception as _cost_exc:
        logger.debug("[WorkflowDAG] Kostenberechnung uebersprungen: %s", _cost_exc)
    out = {
        "status": "error" if is_error else "success",
        "node_id": node.get("id"),
        "agent_id": agent_id,
        "model": res.get("model") or model,
        "content": content,
        "error": res.get("error") or "",
        "input_tokens": int(res.get("input_tokens") or 0),
        "output_tokens": int(res.get("output_tokens") or 0),
        "kanban_task_id": kanban_task_id,
        "cost_usd": _cost_usd,
    }
    if quality_report is not None:
        out["quality_score"] = int(quality_report.get("score", 0))
        out["quality_report"] = quality_report
        out["revisions_used"] = revisions_used
    if deliverable_path:
        out["deliverable_path"] = deliverable_path
    if tool_trace:
        out["tool_trace"] = tool_trace
    if parsed_output is not None:
        out["parsed_output"] = parsed_output

    await asyncio.to_thread(
        _update_kanban_task_status,
        kanban_task_id,
        "blocked" if is_error else "done",
        result=content or out["error"],
        block_kind="workflow_error" if is_error else None,
        event_kind="workflow_node_failed" if is_error else "workflow_node_completed",
        event_payload={"node_id": node.get("id"), "agent_id": agent_id, "status": out["status"]},
    )
    return out


async def _exec_with_retry_and_timeout(
    executor_fn: ExecutorFn,
    node: Dict[str, Any],
    upstream: Dict[str, Any],
) -> Dict[str, Any]:
    max_retries = max(0, min(5, int(node.get("max_retries") or 0)))
    timeout_sec = max(5.0, min(900.0, float(node.get("timeout_sec") or 180.0)))
    last_err = ""
    for attempt in range(max_retries + 1):
        try:
            res = await asyncio.wait_for(executor_fn(node, upstream), timeout=timeout_sec)
            out = res if isinstance(res, dict) else {"status": "success", "result": res}
            if out.get("status") != "error":
                return out
            last_err = str(out.get("error") or "node_returned_error")
            if attempt == max_retries:
                return out
        except asyncio.TimeoutError:
            last_err = f"Timeout nach {timeout_sec}s (Versuch {attempt + 1}/{max_retries + 1})"
        except Exception as exc:
            last_err = str(exc)
        if attempt < max_retries:
            await asyncio.sleep(min(2.0 * (attempt + 1), 6.0))
    return {"status": "error", "error": last_err, "node_id": node.get("id")}


async def run_workflow_dag(
    dag_def: Dict[str, Any],
    executor_fn: Optional[ExecutorFn] = None,
    run_id: Optional[str] = None,
    gate_approvals: Optional[Dict[str, bool]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Fuehrt einen Workflow-DAG aus (mit Per-run_id-Lock gegen Doppel-Ausfuehrung).
    `dag_def`: {
        "id": "...",
        "nodes": [{"id": "...", "type": "agent|fanout|gate", "depends_on": [...], ...}],
        "edges": [{"from": "...", "to": "...", "condition": "always|on_success|on_failure", "data_mode": "full|summary|artifact_only|none"}]
    }
    """
    rid = run_id or f"wfrun-{secrets.token_hex(5)}"
    # Per-run_id-Lock: nur EINE Ausfuehrung pro Run. Falls belegt, laufende
    # Ausfuehrung nicht stoeren, sondern sofort melden.
    run_lock = _get_run_lock(rid)
    if run_lock.locked():
        logger.warning(f"[WorkflowDAG] Run '{rid}' laeuft bereits — keine zweite Ausfuehrung gestartet.")
        return {
            "status": "already_running",
            "run_id": rid,
            "workflow_id": str(dag_def.get("id") or "workflow"),
            "node_statuses": {},
            "outputs": {},
        }
    await run_lock.acquire()
    try:
        return await _run_workflow_dag_locked(dag_def, executor_fn, rid, gate_approvals, db_path)
    finally:
        run_lock.release()


async def _run_workflow_dag_locked(
    dag_def: Dict[str, Any],
    executor_fn: Optional[ExecutorFn],
    rid: str,
    gate_approvals: Optional[Dict[str, bool]],
    db_path: Optional[str],
) -> Dict[str, Any]:
    """Eigentliche DAG-Ausfuehrung; Per-run_id-Lock wird von run_workflow_dag gehalten."""
    eff_executor = executor_fn or default_agent_node_executor
    wf_id = str(dag_def.get("id") or "workflow")
    nodes = dag_def.get("nodes") or []
    node_map: Dict[str, Dict[str, Any]] = {str(n["id"]): n for n in nodes if isinstance(n, dict) and n.get("id")}
    edge_map = _extract_edge_map(dag_def)
    now = time.time()

    # M110 Pre-Execution Validator: Zyklen/Schema/Mapping/Budget/Deadline/
    # RBAC/HITL/Replan-Count werden VOR jedem Node geprüft (kein halber Start).
    validation = validate_dag_def(dag_def, now=now)
    if not validation["valid"]:
        err_msg = "Plan-Validator: " + "; ".join(validation["errors"][:8])
        logger.error(f"[WorkflowDAG] Run '{rid}' von Plan-Validator abgelehnt: {err_msg}")
        with _connect(db_path) as conn:
            conn.execute(
                "INSERT INTO workflow_runs (run_id, workflow_id, status, dag_json, created_at, updated_at) "
                "VALUES (?, ?, 'failed', ?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET status = 'failed', updated_at = excluded.updated_at",
                (rid, wf_id, json.dumps(dag_def, ensure_ascii=False), now, now),
            )
            conn.commit()
        return {
            "run_id": rid,
            "workflow_id": wf_id,
            "status": "failed",
            "node_statuses": {},
            "outputs": {},
            "error": err_msg,
            "validation_errors": validation["errors"],
        }

    # Unbekannte depends_on-IDs / Kanten-Quellen: sofort failed mit klarer Diagnose
    for _nid, _node in node_map.items():
        for _dep in _all_dependencies_for_node(_node, edge_map.get(_nid, [])):
            if _dep not in node_map:
                _err_msg = f"Unknown dependency: {_dep}"
                logger.error(f"[WorkflowDAG] Run '{rid}': {_err_msg}")
                with _connect(db_path) as conn:
                    conn.execute(
                        """
                        INSERT INTO workflow_runs (run_id, workflow_id, status, dag_json, created_at, updated_at)
                        VALUES (?, ?, 'failed', '{}', ?, ?)
                        ON CONFLICT(run_id) DO UPDATE SET status = 'failed', updated_at = excluded.updated_at
                        """,
                        (rid, wf_id, now, now),
                    )
                    conn.commit()
                return {
                    "run_id": rid,
                    "workflow_id": wf_id,
                    "status": "failed",
                    "node_statuses": {},
                    "outputs": {},
                    "error": _err_msg,
                }

    # OTel: ein Trace pro Run, ein Span pro Node. Alle Tracer-Writes laufen
    # im Threadpool, damit der Event-Loop nicht blockiert.
    trace_id = await _otel_start(f"workflow.{wf_id}", rid)

    approvals: Dict[str, bool] = {}
    with _connect(db_path) as conn:
        prev_run = conn.execute(
            "SELECT gate_approvals_json FROM workflow_runs WHERE run_id = ?",
            (rid,),
        ).fetchone()
        if prev_run and prev_run["gate_approvals_json"]:
            try:
                stored_app = json.loads(prev_run["gate_approvals_json"])
                if isinstance(stored_app, dict):
                    approvals.update({str(k): bool(v) for k, v in stored_app.items()})
            except Exception:
                pass
        if gate_approvals:
            approvals.update({str(k): bool(v) for k, v in gate_approvals.items()})
        conn.execute(
            """
            INSERT INTO workflow_runs (run_id, workflow_id, status, dag_json, gate_approvals_json, created_at, updated_at)
            VALUES (?, ?, 'running', ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                status='running',
                dag_json=CASE WHEN excluded.dag_json != '{}' THEN excluded.dag_json ELSE workflow_runs.dag_json END,
                gate_approvals_json=excluded.gate_approvals_json,
                updated_at=excluded.updated_at
            """,
            (rid, wf_id, json.dumps(dag_def, ensure_ascii=False), json.dumps(approvals, ensure_ascii=False), now, now),
        )
        conn.commit()
        cached_rows = conn.execute(
            "SELECT node_id, fingerprint, status, output_json FROM workflow_node_states WHERE run_id = ?",
            (rid,),
        ).fetchall()
        cached = {r["node_id"]: dict(r) for r in cached_rows}

    outputs: Dict[str, Any] = {}
    statuses: Dict[str, str] = {}

    max_conc = max(1, min(16, int(dag_def.get("max_concurrent_tasks") or 4)))
    sem = asyncio.Semaphore(max_conc)
    pending = set(node_map.keys())
    running_tasks: Dict[str, "asyncio.Task[None]"] = {}

    async def _run_one(nid: str) -> None:
        node_started = time.perf_counter()
        node = node_map[nid]
        inc_edges = edge_map.get(nid, [])
        edge_by_src = {e["from"]: e for e in inc_edges}
        deps = _all_dependencies_for_node(node, inc_edges)
        upstream = {
            d: _shape_upstream_output(outputs.get(d), (edge_by_src.get(d) or {}).get("data_mode", "full"))
            for d in deps
        }
        fp = compute_node_fingerprint(node, upstream)

        prev = cached.get(nid)
        if prev and prev["fingerprint"] == fp and prev["status"] in ("completed", "skipped_cached"):
            outputs[nid] = json.loads(prev["output_json"] or "{}")
            statuses[nid] = "skipped_cached"
            return

        # Persistenter Running-Status + Live-SSE-Broadcast
        with _connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO workflow_node_states (run_id, node_id, fingerprint, status, output_json, updated_at)
                VALUES (?, ?, ?, 'running', '{}', ?)
                ON CONFLICT(run_id, node_id) DO UPDATE SET
                    fingerprint=excluded.fingerprint, status='running', updated_at=excluded.updated_at
                """,
                (rid, nid, fp, time.time()),
            )
            conn.commit()

        try:
            from archon.core.runtime import broadcast_event
            broadcast_event("workflow_node_state", {
                "run_id": rid, "workflow_id": wf_id, "node_id": nid, "status": "running"
            })
        except Exception as _bexc:
            logger.debug("[WorkflowDAG] SSE running-Event uebersprungen: %s", _bexc)

        ntype = str(node.get("type") or "agent").lower()
        requires_gate = ntype == "gate" or bool(node.get("require_hitl"))
        node_ctx = {**node, "workflow_id": wf_id, "_dag_run_id": rid, "_dag_db_path": db_path}

        if ntype == "gate":
            if approvals.get(nid) is True:
                out = {"approved": True, "status": "success"}
                st = "completed"
                await asyncio.to_thread(_update_kanban_task_status, node.get("kanban_task_id"), "done", result="HITL-Gate freigegeben.")
            elif approvals.get(nid) is False:
                out = {"approved": False, "status": "rejected"}
                st = "rejected"
                await asyncio.to_thread(_update_kanban_task_status, node.get("kanban_task_id"), "blocked", result="HITL-Gate abgelehnt.", block_kind="hitl_rejected")
            else:
                deci_id = await asyncio.to_thread(_register_hitl_gate_decision, rid, wf_id, node, upstream, db_path)
                out = {"awaiting_gate": True, "decision_id": deci_id}
                st = "awaiting_gate"
                await asyncio.to_thread(_update_kanban_task_status, node.get("kanban_task_id"), "blocked", result="Wartet auf HITL-Freigabe.", block_kind="hitl_gate")
        elif requires_gate and approvals.get(nid) is not True:
            if approvals.get(nid) is False:
                out = {"approved": False, "status": "rejected"}
                st = "rejected"
                await asyncio.to_thread(_update_kanban_task_status, node.get("kanban_task_id"), "blocked", result="HITL-Freigabe abgelehnt.", block_kind="hitl_rejected")
            else:
                deci_id = await asyncio.to_thread(_register_hitl_gate_decision, rid, wf_id, node, upstream, db_path)
                out = {"awaiting_gate": True, "decision_id": deci_id}
                st = "awaiting_gate"
                await asyncio.to_thread(_update_kanban_task_status, node.get("kanban_task_id"), "blocked", result="Wartet auf HITL-Freigabe vor Ausfuehrung.", block_kind="hitl_gate")
        elif ntype == "quality_gate":
            from backend.content_machine import evaluate_asset_quality
            combined_up = "\n\n".join(
                str(v.get("content") or v.get("result") or "") if isinstance(v, dict) else str(v)
                for v in upstream.values()
            ).strip()
            lines_u = [ln.strip() for ln in combined_up.splitlines() if ln.strip()]
            q_rep = evaluate_asset_quality({
                "channel": str(node.get("channel") or "linkedin"),
                "hook": lines_u[0] if lines_u else "",
                "body": combined_up,
                "cta": lines_u[-1] if len(lines_u) > 1 else "",
            })
            min_q = int(node.get("min_quality_score") or 70)
            q_ok = bool(q_rep.get("passed")) and int(q_rep.get("score", 0)) >= min_q
            out = {
                "status": "success" if q_ok else "error",
                "quality_score": int(q_rep.get("score", 0)),
                "quality_report": q_rep,
                "content": combined_up,
            }
            st = "completed" if q_ok else "failed"
            await asyncio.to_thread(
                _update_kanban_task_status,
                node.get("kanban_task_id"),
                "done" if q_ok else "blocked",
                result=f"Anti-Slop Quality-Score: {out['quality_score']}/100",
                block_kind=None if q_ok else "quality_gate_failed",
            )
        elif ntype in ("map", "dynamic_fanout"):
            # Punkt 3.2.3: Dynamisches Sub-DAG-Spawning (Map-Over-Items)
            items = []
            items_key = str(node.get("items_key") or "items").strip()
            if isinstance(node.get("items"), list):
                items = list(node["items"])
            else:
                for up_k, up_val in upstream.items():
                    if isinstance(up_val, dict):
                        po = up_val.get("parsed_output")
                        if isinstance(po, list):
                            items = po
                            break
                        elif isinstance(po, dict) and isinstance(po.get(items_key), list):
                            items = po[items_key]
                            break
                        if isinstance(up_val.get("items"), list):
                            items = up_val["items"]
                            break
                        if isinstance(up_val.get("results"), list):
                            items = up_val["results"]
                            break
                        raw_c = str(up_val.get("content") or up_val.get("result") or "").strip()
                        if raw_c.startswith("[") and raw_c.endswith("]"):
                            try:
                                loaded = json.loads(raw_c)
                                if isinstance(loaded, list):
                                    items = loaded
                                    break
                            except Exception:
                                pass
                    elif isinstance(up_val, list):
                        items = up_val
                        break

            max_items = max(1, min(50, int(node.get("max_items") or 10)))
            max_budget_eur = float(node.get("max_budget_eur") or 1.0)
            items_to_process = items[:max_items]

            if not items_to_process:
                out = await _exec_with_retry_and_timeout(eff_executor, node_ctx, upstream)
                st = "failed" if out.get("status") == "error" else "completed"
            else:
                sub_tasks = []
                for idx, itm in enumerate(items_to_process):
                    sub_ctx = {
                        **node_ctx,
                        "id": f"{nid}_item_{idx}",
                        "map_item": itm,
                        "map_index": idx,
                        "map_total": len(items_to_process),
                        "plugin_params": {
                            **dict(node.get("plugin_params") or {}),
                            "item": itm,
                            "index": idx,
                        },
                    }
                    sub_up = {**upstream, "_item": itm}
                    sub_tasks.append(_exec_with_retry_and_timeout(eff_executor, sub_ctx, sub_up))

                sub_results = await asyncio.gather(*sub_tasks, return_exceptions=True)
                ok_results = []
                total_cost = 0.0
                for r in sub_results:
                    if isinstance(r, dict):
                        total_cost += float(r.get("cost_usd") or 0.0)
                        if r.get("status") != "error":
                            ok_results.append(r)
                    elif not isinstance(r, Exception):
                        ok_results.append({"result": r, "status": "success"})

                budget_exceeded = total_cost > (max_budget_eur * 1.15)
                quorum = int(node.get("quorum_min") or max(1, len(items_to_process) // 2 or 1))
                st = "completed" if (len(ok_results) >= quorum and not budget_exceeded) else "failed"
                out = {
                    "status": "success" if st == "completed" else "error",
                    "map_results": ok_results,
                    "items_count": len(items_to_process),
                    "ok_count": len(ok_results),
                    "cost_usd": round(total_cost, 6),
                    "budget_exceeded": budget_exceeded,
                    "max_budget_eur": max_budget_eur,
                    "results": ok_results,
                }
        elif ntype == "fanout":
            branches = node.get("branches") or []
            if branches:
                quorum = int(node.get("quorum_min") or max(1, len(branches)))
                results = await asyncio.gather(
                    *(_exec_with_retry_and_timeout(eff_executor, {**node_ctx, "branch": b}, upstream) for b in branches),
                    return_exceptions=True,
                )
                ok_results = [r for r in results if isinstance(r, dict) and r.get("status", "success") != "error"]
                if len(ok_results) >= quorum:
                    out = {"status": "success", "quorum_met": True, "ok_count": len(ok_results), "results": ok_results}
                    st = "completed"
                else:
                    out = {"status": "error", "quorum_met": False, "ok_count": len(ok_results), "required": quorum}
                    st = "failed"
            else:
                out = await _exec_with_retry_and_timeout(eff_executor, node_ctx, upstream)
                st = "failed" if out.get("status") == "error" else "completed"
        else:
            out = await _exec_with_retry_and_timeout(eff_executor, node_ctx, upstream)
            st = "failed" if out.get("status") == "error" else "completed"

        outputs[nid] = out
        statuses[nid] = st
        if trace_id:
            await _otel_span(
                trace_id,
                name=f"dag.node.{nid}",
                span_type="agent",
                agent_id=str(node.get("agent_id") or "workflow_engine"),
                model=str(node.get("model") or ""),
                output_data=out if isinstance(out, dict) else {"result": out},
                status="OK" if st in SUCCESS_NODE_STATES else "ERROR",
                cost_usd=float(out.get("cost_usd") or 0.0) if isinstance(out, dict) else 0.0,
                duration_ms=round((time.perf_counter() - node_started) * 1000.0, 2),
                attributes={"run_id": rid, "node_id": nid, "node_type": ntype, "status": st},
            )
        with _connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO workflow_node_states (run_id, node_id, fingerprint, status, output_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, node_id) DO UPDATE SET
                    fingerprint=excluded.fingerprint, status=excluded.status,
                    output_json=excluded.output_json, updated_at=excluded.updated_at
                """,
                (rid, nid, fp, st, json.dumps(out, ensure_ascii=False), time.time()),
            )
            conn.commit()
        try:
            from archon.core.runtime import broadcast_event
            broadcast_event("workflow_node_state", {
                "run_id": rid,
                "workflow_id": wf_id,
                "node_id": nid,
                "status": st,
                "quality_score": out.get("quality_score") if isinstance(out, dict) else None,
                "deliverable_path": out.get("deliverable_path") if isinstance(out, dict) else None,
            })
        except Exception as _bexc:
            logger.debug("[WorkflowDAG] SSE terminal-Event uebersprungen: %s", _bexc)

    async def _run_guarded(nid: str) -> None:
        async with sem:
            await _run_one(nid)

    # Event-gesteuerte Topologische Ready-Queue (kein globales Wave-Barrier-Warten)
    while pending or running_tasks:
        ready: List[str] = []
        skippable: List[str] = []

        for nid in sorted(pending - set(running_tasks.keys())):
            node = node_map[nid]
            inc_edges = edge_map.get(nid, [])
            deps = _all_dependencies_for_node(node, inc_edges)
            if not deps:
                ready.append(nid)
                continue
            if not all(statuses.get(d) in TERMINAL_NODE_STATES for d in deps):
                continue

            edge_by_src = {e["from"]: e for e in inc_edges}
            all_conditions_met = True
            for d in deps:
                e = edge_by_src.get(d)
                cond = e["condition"] if e else "on_success"
                if not _edge_condition_matches(cond, statuses.get(d, "")):
                    all_conditions_met = False
                    break
            if all_conditions_met:
                ready.append(nid)
            else:
                skippable.append(nid)

        for nid in skippable:
            outputs[nid] = {"status": "skipped", "reason": "upstream_condition_not_met"}
            statuses[nid] = "skipped_condition"
            pending.discard(nid)
            with _connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO workflow_node_states (run_id, node_id, fingerprint, status, output_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, node_id) DO UPDATE SET
                        status=excluded.status, output_json=excluded.output_json, updated_at=excluded.updated_at
                    """,
                    (rid, nid, "skipped", "skipped_condition", json.dumps(outputs[nid], ensure_ascii=False), time.time()),
                )
                conn.commit()

        for nid in ready:
            running_tasks[nid] = asyncio.create_task(_run_guarded(nid))

        if not running_tasks:
            # Entweder durch Gate/Fehler blockiert oder Zyklus
            break

        done_set, _ = await asyncio.wait(list(running_tasks.values()), return_when=asyncio.FIRST_COMPLETED)
        for fin_nid, fin_task in list(running_tasks.items()):
            if fin_task in done_set:
                running_tasks.pop(fin_nid, None)
                pending.discard(fin_nid)
                # Exceptions im Task abfangen, damit Scheduler nicht abbricht
                try:
                    fin_task.result()
                except Exception as _texc:
                    logger.error("[WorkflowDAG] Unbehandelter Task-Fehler in Node '%s': %s", fin_nid, _texc, exc_info=_texc)
                    statuses[fin_nid] = "failed"
                    outputs[fin_nid] = {"status": "error", "error": str(_texc)}

    # on_failure-Recovery pruefen: ein fehlgeschlagener Node gilt als aufgefangen,
    # wenn ein nachgelagerter on_failure-Knoten erfolgreich abgeschlossen wurde.
    recovered_failures = set()
    for target_nid, inc_edges in edge_map.items():
        if statuses.get(target_nid) in ("completed", "skipped_cached"):
            for e in inc_edges:
                if e.get("condition") == "on_failure" and statuses.get(e.get("from")) == "failed":
                    recovered_failures.add(e["from"])

    unrecovered_fail = any(
        (st == "rejected") or (st == "failed" and nid not in recovered_failures)
        for nid, st in statuses.items()
    )
    has_awaiting_gate = any(s == "awaiting_gate" for s in statuses.values())
    cycle_error: Optional[str] = None
    if unrecovered_fail:
        final_status = "failed"
    elif has_awaiting_gate:
        final_status = "paused"
    elif pending:
        # Kein Fortschritt moeglich und kein wartendes Gate: Zyklus / unresolvable dependency
        final_status = "failed"
        cycle_error = "Cycle or unresolvable dependency detected"
        logger.error(f"[WorkflowDAG] Run '{rid}': {cycle_error}")
    else:
        final_status = "completed"

    with _connect(db_path) as conn:
        # Punkt 3.2.6: Gesamtkosten pro Run/Deliverable ausmessen
        _total_cost = 0.0
        try:
            for _r in conn.execute("SELECT output_json FROM workflow_node_states WHERE run_id = ?", (rid,)).fetchall():
                try:
                    _o = json.loads(_r[0] or "{}")
                    _total_cost += float(_o.get("cost_usd") or 0.0)
                except Exception:
                    pass
        except sqlite3.OperationalError:
            pass
        conn.execute(
            "UPDATE workflow_runs SET status = ?, updated_at = ?, total_cost_usd = ? WHERE run_id = ?",
            (final_status, time.time(), round(_total_cost, 6), rid),
        )
        conn.commit()

    result: Dict[str, Any] = {
        "run_id": rid,
        "workflow_id": wf_id,
        "status": final_status,
        "node_statuses": statuses,
        "outputs": outputs,
    }
    if cycle_error:
        result["error"] = cycle_error
    if trace_id:
        await _otel_end(trace_id, "ERROR" if final_status in FAILURE_NODE_STATES or cycle_error else "OK")
    return result


def get_workflow_run(run_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with _connect(db_path) as conn:
        run_cols = {r[1] for r in conn.execute("PRAGMA table_info(workflow_runs)").fetchall()}
        cost_col = ", total_cost_usd" if "total_cost_usd" in run_cols else ""
        run_row = conn.execute(
            f"SELECT run_id, workflow_id, status, dag_json, created_at, updated_at{cost_col} FROM workflow_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if not run_row:
            return None
        node_rows = conn.execute(
            "SELECT node_id, fingerprint, status, output_json, updated_at FROM workflow_node_states WHERE run_id = ? ORDER BY updated_at ASC",
            (run_id,),
        ).fetchall()
    nodes = {}
    for nr in node_rows:
        try:
            out_parsed = json.loads(nr["output_json"] or "{}")
        except Exception:
            out_parsed = {}
        nodes[nr["node_id"]] = {
            "status": nr["status"],
            "fingerprint": nr["fingerprint"],
            "output": out_parsed,
            "updated_at": nr["updated_at"],
        }
    try:
        dag_parsed = json.loads(run_row["dag_json"] or "{}")
    except Exception:
        dag_parsed = {}
    return {
        "run_id": run_row["run_id"],
        "workflow_id": run_row["workflow_id"],
        "status": run_row["status"],
        "dag": dag_parsed,
        "nodes": nodes,
        "total_cost_usd": float(run_row["total_cost_usd"] or 0.0) if "total_cost_usd" in run_row.keys() else 0.0,
        "created_at": run_row["created_at"],
        "updated_at": run_row["updated_at"],
    }


def list_workflow_runs(limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    with _connect(db_path) as conn:
        run_cols = {r[1] for r in conn.execute("PRAGMA table_info(workflow_runs)").fetchall()}
        cost_col = ", total_cost_usd" if "total_cost_usd" in run_cols else ""
        rows = conn.execute(
            f"SELECT run_id, workflow_id, status, created_at, updated_at{cost_col} FROM workflow_runs ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(200, int(limit))),),
        ).fetchall()
    return [dict(r) for r in rows]


async def resume_workflow_run(
    run_id: str,
    gate_approvals: Optional[Dict[str, bool]] = None,
    executor_fn: Optional[ExecutorFn] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    existing = get_workflow_run(run_id, db_path=db_path)
    if not existing:
        raise KeyError(f"Workflow run '{run_id}' not found")
    dag_def = existing.get("dag") or {}
    if not dag_def.get("nodes"):
        raise ValueError(f"Workflow run '{run_id}' besitzt keine gespeicherte DAG-Definition fuer Resume.")
    return await run_workflow_dag(
        dag_def=dag_def,
        executor_fn=executor_fn,
        run_id=run_id,
        gate_approvals=gate_approvals or {},
        db_path=db_path,
    )


def schedule_workflow_resume(
    run_id: str,
    gate_approvals: Optional[Dict[str, bool]] = None,
    executor_fn: Optional[ExecutorFn] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Feuert einen Fire-and-Forget-Resume-Task ab (fire-and-sauber-vergessen).

    Eine Exception im Hintergrund-Task wird NICHT still geschluckt: der
    Done-Callback loggt sie mit traceback und setzt den Run in workflow_runs
    auf 'failed' (statt fuer immer 'running'/'paused' zu bleiben).
    Wird von decisions.py / v2_capabilities.py benutzt.
    """
    async def _resume_runner() -> Dict[str, Any]:
        return await resume_workflow_run(
            run_id=run_id,
            gate_approvals=gate_approvals,
            executor_fn=executor_fn,
            db_path=db_path,
        )

    def _on_resume_done(task: "asyncio.Task[Dict[str, Any]]") -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            logger.debug(f"[WorkflowDAG] Resume-Task fuer Run '{run_id}' wurde abgebrochen.")
        except Exception as exc:
            logger.error(f"[WorkflowDAG] Resume-Task fuer Run '{run_id}' fehlgeschlagen: {exc}", exc_info=exc)
            try:
                with _connect(db_path) as conn:
                    conn.execute(
                        "UPDATE workflow_runs SET status = 'failed', updated_at = ? WHERE run_id = ?",
                        (time.time(), run_id),
                    )
                    conn.commit()
            except Exception as persist_exc:
                logger.error(
                    f"[WorkflowDAG] Failed-Status fuer Run '{run_id}' konnte nicht persistiert werden: {persist_exc}",
                    exc_info=persist_exc,
                )

    task = asyncio.create_task(_resume_runner())
    task.add_done_callback(_on_resume_done)
    return {"status": "scheduled", "run_id": run_id, "scheduled": True}
