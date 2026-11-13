# Automatisierte Restore- & Integritätstests (SQLite & Litestream)

## Überblick
Backups sind erst dann vertrauenswürdig, wenn ihre Wiederherstellbarkeit und Datenintegrität kontinuierlich verifiziert werden. 

Archon OS implementiert mit [`scripts/automated_restore_test.py`](../../scripts/automated_restore_test.py) einen automatisierten Restore-Tester:
1. **Wegwerf-Sandbox:** Erzeugt ein isoliertes temporäres Dateisystem für jeden Prüflauf.
2. **Lock-freier Online-Restore:** Nutzt die atomare SQLite Backup-API (`pages=200` mit `immutable=1`), um aktive WAL-Datenbanken verlustfrei ohne Schreibblockaden zu spiegeln.
3. **PRAGMA Prüfungen:** Führt auf allen drei Kern-Datenbanken (`kanban.db`, `state.db`, `agentic_memory.db`) `PRAGMA integrity_check` und `PRAGMA foreign_key_check` aus.
4. **Smoke-Tests:** Validiert Tabellenschemata und echte Datensatzmengen (Aufgaben, Dialog-Nachrichten, Prompt-Versionen).
5. **Alarmierung & Governance:** Schlägt ein Test fehl, wird sofort ein Alarm der Stufe `CRITICAL` ausgelöst (Telegram-Push durchbricht Ruhezeiten). Erfolgreiche Läufe werden im Morgen-Standup zusammengefasst.

---

## 1. Getestete Datenbanken & Kriterien

| Datenbank | Typischer Umfang | Smoke-Test Kriterium |
|---|---|---|
| `kanban.db` | Operations Kanban Board | Tabelle `tasks` vorhanden, Datensatzanzahl > 0 |
| `state.db` | Dialogprotokolle & Sessions | Tabelle `messages` vorhanden, Datensatzanzahl > 0 |
| `agentic_memory.db` | Langzeitgedächtnis & Registry | Tabelle `prompt_versions` und `otel_spans` intakt |

---

## 2. CLI-Ausführung

Der Testlauf kann manuell im Terminal ausgeführt werden:

```bash
# Standard-Lauf mit Terminal-Report
python scripts/automated_restore_test.py

# Lauf mit Telegram-Alarmierung
python scripts/automated_restore_test.py --notify
```

**Beispielausgabe:**
```text
=================================================================
  Archon OS – Automatisierter Restore- & Integritäts-Report
=================================================================
Status:      PASSED
Zeitpunkt:   2026-10-30T20:52:11
Dauer:       10.41s
-----------------------------------------------------------------
  [OK] kanban.db         : Integrität=ok | Smoke=OK (94 Einträge in tasks)
  [OK] state.db          : Integrität=ok | Smoke=OK (11339 Einträge in messages)
  [OK] agentic_memory.db : Integrität=ok | Smoke=OK (3 Einträge in prompt_versions)
=================================================================
[ERFOLG] Alle SQLite-Datenbanken wurden fehlerfrei in der Sandbox wiederhergestellt.
```

---

## 3. REST-API Schnittstellen

### Historie abrufen
```http
GET /api/operations/backup/restore-test
```
Liefert die letzten 30 Testergebnisse inklusive Zeitstempel, Dauer und Fehlermeldungen.

### On-Demand Testlauf anstoßen
```http
POST /api/operations/backup/restore-test?notify=true
```
Führt die Wiederherstellung in der Sandbox synchron aus und gibt das Ergebnis zurück.

---

## 4. Zeitgesteuerte Ausführung (Cron / Watchdog)
Der Restore-Tester ist für wöchentliche Ausführung (z. B. sonntags um 03:00 Uhr im Rahmen der nächtlichen Gedächtniskonsolidierung) ausgelegt und schreibt seinen Verlauf persistent nach `data/restore_test_history.json`.
