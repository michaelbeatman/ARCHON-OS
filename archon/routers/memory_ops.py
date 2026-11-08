"""Router fuer Memory Operations (Stats, Consolidate, Evict, Chat-History & Learning)."""
from __future__ import annotations

import datetime
import logging
import os
import re
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, Body, HTTPException

logger = logging.getLogger("archon.routers.memory_ops")

router = APIRouter(tags=["memory_ops"])


def _query_memory_stats() -> tuple[int, int, int]:
    from local_memory_bridge import LocalMemoryBridge

    bridge = LocalMemoryBridge()
    learnings_cnt = 0
    conv_cnt = 0
    stale_cnt = 0
    try:
        conn = bridge._get_conn()
        cur = conn.cursor()
        learnings_cnt = cur.execute("SELECT COUNT(*) FROM learnings").fetchone()[0]
        conv_cnt = cur.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        stale_info = bridge.evict_stale_memories(threshold=0.1, table="learnings", dry_run=True)
        stale_cnt = stale_info.get("stale_count", 0)
        conn.close()
    except Exception:
        pass
    return learnings_cnt, conv_cnt, stale_cnt


@router.get("/api/v1/memory/stats")
def api_get_memory_stats():
    from local_memory_bridge import LocalMemoryBridge

    bridge = LocalMemoryBridge()
    learnings_cnt, conv_cnt, stale_cnt = _query_memory_stats()
    vault_summary = bridge.scan_vault_summary()
    vault_notes = vault_summary.get("total_notes", 0) if isinstance(vault_summary, dict) else 0

    return {
        "status": "success",
        "learnings_count": learnings_cnt,
        "conversations_count": conv_cnt,
        "stale_count": stale_cnt,
        "vault_notes_count": vault_notes,
        "vault_path": bridge.vault_path,
    }


@router.get("/api/v1/agent/{agent_id}/stats")
def api_get_agent_real_stats(agent_id: str):
    """Liefert echte Leistungsdaten aus der Personalakte und den Datenbanken."""
    import main as app_main

    obsidian_vault = getattr(app_main, "OBSIDIAN_VAULT", "/opt/data/obsidian")
    vault_dir = Path("/opt/data/obsidian") if Path("/opt/data/obsidian").exists() else Path(obsidian_vault)
    akte = vault_dir / "00_HR_Agenten" / "Personalakten" / f"{agent_id}.md"
    tasks_completed = 0
    if akte.exists():
        try:
            txt = akte.read_text(encoding="utf-8")
            m = re.search(r"tasks_completed:\s*(\d+)", txt)
            if m:
                tasks_completed = int(m.group(1))
        except Exception:
            pass

    learnings_count = 0
    try:
        from local_memory_bridge import LocalMemoryBridge

        b = LocalMemoryBridge()
        with b._get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM learnings WHERE agent_id = ?", (agent_id,))
            learnings_count = c.fetchone()[0]
    except Exception:
        pass

    return {
        "status": "ok",
        "agent_id": agent_id,
        "tasks_completed": tasks_completed,
        "learnings_count": learnings_count,
        "performance_rating": "100% nominal" if tasks_completed > 0 else "Bereit im Standby",
        "is_deployed": True,
    }


def _consolidate_internal(payload: Optional[Dict]) -> Dict:
    from local_memory_bridge import LocalMemoryBridge

    bridge = LocalMemoryBridge()
    payload = payload or {}

    with bridge._get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT agent_id, role, content, timestamp 
            FROM conversations 
            ORDER BY id DESC LIMIT 40
        """
        )
        rows = cur.fetchall()

    if not rows:
        return {"status": "empty", "message": "Keine Chat-Einträge zur Konsolidierung gefunden."}

    facts = []
    for r in reversed(rows):
        txt = (r["content"] or "").strip().replace("\n", " ")
        if len(txt) > 20 and not txt.startswith("{") and not txt.startswith("["):
            facts.append(f"- [{r['agent_id']}] {txt[:120]}")

    facts_text = "\n".join(facts[:10])
    if not facts_text:
        facts_text = "- [general] Routinemäßiger Systemdurchlauf ohne kritische Vorfälle."

    vault_path = bridge.vault_path
    note_file = None
    today = datetime.datetime.now().strftime("%Y-%m-%d")

    if os.path.exists(vault_path):
        mem_dir = os.path.join(vault_path, "memories")
        os.makedirs(mem_dir, exist_ok=True)
        note_path = os.path.join(mem_dir, f"daily_consolidation_{today}.md")
        md_content = f"""---
