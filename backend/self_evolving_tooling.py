# -*- coding: utf-8 -*-
"""
backend/self_evolving_tooling.py
================================
Pillar 7 (Selbst-Evolution) & Voyager-Paradigma:
Ermöglicht Agenten, bei fehlenden Werkzeugen oder komplexen Sonderaufgaben
vollautomatisch neue Python-Tools und FastMCP-Werkzeuge zu synthetisieren,
in einer isolierten Sandbox gegen Testfälle zu validieren (inklusive Traceback-
Selbstkorrektur) und bei Erfolg permanent in der Skill-Bibliothek zu registrieren.
"""

import os
import sys
import json
import sqlite3
import datetime
import traceback
import subprocess
from typing import Dict, Any, List, Optional, Tuple

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")
SKILLS_DIR = os.path.join(WORKSPACE_DIR, ".agents", "skills")
DYNAMIC_TOOLS_DIR = os.path.join(WORKSPACE_DIR, "scripts", "dynamic_tools")
os.makedirs(DYNAMIC_TOOLS_DIR, exist_ok=True)
os.makedirs(SKILLS_DIR, exist_ok=True)


class SelfEvolvingToolEngine:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS evolved_tools (
                    id TEXT PRIMARY KEY,
                    tool_name TEXT NOT NULL UNIQUE,
                    creator_agent TEXT NOT NULL,
                    description TEXT NOT NULL,
                    code TEXT NOT NULL,
                    test_code TEXT,
                    status TEXT DEFAULT 'active',
                    verification_passed INTEGER DEFAULT 0,
                    iterations_needed INTEGER DEFAULT 1,
                    file_path TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used_at TIMESTAMP
                )
            """)
            conn.commit()

    def test_in_sandbox(self, tool_code: str, test_code: str, timeout_seconds: int = 15) -> Tuple[bool, str]:
        """
        Führt das generierte Tool mit Testcode in einem isolierten Python-Subprozess aus.
        Gibt (Erfolg: bool, Output/Traceback: str) zurück.
        """
        combined_script = f"""# -*- coding: utf-8 -*-
import sys
import os

# --- TOOL CODE ---
{tool_code}

# --- VERIFICATION TEST ---
if __name__ == "__main__":
    try:
{self._indent(test_code, 8)}
        print("__VOYAGER_TEST_PASSED__")
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
"""
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tf:
            tf.write(combined_script)
            temp_path = tf.name

        try:
            py_exe = sys.executable or "python3"
            res = subprocess.run(
                [py_exe, temp_path],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                cwd=WORKSPACE_DIR
            )
            out = res.stdout + "\n" + res.stderr
            passed = res.returncode == 0 and "__VOYAGER_TEST_PASSED__" in out
            return passed, out.strip()
        except subprocess.TimeoutExpired:
            return False, f"Timeout nach {timeout_seconds}s in Sandbox-Ausführung."
        except Exception as e:
            return False, f"Sandbox-Fehler: {str(e)}"
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass

    def synthesize_and_evolve_tool(
        self,
        creator_agent: str,
        tool_name: str,
        description: str,
        implementation_code: str,
        verification_test_code: str,
        max_repair_iterations: int = 3
    ) -> Dict[str, Any]:
        """
        Vollständiger Voyager-Zyklus:
        1. Testet das synthetisierte Tool in der Sandbox.
        2. Bei Fehler: Führt Traceback-Reparaturversuche durch.
        3. Bei Erfolg: Registriert das Tool persistent in dynamic_tools und als SKILL.md.
        4. Vermerkt den Erkenntnisgewinn in agentic_memory.db.
        """
        tool_slug = tool_name.lower().replace(" ", "_").replace("-", "_")
        current_code = implementation_code
        iteration = 1
        passed = False
        last_error = ""

        while iteration <= max_repair_iterations:
            passed, output = self.test_in_sandbox(current_code, verification_test_code)
            if passed:
                break
            last_error = output
            iteration += 1
            # Einfache heuristische Reparatur / Fallback
            current_code = self._attempt_auto_fix(current_code, last_error)

        if not passed:
            return {
                "status": "failed",
                "tool_name": tool_slug,
                "iterations": iteration - 1,
                "error": f"Tool-Verifikation nach {max_repair_iterations} Iterationen fehlgeschlagen:\n{last_error}"
            }

        # 3. Permanent abspeichern (idempotent: nur schreiben, wenn sich der Inhalt ohne Zeitstempel ändert)
        tool_filename = f"{tool_slug}.py"
        tool_file_path = os.path.join(DYNAMIC_TOOLS_DIR, tool_filename)
        
        # Header ohne Zeitstempel für Vergleich
        header_prefix = f"# Autonom synthetisiert von {creator_agent} am "
        
        # Prüfen ob Datei existiert und Inhalt (abzüglich Zeitstempel) identisch ist
        should_write = True
        stored_created_at = None
        if os.path.exists(tool_file_path):
            with open(tool_file_path, "r", encoding="utf-8") as f:
                existing_content = f.read()
            # created_at aus existierendem Header extrahieren (robuster als DB-Format)
            if existing_content.startswith(header_prefix):
                header_end = existing_content.find("\n")
                if header_end > 0:
                    existing_header = existing_content[:header_end + 1]
                    existing_without_header = existing_content[header_end + 1:]
                    new_without_header = current_code
                    if existing_without_header == new_without_header:
                        should_write = False
                        # created_at aus bestehendem Header extrahieren für Wiederverwendung
                        stored_created_at = existing_content[len(header_prefix):header_end].strip()
            else:
                existing_without_header = existing_content
                new_without_header = current_code
                if existing_without_header == new_without_header:
                    should_write = False
        
        if should_write:
            # created_at für neuen Eintrag: aus existierendem Header falls Update, sonst jetzt
            write_created_at = stored_created_at or datetime.datetime.now().isoformat()
            with open(tool_file_path, "w", encoding="utf-8") as f:
                f.write(f"{header_prefix}{write_created_at}\n" + current_code)
        else:
            # Auch beim Nicht-Schreiben: created_at aus Header für Skill-Wiederverwendung
            if stored_created_at is None and os.path.exists(tool_file_path):
                with open(tool_file_path, "r", encoding="utf-8") as f:
                    existing_content = f.read()
                if existing_content.startswith(header_prefix):
                    header_end = existing_content.find("\n")
                    if header_end > 0:
                        stored_created_at = existing_content[len(header_prefix):header_end].strip()

        # 4. Als SKILL.md registrieren (idempotent)
        skill_dir = os.path.join(SKILLS_DIR, f"auto-{tool_slug.replace('_', '-')}")
        os.makedirs(skill_dir, exist_ok=True)
        skill_md_path = os.path.join(skill_dir, "SKILL.md")
        
        # created_at für Skill: aus existierendem Header falls Update, sonst jetzt (Format YYYY-MM-DD HH:MM)
        if stored_created_at:
            # ISO-Format in YYYY-MM-DD HH:MM umwandeln
            try:
                dt = datetime.datetime.fromisoformat(stored_created_at.replace('Z', '+00:00'))
                skill_created_at = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                skill_created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        else:
            skill_created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        
        skill_content = f"""---
