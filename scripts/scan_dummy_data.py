import os
import sqlite3
import json
import re

print("==================================================")
print("FOCUSED DUMMY / MOCK DATA AUDIT")
print("==================================================")

# 1. Inspect kanban.db details
kanban_db = "/opt/data/kanban.db" if os.path.exists("/opt/data/kanban.db") else "C:/Users/User/.hermes/kanban.db"
print(f"\n--- 1. KANBAN DB: {kanban_db} ---")
if os.path.exists(kanban_db):
    conn = sqlite3.connect(kanban_db)
    conn.row_factory = sqlite3.Row
    tasks = conn.execute("SELECT * FROM tasks").fetchall()
    print(f"Total tasks: {len(tasks)}")
    for t in tasks:
        d = dict(t)
        print(f"  ID: {d.get('id')} | Title: {d.get('title')} | Status: {d.get('status')} | Assignee: {d.get('assigned_agent')}")
    comments = conn.execute("SELECT * FROM task_comments").fetchall()
    print(f"Total comments: {len(comments)}")
    for c in comments:
        d = dict(c)
        print(f"  Task {d.get('task_id')} | Author {d.get('author')}: {d.get('content')}")
    events = conn.execute("SELECT * FROM task_events").fetchall()
    print(f"Total events: {len(events)}")
    conn.close()

# 2. Check state.db for any dummy/mock records
state_db = "/opt/data/state.db" if os.path.exists("/opt/data/state.db") else "C:/Users/User/.hermes/state.db"
print(f"\n--- 2. STATE DB: {state_db} ---")
if os.path.exists(state_db):
    try:
        conn = sqlite3.connect(state_db)
        tbls = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        print(f"Tables in state.db: {tbls}")
        for t in tbls:
            cnt = conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            print(f"  Table '{t}': {cnt} entries")
        conn.close()
    except Exception as e:
        print(f"Error inspecting state.db: {e}")

# 3. Check App Source Files for Mock / Dummy Fallbacks
print("\n--- 3. APP CODE SCAN (backend, static, main.py) ---")
base_dir = "/app" if os.path.exists("/app") else "."
app_paths = [
    os.path.join(base_dir, "main.py"),
    os.path.join(base_dir, "static/index.html"),
    os.path.join(base_dir, "static/js"),
    os.path.join(base_dir, "backend"),
    os.path.join(base_dir, "config"),
]

files_to_scan = []
for p in app_paths:
    if os.path.isfile(p):
        files_to_scan.append(p)
    elif os.path.isdir(p):
        for root, dirs, files in os.walk(p):
            for f in files:
                if f.endswith((".py", ".js", ".html", ".json")) and not f.endswith(".bak"):
                    files_to_scan.append(os.path.join(root, f))

patterns = [
    re.compile(r'\b(dummy|mock|beispiel|muster(?:mann|frau)?|test-data|fake-data|foo@example\.com)\b', re.IGNORECASE),
]

findings = []
for fpath in files_to_scan:
    rel_path = os.path.relpath(fpath, base_dir)
    try:
        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        for idx, line in enumerate(lines, 1):
            clean = line.strip()
            if not clean or clean.startswith(("#", "//", "/*", "*")):
                continue
            if "::placeholder" in clean or "placeholder=" in clean:
                continue
            for pat in patterns:
                m = pat.search(clean)
                if m:
                    findings.append((rel_path, idx, m.group(0), clean[:110]))
                    break
    except Exception as e:
        pass

print(f"Total dummy/mock occurrences found in app code: {len(findings)}")
for rel, line_no, word, text in findings:
    print(f"  {rel}:{line_no} [{word}]: {text}")
