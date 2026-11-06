"""Benchmark: alle parameterlosen GET-Routen einmal messen und ranken."""
import time

import httpx

import main

TOKEN = ""
try:
    with open("/app/data/.archon_service_token", "r", encoding="utf-8") as f:
        TOKEN = f.read().strip()
except Exception:
    pass

paths = []
for r in main.app.routes:
    for sub in (getattr(r, "routes", None) or [r]):
        p = getattr(sub, "path", None)
        methods = getattr(sub, "methods", None) or set()
        if p and "GET" in methods and "{" not in p and not p.startswith("/static"):
            paths.append(p)

paths = sorted(set(paths))
rows = []
with httpx.Client(base_url="http://127.0.0.1:8501", timeout=6.0,
                  headers={"x-archon-service-token": TOKEN}) as c:
    for p in paths:
        try:
            t = time.time()
            r = c.get(p)
            ms = (time.time() - t) * 1000
            rows.append((ms, r.status_code, p))
        except Exception as e:
            rows.append((60000.0, f"ERR:{type(e).__name__}", p))

rows.sort(reverse=True)
print(f"GET-Routen ohne Parameter: {len(rows)}\n")
print("TOP 25 langsamste:")
for ms, code, p in rows[:25]:
    print(f"  {ms:8.0f} ms  {str(code):5}  {p}")
print("\nGESAMT: %.1f s" % (sum(r[0] for r in rows) / 1000))