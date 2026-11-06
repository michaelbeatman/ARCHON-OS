"""Benchmark: alle parameterlosen GET-Routen einmal messen und ranken.

Aufruf im Container:  docker exec ARCHON-OS python /app/scripts/bench_routes.py

Berücksichtigt auch ausgelagerte Router (FastAPI legt sie als _IncludedRouter
ab) und überspringt Streaming-Endpunkte (SSE), die nie terminieren.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

import main

TOKEN = ""
for _cand in ("/app/data/.archon_service_token",
              os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "data", ".archon_service_token")):
    try:
        with open(_cand, "r", encoding="utf-8") as f:
            TOKEN = f.read().strip()
        break
    except Exception:
        continue

SKIP = ("/api/v1/events/stream", "/static", "/redoc", "/docs", "/openapi.json")


def collect(routes, out=None):
    """Sammelt Pfade rekursiv - Router sind als _IncludedRouter verschachtelt."""
    out = out if out is not None else []
    for r in routes:
        sub = getattr(r, "routes", None)
        if sub:
            collect(sub, out)
            continue
        p = getattr(r, "path", None)
        methods = getattr(r, "methods", None) or set()
        if p and "GET" in methods and "{" not in p and not any(p.startswith(s) for s in SKIP):
            out.append(p)
    return out


paths = sorted(set(collect(main.app.routes)))
rows = []
with httpx.Client(base_url="http://127.0.0.1:8501", timeout=8.0,
                  headers={"x-archon-service-token": TOKEN}) as c:
    for p in paths:
        try:
            t = time.time()
            r = c.get(p)
            rows.append(((time.time() - t) * 1000, r.status_code, p))
        except Exception as e:
            rows.append((99999.0, f"ERR:{type(e).__name__}", p))

rows.sort(reverse=True)
print(f"GET-Routen ohne Parameter: {len(rows)}\n")
print("TOP 15 langsamste:")
for ms, code, p in rows[:15]:
    print(f"  {ms:8.0f} ms  {str(code):5}  {p}")
print("\nGESAMT: %.1f s (Median %.0f ms)"
      % (sum(r[0] for r in rows) / 1000, sorted(r[0] for r in rows)[len(rows) // 2]))