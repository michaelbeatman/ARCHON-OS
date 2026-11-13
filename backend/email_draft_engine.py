"""
Archon OS - Email Draft Engine mit Freigabe-Queue und GoBD/ISO 27001 Auditierung (t-7ca8cd)
Verwaltung KI-generierter E-Mail-Entwuerfe vor dem Versand mit 5 Aktionen:
1. Freigeben & Senden
2. Im Editor bearbeiten
3. Spaeter erinnern (Snooze)
4. Neu generieren (Prompt-Feedback)
5. Abbrechen / Verwerfen
"""

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

DB_FILE = "/opt/data/agentic_memory.db" if os.path.exists("/opt/data/agentic_memory.db") else os.path.expanduser("~/.hermes/agentic_memory.db")
GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

class EmailDraftEngine:
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._init_db()
        self._seed_sample_drafts_if_empty()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
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
            conn.commit()

    def _log_audit(self, draft_id: str, action: str, details: Dict[str, Any], created_by: str = "admin", conn: Optional[sqlite3.Connection] = None):
        """Revisionssichere SHA-256 Hash-Kette fuer saemtliche Entwurfs-Aktionen."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        details_json = json.dumps(details, sort_keys=True, ensure_ascii=False)

        def _do_log(active_conn: sqlite3.Connection):
            row = active_conn.execute("SELECT block_hash FROM email_draft_audit_log ORDER BY id DESC LIMIT 1").fetchone()
            prev_hash = row["block_hash"] if row else GENESIS_HASH
            raw_string = f"{prev_hash}|{draft_id}|{action}|{details_json}|{created_by}|{now_iso}"
            block_hash = hashlib.sha256(raw_string.encode("utf-8")).hexdigest()

            active_conn.execute("""
                INSERT INTO email_draft_audit_log (draft_id, action, details, prev_hash, block_hash, created_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (draft_id, action, details_json, prev_hash, block_hash, now_iso, created_by))
            try:
                from backend.audit_log import chained_audit_log
                chained_audit_log.record_event(
                    category="email",
                    action=f"email_{action.lower()}",
                    agent_id=created_by,
                    payload={"draft_id": draft_id, **details}
                )
            except Exception:
                pass

        if conn is not None:
            _do_log(conn)
        else:
            with self._get_conn() as local_conn:
                _do_log(local_conn)
                local_conn.commit()

    def _seed_sample_drafts_if_empty(self):
        """Erzeugt 2 realistische Muster-Entwuerfe, falls noch keine Daten vorliegen."""
        with self._get_conn() as conn:
            count = conn.execute("SELECT COUNT(*) as c FROM email_drafts").fetchone()["c"]
            if count > 0:
                return

            now = datetime.datetime.now(datetime.timezone.utc)
            d1_id = f"draft_{secrets.token_hex(6)}"
            d1_subject = "Projekt-Update: Status Meilenstein Q4 Infrastruktur"
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
            self._log_audit(d1_id, "DRAFT_CREATED", {"subject": d1_subject, "recipient": d1_rec}, created_by="system", conn=conn)

            d2_id = f"draft_{secrets.token_hex(6)}"
            d2_subject = "Rückfrage zu Rechnung INV-2026-0881 (Zahlungseingang)"
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
            self._log_audit(d2_id, "DRAFT_CREATED", {"subject": d2_subject, "recipient": d2_rec}, created_by="system", conn=conn)

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
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_conn() as conn:
            draft = conn.execute("SELECT * FROM email_drafts WHERE draft_id = ?", (draft_id,)).fetchone()
            if not draft:
                raise ValueError("Entwurf nicht gefunden.")

            body_hash = hashlib.sha256(draft["body_text"].encode("utf-8")).hexdigest()
            conn.execute("""
                UPDATE email_drafts
                SET status = 'approved', approved_at = ?, approved_by = ?, updated_at = ?, audit_hash = ?
                WHERE draft_id = ?
            """, (now_iso, approver_id, now_iso, body_hash, draft_id))

            # Revisionssicheres Audit-Log
            self._log_audit(draft_id, "DRAFT_APPROVED_SENT", {
                "approver": approver_id,
                "recipient": draft["recipient"],
                "subject": draft["subject"],
                "body_sha256": body_hash
            }, created_by=approver_id, conn=conn)

            # Falls verknuepft mit Kanban-Task, Task auf done setzen
            if draft["source_task_id"]:
                try:
                    kanban_db = os.path.expanduser("~/.hermes/kanban.db")
                    if os.path.exists(kanban_db):
                        with sqlite3.connect(kanban_db, timeout=5.0, factory=_ArchonClosingConn) as kconn:
                            kconn.execute("UPDATE tasks SET status = 'done' WHERE id = ?", (draft["source_task_id"],))
                            kconn.commit()
                except Exception:
                    pass

            conn.commit()

        return self.get_draft(draft_id)

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

    def get_audit_trail(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT id, draft_id, action, details, prev_hash, block_hash, created_at, created_by
                FROM email_draft_audit_log
                ORDER BY id DESC LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]

email_draft_engine = EmailDraftEngine()
