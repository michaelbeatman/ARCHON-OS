# DSGVO-Betroffenenrechte (Art. 15 & Art. 17) in Archon OS

Dieses Dokument beschreibt die Architektur und Bedienung der Betroffenenrechte-Engine (`backend/gdpr_compliance_engine.py`) gemäß Datenschutz-Grundverordnung (DSGVO).

## 1. Gesetzliche Grundlagen & Abdeckung

Archon OS speichert Nutzerdaten über mehrere relationale und dokumentenbasierte Schichten. Die Compliance-Engine deckt Anfragen nach Auskunft und Löschung/Anonymisierung zentral ab:

- **Art. 15 DSGVO (Auskunftsrecht):**
  Exportiert alle mit der Person verknüpften Datensätze als maschinenlesbares JSON-Dossier (Kanban-Tasks, Chatverläufe, Langzeit-Learnings, CRM-Kontakte, verknüpfte Notizen).
- **Art. 17 DSGVO (Recht auf Vergessenwerden / Löschung):**
  Löscht oder anonymisiert personenbezogene Daten (`[ANONYMISIERT_DSGVO_ART17]`). Das Löschen erfolgt atomar über die SQLite-Datenbanken und PocketBase.
- **Art. 30 DSGVO (Nachweispflicht & Audit-Log):**
  Zur Beweisbarkeit wird für jede Löschung eine kryptografische Quittung erzeugt. Diese enthält den SHA-256-Hash des Identifikators (niemals Klartext-PII) und wird in einer Hash-Kette (`gdpr_audit_log`) in `agentic_memory.db` unveränderlich festgehalten.

---

## 2. Abgedeckte Datenspeicher

| Speicher | Datei / Service | Art. 15 Export | Art. 17 Löschung / Anonymisierung |
| :--- | :--- | :--- | :--- |
| **Kanban Engine** | `kanban.db` | Titel, Beschreibung, Resultat | Textuelle Anonymisierung in Tasks |
| **Chat & Sessions** | `state.db` | Nachrichten (`messages`) | Content-Anonymisierung |
| **Agenten-Gedächtnis** | `agentic_memory.db` | `learnings`, `human_feedback` | Zusammenfassungen & Feedback bereinigen |
| **CRM Kontakte** | PocketBase (`/api/collections/kontakte`) | Kontaktdaten, E-Mail, Firma | Records löschen / bereinigen |
| **Obsidian Vault** | Markdown-Dateien | Dateinamen- & Volltextsuche | Manuelle Revision / Bereinigungsliste |

---

## 3. REST-Schnittstellen

Die Endpunkte stehen unter `/api/operations/gdpr` zur Verfügung:

### `POST /api/operations/gdpr/export`
Erstellt ein vollständiges Datendossier für eine betroffene Person.

```json
// Request Body
{
  "identifier": "max.mustermann@example.com"
}

// Response
{
  "status": "success",
  "export": {
    "requested_identifier": "max.mustermann@example.com",
    "export_timestamp": "2026-10-31T04:15:00",
    "legal_basis": "Art. 15 DSGVO (Auskunftsrecht)",
    "sources": {
      "kanban_tasks": [],
      "chat_messages": [],
      "memory_learnings": [],
      "feedback_and_evals": [],
      "crm_contacts": [],
      "obsidian_notes": []
    },
    "total_records_found": 0
  }
}
```

### `POST /api/operations/gdpr/erase`
Führt eine Bereinigung nach Art. 17 aus. Unterstützt Simulationsmodus (`dry_run=true`).

```json
// Request Body
{
  "identifier": "max.mustermann@example.com",
  "dry_run": false,
  "anonymize": true
}

// Response
{
  "status": "success",
  "result": {
    "requested_identifier": "max.mustermann@example.com",
    "dry_run": false,
    "mode": "anonymize",
    "timestamp": "2026-10-31T04:15:57",
    "affected": {
      "kanban_tasks": 1,
      "chat_messages": 3,
      "memory_learnings": 0,
      "feedback_entries": 0,
      "crm_contacts": 1
    },
    "total_affected": 5,
    "receipt": {
      "receipt_id": "gdpr-rcpt-477d76bd",
      "timestamp": "2026-10-31 04:15:57",
      "action": "ERASE_ART17",
      "identifier_hash": "221c266da850f1270a2f04bbc13ad3cadea25daaaa75d9b5fcac53d51db849d2",
      "records_affected": 5,
      "prev_hash": "GENESIS",
      "hash": "595530dcc630224bb93311233741168014880e493587e3b3f3021f7c0f8a1ca0"
    }
  }
}
```

### `GET /api/operations/gdpr/audit-log`
Liefert die Liste aller ausgestellten Löschquittungen für Nachweiszwecke bei Aufsichtsbehörden.

---

## 4. Hash-Ketten-Verifikation

Jede Löschquittung berechnet einen SHA-256-Hash über:
`SHA-256(prev_hash + receipt_id + action + identifier_hash + records_affected + details_json + timestamp)`

Dadurch lässt sich nachträglich mathematisch beweisen, dass kein Audit-Eintrag manipuliert, gelöscht oder eingefügt wurde.
