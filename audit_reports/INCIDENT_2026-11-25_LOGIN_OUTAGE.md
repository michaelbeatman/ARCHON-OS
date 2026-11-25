# INCIDENT 2026-11-25 — Login-Ausfall durch korrumpierte `data/memory.db`

## Symptom
User wurde aus Archon ausgeloggt; erneuter Login nicht möglich.

## Ursache
Parallel laufende Test-Suiten mehrerer Subagenten (und Orchestrator-Läufe) schrieben gegen die **produktiven** SQLite-DBs unter `./data`. Dabei wurde `data/memory.db` beschädigt:

```
[Auth] Session-Prüfung fehlgeschlagen: database disk image is malformed
[Integritaet] Quittungs-Hashkette nicht pruefbar: database disk image is malformed
```

`PRAGMA integrity_check` auf `data/memory.db` → `database disk image is malformed`. Alle anderen DBs (inkl. Tenant-DBs, `ops.db`, `state.db`, `business.db`) waren **gesund**.

## Reparatur (destruktionsfrei dokumentiert)
1. Diagnose-Skripte: `scripts/emergency_db_check.py`, `emergency_db_probe.py`, `emergency_table_map.py`, `emergency_candidate_compare.py`.
2. Beschädigte Dateien gesichert nach `data/emergency_backups/20261125_login_outage/` (`memory.db.corrupt`, `-wal.corrupt`, `-shm.corrupt`).
3. `archon-os` gestoppt, `data/memory.db` durch frischste gesunde Kopie `data/agentic_memory.db` ersetzt (16 User, 4689 Audit-Zeilen), veraltete `-wal`/`-shm` entfernt.
4. `PRAGMA integrity_check` der neuen `data/memory.db` → **ok**, 16 User.
5. Fehlende Secrets in `.env` ergänzt (`scripts/emergency_ensure_secrets.py`): `ARCHON_API_KEY_PEPPER`, `ARCHON_AUDIT_ANCHOR_KEY`, `ARCHON_RECEIPT_HMAC_KEY`.
6. `docker-compose.yml`: `ARCHON_API_KEY_PEPPER=${ARCHON_API_KEY_PEPPER:-}` in `environment:` ergänzt — der neue Fail-Fast-Hook (`_assert_api_key_pepper`) hatte den Start sonst abgebrochen.
7. Container neu erstellt (`--force-recreate`), danach: `livez=200`, `readyz=200`, `health=200`; keine `Session-Prüfung fehlgeschlagen` in den Logs seit Restart.

## Rest-Risiken / offene Punkte
- **Audit-Ketten-Bruch dokumentiert (Stand 25.11.2026, 10:25 Uhr):**
  - `audit_log` (`data/memory.db`): 4.695 Zeilen (IDs `10..4704`), davon Blöcke `10..1669` (1.660 Zeilen) als historisches Plain-SHA (Block `#148` mit abweichender `session_id`-Korrelation aus Altbestand), Blöcke `1670..4698` aus der wiederhergestellten `agentic_memory.db` (bis `2026-11-25T06:33:20Z`) mit altem Key und Blöcke `4699..4704` (ab `2026-11-25T06:50:44Z`) mit dem neuen `ARCHON_AUDIT_HMAC_KEY`.
  - `execution_receipts` (`data/memory.db`): 106 Alt-Einträge mit altem Receipt-Key (`chain_valid=False` gegen neuen `ARCHON_RECEIPT_HMAC_KEY`).
  - **Entscheidung / nächster Schritt:** Alte Blöcke werden **nicht** still re-signiert (Beweismittel-Integrität). Wenn künftig wieder `valid=True` im Live-System gewünscht ist, können die Pre-Recovery-Einträge (`audit_log <= 4698` und die 106 Alt-Receipts) bei gestopptem Container in ein Read-Only-Archiv (`data/emergency_backups/20261125_login_outage/pre_recovery_audit_archive.db`) ausgelagert und die Live-Kette ab einem neuen Genesis-Block gestartet werden; alternativ bleibt der dokumentierte Bruch als Epochen-Grenze (`2026-11-25T06:50:44Z`) bestehen.
- Die wiederhergestellte `memory.db` stammt aus `agentic_memory.db`; neueste Daten aus der korrumpierten `memory.db` sind verloren (u.a. `lcm_turns`/`lcm_summaries` aus F011 — werden beim nächsten Start per `CREATE TABLE IF NOT EXISTS` neu angelegt, aber ohne alte Inhalte).
- Alle weiteren Testläufe **müssen** `ARCHON_DATA_DIR` auf ein temporäres Verzeichnis setzen. An alle W3-Agenten wurde eine entsprechende Anweisung gesendet.

## Lehre
Die §0-Forderung „Verifikation" gilt auch für die **Isolation der Testdaten**. Ein Audit, das Produktions-DBs mit parallelen Testläufen beschreibt, verletzt genau die Integrität, die es prüfen soll. F050 muss einen Testlauf gegen `ARCHON_DATA_DIR=<temp>` belegen.
