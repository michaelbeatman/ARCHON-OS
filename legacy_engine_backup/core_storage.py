import os
import sqlite3
import datetime
import json
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

# --- Pydantic Datenmodell für das Agenten-Manifest ("SUBAGENT.md") ---
class AgentManifest(BaseModel):
    agent_id: str
    name: str
    base_model: str
    system_prompt: str
    mcp_tools: List[str] = Field(default_factory=list)
    privilege_group: str = "default"

    @classmethod
    def from_markdown(cls, file_path: str) -> "AgentManifest":
        """
        Hilfsfunktion zum Parsen eines Manifests aus einer Markdown-Datei mit YAML-Frontmatter.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Manifest-Datei {file_path} existiert nicht.")
            
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        # Simples YAML-Frontmatter-Parsing
        if not content.startswith("---"):
            raise ValueError("Manifest besitzt kein gültiges Frontmatter.")
            
        parts = content.split("---")
        if len(parts) < 3:
            raise ValueError("Ungültiges Frontmatter-Format.")
            
        frontmatter_lines = parts[1].strip().split("\n")
        data = {}
        for line in frontmatter_lines:
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                # Entferne eventuelle Anführungszeichen
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                # MCP-Tools Liste parsen
                if key == "mcp_tools":
                    # erwarte z.B. [tool1, tool2] oder simple Komma-Trennung
                    val_clean = val.strip("[]")
                    data[key] = [t.strip() for t in val_clean.split(",") if t.strip()]
                else:
                    data[key] = val
                    
        # System-Prompt aus dem Body übernehmen falls nicht im Frontmatter deklariert
        if "system_prompt" not in data:
            data["system_prompt"] = parts[2].strip()
            
        return cls(**data)


# --- Core Storage Engine (SQLite im WAL-Modus) ---
class CoreStorage:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()
        self._cleanup_stale_tasks()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        # WAL-Modus aktivieren
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_connection()
        try:
            # 1. Prozesstabelle: tasks
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending', 'in_progress', 'completed', 'failed', 'pending_approval', 'suspended')),
                    payload TEXT,
                    result TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # 2. Sitzungsverläufe: conversations
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    session_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)

            # 3. Extrahiertes Langzeitwissen: learnings
            conn.execute("""
                CREATE TABLE IF NOT EXISTS learnings (
                    knowledge_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source_hash TEXT,
                    extraction_date TEXT NOT NULL
                )
            """)

            # 4. Transiente Schlüssel-Wert-Paare: kv_store
            conn.execute("""
                CREATE TABLE IF NOT EXISTS kv_store (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # 5. Globale Präferenzen und Sicherheitsstufen: user_profile
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_profile (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def _cleanup_stale_tasks(self):
        """
        Automatische Recovery-Routine.
        Setzt alle hängenden Tasks mit Status 'in_progress' beim Systemstart auf 'failed'.
        """
        now_str = datetime.datetime.now().isoformat()
        conn = self._get_connection()
        try:
            aborted_result = json.dumps({"error": "Task aborted due to system restart / crash recovery."})
            cursor = conn.execute(
                "UPDATE tasks SET status = 'failed', result = ?, updated_at = ? WHERE status = 'in_progress'",
                (aborted_result, now_str)
            )
            count = cursor.rowcount
            conn.commit()
            if count > 0:
                print(f"[CoreStorage Recovery] Cleaned up {count} stale 'in_progress' tasks (status marked as 'failed').")
        finally:
            conn.close()

    # --- API Helper für Tasks ---
    def save_task(self, task_id: str, agent_id: str, status: str, payload: Optional[Dict] = None, result: Optional[Dict] = None) -> bool:
        now_str = datetime.datetime.now().isoformat()
        payload_str = json.dumps(payload) if payload is not None else None
        result_str = json.dumps(result) if result is not None else None

        conn = self._get_connection()
        try:
            conn.execute("""
                INSERT INTO tasks (task_id, agent_id, status, payload, result, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    status=excluded.status,
                    payload=COALESCE(excluded.payload, tasks.payload),
                    result=COALESCE(excluded.result, tasks.result),
                    updated_at=excluded.updated_at
            """, (task_id, agent_id, status, payload_str, result_str, now_str, now_str))
            conn.commit()
        finally:
            conn.close()
        return True

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row:
                res = dict(row)
                try:
                    res["payload"] = json.loads(res["payload"]) if res["payload"] else None
                except Exception:
                    pass
                try:
                    res["result"] = json.loads(res["result"]) if res["result"] else None
                except Exception:
                    pass
                return res
        finally:
            conn.close()
        return None

    # --- API Helper für Conversations ---
    def add_message(self, session_id: str, agent_id: str, role: str, content: str) -> bool:
        now_str = datetime.datetime.now().isoformat()
        conn = self._get_connection()
        try:
            conn.execute("""
                INSERT INTO conversations (session_id, agent_id, role, content, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (session_id, agent_id, role, content, now_str))
            conn.commit()
        finally:
            conn.close()
        return True

    def get_session_history(self, session_id: str) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            rows = conn.execute("SELECT * FROM conversations WHERE session_id = ? ORDER BY timestamp ASC", (session_id,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # --- API Helper für Learnings ---
    def save_learning(self, knowledge_id: str, agent_id: str, key: str, value: str, source_hash: Optional[str] = None) -> bool:
        now_str = datetime.datetime.now().isoformat()
        conn = self._get_connection()
        try:
            conn.execute("""
                INSERT INTO learnings (knowledge_id, agent_id, key, value, source_hash, extraction_date)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(knowledge_id) DO UPDATE SET
                    key=excluded.key,
                    value=excluded.value,
                    source_hash=COALESCE(excluded.source_hash, learnings.source_hash),
                    extraction_date=excluded.extraction_date
            """, (knowledge_id, agent_id, key, value, source_hash, now_str))
            conn.commit()
        finally:
            conn.close()
        return True

    # --- API Helper für KV Store ---
    def set_kv(self, key: str, value: Any) -> bool:
        now_str = datetime.datetime.now().isoformat()
        val_str = json.dumps(value)
        conn = self._get_connection()
        try:
            conn.execute("""
                INSERT INTO kv_store (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
            """, (key, val_str, now_str))
            conn.commit()
        finally:
            conn.close()
        return True

    def get_kv(self, key: str) -> Optional[Any]:
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT value FROM kv_store WHERE key = ?", (key,)).fetchone()
            if row:
                return json.loads(row["value"])
        finally:
            conn.close()
        return None

    # --- API Helper für User Profile ---
    def set_preference(self, key: str, value: str) -> bool:
        conn = self._get_connection()
        try:
            conn.execute("""
                INSERT INTO user_profile (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """, (key, value))
            conn.commit()
        finally:
            conn.close()
        return True

    def get_preference(self, key: str) -> Optional[str]:
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT value FROM user_profile WHERE key = ?", (key,)).fetchone()
            if row:
                return row["value"]
        finally:
            conn.close()
        return None
