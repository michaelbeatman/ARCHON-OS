# mypy: ignore-errors
"""Hilfs- und Sync-Funktionen fuer Mission Control, Obsidian-Spiegelung und Live-Telemetrie."""
from __future__ import annotations

import datetime
import glob
import json
import logging
import os
import re
import sqlite3
import time
from typing import Any, Dict, List

from archon.core.paths import (
    HERMES_PROFILES_BASE,
    OPT_DATA_DIR,
    PROJEKTE_DIR,
    STATE_DB_PATH,
)
from archon.core.runtime import WORKSPACE_DIR, resolve_obsidian_vault_path
from utils.path_jail import safe_filename

logger = logging.getLogger("archon.services.mission_sync")


class _SyncPath(str):
    """Pfad + ehrlicher Sync-Status (str-Kompatibilitaet fuer bestehende Aufrufer)."""

    def __new__(cls, value: str, status: str, replicas: list, hashes: dict):
        obj = super().__new__(cls, value)
        obj.status = status
        obj.replicas = replicas
        obj.hashes = hashes
        return obj


def _slugify(text: str) -> str:
    """Wandelt Text in sauberes, striktes ASCII um (ersetzt Umlaute) für sichere Dateinamen über Docker/NTFS."""
    text = text.lower()
    umlaut_map = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
        "Ä": "ae",
        "Ö": "oe",
        "Ü": "ue",
    }
    for k, v in umlaut_map.items():
        text = text.replace(k, v)
    text = re.sub(r"[^a-z0-9_-]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    if len(text) > 60:
        text = text[:60].rstrip("-")
    return text or "task"


def _sync_task_to_obsidian(task: dict) -> str:
    """Führt die Post-Task-Pipeline aus:
    1. Projektordner-Struktur (01_Zwischenberichte, 02_Medien, 03_Endprodukte) + PROJEKT.md
    2. Personalakten-Aktualisierung (tasks_completed, Tabellen-Eintrag)
    3. Self-Improvement Lerneffekt via LocalMemoryBridge
    4. Paperclip-Status-Schließung
    5. E-Mail-Versand (falls konfiguriert)
    """
    import main as app_main

    # D03/MED: kanonischer Vault-Pfad ueber den Resolver (kein hartcodierter
    # Fallback), wenn main.py keinen expliziten Override bereitstellt.
    obs_vault_dir = getattr(app_main, "OBSIDIAN_VAULT_DIR", None) or resolve_obsidian_vault_path()
    workspace_dir = getattr(app_main, "WORKSPACE_DIR", WORKSPACE_DIR)

    try:
        from backend.post_task_pipeline import execute_post_task_pipeline

        pipe_res = execute_post_task_pipeline(task)
        if pipe_res and pipe_res.get("final_path"):
            return pipe_res["final_path"]
    except Exception as e_hook:
        logger.warning(f"[PostTaskPipeline] Hook-Fehler, weiche auf Fallback aus: {e_hook}")

    task_id = str(task.get("id") or "task-0").strip()
    raw_title = task.get("title") or "task"
    task_slug = _slugify(raw_title)
    # User-Vorgabe 09.10.2026: Datum (YYYYMMDD-) als Präfix statt "task-"
    _date_prefix = datetime.datetime.now().strftime("%Y%m%d")
    _tid_core = task_id.replace("task-", "")
    # Dateiname jailen: task_id koennte Pfadzeichen/Traversal enthalten.
    _tid_core = "".join(c for c in _tid_core if c.isalnum() or c in "-_")[:80] or "task"
    file_name = f"{_date_prefix}-{_tid_core}-{task_slug}.md"

    # Bevorzugt PROJEKTE_DIR, fallbacks auf OBSIDIAN_VAULT_DIR und inbox
    target_dirs = [
        PROJEKTE_DIR,
        os.path.join(obs_vault_dir, "01_PROJEKTE"),
        os.path.join(workspace_dir, "obsidian_vault", "01_PROJEKTE"),
        os.path.join(OPT_DATA_DIR, "inbox"),
    ]

    written_paths = []
    # YAML-Frontmatter.values mit json.dumps quoten — ein Titel/Name mit
    # Anfuehrungszeichen oder Newline zerstoerte sonst die Obsidian-Notiz.
    import json as _json
    def _y(v: Any) -> str:
        return _json.dumps(str(v if v is not None else ""), ensure_ascii=False)
    content = f"""---
project_id: {_y(task_id)}
date: {_y(datetime.date.today().isoformat())}
agent: {_y(task.get('agent_name', 'Hermes Agent'))}
model: {_y(task.get('model', 'Universal'))}
tokens_used: {task.get('estimated_tokens', 0)}
cost_eur: {float(task.get('estimated_cost_eur', 0.0) or 0.0):.2f}
status: completed
---
# {task.get('title', 'Ohne Titel')}

## Ursprüngliche Anforderung
{task.get('capture_input') or task.get('title', '')}

## Umsetzungsplan & Ergebnisse
{task.get('result_summary') or 'Erfolgreich von Archon OS ausgeführt und validiert.'}

## Generierte Artefakte
- Pfad: {os.path.join(PROJEKTE_DIR, file_name)}
"""
    # D03/MED: autoritativer Zielpfad = PROJEKTE_DIR; alle weiteren Ziele sind
    # explizite Replikate und werden mit einem Hash-Manifest ausgewiesen.
    import hashlib as _hashlib
    content_hash = _hashlib.sha256(content.encode("utf-8")).hexdigest()
    replica_errors: List[str] = []

    for idx, d in enumerate(target_dirs):
        # Pfad-Jail: Dateiname darf nie Pfadanteile enthalten.
        f_name = safe_filename(file_name)
        try:
            os.makedirs(d, exist_ok=True)
            f_path = os.path.join(d, f_name)
            if os.path.commonpath([os.path.abspath(f_path), os.path.abspath(d)]) != os.path.abspath(d):
                raise ValueError(f"Ziel ausserhalb des erlaubten Verzeichnisses: {f_path}")
            tmp_path = os.path.join(d, f".{f_name}.tmp_{os.getpid()}_{int(time.time()*1000)}")
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, f_path)
            written_paths.append(f_path)
            logger.info(f"[Obsidian Sync] Atomar gespeichert: {'AUTHORITATIVE' if idx == 0 else 'REPLICA'} {f_path}")
        except Exception as err:
            if idx == 0:
                raise RuntimeError(
                    f"[Obsidian Sync] Autoritativer Zielpfad {d} nicht schreibbar: {err}"
                ) from err
            replica_errors.append(f"{d}: {err}")
            logger.warning(f"[Obsidian Sync] Replikat {d} fehlgeschlagen: {err}")

    final_path = written_paths[0]
    hashes = {p: content_hash for p in written_paths}
    manifest = {
        "task_id": task_id,
        "authoritative": final_path,
        "content_sha256": content_hash,
        "replicas": written_paths[1:],
        "hashes": hashes,
        "status": "partial" if replica_errors else "ok",
        "errors": replica_errors,
    }
    # Hash-Manifest atomar NEBEN das autoritative Ziel (mount-übergreifend sicher).
    m_path = final_path + ".sync_manifest.json"
    m_tmp = m_path + f".tmp_{os.getpid()}"
    try:
        with open(m_tmp, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(m_tmp, m_path)
    except Exception as err:
        replica_errors.append(f"manifest: {err}")
    status = "partial" if replica_errors else "ok"
    if replica_errors:
        logger.warning(f"[Obsidian Sync] Teilfehler — Status=partial: {replica_errors}")
    print(f"[Obsidian Sync] Speicherpfad verifiziert ({status}): {final_path}")
    return _SyncPath(final_path, status, written_paths[1:], hashes)


_LIVE_TELEMETRY_CACHE = {"ts": 0.0, "data": None, "tenant": ""}


def _get_live_telemetry_metrics() -> Dict[str, Any]:
    now_ts = time.time()
    try:
        from backend.tenant_context import tenant_context
        _tenant_id = tenant_context.get_active_tenant_id()
    except Exception:
        _tenant_id = "default"
    if (
        _LIVE_TELEMETRY_CACHE.get("tenant") == _tenant_id
        and _LIVE_TELEMETRY_CACHE["data"] is not None
        and (now_ts - _LIVE_TELEMETRY_CACHE["ts"]) < 15.0
    ):
        return _LIVE_TELEMETRY_CACHE["data"]
    all_dbs = sorted(glob.glob(os.path.join(HERMES_PROFILES_BASE, "*", "state.db")) + [STATE_DB_PATH])
    if not all_dbs:
        all_dbs = sorted(
            glob.glob(os.path.expanduser("~/.hermes/profiles/*/state.db"))
            + [os.path.expanduser("~/.hermes/state.db")]
        )

    fifteen_min_ago = now_ts - 900
    # Tagesbeginn (00:00 Uhr lokaler Kalendertag)
    today_dt = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_ts = today_dt.timestamp()

    # Performance-Optimierung: Nur DBs öffnen, die heute modifiziert wurden oder die globale state.db
    state_dbs = []
    for db in all_dbs:
        try:
            if not os.path.exists(db):
                continue
            if db.endswith("state.db") and "/profiles/" not in db:
                state_dbs.append(db)
            elif os.path.getmtime(db) >= today_start_ts:
                state_dbs.append(db)
        except Exception as exc:
            logger.warning(f"State-DB {db} konnte nicht geprueft werden: {exc}")
    if not state_dbs:
        state_dbs = [d for d in all_dbs if d.endswith("state.db") and "/profiles/" not in d] or all_dbs[:1]

    tokens_last_15m = 0
    today_cost = 0.0
    latest_model = "deepseek/deepseek-v4-flash-0731"
    latest_tokens = 0
    model_breakdown = {}
    all_sessions = []

    # Minuten-Buckets für die 15-Minuten Sparkline
    minute_buckets = [0.0] * 15

    for db in state_dbs:
        con = None
        try:
            con = sqlite3.connect(db, timeout=5.0)
            con.execute("PRAGMA busy_timeout=5000;")
            rows = con.execute(
                """
                SELECT model, input_tokens, output_tokens, estimated_cost_usd, last_seen 
                FROM session_model_usage 
                WHERE last_seen >= ?
                ORDER BY last_seen DESC LIMIT 200
            """,
                (today_start_ts,),
            ).fetchall()
            if not rows:
                rows = con.execute(
                    """
                    SELECT model, input_tokens, output_tokens, estimated_cost_usd, last_seen 
                    FROM session_model_usage 
                    ORDER BY last_seen DESC LIMIT 50
                """
                ).fetchall()
            for r in rows:
                m, inp, out, cost, lseen = r[0], r[1] or 0, r[2] or 0, r[3] or 0.0, r[4] or 0
                tot = inp + out
                all_sessions.append((lseen, m, inp, out, cost, tot))
                if m:
                    model_breakdown[m] = model_breakdown.get(m, 0.0) + cost
                # Echte Aktivität heute
                if lseen and lseen >= today_start_ts:
                    today_cost += cost
                # Echte Aktivität der letzten 15 Minuten
                if lseen and lseen >= fifteen_min_ago:
                    tokens_last_15m += tot
                    bucket_idx = min(14, max(0, int((now_ts - lseen) / 60)))
                    minute_buckets[14 - bucket_idx] += round(tot / 1000.0, 1)
        except Exception as exc:
            logger.error(f"Telemetrie-DB-Auswertung fehlgeschlagen: {exc}")
        finally:
            if con:
                con.close()

    all_sessions.sort(key=lambda x: x[0], reverse=True)
    if all_sessions:
        latest_model = all_sessions[0][1] or latest_model
        latest_tokens = all_sessions[0][5] or latest_tokens

    # Echter Durchsatz: Tokens der letzten 15 Min geteilt durch 15 Minuten
    tpm_real = int(tokens_last_15m / 15) if tokens_last_15m > 0 else 0

    # Sparkline: Wenn in den letzten 15 Min aktiv, dann die echten Minuten-Buckets. Sonst flache Null-Linie.
    sparkline_vals = minute_buckets

    top_models_cost = sorted(model_breakdown.items(), key=lambda x: x[1], reverse=True)[:5]

    res = {
        "sparkline_data": sparkline_vals,
        "today_cost": round(today_cost, 2),
        "tpm_est": tpm_real,
        "tokens_15m": tokens_last_15m,
        "latest_model": latest_model,
        "latest_tokens": latest_tokens,
        "top_models_cost": [{"model": m, "cost": round(c, 4)} for m, c in top_models_cost],
    }
    _LIVE_TELEMETRY_CACHE["ts"] = time.time()
    _LIVE_TELEMETRY_CACHE["data"] = res
    _LIVE_TELEMETRY_CACHE["tenant"] = _tenant_id
    return res
