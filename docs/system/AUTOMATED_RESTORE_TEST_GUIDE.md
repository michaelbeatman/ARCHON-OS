# Automatisierte Restore- & Integritätstests (SQLite & Litestream)

> **Audit D10-M2 / W5-B (27.11.2026):** Der Tester verifiziert jetzt echte
> Litestream-Replikate via `litestream restore` in der Wegwerf-Sandbox. Die
> frühere Aussage „alle Ziele als PASSED gemeldet" beruhte auf einer reinen
> Konfigurationsprüfung (`dir: /app/data/tenants`) und war im Produktivpfad ein
> Scheinerfolg. Ohne Replikat-Artefakt ist der Lauf jetzt `FAILED`.

## Überblick

Backups sind erst dann vertrauenswürdig, wenn ihre Wiederherstellbarkeit und Datenintegrität kontinuierlich verifiziert werden.

Archon OS implementiert mit [`scripts/automated_restore_test.py`](../../scripts/automated_restore_test.py) einen automatisierten Restore-Tester:

1. **Wegwerf-Sandbox:** Erzeugt ein isoliertes temporäres Dateisystem für jeden Prüflauf.
2. **Lock-freier Online-Restore:** Nutzt die atomare SQLite Backup-API (`pages=200`), um echte Backup-Artefakte verlustfrei ohne Schreibblockaden in die Sandbox zu spiegeln. Die Live-DB als Quelle führt bewusst zu `FAILED`.
3. **Echter Litestream-Restore:** Für jedes Replikat unter `ARCHON_LITESTREAM_REPLICA_DIR` wird `litestream restore -config <config> -o <sandbox> <db-path>` ausgeführt und die erzeugte Datei identisch geprüft (siehe Abschnitt 2).
4. **PRAGMA Prüfungen:** Führt auf allen geprüften Zielen `PRAGMA integrity_check` und `PRAGMA foreign_key_check` aus.
5. **Smoke-Tests:** Validiert Tabellenschemata und echte Datensatzmengen der konsolidierten Domänen-DBs, der PocketBase-CRM-DB sowie der wiederhergestellten Tenant-Replikate.
6. **Frische-Gate:** Das jüngste Replikat-Artefakt darf höchstens `ARCHON_LITESTREAM_MAX_AGE_S` (Default 120 s) alt sein. Bei veralteten oder fehlenden Artefakten → `FAILED`, nie `SKIPPED`.
7. **Alarmierung & Governance:** Schlägt ein Test fehl, wird sofort ein Alarm der Stufe `CRITICAL` ausgelöst (Telegram-Push durchbricht Ruhezeiten). Erfolgreiche Läufe werden im Morgen-Standup zusammengefasst.

---

## 1. Getestete Ziele & Kriterien

Der Test prüft seit der Konsolidierung 28 → 3 nicht mehr die alten Einzeldateien (`kanban.db`, `state.db`, `agentic_memory.db`), sondern:

| Ziel | Umfang / Zweck | Smoke-Test Kriterium |
|---|---|---|
| `ops.db` | Operative Steuerung, Kanban-Tasks, Workflows & Security | Tabelle `tasks` (alternativ `task_events`, `checkpoints`) vorhanden, Datensatzanzahl > 0 |
| `business.db` | ERP, CRM, Deals, Verträge & Treasury | Tabelle `deals` (alternativ `contracts`, `invoices`) vorhanden, Datensatzanzahl > 0 |
| `memory.db` | Langzeitgedächtnis, Learnings & Prompt-Registry | Tabelle `learnings` (alternativ `prompt_versions`) vorhanden, Datensatzanzahl > 0 |
| `pb_data.db` | PocketBase-CRM (optional) | Tabelle `kontakte` vorhanden; `SKIPPED`, wenn PocketBase lokal nicht verfügbar ist |
| `LITESTREAM_RESTORE:*` | Replikate `ops.db`, `business.db`, `memory.db`, `kanban.db`, `state.db` und `tenants/<tid>/*.db` | `litestream restore` Exit 0, nicht leere Datei, `integrity_check=ok`, `foreign_key_check=OK`, Smoke, Alter ≤ 120 s |
| `TENANT_REPLICATION` | Mandanten-DBs `data/tenants/<id>/*.db` | `PASSED` nur wenn Configabdeckung **und** mindestens ein Tenant-Replikat real restore-verifiziert wurde |
| `LITESTREAM_REPLICA_SOURCE` | Pflichtquellen-Prüfung | `FAILED`, wenn keine Replikate gefunden wurden (kein stilles Grün) |

Die alten Dateinamen `kanban.db`, `state.db` und `agentic_memory.db` bleiben als Legacy-Aliase erhalten; `backend/db_paths.py` routet sie bei aktiver Konsolidierung transparent auf `ops.db` bzw. `memory.db`.

---

## 2. Litestream-Replikat-Restore (D10-M2)

**Wichtig:** Das Replikatverzeichnis ist keine `.db`-Datei, sondern ein von
Litestream verwalteter Zielpfad (`config/litestream.yml`: `/opt/litestream_replicas/…`).
Der Tester läuft in der Sandbox den echten CLI-Befehl:

```text
litestream restore -o <sandbox>/litestream_restored_<name> \
  -config config/litestream.yml <configurierter-db-path>
```

