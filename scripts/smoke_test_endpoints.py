"""Smoke test for all parameterless GET routes of the Archon OS API.

Usage (inside container):  python scripts/smoke_test_endpoints.py [base_url]
Writes docs/system/smoke_test_results.json
"""
import json, sys, time, os, urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8501"
SKIP = ("stream", "sse", "events", "download", "logout", "restart", "shutdown", "reset", "sync", "run", "trigger", "fetch")

def get(path, timeout=15):
    t = time.time()
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            body = r.read()
            return r.status, round((time.time() - t) * 1000), len(body), None
    except urllib.error.HTTPError as e:
        return e.code, round((time.time() - t) * 1000), 0, str(e.reason)
    except Exception as e:
        return None, round((time.time() - t) * 1000), 0, type(e).__name__ + ": " + str(e)[:120]

spec = json.loads(urllib.request.urlopen(BASE + "/openapi.json", timeout=20).read())
results = []
for path, ops in sorted(spec.get("paths", {}).items()):
    if "get" not in ops:
        continue
    if "{" in path or any(s in path.lower() for s in SKIP):
        results.append({"path": path, "status": "skipped"})
        continue
    st, ms, size, err = get(path)
    results.append({"path": path, "status": st, "ms": ms, "bytes": size, "error": err})
    print(f"{str(st):>7} {ms:>6}ms {size:>9}B  {path}")

os.makedirs("docs/system", exist_ok=True)
summary = {
    "base": BASE,
    "total_get_routes": len(results),
    "ok": sum(1 for r in results if r["status"] == 200),
    "failed": [r for r in results if r["status"] not in (200, "skipped")],
    "skipped": sum(1 for r in results if r["status"] == "skipped"),
    "results": results,
}
json.dump(summary, open("docs/system/smoke_test_results.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print(f"\nOK {summary['ok']} / failed {len(summary['failed'])} / skipped {summary['skipped']}")
