# W1-E (Fundament/DB) — Fix-Report: D05-H2 (HIGH)

**Datum:** 26.11.2026 · **Befund:** D05-H2 (Gewicht 9, Welle W1) · **Domäne:** 05 Audit-Trail & Kryptografie
**Referenzen:** `audit_reports/00_SOLL_SPEC.md` §2.5 · `audit_reports/GEWICHTETE_BEFUNDLISTE.md` D05-H2 · `audit_reports/domain_05.md` Befund 2 (Fix-Plan)

---

## Ausgangslage

Der „externe" Audit-Anker war im Auslieferungszustand eine gewöhnliche Datei im selben
Bind-Mount wie die Datenbank:

- `.env:18` setzte `ARCHON_AUDIT_ANCHOR_PATH=./data/audit_anchor.log`.
- `docker-compose.yml:124` reicht den Wert mit Compose-Default
  `${ARCHON_AUDIT_ANCHOR_PATH:-/app/audit_anchor/audit_anchor.log}` durch; der `.env`-Wert
  gewinnt und überschreibt den sicheren Default.
- `docker-compose.yml:171` mountet `${ARCHON_AUDIT_ANCHOR_DIR:-./audit_anchor}:/app/audit_anchor`
  als physisch getrenntes Volume — dieser Mount blieb ungenutzt; der Anker landete unter
  `/app/data/` neben `agentic_memory.db` (`:172`).

Netto-Effekt: Ein Prinzipal mit DB-Schreibzugriff konnte Kette **und** Anker löschen/kürzen;
die externe Tamper-Evidenz war wirkungslos. `verify_integrity()` in `backend/audit_log.py`
selbst prüft den Anker korrekt — das Versäumnis lag rein in der Deployment-Konfiguration.

## Änderungen (ausschließlich Dateibesitz)

| Datei | Zeile | Vorher | Nachher | Status |
|---|---|---|---|---|
| `.env` | 18 | `ARCHON_AUDIT_ANCHOR_PATH=./data/audit_anchor.log` | `ARCHON_AUDIT_ANCHOR_PATH=/app/audit_anchor/audit_anchor.log` | **geändert** |
| `.env.example` | 172 | `ARCHON_AUDIT_ANCHOR_PATH=/app/audit_anchor/audit_anchor.log` | identisch | unverändert (bereits korrekt) |
| `docker-compose.yml` | 124, 171 | Default/Mount korrekt | identisch | unverändert (nicht nötig) |

Es wurde **nur eine Zeile** geändert (`.env:18`). Alle anderen Env-Werte — insbesondere die
Audit-/HMAC-Secrets — blieben unangetastet. Es wurden **keine Secrets** in die Dateien oder
diesen Report geschrieben.

## Warum keine Docker-Compose-Änderung nötig war

- `docker-compose.yml:124` hat bereits den korrekten Default
  `/app/audit_anchor/audit_anchor.log`; mit dem gefixten `.env` wird genau dieser Wert in den
  Container durchgereicht.
- `docker-compose.yml:171` mountet bereits das getrennte Verzeichnis `./audit_anchor`
  (außerhalb `data/`) nach `/app/audit_anchor`. Der Anker liegt damit auf einem von der DB
  physisch getrennten Volume.
- Ein `:ro`-Mount des Ankerziels (wie im Fix-Plan von `domain_05.md` erwogen) wurde **bewusst
  nicht** gesetzt: Die Anwendung muss die Ankerdatei append-only schreiben
  (`audit_log.py:510`, `O_WRONLY|O_CREAT|O_APPEND`). Ein read-only-Mount würde das Schreiben
  des Ankers und damit die Produktions-Fail-Closed-Prüfung brechen.
- Keine Härtung anderer Compose-Dienste (Socket-Proxy, NETWORKS, Dead-Man-Switch, …) — das ist
  W5 und außerhalb dieses Auftrags.

## Verifikation (statisch)

- `.env:18` = `/app/audit_anchor/audit_anchor.log` ✅
- `.env.example:172` = `/app/audit_anchor/audit_anchor.log` (bereits vor dem Fix korrekt) ✅
- `docker-compose.yml:124` Default = `/app/audit_anchor/audit_anchor.log` ✅ (unverändert)
- `docker-compose.yml:171` = `${ARCHON_AUDIT_ANCHOR_DIR:-./audit_anchor}:/app/audit_anchor` ✅
- Kein `ARCHON_AUDIT_ANCHOR_*`-Wert zeigt mehr auf `./data` ✅
- Keine Secrets hinzugefügt, keine fremden Env-Werte geändert ✅
- Keine Commits, keine Replay-/PostgreSQL-Aktionen, kein Container-Start/Rebuild ✅

Shell war für diesen Fix nicht erforderlich; die Änderung ist statisch sauber. Der Koordinator
verifiziert zentral.
