import os, sqlite3
c = sqlite3.connect("/opt/data/kanban.db")
try:
    print(c.execute("SELECT count(*) FROM tasks").fetchone()[0])
except Exception as e:
    print("ERROR:", e)
