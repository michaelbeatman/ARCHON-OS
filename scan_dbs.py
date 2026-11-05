import os
import sqlite3
import glob

print("Scanning for databases inside container...")
for root, dirs, files in os.walk("/"):
    if any(p in root for p in ["/proc", "/sys", "/dev", "/usr", "/var/lib/docker"]):
        continue
    for f in files:
        if f.endswith(".db"):
            full = os.path.join(root, f)
            try:
                conn = sqlite3.connect(full)
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'")
                if cur.fetchone():
                    print("Found sessions table in:", full)
                    cur.execute("SELECT id, display_name FROM sessions WHERE display_name LIKE '%202705237%' OR id LIKE '%202705237%'")
                    res = cur.fetchall()
                    if res:
                        print("  MATCH:", res)
                        cur.execute("SELECT id, role, content FROM messages WHERE session_id=? ORDER BY id ASC", (res[0][0],))
                        for m in cur.fetchall():
                            print(f"\n--- [#{m[0]} {m[1]}] ---\n{m[2]}")
            except Exception as e:
                pass
