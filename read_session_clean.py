import sqlite3

conn = sqlite3.connect('/opt/data/state.db')
cur = conn.cursor()
cur.execute("SELECT id, role, content FROM messages WHERE session_id = 'task_agent_executive_decision_architect' AND id >= 2772 ORDER BY id ASC")
for m in cur.fetchall():
    print(f"\n=================== [MSG #{m[0]} | {m[1]}] ===================")
    content = m[2] or ""
    # strip repeating routed to lines
    lines = [l for l in content.split('\n') if not l.strip().startswith('*- Routed to:')]
    print("\n".join(lines[:30]))
    if len(lines) > 30:
        print(f"... ({len(lines)} lines)")
