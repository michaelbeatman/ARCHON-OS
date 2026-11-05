import sqlite3

conn = sqlite3.connect('/opt/data/state.db')
cur = conn.cursor()
cur.execute("SELECT id, role, content FROM messages WHERE session_id = 'task_agent_executive_decision_architect' AND id >= 2765 ORDER BY id ASC")
for m in cur.fetchall():
    print(f"\n=================== [MSG #{m[0]} | {m[1]}] ===================")
    content = m[2] or ""
    # if routing lines are repeated, clean them up for reading
    lines = content.split('\n')
    filtered = []
    for l in lines:
        if "*- Routed to:" in l:
            if not any("*- Routed to:" in x for x in filtered[-2:]):
                filtered.append(l)
        else:
            filtered.append(l)
    print("\n".join(filtered))
