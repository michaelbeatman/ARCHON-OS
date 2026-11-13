"""
backend/deal_pipeline.py
Deal-Pipeline mit Stufen & Forecast-Engine für Archon OS (t-5b159d, Pillar 4 & CRM).
- Verwaltet Geschäftschancen und Leads in einer SQLite-Datenbank mit WAL-Modus (`data/deals.db`).
- Phasen: Lead (10%) -> Discovery (25%) -> Proposal (50%) -> Negotiation (75%) -> Closed Won (100%) / Closed Lost (0%).
- Berechnet gewichtete Umsatzprognosen (Weighted Pipeline Forecast), Win-Rates und monatliche Fälligkeiten.
- Nahtlos integrierbar in CRM, PocketBase und Kanban.
"""

import os
import sys
import uuid
import sqlite3
import datetime
from typing import Dict, Any, List, Optional, Tuple

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "deals.db")

STAGE_CONFIG = {
    "lead": {"name_de": "Qualifizierung", "default_prob": 0.10, "is_active": True},
    "discovery": {"name_de": "Erstgespräch / Bedarfsanalyse", "default_prob": 0.25, "is_active": True},
    "proposal": {"name_de": "Angebot abgegeben", "default_prob": 0.50, "is_active": True},
    "negotiation": {"name_de": "Vertragsverhandlung", "default_prob": 0.75, "is_active": True},
    "closed_won": {"name_de": "Gewonnen / Abgeschlossen", "default_prob": 1.00, "is_active": False},
    "closed_lost": {"name_de": "Verloren", "default_prob": 0.00, "is_active": False},
}


def _get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.row_factory = sqlite3.Row
    return conn


