#!/usr/bin/env python3
"""
Archon CRM - LinkedIn messages.csv MERGE Importer
==================================================
Liest die von LinkedIn exportierte messages.csv und MERGT die Nachrichten
in den 'nachrichtenverlauf' der Kontakte-Collection (PocketBase).

IMPORTANT: Merged statt ersetzt! Bestehende Nachrichten bleiben erhalten,
nur FEHLENDE werden angehaengt. Dedupe ueber (text, timestamp)-Hash.

Format der Nachrichten im CRM (muss exakt so bleiben):
  {"id": "msg_<kontaktid>_<n>", "sender": "user"|"contact",
   "text": "...", "timestamp": "YYYY-MM-DD HH:mm:ss UTC", "type": "linkedin"}

Usage:
  python scripts/import_linkedin_messages.py <pfad/zu/messages.csv> [--dry-run]
  python scripts/import_linkedin_messages.py <pfad/zu/messages.csv> [--limit 50]
  python scripts/import_linkedin_messages.py <pfad> --csv-encoding utf-8-sig
"""

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

POCKETBASE_URL = os.environ.get("POCKETBASE_URL", "http://localhost:8090")
COLLECTION = "Kontakte"  # ACHTUNG: Gross-K, PocketBase ist case-sensitiv!
USER_HANDLES = ["michael-keller", "michael keller"]

# ---------------------------------------------------------------------------
# CSV-Parsing (robust gegen LinkedIn-Formate)
# ---------------------------------------------------------------------------

def find_header(rows):
    """Finde die Kopfzeile: enthaelt 'CONTENT' oder 'Message'."""
    for i, row in enumerate(rows):
        joined = "|".join(str(c) for c in row).upper()
        if ("CONTENT" in joined or "MESSAGE" in joined) and ("DATE" in joined or "CREATED" in joined):
            return i, row
    # Fallback: erste Zeile
    return 0, rows[0] if rows else []

def extract_columns(header):
    """Mappe Spaltennamen (Gross/Klein, verschiedene Formate) auf Indizes."""
    cols = {}
    for i, name in enumerate(header):
        n = str(name).strip().lower()
        if "conversation" in n and "id" in n:
            cols["conv_id"] = i
        elif "title" in n:
            cols["conv_title"] = i
        elif n in ("from", "first name", "sender name"):
            cols["from_name"] = i
        elif "sender profile url" in n or "from profile" in n:
            cols["from_url"] = i
        elif n in ("to", "last name"):
            cols["to_name"] = i if "to" == n else cols.get("to_name")
        elif "recipient profile" in n or "to profile" in n:
            cols["to_url"] = i
        elif "date" in n or "created" in n:
            cols["date"] = i
        elif "content" in n or "message" == n:
            cols["content"] = i
        elif "direction" in n:
            cols["direction"] = i
        elif "first" in n:
            cols["first_name"] = i
        elif "last" in n:
            cols["last_name"] = i
    return cols

def normalize_url(u):
    if not u:
        return ""
    u = u.strip().lower()
    u = re.sub(r"\?.*$", "", u)
    if u.endswith("/"):
        u = u[:-1]
    return u

def parse_date(raw):
    """LinkedIn: '2026-08-07 08:31:00 UTC' -> '2026-08-07 08:31:00 UTC' (CRM-Format)."""
    if not raw:
        return ""
    s = str(raw).strip()
    m = re.match(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)", s)
    if not m:
        return ""
    time_part = m.group(2)
    if time_part.count(":") == 1:
        time_part += ":00"
    return f"{m.group(1)} {time_part} UTC"

