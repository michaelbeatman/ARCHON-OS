# -*- coding: utf-8 -*-
"""
backend/competitor_idea_bridge.py
=================================
Verbindet den Internet-Watchdog (Competitor-Watcher) und das ARCHON CRM
(Telegram -> PocketBase `MediaBoard`, `linkedin_content`, `media_items`)
direkt mit der Archon Content-Maschine (Vorstufe "Ideas") und dem Archon Kanban-Board.

Funktionen:
1. `import_crm_telegram_ideas_to_archon()`:
   Überträgt per Telegram ins ARCHON CRM (`pocketbase/pb_data/data.db` -> `MediaBoard`,
   `linkedin_content`, `media_items`) geschickte Links, Notizen, Screenshots und Videos
   dublettenfrei in `business.db` (`content_campaigns` mit Status `idea`) sowie ins
   Archon Kanban-Board (`triage` / `@linkedin_social_media_specialist`).
2. `ingest_watchdog_competitor_findings_to_ideas()`:
   Überführt relevante Watchdog-Funde automatisch als Content-Ideen ("Ideas"-Spalte)
   in die Content-Maschine.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import sqlite3
import unicodedata
from typing import Any, Dict, List, Optional

logger = logging.getLogger("archon.competitor_idea_bridge")

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CRM_PB_DB = os.path.join(WORKSPACE_DIR, "pocketbase", "pb_data", "data.db")
MEDIA_PB_DB = os.path.join(WORKSPACE_DIR, "pocketbase-media", "pb_data", "data.db")


def _normalize_fancy_unicode(text: str) -> str:
    """Normalizes mathematical bold/italic Unicode characters (e.g. from LinkedIn posts) to clean UTF-8."""
    if not text:
        return ""
    return unicodedata.normalize("NFKC", str(text)).strip()


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _get_business_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    from backend.content_machine import init_content_machine_db
    from backend.db_paths import get_db_connection

    init_content_machine_db(db_path)
    conn = get_db_connection(db_path or "business.db")
    conn.row_factory = sqlite3.Row
    return conn


def _insert_kanban_idea_card(
    task_id: str,
    title: str,
    body: str,
    assignee: str = "linkedin_social_media_specialist",
    status: str = "triage",
) -> bool:
    from archon.core.paths import KANBAN_DB_PATH
    from backend.db_paths import get_db_connection

    candidates = [
        KANBAN_DB_PATH,
        os.path.join(WORKSPACE_DIR, "data", "kanban.db"),
        os.path.expanduser("~/.hermes/kanban.db"),
    ]
    now_iso = datetime.datetime.now().isoformat()
    inserted = False
    for db_p in candidates:
        if not db_p or not os.path.exists(db_p):
            continue
        conn = None
        try:
            conn = get_db_connection(db_p, timeout=5.0)
            cur = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,))
            if cur.fetchone():
                continue
            conn.execute(
                """
                INSERT INTO tasks (id, title, body, assignee, status, priority, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, title, body, assignee, status, 1, "crm_watchdog_bridge", now_iso),
            )
            conn.commit()
            inserted = True
        except Exception as exc:
            logger.debug(f"[CompetitorIdeaBridge] Kanban-Insert in {db_p} uebersprungen: {exc}")
        finally:
            if conn:
                conn.close()
    return inserted


