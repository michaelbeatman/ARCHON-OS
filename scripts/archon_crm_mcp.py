import requests
import json
import sys
import re

POCKETBASE_URL = "http://127.0.0.1:8090"
COLLECTION_NAME = "kontakte"

def get_all_contacts():
    """Liest alle Kontakte aus PocketBase aus."""
    url = f"{POCKETBASE_URL}/api/collections/{COLLECTION_NAME}/records?perPage=500"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.json().get("items", [])
    except Exception as e:
        print(f"Fehler bei PocketBase-Verbindung: {e}")
    return []

def update_contact_email(contact_id, email_address):
    """Führt Auto-Enrichment aus (ergänzt fehlende E-Mail-Adresse)."""
    url = f"{POCKETBASE_URL}/api/collections/{COLLECTION_NAME}/records/{contact_id}"
    payload = {"email": email_address}
    response = requests.patch(url, json=payload)
    return response.status_code == 200

def append_email_to_history(contact_id, email_obj):
    """Fügt E-Mail zum nachrichtenverlauf hinzu (mit Duplikats-Schutz)."""
    url = f"{POCKETBASE_URL}/api/collections/{COLLECTION_NAME}/records/{contact_id}"
    res = requests.get(url)
    if res.status_code != 200:
        return False
    
    contact = res.json()
    history = contact.get("nachrichtenverlauf") or []
    
    existing_ids = {msg.get("messageId") for msg in history if isinstance(msg, dict) and "messageId" in msg}
    if email_obj.get("messageId") in existing_ids:
        return True  # Bereits vorhanden

    if isinstance(email_obj, dict) and "text" in email_obj:
        raw_text = email_obj.get("text") or ""
        email_obj["text"] = re.sub(r'(\r?\n){2,}', '\n', raw_text).strip()

    history.append(email_obj)
    update_res = requests.patch(url, json={"nachrichtenverlauf": history})
    return update_res.status_code == 200

def fetch_local_outlook_emails(limit=200):
    """Liest Mails direkt aus dem lokal geöffneten Windows-Outlook aus."""
    try:
        import win32com.client
    except ImportError:
        print("[-] Paket 'pywin32' nicht installiert. Bitte 'pip install pywin32' ausführen.")
        return []

    try:
        outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        
        # 6 = Posteingang, 5 = Gesendete Elemente
        inbox = outlook.GetDefaultFolder(6).Items
        sent = outlook.GetDefaultFolder(5).Items
        
        emails = []
        
        # Posteingang lesen
        inbox.Sort("[ReceivedTime]", True)
        for idx, item in enumerate(inbox):
            if idx >= limit:
                break
            try:
                raw_text = getattr(item, "Body", "")[:2000]
                cleaned_text = re.sub(r'(\r?\n){2,}', '\n', raw_text).strip()
                subject_text = getattr(item, "Subject", "")
                sender_email = getattr(item, "SenderEmailAddress", "")

                sec_status = "safe"
                try:
                    import sys, os
                    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    if root_dir not in sys.path:
                        sys.path.insert(0, root_dir)
                    from local_security_guard import scan_prompt_injection, sanitize_injection_text
                    scan_res = scan_prompt_injection(cleaned_text, subject=subject_text, sender=sender_email)
                    sec_status = scan_res.get("verdict", "safe")
                    if sec_status != "safe":
                        cleaned_text = sanitize_injection_text(cleaned_text)
                except Exception:
                    pass

                emails.append({
                    "type": "inbound",
                    "sender_name": getattr(item, "SenderName", ""),
                    "sender_email": sender_email,
                    "recipient": getattr(item, "To", ""),
                    "subject": subject_text,
                    "text": cleaned_text,
                    "security_status": sec_status,
                    "timestamp": str(getattr(item, "ReceivedTime", "")),
                    "messageId": f"outlook_in_{getattr(item, 'EntryID', str(idx))}"
                })
            except Exception:
                continue

        # Gesendete Mails lesen
        sent.Sort("[SentOn]", True)
        for idx, item in enumerate(sent):
            if idx >= limit:
                break
            try:
                raw_text = getattr(item, "Body", "")[:2000]
                cleaned_text = re.sub(r'(\r?\n){2,}', '\n', raw_text).strip()
                emails.append({
                    "type": "outbound",
                    "sender_name": "Me",
                    "sender_email": "",
                    "recipient_name": getattr(item, "To", ""),
                    "subject": getattr(item, "Subject", ""),
                    "text": cleaned_text,
                    "timestamp": str(getattr(item, "SentOn", "")),
                    "messageId": f"outlook_sent_{getattr(item, 'EntryID', str(idx))}"
                })
            except Exception:
                continue

        return emails
    except Exception as e:
        print(f"Fehler beim Zugriff auf Outlook: {e}")
        return []

def save_potential_contacts(potential_list):
    with open("potenzielle_neukontakte.json", "w", encoding="utf-8") as f:
        json.dump(potential_list, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "--get-contacts":
            print(json.dumps(get_all_contacts(), ensure_ascii=False))
        elif cmd == "--fetch-mails":
            print(json.dumps(fetch_local_outlook_emails(), ensure_ascii=False))