# E-Signatur & Vertragsverwaltung (DocuSeal self-hosted) in Archon OS

Dieses Handbuch beschreibt die Einrichtung und den Betrieb der selbstgehosteten elektronischen Signaturlösung DocuSeal (`backend/docuseal_client.py`) für Verträge, Geheimhaltungsvereinbarungen (NDAs) und Vollmachten.

---

## 1. Architektur & Compose-Integration

DocuSeal läuft isoliert im Docker-Netzwerk `agentic_mesh`:

- **Container-Name:** `docuseal-esign`
- **Profil:** `esign` / `legal`
- **Host-Port:** `http://localhost:3080` (Container-Port 3000)
- **Persistenz:** Docker Volume `docuseal_data` (`/data/docuseal.sqlite3`)
- **Archon Integration:** `backend/docuseal_client.py` synchronisiert Signatur-Zustände automatisch mit `kanban.db` und `agentic_memory.db`.

---

## 2. Starten des Dienstes

```bash
# DocuSeal starten
docker compose --profile esign up -d docuseal

# Status und Health prüfen
docker compose --profile esign ps docuseal

# Beenden
docker compose --profile esign stop docuseal
```

---

## 3. Vertrags-Workflow & Automatisierung

1. **Vertragsanlage (Legal Counsel / Rechtsteam):**
   - Das Rechtsteam oder ein Agent initiiert eine Signaturanfrage via API oder Kanban.
   - Ein Signatur-Link wird generiert (`http://localhost:3080/s/{submission_id}`).
   - Ein Kanban-Task wird unter Team `Recht` angelegt: `[E-Signatur] NDA Partner GmbH (Max Mustermann)`.
2. **Unterzeichnung:**
   - Der Vertragspartner öffnet den Link im Browser und unterzeichnet digital.
3. **Webhook & Rückfluss:**
   - DocuSeal sendet nach erfolgreicher Signatur einen Webhook an `POST /api/operations/esign/webhook`.
   - Der verknüpfte Task in `kanban.db` wird automatisch auf `done` gesetzt (`Vollständig digital unterzeichnet via DocuSeal`).
   - Im NotificationHub wird eine Benachrichtigung an das Team gesendet.

---

## 4. REST-API-Schnittstellen

Unter `/api/operations/esign` stehen drei Endpunkte bereit:

### `POST /api/operations/esign/submissions`
Erstellt eine neue Signaturanfrage.

```json
// Request Body
{
  "title": "Auftragsverarbeitungsvertrag (AVV) 2026",
  "signer_name": "Erika Musterfrau",
  "signer_email": "erika@beispiel.de"
}

// Response
{
  "status": "success",
  "submission": {
    "submission_id": "sub_1793421187_f4e2a1",
    "title": "Auftragsverarbeitungsvertrag (AVV) 2026",
    "signer_name": "Erika Musterfrau",
    "signer_email": "erika@beispiel.de",
    "sign_url": "http://127.0.0.1:3080/s/sub_1793421187_f4e2a1",
    "kanban_task_id": "task-esign-sub_1793421187_f4e2a1"
  }
}
```

### `GET /api/operations/esign/contracts`
Listet alle versandten und unterzeichneten Verträge auf.

### `POST /api/operations/esign/webhook`
Empfängt Webhooks von DocuSeal bei Statusänderungen.
