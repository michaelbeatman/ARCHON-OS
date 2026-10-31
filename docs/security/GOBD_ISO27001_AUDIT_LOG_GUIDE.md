# Revisionssicheres Audit-Log (GoBD & ISO/IEC 27001)

Dieses Dokument beschreibt die Architektur, kryptografische Verifikation und Handhabung des unveränderlichen Audit-Logs in Archon OS.

---

## 1. Übersicht & Zielsetzung

Unternehmen unterliegen strengen regulatorischen Vorgaben bezüglich der Nachvollziehbarkeit automatisierter System- und Finanzentscheidungen (GoBD § 146 AO, ISO/IEC 27001 Control A.12.4, EU AI Act Art. 12). 

Das Audit-Log von Archon OS (`backend/audit_log.py`) garantiert:
- **Lückenlose Protokollierung:** Jede Systemaktion, Agentenentscheidung, Freigabe und Konfigurationsänderung wird erfasst.
- **Unveränderlichkeit (Tamper-Proofing):** Einträge sind über kryptografische SHA-256 Hashketten (Blockchain-Prinzip) miteinander verkettet.
- **Prüfer-Konformität:** Direkter 1-Klick-Export für Wirtschaftsprüfer und Datenschutzbeauftragte als JSON oder CSV.

---

## 2. Kryptografische Hashkette (Merkle-Verkettung)

Jeder Logeintrag berechnet seinen eigenen Hash aus seinen Nutzdaten sowie dem Hash des unmittelbar vorhergehenden Eintrags:

$$\text{Current Hash} = \text{SHA-256}(\text{Index} \parallel \text{Timestamp} \parallel \text{Category} \parallel \text{Action} \parallel \text{Actor} \parallel \text{Previous Hash} \parallel \text{Payload Hash})$$

### Datenstruktur in `data/audit_log.json` / SQLite:
```json
{
  "index": 142,
  "timestamp": "2026-10-31T10:45:12Z",
  "category": "FINANCE",
  "action": "PAYMENT_RELEASED",
  "actor": "katharina_voelk",
  "target": "invoice_2026_089",
  "details": {
    "amount_eur": 1450.00,
    "recipient": "Cloud Hosting GmbH",
    "approval_id": "appr_789"
  },
  "previous_hash": "a3f5b8c9e2d14781...",
  "entry_hash": "e7c2a104b99f8d34..."
}
```

Wenn ein Angreifer oder ein technischer Fehler einen vergangenen Eintrag manipuliert oder löscht, bricht die Hashkette an dieser Stelle ab. Die Manipulationserkennung lokalisiert exakt den ersten verfälschten Block.

---

## 3. REST-API & Verifizierungs-Endpunkte

| Methode | Pfad | Beschreibung |
|---|---|---|
| `GET` | `/api/governance/audit-log` | Ruft paginierte Audit-Einträge ab (Filter: `category`, `actor`, `limit`). |
| `GET` | `/api/governance/audit-log/verify` | Führt eine vollständige kryptografische Hashprüfung aller Einträge durch. |
| `GET` | `/api/governance/audit-log/export?format=json\|csv` | Generiert den offiziellen Prüfbericht für Auditoren. |

### Beispiel: Integritätsprüfung per Terminal
```bash
curl -s http://127.0.0.1:8501/api/governance/audit-log/verify
```
*Antwort:*
```json
{
  "status": "valid",
  "total_records": 1845,
  "tampered_records": 0,
  "genesis_hash": "0000000000000000000000000000000000000000000000000000000000000000",
  "latest_hash": "c88f1b2190da753c..."
}
```

---

## 4. Bedienung im Web-Interface (Telemetrie & Log-Stream)

1. Navigiere in der linken Seitenleiste zu **Telemetrie & Logs**.
2. Wähle den Reiter **GoBD / Revisions-Log**.
3. **Kategorie-Pills:** Filtere nach `ALL`, `SECURITY`, `FINANCE`, `AGENT_ACTION`, `APPROVAL`, `SYSTEM`.
4. **Suchfeld:** Durchsuche Einträge nach Akteur, Aktionsname oder Datensatz-ID.
5. **Detail-Modal:** Klicke auf eine Zeile, um die Rohdaten, den Hash und den `previous_hash` forensisch zu prüfen.
6. **Prüfbericht exportieren:** Klicke oben rechts auf **Exportieren** (`JSON` oder `CSV (Prüfer-Format)`).
