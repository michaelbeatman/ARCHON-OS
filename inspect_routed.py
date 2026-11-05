import sqlite3

conn = sqlite3.connect('/opt/data/state.db')
cur = conn.cursor()
cur.execute("SELECT id, role, content FROM messages WHERE session_id = 'task_agent_executive_decision_architect' AND id >= 2800 ORDER BY id ASC")
for m in cur.fetchall():
    print(f"=== MSG #{m[0]} ({m[1]}) ===")
    txt = m[2] or ""
    lines = txt.split('\n')
    routed_lines = [l for l in lines if 'Routed to:' in l]
    print(f"Total lines: {len(lines)}, 'Routed to:' count: {len(routed_lines)}")
    if len(routed_lines) > 5:
        print("First 3 routed:", routed_lines[:3])
        print("Last 3 routed:", routed_lines[-3:])