def load_messages(csv_path, encoding="utf-8"):
    """Lies messages.csv, liefere Liste von (url_key, name_key, msg)."""
    messages = []  # (url_key, name_key, msg)
    with open(csv_path, "r", encoding=encoding, errors="replace") as f:
        text = f.read()
    if text.startswith("\ufeff"):
        text = text[1:]
    # WICHTIG: io.StringIO statt splitlines() - mehrzeilige Nachrichten in
    # Anfuehrungszeichen duerfen NICHT zerrissen werden!
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        print("❌ CSV ist leer.")
        sys.exit(1)

    header_idx, header = find_header(rows)
    cols = extract_columns(header)
    print(f"📋 Header (Zeile {header_idx + 1}): {header[:12]}...")

    if "content" not in cols:
        print("❌ Konnte CONTENT-Spalte nicht finden. Unerwartetes CSV-Format:")
        print("   ", header)
        sys.exit(1)

    count = 0
    for row in rows[header_idx + 1:]:
        if len(row) <= cols.get("content", 99):
            continue
        text = (row[cols["content"]] or "").strip()
        if not text:
            continue

        from_name = (row[cols.get("from_name", 0)] or "").strip() if "from_name" in cols else ""
        to_name = (row[cols.get("to_name", 0)] or "").strip() if "to_name" in cols else ""
        from_url = normalize_url(row[cols["from_url"]]) if "from_url" in cols else ""
        to_url = normalize_url(row[cols["to_url"]]) if "to_url" in cols else ""
        date_raw = (row[cols.get("date", 0)] or "") if "date" in cols else ""
        direction = (row[cols.get("direction", 0)] or "").strip().lower() if "direction" in cols else ""

        # Neuere Formate: First Name / Last Name Spalten + Direction
        if "first_name" in cols and not from_name:
            fn = (row[cols.get("first_name", 0)] or "").strip()
            ln = (row[cols.get("last_name", 0)] or "").strip()
            from_name = f"{fn} {ln}".strip()
        if "direction" in cols and not from_url and direction == "outgoing":
            from_name = from_name or "Michael Keller"

        is_user_sender = (
            "michael-keller" in from_url
            or any(h in from_name.lower() for h in USER_HANDLES)
            or direction == "outgoing"
        )
        target_url = to_url if is_user_sender else from_url
        target_name = to_name if is_user_sender else from_name
        sender = "user" if is_user_sender else "contact"
        timestamp = parse_date(date_raw)

        msg = {
            "text": text,
            "sender": sender,
            "timestamp": timestamp,
            "type": "linkedin",
        }
        # Stabile ID aus Hash (Dedupe ueber Import-Laeufe hinweg)
        h = hashlib.sha1(f"{timestamp}|{text}".encode("utf-8")).hexdigest()[:10]
        msg["id"] = f"msg_{h}"
        messages.append((target_url, target_name.lower(), msg))
        count += 1

    print(f"💬 {count} Nachrichten aus messages.csv gelesen.")
    return messages

# ---------------------------------------------------------------------------
# PocketBase API (Collection ist public -> ohne Token)
# ---------------------------------------------------------------------------

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

def normalize_ts(ts):
    """Normalisiere Timestamps auf ein einziges Vergleichsformat, damit
    '2026-07-23 11:36:04 UTC' und '2026-07-23T11:36:04.000Z' als GLEICH
    erkannt werden (Dedupe!). Gibt None zurueck, wenn nicht parsebar."""
    if not ts:
        return None
    s = str(ts).strip()
    m = re.match(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)", s)
    if not m:
        return None
    time_part = m.group(2)
    if time_part.count(":") == 1:
        time_part += ":00"
    return m.group(1) + "T" + time_part + "Z"  # kanonisches Format

