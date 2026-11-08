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
import datetime
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.getenv("DATA_DIR", "/opt/data" if os.path.exists("/opt/data") else os.path.join(os.path.expanduser("~"), ".hermes"))


def _resolve_db(name: str) -> str:
    """Delegiert an die zentrale, validierende Auflösung (backend/db_paths.py)."""
    from backend.db_paths import resolve_db
    return resolve_db(name)


class DunningEngine:
    """Verwaltet Ausgangsrechnungen und das dreistufige Mahnwesen."""

    def __init__(self):
        self.memory_db = _resolve_db("agentic_memory.db")
        self.kanban_db = _resolve_db("kanban.db")
        self._init_tables()

    def _init_tables(self):
        """Erstellt die Tabellen für Rechnungen und Mahnhistorie."""
        if os.path.exists(self.memory_db):
            try:
                with sqlite3.connect(self.memory_db, timeout=5.0) as conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS invoices (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            invoice_id TEXT UNIQUE NOT NULL,
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
                            last_reminder_date TEXT,
                            dunning_level INTEGER DEFAULT 0,
                            dunning_fee REAL DEFAULT 0.0,
                            kanban_task_id TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS dunning_history (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            dunning_id TEXT UNIQUE NOT NULL,
                            invoice_id TEXT NOT NULL,
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
        recipient_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """Legt eine neue Ausgangsrechnung an."""
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
            with sqlite3.connect(self.memory_db, timeout=10.0) as conn:
                for attempt in range(5):
                    # Kollisionsfreie Rechnungsnummer (R-04): Zeit + Zufallssuffix
                    suffix = f"{int(time.time() * 1000) % 1000000:06d}-{uuid.uuid4().hex[:4].upper()}"
                    invoice_id = f"RE-{year}-{suffix}"
                    try:
                        conn.execute("""
                            INSERT INTO invoices (
                                invoice_id, customer_name, customer_email, recipient_address,
                                invoice_date, due_date, amount_net, tax_amount, amount_gross,
                                currency, status, dunning_level, dunning_fee
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'EUR', 'open', 0, 0.0)
                        """, (
                            invoice_id, customer_name, customer_email, recipient_address or "",
                            inv_date, due_date, amount_net, tax_amount, amount_gross
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
            "customer_name": customer_name,
            "customer_email": customer_email,
            "invoice_date": inv_date,
            "due_date": due_date,
            "amount_gross": amount_gross,
            "status": "open"
        }

    def check_overdue_invoices(self) -> List[Dict[str, Any]]:
        """Prüft alle Rechnungen auf Fälligkeit und ermittelt Handlungsbedarf."""
        if not os.path.exists(self.memory_db):
            return []

        today = datetime.date.today()
        candidates = []

        try:
            with sqlite3.connect(f"file:{self.memory_db}?mode=ro", uri=True, timeout=5.0) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
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

    def generate_dunning_draft(self, invoice_id: str, level: int) -> Dict[str, Any]:
        """Generiert einen rechtssicheren 3-Stufen Mahnentwurf zur Freigabe (HITL)."""
        if not os.path.exists(self.memory_db):
            raise ValueError("Datenbank nicht erreichbar.")

        with sqlite3.connect(f"file:{self.memory_db}?mode=ro", uri=True, timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,))
            inv = cur.fetchone()
            if not inv:
                raise ValueError(f"Rechnung {invoice_id} nicht gefunden.")
            inv = dict(inv)

        today = datetime.date.today()
        dunning_id = f"MAHN-{invoice_id}-{level}"
        
        # Konfiguration je Stufe
        if level == 1:
            fee = 0.0
            interest = 0.0
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
            fee = 5.0
            interest = 0.0
            deadline_days = 5
            deadline = (today + datetime.timedelta(days=deadline_days)).isoformat()
            total_claim = inv["amount_gross"] + fee
            subject = f"1. Mahnung zur Rechnung {invoice_id}"
            body_text = (
                f"Sehr geehrte Damen und Herren,\n\n"
                f"trotz unserer vorherigen Zahlungserinnerung konnten wir für die Rechnung {invoice_id} vom {inv['invoice_date']} "
                f"leider noch immer keinen Zahlungseingang feststellen. Die Forderung ist seit dem {inv['due_date']} fällig.\n\n"
                f"Forderungsaufstellung:\n"
                f"- Rechnungsbetrag: {inv['amount_gross']:.2f} EUR\n"
                f"- Mahngebühr: {fee:.2f} EUR\n"
                f"- GESAMTFORDERUNG: {total_claim:.2f} EUR\n\n"
                f"Wir fordern Sie hiermit auf, den Gesamtbetrag von {total_claim:.2f} EUR bis spätestens {deadline} "
                f"auf unser unten genanntes Konto auszugleichen.\n\n"
                f"Mit freundlichen Grüßen,\nBuchhaltung Archon OS"
            )
        else: # level >= 3
            fee = 10.0
            interest = round(inv["amount_gross"] * 0.03, 2) # ca. 3% Verzugsschaden
            deadline_days = 3
            deadline = (today + datetime.timedelta(days=deadline_days)).isoformat()
            total_claim = inv["amount_gross"] + fee + interest
            subject = f"LETZTE MAHNUNG vor Einleitung gerichtlicher Schritte (Rechnung {invoice_id})"
            body_text = (
                f"Sehr geehrte Damen und Herren,\n\n"
                f"auf unsere bisherigen Mahnungen zur Rechnung {invoice_id} vom {inv['invoice_date']} erfolgte bisher keine Zahlung.\n\n"
                f"Forderungsaufstellung:\n"
                f"- Hauptforderung: {inv['amount_gross']:.2f} EUR\n"
                f"- Mahnkosten & Verzugsschaden: {(fee + interest):.2f} EUR\n"
                f"- GESAMTBETRAG: {total_claim:.2f} EUR\n\n"
                f"Dies ist die LETZTE außergerichtliche Frist. Bitte überweisen Sie den Betrag von {total_claim:.2f} EUR "
                f"bis zum {deadline}.\n\n"
                f"Sollte kein fristgerechter Eingang erfolgen, werden wir ohne weitere Ankündigung das gerichtliche Mahnverfahren "
                f"beantragen bzw. die Forderung an ein Inkassounternehmen übergeben. Die hierdurch entstehenden erheblichen Mehrkosten "
                f"gehen zu Ihren Lasten.\n\n"
                f"Mit freundlichen Grüßen,\nGeschäftsleitung / Rechtsabteilung Archon OS"
            )

        total_claim = inv["amount_gross"] + fee + interest

        # Speichere Entwurf in DB
        with sqlite3.connect(self.memory_db, timeout=5.0) as conn:
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
                with sqlite3.connect(self.kanban_db, timeout=5.0) as conn:
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
            "status": "draft",
            "body_text": body_text
        }

    def approve_and_send_dunning(self, dunning_id: str) -> Dict[str, Any]:
        """Gibt einen Mahnentwurf frei und aktualisiert den Status der Rechnung (HITL Freigabe)."""
        if not os.path.exists(self.memory_db):
            raise ValueError("Datenbank nicht erreichbar.")

        with sqlite3.connect(self.memory_db, timeout=5.0) as conn:
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
                "SELECT status, dunning_level FROM invoices WHERE invoice_id = ?", (inv_id,)
            ).fetchone()
            if not inv_stat:
                raise ValueError(f"Rechnung {inv_id} nicht gefunden.")
            inv_status, inv_level = inv_stat[0], inv_stat[1]
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

            # 2. Rechnung aktualisieren
            status_map = {1: "dunning_1", 2: "dunning_2", 3: "dunning_3"}
            new_status = status_map.get(lvl, "dunning_1")
            conn.execute("""
                UPDATE invoices
                SET status = ?, dunning_level = ?, dunning_fee = ?, last_reminder_date = ?
                WHERE invoice_id = ?
            """, (new_status, lvl, d_dict["fee"], now_iso, inv_id))
            conn.commit()

        # 3. NotificationHub alarmieren
        try:
            from backend.notification_hub import get_notification_hub
            get_notification_hub().dispatch_notification(
                title=f"Mahnung Stufe {lvl} versandt",
                message=f"Mahnung '{dunning_id}' für Rechnung {inv_id} über {d_dict['total_claim']:.2f} EUR wurde freigegeben und versendet.",
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
            "dispatched_at": now_iso
        }

    def mark_invoice_paid(self, invoice_id: str) -> bool:
        """Markiert eine Rechnung als vollständig beglichen."""
        if not os.path.exists(self.memory_db):
            return False
        try:
            with sqlite3.connect(self.memory_db, timeout=5.0) as conn:
                conn.execute("UPDATE invoices SET status = 'paid' WHERE invoice_id = ?", (invoice_id,))
                conn.commit()
            return True
        except Exception as e:
            print(f"[DunningEngine] Error marking invoice paid: {e}", file=sys.stderr)
            return False


dunning_engine = DunningEngine()