title: "Tages-Konsolidierung: {today}"
date: {today}
tags: ["memory", "consolidated", "daily"]
source: "Archon OS Memory Bridge"
---

# Tages-Konsolidierung: {today}

## Extrahierte Erkenntnisse
{facts_text}

---
[[00_VAULT_KNOWLEDGE]] | [[Archiv-Hubs]]
"""
        try:
            with open(note_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            note_file = note_path
        except Exception as e:
            note_file = str(e)

    with bridge._get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO learnings (agent_id, category, summary, obsidian_link, importance, accesses, last_accessed)
            VALUES (?, ?, ?, ?, 2.0, 1, CURRENT_TIMESTAMP)
        """,
            (
                "consolidator",
                "daily_summary",
                f"Tages-Zusammenfassung {today}: {len(facts)} Interaktionen analysiert",
                f"[[daily_consolidation_{today}]]",
            ),
        )
        conn.commit()

    return {
        "status": "success",
        "message": f"{len(facts)} Interaktionen konsolidiert.",
        "note_file": note_file,
        "facts_count": len(facts),
    }


@router.post("/api/v1/memory/consolidate")
def api_consolidate_memory(payload: Optional[Dict] = Body(None)):
    return _consolidate_internal(payload)


@router.post("/api/v1/memory/evict")
def api_evict_stale_memory(payload: Optional[Dict] = Body(None)):
    from local_memory_bridge import LocalMemoryBridge

    bridge = LocalMemoryBridge()
    payload = payload or {}
    threshold = float(payload.get("threshold", 0.1))
    dry_run = bool(payload.get("dry_run", False))

    res_conv = bridge.evict_stale_memories(threshold=threshold, table="conversations", dry_run=dry_run)
    res_learn = bridge.evict_stale_memories(threshold=threshold, table="learnings", dry_run=dry_run)

    return {
        "status": "success",
        "conversations_pruned": res_conv.get("stale_count", 0),
        "learnings_pruned": res_learn.get("stale_count", 0),
        "threshold": threshold,
        "dry_run": dry_run,
    }


# --- CHAT HISTORY & VAULT SUMMARY ---


@router.get("/api/v1/chat/history")
def get_chat_history_api(agent_id: str, limit: int = 30, session_id: Optional[str] = None):
    import main as app_main

    mb = getattr(app_main, "memory_bridge", None)
    if mb:
        history = mb.get_conversation_history(agent_id, limit=limit, session_id=session_id)
        return {"status": "success", "agent_id": agent_id, "history": history}
    return {"status": "success", "agent_id": agent_id, "history": []}


@router.delete("/api/v1/chat/history")
def clear_chat_history_api(agent_id: str, session_id: Optional[str] = None):
    import main as app_main

    mb = getattr(app_main, "memory_bridge", None)
    if mb:
        mb.clear_conversation_history(agent_id, session_id=session_id)
        return {"status": "success", "message": f"History for {agent_id} cleared"}
    return {"status": "error", "message": "Memory bridge unavailable"}


@router.get("/api/v1/memory/context")
def api_memory_context(agent_id: str = "hermes_default", limit: int = 5):
    import main as app_main

    mb = getattr(app_main, "memory_bridge", None)
    if not mb:
        raise HTTPException(status_code=500, detail="Memory bridge not initialized")
    return {"context": mb.get_agent_context_injection(agent_id, limit)}


@router.get("/api/v1/memory/profile")
def api_memory_profile():
    import main as app_main

    mb = getattr(app_main, "memory_bridge", None)
    if not mb:
        raise HTTPException(status_code=500, detail="Memory bridge not initialized")
    return mb.get_user_profile()


@router.post("/api/v1/memory/learning")
def api_memory_learning(
    agent_id: str = Body(...),
    category: str = Body(...),
    summary: str = Body(...),
    detailed_note: Optional[str] = Body(None),
):
    import main as app_main

    mb = getattr(app_main, "memory_bridge", None)
    if not mb:
        raise HTTPException(status_code=500, detail="Memory bridge not initialized")
    return mb.record_learning(agent_id, category, summary, detailed_note)


@router.get("/api/v1/memory/vault-summary")
def api_memory_vault_summary():
    import main as app_main

    mb = getattr(app_main, "memory_bridge", None)
    if not mb:
        raise HTTPException(status_code=500, detail="Memory bridge not initialized")
    return mb.scan_vault_summary()