def merge_into_contact(contact, new_msgs):
    """Merge neue Nachrichten in bestehenden Verlauf (Dedupe mit
    normalisierten Timestamps - verhindert Duplikate zwischen den Formaten
    'YYYY-MM-DD HH:mm:ss UTC' (Import) und 'YYYY-MM-DDTHH:mm:ss.sssZ' (App))."""
    existing = contact.get("nachrichtenverlauf") or []
    if isinstance(existing, str):
        try:
            existing = json.loads(existing)
        except Exception:
            existing = []

    def norm_text(t):
        """Normalisiere Text fuer den Dedupe-Vergleich: Leerzeilen und
        Whitespace vereinheitlichen. LinkedIn exportiert Nachrichten mit
        doppelten Zeilenumbruechen (\\n\\n), die App normalisiert sie zu
        einfachen (\\n) - inhaltlich ist es DIESELBE Nachricht."""
        if not t:
            return ""
        return re.sub(r"[ \t]+", " ", re.sub(r"\n{2,}", "\n", str(t).strip()))

    existing_ids = {m.get("id") for m in existing if isinstance(m, dict) and m.get("id")}
    # Dedupe-Key: Sender + normalisierter Text. Der Timestamp ist bewusst KEIN
    # Teil des Keys - Nachrichten existieren in zwei Formen (mit Datum aus dem
    # CSV-Import, ohne Datum aus der App) und duerfen NICHT dupliziert werden.
    existing_keys = set()
    for m in existing:
        if not isinstance(m, dict):
            continue
        existing_keys.add((m.get("sender"), norm_text(m.get("text"))))

    added = []
    for m in new_msgs:
        if m["id"] in existing_ids:
            continue
        if (m["sender"], norm_text(m.get("text"))) in existing_keys:
            continue
        added.append(m)

    if not added:
        return None

    merged = existing + added
    # Generelle Regel: JUENGSTE zuerst, AELTESTE zuletzt (absteigend).
    # Nachrichten ohne Datum wandern ans Ende (gelten als am aeltesten).
    def sort_key(m):
        ts = normalize_ts(m.get("timestamp"))
        return ts or "0000-00-00T00:00:00Z"
    merged.sort(key=sort_key, reverse=True)

    return merged

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Merge LinkedIn messages.csv in CRM")
    ap.add_argument("csv_path", help="Pfad zur messages.csv")
    ap.add_argument("--dry-run", action="store_true", help="Nur pruefen, nichts schreiben")
    ap.add_argument("--limit", type=int, default=0, help="Max. Kontakte verarbeiten (0 = alle)")
    ap.add_argument("--csv-encoding", default="utf-8", help="Encoding der CSV (Default: utf-8)")
    ap.add_argument("--only-name", help="Nur diesen Kontakt (Name-Substring) verarbeiten")
    args = ap.parse_args()

    if not os.path.exists(args.csv_path):
        print(f"❌ Datei nicht gefunden: {args.csv_path}")
        sys.exit(1)

    t0 = time.time()
    messages = load_messages(args.csv_path, args.csv_encoding)

    # Nachrichten nach Ziel gruppieren (URL bevorzugt, dann Name)
    by_url = {}
    by_name = {}
    for url_key, name_key, msg in messages:
        if url_key:
            by_url.setdefault(url_key, []).append(msg)
        if name_key:
            by_name.setdefault(name_key, []).append(msg)

    print("\n👥 Lade bestehende Kontakte aus PocketBase...")
    contacts = fetch_all_contacts()
    if not contacts:
        print("❌ Keine Kontakte geladen — ist PocketBase erreichbar?")
        sys.exit(1)
    print(f"✅ {len(contacts)} Kontakte geladen.")

    # Indizes: URL -> Kontakt UND Name -> Liste von Kontakten
    url_map = {}
    name_map = {}
    for c in contacts:
        if c.get("linkedin_url"):
            url_map[normalize_url(c["linkedin_url"])] = c
        full = (c.get("name") or "").strip().lower()
        if full:
            name_map.setdefault(full, []).append(c)

    # WICHTIG (Bugfix Brücker/Bley): Nachrichten werden NUR über die URL
    # zugeordnet. Der Name darf NUR bestätigen - wenn die URL fehlt ODER
    # mehrere Kontakte denselben Namen haben, wird der Name-Match übersprungen
    # statt zu raten. So können Nachrichten nie dem falschen Kontakt zugeordnet
    # werden, nur weil zwei Personen ähnliche Namen/URLs haben.

    matched = 0
    unmatched = 0
    total_added = 0
    changed_contacts = []
    unmatched_keys = set()

    for c in contacts:
        if args.only_name and args.only_name.lower() not in (c.get("name") or "").lower():
            continue

        # Kandidaten NUR über die URL (die eindeutige Wahrheit)
        cand = []
        seen_cand = set()
        url = normalize_url(c.get("linkedin_url") or "")
        if url and url in by_url:
            for m in by_url[url]:
                k = (m.get("sender"), m.get("timestamp"), m.get("text"))
                if k not in seen_cand:
                    seen_cand.add(k)
                    cand.append(m)

        # Name nur als Fallback, WENN die URL nicht matcht UND der Name EINDEUTIG ist
        if not cand:
            full_name = (c.get("name") or "").strip().lower()
            if full_name and full_name in by_name and len(name_map.get(full_name, [])) == 1:
                for m in by_name[full_name]:
                    k = (m.get("sender"), m.get("timestamp"), m.get("text"))
                    if k not in seen_cand:
                        seen_cand.add(k)
                        cand.append(m)

        if not cand:
            continue
        matched += 1

        merged = merge_into_contact(c, cand)
        if merged is None:
            continue

        total_added += len(merged) - len(c.get("nachrichtenverlauf") or [])
        changed_contacts.append((c, merged))
        print(f"  ➕ {c.get('name')}: {len(c.get('nachrichtenverlauf') or [])} -> {len(merged)} Nachrichten (+{len(merged) - len(c.get('nachrichtenverlauf') or [])})")

        if args.limit and len(changed_contacts) >= args.limit:
            break

    # Unmatched Ziele melden (Nachrichten ohne Kontakt im CRM)
    all_names = {n for n in name_map}
    all_urls = {normalize_url(c.get("linkedin_url") or "") for c in contacts}
    for key in list(by_url.keys()) + list(by_name.keys()):
        if key and key not in all_urls and key not in all_names:
            unmatched_keys.add(key)

    print(f"\n📊 Ergebnis:")
    print(f"   Kontakte mit Treffern:     {matched}")
    print(f"   Kontakte mit neuen Msgs:   {len(changed_contacts)}")
    print(f"   Neue Nachrichten gesamt:   {total_added}")
    if unmatched_keys:
        print(f"   ⚠️  {len(unmatched_keys)} Chat-Partner ohne CRM-Kontakt (werden uebersprungen):")
        for k in sorted(unmatched_keys)[:10]:
            print(f"      - {k}")

    if args.dry_run:
        print("\n🚫 DRY-RUN: Keine Änderungen geschrieben.")
        return

    if not changed_contacts:
        print("\n✅ Keine Änderungen nötig — alle Nachrichten bereits vorhanden.")
        return

    print(f"\n💾 Schreibe {len(changed_contacts)} Kontakte...")
    ok = 0
    for c, merged in changed_contacts:
        res = api(f"/records/{c['id']}", "PATCH", {"nachrichtenverlauf": merged})
        if res:
            ok += 1
        time.sleep(0.05)  # sanft raten, PocketBase nicht hammern

    print(f"✅ {ok}/{len(changed_contacts)} Kontakte aktualisiert in {time.time() - t0:.1f}s.")
    print(f"   Neue Nachrichten geschrieben: {total_added}")

if __name__ == "__main__":
    main()
