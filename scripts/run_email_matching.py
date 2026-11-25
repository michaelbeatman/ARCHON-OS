"""CRM-/Outlook-Abgleich mit ehrlichem Sync-Status (W4-B, Eskalation W2-B).

Frueher wurde am Ende unconditionally "ABGLEICH ERFOLGREICH BEENDET" gedruckt —
auch wenn PocketBase oder Outlook nicht erreichbar waren oder Schreibfehler
auftraten. Der Status kommt jetzt aus den strukturierten Sync-Ergebnissen
(``status``/``error_code``) und den tatsaechlichen Schreibergebnissen.
"""

import json
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# W2-B hat scripts/archon_crm_mcp.py auf strukturierte Ergebnisse umgestellt;
# das Root-Modul liefert weiterhin nur leere Listen. Bewusst das strukturierte
# Modul verwenden, damit "leer" nicht mit "Fehler" verwechselt wird.
from scripts.archon_crm_mcp import (  # noqa: E402
    get_all_contacts,
    fetch_local_outlook_emails,
    update_contact_email,
    append_email_to_history,
    save_potential_contacts,
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


def _status(result) -> str:
    """Status aus dem strukturierten Sync-Ergebnis (statt 'immer Erfolg')."""
    if isinstance(result, dict):
        return str(result.get("status") or "ok").strip().lower()
    return "ok"  # Legacy-Listen: kein Fehler-Signal vorhanden


def _error_code(result) -> str:
    if isinstance(result, dict):
        return str(result.get("error_code") or "").strip()
    return ""


def _items(result, key: str) -> list:
    """Liste aus dem strukturierten Ergebnis (nicht aus dict-Keys) ziehen."""
    if isinstance(result, dict):
        return list(result.get(key) or [])
    return list(result or [])


def run_matching() -> dict:
    errors = []

    print("[1/3] Lade Kontakte aus PocketBase...")
    contacts_result = get_all_contacts()
    contacts = _items(contacts_result, "contacts")
    print(f"  -> {len(contacts)} Kontakte geladen.")
    if _status(contacts_result) == "error":
        errors.append(f"contacts: {_error_code(contacts_result) or 'CRM_FETCH_FAILED'}")

    print("[2/3] Lade Mails aus Outlook...")
    emails_result = fetch_local_outlook_emails(limit=300)
    emails = _items(emails_result, "emails")
    print(f"  -> {len(emails)} Mails aus Outlook ausgelesen.")
    if _status(emails_result) == "error":
        errors.append(f"outlook: {_error_code(emails_result) or 'OUTLOOK_IMPORT_FAILED'}")

    print("[3/3] Starte Abgleich & Auto-Enrichment...")

    contact_email_map = {}
    contact_name_list = []

    for c in contacts:
        cid = c.get("id")
        c_email = (c.get("email") or "").strip().lower()
        c_name = (c.get("name") or "").strip()

        # Clean up any bad system emails if previously set
        if c_email and not is_valid_contact_email(c_email):
            if not update_contact_email(cid, ""):
                errors.append(f"cleanup_email: {cid}")
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
                else:
                    errors.append(f"enrichment: {cid}")

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
            if not append_email_to_history(cid, email_card):
                errors.append(f"history: {cid}")

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

    try:
        save_potential_contacts(unmatched_emails)
    except Exception as exc:
        errors.append(f"potential_contacts: {exc}")

    # Ehrlicher Gesamtstatus: nur wenn alle Quellen ok sind und keine
    # Schreibfehler auftraten, darf "ERFOLGREICH" erscheinen.
    if errors:
        status = "error" if any(
            e.startswith(("contacts:", "outlook:")) for e in errors
        ) else "partial"
    else:
        status = "success"

    banner = {
        "success": "ABGLEICH ERFOLGREICH BEENDET",
        "partial": "ABGLEICH TEILWEISE FEHLGESCHLAGEN",
        "error": "ABGLEICH FEHLGESCHLAGEN",
    }[status]
    print(f"\n================ {banner} ================")
    print(f"  • Status: {status}")
    print(f"  • Verarbeitete Outlook-Mails: {len(emails)}")
    print(f"  • Erfolgreich gematchte Mails: {matched_emails_count}")
    print(f"  • Auto-Enrichment (neue E-Mail-Adressen): {enriched_emails_count}")
    print(f"  • Ungematchte relevante Kontakte in 'potenzielle_neukontakte.json': {len(unmatched_emails)}")
    if errors:
        print(f"  • Fehler ({len(errors)}): {'; '.join(errors[:5])}")

    return {
        "status": status,
        "errors": errors,
        "contacts": len(contacts),
        "emails": len(emails),
        "matched": matched_emails_count,
        "enriched": enriched_emails_count,
        "unmatched": len(unmatched_emails),
    }


if __name__ == "__main__":
    sys.exit(0 if run_matching()["status"] == "success" else 1)
