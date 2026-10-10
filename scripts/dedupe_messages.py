#!/usr/bin/env python3
"""
Archon CRM - Duplikat-Bereinigung (Nachrichtenverlauf)
=======================================================
Entfernt doppelte Nachrichten im nachrichtenverlauf aller Kontakte.

Regel:
- Nachrichten mit GLEICHEM Sender + GLEICHEM normalisiertem Text gelten als
  Duplikat (Timestamp ist nur ein Bonus - fehlende/abweichende Formate
  duerfen KEINE Duplikate erzeugen).
- Gewinner: die Nachricht MIT gueltigem Timestamp (die ohne Datum fliegt raus).
- Falls beide einen Timestamp haben: die mit dem spaeteren Timestamp gewinnt
  (koennte eine Korrektur sein).
- Anschliessend wird chronologisch ABSTEIGEND sortiert (juengste zuerst).

Usage:
  python scripts/dedupe_messages.py [--dry-run]
"""
import json
import re
import sys
import time
import urllib.request

POCKETBASE_URL = "http://host.docker.internal:8090"
COLLECTION = "Kontakte"

def api(path, method="GET", body=None):
    url = f"{POCKETBASE_URL}/api/collections/{COLLECTION}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"❌ API {method} {path} -> HTTP {e.code}: {e.read().decode()[:300]}")
        return None

def fetch_all_contacts():
    items = []
    page = 1
    while True:
        res = api(f"/records?perPage=200&page={page}&sort=-updated")
        if not res or not res.get("items"):
            break
        items.extend(res["items"])
        if len(res["items"]) < 200:
            break
        page += 1
    return items

def norm_text(t):
    if not t:
        return ""
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{2,}", "\n", str(t).strip()))

def ts_value(ts):
    """Timestamp in vergleichbaren Zeitwert (0 wenn fehlt/ungueltig)."""
    if not ts:
        return 0
    s = str(ts).strip()
    m = re.match(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)", s)
    if not m:
        return 0
    tp = m.group(2)
    if tp.count(":") == 1:
        tp += ":00"
    try:
        return time.mktime(time.strptime(f"{m.group(1)} {tp}", "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return 0

def dedupe_list(nv):
    """Entfernt Duplikate (Text+Sender), behaelt die mit gueltigem/spaetestem
    Timestamp. Sortiert danach ABSTEIGEND (juengste zuerst)."""
    if not isinstance(nv, list):
        return nv
    best = {}
    removed = 0
    for m in nv:
        if not isinstance(m, dict):
            continue
        key = (m.get("sender"), norm_text(m.get("text")))
        tv = ts_value(m.get("timestamp"))
        if key not in best:
            best[key] = (tv, m)
        else:
            old_tv, old_m = best[key]
            if tv > old_tv:
                best[key] = (tv, m)
                removed += 1
            else:
                removed += 1
    result = [m for _, m in best.values()]
    result.sort(key=lambda m: ts_value(m.get("timestamp")), reverse=True)  # juengste zuerst
    return result, removed

def main():
    dry = "--dry-run" in sys.argv
    print("🔍 Lade Kontakte...")
    contacts = fetch_all_contacts()
    print(f"✅ {len(contacts)} Kontakte geladen.")

    total_removed = 0
    changed = 0
    for c in contacts:
        nv = c.get("nachrichtenverlauf")
        if not isinstance(nv, list) or not nv:
            continue
        cleaned, removed = dedupe_list(nv)
        if removed == 0 and len(cleaned) == len(nv):
            continue
        total_removed += removed
        changed += 1
        if not dry:
            api(f"/records/{c['id']}", "PATCH", {"nachrichtenverlauf": cleaned})
            time.sleep(0.03)
        if removed > 0:
            print(f"  ➖ {c.get('name')}: {len(nv)} -> {len(cleaned)} (-{removed})")

    print(f"\n📊 Ergebnis:")
    print(f"   Kontakte bereinigt:   {changed}")
    print(f"   Duplikate entfernt:   {total_removed}")
    if dry:
        print("\n🚫 DRY-RUN: Keine Änderungen geschrieben.")
    else:
        print("\n✅ Bereinigung abgeschlossen.")

if __name__ == "__main__":
    main()
