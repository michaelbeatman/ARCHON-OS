# System-Audit 2026 — konsolidierte Befundmatrix (Phase 1+2)

15 Audits (10 Domänen + 5 Verdrahtungsaudits) wurden zusammengeführt,
Duplikate eliminiert und Zielkonflikte aufgelöst. Priorisierung nach
Abhängigkeit: Fundament → Sicherheit → Orchestrierung → Content → Frontend.

## Priorisierte Abhängigkeitsmatrix (Ausführungsequenz)

| Nr. | Cluster | Kritische Funde | Status |
|---|---|---|---|
| 1 | Startup-Fail-Closed | `_assert_router_health` fehlte; Router-Importe fail-open; CORS/Rate-Limit innen | ✅ behoben |
| 2 | Auth/RBAC | Body-Actors, Auth-Flag im Session-Pfad, `/keys/audit` + Approvals-GETs ohne RBAC, Passkey-Proof fälschbar | ✅ Teil behoben (Actors, RBAC, Auth-Flag); Passkey-Bindung offen |
| 3 | Tenant-Isolation | Default-Tenant teilte DBs, Vault/Key global, Taint/Egress tenant-blind, Cache/Idempotency ohne Scope | ✅ DB-Isolation + Scope; Vault/Taint offen |
| 4 | Orchestrierung | Synthesis-Latch, Cancel nach await, Lease/Fencing, DLQ-Scheinconsumer, Boardroom-Killswitch | ✅ Latch/Recovery/CAS; Cancel/Fencing/Consumer teils offen |
| 5 | Audit/Krypto | HMAC im Break-Glass, Receipt-Kette nacktes SHA-256, verschluckte Audit-Errors, Anker nie verifiziert | ⚠ erkannt, teils offen |
| 6 | Content-Gates | Quality-Report falscher Key, PATCH stale Reports, leerer Korpus = bestanden, li-human-Regeln fehlen | ⚠ erkannt, teils offen |
| 7 | Persistenz | Restore tenant-Pfad, Backups ohne Keys, Meta-Whitelist, konsolidierte DBs nicht gesichert | ✅ Restore + Meta-Whitelist (Teil); Backups offen |
| 8 | Performance | 50 ms Event-Loop-Block, 300 s Slot-Block, DDL pro Budget-Call, Loop-Keyed Clients | ⚠ erkannt, offen |
| 9 | Frontend | SSE-Event-Namen falsch, tote Navigation, Stub-Buttons, doppelte EventSources, unsichtbare Features | ✅ in Bearbeitung |
| 10 | Standards/Reproduzierbarkeit | keine Hashes/Lockfile, CI ohne SAST/SBOM, Pydantic-v1 `.dict()`, Docs-Wahrheit | ✅ Requirements/CI/Pydantic Etappen 1–8; Docs offen |

## API-Validierung (Etappen 1–8) — TEILWEISE (Korrektur 23.11.2026)

- **146 Funde** (121 rohe `Dict=Body` + 25 HTTP-200-Fehler) — ursprüngliche Inventur.
- **Korrigierte Inventur 23.11.2026: weiterhin ~136 rohe `dict = Body(...)`**
  in `archon/routers/**` (u. a. `auth.py:178/227/277`, `erp.py`, `mesh.py`,
  `execution.py`). Die alte Behauptung „0 rohe Body-Dicts" war falsch.
- Neue Modelle überwiegend Pydantic v2, `extra="ignore"`; vereinzelt noch
  `extra="allow"` und `.dict()`-Reste. Direkte Python-Aufrufer vieler Router
  akzeptieren inzwischen Dict **oder** Modell (kein `AttributeError`-500 mehr).
- Verifikation: `compileall` grün; `pytest tests/ -q`: **1765 passed, 16 skipped** (Stand nach Phase-1-Welle 24.11.2026).

## Zweite Welle — zusätzlich behoben

- **Passkey-HITL**: Proof an `action` + `resource` gebunden, `authenticatorData`/
  Store-Fehler fail-closed (`backend/passkey_hitl.py`).
- **Tenant-Scope**: Offline-Vault (DB+Key+AAD), Taint-Guard, Egress-Log,
  PII-Vault und TTL-Cache sind jetzt tenant-scoped.
- **Tool-Output-Firewall**: `guard_result()` in MCP/Plugins/DAG-Chokepoints
  verdrahtet; Audit-Schreibfehler blockieren Tool-Calls.
