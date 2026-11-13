# Beleg- und Quittungserfassung per Foto über Telegram in Archon OS

Dieses Handbuch beschreibt die Architektur und Bedienung der Belegverarbeitung (`backend/receipt_ocr_engine.py`) zur automatisierten Extrahierung und Buchung von Quittungen.

---

## 1. Funktionsweise & Ablauf

1. **Eingang:**
   - Der Nutzer sendet ein Foto (Quittung, Tankbeleg, Bewirtungsbeleg) oder ein PDF-Dokument an den Archon Telegram-Bot.
   - Der Telegram-Adapter spiegelt den Beleg in `/opt/data/inbox/telegram/` und markiert ihn als `is_receipt_candidate`.
2. **Vision OCR Extraktion:**
   - Das Bild wird multimodal an OmniRoute (`auto/best-vision`) übergeben.
   - Folgende Attribute werden strukturiert extrahiert:
     - **Aussteller/Händler** (z. B. *Rewe Markt GmbH*, *Shell Station*, *Deutsche Bahn*)
     - **Belegdatum** (ISO-Format `YYYY-MM-DD`)
     - **Bruttobetrag & Währung** (z. B. `45.80 EUR`)
     - **MwSt-Satz & Steuerbetrag** (z. B. `19%`, `7.31 EUR`)
     - **Kategorie** (*Bewirtung*, *Reisekosten*, *Büromaterial*, *Tanken*, *IT-Hardware*, etc.)
     - **Zahlungsmethode** (*Kreditkarte*, *EC*, *Bar*, *PayPal*)
     - **Einzelpositionen** mit Namen und Preisen
3. **Persistenz & Buchhaltung:**
   - Das Originalbild wird revisionssicher unter `/opt/data/inbox/receipts/{receipt_id}.jpg` archiviert.
   - Die Metadaten werden in der SQLite-Tabelle `receipts` in `agentic_memory.db` und als Sidecar-JSON gespeichert.
   - Automatisch wird eine Aufgabe in `kanban.db` für das Finanzteam (`finance_lead`) angelegt:
     `[Beleg] {Händler}: {Betrag} EUR ({Kategorie})`.

---

## 2. REST-API-Schnittstellen

Unter `/api/operations/receipts` stehen Endpunkte für Web-Upload und Einsicht bereit:

### `POST /api/operations/receipts/process`
Nimmt Belege per Base64 oder Dateipfad entgegen.

```json
// Request Body
{
  "image_base64": "data:image/jpeg;base64,/9j/4AAQSkZJRg...",
  "filename": "tanken_shell.jpg",
  "sender": "@micha",
  "source": "telegram",
  "create_kanban_task": true
}

// Response
{
  "status": "success",
  "receipt": {
    "receipt_id": "rcpt_1793421187_a1b2c3",
    "merchant": "Shell Tankstelle",
    "date": "2026-10-31",
    "amount_gross": 78.50,
    "currency": "EUR",
    "tax_amount": 12.53,
    "tax_rate_pct": 19.0,
    "category": "Tanken",
    "payment_method": "Kreditkarte",
    "kanban_task_id": "task-rcpt_1793421187_a1b2c3"
  }
}
```

### `GET /api/operations/receipts`
Listet die letzten archivierten Belege auf.
