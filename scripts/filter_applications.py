import json
import csv
import re
import os

INPUT_FILE = "potenzielle_neukontakte.json"
OUTPUT_FILE = "bewerbungen_potenziell.csv"

# Schlagwort-Matrix für Bewerbungskontext
BEWERBUNGS_KEYWORDS = [
    r"bewerbung", r"vakanz", r"stelle", r"position", r"einkauf", r"geschäftsführ",
    r"absage", r"einladung", r"interview", r"recruit", r"\bhr\b", r"headhunter",
    r"executive search", r"lebenslauf", r"unterlagen", r"interim", r"mandat",
    r"kandidat", r"profil", r"erstgespräch", r"gehalt", r"vertragsentwurf"
]

KEYWORD_REGEX = re.compile("|".join(BEWERBUNGS_KEYWORDS), re.IGNORECASE)

def filter_and_export_to_csv():
    if not os.path.exists(INPUT_FILE):
        if os.path.exists(os.path.join("..", INPUT_FILE)):
            input_path = os.path.join("..", INPUT_FILE)
        else:
            print(f"[-] Datei '{INPUT_FILE}' wurde nicht gefunden.")
            return
    else:
        input_path = INPUT_FILE

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    filtered_mails = []

    for item in data:
        subject = item.get("subject", "")
        text = item.get("snippet", "") or item.get("text", "")
        sender_name = item.get("sender_name", "")
        sender_email = item.get("sender_email", "")

        combined_content = f"{subject} {text} {sender_name} {sender_email}"

        # Prüfen ob Keyword matcht
        if KEYWORD_REGEX.search(combined_content):
            filtered_mails.append({
                "Typ": item.get("type", "inbound"),
                "Absender/Empfänger Name": sender_name or item.get("recipient_name", ""),
                "E-Mail-Adresse": sender_email or item.get("recipient", ""),
                "Datum": item.get("timestamp", ""),
                "Betreff": subject,
                "Auszug": text[:300].replace("\n", " ").replace("\r", " ")  # Für saubere CSV-Darstellung
            })

    # Schreiben der CSV-Datei (Excel-kompatibel mit UTF-8 Sig)
    fieldnames = ["Typ", "Absender/Empfänger Name", "E-Mail-Adresse", "Datum", "Betreff", "Auszug"]
    
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        for row in filtered_mails:
            writer.writerow(row)

    print(f"[+] Erfolgreich {len(filtered_mails)} bewerbungsrelevante Mails in '{OUTPUT_FILE}' exportiert.")

if __name__ == "__main__":
    filter_and_export_to_csv()
