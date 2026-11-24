"""
Archon OS - Email Draft Engine mit Freigabe-Queue und GoBD/ISO 27001 Auditierung (t-7ca8cd)
Verwaltung KI-generierter E-Mail-Entwuerfe vor dem Versand mit 5 Aktionen:
1. Freigeben & Senden
2. Im Editor bearbeiten
3. Spaeter erinnern (Snooze)
4. Neu generieren (Prompt-Feedback)
5. Abbrechen / Verwerfen
"""
import logging
_archon_exc_logger = logging.getLogger("email_draft_engine")

import os
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
import hashlib
import json
import secrets
import datetime
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.db_paths import resolve_db
    DB_FILE = resolve_db("agentic_memory.db")
except Exception:
    DB_FILE = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")
GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

# Epochen-Migration (block_id): neue Bloecke werden mit
# _chain_hash(canonical, next_id) signiert; die ID steht explizit in der Tabelle.
# CUTOFF markiert die erste ID der id-bewussten Epoche. Stabile, persistente
# Variante: ARCHON_EMAIL_DRAFT_HMAC_EPOCH_FROM. Ohne ENV wird CUTOFF zur
# Laufzeit aus MAX(id)+1 der DB abgeleitet (siehe _chain_migration_cutoff).
_EMAIL_DRAFT_CUTOFF_ENV = "ARCHON_EMAIL_DRAFT_HMAC_EPOCH_FROM"
_EMAIL_DRAFT_AUDIT_TABLE = "email_draft_audit_log"


def _chain_migration_cutoff(conn, table: str, env_name: str) -> int:
    """Erste Block-ID, ab der der id-bewusste Signaturpfad gilt.

    Die ENV-Variable ist die empfohlene Variante: sie ist ueber Neustarts
    hinweg stabil und kann zusammen mit ARCHON_AUDIT_HMAC_EPOCHS/..._FROM eine
    Key-Rotation ab genau diesem Block markieren. Ohne ENV wird MAX(id)+1 aus
    der DB gelesen — alle heute vorhandenen Bloecke sind dann Legacy und
    bleiben (auch mit altem Verfahren) verifizierbar. Es wird keine Tabelle,
    keine Spalte und keine Zeile hinzugefuegt oder veraendert.
    """
    raw = os.environ.get(env_name, "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return int(conn.execute(
        f"SELECT COALESCE(MAX(id), 0) + 1 FROM {table}"
    ).fetchone()[0])


