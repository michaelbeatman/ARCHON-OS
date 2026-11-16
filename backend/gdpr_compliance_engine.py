"""
backend/gdpr_compliance_engine.py
DSGVO- / GDPR-Compliance Engine für Archon OS 2026.
Implementiert Betroffenenrechte nach:
- Art. 15 DSGVO: Recht auf Auskunft (Datenexport über alle Datenquellen)
- Art. 17 DSGVO: Recht auf Löschung / Recht auf Vergessenwerden (Audit-sichere Anonymisierung/Löschung)
- Art. 30 DSGVO: Manipulationssicheres Verzeichnis von Verarbeitungstätigkeiten & Löschquittungen
"""

import os
import re
import sys
import json
import time
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
import datetime
from typing import Dict, Any, List, Optional
import urllib.request
import urllib.parse

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_db(name: str) -> str:
    """Delegiert an die zentrale, validierende Auflösung (backend/db_paths.py)."""
    from backend.db_paths import resolve_db
    return resolve_db(name)


def _resolve_obsidian_dir() -> str:
    candidates = [
        "/opt/data/obsidian",
        os.path.join(WORKSPACE_DIR, "obsidian_vault"),
        os.path.expanduser("~/Documents/Obsidian Vault")
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[1]


class GDPRComplianceEngine:
    """Steuert Datenauskunft und Datenlöschung über alle Speicherschichten."""

    def __init__(self):
        self.memory_db = _resolve_db("agentic_memory.db")
        self.kanban_db = _resolve_db("kanban.db")
        self.state_db = _resolve_db("state.db")
        self.obsidian_dir = _resolve_obsidian_dir()
        self._init_audit_table()

    def _get_conn(self, db_path: str, readonly: bool = False) -> sqlite3.Connection:
        if readonly and os.path.exists(db_path):
            uri = f"file:{db_path}?mode=ro"
            return sqlite3.connect(uri, uri=True, timeout=10.0)
        return sqlite3.connect(db_path, timeout=10.0)

    def _init_audit_table(self):
        """Erstellt die manipulationssichere Tabelle für DSGVO-Löschquittungen."""
        if os.path.exists(self.memory_db):
            try:
                with sqlite3.connect(self.memory_db, timeout=5.0, factory=_ArchonClosingConn) as conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS gdpr_audit_log (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            receipt_id TEXT UNIQUE NOT NULL,
                            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            action TEXT NOT NULL,
                            identifier_hash TEXT NOT NULL,
                            records_affected INTEGER NOT NULL,
                            details_json TEXT,
                            prev_hash TEXT,
                            hash TEXT NOT NULL
                        )
                    """)
                    conn.commit()
            except Exception as e:
                print(f"[GDPR] Audit-Tabellen-Initialisierung fehlgeschlagen: {e}", file=sys.stderr)

    def export_subject_data(self, identifier: str, max_messages: Optional[int] = None) -> Dict[str, Any]:
        """Art. 15 DSGVO: Erstellt einen vollständigen Datenauszug für eine Person (E-Mail, Name, Telefon)."""
        term = identifier.strip()
        if not term or len(term) < 3:
            raise ValueError("Suchbegriff muss mindestens 3 Zeichen lang sein.")

        now_iso = datetime.datetime.now().isoformat()
        export = {
            "requested_identifier": term,
            "export_timestamp": now_iso,
            "legal_basis": "Art. 15 DSGVO (Auskunftsrecht)",
            "is_truncated": False,
            "sources": {
                "kanban_tasks": [],
                "chat_messages": [],
                "memory_learnings": [],
                "feedback_and_evals": [],
                "crm_contacts": [],
                "obsidian_notes": []
            },
            "total_records_found": 0
        }

        # 1. Kanban Tasks (kanban.db)
        if os.path.exists(self.kanban_db):
            try:
                with self._get_conn(self.kanban_db, readonly=True) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT id, title, body, assignee, status, created_at, result
                        FROM tasks
                        WHERE title LIKE ? OR body LIKE ? OR result LIKE ?
                    """, (f"%{term}%", f"%{term}%", f"%{term}%"))
                    for r in cur.fetchall():
                        export["sources"]["kanban_tasks"].append(dict(r))
            except Exception as e:
                export["sources"]["kanban_tasks_error"] = str(e)

        # 2. Chat-Nachrichten (state.db) — standardmäßig paginierter Voll-Export (Art. 15 DSGVO)
        if os.path.exists(self.state_db):
            try:
                with self._get_conn(self.state_db, readonly=True) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    msgs: List[Dict[str, Any]] = []
                    truncated = False
                    if max_messages is not None and max_messages > 0:
                        cur.execute("SELECT COUNT(*) FROM messages WHERE content LIKE ?", (f"%{term}%",))
                        total_count = int(cur.fetchone()[0])
                        cur.execute("""
                            SELECT id, session_id, role, content, timestamp
                            FROM messages
                            WHERE content LIKE ?
                            ORDER BY id ASC
                            LIMIT ?
                        """, (f"%{term}%", int(max_messages)))
                        msgs = [dict(r) for r in cur.fetchall()]
                        truncated = total_count > len(msgs)
                    else:
                        page_size = 500
                        offset = 0
                        while True:
                            cur.execute("""
                                SELECT id, session_id, role, content, timestamp
                                FROM messages
                                WHERE content LIKE ?
                                ORDER BY id ASC
                                LIMIT ? OFFSET ?
                            """, (f"%{term}%", page_size, offset))
                            chunk = [dict(r) for r in cur.fetchall()]
                            if not chunk:
                                break
                            msgs.extend(chunk)
                            if len(chunk) < page_size:
                                break
                            offset += page_size
                        total_count = len(msgs)
                    export["sources"]["chat_messages"] = msgs
                    export["sources"]["chat_messages_truncated"] = truncated
                    export["sources"]["chat_messages_total_count"] = total_count
                    if truncated:
                        export["is_truncated"] = True
            except Exception as e:
                export["sources"]["chat_messages_error"] = str(e)

        # 3. Langzeitgedächtnis (agentic_memory.db)
        if os.path.exists(self.memory_db):
            try:
                with self._get_conn(self.memory_db, readonly=True) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    # learnings
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='learnings'")
                    if cur.fetchone():
                        cur.execute("SELECT * FROM learnings WHERE summary LIKE ?", (f"%{term}%",))
                        for r in cur.fetchall():
                            export["sources"]["memory_learnings"].append(dict(r))

                    # human_feedback
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='human_feedback'")
                    if cur.fetchone():
                        cur.execute("SELECT * FROM human_feedback WHERE comment LIKE ? OR corrected_text LIKE ? OR task_prompt LIKE ?", (f"%{term}%", f"%{term}%", f"%{term}%"))
                        for r in cur.fetchall():
                            export["sources"]["feedback_and_evals"].append(dict(r))
            except Exception as e:
                export["sources"]["memory_error"] = str(e)

        # 4. PocketBase CRM Kontakte (nur aktiv, wenn explizit POCKETBASE_ENABLED=true)
        if os.getenv("POCKETBASE_ENABLED", "false").strip().lower() in ("1", "true", "yes"):
            pb_urls = [os.getenv("POCKETBASE_URL", "http://pocketbase:8090"), "http://127.0.0.1:8090"]
            for pb in pb_urls:
                try:
                    filter_q = urllib.parse.quote(f'name ~ "{term}" || email ~ "{term}" || firma ~ "{term}"')
                    url = f"{pb.rstrip('/')}/api/collections/kontakte/records?filter={filter_q}"
                    req = urllib.request.Request(url, headers={"User-Agent": "ArchonGDPR/1.0"})
                    with urllib.request.urlopen(req, timeout=1.0) as resp:
                        if resp.status == 200:
                            data = json.loads(resp.read().decode("utf-8"))
                            export["sources"]["crm_contacts"] = data.get("items", [])
                            break
                except Exception:
                    continue

        # 5. Obsidian Vault Notizen
        if os.path.exists(self.obsidian_dir):
            try:
                target_subdirs = {"00_HR_Agenten", "Bewerbung", "Bewerbungen", "01_PROJEKTE", "Kontakte"}
                opened = 0
                for root, dirs, files in os.walk(self.obsidian_dir):
                    dirs[:] = [d for d in dirs if not d.startswith(".") and d not in (
                        "node_modules", ".git", "AgenticOS-2026", "__pycache__", ".venv", ".pytest_cache", "attachments", "Archiv", "02_Wissensbibliothek"
                    )]
                    rel = os.path.relpath(root, self.obsidian_dir)
                    top = rel.split(os.sep)[0]
                    is_relevant_dir = (rel == ".") or (top in target_subdirs)

                    for f in files:
                        if f.endswith(".md"):
                            fpath = os.path.join(root, f)
                            if term.lower() in f.lower():
                                export["sources"]["obsidian_notes"].append({
                                    "file": f,
                                    "path": fpath,
                                    "size_bytes": os.path.getsize(fpath),
                                    "match_type": "filename"
                                })
                                continue

                            if is_relevant_dir and opened < 150:
                                opened += 1
                                try:
                                    with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                                        if term.lower() in fh.read().lower():
                                            export["sources"]["obsidian_notes"].append({
                                                "file": f,
                                                "path": fpath,
                                                "size_bytes": os.path.getsize(fpath),
                                                "match_type": "content"
                                            })
                                except Exception:
                                    pass
            except Exception as e:
                export["sources"]["obsidian_error"] = str(e)

        total = sum(len(v) for k, v in export["sources"].items() if isinstance(v, list))
        # R-33: Gesamtanzahl beruecksichtigt ungedeckelte Zaehler
        if export.get("is_truncated") and "chat_messages_total_count" in export["sources"]:
            total = total - len(export["sources"]["chat_messages"]) + export["sources"]["chat_messages_total_count"]
        export["total_records_found"] = total
        return export

    def erase_subject_data(self, identifier: str, dry_run: bool = False, anonymize: bool = True) -> Dict[str, Any]:
        """Art. 17 DSGVO: Löscht oder anonymisiert alle Daten zu einer Person und erstellt eine Hash-Löschquittung."""
        term = identifier.strip()
        if not term or len(term) < 3:
            raise ValueError("Suchbegriff muss mindestens 3 Zeichen lang sein.")

        replacement = "[ANONYMISIERT_DSGVO_ART17]" if anonymize else ""
        errors = []
        results = {
            "requested_identifier": term,
            "dry_run": dry_run,
            "mode": "anonymize" if anonymize else "purge",
            "timestamp": datetime.datetime.now().isoformat(),
            "affected": {
                "kanban_tasks": 0,
                "chat_messages": 0,
                "memory_conversations": 0,
                "memory_learnings": 0,
                "feedback_entries": 0,
                "crm_contacts": 0,
                "tenant_records": 0,
            },
            "total_affected": 0,
            "receipt": None
        }

        term_re = re.compile(re.escape(term), re.IGNORECASE)

        def _redact_ci(val: Optional[str]) -> str:
            return term_re.sub(replacement, val or "")

        # 1. Kanban Tasks
        if os.path.exists(self.kanban_db):
            try:
                with self._get_conn(self.kanban_db, readonly=dry_run) as conn:
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT id, title, body, result FROM tasks
                        WHERE title LIKE ? OR body LIKE ? OR result LIKE ?
                    """, (f"%{term}%", f"%{term}%", f"%{term}%"))
                    rows = cur.fetchall()
                    results["affected"]["kanban_tasks"] = len(rows)

                    if not dry_run and rows:
                        for tid, t_title, t_body, t_res in rows:
                            cur.execute("""
                                UPDATE tasks SET title = ?, body = ?, result = ?
                                WHERE id = ?
                            """, (_redact_ci(t_title), _redact_ci(t_body), _redact_ci(t_res), tid))
                        conn.commit()
            except Exception as e:
                print(f"[GDPR] Fehler bei Kanban-Löschung: {e}", file=sys.stderr)
                errors.append(f"Kanban: {e}")

        # 2. Chat Nachrichten (state.db)
        if os.path.exists(self.state_db):
            try:
                with self._get_conn(self.state_db, readonly=dry_run) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT id, content FROM messages WHERE content LIKE ?", (f"%{term}%",))
                    rows = cur.fetchall()
                    results["affected"]["chat_messages"] = len(rows)

                    if not dry_run and rows:
                        for mid, cont in rows:
                            cur.execute("UPDATE messages SET content = ? WHERE id = ?", (_redact_ci(cont), mid))
                        conn.commit()
            except Exception as e:
                print(f"[GDPR] Fehler bei Chat-Löschung: {e}", file=sys.stderr)
                errors.append(f"Chat: {e}")

        # 3. Langzeitgedächtnis (agentic_memory.db)
        if os.path.exists(self.memory_db):
            try:
                with self._get_conn(self.memory_db, readonly=dry_run) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='learnings'")
                    if cur.fetchone():
                        cur.execute("SELECT id, summary FROM learnings WHERE summary LIKE ?", (f"%{term}%",))
                        l_rows = cur.fetchall()
                        results["affected"]["memory_learnings"] = len(l_rows)
                        if not dry_run and l_rows:
                            for lid, s in l_rows:
                                cur.execute("UPDATE learnings SET summary = ? WHERE id = ?",
                                            (_redact_ci(s), lid))

                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='conversations'")
                    if cur.fetchone():
                        cur.execute("SELECT id, content FROM conversations WHERE content LIKE ?", (f"%{term}%",))
                        c_rows = cur.fetchall()
                        results["affected"]["memory_conversations"] = len(c_rows)
                        if not dry_run and c_rows:
                            for cid, cont in c_rows:
                                cur.execute("UPDATE conversations SET content = ? WHERE id = ?", (_redact_ci(cont), cid))

                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='human_feedback'")
                    if cur.fetchone():
                        cur.execute("SELECT id, comment, corrected_text FROM human_feedback WHERE comment LIKE ? OR corrected_text LIKE ?", (f"%{term}%", f"%{term}%"))
                        f_rows = cur.fetchall()
                        results["affected"]["feedback_entries"] = len(f_rows)
                        if not dry_run and f_rows:
                            for fid, c, cr in f_rows:
                                cur.execute("UPDATE human_feedback SET comment = ?, corrected_text = ? WHERE id = ?",
                                            (_redact_ci(c), _redact_ci(cr), fid))
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='email_drafts'")
                    if cur.fetchone():
                        cur.execute("SELECT draft_id, subject, recipient, body_text FROM email_drafts WHERE recipient LIKE ? OR subject LIKE ? OR body_text LIKE ?", (f"%{term}%", f"%{term}%", f"%{term}%"))
                        ed_rows = cur.fetchall()
                        results["affected"]["email_drafts"] = len(ed_rows)
                        if not dry_run and ed_rows:
                            for did, subj, recp, btxt in ed_rows:
                                cur.execute("UPDATE email_drafts SET subject = ?, recipient = ?, body_text = ? WHERE draft_id = ?",
                                            (_redact_ci(subj), _redact_ci(recp), _redact_ci(btxt), did))

                    if not dry_run:
                        conn.commit()
            except Exception as e:
                print(f"[GDPR] Fehler bei Memory-Löschung: {e}", file=sys.stderr)
                errors.append(f"Memory: {e}")

        # 3b. Multi-Tenant-DBs (ERP, Contracts, Deals, CRM unter data/tenants/*) mit GoBD-Sperrprüfung (Art. 18 DSGVO / § 147 AO)
        import glob
        tenants_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "tenants")
        tenant_db_files = sorted(glob.glob(os.path.join(tenants_root, "*", "*.db")))
        tenant_targets = {
            "crm_contacts": ["full_name", "email", "phone", "mobile", "notes"],
            "crm_entities": ["display_name", "billing_email", "phone", "notes"],
            "crm_interactions": ["subject", "summary", "author"],
            "contracts": ["title", "partner_name", "notes"],
            "deals": ["title", "partner", "notes"],
        }
        like_pat = f"%{term}%"
        for tdb in tenant_db_files:
            try:
                with self._get_conn(tdb, readonly=dry_run) as conn:
                    cur = conn.cursor()
                    protected_entity_ids = set()
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='erp_documents'")
                    if cur.fetchone():
                        for erp_row in cur.execute(
                            "SELECT DISTINCT entity_id FROM erp_documents WHERE status IN ('booked', 'paid') AND entity_id IS NOT NULL"
                        ).fetchall():
                            if erp_row[0]:
                                protected_entity_ids.add(str(erp_row[0]))

                    for tbl, cols in tenant_targets.items():
                        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,))
                        if not cur.fetchone():
                            continue
                        cur.execute(f"PRAGMA table_info({tbl})")
                        avail = {r[1] for r in cur.fetchall()}
                        use_cols = [c for c in cols if c in avail]
                        if not use_cols or "id" not in avail:
                            continue
                        where_sql = " OR ".join(f"{c} LIKE ?" for c in use_cols)
                        sel_sql = f"SELECT id, {', '.join(use_cols)} FROM {tbl} WHERE {where_sql}"
                        t_rows = cur.execute(sel_sql, [like_pat] * len(use_cols)).fetchall()
                        for row in t_rows:
                            rid = str(row[0])
                            # Art. 17 Abs. 3 lit. b i.V.m. Art. 18 DSGVO: Geschäftspartner mit festgeschriebenen Buchungsbelegen (§ 147 AO / 8J) sperren statt vernichten
                            if tbl == "crm_entities" and rid in protected_entity_ids:
                                results["affected"]["legal_hold_restricted"] = results["affected"].get("legal_hold_restricted", 0) + 1
                                if not dry_run and "notes" in avail:
                                    cur.execute(
                                        "UPDATE crm_entities SET notes = ? WHERE id = ?",
                                        ("[DSGVO Art. 18 Sperre: Aufbewahrungspflicht gem. § 147 AO / § 257 HGB (8 Jahre)]", rid),
                                    )
                                continue
                            results["affected"]["tenant_records"] += 1
                            if not dry_run:
                                set_sql = ", ".join(f"{c} = ?" for c in use_cols)
                                upd_sql = f"UPDATE {tbl} SET {set_sql} WHERE id = ?"
                                vals = [_redact_ci(row[idx + 1]) for idx in range(len(use_cols))]
                                cur.execute(upd_sql, vals + [rid])
                    if not dry_run:
                        conn.commit()
            except Exception as e:
                print(f"[GDPR] Fehler bei Tenant-DB {os.path.basename(tdb)}: {e}", file=sys.stderr)
                errors.append(f"Tenant({os.path.basename(tdb)}): {e}")

        if errors:
            results["errors"] = errors
            results["status"] = "failed"
            results["receipt"] = None
            raise RuntimeError(f"DSGVO Art. 17 Löschung unvollständig, Fehler in Stores: {', '.join(errors)}")

        total = sum(results["affected"].values())
        results["total_affected"] = total

        # 4. Audit-Log Quittung erstellen
        if not dry_run:
            receipt = self._write_audit_receipt(term, total, results["affected"], results["mode"])
            results["receipt"] = receipt

            # NotificationHub informieren
            try:
                from backend.notification_hub import get_notification_hub
                get_notification_hub().dispatch_notification(
                    title="DSGVO-Löschung ausgeführt",
                    message=f"Art. 17 DSGVO Löschung/Anonymisierung für Hash '{receipt['identifier_hash'][:12]}...': {total} Datensätze bereinigt. Quittung: {receipt['receipt_id']}",
                    severity="WARNING",
                    category="gdpr_compliance"
                )
            except Exception:
                pass
        else:
            results["receipt"] = {
                "receipt_id": "DRY-RUN-PREVIEW",
                "action": "dry_run_simulation",
                "identifier_hash": hashlib.sha256(term.encode("utf-8")).hexdigest(),
                "records_affected": total,
                "receipt_hash": "SIMULATION_NO_CHANGES_COMMITTED"
            }

        return results

    def _write_audit_receipt(self, term: str, count: int, breakdown: Dict[str, int], mode: str) -> Dict[str, Any]:
        """Schreibt eine kryptografische Löschquittung (ohne das gelöschte PII selbst zu speichern!)."""
        import uuid
        receipt_id = f"gdpr-rcpt-{uuid.uuid4().hex[:8]}"
        id_hash = hashlib.sha256(term.lower().encode("utf-8")).hexdigest()
        now_iso = datetime.datetime.now().isoformat()
        details_str = json.dumps({"mode": mode, "breakdown": breakdown})

        prev_hash = "GENESIS"
        with self._get_conn(self.memory_db) as conn:
            cur = conn.cursor()
            cur.execute("SELECT hash FROM gdpr_audit_log ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                prev_hash = row[0]

            record_payload = f"{receipt_id}|ERASE_ART17|{now_iso}|{id_hash}|{count}|{details_str}|{prev_hash}"
            record_hash = hashlib.sha256(record_payload.encode("utf-8")).hexdigest()

            cur.execute("""
                INSERT INTO gdpr_audit_log (receipt_id, action, identifier_hash, records_affected, details_json, prev_hash, hash)
                VALUES (?, 'ERASE_ART17', ?, ?, ?, ?, ?)
            """, (receipt_id, id_hash, count, details_str, prev_hash, record_hash))
            conn.commit()

        return {
            "receipt_id": receipt_id,
            "timestamp": now_iso,
            "identifier_hash": id_hash,
            "records_affected": count,
            "tamper_proof_hash": record_hash,
            "previous_receipt_hash": prev_hash
        }

    def list_audit_receipts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Gibt die gespeicherten DSGVO-Löschquittungen zurück."""
        if not os.path.exists(self.memory_db):
            return []
        with self._get_conn(self.memory_db, readonly=True) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM gdpr_audit_log ORDER BY id DESC LIMIT ?", (limit,))
            rows = []
            for r in cur.fetchall():
                d = dict(r)
                try:
                    d["details"] = json.loads(d["details_json"])
                except Exception:
                    d["details"] = {}
                rows.append(d)
            return rows


gdpr_engine = GDPRComplianceEngine()
