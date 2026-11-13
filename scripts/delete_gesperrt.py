#!/usr/bin/env python3
"""
Archon CRM - Kontakte mit Status 'Gesperrt_1Jahr' loeschen
============================================================
Loescht ENDGUELTIG alle Kontakte in der 'Kontakte'-Collection, deren
Status 'Gesperrt_1Jahr' ist. Dieser Vorgang ist NICHT umkehrbar.

Hinweis: Durchprobiert mehrere PocketBase-URLs
  (127.0.0.1:8090, localhost:8090, host.docker.internal:8090).

Usage:
  python delete_gesperrt.py              # loescht wirklich
  python delete_gesperrt.py --dry-run    # nur auflisten, nichts loeschen
"""
import sys
import requests

# Reconfigure stdout/stderr for Windows console unicode robustness
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='backslashreplace')

PB_URLS = [
    "http://127.0.0.1:8090",
    "http://localhost:8090",
    "http://host.docker.internal:8090",
]
COLLECTION = "Kontakte"
TARGET_STATUS = "Gesperrt_1Jahr"

_session = requests.Session()


def find_working_base():
    for base in PB_URLS:
        try:
            resp = _session.get(f"{base}/api/health", timeout=4)
            if resp.ok:
                print(f"PocketBase erreichbar unter: {base}")
                return base
        except Exception:
            continue
    raise RuntimeError("Keine PocketBase-Instanz erreichbar. Pruefe, ob PocketBase läuft (Port 8090).")


def fetch_all_contacts(base_url):
    contacts = []
    page = 1
    per_page = 500
    while True:
        resp = _session.get(
            f"{base_url}/api/collections/{COLLECTION}/records",
            params={"page": page, "perPage": per_page},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        contacts.extend(items)
        if len(items) < per_page:
            break
        page += 1
    return contacts


def main():
    dry = "--dry-run" in sys.argv
    print("Verbinde mit PocketBase ...")
    base = find_working_base()
    contacts = fetch_all_contacts(base)
    targets = [c for c in contacts if c.get("status") == TARGET_STATUS]
    print(f"Gefunden: {len(contacts)} Kontakte insgesamt, davon {len(targets)} mit Status '{TARGET_STATUS}'.")

    if dry:
        print("\n[DRY-RUN] Folgende Kontakte wuerden geloescht:")
        for c in targets:
            print(f"  - {c.get('name', '(ohne Name)')} ({c.get('id')})")
        print("\n[DRY-RUN] Ende - nichts geloescht.")
        return

    if not targets:
        print(f"Keine Kontakte mit Status '{TARGET_STATUS}' gefunden. Nichts zu tun.")
        return

    if "--yes" not in sys.argv:
        confirm = input(f"Wirklich {len(targets)} Kontakte endgueltig loeschen? (ja/nein): ").strip().lower()
        if confirm not in ("ja", "y", "yes"):
            print("Abgebrochen. Nichts geloescht.")
            return

    deleted = 0
    for c in targets:
        try:
            resp = _session.delete(f"{base}/api/collections/{COLLECTION}/records/{c['id']}", timeout=10)
            if resp.status_code in (200, 204):
                deleted += 1
                print(f"  [OK] {c.get('name', c['id'])}")
            else:
                print(f"  [FEHLER {resp.status_code}] {c.get('name', c['id'])}: {resp.text[:120]}")
        except Exception as e:
            print(f"  [EXCEPTION] {c.get('name', c['id'])}: {e}")

    print(f"\nErgebnis: {deleted} von {len(targets)} Kontakten endgueltig geloescht.")


if __name__ == "__main__":
    try:
        main()
    except requests.exceptions.RequestException as e:
        print(f"PocketBase-Fehler: {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