- **Windows-ACLs**: echtes `icacls`-Härten + DACL-Verifikation in `secret_files.py`.
- **Startup/Shutdown**: `_assert_router_health` wirft jetzt wirklich (Lifespan
  re-raist), `/livez` + `/readyz` mit 503, Loop-Guards resetten beim Re-Lifespan,
  Shutdown-`gather` mit 10-s-Timeout.
- **Integrationen**: Watchdog-Killswitch-Env auf Service-Namen, SSRF-Schutz in
  `test-connection`, Env-Injection in `set_env_value` blockiert, Publish-Sweep
  nutzt Default-Webhook, `external_url`-Parsing stabiler.
- **Frontend (12 Punkte)**: SSE-Event-Namen korrigiert, `SidebarNav`/`HeaderTopBar`
  gemountet (Fake-Status entfernt), eine einzige gemeinsame `EventSource` statt
  2–3 Verbindungen, 30-s-Polling durch `archon:sse` ersetzt, alle Alert-/Stub-
  Buttons durch echte Handler/Panels ersetzt, 6 unsichtbare Content-Endpunkte
  plus Swarm/Mesh/Consensus/War-Room-UI verdrahtet, Port-Kommentare/PUT-Proxy
  korrigiert. `node --check` auf allen geänderten JS-Dateien: grün.
- **Infrastruktur (17 Punkte)**: CAS-Claim fail-closed + Lease-Guard bricht
  DAG bei Token-Verlust hart ab; DLQ-Consumer mit echten Replay-Handlern
  (`delegation_result`, `workflow_resume`) statt nur Ticker; `replay_job` default
  echter Replay; `dead`-Outbox → DLQ; `suspend()` im HITL-Gate-Pfad; Startup
  resumed Checkpoints tatsächlich; semantischer Cache im Dispatch-Pfad;
  Write-Batcher hat Produzenten; Budget-Aliase auf `BudgetBank`; Alert-Loop;
  Restore tenant-correct + Secrets; DATENVERLUST bricht Migration ab;
  War-Room blockiert per echter Decision; Swarm nicht mehr Dry-Run-Default;
  ein Inbox-Scanner; Concurrency-Gate fail-closed; JEV-Pruning im Request-Pfad.
  `compileall` Exit 0, Import-Smoke OK. Die damalige Zahl „40 Tests bestanden"
  war ein Teil-Scope; Stand 23.11.2026: **1727 Tests bestanden, 16 übersprungen**.

## Dritte Welle — kritische Restfundamente

- **Kanban-Doppelausführung**: `_execute_kanban_task_async` nutzt jetzt einen
  CAS-Lease mit 30-s-Heartbeat und gibt ihn im `finally` frei — der Deadlock-
  Watchdog kann keinen laufenden Task mehr reaktivieren.
- **Zero-Egress**: `explicit_category` darf die serverseitige Klassifikation
  nicht mehr abschwächen; bei Klassifikationsfehler fail-closed `confidential`.
- **Warrant-Pfad-Bypass**: alle Pfad-Aliase (`file_path`, `uri`, `target`, …)
  werden gegen `allowed_path_prefixes` geprüft; fehlendes Pfad-Argument bei
  Pfad-Constraint → deny.
- **Receipt-Kette**: HMAC-SHA256 mit ENV-Key (nacktes SHA-256 nur noch als
  lesbares Legacy-Format), Append-only-Trigger gegen UPDATE/DELETE,
  `hmac_protected` im Verify-Result.
- **li-human**: echte Stilregeln aus `config/voice.md` als Fallback, wenn die
  (nicht existierende) SKILL.md fehlt — Review-Node injiziert nie mehr „nichts".
- **Performance-Kaskade**: Backpressure/Config im `to_thread` (kein 50-ms-
  Event-Loop-Block mehr), 90-s-Gesamt-Deadline für die Provider-Fallback-
  Kette (statt ~308 s bei gehaltenem Slot), Budget-Schema-Init nur noch
  einmal pro DB-Pfad (statt 5–8× pro Dispatch).
- **Docs**: „28/28 umgesetzt" auf „implementiert, aber nicht verifiziert"
  korrigiert, mit Verweis auf den Konsolidierungsbericht.

## Vierte Welle — Default-Deny und Auditsicherheit

