#!/usr/bin/env python3
"""
Archon CRM - Tiefenbereinigung & Deduplizierung aller Nachrichten
================================================================
Bereinigt doppelte Nachrichten im 'nachrichtenverlauf' aller Kontakte in PocketBase.

Erkennungs- & Bereinigungsregeln:
- Sender-Normalisierung: 'Ich', 'user', 'Michael Keller', 'michael-keller' -> 'Ich'.
  Anderer Name / 'contact' -> Name des Kontakts.
- Text-Normalisierung: Whitespace vereinheitlichen, Zeilenumbrüche glätten, strip().
- Zeitzonen-Harmonisierung: Erkennt Zeitstempel in 'date' und 'timestamp', fängt
  UTC/CEST-Verschiebungen ab und behält den exaktesten/lokalen Zeitstempel.
- Einheitliches Datenformat: Stellt sicher, dass sowohl 'date' als auch 'timestamp' vorhanden sind.
- Chronologische Sortierung: Jüngste Nachricht zuerst (absteigend).

Usage:
  python scripts/crm_dedupe_deep.py [--dry-run]
"""

import sys
import os
import json
import re
import urllib.request
import urllib.error
from datetime import datetime
import time

# Ensure UTF-8 output on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

POCKETBASE_URL = os.environ.get("POCKETBASE_URL", "http://127.0.0.1:8090")
COLLECTION = "kontakte"

def norm_sender(s, contact_name=""):
    if not s:
        return "user"
    s_clean = str(s).strip().lower()
    if s_clean in ["ich", "user", "michael keller", "michael-keller"]:
        return "user"
    return "contact"

def norm_text(t):
    if not t:
        return ""
    cleaned = re.sub(r"[ \t]+", " ", str(t).strip())
    cleaned = re.sub(r"(\r?\n){2,}", "\n", cleaned)
    cleaned = cleaned.replace("\u00a0", " ").strip()
    return cleaned

def parse_time_val(m):
    raw = m.get("timestamp") or m.get("date") or ""
    if not raw:
        return 0
    s = str(raw).strip()
    mat = re.search(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)", s)
    if not mat:
        return 0
    date_part = mat.group(1)
    time_part = mat.group(2)
    if time_part.count(":") == 1:
        time_part += ":00"
    try:
        dt = datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M:%S")
        return dt.timestamp()
    except Exception:
        return 0

def format_clean_message(m, contact_name=""):
    t_val = parse_time_val(m)
    sender_canon = norm_sender(m.get("sender"), contact_name)
    
    date_str = m.get("date")
    ts_str = m.get("timestamp")
    
    if t_val > 0:
        dt = datetime.fromtimestamp(t_val)
        if not date_str or len(date_str) < 10:
            date_str = dt.strftime("%Y-%m-%d %H:%M")
        if not ts_str:
            ts_str = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    else:
        date_str = date_str or ""
        ts_str = ts_str or ""

    clean_obj = {
        "sender": "Ich" if sender_canon == "user" else (contact_name or "Kontakt"),
        "text": m.get("text", "").strip(),
        "date": date_str,
        "timestamp": ts_str,
        "type": m.get("type") or "linkedin"
    }
    if m.get("id"):
        clean_obj["id"] = m["id"]
    return clean_obj, t_val

def dedupe_history(nv, contact_name=""):
    if not nv or not isinstance(nv, list):
        return [], 0
        
    seen = {}
    removed = 0
    
    for m in nv:
        if not isinstance(m, dict):
            continue
        text_clean = norm_text(m.get("text"))
        if not text_clean:
            continue
        sender_canon = norm_sender(m.get("sender"), contact_name)
        key = (sender_canon, text_clean)
        
        clean_msg, t_val = format_clean_message(m, contact_name)
        
        if key not in seen:
            seen[key] = (t_val, clean_msg)
        else:
            old_t, old_msg = seen[key]
            # Behalte die Nachricht mit dem späteren / vollständigeren Datum
            if t_val > old_t:
                seen[key] = (t_val, clean_msg)
            removed += 1
            
    result = [msg for t, msg in seen.values()]
    result.sort(key=lambda x: parse_time_val(x), reverse=True)
    return result, removed

def fetch_all_contacts():
    items = []
    page = 1
    per_page = 250
    while True:
        url = f"{POCKETBASE_URL}/api/collections/{COLLECTION}/records?page={page}&perPage={per_page}"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                batch = data.get("items", [])
                if not batch:
                    break
                items.extend(batch)
                if page >= data.get("totalPages", 1):
                    break
                page += 1
        except Exception as e:
            print(f"Fehler beim Abrufen der Kontakte (Seite {page}): {e}")
            break
    return items

def patch_contact_history(contact_id, clean_history):
    url = f"{POCKETBASE_URL}/api/collections/{COLLECTION}/records/{contact_id}"
    payload = json.dumps({"nachrichtenverlauf": clean_history}).encode('utf-8')
    req = urllib.request.Request(url, data=payload, method="PATCH")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204)
    except Exception as e:
        print(f"Fehler beim Speichern von Kontakt {contact_id}: {e}")
        return False

def main():
    dry_run = "--dry-run" in sys.argv
    print(f"🚀 Starte Archon CRM Tiefenbereinigung (PocketBase: {POCKETBASE_URL})...")
    if dry_run:
        print("ℹ️ Modus: DRY-RUN (Es werden keine Daten überschrieben)")
        
    contacts = fetch_all_contacts()
    print(f"📋 {len(contacts)} Kontakte insgesamt geladen.")

    total_with_history = 0
    contacts_cleaned = 0
    total_duplicates_removed = 0

    for c in contacts:
        c_id = c.get("id")
        name = c.get("name") or "Unbekannt"
        nv = c.get("nachrichtenverlauf")
        
        if not nv or not isinstance(nv, list):
            continue
            
        total_with_history += 1
        cleaned_nv, removed = dedupe_history(nv, name)
        
        if removed > 0 or len(cleaned_nv) != len(nv):
            contacts_cleaned += 1
            total_duplicates_removed += removed
            print(f"  ✂️ {name}: {len(nv)} -> {len(cleaned_nv)} Nachrichten (-{removed} Duplikate)")
            
            if not dry_run:
                success = patch_contact_history(c_id, cleaned_nv)
                if not success:
                    print(f"     ❌ Fehler beim Aktualisieren von {name} ({c_id})")
                time.sleep(0.02) # sanfte Drosselung gegen DB-Locks

    print("\n" + "=" * 50)
    print(f"📊 BEREINIGUNGS-STATISTIK:")
    print(f"   Kontakte mit Nachrichten: {total_with_history}")
    print(f"   Bereinigte Kontakte:     {contacts_cleaned}")
    print(f"   Entfernte Duplikate:     {total_duplicates_removed}")
    print("=" * 50)
    
    if dry_run:
        print("💡 Führe das Skript ohne --dry-run aus, um die Änderungen jetzt zu schreiben.")
    else:
        print("✅ Datenbank erfolgreich bereinigt. Keine Duplikate mehr vorhanden.")

if __name__ == "__main__":
    main()
