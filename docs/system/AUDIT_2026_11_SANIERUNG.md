# Archon OS — Code-Audit & Sanierung (22.11.2026)

> **Ehrlichkeitshinweis:** Die bisherige Doku (`MULTI_AGENT_CONTENT_ROADMAP_2026_GUIDE.md`)
> meldet „28/28 umgesetzt" und `SYSTEM_ARCHITEKTUR_UND_AUDIT_2026.md` meldet
> „Alle Erfüllt". Das war nicht mit dem Code vereinbar: mehrere Gates waren
> Theater, eine Publish-Queue ohne Versand, ein Frontend ohne die Hälfte der
> Endpunkte. Dieses Dokument清单 die verifizierten Befunde und den
> Sanierungsstand. Regressionstests sind im Repo vorhanden, wurden aber
> historically nicht ausgeführt (lokale venvs ohne pytest) — CI muss grün sein.

## 1. Kritische Blocker — behoben

| Fund | Datei | Maßnahme |
|---|---|---|
| `os.kill(pid, 0)` tötet unter Windows Worker (0 == CTRL_C_EVENT) | `backend/deadlock_supervisor.py` | psutil-basierte Liveness, POSIX-Fallback, Fail-Safe auf Windows |
| Service-Token nur per Header-Präsenz → Mandanten-IDOR | `main.py:293` | `_request_has_service_token()` (HMAC) |
| Auth-Force-Env nicht in Container durchgereicht | `docker-compose.yml` | `ARCHON_BIND_IP`, `ENVIRONMENT`, Publish-Webhook |
| `all([]) == True` → HITL-Bypass | `backend/workflow_dag_runner.py` | Explizite Freigabe erforderlich |
| Warrant hebt Session-Taint/HITL auf | `backend/delegation_isolation.py` | M89 läuft immer; Warrant ersetzt nur M75 |
| HITL-Freigabe nicht an Argumente gebunden | `backend/session_taint_guard.py` | kanonisches `args_json` verglichen |
| PbD-Slug/Code-Injection (Path-Traversal + RCE) | `backend/computer_use_pbd.py` | strikter Slug, `repr()`, Secret-Maskierung |
| TypeScript-Buildfehler (TS2554, 8 Call-Sites) | `frontend/src/utils/aiAudio.ts` | optionale Parameter + 404-freie Proxy-URLs |
| Browser-`localhost` im Frontend | `frontend/src/**` | alle Calls über `/api/archon/*`, `/api/media/*` |
| Keine UI für Content-Machine | `static/views/content_machine_view.html` | eigenes Cockpit mit Kampagnen/Review/Publish |

## 2. Orchestrierung — behoben

- **TaskRegistry** (`archon/core/task_registry.py`): Fire-and-Forget-Tasks behalten Referenz und loggen Exceptions; Shutdown bricht sie ab.
- **Fan-In** nutzt jetzt `update_mission_control_data(mutator)` statt veraltetem Snapshot → keine Lost Updates, keine Audit-Duplikate.
- **`synthesis_started` Recovery**: Zeitstempel + 30-s-Watchdog setzt verwaiste Flags zurück.
- **Claim-Renewal**: DAG-Lease wird alle 60 s verlängert.
- **Cancel**: Kind-Tokens werden beim Registrieren neu am Parent verdrahtet.
- **Budget-Cap**: Reservierungen zählen jetzt über alle Tasks desselben Agenten.
- **Backpressure**: reduziert verfügbare Slots statt nur Anzeige zu sein.
- **Rollover**: Ausfall-Markierungen verfallen nach 5 Minuten.
- **Ephemeral Teams / Squad Packs**: reale Agent-IDs, Listen-/Dict-Formate normalisiert.
- **Outbox** wird bereits vom Workflow-Scheduler (30 s) gedraint — **DLQ-Worker fehlt weiterhin** (offen).

## 3. Content-Machine — behoben