- **Taint-Gate**: `is_critical_egress_tool()` ist jetzt Default-Deny —
  `terminal`, `execute_code`, `computer_use`, `mcp__*`, `node_plugin:*` und
  alle unbekannten Tools triggern den HITL-Park; nur explizit harmlose Tools
  (`read_file`, `web_search`, …) sind ausgenommen.
- **Audit-Anker**: `verify_integrity()` vergleicht den letzten Anker-Hash mit
  dem Ketten-Head; Abweichung → `valid=False` (Tail-Loeschung erkannt).
- **Receipt-Kette**: HMAC-SHA256 aus ENV + Append-only-Trigger; Verify meldet
  `hmac_protected` und liest Legacy-SHA-256 weiterhin.
- **Break-Glass**: Klartext-Notfallkey liegt jetzt unter `data/security/` mit
  Modus 600, nicht mehr neben dem verschluesselten Vault und dem HMAC-Key.

## Fünfte Welle — Async-Korrektheit und Ressourcen

- **CancelledError**: DAG-Node-Loop fängt `asyncio.CancelledError` explizit,
  markiert Nodes `cancelled` und persistiert den Run-Status `cancelled` über
  einen eigenen Wrapper (vorher blieb der Run dauerhaft `running`).
- **Sync-SQLite im Dispatch**: `_log_dispatcher_usage` ist jetzt ein
  Async-Wrapper mit `asyncio.to_thread` — alle 11 Aufrufstellen `await`en ihn.
- **Loop-Keyed Clients**: `WeakKeyDictionary` statt `id(loop)`, plus
  `close_dispatcher_clients()` als Shutdown-Hook → kein FD-/Memory-Leak bei
  Reloads mehr.

## Verifikationsstand (Korrektur 23.11.2026)

- **pytest**: `.ci_venv\Scripts\python.exe -m pytest tests/ -q` → **1765 passed,
  16 skipped** (Stand nach Phase-1-Welle 24.11.2026; lokal ausgeführt, Exit 0). Der Gesamtlauf ist nachgeholt.
- **compileall**: über alle Produktivdateien → Exit 0.
- **Frontend**: `node_modules` fehlt lokal; `npm ci && npx tsc --noEmit &&
  npm run build` bleibt ein CI-Gate und ist hier **nicht** verifiziert.
- „100 % korrekt verdrahtet" ist daher weiterhin eine Einschätzung, kein
  durch Frontend-Build gedecktes Faktum. Alle anderen Audit-Funde sind behoben
  oder dokumentiert (siehe `AUDIT_ABSCHLUSS_2026_11_23.md`).

## Produktmodell-Korrektur (Benutzerentscheidung 23.11.2026)

**Content ist keine eigene Domäne.** Content ist Arbeit, die Workflows
erfordert — eine Marktanalyse und ein YouTube-Short sind in Archon derselbe
Vorgang: Task → Workflow → Agenten → Gate → Artefakt. Der Unterschied liegt
nur im Workflow-Template, nicht in der Oberfläche.

Konsequenz: Es gibt **keine separate Content-/Medien-UI** mehr.
Entfernt wurden (UI-Ebene, Backend bleibt erhalten):
- `frontend/src/app/content-studio/` (Route)
- `frontend/src/components/ContentMachineCockpit.tsx`
- `frontend/src/components/ContentStudioView.tsx` + `ContentStudio/*`
- `frontend/src/lib/content-flow.ts` + die `archonApi`-Content-Helfer und -Typen
- alle Navigationseinträge/Buttons/Links zu ``/content-studio`` in Sidebar,
  CRM-Seite, ExecutiveCockpit und WorkflowCockpit
- alle von mir zusätzlich eingefügten Content-/Advanced-Panels in der
  statischen App (View-Datei, Nav-Button, Handler) — Rückkehr zum Originalzustand

`backend/content_machine.py`, `archon/routers/content_machine.py`, Prompts,
Quality-Gates und Repurposing-Funktionen bleiben als **interne Bausteine**,
die von normalen Workflows aufgerufen werden (Implementierungsdetail, nicht
Produktfläche). Die vorhandenen RESTful-Endpunkte `/api/v2/content-machine/*`
bleiben unverändert.

## Bewusst NICHT umgesetzt (Benutzerentscheidung)

Siehe `NEVER_DO_LIST.md`: kein Coroutine-Replay, keine PostgreSQL-Migration.
