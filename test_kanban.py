import os, sqlite3
p = "/opt/data/kanban/kanban.db" if os.path.exists("/opt/data/kanban/kanban.db") else os.path.expanduser("~/.hermes/kanban/kanban.db")
print("KANBAN PATH:", p)
c = sqlite3.connect(p)
try:
    print("COUNT:", c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0])
except Exception as e:
    print("ERROR:", e)