- Research-`sources` + `snippet` fließen in Assets; Snippets sind der Plagiats-Korpus.
- Fact-Check-Gate blockiert auch bei fehlenden Zahlen (Opinion-Opt-out in `settings.json`).
- Plagiats-Gate verlangt `checked=True`.
- Assets werden nur bei bestandenem Quality-Gate direkt freigegeben.
- `scheduled_at` wird bei Freigabe gesetzt → Publish-Sweep findet Assets.
- Sweep übermittelt Webhook (ENV/settings) und übernimmt `external_url` aus der Response.
- Kampagnen-Löschung räumt alle Kindtabellen auf; Voice-Hooks werden angehängt statt überschrieben.
- A/B-Entscheidung: gültige Metrik-Spalte, Mindest-Stichprobe, Wilson-Konfidenzintervall.
- Oracle-Triage schreibt in `kanban.db` statt veralteter `kanban_data.json`.
- Wettbewerber-Ideen haben keinen gefälschten `quality_score=85` mehr.

## 4. Persistenz & Sicherheit — behoben

- Semantic Cache und Idempotency-Ledger haben Tenant-/Scope-Key.
- Idempotency `pending` blockiert laufende Zweit-Worker (Lease statt Doppel-Execution).
- `settings.json`: Parse-Fehler mit `.bak`-Recovery, kein stilles Leeren.
- Vault-Key atomar mit `O_EXCL`/600; Warrant-Key ebenfalls.
- `HERMES_HOME`/Vault-Pfade absolut und expandiert.
- TTL-Cache: pro-Eintrag-Ablauf + Single-Flight.
- Async-Batcher verwirft keine Events mehr.
- Secret-Masker: ENV-Literale + GitHub/Google/AWS/Slack-Formate.
- Tool-Output-Firewall: Injection-Scan + Maskierung + Untrusted-Delimiter im Chokepoint.
- Egress: lokale Zonen nur nach DNS/IP-Validierung freigegeben.
- Sandbox: Netzwerk-Isolation hart fail-closed.
- Rate-Limits auf allen LLM-Pfaden, zusätzlich nach Session gebuckett.
- n8n: X-Frame-Bypass/unverifizierte Pakete aus, Settings-Permissions an.
- Router-Importfehler werden gesammelt und in Produktion hart abgebrochen.
- CORS außen; SSE-Queue begrenzt; Hintergrund-Loops idempotent; Watchdog-Stop.

## 5. Never-Do (Benutzerentscheidung 22.11.2026)

Siehe [`NEVER_DO_LIST.md`](NEVER_DO_LIST.md): **kein Coroutine-Replay**,
**keine PostgreSQL-Migration**. Beides ist verbindlich abgelehnt und darf
nicht mehr als offene Aufgabe geführt werden.

## 5b. Nachfolgend umgesetzt

- **Nummernkreise in SQLite**: `document_number_sequences` in der isolierten
  `erp.db` je Mandant, `BEGIN IMMEDIATE`, Migration von `number_ranges.json`
  (Zählerstand erhalten). GoBD-konform bei mehreren Workern.
- **Vollständige Mandanten-DB-Isolation**: auch `default`/`archon-systems`
  liegen jetzt unter `data/tenants/<tid>/`. DSGVO Art. 17 über
  `tenant_context.resolve_active_db()` wirkt damit auf die richtige Datei.
- **Migration**: `scripts/migrate_tenant_dbs.py --execute` hat geteilte DBs
  und den alten Pfad `agent_workspace/data/tenants/` nach `data/tenants/`
  überführt; verwaiste Root-DBs liegen unter `data/_legacy_root_dbs_*`.
- `tenant_context` nutzt jetzt denselben Repo-Root wie `backend.db_paths`
  (vorher Split-Brain zwischen `./agent_workspace` und `data/`).

## 5c. Offene Punkte

1. **~158 unvalidierte Body-Dicts** und ~25 `status:"error"` mit HTTP 200 — Pydantic-Modelle fehlen.
2. **Frontend-Build** trotz CI-Job nicht lokal verifiziert (kein `frontend/node_modules`).
3. **Import-Pfade** in `views_core`-Theme-Legacy nicht vollständig konsolidiert.

## 6. Verifikation

```bash
python -m compileall -q archon backend utils main.py
npm ci --prefix frontend && npm run lint --prefix frontend && npx tsc --noEmit --prefix frontend
python -m pytest tests/ -q
python scripts/run_ci_suite.py
```
