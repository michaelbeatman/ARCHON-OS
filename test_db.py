import os, sqlite3
p = "/opt/data/state.db" if os.path.exists("/opt/data/state.db") else os.path.expanduser("~/.hermes/state.db")
c = sqlite3.connect(p)
try:
    print("COUNT:", c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
except Exception as e:
    print("ERROR:", e)
