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
    url = f"{POCKETBASE_URL}/api/collections/{COLLECTION_NAME}/records/{contact_id}"
    
    # 1. Aktuellen Kontakt abrufen
    res = requests.get(url)
    if res.status_code != 200:
        return False
    
    contact = res.json()
    history = contact.get("nachrichtenverlauf") or []
    
    # 2. Duplikats-Prüfung via messageId
    existing_ids = {msg.get("messageId") for msg in history if isinstance(msg, dict) and "messageId" in msg}
    if email_obj.get("messageId") in existing_ids:
        print(f"[-] E-Mail {email_obj.get('messageId')} existiert bereits bei Kontakt {contact_id}. Übersprungen.")
        return True

    # 3. Anfügen und Speichern
    history.append(email_obj)
    update_res = requests.patch(url, json={"nachrichtenverlauf": history})
    return update_res.status_code == 200

def save_potential_contacts(potential_list):
    """Speichert nicht zuordenbare, relevante E-Mails in eine Berichtsdatei."""
    with open("potenzielle_neukontakte.json", "w", encoding="utf-8") as f:
        json.dump(potential_list, f, ensure_ascii=False, indent=2)
    print(f"[+] {len(potential_list)} potenzielle Neukontakte in 'potenzielle_neukontakte.json' gespeichert.")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--get-contacts":
        print(json.dumps(get_all_contacts(), ensure_ascii=False))