def init_deals_db():
    conn = _get_connection()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS deals (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                partner_name TEXT NOT NULL,
                contact_email TEXT,
                stage TEXT NOT NULL DEFAULT 'lead',
                probability REAL DEFAULT 0.10,
                deal_value REAL DEFAULT 0.0,
                currency TEXT DEFAULT 'EUR',
                expected_close_date TEXT,
                actual_close_date TEXT,
                assigned_agent TEXT DEFAULT 'Robert',
                notes TEXT,
                lost_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_deals_stage ON deals(stage);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_deals_partner ON deals(partner_name);")
    conn.close()


init_deals_db()


class DealPipelineManager:
    """Verwaltung und Forecast-Berechnung für Vertriebs-Deals."""

    @classmethod
    def create_or_update(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Erstellt oder aktualisiert einen Deal."""
        conn = _get_connection()
        did = data.get("id") or f"deal-{uuid.uuid4().hex[:8]}"

        title = data.get("title", "Neuer Deal").strip()
        partner = data.get("partner_name", "Unbekannter Interessent").strip()
        email = data.get("contact_email", "")
        stage = data.get("stage", "lead").lower()
        if stage not in STAGE_CONFIG:
            stage = "lead"

        # Wahrscheinlichkeit ermitteln: manuelle Angabe oder Standard für die Phase
        prob = data.get("probability")
        if prob is None or prob == "":
            prob = STAGE_CONFIG[stage]["default_prob"]
        else:
            prob = float(prob)
            prob = max(0.0, min(1.0, prob))

        val = float(data.get("deal_value", 0.0))
        currency = data.get("currency", "EUR")
        expected_close = data.get("expected_close_date")
        actual_close = data.get("actual_close_date")
        if stage in ["closed_won", "closed_lost"] and not actual_close:
            actual_close = datetime.date.today().strftime("%Y-%m-%d")

        agent = data.get("assigned_agent", "Robert")
        notes = data.get("notes", "")
        lost_reason = data.get("lost_reason", "")
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with conn:
            conn.execute("""
                INSERT INTO deals (
                    id, title, partner_name, contact_email, stage, probability,
                    deal_value, currency, expected_close_date, actual_close_date,
                    assigned_agent, notes, lost_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    partner_name=excluded.partner_name,
                    contact_email=excluded.contact_email,
                    stage=excluded.stage,
                    probability=excluded.probability,
                    deal_value=excluded.deal_value,
                    currency=excluded.currency,
                    expected_close_date=excluded.expected_close_date,
                    actual_close_date=excluded.actual_close_date,
                    assigned_agent=excluded.assigned_agent,
                    notes=excluded.notes,
                    lost_reason=excluded.lost_reason,
                    updated_at=excluded.updated_at
            """, (
                did, title, partner, email, stage, prob, val, currency,
                expected_close, actual_close, agent, notes, lost_reason, now, now
            ))
        conn.close()
        return cls.get(did)

    @classmethod
    def get(cls, deal_id: str) -> Optional[Dict[str, Any]]:
        conn = _get_connection()
        row = conn.execute("SELECT * FROM deals WHERE id = ?", (deal_id,)).fetchone()
        conn.close()
        if not row:
            return None
        res = dict(row)
        res["stage_name_de"] = STAGE_CONFIG.get(res["stage"], {}).get("name_de", res["stage"])
        res["weighted_value"] = round(res["deal_value"] * res["probability"], 2)
        return res

    @classmethod
    def list_deals(
        cls,
        stage: Optional[str] = None,
        partner: Optional[str] = None,
        assigned_agent: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        conn = _get_connection()
        query = "SELECT * FROM deals WHERE 1=1"
        params: List[Any] = []

        if stage and stage.lower() != "alle":
            query += " AND stage = ?"
            params.append(stage.lower())

        if partner:
            query += " AND partner_name LIKE ?"
            params.append(f"%{partner}%")

        if assigned_agent and assigned_agent.lower() != "alle":
            query += " AND assigned_agent = ?"
            params.append(assigned_agent)

        query += " ORDER BY deal_value DESC, updated_at DESC"
        rows = conn.execute(query, tuple(params)).fetchall()
        conn.close()

        result = []
        for r in rows:
            d = dict(r)
            d["stage_name_de"] = STAGE_CONFIG.get(d["stage"], {}).get("name_de", d["stage"])
            d["weighted_value"] = round(d["deal_value"] * d["probability"], 2)
            result.append(d)
        return result

    @classmethod
    def move_stage(cls, deal_id: str, new_stage: str, notes: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Verschiebt einen Deal in eine neue Phase und passt Wahrscheinlichkeit automatisch an."""
        deal = cls.get(deal_id)
        if not deal:
            return None

        new_stage = new_stage.lower()
        if new_stage not in STAGE_CONFIG:
            return None

        deal["stage"] = new_stage
        deal["probability"] = STAGE_CONFIG[new_stage]["default_prob"]
        if notes:
            existing = deal.get("notes") or ""
            deal["notes"] = f"{existing}\n[{datetime.date.today().strftime('%Y-%m-%d')}] Stufe geändert auf {new_stage}: {notes}".strip()

        return cls.create_or_update(deal)

    @classmethod
    def delete(cls, deal_id: str) -> bool:
        conn = _get_connection()
        with conn:
            cur = conn.execute("DELETE FROM deals WHERE id = ?", (deal_id,))
            deleted = cur.rowcount > 0
        conn.close()
        return deleted

    @classmethod
    def get_forecast(cls) -> Dict[str, Any]:
        """
        Berechnet zentrale Vertriebs-KPIs und Forecasts:
        - Total Pipeline Value (aktive Deals)
        - Weighted Forecast Value (aktive Deals gewichtet nach Phase)
        - Won Revenue (bereits gewonnene Abschlüsse)
        - Win-Rate (%)
        - Phasenverteilung
        - Monatliche Abschlussplanung
        """
        deals = cls.list_deals()

        total_active_pipeline = 0.0
        weighted_forecast = 0.0
        won_revenue = 0.0
        lost_value = 0.0

        stage_counts = {k: 0 for k in STAGE_CONFIG}
        stage_values = {k: 0.0 for k in STAGE_CONFIG}
        monthly_forecast: Dict[str, Dict[str, float]] = {}

        for d in deals:
            st = d["stage"]
            val = d["deal_value"]
            prob = d["probability"]

            if st in stage_counts:
                stage_counts[st] += 1
                stage_values[st] += val

            # Aktive Deals (nicht won / lost)
            if STAGE_CONFIG.get(st, {}).get("is_active", False):
                total_active_pipeline += val
                weighted_forecast += (val * prob)

                close_month = (d.get("expected_close_date") or "")[:7]
                if close_month:
                    if close_month not in monthly_forecast:
                        monthly_forecast[close_month] = {"nominal": 0.0, "weighted": 0.0, "count": 0}
                    monthly_forecast[close_month]["nominal"] += val
                    monthly_forecast[close_month]["weighted"] += (val * prob)
                    monthly_forecast[close_month]["count"] += 1

            elif st == "closed_won":
                won_revenue += val
            elif st == "closed_lost":
                lost_value += val

        # Win-Rate
        closed_total = stage_counts["closed_won"] + stage_counts["closed_lost"]
        win_rate_pct = round((stage_counts["closed_won"] / closed_total * 100), 1) if closed_total > 0 else 0.0

        # Monatsübersicht sortieren
        sorted_months = sorted(monthly_forecast.items())

        return {
            "total_deals_count": len(deals),
            "active_pipeline_value": round(total_active_pipeline, 2),
            "weighted_forecast_value": round(weighted_forecast, 2),
            "won_revenue": round(won_revenue, 2),
            "lost_value": round(lost_value, 2),
            "win_rate_pct": win_rate_pct,
            "stage_breakdown": {
                k: {
                    "name_de": STAGE_CONFIG[k]["name_de"],
                    "count": stage_counts[k],
                    "total_value": round(stage_values[k], 2)
                }
                for k in STAGE_CONFIG
            },
            "monthly_schedule": [
                {"month": m, "nominal_value": round(v["nominal"], 2), "weighted_value": round(v["weighted"], 2), "deal_count": v["count"]}
                for m, v in sorted_months
            ]
        }


# Globaler Singleton
deal_pipeline_manager = DealPipelineManager()
