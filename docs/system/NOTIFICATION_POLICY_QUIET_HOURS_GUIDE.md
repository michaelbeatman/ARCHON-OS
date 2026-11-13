# Benachrichtigungs-Richtlinien & Ruhezeiten (Notification Policy & Quiet Hours)

## Überblick
Archon OS verfügt über ein zentrales Benachrichtigungs-Routing (`backend/notification_hub.py`). Es steuert, welche Alarme und Ereignisse zu welchen Zeiten über welche Kanäle (Web-UI Feed, Telegram, Webhook) zugestellt werden.

Zur Vermeidung von nächtlicher Alarm-Müdigkeit (Alert Fatigue) und Ruhestörungen unterdrückt das System während konfigurierbarer Ruhezeiten automatische Push-Nachrichten für nicht-kritische Vorfälle und puffert diese für den morgendlichen Standup-Digest.

---

## Konfiguration

Die Einstellungen werden in `settings.json` im Block `notification_policy` verwaltet und greifen zur Laufzeit:

```json
{
  "notification_policy": {
    "enabled": true,
    "quiet_hours_enabled": true,
    "quiet_hours_start": "22:00",
    "quiet_hours_end": "07:00",
    "timezone": "Europe/Berlin",
    "allow_critical_during_quiet_hours": true,
    "telegram_enabled": true,
    "telegram_min_severity": "WARNING",
    "digest_enabled": true,
    "digest_delivery_time": "08:00",
    "min_severity": "low"
  }
}
```

### Parameter

| Schlüssel | Typ | Standard | Beschreibung |
|---|---|---|---|
| `enabled` | bool | `true` | Globale Aktivierung des Benachrichtigungssystems. |
| `quiet_hours_enabled` | bool | `true` | Aktiviert die Zeitfenster-Prüfung für Ruhezeiten. |
| `quiet_hours_start` | str | `"22:00"` | Beginn der Ruhezeit (HH:MM). |
| `quiet_hours_end` | str | `"07:00"` | Ende der Ruhezeit (HH:MM, unterstützt Nachtsprung). |
| `allow_critical_during_quiet_hours` | bool | `true` | Alarme mit Schweregrad `CRITICAL` durchbrechen die Ruhezeit sofort. |
| `telegram_enabled` | bool | `true` | Steuert den Telegram-Push-Kanal. |
| `telegram_min_severity` | str | `"WARNING"` | Minimaler Schweregrad für Push (`WARNING`, `CRITICAL`). |
| `digest_enabled` | bool | `true` | Fasst unterdrückte Meldungen für das Morgen-Briefing zusammen. |

---

## Eskalations- und Dämpfungslogik

```
[Ereignis / Alarm ausgelöst]
           │
           ▼
[Maskierung sensibler Daten via SecretMasker]
           │
           ▼
[Eintrag in system_notifications (SQLite WAL)]
           │
           ├──────────────────────────────► [UI Notification Feed: Sofort sichtbar]
           ▼
[Telegram Push aktiviert?]
  ├── Nein  ──► Fertig
  └── Ja
        ▼
   [Ist Ruhezeit aktiv?]
     ├── Nein ──► Telegram-Nachricht sofort senden
     └── Ja
           ├── Schweregrad = CRITICAL?
           │     ├── Ja  ──► Ruhezeit durchbrechen, Alarm senden (🚨)
           │     └── Nein ──► Push unterdrücken, in SQLite markieren
           │                  (suppressed_by_quiet_hours = 1)
           └── Als Digest für Morgen-Standup vormerken
```

---

## REST-API Endpunkte

### 1. Richtlinie abfragen
```http
GET /api/operations/notifications/policy
```
**Antwort:**
```json
{
  "status": "success",
  "policy": { ... },
  "in_quiet_hours": false
}
```

### 2. Richtlinie aktualisieren
```http
POST /api/operations/notifications/policy
Content-Type: application/json

{
  "quiet_hours_start": "23:00",
  "quiet_hours_end": "06:30",
  "allow_critical_during_quiet_hours": true
}
```

### 3. Unterdrückten Digest abrufen
```http
GET /api/operations/notifications/digest?since_hours=12
```
Liefert alle während der Ruhezeiten gepufferten Meldungen, beispielsweise für das morgendliche Standup oder das Dashboard.

---

## Verknüpfte Module
- `backend/notification_hub.py`: Zentrale Dispatch- und Filter-Engine.
- `backend/autonomy_settings.py`: Fallback- und Schemadefinition.
- `backend/operations_api.py`: REST-Schnittstellen für Control Center und Kanban.
- `scripts/inbox_watcher.py`: Proaktives Morgen-Standup (08:00 Uhr).
