import sqlite3
import os
db_path = os.path.expanduser("~/.hermes/state.db")
with sqlite3.connect(db_path) as conn:
    cur = conn.cursor()
    cur.execute("SELECT content FROM messages WHERE id = 12746")
    row = cur.fetchone()
    print(repr(row[0]))
