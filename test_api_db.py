import os, sqlite3, json
p = "/opt/data/state.db" if os.path.exists("/opt/data/state.db") else os.path.expanduser("~/.hermes/state.db")
try:
    with sqlite3.connect(p) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, title, profile_name, model, started_at, last_activity_at, message_count, estimated_cost_usd, source FROM sessions ORDER BY COALESCE(last_activity_at, started_at) DESC LIMIT 10").fetchall()
        print([dict(r) for r in rows])
except Exception as e:
    print("ERROR:", e)
