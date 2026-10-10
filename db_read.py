import sqlite3, os, json
c = sqlite3.connect(os.path.expanduser('~/.hermes/state.db'))
c.row_factory = sqlite3.Row
rows = c.execute("SELECT id, title, profile_name, model, started_at, last_activity_at, message_count, estimated_cost_usd, source FROM sessions ORDER BY COALESCE(last_activity_at, started_at) DESC LIMIT 300").fetchall()
print(len(rows))
