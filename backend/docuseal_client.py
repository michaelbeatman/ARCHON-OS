"""
backend/docuseal_client.py
Archon OS DocuSeal E-Signature Integration Client.
Handles contract signing workflows, templates, submission creation, and status synchronisation with Kanban and CRM.
"""

import os
import re
import sys
import time
import json
import hashlib
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
import urllib.request
import urllib.error
import urllib.parse
from typing import Dict, Any, Optional, List

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.getenv("DATA_DIR", "/opt/data" if os.path.exists("/opt/data") else os.path.join(os.path.expanduser("~"), ".hermes"))


def _resolve_db(name: str) -> str:
    """Delegiert an die zentrale, validierende Auflösung (backend/db_paths.py)."""
    from backend.db_paths import resolve_db
    return resolve_db(name)


class DocuSealClient:
    def __init__(self):
        self.base_url = os.getenv("DOCUSEAL_URL", "http://127.0.0.1:3080").rstrip("/")
        self.internal_url = "http://docuseal:3000"
        self.api_key = os.getenv("DOCUSEAL_API_KEY", "archon_docuseal_key_2026")
        self.kanban_db = _resolve_db("kanban.db")
        self.memory_db = _resolve_db("agentic_memory.db")
        self._init_esign_tables()

    @staticmethod
    def _resolve_cid(company_id: Optional[str] = None) -> str:
        try:
            from backend.tenant_context import get_active_company_id, sanitize_tenant_id
            return sanitize_tenant_id(company_id or get_active_company_id() or "default")
        except Exception:
            return (company_id or "default").strip() or "default"

    def _init_esign_tables(self):
        """Initialisiert die esign_contracts Tabelle in agentic_memory.db."""
        if os.path.exists(self.memory_db):
            try:
                with sqlite3.connect(self.memory_db, timeout=5.0, factory=_ArchonClosingConn) as conn:
                    conn.execute("PRAGMA journal_mode=WAL;")
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS esign_contracts (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            submission_id TEXT UNIQUE NOT NULL,
                            company_id TEXT DEFAULT 'default',
                            template_id TEXT,
                            title TEXT NOT NULL,
                            signer_email TEXT NOT NULL,
                            signer_name TEXT,
                            status TEXT DEFAULT 'pending',
                            sign_url TEXT,
                            kanban_task_id TEXT,
                            signed_document_path TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            completed_at TIMESTAMP
                        )
                    """)
                    for col_ddl in (
                        "ALTER TABLE esign_contracts ADD COLUMN company_id TEXT DEFAULT 'default'",
                        "ALTER TABLE esign_contracts ADD COLUMN signed_document_path TEXT",
                    ):
                        try:
                            conn.execute(col_ddl)
                        except sqlite3.OperationalError:
                            pass
                    conn.commit()
            except Exception as e:
                print(f"[DocuSeal] Init Warning: {e}", file=sys.stderr)

    def create_submission(
        self,
        title: str,
        signer_email: str,
        signer_name: str,
        template_id: Optional[str] = None,
        kanban_task_id: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Erstellt eine neue Signaturanfrage (Submission) via DocuSeal API."""
        cid = self._resolve_cid(company_id)
        submission_id = f"sub_{int(time.time())}_{os.urandom(3).hex()}"
        sign_url = f"{self.base_url}/s/{submission_id}"

        # Versuche DocuSeal REST API aufzurufen
        payload = {
            "template_id": template_id or 1,
            "send_email": True,
            "submitters": [
                {
                    "email": signer_email,
                    "name": signer_name,
                    "role": "Signer"
                }
            ]
        }

        api_called = False
        for ep in [self.base_url, self.internal_url]:
            try:
                req = urllib.request.Request(
                    f"{ep}/api/submissions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "X-Auth-Token": self.api_key
                    }
                )
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    if resp.status in (200, 201):
                        data = json.loads(resp.read().decode("utf-8"))
                        submission_id = str(data.get("id") or submission_id)
                        sign_url = data.get("submitters", [{}])[0].get("embed_url") or sign_url
                        api_called = True
                        break
            except Exception:
                continue

        # In SQLite persistieren
        if os.path.exists(self.memory_db):
            try:
                with sqlite3.connect(self.memory_db, timeout=5.0, factory=_ArchonClosingConn) as conn:
                    conn.execute("""
                        INSERT INTO esign_contracts (
                            submission_id, company_id, template_id, title, signer_email,
                            signer_name, status, sign_url, kanban_task_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        submission_id, cid, str(template_id or "default"), title,
                        signer_email, signer_name, "sent" if api_called else "draft_offline",
                        sign_url, kanban_task_id
                    ))
                    conn.commit()
            except Exception as e:
                print(f"[DocuSeal] Error inserting contract: {e}", file=sys.stderr)

        # Optional: Kanban-Task für Rechtsteam anlegen oder updaten
        if not kanban_task_id and os.path.exists(self.kanban_db):
            try:
                task_id = f"task-esign-{submission_id}"
                t_title = f"[E-Signatur] {title} ({signer_name})"
                t_body = (
                    f"Vertrag zur elektronischen Signatur versandt.\n\n"
                    f"- Unterzeichner: {signer_name} <{signer_email}>\n"
                    f"- Submission ID: {submission_id}\n"
                    f"- Signatur-Link: {sign_url}\n"
                    f"- Status: Ausstehend\n"
                )
                with sqlite3.connect(self.kanban_db, timeout=5.0, factory=_ArchonClosingConn) as conn:
                    conn.execute("""
                        INSERT INTO tasks (
                            id, title, body, assignee, status, priority, created_by, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        task_id, t_title, t_body, "legal_counsel", "ready", 2, "docuseal_client",
                        datetime.datetime.now().isoformat()
                    ))
                    conn.commit()
                kanban_task_id = task_id
            except Exception as e:
                print(f"[DocuSeal] Error creating Kanban task: {e}", file=sys.stderr)

        if not api_called:
            return {
                "status": "draft_offline",
                "error": "DocuSeal API nicht erreichbar — Entwurf lokal als draft_offline gespeichert.",
                "submission_id": submission_id,
                "company_id": cid,
                "title": title,
                "signer_name": signer_name,
                "signer_email": signer_email,
                "sign_url": sign_url,
                "kanban_task_id": kanban_task_id,
                "api_dispatched": False,
            }

        return {
            "status": "sent",
            "submission_id": submission_id,
            "company_id": cid,
            "title": title,
            "signer_name": signer_name,
            "signer_email": signer_email,
            "sign_url": sign_url,
            "kanban_task_id": kanban_task_id,
            "api_dispatched": True,
        }

    def _is_allowed_docuseal_url(self, url: str) -> bool:
        try:
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                return False
            allowed_hosts = set()
            for base in (self.base_url, self.internal_url):
                bp = urllib.parse.urlparse(base)
                if bp.hostname:
                    allowed_hosts.add(bp.hostname.lower())
            return parsed.hostname.lower() in allowed_hosts
        except Exception:
            return False

    def _download_signed_pdf(
        self,
        sub_id: str,
        data: Dict[str, Any],
        company_id: str,
    ) -> Optional[str]:
        """Lädt das signierte PDF von DocuSeal herunter und archiviert es GoBD-/mandantenkonform."""
        candidate_urls: List[str] = []
        docs = data.get("documents")
        if isinstance(docs, list):
            for d in docs:
                if isinstance(d, dict) and d.get("url"):
                    candidate_urls.append(str(d["url"]))
        if data.get("combined_document_url"):
            candidate_urls.append(str(data["combined_document_url"]))

        # Falls Webhook keine Dokument-URL enthält, über Submission-Endpoint abfragen
        if not candidate_urls:
            for ep in (self.base_url, self.internal_url):
                try:
                    req = urllib.request.Request(
                        f"{ep}/api/submissions/{urllib.parse.quote(sub_id)}",
                        headers={"X-Auth-Token": self.api_key},
                    )
                    with urllib.request.urlopen(req, timeout=3.0) as resp:
                        if resp.status == 200:
                            sub_info = json.loads(resp.read().decode("utf-8"))
                            for d in (sub_info.get("documents") or []):
                                if isinstance(d, dict) and d.get("url"):
                                    candidate_urls.append(str(d["url"]))
                            if sub_info.get("combined_document_url"):
                                candidate_urls.append(str(sub_info["combined_document_url"]))
                            break
                except Exception:
                    continue

        pdf_bytes: Optional[bytes] = None
        for u in candidate_urls:
            if not self._is_allowed_docuseal_url(u):
                continue
            try:
                req = urllib.request.Request(u, headers={"X-Auth-Token": self.api_key})
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    if resp.status == 200:
                        raw = resp.read()
                        if raw:
                            pdf_bytes = raw
                            break
            except Exception:
                continue

        if not pdf_bytes:
            return None

        cid = self._resolve_cid(company_id)
        safe_sub = re.sub(r"[^A-Za-z0-9._-]+", "_", sub_id).strip("_") or "submission"
        day_tag = datetime.date.today().strftime("%Y%m%d")
        archive_dir = os.path.join(WORKSPACE_DIR, "data", "tenants", cid, "contracts", "signed")
        os.makedirs(archive_dir, exist_ok=True)
        out_path = os.path.join(archive_dir, f"{safe_sub}_{day_tag}.pdf")
        with open(out_path, "wb") as fh:
            fh.write(pdf_bytes)
        return out_path

    def handle_webhook_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Verarbeitet eingehende DocuSeal Webhooks (z. B. submission.completed)."""
        event_type = event_data.get("event_type") or event_data.get("type", "")
        ev_low = str(event_type or "").strip().lower()
        if not ev_low:
            return {"status": "rejected", "reason": "Missing or empty event_type"}

        valid_events = {
            "submission.created",
            "submission.viewed",
            "submission.started",
            "submission.completed",
            "submission.declined",
            "submission.expired",
            "submission.archived",
            "form.viewed",
            "form.started",
            "form.completed",
            "form.declined",
        }
        if ev_low not in valid_events:
            return {"status": "ignored", "reason": f"Unsupported event_type: {event_type}"}

        data = event_data.get("data", {})
        if not isinstance(data, dict):
            data = {}
        sub_id = str(data.get("id") or data.get("submission_id", "")).strip()
        if not sub_id:
            return {"status": "ignored", "reason": "No submission_id found"}

        now_iso = datetime.datetime.now().isoformat()
        kanban_task_id = None
        company_id = "default"

        is_completed = ev_low in ("submission.completed", "form.completed")
        if ev_low in ("submission.declined", "form.declined"):
            target_status = "declined"
        elif ev_low == "submission.expired":
            target_status = "expired"
        elif ev_low in ("form.viewed", "submission.viewed", "form.started", "submission.started"):
            target_status = "viewed"
        elif is_completed:
            target_status = "completed"
        else:
            target_status = ev_low.split(".")[-1] or "updated"

        if os.path.exists(self.memory_db):
            try:
                with sqlite3.connect(self.memory_db, timeout=5.0, factory=_ArchonClosingConn) as conn:
                    cur = conn.cursor()
                    cur.execute("PRAGMA table_info(esign_contracts)")
                    avail_cols = {r[1] for r in cur.fetchall()}
                    sel_cols = ["kanban_task_id"] + (["company_id"] if "company_id" in avail_cols else [])
                    cur.execute(f"SELECT {', '.join(sel_cols)} FROM esign_contracts WHERE submission_id = ?", (sub_id,))
                    row = cur.fetchone()
                    if row:
                        kanban_task_id = row[0]
                        if len(row) > 1 and row[1]:
                            company_id = str(row[1])
            except Exception as e:
                print(f"[DocuSeal] Webhook lookup error: {e}", file=sys.stderr)

        signed_doc_path: Optional[str] = None
        if is_completed:
            signed_doc_path = self._download_signed_pdf(sub_id, data, company_id)

        # 1. Update esign_contracts Status + signed_document_path in DB
        if os.path.exists(self.memory_db):
            try:
                with sqlite3.connect(self.memory_db, timeout=5.0, factory=_ArchonClosingConn) as conn:
                    cur = conn.cursor()
                    cur.execute("PRAGMA table_info(esign_contracts)")
                    avail_cols = {r[1] for r in cur.fetchall()}
                    if "signed_document_path" in avail_cols and signed_doc_path:
                        cur.execute("""
                            UPDATE esign_contracts
                            SET status = ?,
                                completed_at = CASE WHEN ? THEN ? ELSE completed_at END,
                                signed_document_path = ?
                            WHERE submission_id = ?
                        """, (target_status, 1 if is_completed else 0, now_iso, signed_doc_path, sub_id))
                    else:
                        cur.execute("""
                            UPDATE esign_contracts
                            SET status = ?, completed_at = CASE WHEN ? THEN ? ELSE completed_at END
                            WHERE submission_id = ?
                        """, (target_status, 1 if is_completed else 0, now_iso, sub_id))
                    conn.commit()
            except Exception as e:
                print(f"[DocuSeal] Webhook DB error: {e}", file=sys.stderr)

        # 2. Update Kanban-Task differenziert nach Status
        if kanban_task_id and os.path.exists(self.kanban_db):
            try:
                with sqlite3.connect(self.kanban_db, timeout=5.0, factory=_ArchonClosingConn) as conn:
                    if is_completed:
                        conn.execute("""
                            UPDATE tasks
                            SET status = 'done', completed_at = ?, result = 'Vollständig digital unterzeichnet via DocuSeal.'
                            WHERE id = ?
                        """, (now_iso, kanban_task_id))
                    elif target_status in ("declined", "expired"):
                        reason_txt = "Signaturanfrage vom Unterzeichner abgelehnt." if target_status == "declined" else "Signaturanfrage abgelaufen."
                        conn.execute("UPDATE tasks SET result = ? WHERE id = ?", (reason_txt, kanban_task_id))
                    conn.commit()
            except Exception as e:
                print(f"[DocuSeal] Webhook Kanban error: {e}", file=sys.stderr)

        # 3. Differenzierte Benachrichtigung absetzen
        try:
            from backend.notification_hub import get_notification_hub
            hub = get_notification_hub()
            if is_completed:
                hub.dispatch_notification(
                    title="Vertrag unterzeichnet",
                    message=f"DocuSeal Submission '{sub_id}' wurde erfolgreich unterzeichnet.",
                    severity="INFO",
                    category="legal_contract",
                )
            elif target_status == "declined":
                hub.dispatch_notification(
                    title="Vertragssignatur abgelehnt",
                    message=f"DocuSeal Submission '{sub_id}' wurde vom Unterzeichner abgelehnt.",
                    severity="WARNING",
                    category="legal_contract",
                )
            elif target_status == "expired":
                hub.dispatch_notification(
                    title="Signaturanfrage abgelaufen",
                    message=f"DocuSeal Submission '{sub_id}' ist abgelaufen ohne Signatur.",
                    severity="WARNING",
                    category="legal_contract",
                )
            elif target_status == "viewed":
                hub.dispatch_notification(
                    title="Signaturdokument eingesehen",
                    message=f"DocuSeal Submission '{sub_id}' wurde vom Unterzeichner geöffnet.",
                    severity="INFO",
                    category="legal_contract",
                )
        except Exception:
            pass

        return {
            "status": "processed",
            "event_type": event_type,
            "target_status": target_status,
            "submission_id": sub_id,
            "signed_document_path": signed_doc_path,
            "kanban_task_updated": kanban_task_id,
        }

    def list_contracts(self, limit: int = 50, company_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Listet Signaturverträge auf (optional mandantenbezogen)."""
        if not os.path.exists(self.memory_db):
            return []
        limit = max(1, min(int(limit), 500))
        cid: Optional[str] = None
        if company_id and str(company_id).strip():
            try:
                from backend.tenant_context import sanitize_tenant_id
                cid = sanitize_tenant_id(str(company_id).strip())
            except Exception:
                cid = str(company_id).strip()
        try:
            with sqlite3.connect(f"file:{self.memory_db}?mode=ro", uri=True, timeout=5.0, factory=_ArchonClosingConn) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                if cid:
                    cur.execute("""
                        SELECT submission_id, template_id, title, signer_email, signer_name,
                               status, sign_url, kanban_task_id, company_id, signed_document_path,
                               created_at, completed_at
                        FROM esign_contracts
                        WHERE company_id = ? OR company_id IS NULL OR company_id = ''
                        ORDER BY id DESC
                        LIMIT ?
                    """, (cid, limit))
                else:
                    cur.execute("""
                        SELECT submission_id, template_id, title, signer_email, signer_name,
                               status, sign_url, kanban_task_id, company_id, signed_document_path,
                               created_at, completed_at
                        FROM esign_contracts
                        ORDER BY id DESC
                        LIMIT ?
                    """, (limit,))
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            print(f"[DocuSeal] Error listing contracts: {e}", file=sys.stderr)
            return []


docuseal_client = DocuSealClient()
