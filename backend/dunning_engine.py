"""
backend/dunning_engine.py
Archon OS Dunning & Accounts Receivable Engine (Mahnwesen).
Tracks outstanding invoices, determines overdue status, generates legally sound 3-tier dunning drafts,
and enforces Human-in-the-Loop approval before dispatch.
"""

import os
import sys
import time
import uuid
import json
import sqlite3

class _ArchonClosingConn(sqlite3.Connection):
    def __enter__(self):
        super().__enter__()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()
import datetime
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.getenv("DATA_DIR", "/opt/data" if os.path.exists("/opt/data") else os.path.join(os.path.expanduser("~"), ".hermes"))


def _resolve_db(name: str) -> str:
    """Delegiert an die zentrale, validierende Auflösung (backend/db_paths.py)."""
    from backend.db_paths import resolve_db
    return resolve_db(name)


# Basiszinssatz-Tabelle nach § 247 BGB (Deutsche Bundesbank, halbjährliche Anpassung 01.01. / 01.07.)
# Quelle: Bundesbank Bekanntmachung Basiszinssatz
_BGB_BASE_RATE_PERIODS = [
    (datetime.date(2023, 1, 1), 0.0162),
    (datetime.date(2023, 7, 1), 0.0312),
    (datetime.date(2024, 1, 1), 0.0362),
    (datetime.date(2024, 7, 1), 0.0337),
    (datetime.date(2025, 1, 1), 0.0227),
    (datetime.date(2025, 7, 1), 0.0127),
    (datetime.date(2026, 1, 1), 0.0127),
    (datetime.date(2026, 7, 1), 0.0152),
]


def _get_bgb_base_rate(day: datetime.date) -> float:
    """Ermittelt den gültigen § 247 BGB Basiszinssatz für ein Datum (mit optionalem Env-Override)."""
    env_override = os.environ.get("ARCHON_BGB_BASE_RATE")
    if env_override:
        try:
            return float(env_override)
        except ValueError:
            pass
    rate = _BGB_BASE_RATE_PERIODS[0][1]
    for start_dt, period_rate in _BGB_BASE_RATE_PERIODS:
        if day >= start_dt:
            rate = period_rate
    return rate


def calculate_statutory_interest(
    principal_eur: float,
    due_date: datetime.date,
    as_of_date: datetime.date,
    is_b2b: bool = True,
) -> float:
    """Berechnet gesetzliche Verzugszinsen (§ 288 BGB) taggenau über Halbjahresgrenzen hinweg."""
    if principal_eur <= 0 or as_of_date <= due_date:
        return 0.0
    margin = 0.09 if is_b2b else 0.05  # § 288 Abs. 2 (+9 Pp. B2B) / Abs. 1 (+5 Pp. B2C)
    cur = due_date
    total_interest = 0.0
    boundaries = [d for d, _ in _BGB_BASE_RATE_PERIODS if due_date < d < as_of_date]
    for next_bound in boundaries + [as_of_date]:
        days_in_slice = (next_bound - cur).days
        if days_in_slice > 0:
            annual_rate = _get_bgb_base_rate(cur) + margin
            year_days = 366.0 if (cur.year % 4 == 0 and (cur.year % 100 != 0 or cur.year % 400 == 0)) else 365.0
            total_interest += principal_eur * annual_rate * (days_in_slice / year_days)
        cur = next_bound
    return round(total_interest, 2)


