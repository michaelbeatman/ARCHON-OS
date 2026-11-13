import sqlite3

conn = sqlite3.connect('pocketbase/pb_data/data.db')
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print("Tables:", tables)

for tbl in ['kontakte', 'nachrichten', 'events']:
    if tbl in tables:
        c.execute(f"SELECT count(*) FROM {tbl}")
        print(f"{tbl}: {c.fetchone()[0]}")