def read_crm_telegram_inbox_items(
    crm_db_path: Optional[str] = None,
    media_db_path: Optional[str] = None,
    include_media_files: bool = True,
    max_media_items: int = 25,
) -> Dict[str, Any]:
    """
    Reads all Telegram-forwarded items from ARCHON CRM (`MediaBoard`, `linkedin_content`,
    and `media_items`) without mutating the source PocketBase database.
    """
    target_crm = crm_db_path or CRM_PB_DB
    target_media = media_db_path or MEDIA_PB_DB

    mediaboard_items: List[Dict[str, Any]] = []
    linkedin_items: List[Dict[str, Any]] = []
    telegram_media: List[Dict[str, Any]] = []

    if os.path.exists(target_crm):
        conn = sqlite3.connect(target_crm, timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            tables = {
                r[0]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            if "MediaBoard" in tables:
                rows = conn.execute("SELECT * FROM MediaBoard ORDER BY created DESC").fetchall()
                for r in rows:
                    d = dict(r)
                    raw_title = _normalize_fancy_unicode(d.get("titel") or "")
                    raw_note = _normalize_fancy_unicode(d.get("notiz") or "")
                    url = str(d.get("url") or "").strip()
                    bild = str(d.get("bild") or "").strip()
                    title = raw_title or (raw_note.splitlines()[0][:80] if raw_note else f"CRM MediaBoard Fund ({d.get('id')})")
                    mediaboard_items.append({
                        "source_type": "crm_mediaboard",
                        "source_id": str(d.get("id")),
                        "title": title,
                        "url": url,
                        "note": raw_note,
                        "image_file": bild,
                        "created_at": str(d.get("created") or _utc_now_iso()),
                    })

            if "linkedin_content" in tables:
                rows = conn.execute("SELECT * FROM linkedin_content ORDER BY received_at DESC").fetchall()
                for r in rows:
                    d = dict(r)
                    title = _normalize_fancy_unicode(d.get("title") or d.get("user_note") or d.get("url") or f"LinkedIn Idea {d.get('id')}")
                    linkedin_items.append({
                        "source_type": "crm_linkedin_content",
                        "source_id": str(d.get("id")),
                        "title": title[:120],
                        "url": str(d.get("url") or ""),
                        "note": _normalize_fancy_unicode(d.get("user_note") or d.get("raw_content") or d.get("summary") or ""),
                        "draft_post": str(d.get("draft_post") or ""),
                        "status": str(d.get("status") or "inbox"),
                        "created_at": str(d.get("received_at") or _utc_now_iso()),
                    })

            if include_media_files and "media_items" in tables:
                rows = conn.execute(
                    "SELECT * FROM media_items WHERE source = 'telegram' ORDER BY received_at DESC LIMIT ?",
                    (max_media_items,),
                ).fetchall()
                for r in rows:
                    d = dict(r)
                    telegram_media.append({
                        "source_type": "crm_telegram_media",
                        "source_id": str(d.get("id")),
                        "file": str(d.get("file") or ""),
                        "original_filename": str(d.get("original_filename") or d.get("file") or ""),
                        "media_type": str(d.get("media_type") or "video"),
                        "file_size_bytes": int(d.get("file_size_bytes") or 0),
                        "status": str(d.get("status") or "unprocessed"),
                        "created_at": str(d.get("received_at") or _utc_now_iso()),
                    })
        finally:
            conn.close()

    # Optional fallback check in pocketbase-media if CRM DB had no media_items
    if include_media_files and not telegram_media and os.path.exists(target_media):
        conn = sqlite3.connect(target_media, timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            tables = {
                r[0]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            if "media_items" in tables:
                rows = conn.execute(
                    "SELECT * FROM media_items WHERE source = 'telegram' ORDER BY received_at DESC LIMIT ?",
                    (max_media_items,),
                ).fetchall()
                for r in rows:
                    d = dict(r)
                    telegram_media.append({
                        "source_type": "pb_media_telegram",
                        "source_id": str(d.get("id")),
                        "file": str(d.get("file") or ""),
                        "original_filename": str(d.get("original_filename") or d.get("file") or ""),
                        "media_type": str(d.get("media_type") or "video"),
                        "file_size_bytes": int(d.get("file_size_bytes") or 0),
                        "status": str(d.get("status") or "unprocessed"),
                        "created_at": str(d.get("received_at") or _utc_now_iso()),
                    })
        finally:
            conn.close()

    return {
        "mediaboard_count": len(mediaboard_items),
        "linkedin_content_count": len(linkedin_items),
        "telegram_media_count": len(telegram_media),
        "mediaboard_items": mediaboard_items,
        "linkedin_items": linkedin_items,
        "telegram_media": telegram_media,
    }


def import_crm_telegram_ideas_to_archon(
    *,
    crm_db_path: Optional[str] = None,
    business_db_path: Optional[str] = None,
    sync_to_kanban: bool = True,
    include_media_batch_idea: bool = True,
) -> Dict[str, Any]:
    """
    Imports all `MediaBoard` posts, `linkedin_content` notes, and Telegram media items
    from ARCHON CRM into Archon's Content-Maschine (`content_campaigns` with status='idea')
    and optionally creates Triage cards in Kanban.
    """
    inbox = read_crm_telegram_inbox_items(crm_db_path=crm_db_path)
    now_iso = _utc_now_iso()
    imported_campaigns: List[Dict[str, Any]] = []
    skipped_ids: List[str] = []
    kanban_created = 0

    candidates: List[Dict[str, Any]] = []
    for mb in inbox["mediaboard_items"]:
        candidates.append({
            "camp_id": f"camp-crm-mb-{mb['source_id']}",
            "kanban_id": f"crm-mb-{mb['source_id']}",
            "title": f"[CRM-Idee] {mb['title'][:90]}",
            "topic": mb["title"],
            "source_url": mb["url"],
            "source_notes": (
                f"Importiert aus ARCHON CRM MediaBoard (ID: {mb['source_id']}).\n"
                + (f"Screenshot/Bild: {mb['image_file']}\n" if mb.get("image_file") else "")
                + (f"\nNotiz / Volltext:\n{mb['note']}" if mb.get("note") else "")
            ).strip(),
            "pillar": "Telegram / CRM Idea Intake",
            "channels": ["linkedin", "x_threads", "newsletter"],
            "initial_body": mb.get("note") or f"Quellen-Impuls aus CRM MediaBoard: {mb['title']}\nURL: {mb['url']}",
        })

    for li in inbox["linkedin_items"]:
        candidates.append({
            "camp_id": f"camp-crm-li-{li['source_id']}",
            "kanban_id": f"crm-li-{li['source_id']}",
            "title": f"[LinkedIn-Inbox] {li['title'][:90]}",
            "topic": li["title"],
            "source_url": li["url"],
            "source_notes": li["note"],
            "pillar": "LinkedIn Telegram Inbox",
            "channels": ["linkedin"],
            "initial_body": li.get("draft_post") or li.get("note") or li["title"],
        })

    if include_media_batch_idea and inbox["telegram_media"]:
        unproc = [m for m in inbox["telegram_media"] if m.get("status") == "unprocessed"] or inbox["telegram_media"]
        vid_cnt = sum(1 for m in unproc if m.get("media_type") == "video")
        img_cnt = sum(1 for m in unproc if m.get("media_type") == "image")
        sample_files = ", ".join(m["original_filename"] for m in unproc[:8])
        batch_hash = hashlib.sha256(sample_files.encode("utf-8")).hexdigest()[:10]
        candidates.append({
            "camp_id": f"camp-crm-tgmedia-{batch_hash}",
            "kanban_id": f"crm-tgmedia-{batch_hash}",
            "title": f"[Telegram Media-Pool] {vid_cnt} Videos & {img_cnt} Bilder aus CRM zur Content-Verwertung",
            "topic": f"Repurposing der {len(unproc)} per Telegram ins ARCHON CRM gesendeten Medien ({vid_cnt} Videos, {img_cnt} Bilder)",
            "source_url": "pocketbase://media_items?source=telegram",
            "source_notes": f"Erfasste Dateien (Auswahl): {sample_files}",
            "pillar": "Telegram Video & Media Repurposing",
            "channels": ["linkedin", "youtube_shorts", "tiktok"],
            "initial_body": (
                f"Im ARCHON CRM (`pocketbase/pb_data/data.db` -> `media_items`) liegen {len(unproc)} "
                f"per Telegram eingesendete Mediendateien ({vid_cnt} Videos, {img_cnt} Bilder).\n"
                f"Top-Dateien: {sample_files}\n"
                f"Empfohlener Workflow: Über `kinocut-repurpose` & `li-repurpose` in Shorts + LinkedIn-Posts umwandeln."
            ),
        })

    with _get_business_conn(business_db_path) as conn:
        for cand in candidates:
            cid = cand["camp_id"]
            existing = conn.execute("SELECT id FROM content_campaigns WHERE id = ?", (cid,)).fetchone()
            if existing:
                skipped_ids.append(cid)
                continue

            conn.execute(
                """
                INSERT INTO content_campaigns (
                    id, title, topic, target_audience, brand_voice, pillar,
                    source_url, source_notes, channels_json, status, workflow_run_id,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'idea', '', ?, ?)
                """,
                (
                    cid,
                    cand["title"],
                    cand["topic"],
                    "DACH Entscheider, Unternehmer & Tech-Leads",
                    "voice.md (Michael Keller — Direkt, Zahlen-fokus, 0% KI-Slop)",
                    cand["pillar"],
                    cand["source_url"],
                    cand["source_notes"],
                    json.dumps(cand["channels"]),
                    now_iso,
                    now_iso,
                ),
            )

            asset_id = f"asset-{cid[-12:]}-li"
            conn.execute(
                """
                INSERT OR IGNORE INTO content_assets (
                    id, campaign_id, channel, format_type, title, hook, body,
                    cta, hashtags_json, visual_brief, quality_score, quality_report_json, status,
                    agent_id, scheduled_at, external_url, created_at, updated_at
                )
                VALUES (?, ?, 'linkedin', 'post_or_carousel', ?, ?, ?, ?, '["#ArchonOS","#Automation","#AI"]', '', 85, ?, 'draft', 'linkedin_social_media_specialist', '', ?, ?, ?)
                """,
                (
                    asset_id,
                    cid,
                    cand["title"],
                    cand["topic"][:180],
                    cand["initial_body"],
                    "Welche Erfahrung habt ihr damit in eurer Infrastruktur gemacht?",
                    json.dumps({"source": "archon_crm_transfer", "voice_profile": "config/voice.md", "score": 85, "passed": True}),
                    cand["source_url"],
                    now_iso,
                    now_iso,
                ),
            )
            imported_campaigns.append({
                "campaign_id": cid,
                "title": cand["title"],
                "source_url": cand["source_url"],
                "pillar": cand["pillar"],
                "status": "idea",
            })

            if sync_to_kanban:
                kb_body = (
                    f"📥 **Importiert aus ARCHON CRM (Telegram-Intake)**\n\n"
                    f"• **Kampagnen-ID:** `{cid}`\n"
                    f"• **Thema:** {cand['topic']}\n"
                    + (f"• **Link:** {cand['source_url']}\n" if cand["source_url"] else "")
                    + f"\n**Notiz / Rohinhalt:**\n{cand['source_notes'] or cand['initial_body']}\n\n"
                    f"**Nächster Schritt:** Mit `@linkedin_social_media_specialist` (`li-post` + `li-human` + `voice.md`) ausarbeiten."
                )
                if _insert_kanban_idea_card(
                    task_id=cand["kanban_id"],
                    title=cand["title"],
                    body=kb_body,
                    assignee="linkedin_social_media_specialist",
                    status="triage",
                ):
                    kanban_created += 1

        conn.commit()

    return {
        "status": "ok",
        "imported_count": len(imported_campaigns),
        "skipped_existing_count": len(skipped_ids),
        "kanban_cards_created": kanban_created,
        "imported_campaigns": imported_campaigns,
        "crm_source_counts": {
            "mediaboard": inbox["mediaboard_count"],
            "linkedin_content": inbox["linkedin_content_count"],
            "telegram_media": inbox["telegram_media_count"],
        },
    }


def ingest_watchdog_competitor_findings_to_ideas(
    findings: List[Dict[str, Any]],
    *,
    priority_keywords: Optional[List[str]] = None,
    min_score: float = 0.25,
    business_db_path: Optional[str] = None,
    sync_to_kanban: bool = False,
) -> Dict[str, Any]:
    """
    Automatic Competitor-Watcher -> Content Machine "Ideas" stage:
    Evaluates Watchdog findings and promotes relevant items directly into
    `content_campaigns` (`status='idea'`).
    """
    from backend.watchdog_radar_v2 import score_signal_relevance

    if not findings:
        return {"created_ideas": 0, "ideas": []}

    kws = priority_keywords or ["KI", "AI", "Agent", "n8n", "LinkedIn", "Immobilien", "KfW", "BauGB", "Cannabis", "MedTech", "ERP"]
    now_iso = _utc_now_iso()
    created_ideas: List[Dict[str, Any]] = []

    with _get_business_conn(business_db_path) as conn:
        for f in findings:
            fid = str(f.get("id") or hashlib.sha256(str(f.get("title", "")).encode()).hexdigest()[:12])
            title = _normalize_fancy_unicode(f.get("title") or "Watchdog Fund")
            snippet = _normalize_fancy_unicode(f.get("snippet") or f.get("summary") or "")
            cat = str(f.get("category") or "Competitor Radar")
            link = str(f.get("link") or "")

            rel = score_signal_relevance(title, f"{snippet} {cat}", kws, threshold=min_score)
            is_competitor_cat = any(w in cat.lower() for w in ("wettbewerb", "competitor", "linkedin", "radar", "ki", "markt"))
            if not (rel["is_signal"] or f.get("is_priority") or is_competitor_cat):
                continue

            camp_id = f"camp-wd-{fid}"
            exists = conn.execute("SELECT id FROM content_campaigns WHERE id = ?", (camp_id,)).fetchone()
            if exists:
                continue

            idea_title = f"[Competitor-Watcher: {cat}] {title[:85]}"
            notes = (
                f"Automatisch vom Archon Watchdog erfasst ({f.get('target_name') or cat}).\n"
                f"Relevanz-Score: {rel['score']} | Quelle: {link}\n"
                + (f"\nAuszug:\n{snippet}" if snippet else "")
            )
            conn.execute(
                """
                INSERT INTO content_campaigns (
                    id, title, topic, target_audience, brand_voice, pillar,
                    source_url, source_notes, channels_json, status, workflow_run_id,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'Competitor & Trend Radar', ?, ?, '["linkedin","x_threads"]', 'idea', '', ?, ?)
                """,
                (
                    camp_id,
                    idea_title,
                    title,
                    "DACH Entscheider & Tech-Gründer",
                    "voice.md (Michael Keller)",
                    link,
                    notes,
                    now_iso,
                    now_iso,
                ),
            )
            created_ideas.append({
                "campaign_id": camp_id,
                "title": idea_title,
                "source_url": link,
                "relevance_score": rel["score"],
                "status": "idea",
            })

            if sync_to_kanban:
                _insert_kanban_idea_card(
                    task_id=f"wd-idea-{fid}",
                    title=idea_title,
                    body=f"📡 **Competitor-Watcher Idee**\n\n{notes}",
                    assignee="linkedin_social_media_specialist",
                    status="triage",
                )
        conn.commit()

    return {"created_ideas": len(created_ideas), "ideas": created_ideas}
