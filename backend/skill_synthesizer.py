"""
backend/skill_synthesizer.py
Pillar 7 (Selbst-Evolution):
Erkennt wiederkehrende erfolgreiche Arbeitsabläufe von Agenten,
generiert daraus neue, wiederverwendbare SKILL.md-Entwürfe,
vermerkt diese in der Personalakte des Agenten und legt sie zur Freigabe vor.
"""

import os
import sys
import json
import sqlite3
import datetime
from pathlib import Path
from typing import Dict, Any, List

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")
SKILLS_DRAFT_DIR = os.path.join(WORKSPACE_DIR, ".agents", "skills", "drafts")
PERSONALAKTEN_DIR = os.path.join(WORKSPACE_DIR, "agent_workspace", "personalakten")

class SkillSynthesizer:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(SKILLS_DRAFT_DIR, exist_ok=True)
        os.makedirs(PERSONALAKTEN_DIR, exist_ok=True)
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS skill_proposals (
                    id TEXT PRIMARY KEY,
                    skill_name TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    trigger_intent TEXT NOT NULL,
                    skill_markdown TEXT NOT NULL,
                    draft_file_path TEXT NOT NULL,
                    status TEXT DEFAULT 'pending_approval',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    approved_at TIMESTAMP
                )
            """)
            conn.commit()

    def propose_new_skill(self, agent_id: str, skill_name: str, trigger_intent: str, workflow_description: str, tools_used: List[str] = None) -> Dict[str, Any]:
        """Erstellt einen neuen Skill-Entwurf und trägt ihn in die Personalakte ein."""
        tools_used = tools_used or ["local_memory", "core_dispatcher"]
        skill_slug = skill_name.lower().replace(" ", "-").replace("_", "-")
        prop_id = f"skill-prop-{datetime.datetime.now().strftime('%m%d%H%M%S')}"

        skill_md = f"""---
name: {skill_slug}
description: Automatisch synthetisierter Skill für '{skill_name}'.
version: 1.0.0
author: Archon OS Synthesizer (Pillar 7)
agent: {agent_id}
---

# {skill_name}

## 1. Einsatzzweck & Trigger
Wird automatisch aktiviert bei: `{trigger_intent}`

## 2. Standardisierter Arbeitsablauf
{workflow_description}

## 3. Benötigte Werkzeuge & Tools
{chr(10).join(f"- {t}" for t in tools_used)}

## 4. Best Practices & Qualitätssicherung
- Ergebnisse im Obsidian 2nd Brain dokumentieren.
- Bei Fehlern den Self-Correction Loop verwenden.
"""

        draft_file = os.path.join(SKILLS_DRAFT_DIR, f"{skill_slug}_SKILL.md")
        with open(draft_file, "w", encoding="utf-8") as f:
            f.write(skill_md)

        # In SQLite registrieren
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO skill_proposals (id, skill_name, agent_id, trigger_intent, skill_markdown, draft_file_path, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending_approval', CURRENT_TIMESTAMP)
            """, (prop_id, skill_name, agent_id, trigger_intent, skill_md, draft_file))
            conn.commit()

        # In die Personalakte des Agenten vermerken
        self._record_in_personalakte(agent_id, skill_name, prop_id)

        return {
            "status": "pending_approval",
            "proposal_id": prop_id,
            "skill_name": skill_name,
            "draft_file": draft_file,
            "message": f"Skill-Entwurf '{skill_name}' generiert und in Personalakte von '{agent_id}' vermerkt. Freigabe ausstehend."
        }

    def _record_in_personalakte(self, agent_id: str, skill_name: str, prop_id: str):
        akte_path = os.path.join(PERSONALAKTEN_DIR, f"personalakte_{agent_id}.md")
        today = datetime.date.today().isoformat()
        entry = f"\n- 🌟 **Synthetisierter Skill-Entwurf:** [{skill_name}] (ID: {prop_id}, {today}) — Status: *Wartet auf Benutzerfreigabe*\n"
        try:
            if os.path.exists(akte_path):
                with open(akte_path, "a", encoding="utf-8") as f:
                    f.write(entry)
            else:
                with open(akte_path, "w", encoding="utf-8") as f:
                    f.write(f"# Personalakte: {agent_id}\n\n## Kompetenzen & Skill-Entwicklung\n{entry}")
        except Exception:
            pass

    def approve_skill(self, proposal_id: str) -> Dict[str, Any]:
        """Aktiviert einen freigegebenen Skill dauerhaft im System."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM skill_proposals WHERE id = ?", (proposal_id,))
            row = cur.fetchone()
            if not row:
                return {"status": "error", "message": f"Vorschlag {proposal_id} nicht gefunden."}

            item = dict(row)
            active_skill_dir = os.path.join(WORKSPACE_DIR, ".agents", "skills", item["skill_name"].lower().replace(" ", "-"))
            os.makedirs(active_skill_dir, exist_ok=True)
            active_file = os.path.join(active_skill_dir, "SKILL.md")

            with open(active_file, "w", encoding="utf-8") as f:
                f.write(item["skill_markdown"])

            conn.execute("UPDATE skill_proposals SET status = 'approved', approved_at = CURRENT_TIMESTAMP WHERE id = ?", (proposal_id,))
            conn.commit()

            return {
                "status": "approved",
                "proposal_id": proposal_id,
                "skill_name": item["skill_name"],
                "active_path": active_file,
                "message": f"Skill '{item['skill_name']}' dauerhaft im Agenten-Repertoire aktiviert."
            }

    def list_proposals(self, status: str = None) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            if status:
                cur.execute("SELECT * FROM skill_proposals WHERE status = ? ORDER BY created_at DESC", (status,))
            else:
                cur.execute("SELECT * FROM skill_proposals ORDER BY created_at DESC")
            return [dict(r) for r in cur.fetchall()]

skill_synthesizer = SkillSynthesizer()
