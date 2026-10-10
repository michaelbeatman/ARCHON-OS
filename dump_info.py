import sqlite3
import os
from pathlib import Path

repo = r"C:\.Antigravity-projekte\AgenticOS-2026"
dbs = [
    "agent_os.db",
    "agentic_memory.db",
    "archon_vault.db",
    r"data\agentic_memory.db",
    r"memory\state.db"
]

out = []
for db in dbs:
    full_path = os.path.join(repo, db)
    if os.path.exists(full_path):
        try:
            conn = sqlite3.connect(full_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            out.append(f"DB: {db}")
            for t in tables:
                out.append(f"  Table: {t[0]}")
                if t[1]:
                    out.append(f"    Schema: {t[1].strip().replace(chr(10), ' ')}")
            conn.close()
        except Exception as e:
            out.append(f"DB: {db} - Error: {e}")

print("\n".join(out))
