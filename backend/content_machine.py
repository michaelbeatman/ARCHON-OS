# -*- coding: utf-8 -*-
"""
backend/content_machine.py
==========================
Phase 2.2 — Multi-Channel Content-Maschine v1 für Archon OS.
Unterstuetzt moderne 2026-Kanaele:
- LinkedIn (Text, Carousel/Dokument-Struktur, Thought-Leadership)
- YouTube Longform (Titel-CTR-Varianten, Thumbnail-Brief, Hook 0-30s, Kapitel, SEO)
- YouTube Shorts (9:16, 30-58s, 2s Visual Hook, Beat-Skript, Loop-Ende)
- TikTok (9:16, 15-60s, Pattern-Interrupt, Schnitt-Beats, Audio-Cue, Pinned-Comment-CTA)
- X / Threads / Bluesky (Hook + 5-8 knackige Thread-Posts)
- Newsletter (Betreff A/B, TL;DR, Deep-Dive, einzelner CTA)

Architektur:
- Persistenz direkt in `business.db` (keine neue verstreute SQLite-Datei!)
- Echte Multi-Agenten-Repurposing-Pipeline ueber `backend.workflow_dag_runner.run_workflow_dag`
  (Research -> Master-Skript -> Paralleler Fan-Out pro Kanal -> HITL-Freigabe-Gate -> Queue)
- Performance-Feedback-Loop: Gewinner-Muster werden automatisch in `memory_bridge` zurueckgeschrieben.
"""

from __future__ import annotations

import asyncio
import datetime
import html as _html
import json
import logging
import os
import re
import secrets
import urllib.request
from datetime import timedelta
from typing import Any, Dict, List, Optional

from backend.db_paths import get_db_connection

logger = logging.getLogger("archon.content_machine")

# Für den Feedback-Loop (voice_winner_hooks.md). Vorher undefiniert → NameError
# beim ersten Sweep, der nur als logger.debug verschluckt wurde.
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHANNEL_SPECS: Dict[str, Dict[str, Any]] = {
    "linkedin": {
        "id": "linkedin",
        "label": "LinkedIn",
        "format": "post_or_carousel",
        "aspect_ratio": "1:1 / 4:5 (PDF Carousel)",
        "max_chars": 3000,
        "hook_max_chars": 180,
        "recommended_agent": "storyteller_ghostwriter",
        "best_practices": [
            "Erste 2 Zeilen muessen vor dem 'Mehr anzeigen'-Cut neugierig machen (<=180 Zeichen).",
            "Konkrete Zahlen, Fallstudien oder kontraintuitive Erfahrungen statt generischer Tipps.",
            "3-5 relevante Hashtags, Frage als Kommentar-Ausloeser statt plumper Link-Drop.",
        ],
    },
    "youtube_longform": {
        "id": "youtube_longform",
        "label": "YouTube Longform",
        "format": "video_longform",
        "aspect_ratio": "16:9",
        "target_duration_sec": 600,
        "recommended_agent": "video_script_architect",
        "best_practices": [
            "3 klickstarke Titel-Varianten + Thumbnail-Konzept (max. 3 Woerter im Bild) VOR dem Skript.",
            "0:00-0:30 Payoff-Hook ohne langes Intro; alle 90s ein neuer Retention-Loop/Pattern-Interrupt.",
            "Saubere Kapitel-Timestamps + SEO-Beschreibung + Endscreen-Bruecke.",
        ],
    },
    "youtube_shorts": {
        "id": "youtube_shorts",
        "label": "YouTube Shorts",
        "format": "video_short",
        "aspect_ratio": "9:16",
        "target_duration_sec": 45,
        "recommended_agent": "content_repurposing_specialist",
        "best_practices": [
            "Erste 2 Sekunden: visueller Pattern-Interrupt + klare Nutzen-Aussage im On-Screen-Text.",
            "Schnelle Schnitt-Beats alle 2-3 Sekunden, keine Fuellwoerter, klarer Loop-Uebergang am Ende.",
        ],
    },
    "tiktok": {
        "id": "tiktok",
        "label": "TikTok",
        "format": "video_vertical",
        "aspect_ratio": "9:16",
        "target_duration_sec": 38,
        "recommended_agent": "content_repurposing_specialist",
        "best_practices": [
            "1,5-Sekunden-Hook (Kontrast, These oder direkte Demo), natives Tempo, Untertitel-Cues.",
            "Rewatch-Faktor & Save-Wuerdigkeit (Checkliste/Framework) + Pinned-Comment-CTA.",
        ],
    },
    "x_threads": {
        "id": "x_threads",
        "label": "X / Threads / Bluesky",
        "format": "thread",
        "aspect_ratio": "text + 16:9 visual",
        "max_chars": 280,
        "recommended_agent": "direct_response_copywriter",
        "best_practices": [
            "Post 1 = starke These + klare Zahl; 5-7 Folge-Posts mit je genau einem Gedanken.",
            "Letzter Post fasst zusammen und laedt zur Diskussion oder zum Newsletter ein.",
        ],
    },
    "newsletter": {
        "id": "newsletter",
        "label": "Newsletter",
        "format": "email_issue",
        "aspect_ratio": "html_text",
        "recommended_agent": "storyteller_ghostwriter",
        "best_practices": [
            "2 Betreffzeilen (A/B) + Preheader; 3-Zeilen TL;DR ganz oben; genau ein Haupt-CTA.",
        ],
    },
}

