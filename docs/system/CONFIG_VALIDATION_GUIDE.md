# Archon OS – Pre-Flight Konfigurationsprüfung & Schema-Validator

*Stand: Oktober 2026 | Resilienz & Säule 6 / Zero-Trust Governance*

---

## 1. Übersicht & Zielsetzung

In einem agentischen Betriebssystem mit 57 Fachrollen, dynamischen Hierarchien und komplexen Tool-Berechtigungen sind Konfigurationsfehler ein häufiger Ausfallgrund:
- Fehlende Kommas oder ungültige JSON-Syntax in `agent_profiles.json` oder `settings.json`
- Verwaiste Knoten-IDs im Organigramm (`config/org_hierarchy.json`), die keinem Agenten zugeordnet sind
- Ungültige Port- oder Host-Definitionen in `.env`
- Fehlende oder fehlerhaft typisierte Concurrency-Grenzwerte

Der **Pre-Flight Config Validator** ([`backend/config_validator.py`](../../backend/config_validator.py)) prüft die gesamte Konfigurationslandschaft vor dem Systemstart oder auf Abruf im laufenden Betrieb.

---

## 2. Geprüfte Systemdateien

| Konfigurationsdatei | Prüfkriterien & Validierung |
| :--- | :--- |
| `settings.json` | JSON-Syntax, Pflichtabschnitte (`concurrency`, `fleet_and_hygiene`, `zero_egress_governance`), Grenzwerte für parallele Worker (1–32). |
| `data/privacy_routing.json` | Zero-Egress-Prüfung (`verify_zero_egress_config`): `local_llm_url` muss zwingend auf `LOCAL_ON_PREM` zeigen, `hard_block_on_local_offline` und Pflichtkategorien (`finance`, `contracts`, `crm`). |
| `agent_profiles.json` | Eindeutigkeit aller Profil-IDs (keine Dubletten), Pflichtfelder (`id`, `name`, `status`, Prompts). |
| `config/teams.json` | Konsistenz der Teams und Verknüpfung der `lead_id` mit existierenden Agenten. |
| `config/org_hierarchy.json` | Vollständigkeit von `nodes` und `links`, Warnungen bei unregistrierten Knoten. |
| `.env` | Vorhandensein, Validierung von `PORT` (Zahlenwert 1–65535) und `HOST`. |

---

## 3. Ausführung & CLI-Kommando

Der Validator kann jederzeit manuell im Terminal ausgeführt werden:
```bash
python scripts/validate_config.py
```
Beispielausgabe:
```text
======================================================================
  Archon OS – Pre-Flight Konfigurations- & Konsistenz-Prüfung
======================================================================
Status:       [OK] GÜLTIG
Fehler:       0
Warnungen:    8
----------------------------------------------------------------------
Stats:
  - settings       : {'sections': 37}
  - profiles       : {'total_profiles': 57}
  - org_hierarchy  : {'nodes_count': 64, 'links_count': 63}
======================================================================
Pre-Flight Check erfolgreich abgeschlossen. System ist startbereit.
```

---

## 4. REST-API Endpunkt

| Endpunkt | Methode | Beschreibung |
| :--- | :--- | :--- |
| `/api/operations/config/validate` | `GET` | Führt die Validierung zur Laufzeit aus und liefert Fehler-, Warnungs- und Statistik-Objekte. |
