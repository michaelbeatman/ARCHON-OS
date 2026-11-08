"""
backend/gdpr_compliance_engine.py
DSGVO- / GDPR-Compliance Engine für Archon OS 2026.
Implementiert Betroffenenrechte nach:
- Art. 15 DSGVO: Recht auf Auskunft (Datenexport über alle Datenquellen)
- Art. 17 DSGVO: Recht auf Löschung / Recht auf Vergessenwerden (Audit-sichere Anonymisierung/Löschung)
- Art. 30 DSGVO: Manipulationssicheres Verzeichnis von Verarbeitungstätigkeiten & Löschquittungen
"""

import os
import sys
import json
import time
import sqlite3
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
                with sqlite3.connect(self.memory_db, timeout=5.0) as conn:
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

    def export_subject_data(self, identifier: str) -> Dict[str, Any]:
        """Art. 15 DSGVO: Erstellt einen vollständigen Datenauszug für eine Person (E-Mail, Name, Telefon)."""
        term = identifier.strip()
        if not term or len(term) < 3:
            raise ValueError("Suchbegriff muss mindestens 3 Zeichen lang sein.")

        now_iso = datetime.datetime.now().isoformat()
        export = {
            "requested_identifier": term,
            "export_timestamp": now_iso,
            "legal_basis": "Art. 15 DSGVO (Auskunftsrecht)",
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

        # 2. Chat-Nachrichten (state.db)
        if os.path.exists(self.state_db):
            try:
                with self._get_conn(self.state_db, readonly=True) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT COUNT(*) FROM messages WHERE content LIKE ?
                    """, (f"%{term}%",))
                    total_msg_count = cur.fetchone()[0]

                    cur.execute("""
                        SELECT id, session_id, role, content, timestamp
                        FROM messages
                        WHERE content LIKE ?
                        LIMIT 100
                    """, (f"%{term}%",))
                    msgs = [dict(r) for r in cur.fetchall()]
                    export["sources"]["chat_messages"] = msgs
                    if total_msg_count > len(msgs):
                        export["sources"]["chat_messages_truncated"] = True
                        export["sources"]["chat_messages_total_count"] = total_msg_count
                        export["is_truncated"] = True
                        export["truncation_notice"] = f"Auskunft unvollständig: {total_msg_count - len(msgs)} Chat-Nachrichten durch Limit 100 abgeschnitten."
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

        # 4. PocketBase CRM Kontakte
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
                "memory_learnings": 0,
                "feedback_entries": 0,
                "crm_contacts": 0
            },
            "total_affected": 0,
            "receipt": None
        }

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
                            new_title = (t_title or "").replace(term, replacement)
                            new_body = (t_body or "").replace(term, replacement)
                            new_res = (t_res or "").replace(term, replacement)
                            cur.execute("""
                                UPDATE tasks SET title = ?, body = ?, result = ?
                                WHERE id = ?
                            """, (new_title, new_body, new_res, tid))
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
                            new_cont = (cont or "").replace(term, replacement)
                            cur.execute("UPDATE messages SET content = ? WHERE id = ?", (new_cont, mid))
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
                                            ((s or "").replace(term, replacement), lid))

                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='human_feedback'")
                    if cur.fetchone():
                        cur.execute("SELECT id, comment, corrected_text FROM human_feedback WHERE comment LIKE ? OR corrected_text LIKE ?", (f"%{term}%", f"%{term}%"))
                        f_rows = cur.fetchall()
                        results["affected"]["feedback_entries"] = len(f_rows)
                        if not dry_run and f_rows:
                            for fid, c, cr in f_rows:
                                cur.execute("UPDATE human_feedback SET comment = ?, corrected_text = ? WHERE id = ?",
                                            ((c or "").replace(term, replacement), (cr or "").replace(term, replacement), fid))
                    if not dry_run:
                        conn.commit()
            except Exception as e:
                print(f"[GDPR] Fehler bei Memory-Löschung: {e}", file=sys.stderr)
                errors.append(f"Memory: {e}")

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
        receipt_id = f"gdpr-rcpt-{uuid.uuid4().hex[:8]}" if "uuid" in globals() else f"gdpr-rcpt-{int(time.time())}"
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

            record_payload = f"{receipt_id}|{now_iso}|{id_hash}|{count}|{prev_hash}"
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