DEFAULT_CHANNELS = ["linkedin", "youtube_longform", "youtube_shorts", "tiktok"]
VALID_ASSET_STATUSES = ("draft", "review", "approved", "scheduled", "published", "rejected")


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _conn(db_path: Optional[str] = None):
    import sqlite3
    conn = get_db_connection(db_path or "business.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_content_machine_db(db_path: Optional[str] = None) -> None:
    """Initialisiert die Content-Maschine-Tabellen in business.db (WAL-Modus)."""
    with _conn(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS content_campaigns (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                topic TEXT NOT NULL,
                target_audience TEXT DEFAULT '',
                brand_voice TEXT DEFAULT 'Direkt, faktenbasiert, praxisnah, ohne KI-Floskeln',
                pillar TEXT DEFAULT 'Thought Leadership',
                source_url TEXT DEFAULT '',
                source_notes TEXT DEFAULT '',
                channels_json TEXT NOT NULL DEFAULT '["linkedin","youtube_longform","youtube_shorts","tiktok"]',
                status TEXT NOT NULL DEFAULT 'draft',
                workflow_run_id TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS content_assets (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                format_type TEXT NOT NULL DEFAULT 'post',
                title TEXT NOT NULL,
                hook TEXT DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                visual_brief TEXT DEFAULT '',
                hashtags_json TEXT NOT NULL DEFAULT '[]',
                cta TEXT DEFAULT '',
                duration_sec INTEGER DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'draft',
                scheduled_at TEXT DEFAULT '',
                published_at TEXT DEFAULT '',
                external_url TEXT DEFAULT '',
                decision_id TEXT DEFAULT '',
                agent_id TEXT DEFAULT '',
                quality_score INTEGER DEFAULT 0,
                quality_report_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES content_campaigns (id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS content_metrics (
                id TEXT PRIMARY KEY,
                asset_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                views INTEGER DEFAULT 0,
                likes INTEGER DEFAULT 0,
                comments INTEGER DEFAULT 0,
                shares INTEGER DEFAULT 0,
                saves INTEGER DEFAULT 0,
                watch_time_avg_sec REAL DEFAULT 0.0,
                ctr_pct REAL DEFAULT 0.0,
                conversions INTEGER DEFAULT 0,
                recorded_at TEXT NOT NULL,
                FOREIGN KEY (asset_id) REFERENCES content_assets (id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS content_repurpose_runs (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                workflow_run_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                node_summary_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_cm_assets_campaign ON content_assets(campaign_id);
            CREATE INDEX IF NOT EXISTS idx_cm_assets_status ON content_assets(status, channel);
            CREATE INDEX IF NOT EXISTS idx_cm_metrics_asset ON content_metrics(asset_id);
            """
        )
        # Migration fuer bestehende content_assets ohne quality_score / quality_report_json
        cols = {r[1] for r in conn.execute("PRAGMA table_info(content_assets)").fetchall()}
        if "quality_score" not in cols:
            conn.execute("ALTER TABLE content_assets ADD COLUMN quality_score INTEGER DEFAULT 0")
        if "quality_report_json" not in cols:
            conn.execute("ALTER TABLE content_assets ADD COLUMN quality_report_json TEXT DEFAULT '{}'")
        conn.commit()


def _row_to_campaign(row) -> Dict[str, Any]:
    d = dict(row)
    try:
        d["channels"] = json.loads(d.pop("channels_json", "[]") or "[]")
    except (ValueError, TypeError):
        d["channels"] = list(DEFAULT_CHANNELS)
    return d


def _row_to_asset(row) -> Dict[str, Any]:
    d = dict(row)
    try:
        d["hashtags"] = json.loads(d.pop("hashtags_json", "[]") or "[]")
    except (ValueError, TypeError):
        d["hashtags"] = []
    try:
        d["quality_report"] = json.loads(d.pop("quality_report_json", "{}") or "{}")
    except (ValueError, TypeError):
        d["quality_report"] = {}
    return d


_AI_SLOP_PHRASES = (
    "delve",
    "leverage",
    "cutting-edge",
    "paradigm",
    "tapestry",
    "nestled",
    "game-changer",
    "tauchen wir ein",
    "in der heutigen schnelllebigen",
    "zusammenfassend laesst sich sagen",
    "zusammenfassend lässt sich sagen",
    "es ist wichtig zu beachten",
    "bahnbrechend",
    "revolutioniert die art und weise",
)


def evaluate_asset_quality(asset: Dict[str, Any]) -> Dict[str, Any]:
    """Bewertet ein Content-Asset deterministisch (Anti-AI-Slop, Hook-Laenge, Zahlen-Anker, CTA)."""
    channel = str(asset.get("channel") or "linkedin").lower()
    hook = str(asset.get("hook") or "").strip()
    body = str(asset.get("body") or "").strip()
    cta = str(asset.get("cta") or "").strip()
    combined = f"{hook}\n{body}".lower()

    score = 100
    issues: List[str] = []
    suggestions: List[str] = []

    slop_hits = [p for p in _AI_SLOP_PHRASES if p in combined]
    if slop_hits:
        penalty = min(35, 12 * len(slop_hits))
        score -= penalty
        issues.append(f"KI-Floskeln erkannt: {', '.join(slop_hits[:4])}")
        suggestions.append("Ersetze generische Floskeln durch konkrete Praxis-Aussagen.")

    if not hook:
        score -= 25
        issues.append("Hook fehlt komplett.")
        suggestions.append("Starke Eroeffnungszeile mit konkretem Nutzen oder Kontrast ergaenzen.")
    elif channel in ("linkedin", "youtube_shorts", "tiktok", "x_threads") and len(hook) > 180:
        score -= 12
        issues.append(f"Hook zu lang ({len(hook)} Zeichen > 180).")
        suggestions.append("Hook auf <= 180 Zeichen kuerzen, damit er vor dem Cut komplett sichtbar bleibt.")

    if len(body) < 40:
        score -= 20
        issues.append("Body ist zu kurz (< 40 Zeichen).")
        suggestions.append("Inhalt mit konkreten Schritten oder Argumenten ausarbeiten.")

    if not re.search(r"\d+", f"{hook} {body}"):
        score -= 10
        issues.append("Kein konkreter Zahlen- oder Fakten-Anker gefunden.")
        suggestions.append("Mindestens eine konkrete Zahl, Dauer, Prozentangabe oder Fallzahl einbauen.")

    if not cta:
        score -= 8
        issues.append("Call-to-Action (CTA) fehlt.")
        suggestions.append("Klaren CTA oder Diskussionsfrage am Ende hinzufuegen.")

    if combined.count("—") > 3:
        score -= 5
        issues.append("Uebermaessige Nutzung von Gedankenstrichen.")

    score = max(0, min(100, score))
    return {
        "score": score,
        "passed": score >= 70 and not slop_hits,
        "slop_hits": slop_hits,
        "issues": issues,
        "suggestions": suggestions,
    }


def list_channel_specs() -> List[Dict[str, Any]]:
    return list(CHANNEL_SPECS.values())


def create_campaign(payload: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    init_content_machine_db(db_path)
    title = str(payload.get("title") or "").strip()
    topic = str(payload.get("topic") or title).strip()
    if not title:
        raise ValueError("Kampagnen-Titel ('title') ist erforderlich.")

    raw_channels = payload.get("channels") or DEFAULT_CHANNELS
    channels = [c for c in raw_channels if c in CHANNEL_SPECS]
    if not channels:
        channels = list(DEFAULT_CHANNELS)

    cid = f"camp-{secrets.token_hex(4)}"
    now = _utc_now_iso()
    with _conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO content_campaigns (
                id, title, topic, target_audience, brand_voice, pillar,
                source_url, source_notes, channels_json, status, workflow_run_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', '', ?, ?)
            """,
            (
                cid,
                title,
                topic,
                str(payload.get("target_audience") or "Entscheider, Gruender & Tech-Interessierte").strip(),
                str(payload.get("brand_voice") or "Direkt, faktenbasiert, praxisnah, ohne KI-Floskeln").strip(),
                str(payload.get("pillar") or "Thought Leadership").strip(),
                str(payload.get("source_url") or "").strip(),
                str(payload.get("source_notes") or "").strip(),
                json.dumps(channels),
                now,
                now,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM content_campaigns WHERE id = ?", (cid,)).fetchone()
    return _row_to_campaign(row)


def list_campaigns(limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    init_content_machine_db(db_path)
    with _conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM content_campaigns ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(200, int(limit))),),
        ).fetchall()
    return [_row_to_campaign(r) for r in rows]


def get_campaign(campaign_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    init_content_machine_db(db_path)
    with _conn(db_path) as conn:
        row = conn.execute("SELECT * FROM content_campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if not row:
            return None
        camp = _row_to_campaign(row)
        assets = conn.execute(
            "SELECT * FROM content_assets WHERE campaign_id = ? ORDER BY created_at DESC",
            (campaign_id,),
        ).fetchall()
        runs = conn.execute(
            "SELECT * FROM content_repurpose_runs WHERE campaign_id = ? ORDER BY created_at DESC LIMIT 10",
            (campaign_id,),
        ).fetchall()
    camp["assets"] = [_row_to_asset(a) for a in assets]
    camp["repurpose_runs"] = [dict(r) for r in runs]
    return camp


def delete_campaign(campaign_id: str, db_path: Optional[str] = None) -> bool:
    init_content_machine_db(db_path)
    with _conn(db_path) as conn:
        conn.execute("DELETE FROM content_assets WHERE campaign_id = ?", (campaign_id,))
        cur = conn.execute("DELETE FROM content_campaigns WHERE id = ?", (campaign_id,))
        conn.commit()
        return cur.rowcount > 0


def create_asset(payload: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    init_content_machine_db(db_path)
    campaign_id = str(payload.get("campaign_id") or "").strip()
    channel = str(payload.get("channel") or "linkedin").strip().lower()
    if channel not in CHANNEL_SPECS:
        raise ValueError(f"Unbekannter Kanal: {channel!r}")
    title = str(payload.get("title") or f"{CHANNEL_SPECS[channel]['label']} Asset").strip()
    status = str(payload.get("status") or "draft").strip().lower()
    if status not in VALID_ASSET_STATUSES:
        status = "draft"

    aid = f"asset-{secrets.token_hex(4)}"
    now = _utc_now_iso()
    hashtags = payload.get("hashtags") if isinstance(payload.get("hashtags"), list) else []
    q_report = evaluate_asset_quality(
        {
            "channel": channel,
            "hook": payload.get("hook") or "",
            "body": payload.get("body") or "",
            "cta": payload.get("cta") or "",
        }
    )
    with _conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO content_assets (
                id, campaign_id, channel, format_type, title, hook, body, visual_brief,
                hashtags_json, cta, duration_sec, status, scheduled_at, published_at,
                external_url, decision_id, agent_id, quality_score, quality_report_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                aid,
                campaign_id,
                channel,
                str(payload.get("format_type") or CHANNEL_SPECS[channel]["format"]),
                title,
                str(payload.get("hook") or "").strip(),
                str(payload.get("body") or "").strip(),
                str(payload.get("visual_brief") or "").strip(),
                json.dumps([str(h).strip() for h in hashtags if str(h).strip()]),
                str(payload.get("cta") or "").strip(),
                int(payload.get("duration_sec") or CHANNEL_SPECS[channel].get("target_duration_sec") or 0),
                status,
                str(payload.get("scheduled_at") or "").strip(),
                str(payload.get("external_url") or "").strip(),
                str(payload.get("decision_id") or "").strip(),
                str(payload.get("agent_id") or CHANNEL_SPECS[channel]["recommended_agent"]),
                int(q_report["score"]),
                json.dumps(q_report, ensure_ascii=False),
                now,
                now,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM content_assets WHERE id = ?", (aid,)).fetchone()
    return _row_to_asset(row)


def list_assets(
    *,
    campaign_id: Optional[str] = None,
    channel: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    init_content_machine_db(db_path)
    clauses: List[str] = []
    params: List[Any] = []
    if campaign_id:
        clauses.append("campaign_id = ?")
        params.append(campaign_id)
    if channel:
        clauses.append("channel = ?")
        params.append(channel.lower())
    if status:
        clauses.append("status = ?")
        params.append(status.lower())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, min(500, int(limit))))
    with _conn(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM content_assets {where} ORDER BY updated_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [_row_to_asset(r) for r in rows]


def update_asset(asset_id: str, patch: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    init_content_machine_db(db_path)
    allowed_fields = {
        "title", "hook", "body", "visual_brief", "cta", "status",
        "scheduled_at", "published_at", "external_url", "duration_sec", "format_type",
    }
    sets: List[str] = []
    params: List[Any] = []
    for k, v in (patch or {}).items():
        if k == "hashtags" and isinstance(v, list):
            sets.append("hashtags_json = ?")
            params.append(json.dumps([str(h).strip() for h in v if str(h).strip()]))
        elif k in allowed_fields:
            if k == "status" and str(v).lower() not in VALID_ASSET_STATUSES:
                raise ValueError(f"Ungueltiger Asset-Status: {v!r}")
            sets.append(f"{k} = ?")
            params.append(v)
    if not sets:
        raise ValueError("Keine gueltigen Felder zum Aktualisieren uebergeben.")
    sets.append("updated_at = ?")
    params.append(_utc_now_iso())

    with _conn(db_path) as conn:
        existing_row = conn.execute("SELECT * FROM content_assets WHERE id = ?", (asset_id,)).fetchone()
        if not existing_row:
            raise KeyError(f"Content-Asset '{asset_id}' nicht gefunden.")
        merged_for_q = {**_row_to_asset(existing_row), **(patch or {})}
        q_report = evaluate_asset_quality(merged_for_q)
        sets.append("quality_score = ?")
        params.append(int(q_report["score"]))
        sets.append("quality_report_json = ?")
        params.append(json.dumps(q_report, ensure_ascii=False))
        params.append(asset_id)
        conn.execute(f"UPDATE content_assets SET {', '.join(sets)} WHERE id = ?", params)
        conn.commit()
        row = conn.execute("SELECT * FROM content_assets WHERE id = ?", (asset_id,)).fetchone()
    return _row_to_asset(row)


def _enforce_asset_quality(conn, row) -> Dict[str, Any]:
    """P1: Quality-Gate als echte Freigabebedingung (nicht nur Anzeige).

    Nutzt den gespeicherten Report, falls vorhanden; andernfalls wird er aus
    dem Asset neu berechnet. Ohne bestandenen Gate darf kein Asset in
    'approved'/'scheduled'/'published' uebergehen.
    """
    raw = None
    try:
        if "quality_report" in row.keys():
            raw = row["quality_report"]
    except Exception:
        raw = None
    report: Optional[Dict[str, Any]] = None
    if raw:
        try:
            report = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except Exception:
            report = None
    if not isinstance(report, dict):
        report = evaluate_asset_quality(_row_to_asset(row))
    if not report.get("passed", False):
        issues = "; ".join(str(i) for i in (report.get("issues") or [])[:3]) or "keine Details"
        raise ValueError(
            f"Quality-Gate blockiert Freigabe (Score {report.get('score', 0)}/100): {issues}"
        )
    return report


def approve_asset(asset_id: str, scheduled_at: str = "", db_path: Optional[str] = None) -> Dict[str, Any]:
    """Nur review/draft → approved/scheduled. Direktes draft→published ist
    damit nicht mehr möglich (HITL-Gate-Umgehung)."""
    new_status = "scheduled" if scheduled_at else "approved"
    now = _utc_now_iso()
    with _conn(db_path) as conn:
        row = conn.execute("SELECT * FROM content_assets WHERE id = ?", (asset_id,)).fetchone()
        if not row:
            raise KeyError(f"Content-Asset '{asset_id}' nicht gefunden.")
        cur = str(row["status"] or "")
        if cur not in ("review", "draft"):
            raise ValueError(f"Unzulässiger Statusübergang: {cur} → {new_status}")
        # P1: Der Quality-Score war bisher Dashboard-Kosmetik — approve_asset()
        # pruefte nur den Status. Ein Score-0-Asset mit KI-Floskeln konnte
        # freigegeben und publiziert werden.
        _enforce_asset_quality(conn, row)
        cur_update = conn.execute(
            "UPDATE content_assets SET status = ?, scheduled_at = ?, updated_at = ? "
            "WHERE id = ? AND status IN ('review', 'draft')",
            (new_status, str(scheduled_at or ""), now, asset_id),
        )
        if int(cur_update.rowcount or 0) != 1:
            raise ValueError("Statusübergang wurde concurrently geändert — bitte erneut prüfen.")
        conn.commit()
        row = conn.execute("SELECT * FROM content_assets WHERE id = ?", (asset_id,)).fetchone()
    return _row_to_asset(row)


def mark_asset_published(asset_id: str, external_url: str = "", db_path: Optional[str] = None) -> Dict[str, Any]:
    """Publish nur aus approved/scheduled — niemals direkt aus draft/review."""
    now = _utc_now_iso()
    with _conn(db_path) as conn:
        row = conn.execute("SELECT * FROM content_assets WHERE id = ?", (asset_id,)).fetchone()
        if not row:
            raise KeyError(f"Content-Asset '{asset_id}' nicht gefunden.")
        cur = str(row["status"] or "")
        if cur not in ("approved", "scheduled"):
            raise ValueError(f"Unzulässiger Statusübergang: {cur} → published")
        _enforce_asset_quality(conn, row)
        cur_update = conn.execute(
            "UPDATE content_assets SET status = 'published', published_at = ?, external_url = ?, updated_at = ? "
            "WHERE id = ? AND status IN ('approved', 'scheduled')",
            (now, str(external_url or "").strip(), now, asset_id),
        )
        if int(cur_update.rowcount or 0) != 1:
            raise ValueError("Statusübergang wurde concurrently geändert — bitte erneut prüfen.")
        conn.commit()
        row = conn.execute("SELECT * FROM content_assets WHERE id = ?", (asset_id,)).fetchone()
    return _row_to_asset(row)


def record_asset_metrics(
    asset_id: str,
    metrics: Dict[str, Any],
    *,
    write_learning_to_memory: bool = True,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Speichert Kanal-Performance-Daten und schreibt starke Muster ins Langzeitgedaechtnis."""
    init_content_machine_db(db_path)
    with _conn(db_path) as conn:
        asset_row = conn.execute("SELECT * FROM content_assets WHERE id = ?", (asset_id,)).fetchone()
        if not asset_row:
            raise KeyError(f"Content-Asset '{asset_id}' nicht gefunden.")
        asset = _row_to_asset(asset_row)

        mid = f"met-{secrets.token_hex(4)}"
        now = _utc_now_iso()
        views = max(0, int(metrics.get("views") or 0))
        likes = max(0, int(metrics.get("likes") or 0))
        comments = max(0, int(metrics.get("comments") or 0))
        shares = max(0, int(metrics.get("shares") or 0))
        saves = max(0, int(metrics.get("saves") or 0))
        watch_time = max(0.0, float(metrics.get("watch_time_avg_sec") or 0.0))
        ctr = max(0.0, float(metrics.get("ctr_pct") or 0.0))
        conversions = max(0, int(metrics.get("conversions") or 0))

        conn.execute(
            """
            INSERT INTO content_metrics (
                id, asset_id, channel, views, likes, comments, shares, saves,
                watch_time_avg_sec, ctr_pct, conversions, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (mid, asset_id, asset["channel"], views, likes, comments, shares, saves, watch_time, ctr, conversions, now),
        )
        conn.commit()

    eng_rate = round(((likes + comments * 2 + shares * 3 + saves * 2) / views) * 100.0, 2) if views > 0 else 0.0

    # Performance-Feedback-Loop: Starke Hooks (>=5% Engagement oder >=1000 Views) als Learning speichern
    learning_saved = False
    if write_learning_to_memory and (eng_rate >= 5.0 or views >= 1000):
        try:
            from local_memory_bridge import memory_bridge
            summary = (
                f"Content-Winner ({asset['channel']}): '{asset['title']}' erzielte {views} Views "
                f"({eng_rate}% Engagement, CTR {ctr}%). Erfolgreiche Hook: {asset['hook'][:160]}"
            )
            memory_bridge.record_learning(
                agent_id=asset.get("agent_id") or "content_repurposing_specialist",
                category=f"content_{asset['channel']}",
                summary=summary,
            )
            learning_saved = True
        except Exception as exc:
            logger.debug(f"[ContentMachine] Learning-Sync uebersprungen: {exc}")

    return {
        "id": mid,
        "asset_id": asset_id,
        "channel": asset["channel"],
        "views": views,
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "saves": saves,
        "watch_time_avg_sec": watch_time,
        "ctr_pct": ctr,
        "conversions": conversions,
        "engagement_rate_pct": eng_rate,
        "learning_saved": learning_saved,
        "recorded_at": now,
    }


def get_content_analytics(db_path: Optional[str] = None) -> Dict[str, Any]:
    init_content_machine_db(db_path)
    with _conn(db_path) as conn:
        by_channel_rows = conn.execute(
            """
            SELECT channel, COUNT(*) AS assets,
                   SUM(CASE WHEN status='published' THEN 1 ELSE 0 END) AS published,
                   SUM(CASE WHEN status IN ('approved','scheduled') THEN 1 ELSE 0 END) AS ready
            FROM content_assets GROUP BY channel
            """
        ).fetchall()
        metric_rows = conn.execute(
            """
            SELECT m.channel, SUM(m.views) AS views, SUM(m.likes) AS likes,
                   SUM(m.comments) AS comments, SUM(m.shares) AS shares,
                   SUM(m.saves) AS saves, AVG(m.ctr_pct) AS avg_ctr,
                   SUM(m.conversions) AS conversions
            FROM content_metrics m GROUP BY m.channel
            """
        ).fetchall()
        top_rows = conn.execute(
            """
            SELECT a.id, a.title, a.channel, a.hook,
                   MAX(m.views) AS views, MAX(m.likes) AS likes,
                   MAX(m.shares) AS shares, MAX(m.ctr_pct) AS ctr_pct
            FROM content_assets a
            JOIN content_metrics m ON m.asset_id = a.id
            GROUP BY a.id
            ORDER BY views DESC LIMIT 10
            """
        ).fetchall()

    return {
        "by_channel": [dict(r) for r in by_channel_rows],
        "metrics_by_channel": [dict(r) for r in metric_rows],
        "top_assets": [dict(r) for r in top_rows],
    }


def get_content_overview(db_path: Optional[str] = None) -> Dict[str, Any]:
    init_content_machine_db(db_path)
    campaigns = list_campaigns(limit=50, db_path=db_path)
    assets = list_assets(limit=150, db_path=db_path)
    status_counts: Dict[str, int] = {s: 0 for s in VALID_ASSET_STATUSES}
    for a in assets:
        st = a.get("status", "draft")
        status_counts[st] = status_counts.get(st, 0) + 1
    analytics = get_content_analytics(db_path=db_path)
    return {
        "channels": list_channel_specs(),
        "campaigns": campaigns,
        "assets": assets,
        "status_counts": status_counts,
        "analytics": analytics,
    }


def build_content_repurposing_dag(campaign: Dict[str, Any], *, require_hitl_gate: bool = True) -> Dict[str, Any]:
    """Erzeugt einen ausfuehrbaren Multi-Agenten-DAG fuer `workflow_dag_runner.run_workflow_dag`."""
    topic = campaign.get("topic") or campaign.get("title") or ""
    audience = campaign.get("target_audience") or "Entscheider & Gruender"
    voice = campaign.get("brand_voice") or "Direkt, faktenbasiert, praxisnah"
    notes = campaign.get("source_notes") or ""

    # P1/Content B6: Feedback-Loop war Write-Only. voice_winner_hooks.md und
    # config/voice.md wurden gespeichert, aber nie in Prompts geladen. Jetzt
    # werden Top-Learnings + Voice-Dateien als aktiver Kontext injiziert.
    feedback_lines: List[str] = []
    try:
        from local_memory_bridge import memory_bridge
        learnings = memory_bridge.search_learnings(str(topic)[:100], limit=5, agent_id="content_machine")
        for learning in learnings or []:
            summary = str(learning.get("summary") or "").strip()
            if summary:
                feedback_lines.append(f"- [Learning] {summary[:220]}")
    except Exception as exc:
        logger.debug(f"[ContentMachine] Learning-Feedback nicht verfuegbar: {exc}")
    for voice_file in ("config/voice.md", "config/voice_winner_hooks.md"):
        try:
            vpath = os.path.join(WORKSPACE_DIR, voice_file)
            if os.path.isfile(vpath):
                with open(vpath, "r", encoding="utf-8") as _vf:
                    text = _vf.read().strip()
                if text:
                    lines = [ln.strip(" -#*") for ln in text.splitlines() if ln.strip()][:8]
                    feedback_lines.append(f"- [{os.path.basename(vpath)}] " + " | ".join(lines))
        except Exception as exc:
            logger.debug(f"[ContentMachine] {voice_file} nicht lesbar: {exc}")
    feedback_addon = (
        "\n\n### ERFOLGREICHE MUSTER AUS VERGANGENEN CAMPAIGNS\n" + "\n".join(feedback_lines)
        if feedback_lines else ""
    )

    channels = [c for c in (campaign.get("channels") or DEFAULT_CHANNELS) if c in CHANNEL_SPECS]
    if not channels:
        channels = list(DEFAULT_CHANNELS)

    nodes: List[Dict[str, Any]] = [
        {
            "id": "n_research",
            "title": f"Trend- & Fakten-Research: {campaign['title']}",
            # P1/Content B1: echter Tool-Knoten (run_research_mission_v2) statt
            # eines Prompt-Agenten. Ergebnis enthaelt `sources` + `verdict`.
            "type": "research",
            "agent_id": "research_scout",
            "depends_on": [],
            "query": (
                f"{topic} — Zielgruppe: {audience}. "
                f"Faktenbasierte Thesen, Pain-Points, konkrete Zahlen. "
                f"Quell-Notizen: {notes or 'keine'}"
            ),
            "max_rounds": 2,
            "max_pages": 4,
            "expected_output": "Quellenbasierte Synthese mit verifizierten Belegquellen.",
        },
        {
            "id": "n_master_brief",
            "title": f"Master-Storyline & Hook-Matrix: {campaign['title']}",
            "type": "agent",
            "agent_id": "video_script_architect",
            "depends_on": ["n_research"],
            "prompt": (
                f"Erstelle auf Basis des Research die zentrale Storyline fuer '{topic}'.\n"
                f"Tonalitaet: {voice}.\n"
                "ZITATIONSPFLICHT: Jede konkrete Zahl oder Behauptung muss auf eine der "
                "Belegquellen aus dem Research-Schritt zurueckzufuehren sein. Keine "
                "Fakten aus dem Modellgedaechtnis erfinden.\n"
                f"{feedback_addon}\n"
                "Liefere: Kernbotschaft in 1 Satz, 5 starke Hooks, visuelle Leitidee und einen klaren CTA."
            ),
            "expected_output": "Master-Brief mit Kernbotschaft, 5 Hooks und Story-Bogen.",
        },
    ]

    edges: List[Dict[str, Any]] = [
        {"from": "n_research", "to": "n_master_brief", "condition": "on_success", "data_mode": "full"},
    ]

    channel_node_ids: List[str] = []
    for ch in channels:
        spec = CHANNEL_SPECS[ch]
        nid = f"n_ch_{ch}"
        channel_node_ids.append(nid)
        rules = "\n- ".join(spec.get("best_practices") or [])
        nodes.append({
            "id": nid,
            "title": f"Kanal-Asset ({spec['label']}): {campaign['title']}",
            "type": "agent",
            "agent_id": spec["recommended_agent"],
            "channel": ch,
            "depends_on": ["n_master_brief"],
            "prompt": (
                f"Transformiere die Master-Storyline in ein publikationsfertiges Asset fuer {spec['label']} "
                f"(Format: {spec['format']}, Seitenverhaeltnis: {spec['aspect_ratio']}).\n"
                f"Tonalitaet: {voice}.\n"
                f"Kanal-Regeln:\n- {rules}\n\n"
                "ZITATIONSPFLICHT: Fakten und Zahlen nur aus den Belegquellen des "
                "Research-Schritts. Unbelegte Behauptungen weglassen.\n\n"
                "Antworte als JSON-Objekt mit den Schluesseln: "
                "title, hook, body, visual_brief, hashtags (Liste), cta."
            ),
            "expected_output": f"JSON-Objekt fuer {spec['label']} inkl. Hook, Body, Visual-Brief und CTA.",
        })
        edges.append({"from": "n_master_brief", "to": nid, "condition": "on_success", "data_mode": "full"})

    if require_hitl_gate:
        nodes.append({
            "id": "n_editorial_gate",
            "title": f"Redaktions-Freigabe (HITL): {campaign['title']}",
            "type": "gate",
            "depends_on": channel_node_ids,
        })
        for cnid in channel_node_ids:
            edges.append({"from": cnid, "to": "n_editorial_gate", "condition": "on_success", "data_mode": "summary"})

    return {
        "id": f"content-dag-{campaign['id']}",
        "campaign_id": campaign["id"],
        "nodes": nodes,
        "edges": edges,
    }


def _parse_asset_output(channel: str, campaign_title: str, raw_out: Dict[str, Any]) -> Dict[str, Any]:
    """Extrahiert strukturiertes Asset aus Agenten-Output (JSON oder Markdown-Fallback)."""
    spec = CHANNEL_SPECS[channel]
    content = str(raw_out.get("content") or raw_out.get("result") or "").strip()
    parsed: Dict[str, Any] = {}
    if content:
        # JSON-Block extrahieren falls in ```json ... ``` eingepackt
        cleaned = content
        if "```" in cleaned:
            for block in cleaned.split("```"):
                b = block.strip()
                if b.startswith("json"):
                    b = b[4:].strip()
                if b.startswith("{") and b.endswith("}"):
                    cleaned = b
                    break
        try:
            obj = json.loads(cleaned)
            if isinstance(obj, dict):
                parsed = obj
        except (ValueError, TypeError):
            parsed = {}

    first_line = next((ln.strip() for ln in content.splitlines() if ln.strip()), "")[:180]
    return {
        "channel": channel,
        "format_type": spec["format"],
        "title": str(parsed.get("title") or f"{spec['label']}: {campaign_title}")[:160],
        "hook": str(parsed.get("hook") or first_line)[:400],
        "body": str(parsed.get("body") or content or f"[Entwurf fuer {spec['label']} zu '{campaign_title}']"),
        "visual_brief": str(parsed.get("visual_brief") or f"Format {spec['aspect_ratio']}, klare Typografie, hohe Kontraste"),
        "hashtags": parsed.get("hashtags") if isinstance(parsed.get("hashtags"), list) else [f"#{channel}", "#ArchonOS"],
        "cta": str(parsed.get("cta") or "Kommentiere deine Erfahrung oder folge fuer Teil 2."),
        "duration_sec": int(parsed.get("duration_sec") or spec.get("target_duration_sec") or 0),
        "agent_id": str(raw_out.get("agent_id") or spec["recommended_agent"]),
    }


async def run_content_campaign_pipeline(
    campaign_id: str,
    *,
    require_hitl_gate: bool = True,
    gate_approvals: Optional[Dict[str, bool]] = None,
    dry_run: bool = False,
    executor_fn=None,
    db_path: Optional[str] = None,
    dag_db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Startet die Multi-Agenten-Content-Pipeline ueber `workflow_dag_runner` und speichert alle Kanal-Assets."""
    from backend.workflow_dag_runner import run_workflow_dag

    camp = get_campaign(campaign_id, db_path=db_path)
    if not camp:
        raise KeyError(f"Content-Kampagne '{campaign_id}' nicht gefunden.")

    dag_def = build_content_repurposing_dag(camp, require_hitl_gate=require_hitl_gate)

    eff_executor = executor_fn
    if dry_run and eff_executor is None:
        async def _dry_exec(node: Dict[str, Any], upstream: Dict[str, Any]) -> Dict[str, Any]:
            ch = node.get("channel")
            if ch and ch in CHANNEL_SPECS:
                spec = CHANNEL_SPECS[ch]
                sample = {
                    "title": f"{spec['label']}: {camp['title']}",
                    "hook": f"Warum 90% bei '{camp['topic']}' Zeit verlieren — und was 2026 wirklich wirkt.",
                    "body": f"[Dry-Run {spec['label']} Skript/Post zu '{camp['topic']}' basierend auf {sorted(upstream.keys())}]",
                    "visual_brief": f"{spec['aspect_ratio']} — Dynamischer Einstieg, klare Daten-Grafik.",
                    "hashtags": [f"#{ch}", "#AIWorkflows", "#ArchonOS"],
                    "cta": "Speichern fuer spaeter und Meinung in die Kommentare.",
                }
                return {"status": "success", "agent_id": node.get("agent_id"), "content": json.dumps(sample, ensure_ascii=False)}
            return {
                "status": "success",
                "agent_id": node.get("agent_id"),
                "content": f"[Dry-Run Ergebnis fuer {node.get('id')}: {camp['topic']}]",
            }
        eff_executor = _dry_exec

    run_res = await run_workflow_dag(
        dag_def=dag_def,
        executor_fn=eff_executor,
        gate_approvals=gate_approvals,
        db_path=dag_db_path,
    )

    created_assets: List[Dict[str, Any]] = []
    outputs = run_res.get("outputs") or {}
    gate_out = outputs.get("n_editorial_gate") or {}
    decision_id = str(gate_out.get("decision_id") or "")
    gate_approved = run_res.get("node_statuses", {}).get("n_editorial_gate") == "completed"

    for node in dag_def["nodes"]:
        ch = node.get("channel")
        nid = node["id"]
        if not ch or nid not in outputs:
            continue
        if run_res.get("node_statuses", {}).get(nid) not in ("completed", "skipped_cached"):
            continue
        asset_data = _parse_asset_output(ch, camp["title"], outputs[nid])
        asset_data["campaign_id"] = campaign_id
        asset_data["status"] = "approved" if gate_approved else ("review" if require_hitl_gate else "draft")
        asset_data["decision_id"] = decision_id
        created_assets.append(create_asset(asset_data, db_path=db_path))

    now = _utc_now_iso()
    run_rec_id = f"crun-{secrets.token_hex(4)}"
    camp_status = "completed" if run_res.get("status") == "completed" else (
        "in_review" if run_res.get("status") == "paused" else "failed"
    )
    with _conn(db_path) as conn:
        conn.execute(
            "UPDATE content_campaigns SET status = ?, workflow_run_id = ?, updated_at = ? WHERE id = ?",
            (camp_status, run_res["run_id"], now, campaign_id),
        )
        conn.execute(
            """
            INSERT INTO content_repurpose_runs (id, campaign_id, workflow_run_id, status, node_summary_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_rec_id, campaign_id, run_res["run_id"], run_res["status"], json.dumps(run_res.get("node_statuses") or {}), now, now),
        )
        conn.commit()

    return {
        "campaign_id": campaign_id,
        "campaign_status": camp_status,
        "workflow_run_id": run_res["run_id"],
        "dag_status": run_res["status"],
        "node_statuses": run_res.get("node_statuses") or {},
        "decision_id": decision_id,
        "assets_created": created_assets,
    }


# =========================================================================
# CONTENT-MASCHINE v2: QUELLEN-INGESTION, CLIP-MATRIX & PUBLISHING-BRIDGE
# =========================================================================

def _strip_html_to_text(raw_html: str) -> tuple[str, str]:
    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, flags=re.IGNORECASE | re.DOTALL)
    title = _html.unescape(re.sub(r"\s+", " ", title_match.group(1)).strip()) if title_match else ""
    cleaned = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", raw_html, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = _html.unescape(re.sub(r"\s+", " ", cleaned)).strip()
    return title, cleaned


def ingest_source_to_campaign(payload: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    """Erstellt eine Multi-Channel-Kampagne aus URL (SSRF-geschuetzt), Obsidian-Notiz oder Transkript."""
    source_type = str(payload.get("source_type") or "transcript").strip().lower()
    extracted_title = str(payload.get("title") or "").strip()
    source_url = str(payload.get("source_url") or "").strip()
    extracted_text = ""

    if source_type == "url":
        from utils.egress_guard import check_public_url
        from utils.safe_http import safe_http_request
        safe_url = check_public_url(source_url)
        _st, _hd, raw_bytes = safe_http_request(
            source_url,
            headers={"User-Agent": "ArchonOS-ContentIngest/2.0"},
            timeout=10.0,
            max_bytes=512 * 1024,
            public_only=True,
        )
        raw = raw_bytes.decode("utf-8", errors="ignore")
        page_title, extracted_text = _strip_html_to_text(raw)
        if not extracted_title:
            extracted_title = page_title or safe_url
    elif source_type == "obsidian":
        from backend.platform_paths import OBSIDIAN_VAULT, OBSIDIAN_VAULT_ALT
        from utils.path_jail import safe_path_within
        rel_or_abs = str(payload.get("obsidian_path") or "").strip()
        roots = [r for r in (OBSIDIAN_VAULT, OBSIDIAN_VAULT_ALT) if r]
        candidate = rel_or_abs if os.path.isabs(rel_or_abs) else os.path.join(roots[0], rel_or_abs)
        safe_file = safe_path_within(candidate, roots, must_exist=True, allow_dirs=False)
        with open(safe_file, "r", encoding="utf-8", errors="ignore") as fh:
            extracted_text = fh.read(256 * 1024).strip()
        if not extracted_title:
            first_h1 = next((ln.lstrip("# ").strip() for ln in extracted_text.splitlines() if ln.strip().startswith("#")), "")
            extracted_title = first_h1 or os.path.splitext(os.path.basename(safe_file))[0]
    else:
        extracted_text = str(payload.get("transcript") or payload.get("source_notes") or "").strip()
        if not extracted_title:
            first_line = next((ln.strip() for ln in extracted_text.splitlines() if ln.strip()), "")
            extracted_title = first_line[:90] or "Content-Kampagne aus Transkript"

    if not extracted_text:
        raise ValueError("Quell-Inhalt ist leer — keine Kampagne erstellt.")

    camp = create_campaign(
        {
            "title": extracted_title[:160],
            "topic": str(payload.get("topic") or extracted_title)[:220],
            "target_audience": payload.get("target_audience") or "Gruender, Geschaeftsfuehrer & Tech-Entscheider",
            "brand_voice": payload.get("brand_voice") or "Direkt, faktenbasiert, praxisnah, ohne KI-Floskeln",
            "pillar": payload.get("pillar") or "Content Repurposing",
            "source_url": source_url,
            "source_notes": extracted_text[:6000],
            "channels": payload.get("channels") or DEFAULT_CHANNELS,
        },
        db_path=db_path,
    )
    return {
        "campaign": camp,
        "source_type": source_type,
        "ingested_chars": len(extracted_text),
    }


async def generate_video_clip_matrix(
    *,
    campaign_id: str,
    source_asset_id: Optional[str] = None,
    script_text: Optional[str] = None,
    clip_count: int = 3,
    target_channels: Optional[List[str]] = None,
    dry_run: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Zerlegt ein Longform-Skript in eigenstaendige 9:16-Clip-Pakete (Shorts & TikTok)."""
    init_content_machine_db(db_path)
    camp = get_campaign(campaign_id, db_path=db_path)
    if not camp and not (script_text or "").strip():
        raise KeyError(f"Content-Kampagne '{campaign_id}' nicht gefunden.")
    if not camp:
        camp = {
            "id": campaign_id,
            "title": "Standalone Clip Matrix",
            "topic": (script_text or "").strip()[:80] or "Clip Matrix",
            "source_notes": (script_text or "").strip(),
        }

    base_text = (script_text or "").strip()
    if source_asset_id and not base_text:
        with _conn(db_path) as conn:
            arow = conn.execute("SELECT * FROM content_assets WHERE id = ?", (source_asset_id,)).fetchone()
        if not arow:
            raise KeyError(f"Quell-Asset '{source_asset_id}' nicht gefunden.")
        base_text = str(arow["body"] or arow["hook"] or camp.get("source_notes") or camp.get("topic") or "")
    if not base_text:
        base_text = str(camp.get("source_notes") or camp.get("topic") or camp["title"])

    count = max(1, min(6, int(clip_count)))
    allowed_video_channels = ("youtube_shorts", "tiktok", "instagram_reels", "linkedin")
    channels = [c for c in (target_channels or ["youtube_shorts", "tiktok"]) if c in allowed_video_channels]
    if not channels:
        channels = ["youtube_shorts", "tiktok"]

    clips_spec: List[Dict[str, Any]] = []
    if dry_run:
        segments = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", base_text) if len(s.strip()) > 15]
        if not segments:
            segments = [base_text]
        for idx in range(count):
            seg = segments[idx % len(segments)]
            ch = channels[idx % len(channels)]
            ch_label = (CHANNEL_SPECS.get(ch) or {}).get("label") or ch
            start_s = idx * 45
            mid_s = start_s + 2
            end_s = start_s + 38
            clips_spec.append({
                "channel": ch,
                "title": f"Clip #{idx + 1} ({ch_label}): {camp['title'][:70]}",
                "hook": f"Stopp — dieser 1 Fehler bei '{camp['topic'][:60]}' kostet 40% Performance ({idx + 1}/{count}).",
                "body": (
                    f"[{start_s // 60:02d}:{start_s % 60:02d}–{mid_s // 60:02d}:{mid_s % 60:02d}] VISUAL HOOK: Grossaufnahme + Einblendung\n"
                    f"[{mid_s // 60:02d}:{mid_s % 60:02d}–{end_s // 60:02d}:{end_s % 60:02d}] KERN-AUSSAGE: {seg[:260]}\n"
                    f"[LOOP-ENDE] Uebergang zur naechsten Frage."
                ),
                "visual_brief": "9:16 Split-Screen, fette Captions (2-3 Woerter/Beat), B-Roll-Wechsel alle 2,5s",
                "cta": "Speichern fuer dein Team & Teil 2 kommentieren.",
                "duration_sec": 38,
                "hashtags": [f"#{ch}", "#Shorts", "#ArchonOS"],
            })
    else:
        import core_dispatcher
        prompt = (
            f"Zerlege folgendes Longform-Skript/Thema in exakt {count} eigenstaendige 9:16 Kurzvideo-Clips "
            f"(fuer {', '.join(channels)}).\n"
            "Jeder Clip braucht: channel (youtube_shorts oder tiktok), title, hook (<=150 Zeichen), "
            "body (mit Timecodes, On-Screen-Captions, Schnitt-Beats & Loop-Ende), visual_brief, cta, duration_sec (25-55), hashtags.\n"
            f"Antworte AUSSCHLIESSLICH als JSON-Array.\n\nQUELLE:\n{base_text[:5000]}"
        )
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id="content_repurposing_specialist",
            agent_name="Content Repurposing Specialist",
            prompt=prompt,
            role="Shortform Video Repurposing",
            system_prompt="Du schneidest praezise, retention-optimierte Kurzvideos ohne Fuellwoerter.",
            model="deepseek/deepseek-chat",
        )
        raw = str(res.get("content") or "").strip()
        if "```" in raw:
            for blk in raw.split("```"):
                b = blk.strip()
                if b.startswith("json"):
                    b = b[4:].strip()
                if b.startswith("[") and b.endswith("]"):
                    raw = b
                    break
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                clips_spec = [x for x in arr if isinstance(x, dict)][:count]
        except (ValueError, TypeError):
            clips_spec = []

    created: List[Dict[str, Any]] = []
    for idx, spec in enumerate(clips_spec):
        ch = str(spec.get("channel") or channels[idx % len(channels)]).lower()
        if ch not in ("youtube_shorts", "tiktok"):
            ch = channels[idx % len(channels)]
        created.append(
            create_asset(
                {
                    "campaign_id": campaign_id,
                    "channel": ch,
                    "format_type": "video_clip_9_16",
                    "title": str(spec.get("title") or f"Clip #{idx + 1}: {camp['title']}")[:160],
                    "hook": str(spec.get("hook") or "")[:400],
                    "body": str(spec.get("body") or ""),
                    "visual_brief": str(spec.get("visual_brief") or "9:16 Untertitel + Schnitt alle 2,5s"),
                    "cta": str(spec.get("cta") or "Speichern & folgen."),
                    "duration_sec": int(spec.get("duration_sec") or 38),
                    "hashtags": spec.get("hashtags") if isinstance(spec.get("hashtags"), list) else [f"#{ch}"],
                    "status": "review",
                    "agent_id": "content_repurposing_specialist",
                },
                db_path=db_path,
            )
        )
    return {"campaign_id": campaign_id, "clips_created": created, "count": len(created)}


def dispatch_asset_to_webhook(
    asset_id: str,
    webhook_url: str,
    *,
    dry_run: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Sendet ein freigegebenes Asset SSRF-geschuetzt an einen Publishing-Webhook (z. B. n8n)."""
    from utils.egress_guard import check_target_url

    init_content_machine_db(db_path)
    with _conn(db_path) as conn:
        row = conn.execute("SELECT * FROM content_assets WHERE id = ?", (asset_id,)).fetchone()
    if not row:
        raise KeyError(f"Content-Asset '{asset_id}' nicht gefunden.")
    asset = _row_to_asset(row)
    if asset["status"] not in ("approved", "scheduled"):
        raise ValueError(f"Asset '{asset_id}' muss erst freigegeben ('approved'/'scheduled') sein (aktuell: {asset['status']}).")

    safe_url = check_target_url(webhook_url)
    payload = {
        "event": "content_asset_publish",
        "asset_id": asset["id"],
        "campaign_id": asset["campaign_id"],
        "channel": asset["channel"],
        "title": asset["title"],
        "hook": asset["hook"],
        "body": asset["body"],
        "visual_brief": asset["visual_brief"],
        "hashtags": asset["hashtags"],
        "cta": asset["cta"],
    }
    if dry_run:
        return {"status": "dry_run", "target_url": safe_url, "payload": payload}

    # Outbox + Idempotenz: ein zweiter Sweep/Retry darf denselben Asset nicht
    # erneut publizieren. safe_http_request blockt zusätzlich Redirect-SSRF
    # (urlopen folgte früher 3xx und löste DNS erneut auf).
    from backend.event_mesh import event_mesh

    idem = f"content-publish:{asset_id}"
    payload["idempotency_key"] = idem
    delivery = event_mesh.emit_outbound_event(
        safe_url, "content_asset_publish", payload, timeout=8.0
    )
    if delivery.get("status") == "duplicate":
        return {
            "status": "already_dispatched",
            "idempotency_key": idem,
            "outbox_status": delivery.get("outbox_status"),
        }
    if delivery.get("status") != "delivered":
        raise RuntimeError(f"Publish-Webhook fehlgeschlagen: {delivery.get('response')}")
    updated = mark_asset_published(asset_id, db_path=db_path)
    return {
        "status": "published",
        "http_status": delivery.get("http_status"),
        "asset": updated,
        "idempotency_key": idem,
    }


def publish_scheduled_due_assets(
    *,
    webhook_url: Optional[str] = None,
    dry_run: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Findet alle faelligen 'scheduled'-Assets (scheduled_at <= now) und publiziert sie."""
    init_content_machine_db(db_path)
    now_iso = _utc_now_iso()
    with _conn(db_path) as conn:
        rows = conn.execute(
            # P1: 'approved' mit gesetztem scheduled_at wurde vom Sweep nie
            # gefunden — Finalisierung und HITL-Gate setzten teils 'approved'.
            "SELECT * FROM content_assets WHERE status IN ('scheduled', 'approved') "
            "AND scheduled_at != '' AND scheduled_at <= ? ORDER BY scheduled_at ASC",
            (now_iso,),
        ).fetchall()
    due_assets = [_row_to_asset(r) for r in rows]
    if dry_run:
        return {"status": "dry_run", "due_count": len(due_assets), "due_asset_ids": [a["id"] for a in due_assets]}

    published: List[str] = []
    errors: List[Dict[str, str]] = []
    for a in due_assets:
        try:
            if webhook_url:
                dispatch_asset_to_webhook(a["id"], webhook_url, dry_run=False, db_path=db_path)
            else:
                mark_asset_published(a["id"], db_path=db_path)
            published.append(a["id"])
        except Exception as exc:
            errors.append({"asset_id": a["id"], "error": str(exc)})
    return {"status": "ok", "due_count": len(due_assets), "published": published, "errors": errors}


def sweep_content_performance_feedback(
    *,
    hours_min: int = 48,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """48h/7d-Performance-Rueckfluss: speist erfolgreiche Hooks gewichtet ins FTS5-Memory & Voice-Vorschlaege."""
    init_content_machine_db(db_path)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours_min)))).isoformat()
    recorded = 0
    suggestions: List[str] = []

    with _conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT m.id AS metric_id, m.asset_id, m.channel, m.views, m.likes, m.comments, m.shares, m.saves,
                   m.ctr_pct, m.recorded_at, a.title, a.hook, a.agent_id
            FROM content_metrics m
            JOIN content_assets a ON a.id = m.asset_id
            WHERE m.recorded_at <= ?
            ORDER BY m.views DESC, m.likes DESC
            LIMIT 25
            """,
            (cutoff,),
        ).fetchall()

    for r in rows:
        views = int(r["views"] or 0)
        likes = int(r["likes"] or 0)
        comments = int(r["comments"] or 0)
        shares = int(r["shares"] or 0)
        saves = int(r["saves"] or 0)
        eng_rate = round(((likes + comments * 2 + shares * 3 + saves * 2) / views) * 100.0, 2) if views > 0 else 0.0
        if eng_rate < 5.0 and views < 1000:
            continue
        summary = (
            f"[48h+ Winner | {r['channel']}] '{r['title']}' — {views} Views, {eng_rate}% Engagement, "
            f"CTR {float(r['ctr_pct'] or 0):.1f}%. Hook: {str(r['hook'] or '')[:160]}"
        )
        try:
            from local_memory_bridge import memory_bridge
            memory_bridge.record_learning(
                agent_id=str(r["agent_id"] or "content_repurposing_specialist"),
                category=f"content_{r['channel']}",
                summary=summary,
                memory_tier="procedural",
            )
            recorded += 1
            suggestions.append(f"- ({r['channel']}, {eng_rate}% Eng.) {str(r['hook'] or '')[:140]}")
        except Exception as exc:
            logger.debug(f"[ContentMachine] 48h-Feedback-Sync uebersprungen: {exc}")

    if suggestions:
        try:
            voice_sugg_path = os.path.join(WORKSPACE_DIR, "config", "voice_winner_hooks.md")
            os.makedirs(os.path.dirname(voice_sugg_path), exist_ok=True)
            with open(voice_sugg_path, "w", encoding="utf-8") as vf:
                vf.write("# Automatische Brand-Voice Hook-Vorschlaege (48h+ Performance-Rueckfluss)\n\n")
                vf.write("\n".join(suggestions[:15]) + "\n")
        except Exception as exc:
            logger.debug(f"[ContentMachine] voice_winner_hooks.md Schreibfehler: {exc}")

    return {"status": "ok", "recorded_learnings": recorded, "suggestions_count": len(suggestions)}


def finalize_assets_for_workflow_run(
    workflow_run_id: str,
    *,
    approved: bool,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """HITL-Abschluss fuer Repurposing-Campaigns.

    Die Kanal-Assets werden vor dem Gate mit status='review' angelegt. Die
    Freigabe resume nur den DAG — die Asset-Persistenz lief aber bereits
    zurueck. Ohne diesen Schritt bleiben die Assets dauerhaft auf 'review'
    und publish_scheduled_due_assets() findet sie nie (Sackgasse).
    """
    now = _utc_now_iso()
    target = "scheduled" if approved else "rejected"
    with _conn(db_path) as conn:
        row = conn.execute(
            "SELECT campaign_id FROM content_repurpose_runs "
            "WHERE workflow_run_id = ? ORDER BY created_at DESC LIMIT 1",
            (workflow_run_id,),
        ).fetchone()
        if not row:
            return {"status": "no_run", "updated": 0, "workflow_run_id": workflow_run_id}
        campaign_id = str(row["campaign_id"] or "")
        cur = conn.execute(
            "UPDATE content_assets SET status = ?, updated_at = ? "
            "WHERE campaign_id = ? AND status IN ('review', 'draft')",
            (target, now, campaign_id),
        )
        updated = int(cur.rowcount or 0)
        conn.commit()
    return {
        "status": "ok",
        "updated": updated,
        "campaign_id": campaign_id,
        "target_status": target,
    }