name: auto-{tool_slug.replace('_', '-')}
description: {description}
version: 1.0.0
author: Voyager Engine ({creator_agent})
evolution_iterations: {iteration}
---

# {tool_name}

## 1. Zweck
{description}

## 2. Ausführung
Pfad: `scripts/dynamic_tools/{tool_filename}`

## 3. Verifikation
Sandbox-Selbsttest erfolgreich bestanden am {skill_created_at}.
"""
        # Nur schreiben wenn sich Inhalt ändert
        should_write_skill = True
        if os.path.exists(skill_md_path):
            with open(skill_md_path, "r", encoding="utf-8") as f:
                existing_skill = f.read()
            if existing_skill == skill_content:
                should_write_skill = False
        
        if should_write_skill:
            with open(skill_md_path, "w", encoding="utf-8") as f:
                f.write(skill_content)

        # 5. In SQLite registrieren
        tool_id = f"tool_{tool_slug}_{int(datetime.datetime.now().timestamp())}"
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO evolved_tools (
                    id, tool_name, creator_agent, description, code, test_code, status,
                    verification_passed, iterations_needed, file_path, created_at, last_used_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', 1, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (tool_id, tool_slug, creator_agent, description, current_code, verification_test_code, iteration, tool_file_path))

            # In learnings eintragen
            conn.execute("""
                INSERT INTO learnings (agent_id, category, summary, obsidian_link, created_at)
                VALUES (?, 'self_evolution', ?, ?, CURRENT_TIMESTAMP)
            """, (
                creator_agent,
                f"Werkzeug '{tool_slug}' ({description}) in {iteration} Iteration(en) erfolgreich synthetisiert und in Sandbox validiert.",
                f"scripts/dynamic_tools/{tool_filename}"
            ))
            conn.commit()

        return {
            "status": "success",
            "tool_id": tool_id,
            "tool_name": tool_slug,
            "file_path": tool_file_path,
            "skill_path": skill_md_path,
            "iterations_needed": iteration,
            "message": f"Tool '{tool_slug}' erfolgreich synthetisiert, in Sandbox validiert und dauerhaft registriert."
        }

    def list_evolved_tools(self) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM evolved_tools WHERE status = 'active' ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]

    def _indent(self, text: str, spaces: int) -> str:
        prefix = " " * spaces
        return "\n".join((prefix + line if line.strip() else line) for line in text.splitlines())

    def _attempt_auto_fix(self, code: str, error_trace: str) -> str:
        # Fügt bei typischen Import- oder Typfehlern automatische Standard-Imports hinzu
        fixed = code
        if "NameError: name 'json' is not defined" in error_trace and "import json" not in fixed:
            fixed = "import json\n" + fixed
        if "NameError: name 're' is not defined" in error_trace and "import re" not in fixed:
            fixed = "import re\n" + fixed
        if "NameError: name 'os' is not defined" in error_trace and "import os" not in fixed:
            fixed = "import os\n" + fixed
        return fixed


# Singleton-Instanz
_evolving_tool_engine = None

def get_evolving_tool_engine() -> SelfEvolvingToolEngine:
    global _evolving_tool_engine
    if _evolving_tool_engine is None:
        _evolving_tool_engine = SelfEvolvingToolEngine()
    return _evolving_tool_engine

get_self_evolving_tool_engine = get_evolving_tool_engine
