"""
backend/prompt_registry.py
Zentrale Prompt-Registry mit Versionierung, 1-Click Rollback,
Unified Diff und Canary-Rollout (Canary Testing) für alle Archon OS Agenten.
Ersetzt unstrukturierte .bak.N Dateien durch versionierte SQLite-Snapshots.
"""

import os
import sys
import json
import sqlite3
import difflib
import hashlib
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_FILE = os.path.join(WORKSPACE_DIR, "agent_profiles.json")


def _resolve_db_path() -> str:
    candidates = [
        "/opt/data/agentic_memory.db",
        os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db"),
        os.path.join(WORKSPACE_DIR, "agentic_memory.db"),
        os.path.expanduser("~/.hermes/agentic_memory.db")
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[1]


class PromptRegistry:
    """Verwaltet Prompt-Versionen, Rollbacks und Canary-Verteilungen."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or _resolve_db_path()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_db(self):
        """Erstellt die Tabelle prompt_versions und Indizes."""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS prompt_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    version_num INTEGER NOT NULL,
                    prompt TEXT NOT NULL,
                    model TEXT,
                    temperature REAL DEFAULT 0.7,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_by TEXT DEFAULT 'manual',
                    commit_message TEXT,
                    is_active INTEGER DEFAULT 0,
                    canary_percentage INTEGER DEFAULT 0,
                    performance_score REAL DEFAULT 0.0,
                    UNIQUE(agent_id, version_num)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_prompt_versions_agent ON prompt_versions(agent_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_prompt_versions_active ON prompt_versions(agent_id, is_active)")
            conn.commit()

    def _sync_profiles_json(self, agent_id: str, new_prompt: str, model: Optional[str] = None):
        """Aktualisiert synchron agent_profiles.json zur Rückwärtskompatibilität."""
        if not os.path.exists(PROFILES_FILE):
            return
        try:
            with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                profiles = json.load(f)
            updated = False
            for p in profiles:
                if p.get("id") == agent_id:
                    p["prompt"] = new_prompt
                    if model:
                        p["model"] = model
                    updated = True
                    break
            if updated:
                with open(PROFILES_FILE, "w", encoding="utf-8") as f:
                    json.dump(profiles, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[PromptRegistry] Fehler beim Abgleich mit agent_profiles.json: {e}", file=sys.stderr)

    def import_baseline_if_missing(self, agent_id: str) -> Optional[int]:
        """Importiert den aktuellen Prompt aus agent_profiles.json als v1, falls noch kein Eintrag vorliegt."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM prompt_versions WHERE agent_id = ?", (agent_id,))
            if cur.fetchone()[0] > 0:
                return None

        # Aus agent_profiles.json laden
        if os.path.exists(PROFILES_FILE):
            try:
                with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                    profiles = json.load(f)
                for p in profiles:
                    if p.get("id") == agent_id:
                        prompt_text = p.get("prompt") or ""
                        model = p.get("model")
                        res = self.save_version(
                            agent_id=agent_id,
                            prompt=prompt_text,
                            commit_message="Initialer Baseline-Import aus agent_profiles.json",
                            created_by="system_baseline",
                            model=model,
                            make_active=True
                        )
                        return res["version_num"]
            except Exception as e:
                print(f"[PromptRegistry] Baseline-Import fehlgeschlagen: {e}", file=sys.stderr)
        return None

    def save_version(
        self,
        agent_id: str,
        prompt: str,
        commit_message: str = "",
        created_by: str = "manual",
        model: Optional[str] = None,
        make_active: bool = True,
        canary_percentage: int = 0
    ) -> Dict[str, Any]:
        """Speichert eine neue Prompt-Version und schaltet diese optional als aktiv."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COALESCE(MAX(version_num), 0) FROM prompt_versions WHERE agent_id = ?", (agent_id,))
            next_v = cur.fetchone()[0] + 1

            if make_active:
                # Bisherige aktive Versionen für diesen Agenten deaktivieren
                cur.execute("UPDATE prompt_versions SET is_active = 0 WHERE agent_id = ?", (agent_id,))

            cur.execute("""
                INSERT INTO prompt_versions (
                    agent_id, version_num, prompt, model, created_by,
                    commit_message, is_active, canary_percentage
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                agent_id, next_v, prompt, model, created_by,
                commit_message or f"Version {next_v}",
                1 if make_active else 0,
                canary_percentage
            ))
            conn.commit()

        if make_active:
            self._sync_profiles_json(agent_id, prompt, model)

        return {
            "status": "success",
            "agent_id": agent_id,
            "version_num": next_v,
            "is_active": make_active,
            "canary_percentage": canary_percentage
        }

    def list_versions(self, agent_id: str) -> List[Dict[str, Any]]:
        """Listet alle Prompt-Versionen eines Agenten auf."""
        self.import_baseline_if_missing(agent_id)
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, agent_id, version_num, model, created_at, created_by,
                       commit_message, is_active, canary_percentage, performance_score,
                       LENGTH(prompt) as prompt_length
                FROM prompt_versions
                WHERE agent_id = ?
                ORDER BY version_num DESC
            """, (agent_id,))
            return [dict(r) for r in cur.fetchall()]

    def get_version(self, agent_id: str, version_num: int) -> Optional[Dict[str, Any]]:
        """Liefert eine spezifische Version eines Agenten-Prompts."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM prompt_versions
                WHERE agent_id = ? AND version_num = ?
            """, (agent_id, version_num))
            row = cur.fetchone()
            return dict(row) if row else None

    def rollback_to_version(self, agent_id: str, target_version_num: int, reason: str = "Rollback") -> Dict[str, Any]:
        """Führt einen 1-Click-Rollback auf eine frühere Version durch und stoppt alle Canaries."""
        target = self.get_version(agent_id, target_version_num)
        if not target:
            raise ValueError(f"Version {target_version_num} für Agent {agent_id} nicht gefunden.")

        # Bestehende Canaries für diesen Agenten sofort stoppen
        with self._get_conn() as conn:
            conn.execute("UPDATE prompt_versions SET canary_percentage = 0 WHERE agent_id = ?", (agent_id,))
            conn.commit()

        # Neue Version anlegen, die den Stand der Zielversion spiegelt
        msg = f"Rollback auf v{target_version_num}: {reason}"
        res = self.save_version(
            agent_id=agent_id,
            prompt=target["prompt"],
            commit_message=msg,
            created_by="rollback_action",
            model=target.get("model"),
            make_active=True,
            canary_percentage=0
        )
        return {
            "status": "success",
            "action": "rollback",
            "agent_id": agent_id,
            "reverted_from_version": target_version_num,
            "new_active_version": res["version_num"]
        }

    def diff_versions(self, agent_id: str, v1: int, v2: int) -> str:
        """Erzeugt ein Unified Diff zwischen zwei Prompt-Versionen."""
        ver1 = self.get_version(agent_id, v1)
        ver2 = self.get_version(agent_id, v2)
        if not ver1 or not ver2:
            return f"Fehler: Version v{v1} oder v{v2} für Agent '{agent_id}' existiert nicht."

        lines1 = ver1["prompt"].splitlines(keepends=True)
        lines2 = ver2["prompt"].splitlines(keepends=True)

        diff = difflib.unified_diff(
            lines1,
            lines2,
            fromfile=f"{agent_id}_v{v1}",
            tofile=f"{agent_id}_v{v2}",
            lineterm=""
        )
        return "".join(diff)

    def set_canary(self, agent_id: str, version_num: int, percentage: int) -> Dict[str, Any]:
        """Definiert eine Version als Canary mit konfigurierter Verkehrsweiterleitung (1–99%)."""
        if not (0 <= percentage <= 100):
            raise ValueError("Canary-Prozentsatz muss zwischen 0 und 100 liegen.")

        ver = self.get_version(agent_id, version_num)
        if not ver:
            raise ValueError(f"Version {version_num} nicht gefunden.")

        with self._get_conn() as conn:
            cur = conn.cursor()
            # Andere Canary-Flags für diesen Agenten zurücksetzen
            cur.execute("UPDATE prompt_versions SET canary_percentage = 0 WHERE agent_id = ?", (agent_id,))
            cur.execute("""
                UPDATE prompt_versions 
                SET canary_percentage = ? 
                WHERE agent_id = ? AND version_num = ?
            """, (percentage, agent_id, version_num))
            conn.commit()

        return {
            "status": "success",
            "agent_id": agent_id,
            "canary_version": version_num,
            "canary_percentage": percentage
        }

    def promote_canary(self, agent_id: str, version_num: int) -> Dict[str, Any]:
        """Befördert eine Canary-Version zur vollwertigen aktiven Version (100% Traffic)."""
        ver = self.get_version(agent_id, version_num)
        if not ver:
            raise ValueError(f"Version {version_num} nicht gefunden.")

        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE prompt_versions SET is_active = 0, canary_percentage = 0 WHERE agent_id = ?", (agent_id,))
            cur.execute("""
                UPDATE prompt_versions 
                SET is_active = 1, canary_percentage = 0, commit_message = commit_message || ' [PROMOTED TO STABLE]'
                WHERE agent_id = ? AND version_num = ?
            """, (agent_id, version_num))
            conn.commit()

        self._sync_profiles_json(agent_id, ver["prompt"], ver.get("model"))

        return {
            "status": "success",
            "action": "promote_canary",
            "agent_id": agent_id,
            "active_version": version_num
        }

    def get_effective_prompt(self, agent_id: str, task_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Ermittelt den aktuell anzuwendenden Prompt.
        Falls ein Canary aktiv ist, wird deterministisch anhand des Task-Hashes entschieden.
        """
        self.import_baseline_if_missing(agent_id)
        with self._get_conn() as conn:
            cur = conn.cursor()
            # 1. Canary prüfen
            cur.execute("""
                SELECT * FROM prompt_versions 
                WHERE agent_id = ? AND canary_percentage > 0
                ORDER BY version_num DESC LIMIT 1
            """, (agent_id,))
            canary = cur.fetchone()

            if canary:
                canary_pct = canary["canary_percentage"]
                # Deterministisches Hashing per task_id
                routing_key = task_id or os.urandom(8).hex()
                hash_val = int(hashlib.md5(routing_key.encode("utf-8")).hexdigest(), 16) % 100
                if hash_val < canary_pct:
                    return {
                        "prompt": canary["prompt"],
                        "version_num": canary["version_num"],
                        "model": canary["model"],
                        "is_canary": True,
                        "canary_percentage": canary_pct,
                        "agent_id": agent_id
                    }

            # 2. Standardmäßig aktive Version zurückgeben
            cur.execute("""
                SELECT * FROM prompt_versions 
                WHERE agent_id = ? AND is_active = 1
                ORDER BY version_num DESC LIMIT 1
            """, (agent_id,))
            active = cur.fetchone()
            if active:
                return {
                    "prompt": active["prompt"],
                    "version_num": active["version_num"],
                    "model": active["model"],
                    "is_canary": False,
                    "canary_percentage": 0,
                    "agent_id": agent_id
                }

        # Fallback: Direkt aus agent_profiles.json
        return {
            "prompt": "",
            "version_num": 0,
            "model": None,
            "is_canary": False,
            "canary_percentage": 0,
            "agent_id": agent_id
        }


# Globales Singleton
prompt_registry = PromptRegistry()
