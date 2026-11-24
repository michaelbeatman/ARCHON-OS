# Automatisierte Restore- & Integritätstests (SQLite & Litestream)

## Überblick
Backups sind erst dann vertrauenswürdig, wenn ihre Wiederherstellbarkeit und Datenintegrität kontinuierlich verifiziert werden.

Archon OS implementiert mit [`scripts/automated_restore_test.py`](../../scripts/automated_restore_test.py) einen automatisierten Restore-Tester:
1. **Wegwerf-Sandbox:** Erzeugt ein isoliertes temporäres Dateisystem für jeden Prüflauf.
2. **Lock-freier Online-Restore:** Nutzt die atomare SQLite Backup-API (`pages=200`), um echte Backup-Artefakte verlustfrei ohne Schreibblockaden in die Sandbox zu spiegeln. Die Live-DB als Quelle führt bewusst zu `FAILED`.
3. **PRAGMA Prüfungen:** Führt auf allen geprüften Zielen `PRAGMA integrity_check` und `PRAGMA foreign_key_check` aus.
4. **Smoke-Tests:** Validiert Tabellenschemata und echte Datensatzmengen der konsolidierten Domänen-DBs, der PocketBase-CRM-DB sowie die Litestream-Abdeckung der Mandanten-DBs.
5. **Alarmierung & Governance:** Schlägt ein Test fehl, wird sofort ein Alarm der Stufe `CRITICAL` ausgelöst (Telegram-Push durchbricht Ruhezeiten). Erfolgreiche Läufe werden im Morgen-Standup zusammengefasst.

---

## 1. Getestete Ziele & Kriterien

Der Test prüft seit der Konsolidierung 28 → 3 nicht mehr die alten Einzeldateien (`kanban.db`, `state.db`, `agentic_memory.db`), sondern die drei konsolidierten Domänen-DBs, die PocketBase-CRM-DB und die Tenant-Replikation — **5 Ziele, `PASSED 5/5`**.

| Ziel | Umfang / Zweck | Smoke-Test Kriterium |
|---|---|---|
| `ops.db` | Operative Steuerung, Kanban-Tasks, Workflows & Security | Tabelle `tasks` (alternativ `task_events`, `checkpoints`) vorhanden, Datensatzanzahl > 0 |
| `business.db` | ERP, CRM, Deals, Verträge & Treasury | Tabelle `deals` (alternativ `contracts`, `invoices`) vorhanden, Datensatzanzahl > 0 |
| `memory.db` | Langzeitgedächtnis, Learnings & Prompt-Registry | Tabelle `learnings` (alternativ `prompt_versions`) vorhanden, Datensatzanzahl > 0 |
| `pb_data.db` | PocketBase-CRM (optional) | Tabelle `kontakte` vorhanden; `SKIPPED`, wenn PocketBase lokal nicht verfügbar ist |
| `TENANT_REPLICATION` | Mandanten-DBs `data/tenants/<id>/*.db` | `config/litestream.yml` enthält `dir: /app/data/tenants` (`pattern: "*.db"`, `recursive: true`) oder explizite Tenant-Pfade |

Die alten Dateinamen `kanban.db`, `state.db` und `agentic_memory.db` bleiben als Legacy-Aliase erhalten; `backend/db_paths.py` routet sie bei aktiver Konsolidierung transparent auf `ops.db` bzw. `memory.db`.

---

## 2. CLI-Ausführung

Der Testlauf kann manuell im Terminal ausgeführt werden:

```bash
# Standard-Lauf mit Terminal-Report
python scripts/automated_restore_test.py

# Lauf mit Telegram-Alarmierung
python scripts/automated_restore_test.py --notify
```

**Beispielausgabe (letzter erfolgreicher Lauf):**
```text
=================================================================
  Archon OS – Automatisierter Restore- & Integritäts-Report
=================================================================
Status:      PASSED
Zeitpunkt:   2026-11-24T08:02:52
Dauer:       0.24s
-----------------------------------------------------------------
  [OK] ops.db             : Integrität=ok | Smoke=OK (189 Einträge in tasks)
  [OK] business.db        : Integrität=ok | Smoke=OK (1 Einträge in deals)
  [OK] memory.db          : Integrität=ok | Smoke=OK (152 Einträge in learnings)
  [OK] pb_data.db         : Integrität=ok | Smoke=OK (2332 Einträge in kontakte)
  [OK] TENANT_REPLICATION : Integrität=N/A | Smoke=OK (20 Tenant-DBs via Litestream abgedeckt)
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
