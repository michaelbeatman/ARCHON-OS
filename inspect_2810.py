import sqlite3

conn = sqlite3.connect('/opt/data/state.db')
cur = conn.cursor()
cur.execute("SELECT id, role, content FROM messages WHERE id = 2810")
m = cur.fetchone()
if m:
    lines = m[2].split('\n')
    print("Non-routed lines:")
    for l in lines:
        if 'Routed to:' not in l:
            print(l[:100])
