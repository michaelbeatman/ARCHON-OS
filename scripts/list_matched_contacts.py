import requests
import json

POCKETBASE_URL = "http://127.0.0.1:8090"
COLLECTION_NAME = "kontakte"

def list_matched():
    url = f"{POCKETBASE_URL}/api/collections/{COLLECTION_NAME}/records?perPage=500"
    res = requests.get(url)
    if res.status_code != 200:
        print("Fehler beim Abruf:", res.status_code)
        return

    items = res.json().get("items", [])
    matched_contacts = []

    for c in items:
        history = c.get("nachrichtenverlauf") or []
        if isinstance(history, str):
            try:
                history = json.loads(history)
            except Exception:
                history = []

        if not isinstance(history, list):
            history = []

        email_msgs = [
            m for m in history 
            if isinstance(m, dict) and (m.get("type") == "email" or m.get("channel") == "email")
        ]

        if email_msgs:
            matched_contacts.append({
                "name": c.get("name") or "Unbekannt",
                "unternehmen": c.get("unternehmen") or "-",
                "email": c.get("email") or "Fehlt",
                "mail_count": len(email_msgs),
                "last_subject": email_msgs[0].get("text", "").split("\n")[0][:80] if email_msgs else ""
            })

    print(f"\n================ GEFUNDENE KONTAKTE MIT E-MAILS ({len(matched_contacts)}) ================\n")
    for idx, item in enumerate(matched_contacts, 1):
        print(f"{idx:2d}. {item['name']:<25} | Firma: {item['unternehmen']:<25} | E-Mail: {item['email']:<35} | Mails: {item['mail_count']}")

if __name__ == "__main__":
    list_matched()