class EmailDraftEngine:
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._init_db()
        self._seed_sample_drafts_if_empty()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0, factory=_ArchonClosingConn)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 10000;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS email_drafts (
                    draft_id TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    agent_id TEXT DEFAULT 'default',
                    agent_name TEXT DEFAULT 'Hermes Orchestrator',
                    body_text TEXT NOT NULL,
                    body_html TEXT,
                    status TEXT DEFAULT 'pending',
                    snooze_until TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    approved_at TEXT,
                    approved_by TEXT,
                    rejected_at TEXT,
                    rejected_by TEXT,
                    rejection_reason TEXT,
                    feedback_text TEXT,
                    source_task_id TEXT,
                    audit_hash TEXT
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS email_draft_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    draft_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT,
                    prev_hash TEXT NOT NULL,
                    block_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL
                );
            """)
            # H3 (Audit 23.11.2026): Append-only-Schutz fuer die Entwurfs-Kette.
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS email_draft_audit_no_update
                BEFORE UPDATE ON email_draft_audit_log
                BEGIN
                    SELECT RAISE(ABORT, 'email_draft_audit_log is append-only');
                END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS email_draft_audit_no_delete
                BEFORE DELETE ON email_draft_audit_log
                BEGIN
                    SELECT RAISE(ABORT, 'email_draft_audit_log is append-only');
                END
            """)
            conn.commit()

    def _log_audit(self, draft_id: str, action: str, details: Dict[str, Any], created_by: str = "admin", conn: Optional[sqlite3.Connection] = None):
        """Revisionssichere SHA-256 Hash-Kette fuer saemtliche Entwurfs-Aktionen."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        details_json = json.dumps(details, sort_keys=True, ensure_ascii=False)

        def _do_log(active_conn: sqlite3.Connection):
            row = active_conn.execute("SELECT block_hash FROM email_draft_audit_log ORDER BY id DESC LIMIT 1").fetchone()
            prev_hash = row["block_hash"] if row else GENESIS_HASH
            # Epochen-Migration: Schreib- und Pruefpfad muessen dieselbe ID
            # verwenden, sonst ist eine Key-Rotation mit EPOCH_FROM wirkungslos
            # (gleicher Fix wie in audit_log.record_event / api_key_manager).
            next_id = int(active_conn.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 FROM email_draft_audit_log"
            ).fetchone()[0])
            raw_string = f"{prev_hash}|{draft_id}|{action}|{details_json}|{created_by}|{now_iso}"
            # H3: HMAC mit zentralem Chain-Secret statt nacktem SHA-256.
            # id-bewusst: Epochen-Key des Blocks statt immer juengstem Key.
            from backend.audit_log import _chain_hash
            block_hash = _chain_hash(raw_string, next_id)

            active_conn.execute("""
                INSERT INTO email_draft_audit_log (id, draft_id, action, details, prev_hash, block_hash, created_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (next_id, draft_id, action, details_json, prev_hash, block_hash, now_iso, created_by))
            try:
                from backend.audit_log import chained_audit_log
                chained_audit_log.record_event(
                    category="email",
                    action=f"email_{action.lower()}",
                    agent_id=created_by,
                    payload={"draft_id": draft_id, **details}
                )
            except Exception as _exc:
                _archon_exc_logger.debug("[email_draft_engine] Ignorierte Ausnahme (Z.114): %s", _exc)

        if conn is not None:
            _do_log(conn)
        else:
            with self._get_conn() as local_conn:
                _do_log(local_conn)
                local_conn.commit()

    def _seed_sample_drafts_if_empty(self):
        """Erzeugt Muster-Entwuerfe NUR im expliziten Demo-Modus (C21).

        Vorher wurden beim ersten Start immer zwei realistisch wirkende
        Entwuerfe (inkl. `DRAFT_CREATED`-Audit-Events und erfundenen
        `source_task_id`) angelegt. Sie erschienen in der Freigabe-Queue und
        konnten tatsaechlich versendet werden. Im Normalbetrieb darf das
        System keine E-Mails erfinden.
        """
        try:
            from backend.demo_mode import is_demo_mode
            demo = bool(is_demo_mode())
        except Exception:
            demo = False
        if not demo:
            _archon_exc_logger.info(
                "[EmailDrafts] Keine Muster-Entwuerfe erzeugt (Demo-Modus inaktiv)."
            )
            return
        with self._get_conn() as conn:
            count = conn.execute("SELECT COUNT(*) as c FROM email_drafts").fetchone()["c"]
            if count > 0:
                return

            now = datetime.datetime.now(datetime.timezone.utc)
            d1_id = f"draft_{secrets.token_hex(6)}"
            d1_subject = "[DEMO] Projekt-Update: Status Meilenstein Q4 Infrastruktur"
            d1_rec = "keller.michael@archon-partner.de"
            d1_body = (
                "Sehr geehrter Herr Keller,\n\n"
                "das autonome Deployment der API-Governance und der GoBD-Auditierung wurde erfolgreich auf Port 8501 abgeschlossen. "
                "Alle 6 Qualitätsprüfungen wurden mit 0 Leaks bestanden.\n\n"
                "Gerne erwarten wir Ihre Freigabe für das anstehende Wartungsfenster.\n\n"
                "Mit freundlichen Grüßen,\n"
                "Hermes Orchestrator (Root Agent)"
            )
            d1_created = (now - datetime.timedelta(minutes=35)).isoformat()
            conn.execute("""
                INSERT INTO email_drafts (
                    draft_id, subject, recipient, sender, agent_id, agent_name,
                    body_text, status, created_at, updated_at, source_task_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, 't-6fad7a')
            """, (d1_id, d1_subject, d1_rec, "hermes@archon-os.internal", "default", "Hermes Orchestrator", d1_body, d1_created, d1_created))
            self._log_audit(d1_id, "DEMO_DRAFT_CREATED", {"subject": d1_subject, "recipient": d1_rec, "demo": True}, created_by="system", conn=conn)

            d2_id = f"draft_{secrets.token_hex(6)}"
            d2_subject = "[DEMO] Rückfrage zu Rechnung INV-2026-0881 (Zahlungseingang)"
            d2_rec = "buchhaltung@cloud-scale.io"
            d2_body = (
                "Hallo Team von CloudScale,\n\n"
                "bezugnehmend auf Ihre Rechnung INV-2026-0881 über 348,00 EUR möchten wir mitteilen, "
                "dass der Beleg im internen Rechnungswesen geprüft und zur Freigabe vorgemerkt wurde.\n\n"
                "Bitte senden Sie uns zur vollständigen Archivierung die zugehörige Umsatzsteuer-ID.\n\n"
                "Beste Grüße,\n"
                "Finanz-Agent (Archon OS)"
            )
            d2_created = (now - datetime.timedelta(hours=2, minutes=10)).isoformat()
            conn.execute("""
                INSERT INTO email_drafts (
                    draft_id, subject, recipient, sender, agent_id, agent_name,
                    body_text, status, created_at, updated_at, source_task_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, 't-5596bd')
            """, (d2_id, d2_subject, d2_rec, "finanzen@archon-os.internal", "finanzen", "Finanz-Agent", d2_body, d2_created, d2_created))
            self._log_audit(d2_id, "DEMO_DRAFT_CREATED", {"subject": d2_subject, "recipient": d2_rec, "demo": True}, created_by="system", conn=conn)

            conn.commit()

    def list_drafts(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Gibt alle Entwuerfe zurueck, optional nach Status gefiltert."""
        with self._get_conn() as conn:
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            # Schlummernde Entwuerfe reaktivieren, falls Zeit abgelaufen
            conn.execute("""
                UPDATE email_drafts
                SET status = 'pending'
                WHERE status = 'snoozed' AND snooze_until IS NOT NULL AND snooze_until <= ?
            """, (now_iso,))
            conn.commit()

            query = "SELECT * FROM email_drafts"
            params = []
            if status and status != "all":
                query += " WHERE status = ?"
                params.append(status)

            query += " ORDER BY created_at DESC"
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_draft(self, draft_id: str) -> Optional[Dict[str, Any]]:
        """Ruft einen einzelnen Entwurf ab."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM email_drafts WHERE draft_id = ?", (draft_id,)).fetchone()
            return dict(row) if row else None

    def create_draft(
        self,
        subject: str,
        recipient: str,
        body_text: str,
        agent_id: str = "default",
        agent_name: str = "Hermes Orchestrator",
        sender: str = "system@archon-os.internal",
        source_task_id: Optional[str] = None,
        created_by: str = "admin"
    ) -> Dict[str, Any]:
        """Erstellt einen neuen Entwurf zur Freigabe."""
        if not subject or not recipient or not body_text:
            raise ValueError("Betreff, Empfänger und Text dürfen nicht leer sein.")

        draft_id = f"draft_{secrets.token_hex(6)}"
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO email_drafts (
                    draft_id, subject, recipient, sender, agent_id, agent_name,
                    body_text, status, created_at, updated_at, source_task_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """, (draft_id, subject.strip(), recipient.strip(), sender.strip(), agent_id, agent_name, body_text.strip(), now_iso, now_iso, source_task_id))

            self._log_audit(draft_id, "DRAFT_CREATED", {
                "subject": subject,
                "recipient": recipient,
                "agent_id": agent_id
            }, created_by=created_by, conn=conn)
            conn.commit()

        return self.get_draft(draft_id)

    # AKTION 1: Freigeben & Senden
    def approve_and_send(self, draft_id: str, approver_id: str = "admin") -> Dict[str, Any]:
        """Gibt den Entwurf frei und versendet ihn TAETSCHLICH ueber SMTP.

        Audit 23.11.2026: diese Methode setzte frueher status='approved' und
        schrieb DRAFT_APPROVED_SENT, ohne jemals SMTP aufzurufen. Der Audit-
        Eintrag und die UI-Meldung 'versendet' waren nachweislich falsch.
        """
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_conn() as conn:
            draft = conn.execute("SELECT * FROM email_drafts WHERE draft_id = ?", (draft_id,)).fetchone()
            if not draft:
                raise ValueError("Entwurf nicht gefunden.")

            # Echter Versand VOR Status-/Audit-Schreibvorgang.
            try:
                from backend.email_service import send_email
                send_result = send_email(
                    to_email=draft["recipient"],
                    subject=draft["subject"],
                    body_text=draft["body_text"],
                ) or {}
            except Exception as exc:
                send_result = {"status": "error", "message": str(exc)}

            delivery_status = str(send_result.get("status") or "error")
            if delivery_status == "error":
                # Kein Statuswechsel, kein 'SENT'-Audit: sonst wuerde die
                # Freigabe einen nie erfolgten Versand bestaetigen.
                raise RuntimeError(
                    f"E-Mail-Versand fehlgeschlagen: {send_result.get('message') or 'unbekannt'}"
                )

            body_hash = hashlib.sha256(draft["body_text"].encode("utf-8")).hexdigest()
            conn.execute("""
                UPDATE email_drafts
                SET status = 'approved', approved_at = ?, approved_by = ?, updated_at = ?, audit_hash = ?
                WHERE draft_id = ?
            """, (now_iso, approver_id, now_iso, body_hash, draft_id))

            # Nur bei tatsaechlichem Versand heisst der Audit-Eintrag '...SENT'.
            audit_action = (
                "DRAFT_APPROVED_SENT" if delivery_status == "sent"
                else "DRAFT_APPROVED_NOT_SENT"
            )
            self._log_audit(draft_id, audit_action, {
                "approver": approver_id,
                "recipient": draft["recipient"],
                "subject": draft["subject"],
                "body_sha256": body_hash,
                "delivery_status": delivery_status,
                "smtp_reason": send_result.get("reason"),
            }, created_by=approver_id, conn=conn)

            # Kanban-Task erst abschliessen, wenn die Mail wirklich raus ist.
            if delivery_status == "sent" and draft["source_task_id"]:
                try:
                    try:
                        from backend.db_paths import resolve_db
                        kanban_db = resolve_db("kanban.db")
                    except Exception:
                        kanban_db = os.path.expanduser("~/.hermes/kanban.db")
                    if os.path.exists(kanban_db):
                        with sqlite3.connect(kanban_db, timeout=5.0, factory=_ArchonClosingConn) as kconn:
                            kconn.execute("UPDATE tasks SET status = 'done' WHERE id = ?", (draft["source_task_id"],))
                            kconn.commit()
                except Exception as _exc:
                    _archon_exc_logger.debug("[email_draft_engine] Ignorierte Ausnahme (Z.272): %s", _exc)

            conn.commit()

        result = self.get_draft(draft_id) or {}
        result["delivery_status"] = delivery_status
        result["message"] = (
            "E-Mail freigegeben und versendet." if delivery_status == "sent"
            else "E-Mail freigegeben, aber NICHT versendet (SMTP nicht konfiguriert)."
        )
        return result

    # AKTION 2: Im Editor bearbeiten
    def edit_draft(
        self,
        draft_id: str,
        subject: str,
        recipient: str,
        body_text: str,
        editor_id: str = "admin"
    ) -> Dict[str, Any]:
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_conn() as conn:
            old = conn.execute("SELECT subject, recipient, body_text FROM email_drafts WHERE draft_id = ?", (draft_id,)).fetchone()
            if not old:
                raise ValueError("Entwurf nicht gefunden.")

            new_hash = hashlib.sha256(body_text.strip().encode("utf-8")).hexdigest()
            conn.execute("""
                UPDATE email_drafts
                SET subject = ?, recipient = ?, body_text = ?, updated_at = ?, audit_hash = ?
                WHERE draft_id = ?
            """, (subject.strip(), recipient.strip(), body_text.strip(), now_iso, new_hash, draft_id))

            self._log_audit(draft_id, "DRAFT_EDITED", {
                "editor": editor_id,
                "old_subject": old["subject"],
                "new_subject": subject.strip(),
                "old_recipient": old["recipient"],
                "new_recipient": recipient.strip()
            }, created_by=editor_id, conn=conn)
            conn.commit()

        return self.get_draft(draft_id)

    # AKTION 3: Spaeter erinnern (Snooze)
    def snooze_draft(self, draft_id: str, hours: int = 1, user_id: str = "admin") -> Dict[str, Any]:
        now = datetime.datetime.now(datetime.timezone.utc)
        snooze_until = (now + datetime.timedelta(hours=hours)).isoformat()
        now_iso = now.isoformat()

        with self._get_conn() as conn:
            conn.execute("""
                UPDATE email_drafts
                SET status = 'snoozed', snooze_until = ?, updated_at = ?
                WHERE draft_id = ?
            """, (snooze_until, now_iso, draft_id))

            self._log_audit(draft_id, "DRAFT_SNOOZED", {
                "snoozed_hours": hours,
                "snooze_until": snooze_until
            }, created_by=user_id, conn=conn)
            conn.commit()

        return self.get_draft(draft_id)

    # AKTION 4: Neu generieren (Prompt-Feedback)
    def regenerate_draft(self, draft_id: str, feedback_text: str, user_id: str = "admin") -> Dict[str, Any]:
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE email_drafts
                SET status = 'generating', feedback_text = ?, updated_at = ?
                WHERE draft_id = ?
            """, (feedback_text.strip(), now_iso, draft_id))

            self._log_audit(draft_id, "DRAFT_REGENERATE_REQUESTED", {
                "feedback": feedback_text.strip(),
                "requested_by": user_id
            }, created_by=user_id, conn=conn)
            conn.commit()

        return self.get_draft(draft_id)

    # AKTION 5: Abbrechen / Verwerfen
    def reject_draft(self, draft_id: str, reason: str = "Vom Nutzer verworfen", user_id: str = "admin") -> Dict[str, Any]:
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE email_drafts
                SET status = 'rejected', rejected_at = ?, rejected_by = ?, rejection_reason = ?, updated_at = ?
                WHERE draft_id = ?
            """, (now_iso, user_id, reason.strip(), now_iso, draft_id))

            self._log_audit(draft_id, "DRAFT_REJECTED", {
                "reason": reason.strip(),
                "rejected_by": user_id
            }, created_by=user_id, conn=conn)
            conn.commit()

        return self.get_draft(draft_id)

    def get_status_counts(self) -> Dict[str, int]:
        """Liefert die Anzahl der Entwuerfe je Status für Filter-Badges und Listen-API."""
        counts: Dict[str, int] = {
            "pending": 0,
            "approved": 0,
            "sent": 0,
            "snoozed": 0,
            "rejected": 0,
            "total": 0,
        }
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT COALESCE(LOWER(status), 'pending') AS st, COUNT(*) AS cnt FROM email_drafts GROUP BY LOWER(status)"
            ).fetchall()
            for r in rows:
                st = r["st"] or "pending"
                cnt = int(r["cnt"] or 0)
                counts[st] = cnt
                counts["total"] += cnt
        return counts

    def verify_chain(self) -> Dict[str, Any]:
        """Kryptografische Pruefung der Entwurfs-Audit-Kette (Legacy + Epoche)."""
        return verify_email_draft_chain(self.db_path)

    def get_audit_trail(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT id, draft_id, action, details, prev_hash, block_hash, created_at, created_by
                FROM email_draft_audit_log
                ORDER BY id DESC LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]


def verify_email_draft_chain(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Prueft die email_draft_audit_log-Kette inkl. Epochen-Migration.

    Strategie pro Block:
      * id >= CUTOFF: streng id-bewusst via _verify_hash(canonical, hash, id).
      * id <  CUTOFF: zuerst id-bewusst, danach als Fallback das alte Verfahren
        ohne ID (_verify_hash(canonical, hash, None)). Der Fallback ist
        erforderlich, damit Legacy-Bloecke auch nach einer Key-Rotation mit
        ARCHON_AUDIT_HMAC_EPOCHS / ARCHON_AUDIT_HMAC_EPOCH_FROM gueltig
        bleiben: der alte Pfad nimmt den zum Schreibzeitpunkt juengsten Key,
        der id-bewusste Pfad den Epochen-Key des Blocks.

    CUTOFF = ARCHON_EMAIL_DRAFT_HMAC_EPOCH_FROM (stabil, dokumentiert), sonst
    MAX(id)+1 zur Laufzeit. Die prev_hash-Verkettung ist Verfahren-unabhaengig:
    der Hash eines neuen Blocks haengt vom gespeicherten prev_hash ab, nicht
    davon, wie der Vorgänger signiert wurde — der Uebergang ist daher bruchfrei.
    """
    from backend.audit_log import HMAC_PREFIX, _verify_hash, _hmac_epochs

    conn = sqlite3.connect(db_path or DB_FILE, timeout=15.0, factory=_ArchonClosingConn)
    conn.row_factory = sqlite3.Row
    try:
        has_tbl = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (_EMAIL_DRAFT_AUDIT_TABLE,),
        ).fetchone()
        if not has_tbl:
            return {"valid": True, "count": 0, "message": "Email-Draft-Kette ist leer."}
        rows = conn.execute(
            "SELECT * FROM email_draft_audit_log ORDER BY id ASC"
        ).fetchall()
        if not rows:
            return {"valid": True, "count": 0, "message": "Email-Draft-Kette ist leer."}

        cutoff = _chain_migration_cutoff(conn, _EMAIL_DRAFT_AUDIT_TABLE, _EMAIL_DRAFT_CUTOFF_ENV)
        expected_prev = GENESIS_HASH
        hmac_blocks = 0
        for r in rows:
            if str(r["prev_hash"]) != expected_prev:
                return {
                    "valid": False, "broken_at_id": r["id"], "cutoff": cutoff,
                    "message": f"Kettenbruch bei Email-Draft-Audit ID {r['id']}.",
                }
            # Exakt derselbe kanonische String wie im Schreibpfad (_log_audit).
            canonical = (
                f"{r['prev_hash']}|{r['draft_id']}|{r['action']}|"
                f"{r['details']}|{r['created_by']}|{r['created_at']}"
            )
            stored = str(r["block_hash"] or "")
            if stored.startswith(HMAC_PREFIX):
                hmac_blocks += 1
            bid = int(r["id"])
            ok = _verify_hash(canonical, stored, bid)
            if not ok and bid < cutoff:
                ok = _verify_hash(canonical, stored, None)
            if not ok:
                return {
                    "valid": False, "broken_at_id": bid, "cutoff": cutoff,
                    "message": f"Payload-Manipulation bei Email-Draft-Audit ID {bid}.",
                }
            expected_prev = stored

        key_active = bool(_hmac_epochs())
        first_hmac_id = next(
            (int(r["id"]) for r in rows if str(r["block_hash"] or "").startswith(HMAC_PREFIX)),
            None,
        )
        if first_hmac_id is not None and any(
            int(r["id"]) > first_hmac_id and not str(r["block_hash"] or "").startswith(HMAC_PREFIX)
            for r in rows
        ):
            return {
                "valid": False, "cutoff": cutoff, "hmac_active": key_active,
                "message": "HMAC-Signatur auf nacktes SHA-256 zurueckgesetzt (Downgrade).",
            }
        if hmac_blocks and not key_active:
            return {
                "valid": False, "cutoff": cutoff, "hmac_active": False,
                "message": "HMAC-Bloecke ohne passenden ARCHON_AUDIT_HMAC_KEY.",
            }
        if key_active and any(
            int(r["id"]) >= cutoff and not str(r["block_hash"] or "").startswith(HMAC_PREFIX)
            for r in rows
        ):
            return {
                "valid": False, "cutoff": cutoff, "hmac_active": True,
                "message": "HMAC-Key aktiv, aber Block ab Epoche ohne HMAC-Signatur (Downgrade).",
            }
        return {
            "valid": True, "count": len(rows), "cutoff": cutoff,
            "hmac_active": key_active, "hmac_blocks": hmac_blocks,
            "latest_hash": expected_prev,
        }
    finally:
        conn.close()


email_draft_engine = EmailDraftEngine()
