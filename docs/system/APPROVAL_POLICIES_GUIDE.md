# GoBD/ISO 27001 Approval-Policies & Freigaberegeln (Archon OS 2026)

Dieses Modul stellt ein revisionssicheres, mehrstufiges Freigabesystem für Archon OS bereit. Es automatisiert Routinefreigaben unterhalb von Wertgrenzen, erzwingt ein Vier-Augen-Prinzip bei Beträgen über Schwellenwerten, überwacht Eskalationsfristen (24 Stunden) und protokolliert jede Regel- sowie Statusänderung in einer manipulationssicheren SHA-256 Hash-Kette.

---

## 1. Übersicht & Benutzeroberfläche

Die Ansicht ist in der Seitenleiste unter **„Infrastruktur & Governance“** an zweiter Stelle platziert:
1. **Rechnungswesen** (Belege & Finanzen)
2. **Approval-Policies** (Schwellen & Freigaben)
3. **LLM Gateway** (OmniRoute)
4. **Token Guard** (Raten- & Budgetwächter)
5. **Telemetrie & Logs** (Live-Audit)

### Header & Subtabs (2-Element-Design, 80px)
- **Status-Pulse:** Zeigt den aktuellen System- und Kettengesundheitsstatus.
- **Urlaubsmodus-Schalter:** Direkter Toggle im Header mit Auswahl des Vertreters (z. B. Katharina Völk für QM/Compliance oder Robert für CEO/Strategie).
- **GoBD SHA-256 Badge:** Ein Klick prüft die mathematische Integrität der gesamten Revisionskette.
- **Drei Fach-Subtabs (72px Cadre-Kacheln):**
  1. **Finanzen:** Auto-Freigabe bis 50 €, Vier-Augen-Prinzip ab 500 €, 24h-Eskalationsfrist.
  2. **Kommunikation & E-Mail:** Freigabepflicht für KI-Antwortentwürfe, 12h-Frist, Domain-Whitelist.
  3. **System & IT:** API-Keys mit Scopes, Notfall-Bypass (Emergency Override), IT-Fristen.

---

## 2. Revisionssicherheit & GoBD/ISO-Konformität

Jede Konfigurationsänderung und jede Freigabeaktion (Erteilung, Ablehnung, Urlaubsdelegation) wird in `approval_policy_audit_chain` in der SQLite-Datenbank append-only abgelegt:

$$\text{hash}_n = \text{SHA256}(\text{hash}_{n-1} \,\|\, \text{timestamp} \,\|\, \text{user\_id} \,\|\, \text{action} \,\|\, \text{payload})$$

Dadurch ist jede nachträgliche Manipulation eines Schwellenwerts oder einer Freigabe sofort als Kettenbruch identifizierbar.

---

## 3. REST-API-Endpunkte

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/operations/approvals/policies` | Ruft alle aktiven Schwellen und Richtlinien ab |
| `POST` | `/api/operations/approvals/policies` | Ändert einen Schwellenwert revisionssicher |
| `GET` | `/api/operations/approvals/requests` | Liste aller Freigabeanfragen (Queue) |
| `POST` | `/api/operations/approvals/requests` | Neue Anfrage einstellen & Schwellen prüfen |
| `POST` | `/api/operations/approvals/requests/{id}/approve` | Freigabe erteilen (1. oder 2. Prüfer) |
| `POST` | `/api/operations/approvals/requests/{id}/reject` | Anfrage mit Begründung ablehnen |
| `GET` | `/api/operations/approvals/delegation` | Status des Urlaubsmodus abfragen |
| `POST` | `/api/operations/approvals/delegation` | Urlaubsmodus aktivieren/deaktivieren |
| `GET` | `/api/operations/approvals/audit-chain` | Die letzten Kettenglieder des Audit-Logs abrufen |
| `GET` | `/api/operations/approvals/audit-verify` | Vollständige mathematische Kettenprüfung ausführen |