Der DB-Pfad wird aus `config/litestream.yml` gelesen (SSOT), mit einer
Fallback-Tabelle für die fünf Bestandseinträge. Danach folgen
`PRAGMA integrity_check`, `PRAGMA foreign_key_check`, ein Tabellen-/Datensatz-
Smoke und die Frischeprüfung gegen den jüngsten Artefakt-Timestamp
(`sync-interval` 5–10 s erwartet).

### Konfiguration

| Variable | Default | Zweck |
|---|---|---|
| `ARCHON_LITESTREAM_REPLICA_DIR` | `<workspace>/dr_replicas` (im Container: Replikat-Volume) | Verzeichnis mit den Replikaten |
| `ARCHON_LITESTREAM_BIN` | `litestream` | Pfad zur Litestream-CLI |
| `ARCHON_LITESTREAM_CONFIG` | `<workspace>/config/litestream.yml` | Config-Datei mit den DB-Zielpfaden |
| `ARCHON_LITESTREAM_MAX_AGE_S` | `120` | Maximal erlaubtes Replikat-Alter |
| `ARCHON_LITESTREAM_RESTORE_TIMEOUT_S` | `120` | Timeout pro Restore-Aufruf |

**Ohne Replikat-Artefakt ist der Gesamtlauf `FAILED`** — Konfigurationspräsenz
allein ist kein Restore-Beweis. Für lokale Entwicklung ohne Replikatvolumen
muss der produktive Pfad bewusst gegen ein Beispieldaten-Replikat ausgeführt
werden; ein `SKIPPED` gibt es für diese Pflichtquelle nicht.

---

## 3. CLI-Ausführung

```bash
# Standard-Lauf mit Terminal-Report
python scripts/automated_restore_test.py

# Lauf mit Telegram-Alarmierung
python scripts/automated_restore_test.py --notify

# Roh-Report als JSON (Exit 0 nur bei overall_status=PASSED)
python scripts/automated_restore_test.py --json
```

**Beispielausgabe (mit konfiguriertem Replikat-Volumen):**
```text
=================================================================
  Archon OS – Automatisierter Restore- & Integritäts-Report
=================================================================
Status:      PASSED
Zeitpunkt:   2026-11-27T09:14:03
Dauer:       1.82s
-----------------------------------------------------------------
  [OK] ops.db                       : Integrität=ok | Smoke=OK (189 Einträge in tasks)
  [OK] business.db                  : Integrität=ok | Smoke=OK (1 Einträge in deals)
  [OK] memory.db                    : Integrität=ok | Smoke=OK (152 Einträge in learnings)
  [OK] pb_data.db                   : Integrität=ok | Smoke=OK (2332 Einträge in kontakte)
  [OK] LITESTREAM_RESTORE:ops.db    : Integrität=ok | Smoke=OK (189 Einträge in tasks)
  [OK] TENANT_REPLICATION           : Integrität=N/A | Smoke=OK (20 Tenant-DBs: Config vorhanden, echtes Replikat in Sandbox restore-verifiziert)
=================================================================
[ERFOLG] Alle SQLite-Datenbanken wurden fehlerfrei in der Sandbox wiederhergestellt.
```

---

## 4. REST-API Schnittstellen

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

## 5. Zeitgesteuerte Ausführung (Cron / Watchdog)
Der Restore-Tester ist für wöchentliche Ausführung (z. B. sonntags um 03:00 Uhr im Rahmen der nächtlichen Gedächtniskonsolidierung) ausgelegt und schreibt seinen Verlauf persistent nach `data/restore_test_history.json`. Der betriebsbegleitende 6-h-Cron wird über die Ansible-Rolle `archon_node`installiert (Partition W5-C; eigener `archon_dr_enabled`-Schalter).

---

## 6. CI-Gate-Vertrag (ehrlicher Status)

`scripts/chaos_tester.py` und `scripts/automated_restore_test.py` sind als
**harte Gates über ihren Exit-Code** konzipiert:

| Skript | Exit 0 nur, wenn | Exit 1 bei |
|---|---|---|
| `chaos_tester.py` | alle Pflichtchecks `passed` | `tests_failed > 0` **oder** `tests_skipped > 0` (Dry-Run, fehlende Watchdog-Evidenz) |
| `automated_restore_test.py` | `overall_status == PASSED` | beliebiges `FAILED`, auch fehlende/veraltete Litestream-Replikate |

**Realitätscheck (Audit D10):** `.github/workflows/ci.yml` ruft derzeit nur
`scripts/automated_restore_test.py` auf; `scripts/chaos_tester.py` ist dort
**nicht** verdrahtet. Die frühere Behauptung in `config/prometheus/alerts.yml`
(„läuft die Suite als harter CI-Gate") war daher falsch und wurde korrigiert.
Der Chaos-Lauf ist über den Ansible-6-h-Cron bzw. einen vom Betreiber
eingerichteten CI-Step zu triggern; solange das nicht passiert, darf kein
Bericht einen bereits aktiven CI-Gate behaupten. Die Prometheus-Regeln in
`config/prometheus/alerts.yml` überwachen echte Metriken; es gibt **keine**
Chaos-Metrik (`chaos_*`) — bitte keine Schein-Alerts ergänzen.
