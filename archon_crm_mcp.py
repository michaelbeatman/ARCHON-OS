import requests
import json
import sys

POCKETBASE_URL = "http://127.0.0.1:8090"
COLLECTION_NAME = "kontakte"

def get_all_contacts():
    """Liest alle Kontakte aus PocketBase aus."""
    url = f"{POCKETBASE_URL}/api/collections/{COLLECTION_NAME}/records?perPage=500"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json().get("items", [])
    print(f"Fehler beim Abrufen der Kontakte: {response.text}")
    return []

def update_contact_email(contact_id, email_address):
    """Führt das Auto-Enrichment durch, falls die E-Mail-Adresse fehlt."""
    url = f"{POCKETBASE_URL}/api/collections/{COLLECTION_NAME}/records/{contact_id}"
    payload = {"email": email_address}
    response = requests.patch(url, json=payload)
    return response.status_code == 200

def append_email_to_history(contact_id, email_obj):
    """
    Fügt eine E-Mail zum nachrichtenverlauf eines Kontakts hinzu.
    Verhindert Duplikate anhand der messageId.
    """
    # W2: If-Match/ETag gegen Lost Updates beim parallelen Mail-Sync.
    url = f"{POCKETBASE_URL}/api/collections/{COLLECTION_NAME}/records/{contact_id}"
    clean_obj = dict(email_obj)
    for _attempt in range(3):
        # 1. Aktuellen Kontakt abrufen
        res = requests.get(url, timeout=15)
        if res.status_code != 200:
            return False
        contact = res.json()
        etag = res.headers.get("ETag") or contact.get("revision")
        history = contact.get("nachrichtenverlauf") or []

        # 2. Duplikats-Prüfung via messageId
        existing_ids = {msg.get("messageId") for msg in history if isinstance(msg, dict) and "messageId" in msg}
        if clean_obj.get("messageId") in existing_ids:
            print(f"[-] E-Mail {clean_obj.get('messageId')} existiert bereits bei Kontakt {contact_id}. Übersprungen.")
            return True

        # 3. Anfügen und Speichern mit optimistischem Concurrency-Token
        history.append(clean_obj)
        headers = {"If-Match": str(etag)} if etag else {}
        update_res = requests.patch(
            url, json={"nachrichtenverlauf": history}, headers=headers, timeout=15
        )
        if update_res.status_code == 200:
            return True
        if update_res.status_code not in (400, 409, 412):
            return False
    return False

def save_potential_contacts(potential_list):
    """Speichert nicht zuordenbare, relevante E-Mails in eine Berichtsdatei."""
    with open("potenzielle_neukontakte.json", "w", encoding="utf-8") as f:
        json.dump(potential_list, f, ensure_ascii=False, indent=2)
    print(f"[+] {len(potential_list)} potenzielle Neukontakte in 'potenzielle_neukontakte.json' gespeichert.")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--get-contacts":
        print(json.dumps(get_all_contacts(), ensure_ascii=False))