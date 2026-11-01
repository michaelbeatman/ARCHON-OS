"""
backend/contract_manager.py
Vertrags- & Fristenmanagement für Archon OS (t-0a2171, Pillar 2, 4 & 6).
- Parst Kündigungsfristen, Verlängerungsklauseln, Zahlungsziele und Kosten aus Verträgen.
- Verwaltet Verträge in einer SQLite-Datenbank mit WAL-Modus.
- Berechnet Fristen, Resttage und Dringlichkeitsstufen.
- Alarmiert zyklisch bei anstehenden Kündigungsstichtagen via Telegram und Kanban.
"""

import os
import re
import sys
import json
import uuid
import sqlite3
import datetime
from typing import Dict, Any, List, Optional, Tuple

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "contracts.db")


def _get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.row_factory = sqlite3.Row
    return conn


def init_contracts_db():
    """Initialisiert das Schema für Verträge und Fristenalarme."""
    conn = _get_connection()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS contracts (
                id TEXT PRIMARY KEY,
                contract_name TEXT NOT NULL,
                partner_name TEXT NOT NULL,
                category TEXT DEFAULT 'SaaS',
                start_date TEXT,
                end_date TEXT,
                notice_period_days INTEGER DEFAULT 30,
                notice_period_type TEXT DEFAULT 'days',
                next_notice_deadline TEXT,
                auto_renewal_months INTEGER DEFAULT 12,
                payment_due_days INTEGER DEFAULT 14,
                cost_amount REAL DEFAULT 0.0,
                cost_currency TEXT DEFAULT 'EUR',
                billing_cycle TEXT DEFAULT 'monatlich',
                status TEXT DEFAULT 'active',
                notes TEXT,
                source_file TEXT,
                alert_thresholds_json TEXT DEFAULT '[60, 30, 14, 7, 3, 1]',
                last_alert_sent TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS contract_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_id TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                days_remaining INTEGER NOT NULL,
                message TEXT NOT NULL,
                dispatched_via TEXT DEFAULT 'system',
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (contract_id) REFERENCES contracts (id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_contracts_deadline ON contracts(next_notice_deadline);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_contracts_status ON contracts(status);")
    conn.close()


init_contracts_db()


class ContractParser:
    """Extrahiert Fristen, Partner, Kosten und Klauseln heuristisch aus Rohtexten."""

    DATE_PATTERNS = [
        re.compile(r'\b(\d{4})-(\d{2})-(\d{2})\b'),               # YYYY-MM-DD
        re.compile(r'\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b'),          # DD.MM.YYYY
        re.compile(r'\b(\d{1,2})\/\d{1,2}\/(\d{4})\b'),           # DD/MM/YYYY
    ]

    MONTH_MAP = {
        "januar": 1, "jan": 1, "january": 1,
        "februar": 2, "feb": 2, "february": 2,
        "märz": 3, "maerz": 3, "mar": 3, "march": 3,
        "april": 4, "apr": 4,
        "mai": 5, "may": 5,
        "juni": 6, "jun": 6, "june": 6,
        "juli": 7, "jul": 7, "july": 7,
        "august": 8, "aug": 8,
        "september": 9, "sep": 9, "sept": 9,
        "oktober": 10, "okt": 10, "oct": 10, "october": 10,
        "november": 11, "nov": 11,
        "dezember": 12, "dez": 12, "dec": 12, "december": 12,
    }

    @classmethod
    def normalize_date(cls, raw: str) -> Optional[str]:
        if not raw:
            return None
        raw = raw.strip()
        # 1. YYYY-MM-DD
        m = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', raw)
        if m:
            return raw

        # 2. DD.MM.YYYY
        m = re.match(r'^(\d{1,2})\.(\d{1,2})\.(\d{4})$', raw)
        if m:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try:
                dt = datetime.date(y, mo, d)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                return None

        # 3. '15. Januar 2026'
        m = re.search(r'(\d{1,2})\.?\s+([A-Za-zäöü]+)\s+(\d{4})', raw, re.IGNORECASE)
        if m:
            d = int(m.group(1))
            month_name = m.group(2).lower()
            y = int(m.group(3))
            mo = cls.MONTH_MAP.get(month_name)
            if mo:
                try:
                    return datetime.date(y, mo, d).strftime("%Y-%m-%d")
                except ValueError:
                    pass

        return None

    @classmethod
    def parse(cls, text: str) -> Dict[str, Any]:
        """Analysiert einen Vertragstext und liefert erkannte Parameter."""
        data: Dict[str, Any] = {
            "contract_name": "Unbenannter Vertrag",
            "partner_name": "Unbekannter Partner",
            "category": "SaaS",
            "start_date": None,
            "end_date": None,
            "notice_period_days": 30,
            "notice_period_type": "days",
            "auto_renewal_months": 12,
            "payment_due_days": 14,
            "cost_amount": 0.0,
            "cost_currency": "EUR",
            "billing_cycle": "monatlich",
            "notes": ""
        }

        if not text:
            return data

        lines = [line.strip() for line in text.splitlines() if line.strip()]

        # 1. Partner / Vertragspartner
        partner_patterns = [
            r'([^\n\r]+?)\s*\((?:Vertragspartner|Auftragnehmer|Dienstleister|Lieferant|Vendor)\)',
            r'(?:Vertragspartner|Auftragnehmer|Dienstleister|Lieferant|Provider|Vendor)\s*[:=]\s*([^\n\r]+)',
            r'zwischen\s+([^\n\r]+?)\s+(?:und|\&)\s+([^\n\r]+)',
            r'(?:Firma|Unternehmen)\s*[:=]\s*([^\n\r]+)',
        ]
        for pat in partner_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                if len(m.groups()) >= 2:
                    p1 = m.group(1).strip()
                    p2 = m.group(2).strip()
                    # Wenn p1 unser eigenes System / Firma ist, wähle p2
                    if any(x in p1.lower() for x in ["archon", "wir", "uns", "auftraggeber"]):
                        found_partner = p2
                    else:
                        found_partner = p2 if "partner" in p2.lower() else p1
                else:
                    found_partner = m.group(1).strip()

                # Eventuelle Klammerzusätze entfernen
                found_partner = re.sub(r'\(.*?\)', '', found_partner).strip()
                if len(found_partner) > 2:
                    data["partner_name"] = found_partner.split("\n")[0][:80].strip()
                    break

        # 2. Titel / Vertragsgegenstand
        title_patterns = [
            r'(?:Vertrag über|Gegenstand|Vertragsgegenstand|Bezeichnung)\s*[:=]?\s*([A-Za-z0-9\.\-\s&,/]+)',
            r'#+\s*(.+)',
        ]
        for pat in title_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                candidate = m.group(1).strip()
                if 4 < len(candidate) < 90:
                    data["contract_name"] = candidate
                    break
        if data["contract_name"] == "Unbenannter Vertrag" and data["partner_name"] != "Unbekannter Partner":
            data["contract_name"] = f"Vertrag mit {data['partner_name']}"

        # 3. Kündigungsfrist
        # e.g. "Kündigungsfrist von 3 Monaten", "Frist von 30 Tagen", "3 Monate zum Monatsende"
        notice_patterns = [
            (r'Kündigungsfrist\s*(?:von|beträgt)?\s*(\d+)\s*(Tagen?|Wochen?|Monaten?|Jahren?)', False),
            (r'(\d+)\s*Monate?\s*zum\s*(Monatsende|Quartalsende|Jahresende)', True),
            (r'spätestens\s*(\d+)\s*(Tage|Wochen|Monate)\s*vor\s*(?:Ablauf|Vertragsende|dem)', False),
            (r'notice\s*period\s*of\s*(\d+)\s*(days?|weeks?|months?|years?)', False),
        ]
        for pat, special_end in notice_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                qty = int(m.group(1))
                unit = m.group(2).lower()
                if "tag" in unit or "day" in unit:
                    data["notice_period_days"] = qty
                    data["notice_period_type"] = "days"
                elif "woch" in unit or "week" in unit:
                    data["notice_period_days"] = qty * 7
                    data["notice_period_type"] = "days"
                elif "monat" in unit or "month" in unit:
                    data["notice_period_days"] = qty * 30
                    if "quartal" in unit:
                        data["notice_period_type"] = "end_of_quarter"
                    elif "jahr" in unit:
                        data["notice_period_type"] = "end_of_year"
                    elif "monatsende" in unit:
                        data["notice_period_type"] = "end_of_month"
                    else:
                        data["notice_period_type"] = "months"
                elif "jahr" in unit or "year" in unit:
                    data["notice_period_days"] = qty * 365
                    data["notice_period_type"] = "years"
                break

        # 4. Automatische Verlängerung
        renewal_patterns = [
            r'verlängert\s*sich\s*(?:automatisch)?\s*(?:um\s*(?:weitere\s*)?)?(\d+)\s*(Monate?|Jahre?)',
            r'Verlängerung\s*um\s*(?:weitere\s*)?(\d+)\s*(Monate?|Jahre?)',
            r'auto-?renews?\s*for\s*(?:another\s*)?(\d+)\s*(months?|years?)',
            r'(keine\s*automatische\s*Verlängerung|Vertrag\s*endet\s*automatisch)',
        ]
        for pat in renewal_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                if len(m.groups()) == 1 and "keine" in m.group(1).lower():
                    data["auto_renewal_months"] = 0
                elif len(m.groups()) >= 2:
                    qty = int(m.group(1))
                    unit = m.group(2).lower()
                    if "jahr" in unit or "year" in unit:
                        data["auto_renewal_months"] = qty * 12
                    else:
                        data["auto_renewal_months"] = qty
                break

        # 5. Zahlungsziel
        due_patterns = [
            r'Zahlungsziel\s*[:von]?\s*(\d+)\s*Tagen?',
            r'Zahlbar\s*innerhalb\s*(?:von\s*)?(\d+)\s*Tagen?',
            r'fällig\s*(?:innerhalb\s*(?:von\s*)?)?(\d+)\s*Tagen?',
            r'payment\s*due\s*within\s*(\d+)\s*days?',
            r'netto\s*Kasse\s*innerhalb\s*(\d+)\s*Tagen?',
        ]
        for pat in due_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                data["payment_due_days"] = int(m.group(1))
                break

        # 6. Kosten / Betrag & Abrechnungszyklus
        cost_patterns = [
            r'(\d+[\.,]\d{2})\s*(€|EUR|Euro|USD|\$)',
            r'(€|EUR|USD|\$)\s*(\d+[\.,]\d{2})',
            r'(?:Betrag|Kosten|Vergütung|Preis)\s*[:=]?\s*(\d+[\.,]\d{2})',
        ]
        for pat in cost_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val_str = m.group(1) if re.search(r'\d', m.group(1)) else m.group(2)
                curr_str = m.group(2) if not re.search(r'\d', m.group(2)) else m.group(1)
                cleaned_val = val_str.replace(".", "").replace(",", ".") if "," in val_str else val_str
                try:
                    data["cost_amount"] = float(cleaned_val)
                except ValueError:
                    pass
                if curr_str:
                    curr_upper = curr_str.upper()
                    if "$" in curr_upper or "USD" in curr_upper:
                        data["cost_currency"] = "USD"
                    else:
                        data["cost_currency"] = "EUR"
                break

        # Abrechnungszyklus
        text_lower = text.lower()
        if any(w in text_lower for w in ["jährlich", "pro jahr", "per annum", "yearly", "annual"]):
            data["billing_cycle"] = "jährlich"
        elif any(w in text_lower for w in ["quartalsweise", "pro quartal", "quarterly"]):
            data["billing_cycle"] = "quartalsweise"
        elif any(w in text_lower for w in ["einmalig", "one-off", "einmalzahlung"]):
            data["billing_cycle"] = "einmalig"
        else:
            data["billing_cycle"] = "monatlich"

        # 7. Daten (Beginn & Ende)
        # Suche nach Datumskombinationen
        date_candidates = []
        for pat in cls.DATE_PATTERNS:
            for match in pat.finditer(text):
                parsed = cls.normalize_date(match.group(0))
                if parsed and parsed not in date_candidates:
                    date_candidates.append(parsed)

        date_candidates = sorted(date_candidates)
        if len(date_candidates) >= 2:
            data["start_date"] = date_candidates[0]
            data["end_date"] = date_candidates[-1]
        elif len(date_candidates) == 1:
            data["start_date"] = date_candidates[0]
            # Enddatum schätzen (z. B. +12 Monate)
            try:
                sy, sm, sd = map(int, data["start_date"].split("-"))
                data["end_date"] = f"{sy + 1}-{sm:02d}-{sd:02d}"
            except Exception:
                pass

        # 8. Kategorie
        if any(w in text_lower for w in ["hosting", "server", "domain", "cloud", "aws", "hetzner"]):
            data["category"] = "Hosting"
        elif any(w in text_lower for w in ["miete", "büro", "pacht", "leasing"]):
            data["category"] = "Miete"
        elif any(w in text_lower for w in ["geheimhaltung", "nda", "confidentiality"]):
            data["category"] = "NDA"
        elif any(w in text_lower for w in ["wartung", "support", "sla"]):
            data["category"] = "Wartung"
        elif any(w in text_lower for w in ["versicherung", "haftpflicht"]):
            data["category"] = "Versicherung"
        elif any(w in text_lower for w in ["saas", "software", "api", "lizenz", "abo", "subscription"]):
            data["category"] = "SaaS"

        return data


class ContractManager:
    """Verwaltung, Fristenberechnung und Alarmierung für Verträge."""

    @staticmethod
    def calculate_deadline(end_date_str: str, notice_period_days: int) -> Optional[str]:
        """Berechnet das Datum, an dem die Kündigung spätestens zugegangen sein muss."""
        if not end_date_str:
            return None
        try:
            end_dt = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()
            deadline_dt = end_dt - datetime.timedelta(days=notice_period_days)
            return deadline_dt.strftime("%Y-%m-%d")
        except Exception:
            return None

    @staticmethod
    def get_urgency(days_left: int) -> Tuple[str, str]:
        """Gibt (Badge-Status, CSS-Farbe) zurück."""
        if days_left < 0:
            return ("Abgelaufen", "rose")
        elif days_left <= 14:
            return ("Kritisch", "red")
        elif days_left <= 45:
            return ("Warnung", "amber")
        elif days_left <= 90:
            return ("Bevorstehend", "sky")
        else:
            return ("Sicher", "emerald")

    @classmethod
    def create_or_update(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Erstellt oder aktualisiert einen Vertrag in der SQLite-Datenbank."""
        conn = _get_connection()
        cid = data.get("id") or f"ct-{uuid.uuid4().hex[:8]}"

        name = data.get("contract_name", "Unbenannter Vertrag").strip()
        partner = data.get("partner_name", "Unbekannt").strip()
        category = data.get("category", "SaaS")
        start_date = data.get("start_date")
        end_date = data.get("end_date")
        notice_days = int(data.get("notice_period_days", 30))
        notice_type = data.get("notice_period_type", "days")

        # Nächste Deadline berechnen falls nicht explizit vorgegeben
        deadline = data.get("next_notice_deadline")
        if not deadline and end_date:
            deadline = cls.calculate_deadline(end_date, notice_days)

        renewal = int(data.get("auto_renewal_months", 12))
        payment_due = int(data.get("payment_due_days", 14))
        cost = float(data.get("cost_amount", 0.0))
        curr = data.get("cost_currency", "EUR")
        cycle = data.get("billing_cycle", "monatlich")
        status = data.get("status", "active")
        notes = data.get("notes", "")
        source_file = data.get("source_file", "")
        thresholds = data.get("alert_thresholds_json", "[60, 30, 14, 7, 3, 1]")
        if isinstance(thresholds, list):
            thresholds = json.dumps(thresholds)

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with conn:
            conn.execute("""
                INSERT INTO contracts (
                    id, contract_name, partner_name, category, start_date, end_date,
                    notice_period_days, notice_period_type, next_notice_deadline,
                    auto_renewal_months, payment_due_days, cost_amount, cost_currency,
                    billing_cycle, status, notes, source_file, alert_thresholds_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    contract_name=excluded.contract_name,
                    partner_name=excluded.partner_name,
                    category=excluded.category,
                    start_date=excluded.start_date,
                    end_date=excluded.end_date,
                    notice_period_days=excluded.notice_period_days,
                    notice_period_type=excluded.notice_period_type,
                    next_notice_deadline=excluded.next_notice_deadline,
                    auto_renewal_months=excluded.auto_renewal_months,
                    payment_due_days=excluded.payment_due_days,
                    cost_amount=excluded.cost_amount,
                    cost_currency=excluded.cost_currency,
                    billing_cycle=excluded.billing_cycle,
                    status=excluded.status,
                    notes=excluded.notes,
                    source_file=excluded.source_file,
                    alert_thresholds_json=excluded.alert_thresholds_json,
                    updated_at=excluded.updated_at
            """, (
                cid, name, partner, category, start_date, end_date,
                notice_days, notice_type, deadline, renewal, payment_due,
                cost, curr, cycle, status, notes, source_file, thresholds,
                now, now
            ))
        conn.close()
        return cls.get(cid)

    @classmethod
    def get(cls, contract_id: str) -> Optional[Dict[str, Any]]:
        conn = _get_connection()
        row = conn.execute("SELECT * FROM contracts WHERE id = ?", (contract_id,)).fetchone()
        conn.close()
        if not row:
            return None
        res = dict(row)
        res = cls._enrich_contract(res)
        return res

    @classmethod
    def list_contracts(
        cls,
        category: Optional[str] = None,
        status: Optional[str] = None,
        sort_by: str = "deadline"
    ) -> List[Dict[str, Any]]:
        conn = _get_connection()
        query = "SELECT * FROM contracts WHERE 1=1"
        params: List[Any] = []

        if category and category.lower() != "alle":
            query += " AND category = ?"
            params.append(category)

        if status and status.lower() != "alle":
            query += " AND status = ?"
            params.append(status)

        if sort_by == "deadline":
            query += " ORDER BY CASE WHEN next_notice_deadline IS NULL THEN 1 ELSE 0 END, next_notice_deadline ASC"
        elif sort_by == "cost":
            query += " ORDER BY cost_amount DESC"
        elif sort_by == "name":
            query += " ORDER BY contract_name ASC"
        else:
            query += " ORDER BY updated_at DESC"

        rows = conn.execute(query, tuple(params)).fetchall()
        conn.close()

        result = []
        for r in rows:
            enriched = cls._enrich_contract(dict(r))
            result.append(enriched)
        return result

    @classmethod
    def delete(cls, contract_id: str) -> bool:
        conn = _get_connection()
        with conn:
            cur = conn.execute("DELETE FROM contracts WHERE id = ?", (contract_id,))
            deleted = cur.rowcount > 0
        conn.close()
        return deleted

    @classmethod
    def _enrich_contract(cls, c: Dict[str, Any]) -> Dict[str, Any]:
        """Berechnet Resttage, Dringlichkeits-Badge und Formatierungen."""
        deadline_str = c.get("next_notice_deadline")
        today = datetime.date.today()
        days_left = None

        if deadline_str:
            try:
                deadline_dt = datetime.datetime.strptime(deadline_str, "%Y-%m-%d").date()
                days_left = (deadline_dt - today).days
            except Exception:
                pass

        c["days_left"] = days_left
        if days_left is not None:
            badge, color = cls.get_urgency(days_left)
            c["urgency_badge"] = badge
            c["urgency_color"] = color
        else:
            c["urgency_badge"] = "Ohne Frist"
            c["urgency_color"] = "gray"

        # Monatliche äquivalente Kosten für einfache Hochrechnung
        cost = c.get("cost_amount") or 0.0
        cycle = c.get("billing_cycle", "monatlich")
        if cycle == "jährlich":
            c["monthly_equivalent_cost"] = round(cost / 12.0, 2)
        elif cycle == "quartalsweise":
            c["monthly_equivalent_cost"] = round(cost / 3.0, 2)
        elif cycle == "einmalig":
            c["monthly_equivalent_cost"] = 0.0
        else:
            c["monthly_equivalent_cost"] = round(cost, 2)

        return c

    @classmethod
    def renew_contract(cls, contract_id: str) -> Optional[Dict[str, Any]]:
        """Verlängert einen Vertrag um die konfigurierten auto_renewal_months."""
        c = cls.get(contract_id)
        if not c or not c.get("end_date"):
            return None

        renewal_months = c.get("auto_renewal_months") or 12
        if renewal_months <= 0:
            return c

        end_dt = datetime.datetime.strptime(c["end_date"], "%Y-%m-%d").date()
        # Nächstes Enddatum berechnen
        new_year = end_dt.year + (end_dt.month + renewal_months - 1) // 12
        new_month = (end_dt.month + renewal_months - 1) % 12 + 1
        new_day = min(end_dt.day, 28)
        new_end_dt = datetime.date(new_year, new_month, new_day)

        new_end_str = new_end_dt.strftime("%Y-%m-%d")
        notice_days = c.get("notice_period_days", 30)
        new_deadline = cls.calculate_deadline(new_end_str, notice_days)

        c["end_date"] = new_end_str
        c["next_notice_deadline"] = new_deadline
        c["status"] = "renewed"

        return cls.create_or_update(c)

    @classmethod
    def scan_and_alert_deadlines(
        cls,
        send_telegram: bool = True,
        create_kanban_task: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Prüft alle aktiven Verträge auf bevorstehende Kündigungsstichtage.
        Verschickt Warnungen via Telegram und erstellt bei akuter Dringlichkeit (<= 14 Tage)
        einen Task im Kanban-Board.
        """
        contracts = cls.list_contracts(status="active")
        alerts_triggered = []
        today_str = datetime.date.today().strftime("%Y-%m-%d")

        for c in contracts:
            days_left = c.get("days_left")
            if days_left is None:
                continue

            # Schwellenwerte aus JSON laden
            thresholds = [60, 30, 14, 7, 3, 1]
            try:
                if c.get("alert_thresholds_json"):
                    thresholds = json.loads(c["alert_thresholds_json"])
            except Exception:
                pass

            # Prüfe ob days_left genau einem Schwellenwert entspricht oder kritisch ist
            should_alert = False
            for t in thresholds:
                if days_left == t:
                    should_alert = True
                    break

            # Auch bei Überfälligkeit oder akuter Frist warnen, wenn heute noch kein Alert rausging
            last_alert = c.get("last_alert_sent") or ""
            if (days_left <= 14 or should_alert) and not last_alert.startswith(today_str):
                should_alert = True

            if should_alert:
                cname = c["contract_name"]
                partner = c["partner_name"]
                deadline = c["next_notice_deadline"]
                cost = c["cost_amount"]
                curr = c["cost_currency"]
                cycle = c["billing_cycle"]

                urgency_title = "⚠️ FRISTEN-WARNUNG" if days_left > 7 else "🚨 AKUTE KÜNDIGUNGSFRIST"
                if days_left < 0:
                    urgency_title = "⛔ KÜNDIGUNGSFRIST VERSTRICHEN"
                    msg = f"{urgency_title}: Die Frist für '{cname}' ({partner}) ist seit {abs(days_left)} Tagen abgelaufen! Stichtag war der {deadline}."
                else:
                    msg = (
                        f"{urgency_title}: Der Vertrag '{cname}' mit '{partner}' muss bis spätestens "
                        f"{deadline} gekündigt werden! Noch {days_left} Tag(e) verbleibend. "
                        f"Kosten: {cost:.2f} {curr}/{cycle}."
                    )

                # In DB protokollieren
                conn = _get_connection()
                with conn:
                    conn.execute("""
                        INSERT INTO contract_alerts (contract_id, alert_type, days_remaining, message, dispatched_via)
                        VALUES (?, ?, ?, ?, ?)
                    """, (c["id"], "deadline_alert", days_left, msg, "telegram" if send_telegram else "system"))
                    conn.execute("UPDATE contracts SET last_alert_sent = ? WHERE id = ?", (today_str, c["id"]))
                conn.close()

                # 1. Telegram-Benachrichtigung
                if send_telegram:
                    cls._dispatch_telegram(msg)

                # 2. Kanban Task erstellen bei akuter Frist (<= 14 Tage)
                if create_kanban_task and 0 <= days_left <= 14:
                    cls._create_kanban_task(c, days_left, msg)

                alerts_triggered.append({
                    "contract_id": c["id"],
                    "contract_name": cname,
                    "partner_name": partner,
                    "deadline": deadline,
                    "days_left": days_left,
                    "message": msg
                })

        return alerts_triggered

    @classmethod
    def _dispatch_telegram(cls, message: str):
        """Sendet Fristenwarnung an den Telegram-Adminchat."""
        try:
            from scripts.patches.hermes_telegram_adapter import send_admin_notification
            send_admin_notification(message)
            return
        except Exception:
            pass

        # Fallback: Direkt über requests / urllib falls Bot-Token vorhanden
        try:
            token = os.getenv("TELEGRAM_BOT_TOKEN")
            chat_id = os.getenv("TELEGRAM_ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
            if token and chat_id:
                import urllib.request
                import urllib.parse
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                data = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode()
                req = urllib.request.Request(url, data=data, method="POST")
                urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            print(f"[ContractManager] Telegram dispatch failed: {e}", file=sys.stderr)

    @classmethod
    def _create_kanban_task(cls, contract: Dict[str, Any], days_left: int, alert_msg: str):
        """Erstellt bei akuten Fristen automatisch einen Task im Kanban-Board."""
        cname = contract["contract_name"]
        partner = contract["partner_name"]
        deadline = contract["next_notice_deadline"]

        task_title = f"Kündigungsfrist prüfen: {cname} ({partner})"
        task_desc = (
            f"Fristenmanagement-Alarm:\n"
            f"Der Vertrag '{cname}' hat noch {days_left} Tage bis zum Kündigungsstichtag ({deadline}).\n"
            f"Kosten: {contract.get('cost_amount', 0.0):.2f} {contract.get('cost_currency', 'EUR')}\n\n"
            f"Handlungsoptionen:\n"
            f"- Kündigung vorbereiten und versenden\n"
            f"- Verlängerungskonditionen prüfen\n"
            f"- Im System auf 'terminating' oder 'renewed' setzen."
        )

        # Prüfe ob Task bereits existiert
        kanban_paths = [
            os.path.join(WORKSPACE_DIR, "data", "kanban.db"),
            os.path.expanduser("~/.hermes/kanban.db")
        ]
        for kpath in kanban_paths:
            if os.path.exists(kpath):
                try:
                    conn = sqlite3.connect(kpath, timeout=5.0)
                    with conn:
                        existing = conn.execute(
                            "SELECT id FROM tasks WHERE title = ? AND status != 'done'",
                            (task_title,)
                        ).fetchone()
                        if not existing:
                            tid = f"task-frist-{uuid.uuid4().hex[:6]}"
                            conn.execute("""
                                INSERT INTO tasks (id, title, description, priority, status, created_at, updated_at)
                                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                            """, (tid, task_title, task_desc, "high", "todo"))
                            print(f"[ContractManager] Kanban-Task '{tid}' für Frist erstellt.")
                    conn.close()
                    break
                except Exception as e:
                    print(f"[ContractManager] Kanban Task-Erstellung fehlgeschlagen: {e}", file=sys.stderr)

    @classmethod
    def get_stats(cls) -> Dict[str, Any]:
        """Liefert Gesamtzahlen, monatliche Fixkosten und Fristenstatus."""
        contracts = cls.list_contracts()
        total_count = len(contracts)
        active_count = 0
        monthly_total_cost = 0.0
        critical_deadlines = 0
        warning_deadlines = 0
        expired_count = 0

        for c in contracts:
            if c.get("status") == "active":
                active_count += 1
                monthly_total_cost += c.get("monthly_equivalent_cost", 0.0)

            days = c.get("days_left")
            if days is not None:
                if days < 0:
                    expired_count += 1
                elif days <= 14:
                    critical_deadlines += 1
                elif days <= 45:
                    warning_deadlines += 1

        # Nächste 5 Fristen
        upcoming = [c for c in contracts if c.get("days_left") is not None and c["days_left"] >= 0]
        upcoming = sorted(upcoming, key=lambda x: x["days_left"])[:5]

        return {
            "total_contracts": total_count,
            "active_contracts": active_count,
            "monthly_fixcosts": round(monthly_total_cost, 2),
            "critical_deadlines": critical_deadlines,
            "warning_deadlines": warning_deadlines,
            "expired_contracts": expired_count,
            "upcoming_deadlines": upcoming
        }
