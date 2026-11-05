import sqlite3

conn = sqlite3.connect('/opt/data/state.db')
cur = conn.cursor()
cur.execute("SELECT id, role, content, timestamp FROM messages WHERE session_id = 'task_agent_executive_decision_architect' ORDER BY id ASC")
msgs = cur.fetchall()
print(f"Total messages: {len(msgs)}")
for m in msgs:
    print(f"\n=================== [MSG #{m[0]} | {m[1]}] ===================")
    print(m[2])
