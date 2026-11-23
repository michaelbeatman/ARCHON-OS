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
# Batch C: geteilte, konservative Rechte-Helfer (keine erfundenen Lizenzen).
from backend.research_sources import (
    apply_rights_defaults,
    classify_rights,
    rights_from_html,
    DEFAULT_LICENSE,
    DEFAULT_RIGHTS,
)

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
# CM: kanonisches Kampagnen-Statusmodell. 'idea' ist die Vorstufe aus dem
# competitor_idea_bridge / CRM-Intake und muss von der Content-Machine
# genauso verstanden werden wie 'draft', 'in_review', 'completed' und 'failed'.
CAMPAIGN_STATUS_IDEA = "idea"
VALID_CAMPAIGN_STATUSES = (
    CAMPAIGN_STATUS_IDEA, "draft", "in_review", "completed", "failed",
)


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
                -- CM 2.0: Fact-Check/Plagiat-Gate + Kanalvalidierung
                sources_json TEXT DEFAULT '[]',
                fact_check_report_json TEXT DEFAULT '{}',
                channel_validation_json TEXT DEFAULT '{}',
                geo_jsonld_json TEXT DEFAULT '{}',
                -- Batch C: Plagiats-/Rechte-Gate (Offline-Similarity + Rights)
                plagiarism_report_json TEXT DEFAULT '{}',
                -- Batch D: Dossier-Pfad aus dem Research-Knoten + Redaktionsrollen
                dossier_path TEXT DEFAULT '',
                author TEXT DEFAULT '',
                reviewer TEXT DEFAULT '',
                publisher TEXT DEFAULT '',
                -- Batch D: offline GEO-Zitatpruefung (48h)
                citation_check_json TEXT DEFAULT '{}',
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
                -- CM 2.0: Variant-Zuordnung fuer A/B-Auswertung
                variant_id TEXT DEFAULT '',
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

            CREATE TABLE IF NOT EXISTS content_asset_approvals (
                id TEXT PRIMARY KEY,
                asset_id TEXT NOT NULL,
                decision_id TEXT DEFAULT '',
                action TEXT NOT NULL,
                actor TEXT DEFAULT '',
                role TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (asset_id) REFERENCES content_assets (id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_cm_assets_campaign ON content_assets(campaign_id);
            CREATE INDEX IF NOT EXISTS idx_cm_assets_status ON content_assets(status, channel);
            CREATE INDEX IF NOT EXISTS idx_cm_metrics_asset ON content_metrics(asset_id);
            CREATE INDEX IF NOT EXISTS idx_cm_approvals_asset ON content_asset_approvals(asset_id, created_at);

            -- Content-Machine 2.0: A/B-Varianten, Fact-Check/Plagiat, GEO
            CREATE TABLE IF NOT EXISTS content_variants (
                id TEXT PRIMARY KEY,
                asset_id TEXT NOT NULL,
                variant_label TEXT NOT NULL,
                title TEXT DEFAULT '',
                hook TEXT DEFAULT '',
                body TEXT DEFAULT '',
                is_winner INTEGER DEFAULT 0,
                selected_by TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (asset_id) REFERENCES content_assets (id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS content_experiments (
                id TEXT PRIMARY KEY,
                asset_id TEXT NOT NULL,
                metric TEXT NOT NULL DEFAULT 'ctr_pct',
                status TEXT NOT NULL DEFAULT 'running',
                winner_variant_id TEXT DEFAULT '',
                decided_at TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (asset_id) REFERENCES content_assets (id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_cm_variants_asset ON content_variants(asset_id);
            CREATE INDEX IF NOT EXISTS idx_cm_experiments_asset ON content_experiments(asset_id);
            """
        )
        # Migration fuer bestehende content_assets ohne quality_score / quality_report_json
        cols = {r[1] for r in conn.execute("PRAGMA table_info(content_assets)").fetchall()}
        if "quality_score" not in cols:
            conn.execute("ALTER TABLE content_assets ADD COLUMN quality_score INTEGER DEFAULT 0")
        if "quality_report_json" not in cols:
            conn.execute("ALTER TABLE content_assets ADD COLUMN quality_report_json TEXT DEFAULT '{}'")
        # CM 2.0 Migration fuer bestehende Installationen (z. B. konsolidierte business.db)
        for col, decl in (
            ("sources_json", "TEXT DEFAULT '[]'"),
            ("fact_check_report_json", "TEXT DEFAULT '{}'"),
            ("channel_validation_json", "TEXT DEFAULT '{}'"),
            ("geo_jsonld_json", "TEXT DEFAULT '{}'"),
            ("plagiarism_report_json", "TEXT DEFAULT '{}'"),
            # Batch D: neue Asset-Spalten (Dossier, Rollen, Zitatpruefung).
            ("dossier_path", "TEXT DEFAULT ''"),
            ("author", "TEXT DEFAULT ''"),
            ("reviewer", "TEXT DEFAULT ''"),
            ("publisher", "TEXT DEFAULT ''"),
            ("citation_check_json", "TEXT DEFAULT '{}'"),
        ):
            if col not in cols:
                conn.execute(f"ALTER TABLE content_assets ADD COLUMN {col} {decl}")
        # Batch D: Tabelle fuer die Freigabe-Historie nachtraeglich anlegen, falls
        # eine bestehende DB nur bis CM 2.0 initialisiert wurde.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS content_asset_approvals (
                id TEXT PRIMARY KEY,
                asset_id TEXT NOT NULL,
                decision_id TEXT DEFAULT '',
                action TEXT NOT NULL,
                actor TEXT DEFAULT '',
                role TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (asset_id) REFERENCES content_assets (id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cm_approvals_asset "
            "ON content_asset_approvals(asset_id, created_at)"
        )
        metric_cols = {r[1] for r in conn.execute("PRAGMA table_info(content_metrics)").fetchall()}
        if metric_cols and "variant_id" not in metric_cols:
            conn.execute("ALTER TABLE content_metrics ADD COLUMN variant_id TEXT DEFAULT ''")
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
    # CM 2.0: strukturierte Zusatzfelder
    for json_field, out_field, default in (
        ("sources_json", "sources", "[]"),
        ("fact_check_report_json", "fact_check", "{}"),
        ("channel_validation_json", "channel_validation", "{}"),
        ("geo_jsonld_json", "geo_jsonld", "{}"),
        ("plagiarism_report_json", "plagiarism_report", "{}"),
    ):
        try:
            d[out_field] = json.loads(d.pop(json_field, default) or default)
        except (ValueError, TypeError):
            d[out_field] = default
    # Batch D: neue TEXT-Spalten auch bei alten Zeilen/Rows explizit im Schema.
    for text_field in ("dossier_path", "author", "reviewer", "publisher"):
        d.setdefault(text_field, "")
        d[text_field] = str(d.get(text_field) or "")
    if "citation_check_json" in d:
        try:
            d["citation_check"] = json.loads(d.pop("citation_check_json") or "{}")
        except (ValueError, TypeError):
            d["citation_check"] = {}
    d.setdefault("citation_check", {})
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
    # Ein String ("linkedin") wurde frueher zeichenweise iteriert -> leere
    # Liste -> still ALLE Default-Kanaele. Explizit normalisieren.
    if isinstance(raw_channels, str):
        raw_channels = [raw_channels]
    channels = [c for c in raw_channels if isinstance(c, str) and c in CHANNEL_SPECS] if isinstance(raw_channels, list) else list(DEFAULT_CHANNELS)
    if not channels:
        channels = list(DEFAULT_CHANNELS)

    status = str(payload.get("status") or "draft").strip().lower()
    if status not in VALID_CAMPAIGN_STATUSES:
        raise ValueError(f"Ungueltiger Kampagnen-Status: {status!r}")

    cid = f"camp-{secrets.token_hex(4)}"
    now = _utc_now_iso()
    with _conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO content_campaigns (
                id, title, topic, target_audience, brand_voice, pillar,
                source_url, source_notes, channels_json, status, workflow_run_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?)
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
                status,
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
        # Kindtabellen zuerst entfernen: FK-Cascade greift nicht von
        # content_campaigns aus, sonst blieben Metriken/Approvals als Waisen
        # und die Analytics-Zaehler blieben dauerhaft falsch.
        asset_ids = [
            str(r[0]) for r in conn.execute(
                "SELECT id FROM content_assets WHERE campaign_id = ?", (campaign_id,)
            ).fetchall()
        ]
        for table in ("content_asset_approvals", "content_variants", "content_experiments", "content_metrics"):
            for aid in asset_ids:
                try:
                    conn.execute(f"DELETE FROM {table} WHERE asset_id = ?", (aid,))
                except Exception:
                    pass
        try:
            conn.execute("DELETE FROM content_repurpose_runs WHERE campaign_id = ?", (campaign_id,))
        except Exception:
            pass
        conn.execute("DELETE FROM content_assets WHERE campaign_id = ?", (campaign_id,))
        cur = conn.execute("DELETE FROM content_campaigns WHERE id = ?", (campaign_id,))
        conn.commit()
        return cur.rowcount > 0


def create_asset(payload: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    init_content_machine_db(db_path)
    campaign_id = str(payload.get("campaign_id") or "").strip() or f"campaign-{secrets.token_hex(4)}"
    aid = f"asset-{secrets.token_hex(4)}"
    # W2/W4: content_assets.campaign_id hat einen FK auf content_campaigns.
    # Früher wurde ohne Eltern-Zeile eingefügt — das funktionierte nur,
    # solange PRAGMA foreign_keys AUS war. Jetzt wird für JEDEN nicht
    # existierenden Wert (leer ODER z. B. 'wf_standalone_test') implizit
    # eine Kampagne angelegt: echte referenzielle Integrität statt
    # stiller Verwaiste-Rows.
    now_auto = _utc_now_iso()
    with _conn(db_path) as conn:
        parent = conn.execute(
            "SELECT 1 FROM content_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if parent is None:
            conn.execute(
                """
                INSERT OR IGNORE INTO content_campaigns
                    (id, title, topic, target_audience, brand_voice, pillar,
                     source_url, source_notes, channels_json, status,
                     workflow_run_id, created_at, updated_at)
                VALUES (?, ?, ?, '', '', '', '', '', '[]', 'draft', '', ?, ?)
                """,
                (campaign_id, f"Auto-Kampagne {aid}", f"Auto-Kampagne {aid}", now_auto, now_auto),
            )
            conn.commit()
    channel = str(payload.get("channel") or "linkedin").strip().lower()
    if channel not in CHANNEL_SPECS:
        raise ValueError(f"Unbekannter Kanal: {channel!r}")
    title = str(payload.get("title") or f"{CHANNEL_SPECS[channel]['label']} Asset").strip()
    status = str(payload.get("status") or "draft").strip().lower()
    if status not in VALID_ASSET_STATUSES:
        status = "draft"

    now = _utc_now_iso()
    hashtags = payload.get("hashtags") if isinstance(payload.get("hashtags"), list) else []
    asset_view = {
        "channel": channel,
        "hook": payload.get("hook") or "",
        "body": payload.get("body") or "",
        "cta": payload.get("cta") or "",
        "sources": payload.get("sources") or [],
        "parse_failed": bool(payload.get("parse_failed")),
        "duration_sec": int(payload.get("duration_sec") or CHANNEL_SPECS[channel].get("target_duration_sec") or 0),
    }
    q_report = evaluate_asset_quality(asset_view)
    # CM 2.0: harte Kanalvalidierung + Fact-Check gegen Belegquellen.
    channel_validation = validate_channel_constraints(asset_view)
    fact_check = evaluate_fact_check(asset_view)
    # Batch C: Rechte- + Plagiatsreport (offline, deterministisch). Der Korpus
    # kann ueber den Payload injiziert werden; ohne Korpus bleibt checked=False.
    rights_report = evaluate_source_rights(asset_view["sources"])
    corpus = payload.get("plagiarism_corpus")
    if corpus is None:
        corpus = payload.get("corpus")
    sim_report = evaluate_plagiarism_risk(asset_view, corpus=corpus)
    plagiarism_report = {
        "rights": rights_report,
        "plagiarism": sim_report,
        "checked": bool(sim_report.get("checked")),
        "passed": bool(rights_report.get("passed", True) and sim_report.get("passed", True)),
        "created_at": now,
    }
    with _conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO content_assets (
                id, campaign_id, channel, format_type, title, hook, body, visual_brief,
                hashtags_json, cta, duration_sec, status, scheduled_at, published_at,
                external_url, decision_id, agent_id, quality_score, quality_report_json,
                sources_json, fact_check_report_json, channel_validation_json,
                plagiarism_report_json, dossier_path, author, reviewer, publisher,
                citation_check_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                json.dumps(asset_view["sources"], ensure_ascii=False),
                json.dumps(fact_check, ensure_ascii=False),
                json.dumps(channel_validation, ensure_ascii=False),
                json.dumps(plagiarism_report, ensure_ascii=False),
                str(payload.get("dossier_path") or "").strip(),
                str(payload.get("author") or "").strip(),
                str(payload.get("reviewer") or "").strip(),
                str(payload.get("publisher") or "").strip(),
                json.dumps(payload.get("citation_check") or {}, ensure_ascii=False, default=str),
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
        # KRITISCH: textabhaengige Gate-Reports bei jedem Patch neu berechnen.
        # Vorher blieben fact_check/plagiat/channel beim alten "passed=True",
        # obwohl der Reviewer per PATCH neue Zahlen/kopierten Text einfuegen konnte.
        if any(k in (patch or {}) for k in ("hook", "body", "cta", "sources", "hashtags")):
            fc = evaluate_fact_check(merged_for_q)
            sets.append("fact_check_report_json = ?")
            params.append(json.dumps(fc, ensure_ascii=False))
            cv = validate_channel_constraints(merged_for_q)
            sets.append("channel_validation_json = ?")
            params.append(json.dumps(cv, ensure_ascii=False))
            corpus = existing_row["plagiarism_corpus_json"] if "plagiarism_corpus_json" in existing_row.keys() else None
            pl = evaluate_plagiarism_risk(merged_for_q, corpus=json.loads(corpus) if corpus else None)
            sets.append("plagiarism_report_json = ?")
            params.append(json.dumps(pl, ensure_ascii=False))
        params.append(asset_id)
        conn.execute(f"UPDATE content_assets SET {', '.join(sets)} WHERE id = ?", params)
        conn.commit()
        row = conn.execute("SELECT * FROM content_assets WHERE id = ?", (asset_id,)).fetchone()
    return _row_to_asset(row)


def validate_channel_constraints(asset: Dict[str, Any]) -> Dict[str, Any]:
    """CM 2.0: Harte Kanalvalidierung gegen CHANNEL_SPECS.

    Frueher wurde hook_max_chars (180) ignoriert und auf 400 gekuerzt; bei
    JSON-Parse-Fehlern bekamen alle Kanaele denselben Body. Hier werden die
    Grenzen verbindlich geprueft und Verletzungen als Blockiergrund geliefert.
    """
    channel = str(asset.get("channel") or "linkedin").lower()
    spec = CHANNEL_SPECS.get(channel, CHANNEL_SPECS["linkedin"])
    issues: List[str] = []
    hook = str(asset.get("hook") or "")
    body = str(asset.get("body") or "")
    hook_limit = int(spec.get("hook_max_chars") or 0)
    max_chars = int(spec.get("max_chars") or 0)
    if hook_limit and len(hook) > hook_limit:
        issues.append(f"Hook {len(hook)} > {hook_limit} Zeichen ({spec['label']}).")
    if max_chars and len(body) > max_chars:
        issues.append(f"Body {len(body)} > {max_chars} Zeichen ({spec['label']}).")
    if asset.get("parse_failed"):
        issues.append("Agent-Output war kein strukturiertes JSON — Kanal-Asset nicht verwertbar.")
    if spec.get("target_duration_sec") and not int(asset.get("duration_sec") or 0):
        issues.append(f"Dauer fehlt fuer {spec['label']} (Ziel {spec['target_duration_sec']}s).")
    return {"passed": not issues, "issues": issues, "channel": channel,
            "hook_limit": hook_limit, "max_chars": max_chars}


def evaluate_fact_check(asset: Dict[str, Any]) -> Dict[str, Any]:
    """CM 2.0: Fakten-Anker muessen in Belegquellen vorkommen.

    Der alte Score akzeptierte jedes '\\d+' als Fakten-Anker. Hier wird
    geprueft, ob Zahlen im Body auch in den Research-Quellen auftauchen.
    """
    body = str(asset.get("body") or "")
    sources = asset.get("sources") or []
    if isinstance(sources, str):
        try:
            sources = json.loads(sources)
        except Exception:
            sources = []
    # Timestamps (00:02:38, 1:45) und Folgen-/Kapitelnummern sind
    # Strukturangaben, keine Faktenbehauptungen.
    body_for_facts = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", " ", body)
    body_for_facts = re.sub(
        r"\b(?:Folge|Episode|Teil|Kapitel|Chapter|Part)\s+\d+\b", " ",
        body_for_facts, flags=re.IGNORECASE,
    )
    # Einstellige Zahlen ohne Einheit sind meist Artikel-/Folgennummern.
    numbers = {
        n for n in re.findall(r"\b\d+(?:[.,]\d+)?\s?%?", body_for_facts)
        if len(n.strip("% ")) >= 2 or "%" in n
    }
    source_text = " ".join(
        str(s.get("text") or s.get("snippet") or s.get("summary") or s.get("content") or s.get("title") or "")
        for s in sources if isinstance(s, dict)
    )
    unbacked = sorted(n for n in numbers if n.strip("% ") not in source_text.replace(",", "."))
    passed = bool(numbers) and not unbacked
    issues = []
    if not numbers:
        issues.append("Keine konkreten Zahlen im Asset — kein Fakten-Anker.")
    if unbacked:
        issues.append(f"Zahlen ohne Beleg in Research-Quellen: {', '.join(unbacked[:6])}")
    return {"passed": passed, "numbers_found": len(numbers),
            "unbacked": unbacked[:10], "issues": issues,
            "sources_checked": len(sources)}


# =========================================================================
# BATCH C: PLAGIATS-/COPYRIGHT-GATE (OFFLINE, DETERMINISTISCH)
# =========================================================================

_PLAGIARISM_SHINGLE_SIZE = 5
_PLAGIARISM_WORD_RE = re.compile(r"[A-Za-zÄÖÜäöüß0-9]+")


def _text_shingles(text: str, k: int = _PLAGIARISM_SHINGLE_SIZE) -> set:
    """O(n)-Token-Shingles (keine Heavy-Deps, kein difflib-Quadratverhalten)."""
    words = [w.lower() for w in _PLAGIARISM_WORD_RE.findall(str(text or ""))]
    if not words:
        return set()
    if len(words) < k:
        return {tuple(words)}
    return {tuple(words[i:i + k]) for i in range(len(words) - k + 1)}


def evaluate_source_rights(sources: Any) -> Dict[str, Any]:
    """Batch C: konservative Rechte-Pruefung der Belegquellen.

    Meldet Issues fuer fehlende oder einschraenkende Lizenz-/Rechte-Angaben.
    'passed' ist NUR False bei explizit verweigerten Rechten — fehlende
    Metadaten oder leere Quellen duerfen keine Freigabe blockieren. Es wird
    niemals ein 'cleared'-Status behauptet.
    """
    if isinstance(sources, str):
        try:
            sources = json.loads(sources)
        except (ValueError, TypeError):
            sources = []
    if not isinstance(sources, (list, tuple)):
        sources = []

    issues: List[str] = []
    denied: List[str] = []
    restricted: List[str] = []
    unknown: List[str] = []
    permissive_declared = 0

    for idx, s in enumerate(sources):
        if not isinstance(s, dict):
            label = f"[{idx}]"
            unknown.append(label)
            issues.append(f"Quelle {label} hat kein Rechte-Metadaten-Format.")
            continue
        label = str(s.get("title") or s.get("url") or s.get("domain") or f"[{idx}]")[:120]
        lic = str(s.get("license") or "").strip()
        rgt = str(s.get("rights") or "").strip()
        info = classify_rights(lic, rgt)
        status = info["status"]
        if status == "denied":
            denied.append(label)
            issues.append(f"Quelle '{label}': Rechte explizit verweigert ({lic or rgt}).")
        elif status == "unknown":
            unknown.append(label)
            issues.append(f"Quelle '{label}': Lizenz/Rechte unbekannt — keine Freigabe behauptet.")
        elif status == "restricted":
            restricted.append(label)
            issues.append(f"Quelle '{label}': Nutzung eingeschraenkt ({lic or rgt}).")
        elif status == "permissive_declared":
            permissive_declared += 1
        else:
            issues.append(f"Quelle '{label}': Lizenz deklariert, aber nicht geprueft ({lic}).")

    if not sources:
        issues.append("Keine Belegquellen vorhanden — keine Rechtepruefung moeglich.")

    overall = "denied" if denied else (
        "restricted" if restricted else (
            "unknown" if unknown else (
                "declared" if permissive_declared == len(sources) and sources else "unknown"
            )
        )
    )
    return {
        "passed": not denied,
        "status": overall,
        "sources_checked": len(sources),
        "issues": issues,
        "denied": denied,
        "restricted": restricted,
        "unknown": unknown,
        "permissive_declared": permissive_declared,
        "note": "Konservative offline Rechtepruefung; 'declared' ist keine Freigabe.",
    }


def evaluate_plagiarism_risk(asset: Any, corpus: Any = None) -> Dict[str, Any]:
    """Batch C: deterministischer Offline-Aehnlichkeitscheck (Token-Shingles).

    `corpus` ist eine Liste von Strings oder Dicts (body/text/content/snippet).
    Fehlt der Korpus, wird ausdruecklich KEIN Check behauptet (checked=False),
    aber passes=True zurueckgegeben (Fail-Safe, keine blockierten Assets).
    """
    if isinstance(asset, dict):
        body = str(asset.get("body") or "")
        text = body or str(asset.get("title") or "")
    else:
        text = str(asset or "")

    if corpus is None:
        return {
            "passed": True,
            "checked": False,
            "max_similarity": 0.0,
            "issues": [],
            "sources_checked": 0,
            "note": "Kein Korpus bereitgestellt — kein Plagiatsvergleich durchgefuehrt (Fail-Safe).",
        }

    if isinstance(corpus, dict):
        corpus = [corpus]
    if not isinstance(corpus, (list, tuple)):
        corpus = []

    docs: List[tuple] = []
    for item in corpus:
        if isinstance(item, dict):
            txt = (item.get("body") or item.get("text") or item.get("content")
                   or item.get("snippet") or item.get("raw_text") or "")
            label = str(item.get("title") or item.get("url") or item.get("id") or "")[:120]
        else:
            txt, label = item, ""
        docs.append((label, str(txt or "")))

    asset_shingles = _text_shingles(text)
    # Ein LEERER Korpus ist kein durchgefuehrter Vergleich. Vorher ergab
    # corpus=[] checked=True/passed=True — ein Client konnte das Gate mit
    # plagiarism_corpus:[] beliebig umgehen.
    if not docs:
        return {
            "passed": False,
            "checked": False,
            "max_similarity": 0.0,
            "issues": ["Leerer Plagiats-Korpus — kein Vergleich durchgefuehrt."],
            "sources_checked": 0,
            "matched_source": "",
            "note": "Keine Belegquellen im Korpus — Freigabe blockiert.",
        }
    base = {
        "passed": True,
        "checked": True,
        "max_similarity": 0.0,
        "issues": [],
        "sources_checked": len(docs),
        "matched_source": "",
        "note": f"Offline-Token-Shingle-Vergleich (k={_PLAGIARISM_SHINGLE_SIZE}, Containment).",
    }
    if not asset_shingles:
        base["issues"].append("Kein Text im Asset — kein Vergleich moeglich.")
        base["passed"] = False
        return base

    best = 0.0
    best_label = ""
    for label, doc in docs:
        doc_shingles = _text_shingles(doc)
        if not doc_shingles:
            continue
        # Containment: Anteil der Asset-Shingles, die im Dokument vorkommen.
        sim = len(asset_shingles & doc_shingles) / len(asset_shingles)
        if sim > best:
            best, best_label = sim, label

    best = round(min(1.0, max(0.0, best)), 4)
    base["max_similarity"] = best
    base["matched_source"] = best_label
    if best > 0.8:
        base["passed"] = False
        base["issues"].append(
            f"Hohe Textaehnlichkeit {best:.2f} (> 0.8) mit "
            f"'{best_label or 'Korpusdokument'}' — Freigabe blockiert."
        )
    elif best > 0.5:
        base["issues"].append(
            f"Erhohte Textaehnlichkeit {best:.2f} mit '{best_label or 'Korpusdokument'}' — manuell pruefen."
        )
    return base


def create_variant(asset_id: str, variant_label: str, hook: str,
                   title: str = "", body: str = "", db_path=None) -> Dict[str, Any]:
    """CM 2.0: A/B-Variante zu einem Asset anlegen."""
    vid = f"var-{secrets.token_hex(6)}"
    with _conn(db_path) as conn:
        conn.execute(
            "INSERT INTO content_variants (id, asset_id, variant_label, title, hook, body, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (vid, asset_id, str(variant_label)[:40], str(title)[:160], str(hook), str(body), _utc_now_iso()),
        )
        conn.commit()
    return {"id": vid, "asset_id": asset_id, "variant_label": variant_label, "hook": hook}


def list_variants(asset_id: str, db_path=None) -> List[Dict[str, Any]]:
    with _conn(db_path) as conn:
        rows = conn.execute("SELECT * FROM content_variants WHERE asset_id = ? ORDER BY created_at", (asset_id,)).fetchall()
    return [dict(r) for r in rows]


def record_variant_metrics(asset_id: str, variant_id: str, metrics: Dict[str, Any], db_path=None) -> Dict[str, Any]:
    """CM 2.0: Metriken einer Variante verknuepfen (variant_id in payload_json)."""
    with _conn(db_path) as conn:
        # FRUEHER: erfundene asset_id/variant_id wurden akzeptiert und
        # verfaelschten Experimente. Beide muessen real existieren.
        if not conn.execute("SELECT 1 FROM content_assets WHERE id = ?", (asset_id,)).fetchone():
            raise KeyError(f"Content-Asset '{asset_id}' existiert nicht.")
        if not conn.execute(
            "SELECT 1 FROM content_variants WHERE id = ? AND asset_id = ?", (variant_id, asset_id)
        ).fetchone():
            raise KeyError(f"Variante '{variant_id}' gehoert nicht zu Asset '{asset_id}'.")
        meta = dict(metrics or {})
        mid = f"cm-{secrets.token_hex(6)}"
        conn.execute(
            "INSERT INTO content_metrics (id, asset_id, channel, views, likes, comments, shares, saves, ctr_pct, variant_id, recorded_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (mid, asset_id, str(meta.get("channel", "")), int(meta.get("views") or 0),
             int(meta.get("likes") or 0), int(meta.get("comments") or 0),
             int(meta.get("shares") or 0), int(meta.get("saves") or 0),
             float(meta.get("ctr_pct") or 0.0), str(variant_id), _utc_now_iso()),
        )
        conn.commit()
    return {"status": "ok", "metric_id": mid, "variant_id": variant_id}


def decide_experiment(asset_id: str, metric: str = "ctr_pct", db_path=None) -> Dict[str, Any]:
    """A/B-Entscheidung mit Mindest-Stichprobe und Wilson-Konfidenzintervall.

    Vorher wurde der `metric`-Parameter ignoriert (immer ctr_pct) und der
    Gewinner per max() gekuert — eine Variante mit 1 View konnte gewinnen.
    """
    allowed_metrics = {"ctr_pct", "views", "likes", "comments", "shares", "saves", "conversions"}
    metric = metric if metric in allowed_metrics else "ctr_pct"
    min_views = 30  # Mindest-Stichprobe pro Variante
    variants = list_variants(asset_id, db_path=db_path)
    if len(variants) < 2:
        return {"status": "insufficient_variants", "winner_variant_id": ""}
    with _conn(db_path) as conn:
        rows = conn.execute(
            f"SELECT variant_id, {metric} AS metric_value, views FROM content_metrics WHERE asset_id = ?",
            (asset_id,),
        ).fetchall()
    scores: Dict[str, float] = {v["id"]: 0.0 for v in variants}
    views_by_variant: Dict[str, int] = {v["id"]: 0 for v in variants}
    for r in rows:
        vid = str(r["variant_id"] or "")
        if vid not in scores:
            continue
        try:
            scores[vid] = max(scores[vid], float(r["metric_value"] or 0.0))
        except (TypeError, ValueError):
            pass
        views_by_variant[vid] = max(views_by_variant[vid], int(r["views"] or 0))

    eligible = {vid: s for vid, s in scores.items() if views_by_variant[vid] >= min_views}
    if not eligible:
        return {
            "status": "insufficient_sample",
            "winner_variant_id": "",
            "scores": scores,
            "min_views_required": min_views,
            "metric": metric,
        }
    # Wilson lower bound als konservativer Score (verhindert Gewinner mit
    # 1 View und 100 % CTR). Für Zaehlmetriken (views) bleibt der Rohwert.
    import math
    def _wilson(pct: float, views: int) -> float:
        if metric != "ctr_pct" or views <= 0:
            return pct
        p = min(1.0, max(0.0, pct / 100.0))
        z = 1.96
        denom = 1 + z * z / views
        center = p + z * z / (2 * views)
        margin = z * math.sqrt((p * (1 - p) + z * z / (4 * views)) / views)
        return round(100.0 * (center - margin) / denom, 4)

    adjusted = {vid: _wilson(score, views_by_variant[vid]) for vid, score in eligible.items()}
    winner = max(adjusted, key=lambda k: adjusted[k]) if adjusted else ""
    with _conn(db_path) as conn:
        conn.execute(
            "UPDATE content_variants SET is_winner = 0 WHERE asset_id = ?", (asset_id,)
        )
        if winner:
            conn.execute("UPDATE content_variants SET is_winner = 1 WHERE id = ?", (winner,))
        conn.execute(
            "INSERT INTO content_experiments (id, asset_id, metric, status, winner_variant_id, decided_at, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (f"exp-{secrets.token_hex(6)}", asset_id, metric, "decided", winner, _utc_now_iso(), _utc_now_iso()),
        )
        conn.commit()
    return {"status": "decided", "winner_variant_id": winner,
            "scores": scores, "metric": metric}


def _enforce_asset_quality(conn, row) -> Dict[str, Any]:
    """P1: Quality-Gate als echte Freigabebedingung (nicht nur Anzeige).

    Nutzt den gespeicherten Report, falls vorhanden; andernfalls wird er aus
    dem Asset neu berechnet. Ohne bestandenen Gate darf kein Asset in
    'approved'/'scheduled'/'published' uebergehen.
    """
    raw = None
    try:
        if "quality_report_json" in row.keys():
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

    # CM 2.0: zusaetzliche harte Gates — Kanalgrenzen und Faktenbelege.
    asset = _row_to_asset(row)
    channel_check = validate_channel_constraints(asset)
    if not channel_check.get("passed"):
        raise ValueError(
            "Kanalvalidierung blockiert Freigabe: " + "; ".join(channel_check["issues"][:3])
        )
    fact_check = asset.get("fact_check") or evaluate_fact_check(asset)
    # FRUEHER: `numbers_found and not passed` -- bei text ohne Zahlen war
    # numbers_found=0 und damit passed=False, das Gate liess den Asset durch.
    # Jetzt gilt: ohne bestandenen Fact-Check keine Freigabe. Reine
    # Opinion-Formate brauchen einen expliziten Opt-out in settings.json.
    _cm_cfg = _get_content_machine_cfg()
    _channel = str(asset.get("channel") or "")
    _require_facts = bool(_cm_cfg.get("require_facts", True))
    _per_channel = _cm_cfg.get("require_facts_by_channel") or {}
    if isinstance(_per_channel, dict) and _channel in _per_channel:
        _require_facts = bool(_per_channel[_channel])
    if _require_facts and not fact_check.get("passed"):
        raise ValueError(
            "Fact-Check blockiert Freigabe: " + "; ".join(
                str(i) for i in (fact_check.get("issues") or [])[:3]
            )
        )

    # Batch C: Plagiats-/Rechte-Gate. Bewusst ENG gefasst — blockiert nur bei
    # Hoher Aehnlichkeit (>0.8) oder explizit verweigerten Rechten. Ein leerer
    # Korpus oder leere Quellen duerfen die Freigabe NICHT verhindern.
    p_report = asset.get("plagiarism_report") or {}
    rights = p_report.get("rights") or {}
    sim = p_report.get("plagiarism") or {}
    if rights.get("denied"):
        raise ValueError(
            "Rechte-Gate blockiert Freigabe: " +
            "; ".join(str(i) for i in (rights.get("issues") or [])[:3])
        )
    max_sim = 0.0
    try:
        max_sim = float(sim.get("max_similarity") or 0.0)
    except (TypeError, ValueError):
        max_sim = 0.0
    if sim.get("checked") and max_sim > 0.8:
        raise ValueError(
            f"Plagiats-Gate blockiert Freigabe: Aehnlichkeit {max_sim:.2f} > 0.8 — "
            + "; ".join(str(i) for i in (sim.get("issues") or [])[:2])
        )
    # checked=False war frueher ein stiller Freigabe-Pass. Mit dem
    # Research-Korpus ist der Check jetzt real; fehlt er, muss der HITL-Pfad
    # greifen, statt automatisch zu veroeffentlichen.
    if _require_facts and not sim.get("checked"):
        raise ValueError(
            "Plagiats-Gate blockiert Freigabe: kein Belegkorpus vorhanden — "
            "bitte Research-Quellen an das Asset haengen (checked=False)."
        )
    return report


def _record_approval(
    conn,
    asset_id: str,
    action: str,
    *,
    decision_id: str = "",
    actor: str = "",
    role: str = "",
    created_at: str = "",
) -> str:
    """Batch D: schreibt eine Zeile in die Freigabe-Historie (gleiche Connection)."""
    aid = f"appr-{secrets.token_hex(6)}"
    conn.execute(
        "INSERT INTO content_asset_approvals "
        "(id, asset_id, decision_id, action, actor, role, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            aid, asset_id, str(decision_id or "").strip(), str(action or "").strip(),
            str(actor or "").strip(), str(role or "").strip(), created_at or _utc_now_iso(),
        ),
    )
    return aid


def approval_history(asset_id: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Batch D: liefert die Freigabe-Historie eines Assets (aelteste zuerst)."""
    init_content_machine_db(db_path)
    with _conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM content_asset_approvals WHERE asset_id = ? ORDER BY created_at ASC, id ASC",
            (asset_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def approve_asset(
    asset_id: str,
    scheduled_at: str = "",
    *,
    decision_id: str = "",
    actor: str = "",
    role: str = "reviewer",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Nur review/draft → approved/scheduled. Direktes draft→published ist
    damit nicht mehr möglich (HITL-Gate-Umgehung).

    Bei manueller Freigabe wird die decision_id mitgeschrieben — sonst ist
    die Freigabe im Audit-Pfad nicht dem HITL-Entscheid zuordenbar.
    Batch D: setzt `reviewer` und schreibt zusaetzlich eine Approval-History-Zeile.
    """
    new_status = "scheduled" if scheduled_at else "approved"
    now = _utc_now_iso()
    init_content_machine_db(db_path)  # Batch D: Approval-Tabelle + Migrationen sicherstellen
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
            "UPDATE content_assets SET status = ?, scheduled_at = ?, decision_id = ?, "
            "reviewer = ?, updated_at = ? "
            "WHERE id = ? AND status IN ('review', 'draft')",
            (
                new_status, str(scheduled_at or ""), str(decision_id or "").strip(),
                str(actor or "").strip(), now, asset_id,
            ),
        )
        if int(cur_update.rowcount or 0) != 1:
            raise ValueError("Statusübergang wurde concurrently geändert — bitte erneut prüfen.")
        _record_approval(
            conn, asset_id, new_status,
            decision_id=decision_id, actor=actor, role=role, created_at=now,
        )
        conn.commit()
        row = conn.execute("SELECT * FROM content_assets WHERE id = ?", (asset_id,)).fetchone()
    return _row_to_asset(row)


def build_geo_jsonld(asset: Dict[str, Any], external_url: str = "") -> Dict[str, Any]:
    """CM 2.0/GEO: JSON-LD Article/FAQPage aus einem publizierten Asset.

    Der seo_geo_specialist hatte bisher nur Prompt-Wissen; hier wird echte
    maschinenlesbare Struktur erzeugt (Schema.org), die Such-/Antwortsysteme
    zitieren koennen.
    """
    schema: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": str(asset.get("title") or "")[:160],
        "description": str(asset.get("hook") or "")[:300],
        "articleBody": str(asset.get("body") or "")[:20000],
        "datePublished": _utc_now_iso(),
        "author": {"@type": "Organization", "name": "Archon OS Content Machine"},
    }
    if external_url:
        schema["url"] = external_url
        schema["mainEntityOfPage"] = {"@type": "WebPage", "@id": external_url}
    sources = asset.get("sources") or []
    if sources:
        schema["citation"] = [
            str(s.get("url") or s.get("title") or "") for s in sources
            if isinstance(s, dict) and (s.get("url") or s.get("title"))
        ][:20]
    return schema


def append_llms_txt(asset: Dict[str, Any], external_url: str = "", db_path=None) -> str:
    """CM 2.0/GEO: llms.txt-Eintrag pflegen (Citation-Readiness)."""
    try:
        from backend.platform_paths import OBSIDIAN_VAULT
        base = OBSIDIAN_VAULT
    except Exception:
        base = os.path.join(WORKSPACE_DIR, "obsidian_vault") if "WORKSPACE_DIR" in globals() else "."
    path = os.path.join(base, "llms.txt")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    line = f"- [{asset.get('title', 'Asset')}]({external_url}): {asset.get('hook', '')[:200]}\n"
    existing = ""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                existing = fh.read()
        except Exception:
            existing = ""
    if line.strip() not in existing:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
    return path


def mark_asset_published(
    asset_id: str,
    external_url: str = "",
    db_path: Optional[str] = None,
    *,
    actor: str = "",
) -> Dict[str, Any]:
    """Publish nur aus approved/scheduled — niemals direkt aus draft/review.
    Batch D: setzt `publisher` und schreibt eine Approval-History-Zeile.
    """
    now = _utc_now_iso()
    init_content_machine_db(db_path)  # Batch D: Approval-Tabelle + Migrationen sicherstellen
    with _conn(db_path) as conn:
        row = conn.execute("SELECT * FROM content_assets WHERE id = ?", (asset_id,)).fetchone()
        if not row:
            raise KeyError(f"Content-Asset '{asset_id}' nicht gefunden.")
        cur = str(row["status"] or "")
        if cur not in ("approved", "scheduled"):
            raise ValueError(f"Unzulässiger Statusübergang: {cur} → published")
        _enforce_asset_quality(conn, row)
        cur_update = conn.execute(
            "UPDATE content_assets SET status = 'published', published_at = ?, external_url = ?, "
            "publisher = ?, updated_at = ? "
            "WHERE id = ? AND status IN ('approved', 'scheduled')",
            (now, str(external_url or "").strip(), str(actor or "").strip(), now, asset_id),
        )
        if int(cur_update.rowcount or 0) != 1:
            raise ValueError("Statusübergang wurde concurrently geändert — bitte erneut prüfen.")
        _record_approval(
            conn, asset_id, "published",
            decision_id=str(row["decision_id"] or ""),
            actor=actor, role="publisher", created_at=now,
        )
        conn.commit()
        row = conn.execute("SELECT * FROM content_assets WHERE id = ?", (asset_id,)).fetchone()
    published = _row_to_asset(row)
    # CM 2.0/GEO: JSON-LD + llms.txt nach dem Publish. Fehler duerfen den
    # bereits erfolgreichen Publish nicht rueckgaengig machen.
    try:
        geo = build_geo_jsonld(published, external_url=external_url)
        with _conn(db_path) as conn:
            conn.execute(
                "UPDATE content_assets SET geo_jsonld_json = ? WHERE id = ?",
                (json.dumps(geo, ensure_ascii=False), asset_id),
            )
            conn.commit()
        published["geo_jsonld"] = geo
        published["llms_txt_path"] = append_llms_txt(published, external_url=external_url)
    except Exception as geo_exc:
        logger.warning("[ContentMachine] GEO-Artefakte fehlgeschlagen: %s", geo_exc)
    return published


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


# =========================================================================
# BATCH D: SKILL-REGELN AUS .agents/skills IN DEN DAG INJIZIEREN
# =========================================================================

_CORE_REVIEW_SKILL = "li-human"
_CHANNEL_SKILLS: Dict[str, tuple] = {
    "linkedin": ("li-post", "li-carousel", "anti-ai-slop"),
    "x_threads": ("li-post", "anti-ai-slop"),
    "newsletter": ("anti-ai-slop",),
}
_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _safe_skill_path(skill_name: str, workspace_dir: str = "") -> Optional[str]:
    """Sicherer Pfad zu einer SKILL.md (Pfad-Jail). None bei fehlender/ungenueltiger Datei."""
    name = str(skill_name or "").strip()
    if not name or not _SKILL_NAME_RE.match(name):
        return None
    base = workspace_dir or WORKSPACE_DIR
    try:
        skills_root = os.path.realpath(os.path.join(base, ".agents", "skills"))
        candidate = os.path.realpath(os.path.join(skills_root, name, "SKILL.md"))
        if os.path.commonpath([skills_root, candidate]) != skills_root:
            return None
    except Exception:
        return None
    return candidate if os.path.isfile(candidate) else None


def _voice_rules_fallback(skill_name: str, max_rules: int) -> str:
    """Liest echte Stilregeln aus config/voice.md (SSOT der Brand Voice).

    Nur als Fallback, wenn eine SKILL.md fehlt. Gibt bei leerer/quellenloser
    Datei '' zurueck, damit der Aufrufer klar 'keine Regeln' melden kann.
    """
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, "config", "voice.md")
        if not os.path.isfile(path):
            return ""
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read(12000)
    except Exception:
        return ""
    lines: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("- ", "* ")) or re.match(r"^\d+\.\s", line):
            rule = re.sub(r"^[*\-]\s*|^\d+\.\s*", "", line).strip()
            rule = rule.replace("**", "").replace("`", "").strip(" :;-")
            rule = re.sub(r"\s+", " ", rule)
            if 6 <= len(rule) <= 220 and rule.lower() not in {r.lower() for r in lines}:
                lines.append(rule)
                if len(lines) >= max_rules:
                    break
    if not lines:
        return ""
    return f"- [Regeln aus config/voice.md — Ersatz für Skill '{skill_name}']\n" + "\n".join(
        f"- {r}" for r in lines
    )


def _extract_skill_rules(skill_name: str, max_rules: int = 8, workspace_dir: str = "") -> str:
    """Extrahiert eine kompakte Regel-Block aus einer SKILL.md.

    Fehlende/unklare Dateien liefern einen expliziten Hinweis statt zu crashen.
    """
    path = _safe_skill_path(skill_name, workspace_dir)
    if not path:
        # KRITISCH: die 'verpflichtenden' li-human-Regeln wurden frueher nie
        # injiziert, weil .agents/skills/li-human/SKILL.md nicht existiert.
        # Fallback auf die echte, vorhandene Regelquelle config/voice.md,
        # damit der Review-Node nicht mit einer leeren Anweisung arbeitet.
        voice_fallback = _voice_rules_fallback(skill_name, max_rules)
        if voice_fallback:
            return voice_fallback
        return (
            f"- [Hinweis] Skill '{skill_name}' nicht gefunden und keine "
            "Fallback-Regeln verfuegbar — Regeln nicht injiziert."
        )
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read(24000)
    except Exception as exc:
        return f"- [Hinweis] Skill '{skill_name}' nicht lesbar: {exc} (Graceful Degradation)."

    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2]

    rules: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        rule = ""
        bold = re.match(r"^\*\*(.+?)\*\*", line)
        if bold:
            rule = bold.group(1)
        elif line.startswith("- ") or re.match(r"^\d+\.\s", line):
            rule = re.sub(r"^\d+\.\s*", "", line[2:] if line.startswith("- ") else line)
        if not rule:
            continue
        rule = re.sub(r"^\d+[.)]\s*", "", rule).strip()
        rule = rule.replace("**", "").replace("`", "").strip(" :;-")
        rule = re.sub(r"\s+", " ", rule)
        if len(rule) < 6 or len(rule) > 220:
            continue
        if rule.lower() in {r.lower() for r in rules}:
            continue
        rules.append(rule)
        if len(rules) >= max_rules:
            break
    if not rules:
        return (
            f"- [Hinweis] Skill '{skill_name}' enthaelt keine extrahierbaren Regeln "
            "(Graceful Degradation)."
        )
    return "\n".join(f"- [{skill_name}] {r}" for r in rules)


def _skill_rules_for_channel(channel: str, max_rules: int = 6) -> str:
    """Kern-Review-Skill (li-human) + kanalrelevante Skills, dedupliziert."""
    names = [_CORE_REVIEW_SKILL] + list(_CHANNEL_SKILLS.get(str(channel).lower(), ()))
    blocks = [_extract_skill_rules(n, max_rules=max_rules) for n in dict.fromkeys(names)]
    return "\n".join(blocks)


def build_content_repurposing_dag(campaign: Dict[str, Any], *, require_hitl_gate: bool = True) -> Dict[str, Any]:
    """Erzeugt einen ausfuehrbaren Multi-Agenten-DAG fuer `workflow_dag_runner.run_workflow_dag`."""
    topic = campaign.get("topic") or campaign.get("title") or ""
    audience = campaign.get("target_audience") or "Entscheider & Gruender"
    voice = campaign.get("brand_voice") or "Direkt, faktenbasiert, praxisnah"
    notes = _source_notes_text(campaign.get("source_notes"))

    # P1/Content B6: Feedback-Loop war Write-Only. voice_winner_hooks.md und
    # config/voice.md wurden gespeichert, aber nie in Prompts geladen. Jetzt
    # werden Top-Learnings + Voice-Dateien als aktiver Kontext injiziert.
    feedback_lines: List[str] = []
    try:
        from local_memory_bridge import memory_bridge
        # Die Learnings werden unter den Rollen-IDs geschrieben (z.B.
        # storyteller_ghostwriter), nicht unter "content_machine". Mit dem
        # harten Filter blieb der Feedback-Block dauerhaft leer.
        learnings = memory_bridge.search_learnings(str(topic)[:100], limit=5)
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
        # Batch D: Skill-Regeln (li-human + kanalrelevant) aus .agents/skills
        # injizieren. CHANNEL_SPECS.best_practices bleiben erhalten.
        skill_rules = _skill_rules_for_channel(ch)
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
                f"Skill-Regeln (li-human & kanalrelevant, aus .agents/skills — verpflichtend):\n"
                f"{skill_rules}\n\n"
                "ZITATIONSPFLICHT: Fakten und Zahlen nur aus den Belegquellen des "
                "Research-Schritts. Unbelegte Behauptungen weglassen.\n\n"
                "Antworte als JSON-Objekt mit den Schluesseln: "
                "title, hook, body, visual_brief, hashtags (Liste), cta."
            ),
            "expected_output": f"JSON-Objekt fuer {spec['label']} inkl. Hook, Body, Visual-Brief und CTA.",
        })
        edges.append({"from": "n_master_brief", "to": nid, "condition": "on_success", "data_mode": "full"})

    if require_hitl_gate:
        # Batch D: verpflichtender li-human-Review-Schritt zwischen Kanal-Fan-Out
        # und HITL-Freigabe. Regelblock stammt aus .agents/skills/li-human/SKILL.md.
        review_node_id = "n_li_human_review"
        review_rules = _extract_skill_rules(_CORE_REVIEW_SKILL, max_rules=10)
        nodes.append({
            "id": review_node_id,
            "title": f"li-human Sprach- & Stil-Review: {campaign['title']}",
            "type": "agent",
            "agent_id": "content_repurposing_specialist",
            "skill": _CORE_REVIEW_SKILL,
            "depends_on": channel_node_ids,
            "prompt": (
                "Pflicht-Review ALLER Kanal-Assets nach der li-human-Methode: entferne "
                "unsichtbare Zeichen, Gedankenstriche/KI-Floskeln und strukturelle "
                "Muster (Regel von drei, Reflex-Engagement-Bait, Hashtag-Waende). "
                "Behalte Fakten, Zahlen und Zitationen unveraendert bei.\n"
                f"li-human Regeln:\n{review_rules}\n\n"
                "Liefere die bereinigten Kanal-Assets als JSON-Objekt (Kanal-ID -> "
                "title, hook, body, visual_brief, hashtags, cta) und eine kurze Liste "
                "der vorgenommenen Aenderungen."
            ),
            "expected_output": "Bereinigte Kanal-Assets plus Aenderungsprotokoll (li-human).",
        })
        for cnid in channel_node_ids:
            edges.append({
                "from": cnid, "to": review_node_id,
                "condition": "on_success", "data_mode": "full",
            })
        nodes.append({
            "id": "n_editorial_gate",
            "title": f"Redaktions-Freigabe (HITL): {campaign['title']}",
            "type": "gate",
            "depends_on": [review_node_id],
        })
        edges.append({
            "from": review_node_id, "to": "n_editorial_gate",
            "condition": "on_success", "data_mode": "summary",
        })

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

    # CM 2.0: harte Kanalgrenzen aus CHANNEL_SPECS statt hartcodiertem 400.
    hook_limit = int(spec.get("hook_max_chars") or 180)
    max_chars = int(spec.get("max_chars") or 0)
    first_line = next((ln.strip() for ln in content.splitlines() if ln.strip()), "")[:hook_limit]
    body = str(parsed.get("body") or content or f"[Entwurf fuer {spec['label']} zu '{campaign_title}']")
    if max_chars and len(body) > max_chars:
        body = body[:max_chars].rstrip() + " …"
    # Bei Parse-FehHER darf der rohe Prompt-Output NICHT als fertiges Asset
    # uebernommen werden (frueher: identischer Body fuer alle Kanaele).
    parse_failed = bool(content) and not parsed
    if parse_failed:
        body = f"[Strukturiertes Asset fehlt — Agent lieferte ungeparsten Output fuer {spec['label']}]\n{body}"[:max_chars or 3000]
    sources = parsed.get("sources") if isinstance(parsed.get("sources"), list) else []
    return {
        "channel": channel,
        "format_type": spec["format"],
        "title": str(parsed.get("title") or f"{spec['label']}: {campaign_title}")[:160],
        "hook": str(parsed.get("hook") or first_line)[:hook_limit],
        "body": body,
        "visual_brief": str(parsed.get("visual_brief") or f"Format {spec['aspect_ratio']}, klare Typografie, hohe Kontraste"),
        "hashtags": parsed.get("hashtags") if isinstance(parsed.get("hashtags"), list) else [f"#{channel}", "#ArchonOS"],
        "cta": str(parsed.get("cta") or "Kommentiere deine Erfahrung oder folge fuer Teil 2."),
        "duration_sec": int(parsed.get("duration_sec") or spec.get("target_duration_sec") or 0),
        "agent_id": str(raw_out.get("agent_id") or spec["recommended_agent"]),
        "sources": sources,
        "parse_failed": parse_failed,
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
    # Batch D: Dossier-Pfad aus dem Research-Knoten auf alle Assets vererben.
    research_out = outputs.get("n_research") or {}
    dossier_path = str(
        research_out.get("dossier_path") if isinstance(research_out, dict) else ""
    ) or ""
    # KRITISCH: die Research-Quellen kamen frueher nie bei den Assets an.
    # Der Kanal-Agent liefert sie nicht, der Research-Knoten schon. Ohne
    # sources markiert evaluate_fact_check jede Zahl als 'unbacked' und das
    # Gate blockiert die Freigabe. Gleichzeitig sind die Snippets der
    # natuerliche Plagiats-Korpus.
    research_sources: List[Dict[str, Any]] = []
    if isinstance(research_out, dict):
        _rs = research_out.get("sources") or []
        if isinstance(_rs, list):
            research_sources = [s for s in _rs if isinstance(s, dict)]
    plagiarism_corpus = [
        str(s.get("snippet") or s.get("text") or s.get("summary") or "")
        for s in research_sources
        if str(s.get("snippet") or s.get("text") or s.get("summary") or "").strip()
    ]

    for node in dag_def["nodes"]:
        ch = node.get("channel")
        nid = node["id"]
        if not ch or nid not in outputs:
            continue
        if run_res.get("node_statuses", {}).get(nid) not in ("completed", "skipped_cached"):
            continue
        asset_data = _parse_asset_output(ch, camp["title"], outputs[nid])
        asset_data["campaign_id"] = campaign_id
        # Quellen nur ergaenzen, wenn der Kanal-Agent keine eigenen geliefert hat.
        if not asset_data.get("sources") and research_sources:
            asset_data["sources"] = research_sources
        if not asset_data.get("plagiarism_corpus") and plagiarism_corpus:
            asset_data["plagiarism_corpus"] = plagiarism_corpus
        # Gate nur dann direkt freigeben, wenn auch die Qualitaet besteht.
        _quality = evaluate_asset_quality(asset_data)
        approved_now = bool(gate_approved and _quality.get("passed", False))
        asset_data["status"] = (
            "approved" if approved_now
            else ("review" if require_hitl_gate else "draft")
        )
        # Ein 'approved'-Asset ohne scheduled_at wird vom Publish-Sweep nie
        # gefunden (Filter scheduled_at != '' AND <= now) — dauerhafte
        # Sackgasse. Direkt mit aktuellem Zeitstempel planen.
        if approved_now and not asset_data.get("scheduled_at"):
            asset_data["scheduled_at"] = _utc_now_iso()
        asset_data["decision_id"] = decision_id
        asset_data["dossier_path"] = dossier_path
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
        "dossier_path": dossier_path,
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


def _source_notes_text(value: Any) -> str:
    """Liest den Klartext aus source_notes (neu: JSON-Objekt, alt: Plaintext)."""
    if isinstance(value, str) and value.lstrip().startswith("{"):
        try:
            obj = json.loads(value)
            if isinstance(obj, dict):
                return str(obj.get("text") or "")
        except (ValueError, TypeError):
            return value
    return str(value or "")


def ingest_source_to_campaign(payload: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    """Erstellt eine Multi-Channel-Kampagne aus URL (SSRF-geschuetzt), Obsidian-Notiz oder Transkript.

    Batch C: Fremd-HTML wird nicht mehr stillschweigend als eigener Text
    gespeichert. Stattdessen werden Rechte-Metadaten (license/rights) und ein
    explizites rights_status flag im source_notes-JSON mitgefuehrt.
    """
    source_type = str(payload.get("source_type") or "transcript").strip().lower()
    extracted_title = str(payload.get("title") or "").strip()
    source_url = str(payload.get("source_url") or "").strip()
    extracted_text = ""
    rights_meta = {
        "license": DEFAULT_LICENSE,
        "rights": DEFAULT_RIGHTS,
        "rights_status": "unknown",
        "license_declared": False,
        "denied": False,
        "restricted": False,
    }

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
        # Batch C: Rechte aus den tatsaechlich geladenen HTML-Metadaten.
        rights_meta = rights_from_html(raw)
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
        extracted_text = str(payload.get("transcript") or _source_notes_text(payload.get("source_notes")) or "").strip()
        if not extracted_title:
            first_line = next((ln.strip() for ln in extracted_text.splitlines() if ln.strip()), "")
            extracted_title = first_line[:90] or "Content-Kampagne aus Transkript"

    if not extracted_text:
        raise ValueError("Quell-Inhalt ist leer — keine Kampagne erstellt.")

    # Batch C: explizite Angaben aus dem Payload haben Vorrang vor Metadaten;
    # fehlende Angaben bleiben konservativ 'unknown'/'unbekannt'.
    for key in ("license", "rights"):
        override = str(payload.get(key) or "").strip()
        if override:
            rights_meta[key] = override
    classify = classify_rights(rights_meta.get("license"), rights_meta.get("rights"))
    rights_meta["rights_status"] = str(payload.get("rights_status") or classify["status"])
    rights_meta["denied"] = bool(classify["denied"])
    rights_meta["restricted"] = bool(classify["restricted"])

    notes_obj = {
        "text": extracted_text[:6000],
        "source_url": source_url,
        "source_type": source_type,
        "license": rights_meta["license"],
        "rights": rights_meta["rights"],
        "rights_status": rights_meta["rights_status"],
        "license_declared": bool(rights_meta.get("license_declared")),
        "rights_denied": bool(rights_meta.get("denied")),
        "rights_restricted": bool(rights_meta.get("restricted")),
    }
    notes_json = json.dumps(notes_obj, ensure_ascii=False)

    camp = create_campaign(
        {
            "title": extracted_title[:160],
            "topic": str(payload.get("topic") or extracted_title)[:220],
            "target_audience": payload.get("target_audience") or "Gruender, Geschaeftsfuehrer & Tech-Entscheider",
            "brand_voice": payload.get("brand_voice") or "Direkt, faktenbasiert, praxisnah, ohne KI-Floskeln",
            "pillar": payload.get("pillar") or "Content Repurposing",
            "source_url": source_url,
            "source_notes": notes_json,
            "channels": payload.get("channels") or DEFAULT_CHANNELS,
        },
        db_path=db_path,
    )
    return {
        "campaign": camp,
        "source_type": source_type,
        "ingested_chars": len(extracted_text),
        "license": rights_meta["license"],
        "rights": rights_meta["rights"],
        "rights_status": rights_meta["rights_status"],
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
        base_text = str(arow["body"] or arow["hook"] or _source_notes_text(camp.get("source_notes")) or camp.get("topic") or "")
    if not base_text:
        base_text = str(_source_notes_text(camp.get("source_notes")) or camp.get("topic") or camp["title"])

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
                    # CM 2.0: Belegquellen erben — die Zahlen im Clip stammen
                    # aus dem Transcription/Research der Campaign.
                    "sources": [{
                        "title": camp["title"],
                        "text": str(_source_notes_text(camp.get("source_notes")) or camp.get("topic") or ""),
                        "url": str(camp.get("source_url") or ""),
                    }],
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
    # Die Plattform-Antwort enthaelt haeufig den echten Permalink. Ohne diese
    # URL waren geo_jsonld und llms.txt unbrauchbar ("- [Titel](): ...").
    external_url = ""
    raw_response = delivery.get("response")
    if isinstance(raw_response, str) and raw_response.strip():
        try:
            parsed = json.loads(raw_response)
            if isinstance(parsed, dict):
                for key in ("url", "permalink", "external_url", "link"):
                    candidate = parsed.get(key)
                    if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                        external_url = candidate
                        break
        except (TypeError, ValueError):
            pass
    updated = mark_asset_published(asset_id, external_url=external_url, db_path=db_path)
    return {
        "status": "published",
        "http_status": delivery.get("http_status"),
        "external_url": external_url,
        "asset": updated,
        "idempotency_key": idem,
    }


def _get_content_machine_cfg() -> Dict[str, Any]:
    """Settings-Sektion der Content-Machine (ein Ort fuer alle Gates)."""
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, "settings.json")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as fh:
                cfg = json.load(fh)
            if isinstance(cfg, dict):
                section = cfg.get("content_machine") or {}
                if isinstance(section, dict):
                    return section
    except Exception:
        pass
    return {}


def get_default_publish_webhook_url() -> str:
    """Zentrale Publish-Ziel-URL aus ENV oder settings.json.

    Der Scheduler rief publish_scheduled_due_assets() frueher ohne webhook_url
    auf — damit wurde nur ein DB-Status gesetzt und kein Content ausgeliefert.
    """
    env_url = (os.environ.get("ARCHON_CONTENT_PUBLISH_WEBHOOK") or "").strip()
    if env_url:
        return env_url
    return str(_get_content_machine_cfg().get("publish_webhook_url") or "").strip()


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
            # FRUEHER: ohne webhook_url wurde nur der DB-Status gesetzt —
            # Content verliess das System nie, der Sweep loggte aber "published".
            target = webhook_url or get_default_publish_webhook_url()
            if target:
                dispatch_asset_to_webhook(a["id"], target, dry_run=False, db_path=db_path)
            else:
                mark_asset_published(a["id"], db_path=db_path)
            published.append(a["id"])
        except Exception as exc:
            errors.append({"asset_id": a["id"], "error": str(exc)})
    return {"status": "ok", "due_count": len(due_assets), "published": published, "errors": errors}


def _norm_citation(value: Any) -> str:
    """Deterministische Normalisierung fuer Zitat-URLs/Titel (offline)."""
    return str(value or "").strip().rstrip("/").lower()


def check_geo_citations(
    hours: int = 48,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Batch D: GEO-Zitatpruefung 48h nach Publish (offline, deterministisch).

    Fuer alle vor `hours` Stunden publizierten Assets mit JSON-LD wird geprueft,
    ob jede `citation` (URL oder Titel) unter den Belegquellen (`sources`) des
    Assets vorkommt. Das Ergebnis wird pro Asset in `citation_check_json`
    persistiert. Es gibt KEINE Netzwerkaufrufe.
    """
    init_content_machine_db(db_path)
    window = max(1, int(hours))
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - timedelta(hours=window)).isoformat()
    reports: List[Dict[str, Any]] = []
    assets_checked = 0
    citations_checked = 0
    citations_missing = 0
    assets_with_missing = 0

    with _conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM content_assets
            WHERE status = 'published'
              AND published_at != '' AND published_at <= ?
              AND geo_jsonld_json NOT IN ('', '{}')
            ORDER BY published_at ASC
            """,
            (cutoff,),
        ).fetchall()
        for row in rows:
            asset = _row_to_asset(row)
            geo = asset.get("geo_jsonld") or {}
            citations = geo.get("citation") if isinstance(geo, dict) else None
            if not isinstance(citations, (list, tuple)):
                citations = []
            sources = asset.get("sources") or []
            if not isinstance(sources, (list, tuple)):
                sources = []
            valid = set()
            for src in sources:
                if isinstance(src, dict):
                    for key in ("url", "title", "link"):
                        if src.get(key):
                            valid.add(_norm_citation(src.get(key)))
                elif src:
                    valid.add(_norm_citation(src))
            missing = [
                str(c) for c in citations
                if c and _norm_citation(c) not in valid
            ]
            citations_checked += len(citations)
            citations_missing += len(missing)
            passed = not missing
            if not passed:
                assets_with_missing += 1
            report = {
                "asset_id": asset.get("id"),
                "title": str(asset.get("title") or "")[:160],
                "channel": str(asset.get("channel") or ""),
                "published_at": str(asset.get("published_at") or ""),
                "checked_at": _utc_now_iso(),
                "hours": window,
                "citations": [str(c) for c in citations],
                "missing": missing,
                "sources_count": len(sources),
                "passed": passed,
                "note": "Offline-Vergleich JSON-LD citation <-> sources; keine Netzwerkaufrufe.",
            }
            reports.append(report)
            assets_checked += 1
            conn.execute(
                "UPDATE content_assets SET citation_check_json = ? WHERE id = ?",
                (json.dumps(report, ensure_ascii=False), asset.get("id")),
            )
        conn.commit()

    return {
        "status": "ok",
        "hours": window,
        "assets_checked": assets_checked,
        "citations_checked": citations_checked,
        "citations_missing": citations_missing,
        "assets_with_missing": assets_with_missing,
        "reports": reports,
    }


def sweep_content_performance_feedback(
    *,
    hours_min: int = 48,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """48h/7d-Performance-Rueckfluss: speist erfolgreiche Hooks gewichtet ins FTS5-Memory & Voice-Vorschlaege."""
    init_content_machine_db(db_path)
    # Batch D: 'datetime' ist das Modul (import datetime) — frueher falsch als
    # Klasse verwendet (AttributFehler/NameError), daher korrekt qualifizieren.
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - timedelta(hours=max(1, int(hours_min)))).isoformat()
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
            # Diese Datei ist gleichzeitig Feedback-QUELLE des DAG-Builders.
            # Mit open("w") sah jeder Sweep nur noch seine eigenen Vorschlaege
            # und die Historie ging verloren. Jetzt anhaengen + deduplizieren.
            header = "# Automatische Brand-Voice Hook-Vorschlaege (48h+ Performance-Rueckfluss)\n\n"
            existing = ""
            if os.path.exists(voice_sugg_path):
                try:
                    with open(voice_sugg_path, "r", encoding="utf-8") as vf:
                        existing = vf.read()
                except Exception:
                    existing = ""
            known = set(line.strip() for line in existing.splitlines() if line.strip().startswith("- "))
            fresh = [s for s in suggestions[:15] if s.strip() not in known]
            if fresh:
                with open(voice_sugg_path, "a", encoding="utf-8") as vf:
                    if not existing:
                        vf.write(header)
                    vf.write("\n".join(fresh) + "\n")
        except Exception as exc:
            logger.debug(f"[ContentMachine] voice_winner_hooks.md Schreibfehler: {exc}")

    # Batch D: GEO-Zitatpruefung als Teil des 48h-Feedback-Sweeps. Fehler duerfen
    # den eigentlichen Feedback-Loop nicht blockieren.
    citation_report: Dict[str, Any] = {}
    try:
        citation_report = check_geo_citations(hours=hours_min, db_path=db_path)
    except Exception as exc:
        logger.debug("[ContentMachine] GEO-Zitatpruefung im Sweep uebersprungen: %s", exc)

    return {
        "status": "ok",
        "recorded_learnings": recorded,
        "suggestions_count": len(suggestions),
        "geo_citation_check": citation_report,
    }


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
        # KRITISCH: der Publish-Sweep filtert zwingend
        # scheduled_at != '' AND scheduled_at <= now. Wurde nur der Status
        # auf 'scheduled' gesetzt, blieben Assets dauerhaft haengen (Sackgasse).
        if approved:
            cur = conn.execute(
                "UPDATE content_assets SET status = ?, scheduled_at = ?, updated_at = ? "
                "WHERE campaign_id = ? AND status IN ('review', 'draft')",
                (target, now, now, campaign_id),
            )
        else:
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