class DunningEngine:
    """Verwaltet Ausgangsrechnungen und das dreistufige Mahnwesen."""

    def __init__(self):
        self.memory_db = _resolve_db("agentic_memory.db")
        self.kanban_db = _resolve_db("kanban.db")
        self._init_tables()

    @staticmethod
    def _resolve_cid(company_id: Optional[str] = None) -> str:
        try:
            from backend.tenant_context import get_active_company_id, sanitize_tenant_id
            return sanitize_tenant_id(company_id or get_active_company_id() or "default")
        except Exception:
            return (company_id or "default").strip() or "default"

    def _init_tables(self):
        """Erstellt die Tabellen für Rechnungen und Mahnhistorie."""
        if os.path.exists(self.memory_db):
            try:
                with sqlite3.connect(self.memory_db, timeout=5.0, factory=_ArchonClosingConn) as conn:
                    conn.execute("PRAGMA journal_mode=WAL;")
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS invoices (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            invoice_id TEXT UNIQUE NOT NULL,
                            company_id TEXT DEFAULT 'default',
                            customer_name TEXT NOT NULL,
                            customer_email TEXT NOT NULL,
                            recipient_address TEXT,
                            invoice_date TEXT NOT NULL,
                            due_date TEXT NOT NULL,
                            amount_net REAL NOT NULL,
                            tax_amount REAL NOT NULL,
                            amount_gross REAL NOT NULL,
                            currency TEXT DEFAULT 'EUR',
                            status TEXT DEFAULT 'open',
                            is_b2b INTEGER DEFAULT 1,
                            last_reminder_date TEXT,
                            dunning_level INTEGER DEFAULT 0,
                            dunning_fee REAL DEFAULT 0.0,
                            kanban_task_id TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    for col_ddl in (
                        "ALTER TABLE invoices ADD COLUMN is_b2b INTEGER DEFAULT 1",
                        "ALTER TABLE invoices ADD COLUMN company_id TEXT DEFAULT 'default'",
                    ):
                        try:
                            conn.execute(col_ddl)
                        except sqlite3.OperationalError:
                            pass
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS dunning_history (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            dunning_id TEXT UNIQUE NOT NULL,
                            invoice_id TEXT NOT NULL,
                            company_id TEXT DEFAULT 'default',
                            level INTEGER NOT NULL,
                            issued_date TEXT NOT NULL,
                            deadline_date TEXT NOT NULL,
                            fee REAL DEFAULT 0.0,
                            interest REAL DEFAULT 0.0,
                            total_claim REAL NOT NULL,
                            status TEXT DEFAULT 'draft',
                            draft_text TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    try:
                        conn.execute("ALTER TABLE dunning_history ADD COLUMN company_id TEXT DEFAULT 'default'")
                    except sqlite3.OperationalError:
                        pass
                    conn.commit()
            except Exception as e:
                print(f"[DunningEngine] Init Warning: {e}", file=sys.stderr)

    def create_invoice(
        self,
        customer_name: str,
        customer_email: str,
        amount_net: float,
        tax_rate_pct: float = 19.0,
        due_days: int = 14,
        invoice_date: Optional[str] = None,
        recipient_address: Optional[str] = None,
        is_b2b: bool = True,
        company_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Legt eine neue Ausgangsrechnung an."""
        cid = self._resolve_cid(company_id)
        inv_date = invoice_date or datetime.date.today().isoformat()
        dt_inv = datetime.date.fromisoformat(inv_date)
        due_date = (dt_inv + datetime.timedelta(days=due_days)).isoformat()

        tax_amount = round(amount_net * (tax_rate_pct / 100.0), 2)
        amount_gross = round(amount_net + tax_amount, 2)
        year = datetime.date.today().year

        inserted = False
        last_error = None
        invoice_id = ""

        if os.path.exists(self.memory_db):
            with sqlite3.connect(self.memory_db, timeout=10.0, factory=_ArchonClosingConn) as conn:
                for attempt in range(5):
                    # Kollisionsfreie Rechnungsnummer (R-04): Zeit + Zufallssuffix
                    suffix = f"{int(time.time() * 1000) % 1000000:06d}-{uuid.uuid4().hex[:4].upper()}"
                    invoice_id = f"RE-{year}-{suffix}"
                    try:
                        conn.execute("""
                            INSERT INTO invoices (
                                invoice_id, company_id, customer_name, customer_email, recipient_address,
                                invoice_date, due_date, amount_net, tax_amount, amount_gross,
                                currency, status, is_b2b, dunning_level, dunning_fee
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'EUR', 'open', ?, 0, 0.0)
                        """, (
                            invoice_id, cid, customer_name, customer_email, recipient_address or "",
                            inv_date, due_date, amount_net, tax_amount, amount_gross, 1 if is_b2b else 0
                        ))
                        conn.commit()
                        inserted = True
                        break
                    except sqlite3.IntegrityError as ie:
                        last_error = ie
                        time.sleep(0.01)
                    except Exception as e:
                        last_error = e
                        break

            if not inserted:
                raise RuntimeError(f"Rechnung konnte nicht angelegt werden: {last_error}")
        else:
            invoice_id = f"RE-{year}-{int(time.time() * 1000) % 1000000:06d}-{uuid.uuid4().hex[:4].upper()}"

        return {
            "invoice_id": invoice_id,
            "company_id": cid,
            "customer_name": customer_name,
            "customer_email": customer_email,
            "invoice_date": inv_date,
            "due_date": due_date,
            "amount_gross": amount_gross,
            "is_b2b": bool(is_b2b),
            "status": "open"
        }

    def check_overdue_invoices(self, company_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Prüft alle Rechnungen eines Mandanten auf Fälligkeit und ermittelt Handlungsbedarf."""
        if not os.path.exists(self.memory_db):
            return []

        cid = self._resolve_cid(company_id) if company_id is not None else None
        today = datetime.date.today()
        candidates = []

        try:
            with sqlite3.connect(f"file:{self.memory_db}?mode=ro", uri=True, timeout=5.0, factory=_ArchonClosingConn) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                if cid:
                    cur.execute("""
                        SELECT * FROM invoices
                        WHERE status NOT IN ('paid', 'written_off') AND COALESCE(company_id, 'default') = ?
                        ORDER BY due_date ASC
                    """, (cid,))
                else:
                    cur.execute("""
                        SELECT * FROM invoices
                        WHERE status NOT IN ('paid', 'written_off')
                        ORDER BY due_date ASC
                    """)
                rows = cur.fetchall()

            for r in rows:
                inv = dict(r)
                due_dt = datetime.date.fromisoformat(inv["due_date"])
                overdue_days = (today - due_dt).days

                inv["overdue_days"] = max(0, overdue_days)
                inv["is_overdue"] = overdue_days > 0

                # Ermittle empfohlene Mahnstufe
                recommended_level = 0
                if overdue_days > 30:
                    recommended_level = 3
                elif overdue_days > 15:
                    recommended_level = 2
                elif overdue_days > 5:
                    recommended_level = 1

                inv["recommended_level"] = recommended_level
                candidates.append(inv)

        except Exception as e:
            print(f"[DunningEngine] Error checking overdue invoices: {e}", file=sys.stderr)

        return candidates

    def generate_dunning_draft(self, invoice_id: str, level: int, include_b2b_pauschale: bool = False) -> Dict[str, Any]:
        """Generiert einen rechtssicheren 3-Stufen Mahnentwurf zur Freigabe (HITL)."""
        if not os.path.exists(self.memory_db):
            raise ValueError("Datenbank nicht erreichbar.")

        with sqlite3.connect(f"file:{self.memory_db}?mode=ro", uri=True, timeout=5.0, factory=_ArchonClosingConn) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,))
            inv = cur.fetchone()
            if not inv:
                raise ValueError(f"Rechnung {invoice_id} nicht gefunden.")
            inv = dict(inv)
            prior_rows = cur.execute(
                "SELECT level, fee, status FROM dunning_history WHERE invoice_id = ? AND level < ? ORDER BY level ASC",
                (invoice_id, int(level)),
            ).fetchall()

        today = datetime.date.today()
        dunning_id = f"MAHN-{invoice_id}-{level}"

        # Konfiguration je Stufe inkl. §§ 286, 288 BGB Konformität
        due_dt = datetime.date.fromisoformat(inv["due_date"]) if inv.get("due_date") else today
        overdue_days = max(0, (today - due_dt).days)
        is_b2b = True if inv.get("is_b2b") is None else bool(int(inv["is_b2b"]))
        statutory_interest = calculate_statutory_interest(
            float(inv["amount_gross"]), due_dt, today, is_b2b=is_b2b
        )
        prior_pauschale_charged = (
            float(inv.get("dunning_fee") or 0.0) >= 40.0
            or any(float(r["fee"] or 0.0) >= 40.0 for r in prior_rows)
        )
        prior_non_pauschale_fees = sum(
            float(r["fee"] or 0.0)
            for r in prior_rows
            if str(r["status"] or "") == "sent" and float(r["fee"] or 0.0) < 40.0
        )

        if level == 1:
            fee = 0.0  # § 286 BGB: Zahlungserinnerung gebührenfrei (kein Verzug vor Fälligkeit/Mahnung)
            interest = 0.0
            cumulative_fee = 0.0
            deadline_days = 7
            deadline = (today + datetime.timedelta(days=deadline_days)).isoformat()
            subject = f"Freundliche Zahlungserinnerung zur Rechnung {invoice_id}"
            body_text = (
                f"Sehr geehrte Damen und Herren,\n\n"
                f"sicherlich ist es Ihrer Aufmerksamkeit im Alltagsgeschäft entgangen: "
                f"Für unsere Rechnung {invoice_id} vom {inv['invoice_date']} über {inv['amount_gross']:.2f} EUR "
                f"konnten wir bisher keinen Zahlungseingang verzeichnen.\n\n"
                f"Wir bitten Sie höflich, den fälligen Betrag von {inv['amount_gross']:.2f} EUR bis zum {deadline} "
                f"auf unser Geschäftskonto zu überweisen.\n\n"
                f"Sollten Sie den Betrag in den letzten Tagen bereits beglichen haben, betrachten Sie dieses Schreiben bitte als gegenstandslos.\n\n"
                f"Mit freundlichen Grüßen,\nBuchhaltung Archon OS"
            )
        elif level == 2:
            if not is_b2b:
                # § 288 Abs. 5 BGB gilt NICHT gegenüber Verbrauchern (is_b2b == 0)
                fee = 5.0
                fee_label = "Mahnkostenpauschale"
            elif include_b2b_pauschale and not prior_pauschale_charged:
                fee = 40.0
                fee_label = "Verzugskostenpauschale (§ 288 Abs. 5 BGB)"
            elif prior_pauschale_charged:
                fee = 0.0
                fee_label = "Verzugskostenpauschale (§ 288 Abs. 5 BGB, bereits berechnet)"
            else:
                fee = 5.0
                fee_label = "Mahnkostenpauschale"
            interest = statutory_interest if overdue_days > 0 else 0.0
            cumulative_fee = 40.0 if (is_b2b and (prior_pauschale_charged or fee >= 40.0)) else fee
            deadline_days = 5
            deadline = (today + datetime.timedelta(days=deadline_days)).isoformat()
            total_claim = round(inv["amount_gross"] + cumulative_fee + interest, 2)
            subject = f"1. Mahnung zur Rechnung {invoice_id}"
            body_text = (
                f"Sehr geehrte Damen und Herren,\n\n"
                f"trotz unserer vorherigen Zahlungserinnerung konnten wir für die Rechnung {invoice_id} vom {inv['invoice_date']} "
                f"leider noch immer keinen Zahlungseingang feststellen. Die Forderung ist seit dem {inv['due_date']} ({overdue_days} Tage) fällig.\n\n"
                f"Forderungsaufstellung:\n"
                f"- Rechnungsbetrag: {inv['amount_gross']:.2f} EUR\n"
                f"- {fee_label}: {cumulative_fee:.2f} EUR\n"
                f"- Verzugszinsen (§ 288 BGB, {overdue_days} Tage): {interest:.2f} EUR\n"
                f"- GESAMTFORDERUNG: {total_claim:.2f} EUR\n\n"
                f"Wir fordern Sie hiermit auf, den Gesamtbetrag von {total_claim:.2f} EUR bis spätestens {deadline} "
                f"auf unser unten genanntes Konto auszugleichen.\n\n"
                f"Mit freundlichen Grüßen,\nBuchhaltung Archon OS"
            )
        else:  # level >= 3
            if not is_b2b:
                # Keine 40-EUR-Verzugspauschale bei Verbrauchern (§ 288 Abs. 5 BGB)
                fee = 10.0
                cumulative_fee = round(prior_non_pauschale_fees + fee, 2)
                fee_label = "Mahnkosten"
            elif prior_pauschale_charged:
                # § 288 Abs. 5 BGB: Maximal EINMAL 40 EUR je überfälliger Forderung
                fee = 0.0
                cumulative_fee = 40.0
                fee_label = "Verzugskostenpauschale (§ 288 Abs. 5 BGB, einmalig)"
            elif include_b2b_pauschale:
                fee = 40.0
                cumulative_fee = 40.0
                fee_label = "Verzugskostenpauschale (§ 288 Abs. 5 BGB, einmalig)"
            else:
                fee = 10.0
                cumulative_fee = round(prior_non_pauschale_fees + fee, 2)
                fee_label = "Mahnkosten"
            interest = statutory_interest if overdue_days > 0 else 0.0
            deadline_days = 3
            deadline = (today + datetime.timedelta(days=deadline_days)).isoformat()
            total_claim = round(inv["amount_gross"] + cumulative_fee + interest, 2)
            subject = f"LETZTE MAHNUNG vor Einleitung gerichtlicher Schritte (Rechnung {invoice_id})"
            body_text = (
                f"Sehr geehrte Damen und Herren,\n\n"
                f"auf unsere bisherigen Mahnungen zur Rechnung {invoice_id} vom {inv['invoice_date']} erfolgte bisher keine Zahlung.\n\n"
                f"Forderungsaufstellung:\n"
                f"- Hauptforderung: {inv['amount_gross']:.2f} EUR\n"
                f"- {fee_label}: {cumulative_fee:.2f} EUR\n"
                f"- Verzugszinsen (§ 288 BGB, {overdue_days} Tage): {interest:.2f} EUR\n"
                f"- GESAMTBETRAG: {total_claim:.2f} EUR\n\n"
                f"Dies ist die LETZTE außergerichtliche Frist. Bitte überweisen Sie den Betrag von {total_claim:.2f} EUR "
                f"bis zum {deadline}.\n\n"
                f"Sollte kein fristgerechter Eingang erfolgen, werden wir ohne weitere Ankündigung das gerichtliche Mahnverfahren "
                f"beantragen bzw. die Forderung an ein Inkassounternehmen übergeben. Die hierdurch entstehenden erheblichen Mehrkosten "
                f"gehen zu Ihren Lasten.\n\n"
                f"Mit freundlichen Grüßen,\nGeschäftsleitung / Rechtsabteilung Archon OS"
            )

        total_claim = round(inv["amount_gross"] + cumulative_fee + interest, 2)

        # Speichere Entwurf in DB
        with sqlite3.connect(self.memory_db, timeout=5.0, factory=_ArchonClosingConn) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO dunning_history (
                    dunning_id, invoice_id, level, issued_date, deadline_date,
                    fee, interest, total_claim, status, draft_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?)
            """, (
                dunning_id, invoice_id, level, today.isoformat(), deadline,
                fee, interest, total_claim, body_text
            ))
            conn.commit()

        # Erstelle / Aktualisiere Kanban-Task zur manuellen Freigabe
        if os.path.exists(self.kanban_db):
            try:
                task_id = f"task-dunning-{dunning_id}"
                t_title = f"[Mahnung Stufe {level}] {inv['customer_name']}: {total_claim:.2f} EUR"
                t_body = (
                    f"Mahnentwurf zur Freigabe vor Mailversand.\n\n"
                    f"- Kunde: {inv['customer_name']} <{inv['customer_email']}>\n"
                    f"- Rechnungsnummer: {invoice_id}\n"
                    f"- Gesamtforderung: {total_claim:.2f} EUR\n"
                    f"- Zahlungsfrist: {deadline}\n\n"
                    f"Entwurfstext:\n{body_text}"
                )
                with sqlite3.connect(self.kanban_db, timeout=5.0, factory=_ArchonClosingConn) as conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO tasks (
                            id, title, body, assignee, status, priority, created_by, created_at
                        ) VALUES (?, ?, ?, 'finance_lead', 'ready', 1, 'dunning_engine', ?)
                    """, (task_id, t_title, t_body, datetime.datetime.now().isoformat()))
                    conn.commit()
            except Exception as e:
                print(f"[DunningEngine] Error updating Kanban: {e}", file=sys.stderr)

        return {
            "dunning_id": dunning_id,
            "invoice_id": invoice_id,
            "level": level,
            "subject": subject,
            "deadline": deadline,
            "total_claim": total_claim,
            "fee": fee,
            "interest": interest,
            "status": "draft",
            "body_text": body_text
        }

    def approve_and_send_dunning(self, dunning_id: str) -> Dict[str, Any]:
        """Gibt einen Mahnentwurf frei und aktualisiert den Status der Rechnung (HITL Freigabe)."""
        if not os.path.exists(self.memory_db):
            raise ValueError("Datenbank nicht erreichbar.")

        with sqlite3.connect(self.memory_db, timeout=5.0, factory=_ArchonClosingConn) as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM dunning_history WHERE dunning_id = ?", (dunning_id,))
            d_row = cur.fetchone()
            if not d_row:
                raise ValueError(f"Mahnentwurf {dunning_id} nicht gefunden.")
            
            d_dict = dict(zip([c[0] for c in cur.description], d_row))
            inv_id = d_dict["invoice_id"]
            lvl = d_dict["level"]
            now_iso = datetime.datetime.now().isoformat()

            # R-22: Status- und Stufenpruefung VOR dem Versand.
            # (a) Eine bezahlte/abgeschriebene Rechnung darf nie gemahnt werden.
            inv_stat = conn.execute(
                "SELECT status, dunning_level, COALESCE(dunning_fee, 0.0) FROM invoices WHERE invoice_id = ?", (inv_id,)
            ).fetchone()
            if not inv_stat:
                raise ValueError(f"Rechnung {inv_id} nicht gefunden.")
            inv_status, inv_level, inv_prev_fee = inv_stat[0], inv_stat[1], float(inv_stat[2] or 0.0)
            if inv_status in ("paid", "written_off"):
                raise ValueError(f"Rechnung {inv_id} ist {inv_status} — keine Mahnung zulaessig.")
            # (b) Stufe N setzt Stufe N-1 voraus (kein Stufe-3-Versand ohne 1/2).
            if lvl >= 2 and inv_level != lvl - 1:
                raise ValueError(
                    f"Mahnstufe {lvl} fuer Rechnung {inv_id} erfordert zuerst Stufe {lvl - 1} "
                    f"(aktueller Rechnungsstand: Stufe {inv_level})."
                )
            # (c) Ein bereits versandter Entwurf wird nicht erneut versendet.
            if d_dict["status"] == "sent":
                raise ValueError(f"Mahnentwurf {dunning_id} wurde bereits versendet.")

            # 1. Mahnung auf sent setzen
            conn.execute("""
                UPDATE dunning_history
                SET status = 'sent'
                WHERE dunning_id = ?
            """, (dunning_id,))

            # 2. Rechnung aktualisieren (BGB § 288 Abs. 5: Pauschale max. 40 EUR einmalig)
            status_map = {1: "dunning_1", 2: "dunning_2", 3: "dunning_3"}
            new_status = status_map.get(lvl, "dunning_1")
            new_fee = float(d_dict["fee"] or 0.0)
            if inv_prev_fee >= 40.0 or new_fee >= 40.0:
                updated_total_fee = max(inv_prev_fee, new_fee)
            else:
                updated_total_fee = round(inv_prev_fee + new_fee, 2)
            conn.execute("""
                UPDATE invoices
                SET status = ?, dunning_level = ?, dunning_fee = ?, last_reminder_date = ?
                WHERE invoice_id = ?
            """, (new_status, lvl, updated_total_fee, now_iso, inv_id))
            conn.commit()

        # 3. E-Mail-Versand via SMTP (backend/email_service.py) + Audit-Entwurf in email_draft_engine
        email_draft_id = None
        smtp_result: Dict[str, Any] = {"status": "skipped"}
        try:
            with sqlite3.connect(self.memory_db, timeout=5.0, factory=_ArchonClosingConn) as conn:
                row_cust = conn.execute(
                    "SELECT customer_name, customer_email FROM invoices WHERE invoice_id = ?", (inv_id,)
                ).fetchone()
            if row_cust and row_cust[1]:
                mail_subj = f"Mahnung Stufe {lvl} zu Rechnung {inv_id}"
                mail_body = d_dict.get("draft_text") or (
                    f"Sehr geehrte Damen und Herren,\n\nMahnung Stufe {lvl} zu Rechnung {inv_id} "
                    f"über {d_dict['total_claim']:.2f} EUR."
                )
                from backend.email_draft_engine import email_draft_engine
                draft_res = email_draft_engine.create_draft(
                    subject=mail_subj,
                    recipient=row_cust[1],
                    body_text=mail_body,
                    agent_id="finance_lead",
                    agent_name="Finance Lead",
                )
                email_draft_id = draft_res.get("draft_id") if isinstance(draft_res, dict) else None
                try:
                    from backend.email_service import send_email
                    smtp_result = send_email(
                        to_email=row_cust[1],
                        subject=mail_subj,
                        body_text=mail_body,
                    )
                    if smtp_result.get("status") == "sent" and email_draft_id:
                        email_draft_engine.approve_and_send(email_draft_id, approver_id="dunning_engine")
                except Exception as smtp_exc:
                    smtp_result = {"status": "error", "message": str(smtp_exc)}
        except Exception:
            pass

        # 4. ERP-Synchronisierung (Beleg-Mahnstatus im aktiven Mandanten nachführen, falls vorhanden)
        try:
            from backend.erp_manager import get_erp_manager
            erp_mgr = get_erp_manager()
            e_conn, _ = erp_mgr._get_conn()
            try:
                e_conn.execute(
                    "UPDATE erp_documents SET updated_at = CURRENT_TIMESTAMP WHERE doc_number = ?",
                    (inv_id,),
                )
                e_conn.commit()
            finally:
                e_conn.close()
        except Exception:
            pass

        # 5. NotificationHub alarmieren
        try:
            from backend.notification_hub import get_notification_hub
            get_notification_hub().dispatch_notification(
                title=f"Mahnung Stufe {lvl} versandt",
                message=f"Mahnung '{dunning_id}' für Rechnung {inv_id} über {d_dict['total_claim']:.2f} EUR wurde freigegeben (SMTP: {smtp_result.get('status')}).",
                severity="WARNING" if lvl >= 2 else "INFO",
                category="finance_dunning"
            )
        except Exception:
            pass

        return {
            "status": "success",
            "dunning_id": dunning_id,
            "invoice_id": inv_id,
            "level": lvl,
            "new_invoice_status": new_status,
            "email_draft_id": email_draft_id,
            "smtp_status": smtp_result.get("status"),
            "smtp_result": smtp_result,
            "dispatched_at": now_iso
        }

    def mark_invoice_paid(self, invoice_id: str) -> bool:
        """Markiert eine Rechnung als vollständig beglichen."""
        if not os.path.exists(self.memory_db):
            return False
        try:
            with sqlite3.connect(self.memory_db, timeout=5.0, factory=_ArchonClosingConn) as conn:
                conn.execute("UPDATE invoices SET status = 'paid' WHERE invoice_id = ?", (invoice_id,))
                conn.commit()
            return True
        except Exception as e:
            print(f"[DunningEngine] Error marking invoice paid: {e}", file=sys.stderr)
            return False


dunning_engine = DunningEngine()
