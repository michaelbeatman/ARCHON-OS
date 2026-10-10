import csv
import re
from archon_crm_mcp import fetch_local_outlook_emails

APPLICATION_KEYWORDS = [
    "bewerb", "candidate", "stelle", "stellenangebot", "position",
    "applicant", "lebenslauf", "cv", "absage", "einladung", "job",
    "karriere", "apply", "recruiting", "recruiter", "talent",
    "interim", "manager", "headoffice", "personal"
]

def export_application_emails():
    print("Lade alle Mails aus Outlook...")
    emails = fetch_local_outlook_emails(limit=1000)
    print(f" -> {len(emails)} Mails geladen.")

    application_emails = []

    for mail in emails:
        subject = mail.get("subject") or ""
        body = mail.get("text") or ""
        sender_name = mail.get("sender_name") or ""
        sender_email = mail.get("sender_email") or ""
        recipient = mail.get("recipient") or mail.get("recipient_name") or ""
        msg_type = "Eingehend" if mail.get("type") == "inbound" else "Ausgehend"
        timestamp = mail.get("timestamp") or ""

        search_text = f"{subject} {body} {sender_name}".lower()

        if any(kw in search_text for kw in APPLICATION_KEYWORDS):
            snippet = body.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
            snippet = re.sub(r'\s+', ' ', snippet)[:250]

            application_emails.append({
                "Typ": msg_type,
                "Absender Name": sender_name,
                "Absender E-Mail": sender_email,
                "Empfänger": recipient,
                "Betreff": subject,
                "Datum": timestamp,
                "Ausschnitt (Snippet)": snippet
            })

    output_csv_path = "bewerbungen_potenzielle_kontakte.csv"
    with open(output_csv_path, "w", encoding="utf-8-sig", newline="") as f:
        fieldnames = ["Typ", "Absender Name", "Absender E-Mail", "Empfänger", "Betreff", "Datum", "Ausschnitt (Snippet)"]
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(application_emails)

    print(f"\n================ EXPORT ERFOLGREICH BEENDET ================")
    print(f"  • Ausgefilterte Bewerbungs-Mails: {len(application_emails)}")
    print(f"  • Datei gespeichert unter: {output_csv_path}")

if __name__ == "__main__":
    export_application_emails()
