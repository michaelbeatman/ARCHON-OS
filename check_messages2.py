import sqlite3
import os

db_path = os.path.expanduser("~/.hermes/state.db")
try:
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, session_id, role, substr(content, 1, 50), active FROM messages ORDER BY timestamp DESC LIMIT 10")
        for row in cur.fetchall():
            print(row)
except Exception as e:
    print(e)
