# API-Keys, Scopes & Rate-Limits (t-6fad7a)

## 1. Übersicht & Zweck
Archon OS stellt eine revisionssichere Governance-Schicht für externe Schnittstellen bereit. Über das System Control Center (Settings -> **API-KEYS & ACCESS**) können kryptografische Tokens für Automatisierungsdienste (z. B. n8n), Messenger-Bots (Telegram) und MCP-Clients generiert und verwaltet werden.

---

## 2. Rechtssicherheit & GoBD / ISO 27001 Konformität
1. **Einmalanzeige (Zero-Plaintext-Persistence):**
   * Der Klartext-Token (`archon_live_<48-hex-zeichen>`) wird dem Nutzer **exakt einmalig** in einem modalen Kopier-Dialog präsentiert.
   * In der Datenbank (`agentic_memory.db`) wird ausschließlich ein kryptografischer SHA-256 Hash (`KEY_SALT:raw_token`) gespeichert. Selbst bei einem unbefugten Datenbankabzug existieren keine Klartext-Zugangsdaten.
2. **Kryptografische SHA-256 Audit-Kette:**
   * Jede Schlüsselerstellung (`KEY_CREATED`), Deaktivierung (`KEY_REVOKED`) und Löschung (`KEY_DELETED`) wird mit Zeitstempel, Nutzer-ID und Vorgänger-Hash in der Tabelle `api_key_audit_log` unveränderlich verkettet.

---

## 3. Berechtigungs-Scopes
| Scope | Beschreibung | Anwendungsfall |
|---|---|---|
| `read_only` | Nur lesender Zugriff auf Status, Telemetrie, Logs und Agentenprofile | Externe Monitoring-Dashboards, Prometheus-Exporte |
| `kanban_rw` | Karten lesen, anlegen, verschieben und aktualisieren | n8n Webhook-Workflows, externe Ticket-Syncs |
| `agent_execute` | Ausführung von Agenten-Aufträgen und Chat-Interaktionen | Telegram-Bot, Voice-Clients, Remote-Agent-Dispatcher |
| `admin_full` | Uneingeschränkter Administratorzugriff auf alle System-APIs | Betreiber-Skripte, Disaster-Recovery-Tools |

---

## 4. Rate-Limiting (Sliding Window)
* **RPM (Requests per Minute):** Maximal zulässige Anfragen in einem rollenden 60-Sekunden-Fenster (Standard: `60`, `0` = unbegrenzt).
* **RPD (Requests per Day):** Maximal zulässige Anfragen pro Tag (Standard: `5.000`, `0` = unbegrenzt).
* Bei Überschreitung antwortet das System mit `HTTP 429 Too Many Requests`.

---

## 5. REST-API Endpunkte
* `GET /api/operations/keys`: Liste aller registrierten Keys (ohne Token oder Hash)
* `POST /api/operations/keys`: Neuer Key (liefert `raw_token` einmalig zurück)
* `POST /api/operations/keys/{key_id}/revoke`: Key sofort unwiderruflich sperren
* `DELETE /api/operations/keys/{key_id}`: Key aus der Liste entfernen (Audit bleibt erhalten)
* `GET /api/operations/keys/audit`: Revisionssichere SHA-256 Kette abrufen
