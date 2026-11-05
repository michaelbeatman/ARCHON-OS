import os
import sys
import json
import sqlite3
import datetime
import time
import math
from typing import List, Dict, Optional, Any

class LocalMemoryBridge:
    def __init__(self, db_path=None, vault_path=None):
        if not vault_path:
            for candidate in [
                os.environ.get("OBSIDIAN_VAULT_PATH"),
                "C:\\Mein Obsidian",
                "C:\\.Mein Obsidian",
                "/opt/data/obsidian",
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_workspace", "obsidian_vault")
            ]:
                if candidate and os.path.exists(candidate):
                    vault_path = candidate
                    break
        self.vault_path = vault_path or "C:\\Mein Obsidian"

        if not db_path:
            workspace_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "agentic_memory.db")
            user_hermes = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), ".hermes", "agentic_memory.db")
            for cand in [
                os.environ.get("AGENTIC_MEMORY_DB"),
                workspace_db,
                "/opt/data/agentic_memory.db",
                user_hermes,
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "agentic_memory.db"),
            ]:
                if cand and os.path.exists(cand):
                    try:
                        test_conn = sqlite3.connect(cand, timeout=1.0)
                        test_conn.execute("SELECT 1;")
                        test_conn.close()
                        db_path = cand
                        break
                    except Exception:
                        continue
            if not db_path:
                base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
                os.makedirs(base_dir, exist_ok=True)
                db_path = os.path.join(base_dir, "agentic_memory.db")
        self.db_path = db_path

        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            # Kein WAL auf Docker Windows Bind-Mounts (/opt/data), auf Host-SSD jedoch WAL für parallele Zugriffe
            if str(self.db_path).replace("\\", "/").startswith("/opt/data"):
                conn.execute("PRAGMA journal_mode=DELETE;")
            else:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=NORMAL;")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS user_profile (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS learnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    obsidian_link TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS kv_store (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT,
                    obsidian_note TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    finished_at TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    agent_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- Pillar 6: Manipulationssicheres Audit-Log mit kryptografischer Hash-Kette
                                -- Pillar 4: Unterbrechbare Langzeit-Workflows mit State-Snapshotting
                CREATE TABLE IF NOT EXISTS workflow_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    current_step INTEGER NOT NULL,
                    total_steps INTEGER NOT NULL,
                    state_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    pause_reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    hash TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Ensure adaptive memory columns exist in conversations & learnings
            try:
                cur = conn.cursor()
                conv_cols = [c[1] for c in cur.execute("PRAGMA table_info(conversations)").fetchall()]
                if "session_id" not in conv_cols:
                    cur.execute("ALTER TABLE conversations ADD COLUMN session_id TEXT")
                if "importance" not in conv_cols:
                    cur.execute("ALTER TABLE conversations ADD COLUMN importance REAL DEFAULT 1.0")
                if "accesses" not in conv_cols:
                    cur.execute("ALTER TABLE conversations ADD COLUMN accesses INTEGER DEFAULT 1")
                if "last_accessed" not in conv_cols:
                    cur.execute("ALTER TABLE conversations ADD COLUMN last_accessed TIMESTAMP")
                    cur.execute("UPDATE conversations SET last_accessed = timestamp WHERE last_accessed IS NULL")

                learn_cols = [c[1] for c in cur.execute("PRAGMA table_info(learnings)").fetchall()]
                if "importance" not in learn_cols:
                    cur.execute("ALTER TABLE learnings ADD COLUMN importance REAL DEFAULT 1.0")
                if "accesses" not in learn_cols:
                    cur.execute("ALTER TABLE learnings ADD COLUMN accesses INTEGER DEFAULT 1")
                if "last_accessed" not in learn_cols:
                    cur.execute("ALTER TABLE learnings ADD COLUMN last_accessed TIMESTAMP")
                    cur.execute("UPDATE learnings SET last_accessed = created_at WHERE last_accessed IS NULL")
                conn.commit()
            except Exception as e:
                print(f"[MemoryBridge] Migration notice: {e}", file=sys.stderr)

            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM user_profile")
            if cur.fetchone()[0] == 0:
                defaults = [
                    ("user_name", "Michael Keller"),
                    ("os_environment", "Windows 11 (Archon OS Runtime)"),
                    ("obsidian_vault", self.vault_path),
                    ("communication_style", "Praezise, faktenbasiert, aktiv, keine Floskeln"),
                    ("active_project", "Archon OS / AgenticOS 2026")
                ]
                conn.executemany("INSERT OR REPLACE INTO user_profile (key, value) VALUES (?, ?)", defaults)
                conn.commit()

    def get_user_profile(self):
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT key, value FROM user_profile")
            return {row["key"]: row["value"] for row in cur.fetchall()}

    def set_user_fact(self, key, value):
        with self._get_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO user_profile (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)", (key, value))
            conn.commit()

    def record_learning(self, agent_id, category, summary, detailed_note=None):
        obsidian_link = None
        if detailed_note and os.path.exists(self.vault_path):
            memories_dir = os.path.join(self.vault_path, "memories")
            os.makedirs(memories_dir, exist_ok=True)
            
            safe_title = summary[:50].replace(" ", "_").replace("/", "_").replace("\\", "_").replace(":", "_")
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            note_filename = f"learning_{safe_title}_{ts}.md"
            note_path = os.path.join(memories_dir, note_filename)

            md_content = f"""---
title: "{summary[:80]}"
agent: "{agent_id}"
category: "{category}"
date: {datetime.datetime.now().isoformat()}
tags: ["learning", "memory", "{agent_id}"]
---

# Learning: {summary}

**Agent:** `{agent_id}`  
**Kategorie:** `{category}`  
**Zeitpunkt:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Inhalt & Details
{detailed_note}

---
[[00_VAULT_KNOWLEDGE]] | [[Archiv-Hubs]]
"""
            try:
                with open(note_path, "w", encoding="utf-8") as f:
                    f.write(md_content)
                obsidian_link = f"[[{note_filename[:-3]}]]"
            except Exception as e:
                print(f"[MemoryBridge] Warning: Failed to write obsidian note: {e}", file=sys.stderr)

        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO learnings (agent_id, category, summary, obsidian_link)
                VALUES (?, ?, ?, ?)
            """, (agent_id, category, summary, obsidian_link))
            learning_id = cur.lastrowid
            conn.commit()

        return {
            "status": "success",
            "learning_id": learning_id,
            "obsidian_link": obsidian_link
        }

    def record_conversation(self, agent_id: str, role: str, content: str, session_id: Optional[str] = None):
        """Speichert einen Chat-Turn (user/assistant) persistent in agentic_memory.db."""
        if not content:
            return
        sess_id = session_id or f"quickchat_{agent_id}"
        with self._get_conn() as conn:
            try:
                conn.execute("""
                    INSERT INTO conversations (session_id, agent_id, role, content, timestamp)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (sess_id, agent_id, role, content))
                conn.commit()
            except sqlite3.OperationalError:
                # Fallback if session_id column does not exist
                conn.execute("""
                    INSERT INTO conversations (agent_id, role, content, timestamp)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                """, (agent_id, role, content))
                conn.commit()

    def get_conversation_history(self, agent_id: str, limit: int = 20, session_id: Optional[str] = None) -> List[Dict[str, str]]:
        """Holt die chronologische Chat-Historie fuer einen Agenten oder eine Session."""
        sess_id = session_id or f"quickchat_{agent_id}"
        with self._get_conn() as conn:
            cur = conn.cursor()
            rows = []
            try:
                cur.execute("""
                    SELECT role, content, timestamp FROM (
                        SELECT id, role, content, timestamp 
                        FROM conversations 
                        WHERE agent_id = ? OR session_id = ?
                        ORDER BY id DESC LIMIT ?
                    ) ORDER BY id ASC
                """, (agent_id, sess_id, limit))
                rows = cur.fetchall()
            except sqlite3.OperationalError:
                cur.execute("""
                    SELECT role, content, timestamp FROM (
                        SELECT id, role, content, timestamp 
                        FROM conversations 
                        WHERE agent_id = ?
                        ORDER BY id DESC LIMIT ?
                    ) ORDER BY id ASC
                """, (agent_id, limit))
                rows = cur.fetchall()
                
            return [{"role": r["role"], "content": r["content"], "timestamp": str(r["timestamp"])} for r in rows]

    def clear_conversation_history(self, agent_id: str, session_id: Optional[str] = None):
        """Loescht die Chat-Historie fuer einen Agenten."""
        sess_id = session_id or f"quickchat_{agent_id}"
        with self._get_conn() as conn:
            try:
                conn.execute("DELETE FROM conversations WHERE agent_id = ? OR session_id = ?", (agent_id, sess_id))
            except sqlite3.OperationalError:
                conn.execute("DELETE FROM conversations WHERE agent_id = ?", (agent_id,))
            conn.commit()

    def get_agent_context_injection(self, agent_id, limit=5):
        profile = self.get_user_profile()
        
        recent_learnings = self.search_learnings("", limit=limit)

        context_lines = [
            "### [SYSTEM MEMORY & USER CONTEXT]",
            f"- Benutzer: {profile.get('user_name', 'Michael Keller')}",
            f"- System: {profile.get('os_environment', 'Windows 11')}",
            f"- Obsidian Second Brain: `{self.vault_path}`",
            f"- Aktuelles Projekt: {profile.get('active_project', 'Archon OS')}"
        ]

        if recent_learnings:
            context_lines.append("\n### [ADAPTIVES GEDAECHTNIS & RELEVANTE ERKENNTNISSE]")
            for l in recent_learnings:
                link_str = f" ({l['obsidian_link']})" if l.get('obsidian_link') else ""
                score_str = f" [Score: {l.get('decayed_score', 1.0)}]" if 'decayed_score' in l else ""
                context_lines.append(f"- [{l['category']}] {l['summary']}{link_str}{score_str}")

        return "\n".join(context_lines)

    def scan_vault_summary(self):
        if not os.path.exists(self.vault_path):
            return {"status": "error", "message": f"Vault path {self.vault_path} not found"}

        notes_count = 0
        categories = {}
        for root, dirs, files in os.walk(self.vault_path):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                if f.endswith(".md"):
                    notes_count += 1
                    rel_dir = os.path.relpath(root, self.vault_path)
                    folder_name = rel_dir if rel_dir != "." else "Stammverzeichnis"
                    categories[folder_name] = categories.get(folder_name, 0) + 1

        return {
            "status": "success",
            "vault_path": self.vault_path,
            "total_notes": notes_count,
            "structure": categories
        }

    # =========================================================================
    # PILLAR 4: ADAPTIVE MEMORY, EXPONENTIAL DECAY & LRU-K EVICTION
    # =========================================================================

    @staticmethod
    def calculate_decay_score(importance: float, last_accessed_ts: Any, half_life_days: float = 14.0) -> float:
        """Berechnet exponentiellen Zerfall: score = importance * e^(-0.693 * days / half_life)."""
        import math, time
        if importance is None:
            importance = 1.0
        importance = float(importance)

        if not last_accessed_ts:
            return round(importance, 4)

        if isinstance(last_accessed_ts, (int, float)):
            ts = float(last_accessed_ts)
        else:
            try:
                s = str(last_accessed_ts).strip()
                if " " in s and "T" not in s:
                    s = s.replace(" ", "T")
                dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
                ts = dt.timestamp()
            except Exception:
                ts = time.time()

        days_since = max(0.0, (time.time() - ts) / 86400.0)
        return round(importance * math.exp(-0.693 * days_since / half_life_days), 4)

    def get_adaptive_context(self, agent_id: str, limit: int = 10, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Holt Chat-Nachrichten adaptiv bewertet nach Relevanz, Aktualitaet und Wichtigkeit.
        Aktualisiert 'accesses' und 'last_accessed' fuer gewaehlte Eintraege.
        """
        sess_id = session_id or f"quickchat_{agent_id}"
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute("""
                    SELECT id, role, content, timestamp, importance, accesses, last_accessed
                    FROM conversations
                    WHERE agent_id = ? OR session_id = ?
                    ORDER BY id DESC LIMIT 50
                """, (agent_id, sess_id))
            except sqlite3.OperationalError:
                cur.execute("""
                    SELECT id, role, content, timestamp, 1.0 as importance, 1 as accesses, timestamp as last_accessed
                    FROM conversations
                    WHERE agent_id = ?
                    ORDER BY id DESC LIMIT 50
                """, (agent_id,))

            rows = cur.fetchall()
            scored = []
            for r in rows:
                imp = r["importance"] if "importance" in r.keys() and r["importance"] is not None else 1.0
                last_acc = r["last_accessed"] if "last_accessed" in r.keys() and r["last_accessed"] is not None else r["timestamp"]
                decayed = self.calculate_decay_score(imp, last_acc)
                scored.append({
                    "id": r["id"],
                    "role": r["role"],
                    "content": r["content"],
                    "timestamp": str(r["timestamp"]),
                    "importance": imp,
                    "decayed_score": decayed
                })

            # Sortiere nach decayed_score absteigend und nimm Top-Limit
            scored.sort(key=lambda x: x["decayed_score"], reverse=True)
            top_items = scored[:limit]

            # In chronologischer Reihenfolge fuer LLM zurueckgeben
            top_items.sort(key=lambda x: x["id"])

            # Touch: Markiere die abgerufenen Items als genutzt
            if top_items:
                ids = [item["id"] for item in top_items]
                try:
                    cur.execute(f"""
                        UPDATE conversations 
                        SET accesses = accesses + 1, last_accessed = CURRENT_TIMESTAMP
                        WHERE id IN ({','.join(['?']*len(ids))})
                    """, ids)
                    conn.commit()
                except Exception:
                    pass

            return top_items

    def boost_memory(self, memory_id: int, table: str = "learnings", boost_amount: float = 0.5) -> Dict[str, Any]:
        """Erhoeht die Wichtigkeit eines Memory-Eintrags und setzt last_accessed neu."""
        if table not in ("learnings", "conversations"):
            return {"status": "error", "message": "Invalid table name"}

        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(f"SELECT importance FROM {table} WHERE id = ?", (memory_id,))
                row = cur.fetchone()
                if not row:
                    return {"status": "error", "message": f"Entry {memory_id} not found in {table}"}
                current_imp = row[0] if row[0] is not None else 1.0
                new_imp = min(5.0, current_imp + boost_amount)
                cur.execute(f"""
                    UPDATE {table}
                    SET importance = ?, accesses = accesses + 1, last_accessed = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (new_imp, memory_id))
                conn.commit()
                return {"status": "boosted", "id": memory_id, "new_importance": new_imp}
            except Exception as e:
                return {"status": "error", "message": str(e)}

    def evict_stale_memories(self, threshold: float = 0.1, table: str = "conversations", dry_run: bool = False) -> Dict[str, Any]:
        """
        Pillar 4 LRU-K / Decay Eviction:
        Findet Eintraege unterhalb der Relevanz-Schwelle und entfernt sie aus der aktiven DB.
        """
        time_col = "timestamp" if table == "conversations" else "created_at"
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(f"SELECT id, importance, last_accessed, {time_col} FROM {table}")
                rows = cur.fetchall()
            except Exception as e:
                return {"status": "error", "message": str(e)}

            stale_ids = []
            for r in rows:
                imp = r["importance"] if "importance" in r.keys() and r["importance"] is not None else 1.0
                last_acc = r["last_accessed"] if "last_accessed" in r.keys() and r["last_accessed"] is not None else r[time_col]
                decayed = self.calculate_decay_score(imp, last_acc)
                if decayed < threshold:
                    stale_ids.append(r["id"])

            if not dry_run and stale_ids:
                cur.execute(f"DELETE FROM {table} WHERE id IN ({','.join(['?']*len(stale_ids))})", stale_ids)
                conn.commit()

            return {
                "status": "success",
                "table": table,
                "threshold": threshold,
                "stale_count": len(stale_ids),
                "evicted_ids": stale_ids if dry_run else len(stale_ids),
                "dry_run": dry_run
            }

    def search_learnings(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Durchsucht die learnings-Tabelle nach Stichworten und rankt nach Relevanz & Decay-Score.
        """
        tokens = [t.strip().lower() for t in query.split() if len(t.strip()) > 2]
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute("""
                    SELECT id, agent_id, category, summary, obsidian_link, created_at,
                           importance, accesses, last_accessed
                    FROM learnings
                    ORDER BY id DESC LIMIT 100
                """)
                rows = cur.fetchall()
            except sqlite3.OperationalError:
                cur.execute("""
                    SELECT id, agent_id, category, summary, obsidian_link, created_at,
                           1.0 as importance, 1 as accesses, created_at as last_accessed
                    FROM learnings
                    ORDER BY id DESC LIMIT 100
                """)
                rows = cur.fetchall()

            scored = []
            for r in rows:
                text = f"{r['category']} {r['summary']} {r['obsidian_link'] or ''}".lower()
                match_count = sum(1 for tok in tokens if tok in text)
                if not tokens or match_count > 0:
                    imp = r["importance"] if "importance" in r.keys() and r["importance"] is not None else 1.0
                    last_acc = r["last_accessed"] if "last_accessed" in r.keys() and r["last_accessed"] is not None else r["created_at"]
                    decay = self.calculate_decay_score(imp, last_acc)
                    # Kombinierter Score: Text-Match-Dichte * Decay-Score
                    total_score = (match_count + 1) * decay
                    scored.append({
                        "id": r["id"],
                        "agent_id": r["agent_id"],
                        "category": r["category"],
                        "summary": r["summary"],
                        "obsidian_link": r["obsidian_link"],
                        "importance": imp,
                        "decayed_score": decay,
                        "match_score": total_score
                    })

            scored.sort(key=lambda x: x["match_score"], reverse=True)
            top = scored[:limit]

            # Touch: Markiere gefundene Learnings als aktiv abgerufen
            if top:
                top_ids = [t["id"] for t in top]
                try:
                    cur.execute(f"""
                        UPDATE learnings 
                        SET accesses = accesses + 1, last_accessed = CURRENT_TIMESTAMP
                        WHERE id IN ({','.join(['?']*len(top_ids))})
                    """, top_ids)
                    conn.commit()
                except Exception:
                    pass

            return top

    def log_audit_event(self, agent_id: str, action: str, payload: dict) -> dict:
        """
        Pillar 6 (Zero-Trust Governance): Delegiert an das zentrale revisionssichere
        GoBD/ISO 27001 Audit-Log (backend.audit_log.chained_audit_log).
        """
        from backend.audit_log import chained_audit_log
        res = chained_audit_log.record_event(category="operations", action=action, agent_id=agent_id, payload=payload)
        return {
            "status": "success",
            "hash": res["current_hash"],
            "prev_hash": res["prev_hash"],
            "timestamp": res["timestamp"]
        }

    def verify_audit_chain(self) -> dict:
        """
        Prueft die kryptografische Integritaet der gesamten Hash-Kette ueber chained_audit_log.
        """
        from backend.audit_log import chained_audit_log
        return chained_audit_log.verify_integrity()

    def sync_task(self, task_id: str, title: str, role: str, status: str, result: Optional[str] = None, obsidian_note: Optional[str] = None) -> dict:
        """
        Synchronisiert einen Task-Eintrag zwischen Operations-Kanban (kanban.db)
        und dem zentralen Agentengedächtnis (agentic_memory.db -> tasks).
        """
        now_iso = datetime.datetime.now().isoformat()
        finished_at = now_iso if str(status).lower() in ("done", "completed", "archived") else None
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, title, role, result, obsidian_note, created_at FROM tasks WHERE id = ?", (task_id,))
            existing = cur.fetchone()
            if existing:
                cur.execute("""
                    UPDATE tasks
                    SET title = COALESCE(?, title),
                        role = COALESCE(?, role),
                        status = ?,
                        result = COALESCE(?, result),
                        obsidian_note = COALESCE(?, obsidian_note),
                        finished_at = COALESCE(?, finished_at)
                    WHERE id = ?
                """, (
                    title or existing["title"],
                    role or existing["role"],
                    status,
                    result,
                    obsidian_note,
                    finished_at,
                    task_id
                ))
            else:
                cur.execute("""
                    INSERT INTO tasks (id, title, role, status, result, obsidian_note, created_at, finished_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    task_id,
                    title or task_id,
                    role or "unassigned",
                    status,
                    result,
                    obsidian_note,
                    now_iso,
                    finished_at
                ))
            conn.commit()
        return {"status": "synced", "task_id": task_id, "task_status": status}



    def deduplicate_and_record_learning(self, agent_id: str, category: str, summary: str, detailed_note: str = None, similarity_threshold: float = 0.85) -> Dict[str, Any]:
        """
        Pillar 4: Semantic Memory Deduplication
        Prüft vor dem Speichern, ob eine inhaltlich identische Lektion bereits existiert.
        Aktualisiert bestehende Lektionen statt Duplikate anzuhäufen.
        """
        import re
        def _get_words(t):
            return set(re.findall(r'\w+', str(t).lower()))

        new_words = _get_words(summary)
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, summary, obsidian_link FROM learnings ORDER BY id DESC LIMIT 50")
            existing = cur.fetchall()
            for row in existing:
                ex_words = _get_words(row["summary"])
                if new_words and ex_words:
                    overlap = len(new_words & ex_words) / len(new_words | ex_words)
                    if overlap >= similarity_threshold:
                        # Duplikat gefunden -> Timestamp auffrischen und zurückgeben
                        conn.execute("UPDATE learnings SET created_at = CURRENT_TIMESTAMP WHERE id = ?", (row["id"],))
                        conn.commit()
                        return {
                            "status": "deduplicated",
                            "message": f"Aehnliche Lerneinheit (ID {row['id']}, Uebereinstimmung {overlap*100:.0f}%) existiert bereits.",
                            "learning_id": row["id"],
                            "existing_summary": row["summary"]
                        }

        # Kein Duplikat gefunden -> regulär speichern
        res = self.record_learning(agent_id, category, summary, detailed_note)
        res["status"] = "created"
        return res

    def harvest_facts_and_preferences(self, text_corpus: str, agent_id: str = "orchestrator") -> Dict[str, Any]:
        """
        Pillar 4: Autonomes Fact-Harvesting & Memory Enrichment
        Extrahiert Fakten, Benutzerpräferenzen und Systemkonfigurationen
        aus Konversationen und aktualisiert user_profile und learnings automatisch.
        """
        import re
        extracted_facts = {}
        extracted_learnings = []

        # 1. Bekannte Schlüssel-Muster für Benutzer-Präferenzen
        patterns = [
            (r"(?:bevorzuge|nutze am liebsten|nutze bitte immer|standard[ -]?modell ist)\s+([a-zA-Z0-9_\-\./]+)", "preferred_model"),
            (r"(?:datenbank|db)[ -]modus\s+ist\s+([a-zA-Z0-9_\-]+)", "database_mode"),
            (r"(?:arbeite auf|betriebssystem ist|os ist)\s+([a-zA-Z0-9_\- ]+)", "os_environment"),
            (r"(?:stil|tonfall|kommunikation soll)\s+([a-zA-Z0-9_\- ,]+)\s+sein", "communication_style"),
            (r"(?:aktives projekt|fokus-projekt ist)\s+([a-zA-Z0-9_\- ]+)", "active_project")
        ]

        lower_text = text_corpus.lower()
        for pat, key in patterns:
            match = re.search(pat, lower_text)
            if match:
                val = match.group(1).strip()
                extracted_facts[key] = val
                self.set_user_fact(key, val)

        # 2. Extrahierte Beschlüsse als dedizierte Learnings erfassen
        decision_matches = re.findall(r"(?:beschluss|entscheidung|regel|architektur-entscheidung):\s*([^\n\.]+)", text_corpus, re.IGNORECASE)
        for dec in decision_matches:
            dec_clean = dec.strip()
            if len(dec_clean) > 10:
                rec = self.deduplicate_and_record_learning(
                    agent_id=agent_id,
                    category="System-Beschluss",
                    summary=f"Beschluss: {dec_clean[:80]}",
                    detailed_note=f"Automatisch extrahierter Beschluss aus Unterhaltung:\n{dec_clean}"
                )
                extracted_learnings.append(rec)

        return {
            "status": "success",
            "facts_updated": extracted_facts,
            "learnings_captured": len(extracted_learnings),
            "learnings": extracted_learnings
        }

    def save_workflow_checkpoint(self, checkpoint_id: str, workflow_id: str, agent_id: str, current_step: int, total_steps: int, state_data: dict, status: str = "running", pause_reason: str = None) -> bool:
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO workflow_checkpoints (checkpoint_id, workflow_id, agent_id, current_step, total_steps, state_json, status, pause_reason, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (checkpoint_id, workflow_id, agent_id, current_step, total_steps, json.dumps(state_data, ensure_ascii=False), status, pause_reason))
            conn.commit()
            return True

    def get_workflow_checkpoint(self, checkpoint_id: str) -> Optional[dict]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM workflow_checkpoints WHERE checkpoint_id = ?", (checkpoint_id,))
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            try:
                d["state"] = json.loads(d["state_json"])
            except Exception:
                d["state"] = {}
            return d

    def list_workflow_checkpoints(self, status: str = None, limit: int = 50) -> list:
        with self._get_conn() as conn:
            cur = conn.cursor()
            if status:
                cur.execute("SELECT * FROM workflow_checkpoints WHERE status = ? ORDER BY updated_at DESC LIMIT ?", (status, limit))
            else:
                cur.execute("SELECT * FROM workflow_checkpoints ORDER BY updated_at DESC LIMIT ?", (limit,))
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                try:
                    r["state"] = json.loads(r["state_json"])
                except Exception:
                    r["state"] = {}
            return rows


# Singleton Bridge-Instanz und Modul-Export-Helper
memory_bridge = LocalMemoryBridge()

def save_workflow_checkpoint(checkpoint_id: str, workflow_id: str = '', agent_id: str = '', current_step: int = 0, total_steps: int = 0, state_data: dict = None, status: str = 'running', pause_reason: str = None) -> bool:
    if state_data is None:
        state_data = {}
    return memory_bridge.save_workflow_checkpoint(checkpoint_id, workflow_id, agent_id, current_step, total_steps, state_data, status, pause_reason)

def get_workflow_checkpoint(checkpoint_id: str):
    return memory_bridge.get_workflow_checkpoint(checkpoint_id)

def list_workflow_checkpoints(status: str = None, limit: int = 50):
    return memory_bridge.list_workflow_checkpoints(status, limit)
