import urllib.request
import json
import time

endpoints = [
    '/health',
    '/api/system/health',
    '/api/v1/services',
    '/api/models',
    '/api/agents/profiles',
    '/api/operations/org-chart',
    '/api/operations/org-hierarchy',
    '/api/operations/kanban/tasks',
    '/api/views/inbox/items',
    '/api/views/library/vault/tree',
    '/api/views/showroom/tree',
    '/api/v1/telemetry/dashboard',
    '/api/guardian/stats',
    '/api/v1/hud/telemetry'
]

results = {}
for ep in endpoints:
    url = f'http://127.0.0.1:8501{ep}'
    t0 = time.time()
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as res:
            status = res.status
            size = len(res.read())
            ms = round((time.time() - t0) * 1000)
            results[ep] = {'status': status, 'size': size, 'ms': ms, 'ok': True}
    except Exception as e:
        ms = round((time.time() - t0) * 1000)
        results[ep] = {'error': str(e), 'ms': ms, 'ok': False}

print("=== CORE ENDPOINTS SMOKE TEST ===")
for ep, r in results.items():
    if r['ok']:
        print(f"PASS [{r['status']}] {r['ms']:>4}ms ({r['size']:>7} B)  {ep}")
    else:
        print(f"FAIL [{r['ms']:>4}ms] {ep} -> {r['error']}")
