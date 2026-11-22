# Operations-Kalender 2.0 (M104)

Der **Operations-Kalender** unter **Operations → Kalender** nutzt eine vollständig eigene, unminifizierte **Archon OS Kalender-Engine** in `static/js/operations_calendar.js` (ohne Fremdbibliothek, direkt anpassbar) und bleibt bewusst vom CRM-Kalender getrennt.

## 1. Funktionen im Überblick

- **Eingebettete Ansicht (`#ops-view-calendar`):** Öffnet direkt im Operations-Arbeitsbereich (kein Popup-Dialog), mit Umschaltung über `setOperationsTab('calendar')`.
- **Kalender-Einstellungen in den System-Settings:** Unter **Settings → Kommunikation & Sync** (`#calendar-settings-card`) lassen sich Standardansicht (Tag/Woche/Monat/Jahr/Agenda), Arbeitszeiten, Fokus-Block-Dauer sowie externe Kalender-Quellen (Google ICS, Microsoft 365 / Outlook ICS, Apple / Nextcloud CalDAV) zentral verwalten.
- **Ansichten:** Tag, Woche (Zeitraster mit Jetzt-Linie & Überlappungs-Spalten), Monat (mit KW), Jahr (12 Mini-Monate) und Agenda/Liste.
- **Direkte Interaktion:** Termine per **Drag & Drop** verschieben, am unteren Rand **verlängern/verkürzen (Resize)** oder durch Ziehen über freie Zeitslots direkt neu anlegen.
- **Kalender-Layer (linke Sidebar):**
  - *Termine & Meetings* (`custom`)
  - *Deep-Work / Fokus* (`focus`)
  - *Kanban-Deadlines* (`kanban`)
  - *Workflow-Cron-Jobs* (`workflow` — nächste geplante Läufe aus `data/workflow_schedules.db`)
  - *ERP / Zahlungen* (`erp`)
  - *Externe Kalender* (`external`)
  - *Feiertage (Bundesland)* (`holiday` — automatische deutsche Feiertage nach Bundesland, inkl. Ostern-Formel)
  - *Schulferien (Bundesland)* (`school_holiday` — Abruf über `ferien-api.de` je Bundesland mit lokalem Cache `data/school_holidays_cache.json`)
