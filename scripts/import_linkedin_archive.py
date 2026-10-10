import csv
import json
import requests
import os
import hashlib

import sys

POCKETBASE_URL = "http://127.0.0.1:8090"
COLLECTION_NAME = "kontakte"

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

def get_existing_contacts():
    items = []
    page = 1
    per_page = 500
    while True:
        url = f"{POCKETBASE_URL}/api/collections/{COLLECTION_NAME}/records?page={page}&perPage={per_page}"
        try:
            res = requests.get(url, timeout=10)
            if res.status_code != 200:
                break
            data = res.json()
            page_items = data.get("items", [])
            if not page_items:
                break
            items.extend(page_items)
            total_pages = data.get("totalPages", 1)
            if page >= total_pages:
                break
            page += 1
        except Exception as e:
            print(f"Fehler beim Laden bestehender Kontakte: {e}")
            break
    return items

def normalize_url(url):
    if not url:
        return ""
    return url.strip().lower().rstrip("/")

def merge_and_import_connections(csv_path):
    existing_contacts = get_existing_contacts()
    existing_by_name = {}
    existing_by_url = {}
    
    # In-Memory Index nach Namen und URLs
    for c in existing_contacts:
        name = (c.get("name") or "").strip().lower()
        if name and name != "ohne namen":
            existing_by_name[name] = c
        if c.get("linkedin_url"):
            existing_by_url[normalize_url(c.get("linkedin_url"))] = c

    month_map = {
        "jan": "01", "feb": "02", "mar": "03", "apr": "04",
        "may": "05", "mai": "05", "jun": "06", "jul": "07",
        "aug": "08", "sep": "09", "okt": "10", "oct": "10",
        "nov": "11", "dez": "12", "dec": "12"
    }

    def parse_date(date_str):
        if not date_str or not date_str.strip():
            return ""
        parts = date_str.strip().split()
        if len(parts) >= 3:
            day = parts[0].zfill(2)
            mon = month_map.get(parts[1][:3].lower(), "01")
            yr = parts[2]
            return f"{yr}-{mon}-{day}"
        return ""

    with open(csv_path, mode='r', encoding='utf-8', errors='replace') as f:
        reader = csv.reader(f)
        rows = list(reader)
        
        header_idx = 0
        for idx, row in enumerate(rows):
            if any("First Name" in col or "Vorname" in col for col in row):
                header_idx = idx
                break
        
        f.seek(0)
        for _ in range(header_idx):
            next(f)
            
        dr = csv.DictReader(f)
        for row in dr:
            first_name = row.get("First Name") or row.get("Vorname", "")
            last_name = row.get("Last Name") or row.get("Nachname", "")
            url = row.get("URL") or row.get("Url", "")
            email = row.get("Email Address") or row.get("E-Mail-Adresse", "")
            company = row.get("Company") or row.get("Unternehmen", "")
            position = row.get("Position", "")
            connected_on = row.get("Connected On") or row.get("Vernetzt am", "")
            
            full_name = f"{first_name} {last_name}".strip()
            if not full_name:
                continue
                
            norm_url = normalize_url(url)
            name_key = full_name.lower()
            
            contact = existing_by_url.get(norm_url) or existing_by_name.get(name_key)
            
            if contact:
                # KONTAKT EXISTIERT: Nur leere Felder anreichern (MERGE)
                update_payload = {}
                if not contact.get("email") and email:
                    update_payload["email"] = email.strip()
                if not contact.get("unternehmen") and company:
                    update_payload["unternehmen"] = company.strip()
                if not contact.get("rolle") and position:
                    update_payload["rolle"] = position.strip()
                if not contact.get("linkedin_url") and url:
                    update_payload["linkedin_url"] = url.strip()
                if not contact.get("vernetzt_am") and connected_on:
                    update_payload["vernetzt_am"] = parse_date(connected_on)
                if contact.get("status") in ["Gesperrt_1Jahr", "Unvernetzt", "", None]:
                    update_payload["status"] = "Vernetzt"
                    
                if update_payload:
                    patch_url = f"{POCKETBASE_URL}/api/collections/{COLLECTION_NAME}/records/{contact['id']}"
                    requests.patch(patch_url, json=update_payload)
                    print(f"[+] Anreicherung für {full_name}: {list(update_payload.keys())}")
            else:
                # NEUER KONTAKT
                new_contact = {
                    "name": full_name,
                    "rolle": position.strip(),
                    "unternehmen": company.strip(),
                    "email": email.strip(),
                    "linkedin_url": url.strip(),
                    "status": "Vernetzt",
                    "vernetzt_am": parse_date(connected_on),
                    "tags": ["LinkedIn Import"],
                    "nachrichtenverlauf": []
                }
                post_url = f"{POCKETBASE_URL}/api/collections/{COLLECTION_NAME}/records"
                res = requests.post(post_url, json=new_contact)
                if res.status_code in [200, 201]:
                    created_data = res.json()
                    existing_by_name[name_key] = created_data
                    if norm_url:
                        existing_by_url[norm_url] = created_data
                    print(f"[+] Neuer LinkedIn-Kontakt angelegt: {full_name}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        merge_and_import_connections(sys.argv[1])
    else:
        print("Bitte Pfad zur Connections.csv angeben.")