import json
import re
import sys
from archon_crm_mcp import (
    get_all_contacts,
    fetch_local_outlook_emails,
    update_contact_email,
    append_email_to_history,
    save_potential_contacts
)

SYSTEM_EMAIL_KEYWORDS = [
    "noreply", "no-reply", "invitations", "notification", "digest",
    "bounce", "donotreply", "system", "mailer-daemon", "info-digest"
]

SYSTEM_DOMAINS = [
    "linkedin.com", "xing.com", "google.com", "microsoft.com",
    "facebookmail.com", "zoom.us", "github.com"
]

def is_valid_contact_email(email_str):
    if not email_str or "@" not in email_str:
        return False
    email_lower = email_str.strip().lower()
    if any(kw in email_lower for kw in SYSTEM_EMAIL_KEYWORDS):
        return False
    domain = email_lower.split("@")[-1]
    if any(domain == dom or domain.endswith("." + dom) for dom in SYSTEM_DOMAINS):
        return False
    return True

def run_matching():
    print("[1/3] Lade Kontakte aus PocketBase...")
    contacts = get_all_contacts()
    print(f"  -> {len(contacts)} Kontakte geladen.")

    print("[2/3] Lade Mails aus Outlook...")
    emails = fetch_local_outlook_emails(limit=300)
    print(f"  -> {len(emails)} Mails aus Outlook ausgelesen.")

    print("[3/3] Starte Abgleich & Auto-Enrichment...")
    
    contact_email_map = {}
    contact_name_list = []
    
    for c in contacts:
        cid = c.get("id")
        c_email = (c.get("email") or "").strip().lower()
        c_name = (c.get("name") or "").strip()
        
        # Clean up any bad system emails if previously set
        if c_email and not is_valid_contact_email(c_email):
            update_contact_email(cid, "")
            c_email = ""
            c["email"] = ""
            
        if c_email:
            contact_email_map[c_email] = c
            
        if c_name:
            name_parts = [p.lower() for p in re.split(r'\s+', c_name) if len(p) >= 2]
            contact_name_list.append({
                "contact": c,
                "full_name": c_name.lower(),
                "parts": name_parts
            })

    matched_emails_count = 0
    enriched_emails_count = 0
    unmatched_emails = []
    
    business_keywords = [
        "bewerbung", "hr", "einkauf", "angebot", "anfrage", "rechnung",
        "kooperation", "projekt", "vertrieb", "sales", "karriere",
        "job", "stellenangebot", "partner", "einkaufskontakt", "kontakt"
    ]

    for mail in emails:
        sender_email = (mail.get("sender_email") or "").strip().lower()
        sender_name = (mail.get("sender_name") or "").strip()
        recipient = (mail.get("recipient") or mail.get("recipient_name") or "").strip()
        subject = mail.get("subject") or ""
        body = mail.get("text") or ""
        
        matched_contact = None
        
        # 1. Match by Email Address
        if sender_email and is_valid_contact_email(sender_email) and sender_email in contact_email_map:
            matched_contact = contact_email_map[sender_email]
        elif recipient:
            for c_email, c in contact_email_map.items():
                if c_email in recipient.lower():
                    matched_contact = c
                    break
                    
        # 2. Match by First / Last Name if no email match
        if not matched_contact:
            search_str = f"{sender_name} {recipient}".lower()
            for c_entry in contact_name_list:
                c_parts = c_entry["parts"]
                if len(c_parts) >= 2:
                    if all(part in search_str for part in c_parts):
                        matched_contact = c_entry["contact"]
                        break
        
        if matched_contact:
            matched_emails_count += 1
            cid = matched_contact.get("id")
            
            # Auto-Enrichment if contact email is missing and sender_email is valid
            if not matched_contact.get("email") and is_valid_contact_email(sender_email):
                if update_contact_email(cid, sender_email):
                    enriched_emails_count += 1
                    matched_contact["email"] = sender_email
                    contact_email_map[sender_email] = matched_contact
                    print(f"  [+] Auto-Enrichment: E-Mail '{sender_email}' für Kontakt '{matched_contact.get('name')}' eingetragen.")

            # Create history message card
            is_outbound = mail.get("type") == "outbound"
            email_card = {
                "id": mail.get("messageId") or str(hash(subject + mail.get("timestamp", ""))),
                "type": "email",
                "sender": "user" if is_outbound else "kontakt",
                "text": f"✉️ Betreff: {subject}\n\n{body}",
                "timestamp": mail.get("timestamp") or "",
                "messageId": mail.get("messageId")
            }
            append_email_to_history(cid, email_card)
        else:
            search_text = f"{sender_name} {sender_email} {subject} {body}".lower()
            if any(kw in search_text for kw in business_keywords):
                unmatched_emails.append({
                    "sender_name": sender_name,
                    "sender_email": sender_email,
                    "recipient": recipient,
                    "subject": subject,
                    "snippet": body[:300],
                    "timestamp": mail.get("timestamp"),
                    "relevance_reason": "Bewerbung/HR/Einkauf/Geschäftskontakt"
                })

    save_potential_contacts(unmatched_emails)
    print(f"\n================ ABGLEICH ERFOLGREICH BEENDET ================")
    print(f"  • Verarbeitete Outlook-Mails: {len(emails)}")
    print(f"  • Erfolgreich gematchte Mails: {matched_emails_count}")
    print(f"  • Auto-Enrichment (neue E-Mail-Adressen): {enriched_emails_count}")
    print(f"  • Ungematchte relevante Kontakte in 'potenzielle_neukontakte.json': {len(unmatched_emails)}")

if __name__ == "__main__":
    run_matching()