- **Ressourcen- & Raum-Matrix (`resource` / `timeline`):** Vertikale Ressourcenansicht mit Drag-&-Drop zwischen Ressourcenspalten sowie horizontale Gantt-Zeitleiste wahlweise für **Tag** oder **7-Tage-Woche** (`R` / `L`). Automatische **Konflikt- & Doppelbuchungs-Sperre** (`GET /check-conflict`, `allow_conflict`-Override). Ressourcen werden über `config/calendar_resources.json` verwaltet.
- **Team-Verfügbarkeit („Find a Time“):** Direkter Frei/Belegt-Vergleich im Termin-Editor über `GET /api/v1/calendar/free-busy` inklusive klickbarer gemeinsamer freier Slots.
- **Quick-Add & KI-Chat-Abfragen (`/termin` & `/kalender`):** Natürliche Spracheingabe direkt in der Kalender-Toolbar (`POST /nl-query`, `POST /quick-add`) oder im Masterchat für Anlegen, Abfragen (*„Wann habe ich nächste Woche 2 Stunden frei?“*), Agenda und Verschieben (*„Verschiebe Call mit Max auf morgen 16:30“*).
- **Suche & Kategorie-Filter:** Live-Suche über Titel, Teilnehmer, Ort, Ressource und Notizen sowie Kategorie-Filter direkt in der Toolbar.
- **Zweit-Zeitzone:** Optionale parallele Zeitzonen-Spalte in Tag/Woche (z. B. `America/New_York`, `UTC`, `Europe/London`, `Asia/Tokyo`) neben der lokalen Zeitachse.
- **Serientermine & Einzel-Ausnahmen:** Tägliche, wöchentliche (mit Wochentagen Mo–So) oder monatliche Wiederholungen mit optionalem Enddatum (`recurrence_until`). Beim Verschieben, Verändern oder Löschen einer Serien-Instanz lässt sich gezielt zwischen **„Nur diesen Termin“** (`occurrence_overrides` / `excluded_dates`) und **„Gesamte Serie“** wählen.
- **Einladungs- & RSVP-System:** Versand von RFC-5545 `METHOD:REQUEST` `.ics`-Einladungen über den Postausgang (`POST /events/{id}/invite`) sowie anklickbarer Teilnehmer-Status (`pending`, `accepted`, `declined`, `tentative`) pro E-Mail.
- **Öffentliche Buchungslinks (`static/booking.html`):** Cal.com-ähnliche Multi-Event-Type-Buchungsseite (`/static/booking.html?slug=mein-termin`, konfigurierbare Slugs inkl. UI-Editor in Settings → Kommunikation & Sync), inklusive Vor-/Nachlaufpuffern, Tageslimits (`max_per_day`), Custom-Branding, **Round-Robin-Teamzuweisung**, optionalem **Bezahl-Gate (`price_eur`)** und **Fragebogen-Feldern**.
- **Vollständige i18n-Unterstützung:** 9 Sprachen (`de`, `en`, `fr`, `es`, `pt`, `ru`, `ja`, `ko`, `zh`) in `operations_calendar.js` und `booking.html`.
- **Mobile Touch-Gesten & Offline-PWA-Sync (`static/sw_calendar.js`):** Horizontales Wischen zum Blättern, Touch-Drag für Termine, Service-Worker-Cache sowie **Offline-Write-Queue** mit automatischer Synchronisation bei Reconnect.
- **Echtzeit-Multi-User-Kollaboration (`/api/v1/calendar/ws`):** WebSocket-Live-Sync zwischen geöffneten Browser-Tabs.
- **Hintergrund-Wartungs-Scheduler:** Periodischer Hintergrund-Job (`start_background_maintenance`, manuell per `POST /maintenance/run`) für automatisches IMAP-RSVP-Polling und Erneuerung ablaufender Google/Microsoft-Webhooks.
- **Tastatur-Shortcuts:** `T` (Heute), `D`/`W`/`M`/`Y`/`A` (Ansichten), `N` (Neuer Termin), `←`/`→` (Blättern).
- **Druckansicht / PDF:** `@media print`-Stylesheet + Button **„Drucken / PDF“** blenden Sidebar und Aktionsleisten aus.
- **Fokuszeit finden:** Prüft freie 90-Minuten-Blöcke in den nächsten 5 Werktagen (Mo–Fr 09:00–17:00) und trägt sie auf Wunsch direkt als Deep-Work-Block ein.

## 2. Externe Kalender, CalDAV-Writeback & Two-Way-Sync

- **`.ics` Import & Export:** Direkter Import von `BEGIN:VCALENDAR`-Daten sowie Download/Abo über `GET /api/v1/calendar/export.ics`.
- **Externe Quellen (`config/calendar_sources.json`):** Verbindung zu **Google Calendar (.ics & OAuth2 Redirect-Flow mit Token-Refresh & Push-Webhooks)**, **Microsoft 365 / Outlook (.ics & Graph OAuth2 Redirect-Flow & Subscriptions)** sowie **Apple / Nextcloud (CalDAV Writeback)** inklusive manuellem Re-Sync (`POST /sources/{id}/sync`), Echtzeit-Push (`POST /sources/{id}/watch`, `POST /webhooks/push`), IMAP-RSVP-Abruf (`POST /rsvp/poll-imap`, `POST /rsvp/ingest-ics`) und Rückschreiben von Terminen (`POST /events/{id}/push`).

## 3. Event-Bus-Anbindung

- Das Anlegen (`calendar.created`), Verschieben/Aktualisieren (`calendar.updated`), Synchronisieren (`calendar.synced`) sowie fällige Tagestermine (`calendar.due`) senden automatisch Events in den zentralen Event-Bus (`backend/workflow_scheduler.py`) und sind unter **Telemetrie & Logs → Event-Bus** sichtbar.

## 4. API-Endpunkte (`/api/v1/calendar`)

- `GET /events` (`?holiday_state=BY`) | `POST /events` | `PATCH /events/{id}` | `DELETE /events/{id}` (`?occurrence_date=...`)
- `POST /quick-add` | `GET /free-busy` | `GET/POST /resources`
- `GET/POST /oauth/config` | `GET /oauth/{provider}/start` | `GET /oauth/{provider}/callback`
- `POST /events/{id}/invite` | `POST /events/{id}/rsvp` | `POST /events/{id}/push`
- `GET /booking/{slug}` | `POST /booking/{slug}`
- `GET /sources` | `POST /sources` | `DELETE /sources/{id}` | `POST /sources/{id}/sync`
- `POST /import-ics` | `GET /export.ics` | `GET /focus-slots`
