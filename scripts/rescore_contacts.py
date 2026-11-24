#!/usr/bin/env python3
"""
Rescore contacts based on the length of nachrichtenverlauf.
Sets rating (0-5) according to:
0: 0 messages
1: 1 message
2: 2-3 messages
3: 4-6 messages
4: 7-9 messages
5: >=10 messages
"""
import requests
import sys

PB_URL = "http://host.docker.internal:8090"
COLLECTION = "kontakte"

def fetch_all_contacts():
    contacts = []
    page = 1
    per_page = 500
    max_pages = 100  # M7/M9: Schutz vor Endlosschleifen bei fehlerhafter API
    while page <= max_pages:
        resp = requests.get(
            f"{PB_URL}/api/collections/{COLLECTION}/records",
            params={"page": page, "perPage": per_page},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        contacts.extend(data.get("items", []))
        if len(data.get("items", [])) < per_page:
            break
        page += 1
    return contacts

def compute_rating(nachrichtenverlauf):
    if nachrichtenverlauf is None:
        count = 0
    elif isinstance(nachrichtenverlauf, list):
        count = len(nachrichtenverlauf)
    else:
        # treat as string or other? fallback to 0
        count = 0
    if count == 0:
        return 0
    elif count == 1:
        return 1
    elif 2 <= count <= 3:
        return 2
    elif 4 <= count <= 6:
        return 3
    elif 7 <= count <= 9:
        return 4
    else:  # >=10
        return 5

def main():
    print("Fetching contacts...")
    contacts = fetch_all_contacts()
    print(f"Fetched {len(contacts)} contacts.")
    updates = []
    for c in contacts:
        current_rating = c.get("rating", 0)
        nachrichten = c.get("nachrichtenverlauf")
        new_rating = compute_rating(nachrichten)
        if current_rating != new_rating:
            updates.append({"id": c["id"], "rating": new_rating})
            count_val = 0
            if isinstance(nachrichten, list):
                count_val = len(nachrichten)
            elif nachrichten is not None:
                count_val = 1
            print(f"Contact {c['id']} ({c.get('name')}): rating {current_rating} -> {new_rating} (nachrichten count: {count_val})")
    if not updates:
        print("No updates needed.")
        return
    print(f"Applying {len(updates)} updates...")
    for upd in updates:
        # D: konsistent zu fetch_all_contacts() (Zeilen 24-29): Timeout und
        # Fehlerabbruch statt endlos blockierendem Request / stillem 4xx/5xx.
        resp = requests.patch(
            f"{PB_URL}/api/collections/{COLLECTION}/records/{upd['id']}",
            json=upd,
            timeout=10,
        )
        resp.raise_for_status()
        if resp.status_code == 200:
            print(f"  Updated {upd['id']} -> rating {upd['rating']}")
        else:
            print(f"  Failed {upd['id']}: {resp.status_code} {resp.text}")
    print("Done.")

if __name__ == "__main__":
    try:
        main()
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)