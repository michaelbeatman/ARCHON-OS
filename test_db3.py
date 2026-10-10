import sqlite3
import os
db_path = os.path.expanduser("~/.hermes/state.db")
try:
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT session_id FROM messages ORDER BY id DESC LIMIT 5")
        for row in cur.fetchall():
            print(row[0])
except Exception as e:
    print(e)
