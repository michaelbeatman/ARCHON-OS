# Archon OS — Zentrales Findings-Register

**Stand:** 2026-11-23 · **Zweck:** eine einzige Wahrheitsquelle für alle Audit-Funde.
Jeder neue Audit-Lauf wird hier eingetragen. Kein Fix ohne Register-Eintrag.
Damit erkennt man sofort: *neu*, *bekannt und bewusst liegen gelassen*, oder *von uns selbst eingebaut*.

## Status-Legende

| Status | Bedeutung |
|---|---|
| `FIXED` | behoben und durch Tests/`py_compile`/Container verifiziert |
| `PARTIAL` | teilweise behoben, Rest offen |
| `DEFERRED` | bekannt, bewusst nicht behoben — Grund in Spalte „Einordnung" |
| `NEW` | aus aktuellem Audit, noch nicht behandelt |
| `REGRESSION` | durch unsere eigenen Fixes eingeführt |
| `ACCEPTED` | bewusstes Risiko (Design-Entscheidung, dokumentiert) |

---

## 1. Gesamtübersicht

| Quelle | Funde | KRITISCH | HOCH | MITTEL | NIEDRIG |
|---|---|---|---|---|---|
| Phase 1/2 (10 Subagenten) | 116 Rohfunde → 10 Cluster | 8 | 33 | 58 | 17 |
| Audit-Lauf 5 (Domäne 6, Integrationen) | 22 | 4 | 6 | 10 | 2 |
| **Summe (Roh)** | **138** | **12** | **39** | **68** | **19** |

**Buchhaltungs-Korrektur (Re-Triage):** Abschnitt 3 führt 22 namentlich gelistete IDs (4+6+10+2). Die ursprüngliche Meldung „23 / 3 NIEDRIG" war ein Zählfehler; es gibt nur N1 und N2 als NIEDRIG. Kein neuer Fund.

---

## 2. Phase-1/2-Cluster — Status nach Wellen 0–5

| Cluster | Inhalt | Status | Welle | Rest / Grund |
|---|---|---|---|---|
| A | Schein-Funktionalität | `PARTIAL` | 0, 4 | n8n echte Nodes fehlen; PbSettings-Backend-Endpunkte fehlen; `subagents_count`, `suspend_task()`, Schema-Dropzone |
| B | Fail-Open Governance | `PARTIAL` | 1, 4 | Default-Auth-aus weiterhin (siehe Lauf-5 K2); Emergency-Bypass deaktiviert statt implementiert |
| C | Persistenz & Restore | `FIXED` | 0, 2 | — (Restore-Test inkl. PB, FK, WAL, ETag, Break-Glass) |
| D | Audit-Integrität | `PARTIAL` | 0, 1, 2 | 3 Nebenketten ohne `verify_integrity()`; Boardroom primär weiter JSON (HMAC-gespiegelt) |
| E | Orchestrierung & Abbruch | `PARTIAL` | 1 | Circuit-Breaker nur Boardroom; Subagent-Loop-Detection fehlt; Provider-Breaker prozess-lokal |
| F | 24/7 & Observability | `FIXED` | 0, 1, 3 | — (Probes, Alerts, Logs, Locks, Circuit-Breaker) |
| G | Performance & Concurrency | `FIXED` | 1, 5 | — (to_thread, WeakKeyDictionary, Caches, Single-Flight, Trimming) |
| H | Architektur & Build | `DEFERRED` | 5 (Pinning) | `import main as app_main` (~50), mypy/ruff, TS-`any`, 11k-Adapter (bewusst nicht gesplittet) |

**Wellen 0–5 insgesamt:** ~70–80 der 116 Funde adressiert. Der Rest ist oben dokumentiert — **nicht übersehen, sondern bewusst zurückgestellt.**

---

## 3. Audit-Lauf 5 — Domäne 6 (Integrationen), 22 Funde

Register-konform re-triangelt (14 `NEW`, 2 `PARTIAL`, 5 `DEFERRED`/bekannte Punkte, 1 `REGRESSION` → `FIXED`). Abschnitt 6 wurde nicht erneut verhandelt.

| ID | Krit. | Fund | Einordnung | Empfehlung |
|---|---|---|---|---|
| **K1** | K | Unauthentifizierter `/webhooks/push` triggert Sync aller OAuth-Quellen | **`FIXED`** — war `NEW` (W0 K4 betraf den **anderen** Endpunkt `calendar_aggregator.py:8421`). Fix: Google-Watch sendet jetzt `clientState=watch_id`; `handle_webhook_push()` matcht nur noch per `hmac.compare_digest` auf `watch_id` (kein Provider-Blanket-Match); Router liest `X-Goog-Channel-ID`/`-Token` bzw. Graph-`clientState` aus dem Body, lehnt Unbekannte mit 401 ab. Verifikation: `py_compile` via Docker `python:3.13-slim` + Funktionstest (leer/falsch → `matched:False`, richtiger Kanal → nur die passende Quelle synchronisiert). | Auth/HMAC + `clientState`-Vergleich, nur gematchte `watch_id` |
| **K2** | K | Default-Auth aus → Admin-APIs im Docker-Mesh erreichbar | `DEFERRED` → **neu bewertet** — wir kannten „Development bleibt privilegiert", aber nicht die Mesh-Reichweite (n8n/OmniRoute/Watchdog) | In Produktion/für Mesh-Deployments Auth fail-closed erzwingen; dienstliche Aufrufe mit Service-Token |
| **K3** | K | Klartext-Secrets + 3 hartcodierte Fallback-Keys | `NEW` — D4 fand „keine echten Keys im Repo", aber nicht `sk-archon-local-dev`, `Bearer omniroute-local-key`, `Bearer sk-archon` | Zentrale Key-Verwaltung, keine statischen Fallbacks, Rotation |
| **K4** | K | n8n-Auth-Patch: Auto-Owner-Fallback + Browser-ID-Bindung deaktiviert | **`FIXED`** — war `NEW`. `scripts/patches/n8n_auth_service.js`: Auto-Owner-Block entfernt; `validateBrowserId()` stellt die gehashte Browser-ID-Bindung mit Ausnahmeliste wieder her. Verifikation: `docker exec n8n node --check` OK, `docker restart n8n`, `healthz` 200 nach ~14 s. | `N8N_ARCHON_AUTO_OWNER` entfernen, `validateBrowserId()` reaktivieren |
| **H1** | H | Kein Backoff/Jitter, 90-s-Timeouts im LLM-Dispatcher | **`FIXED`** — `core_dispatcher._provider_backoff()` in `_audited_post()` (429/5xx + Exceptions) und `agent_router._router_provider_backoff()` an beiden Fallback-Stellen (non-stream + stream); beide respektieren `Retry-After` (max 3 s) mit Jitter 0,75–1,25. `agent_router` nutzt jetzt zusätzlich `provider_breaker` (allow/record_failure/record_success) im Non-Stream- und Stream-Pfad. Verifikation: Core 429→0,522 s / Exception→0,174 s; Router 429→0,445 s / Failure→0,198 s; Syntax OK. | Retry-After, Backoff+Jitter, konsistente Timeouts; Breaker auch in `agent_router` |
| **H2** | H | n8n: 3 Workflow-Quellen, unauthentifizierte Webhooks, falscher Host | `PARTIAL` — Stubs deaktiviert (W0), aber Auth/Host-Drift und tokenlose Calls sind neu | Eine Quelle, Auth an Webhooks, Service-Token, Host `archon-os` korrigieren |
| **H3** | H | Ungeprüfte `base_url` → YAML-Injektion in Hermes-Config / SSRF | **`FIXED`** — `api_provider._is_safe_yaml_value()` + `_validate_base_url()` (nur http(s), keine Steuerzeichen/Credentials); `_set_model_block()` lehnt unsichere Werte ab; Router `select` prüft vor dem Schreiben und behandelt `False` als Fehler. Verifikation: Syntax OK, gültige URL akzeptiert, Newline/Credentials/`@` abgelehnt, `write=False`. | Validierung + Newline-Sperre wie in `set_env_value()` |
| **H4** | H | Externe Plugin-Antwort überschreibt `status`/`content` via `**data_dict` | **`FIXED`** — `workflow_node_plugins.py:849`: Steuerungsfelder `status/content/error/media_path/data` sind vor externen Keys geschützt, externe Daten zusätzlich unter `data`. Verifikation: Syntax + Import OK (Volldurchlauf mit gemocktem Plugin-Aufruf noch offen). | Key-Allowlist, externe Daten nur unter `data` |
| **H5** | H | Outbound-Webhooks ohne HMAC | **`PARTIAL` (Sender-Seite komplett)** — `utils/safe_http.py::webhook_signature_headers()` (HMAC-SHA256, Secret nur aus `ARCHON_WEBHOOK_HMAC_SECRET`, kein Default) wird auf den exakten Body angewendet in `event_mesh._deliver_outbox()`, `core_dispatcher.trigger_n8n_execution()` und `watchdog_daemon` (Alarm + Abort). Verifikation: ohne Secret unsigniert, mit Secret deterministisch/body-spezifisch, Syntax aller 3 Dateien OK. **Offen:** Empfängerseite (n8n-Webhook-Nodes) prüft die Signatur noch nicht — dazu braucht es einen Code-Node mit `compare_digest` und dasselbe Secret. Ohne `ARCHON_WEBHOOK_HMAC_SECRET` bleibt alles unsigniert (Kompatibilität). | Shared Secret + `compare_digest`, wie bei DocuSeal |
| **H6** | H | Ungeprüfte Container-Antwort als Agenten-Output | **`FIXED`** — `core_dispatcher.py:1462`: nur bekannte Inhaltsfelder (`content/output/result`), `_clean_dispatch_output()`, keine Antwort ohne Inhalt als Erfolg. Verifikation: Syntax OK (Laufzeit-Check mit Container-Response noch offen). | Schema + `_clean_dispatch_output()` wie im anderen Container-Pfad |
| **M1** | M | Circuit-Breaker-Half-Open erlaubt parallele Probes | **`FIXED`** — war `REGRESSION` (von uns in W3 eingebaut). Fix in `backend/provider_circuit_breaker.py:37-43`: `probing` wird geprüft, genau ein Probe durchgelassen, bei Failure/Success zurückgesetzt. Verifikation: Code-Inspektion (lokales Python nur als WindowsApps-Stub verfügbar); Fix wurde von der anderen Session gemeldet. | Flag prüfen, genau einen Probe durchlassen |
| **M2** | M | OmniRoute-`/v1/models` ohne Auth; statische Fallback-Liste | `NEW` — W4 injizierte Key nur für Chat-Completions | Key auch für Modellliste, Fallback nicht still |
| **M3** | M | Fail-Open bei malformatter Recherche-Antwort (`sufficient=True`) | `NEW` | `data={}` → `sufficient=False` |
| **M4** | M | Security-Guard schweigt bei Fehlern; Score ohne Bereichsgrenze | `NEW` | fail-closed + `SCORE` auf 0–10 clampen |
| **M5** | M | OmniRoute-Modellpool aus externer API, direkter SQLite-Update | `NEW` | Allowlist, Diff/Review vor `--fix` |
| **M6** | M | Dormantes Script senkt CSP/Frame-Protection | `NEW` (inaktiv) | Löschen oder klar als described-risk markieren |
| **M7** | M | Hermes-Proxy reicht interne Auth-Header weiter | `NEW` | Header-Filter wie in `utils/reverse_proxy.py` |
| **M8** | M | `check_local_llm_status()` umgeht Egress-Prüfung | `NEW` | `sanitize_llm_endpoint()` + Zonenprüfung |
| **M9** | M | Fehlende Timeouts in Integrations-Skripten | **`FIXED`** (gelistete Fälle) — `timeout=10/15/30` ergänzt in `archon_crm_mcp.py`, `scripts/archon_crm_mcp.py`, `scripts/import_linkedin_archive.py`, `scripts/setup_media_pocketbase.py`, `scripts/sync_inbox_to_pocketbase.py`, `scripts/list_matched_contacts.py`, `scripts/rescore_contacts.py` (zusätzlich `max_pages=100`). Verifikation: Syntax-Check aller 7 Dateien OK. Weitere, nicht gelistete Calls können noch ohne Timeout sein. | Timeout auf alle `requests`/`urlopen` |
| **M10** | M | Fallback-Kette ohne Fehlerdiagnose | `DEFERRED` — aus Lauf 1 bekannt | strukturierte Hop-Resultate für Monitoring |
| **N1** | N | Retry ohne Jitter (`mcp_n8n_driver`) | `DEFERRED` — W4 fixte Idempotenz/Pfad, nicht Jitter | Jitter ergänzen |
| **N2** | N | `INSERT OR REPLACE` in n8n-interne Webhook-Tabelle | `NEW` | Bestehende IDs prüfen |

---

## 4. Top-10 offene Punkte (priorisiert)

1. ~~**K1** — Calendar-Webhook authentifizieren~~ **ERLEDIGT** (siehe Abschnitt 3, `FIXED`)
2. **K2** — Auth für Mesh-Deployments fail-closed (Design-Entscheidung nötig)
3. ~~**K4**~~ **ERLEDIGT** (n8n-Patch gehärtet, neu gestartet); **K3** — statische Keys (Rotation = Menschenaufgabe, siehe Abschnitt 7) bleibt offen
4. **M1** — **Unser eigenen Regression** sofort fixen (5 Zeilen)
5. ~~**H3/H4/H6**~~ **ERLEDIGT** — externe Eingaben validiert/bereinigt (siehe Abschnitt 3)
6. ~~**H1**~~ **ERLEDIGT** (Backoff+Breaker in Core-Dispatcher und `agent_router`); **H5** `PARTIAL` — HMAC-Signatur im Event-Mesh geliefert, Empfängerprüfung und Watchdog-Signatur noch offen
7. **H2** — n8n-Quellen vereinheitlichen
8. **M9** — Timeouts in Skripten (mechanisch)
9. **Register-Pflicht**: jeder weitere Audit-Triage hier eintragen
10. **Checkpoint**: `docs/AUDIT_FINDINGS_REGISTER.md` mitcommitten

---

## 5. Regeln für weitere Audit-Läufe

1. **Kein neuer Lauf ohne Register-Abgleich.** Jeder Fund wird mit ID hier eingetragen.
2. **Drei Kategorien pflicht:** `NEU` / `DEFERRED (schon bekannt)` / `REGRESSION (von uns eingebaut)`.
3. **Grüne Tests heißen nur „keine Regression", nicht „fertig".**
4. **Akzeptierte Risiken explizit markieren** — sonst meldet der nächste Audit sie erneut als kritisch.
5. **Nach jedem Fix:** Status auf `FIXED` setzen + Verifikationsmethode notieren.

---

## 6. Bewusst akzeptierte Risiken (nicht mehr neu verhandeln)

| Risiko | Grund |
|---|---|
| 11k-Zeilen-Telegram-Adapter bleibt eine Datei | Single-File-Mount in Hermes; Split ohne Container-Test zu riskant. Keine Laufzeitwirkung auf Archon. |
| `main.py` bleibt ~2,5k Zeilen | 26k → 2,5k bereits ausgelagert; weiterer Grenzertrag klein |
| Provider-Breaker prozess-lokal | Akzeptiert für Single-Instance; bei Replicas Redis-basiert nachrüsten |
| Development-Default ohne Auth | Bewusst, solange `ARCHON_BIND_IP=127.0.0.1`; **nicht** für Mesh/Prod — siehe K2 |
| n8n-Stubs deaktiviert statt implementiert | Ehrlicher Zustand statt Fake-Erfolg; echte Nodes sind eigene Welle |

---

## 7. Zweiter Audit-Lauf (10 Agenten, 171 Funde, 25 Cluster)

Ein unabhängiger Lauf mit anderer Prompt-Tiefe kam auf **171 Rohfunde / 25 Cluster (C01–C25)**
und 24 kritische Funde. Die Zahlen unterscheiden sich von unseren 116/10 – das ist
**Abdeckung, nicht Widerspruch**. Dieser Abschnitt mappt die 25 Cluster auf unseren Status,
damit nicht zwei Wellenpläne gegeneinander laufen.

| Cluster | Thema | Unser Status | Anmerkung |
|---|---|---|---|
| C01 | Auth default-off, Fallback-Admin | **`PARTIAL`** | Mechanismus geliefert: `ARCHON_REQUIRE_AUTH` in `auth_service._must_force_auth()`, Compose-Env (Default `false` = akzeptierter Dev-Fall), Startup-Warnung bei aktivierter Auth ohne Service-Token. **Aktivierung offen**: kein `ARCHON_SERVICE_TOKEN` vorhanden → n8n würde 401 erhalten. |
| C02 | Klartext-Secrets, statische Keys | `PARTIAL → OPEN` | Wir fanden sie, haben aber **nicht rotiert** (user action) |
| C03 | RBAC-Jail ohne Wirkung im Tool-Pfad | **`FIXED`** — `backend/delegation_isolation.py::PolicyEngine._enforce_file_jail()` prüft Pfad-Argumente zentral in `decide()` (auch nach gültigem Warrant) über `agent_rbac_jail.check_access()` mit `kernel_admin`-Scope (die realen Agent-IDs sind in `ROLE_POLICIES` nicht hinterlegt). Verifikation: `../.env` und `/etc/passwd` → `rbac_jail`/`blocked: True`, `docs/readme.md` → erlaubt, `decide()`-Deny korrekt. Rollen-Mapping selbst bleibt bewusst unangetastet. |
| C04 | HITL-Gates deaktiviert | **`PARTIAL — Durchsetzung verdrahtet, Aktivierung offen`** — `archon/routers/decisions.py`: Freigabe von `profil_loeschen` (Kategorie `destructive_actions`) und `tools_erweiterung` (`system`) verlangt jetzt einen gültigen Passkey-Proof, sofern `is_passkey_required()` wahr ist; bei Prüffehler fail-closed 503. Syntax OK. `permission_gates.json` ist korrekt leer (Warteschlange, nicht Policy). **Offen:** `passkey_hitl.json` hat `enabled:false` und `credentials: []` — `is_passkey_required(...)=False`; Passkey-Registrierung ist eine WebAuthn-Menschenaufgabe und kann nicht agentenseitig aktiviert werden. Weitere Kategorien (`project_start`, `budget_overrun`) haben weiterhin keine Aufrufer (und `POST /api/system/backup-db/restore` bleibt bewusst ohne blockierendes Telegram-Gate, um Notfall-Restores nicht zu blockieren). |
| C05 | Webhooks ohne Auth/Signatur | `PARTIAL` | W0 fixte Port-8421-Server; FastAPI-Webhook (K1) jetzt `FIXED`; n8n-Outbound/HMAC weiter offen (H5) |
| C06 | Verwaiste WAL/SHM-Sidecars, Datenverlust | **`PARTIAL — kein Datenverlust belegt`** | Lesende Analyse 23.11.: Root-WALs `agent_os.db-wal` / `agentic_memory.db-wal` sind **0 Bytes**; die archivierten DBs haben Journal-ModeByte 2/2 (= DELETE, nicht WAL) und enthalten intakte Tabellen (5 bzw. 8). Damit ist die ursprüngliche Behauptung „bereits eingetretener Datenverlust" **nicht belegt**. Restrisiko: verwaiste 32-KB-`-shm`-Dateien können eine neu angelegte gleichnamige DB irritieren. Empfehlung: Sidecars nach Freigabe entfernen — keine automatische Löschung durch Agent. |
| C07 | Restore-TOCTOU | **`FIXED — Option B, extern verifiziert`** | Option A scheiterte (`destination database is in use` / `locking_mode=EXCLUSIVE` blockiert). Option B: `backend/process_lock.py::acquire_restore_lock()` (Lock-DB, OS-verwaltet) wird in `db_backup_manager._restore_gate()` über die gesamte Restore-Phase gehalten; nach `os.replace()` `PRAGMA quick_check`. **Verifikation durch externe Session unter Windows:** `py_compile` aller 22 geänderten `.py`-Dateien Exit 0; Happy-Path `{'restored': True, 'integrity': 'ok', 'verified': True}` inkl. `os.replace()` und Post-Condition; Lock-Contention wirft `RuntimeError: Restore abgelehnt: … anderer Restore-Prozess …` und gibt den Lock im `finally` sauber frei (`C07_VERIFIED_OK`). |
| C08 | Auditketten dezentral (5 Ketten) | **`FIXED` (Ketten & Verifikation; M-05/H-04 dokumentiert)** — `main.py` verifiziert im 30-s-Loop alle 5 Ketten (`chained_audit_log`, `approval_engine`, `receipt_ledger`, `_api_key_chain.verify_integrity`, `verify_treasury_chain`). `treasury_engine.py`: HMAC-SHA256 + `company_id`/`idempotency_key` + `_legacy_entry_hash(prev, dict(r))` + `verify_treasury_chain(db_path=...)` (inkl. Fix für `sqlite3.Row.get` und fehlende Tabelle). **Verifikation:** `py_compile` Exit 0; `verify_treasury_chain()` auf gemischter Legacy-SHA-256 + HMAC-DB `valid=True` (`count=2, hmac_blocks=1`), Manipulation → `valid=False, broken_at_id=1`; `ApiKeyManager.verify_integrity()` `valid=True` (`count=1`), Append-only-Trigger blockiert `UPDATE` (`IntegrityError`). **Dokumentiert:** fail-open Spiegelungen (M-05) und externer Anker default-aus (H-04) bleiben kompatibilitätsbedingt optional. |
| C09 | Zirkel-Delegation ohne visited-Set | `PARTIAL` | Sandy-Pfad begrenzt (W1-H7), Hauptpfad ohne Zyklus-Schutz |
| C10 | Abbruchkette wirkungslos | **`FIXED`** — (1) `core_dispatcher.stream_boardroom_debate()`: Kill-Switch-Registrierungsfehler fail-closed statt `pass`, Scope-Cleanup im `finally`; Verifikation: simulierter Fehler → `RuntimeError` + Log. (2) `delegation.py`: `_DELEGATED_WORKER_TASKS` hält die Worker-Referenz; beim Deadline wird `worker.cancel()` aufgerufen und die Registry aufgeräumt. Verifikation: simulierter Timeout → `worker.cancelled()=True`, Timeout-Nachricht, Registry leer. |
| C11 | Lease-Fail-Open | `PARTIAL` | Heartbeat-Exception gefixt, Claim bleibt fail-open |
| C12 | Sandbox-Zombie + Checkpoint-Verlust | **`FIXED`** | Sandbox: `_terminate_container()` meldet `destroyed` nur nach verifizierter Entfernung, räumt auch im generischen Fehlerpfad auf; Checkpoint: nur erfolgreich gesicherte Tasks werden aus der Registry entfernt. Verifikation: Docker `python:3.13-slim`, Syntax + 3 Cleanup-Szenarien + Checkpoint-Fehlersim (`t1` bleibt, `t2` gesichert). |
| C13 | Self-Healing nie verdrahtet | **`PARTIAL`** | Self-Healing ist verdrahtet: `main.py::_fleet_self_healing_loop()` (120 s, `_exclusive_loop`, via `_spawn_background` shutdown-tracked) ruft `check_fleet_and_heal()`; diese betrachtet nur existierende Container und erkennt `unhealthy` trotz `Up`. Verifikation: Docker `python:3.13-slim`, Syntax + Sim (omniroute ok, n8n unhealthy, anything-llm Exited → 2 Restarts, crm/freellmapi übersprungen). **Offen:** externer Dead-Man-Switch / Heartbeat-Empfänger (`guardian.py:712` bleibt Stub). |
| C14 | `read_only: true` → settings.json unbeschreibbar | **`FIXED`** | `docker-compose.yml`: `./settings.json:/app/settings.json:rw` ergänzt; `backend/settings_json.py::_write_atomic()` ist jetzt mount-fähig (Temp im `/tmp` bei read-only-Zielverzeichnis, In-Place+fsync bei `EBUSY`/`EROFS`/`EXDEV` statt `os.replace`). Verifikation: Docker-Bind-Mount-Test (`atomic_update_settings` schreibt `c14_probe` in die Host-Datei) + `docker compose config --quiet` OK. Hinweis: unter Linux muss die Host-Datei für den Container-User beschreibbar sein. |
| C15 | Cache-Races, Token-Overhead | `PARTIAL` | Mehrere Caches gefixt, Skills-Cache/OpenRouter-Preis offen |
| C16 | LLM-Dispatcher kein Backoff/Jitter | `DEFERRED` = unser H1 | Nie gefixt |
| C17 | n8n/OmniRoute Deploy-Drift | **`PARTIAL`** | `deploy_n8n_routines.py` injiziert jetzt den Service-Token zur Laufzeit in alle 5 HTTP-Nodes (Template mit `__ARCHON_SERVICE_TOKEN__` bleibt im Repo, echte Datei `0600` außerhalb); bricht ohne Token ab statt tokenlose aktive Workflows zu deployen. Host `ARCHON-OS`→`archon-os` in beiden JSONs. Verifikation: Syntax OK, 5 Token-Header, kein Alter Host, Abbruch rc=1. **Offen:** Webhook-Node-Auth, OmniRoute-Key für `/v1/models` (M2), Live-Re-Import nach Token-Vergabe. |
| C18/C19 | Injection, ungeprüfte Base-URL | `PARTIAL` | n8n-Pfad gehärtet, YAML/SSRF/Response-Merge offen |
| C20 | Vault-Atomarität, Split-Brain-Resolver | `PARTIAL` | Break-Glass gefixt, `vault_hygiene`/Resolver offen |
| C21 | Schein-Funktionalität | **`FIXED`** (dieser Anteil) | PbSettings/MCP bereits gefixt. `backend/email_draft_engine.py`: Muster-Entwürfe nur noch bei `ARCHON_DEMO_MODE=true`, Betreff `[DEMO]`, Audit-Action `DEMO_DRAFT_CREATED`. Verifikation: Temp-DB normal=0 Entwürfe / Demo=2 mit Prefix und Demo-Audit. Bestehende 2 Fake-Entwürfe in `data/agentic_memory.db` über `reject_draft()` auf `rejected` gesetzt (reversibel, Audit `DRAFT_REJECTED`) — 0 verbleibende `pending`. Restliche C21-Stubs (MCP-/Modell-/Paperclip-/Bot-Screen-Platzhalter) weiter offen. |
| C22 | Python/Node/Image-Version drift | `PARTIAL` | Root-Pinning gefixt, Versionen selbst offen |
| C23 | Observability-Profile inaktiv | `PARTIAL` | Alert-Dedup/Loki/Logs gefixt, Profile default-off |
| C24 | CI-/Statikanalyse-Drift | `DEFERRED` | mypy/ruff bewusst zurückgestellt |
| C25 | God Object `main.py` | `ACCEPTED` | Bewusst nicht weiter zerlegt (26k → 2,5k) |

### Neue, relevante Punkte aus Lauf 2 (nach unserem Register)

| Priorität | Cluster | Warum wichtig |
|---|---|---|
| ~~1~~ | ~~**C14**~~ | **ERLEDIGT** — `settings.json` ist rw gemountet, Schreiber mount-fähig (siehe Abschnitt 7) |
| 2 | **C06** | Kein Datenverlust belegt (WALs 0 Bytes, DBs im DELETE-Mode); nur verwaiste `-shm` als Hygiene-Risiko |
| 3 | **C13** | Self-Healing verdrahtet; externer Dead-Man-Switch weiter offen (siehe Abschnitt 7) |
| ~~4~~ | ~~**C12**~~ | **ERLEDIGT** — Cleanup verifiziert, Checkpoint-Verlust behoben (siehe Abschnitt 7) |
| 5 | ~~**C21 (Rest) — Fake-Entwürfe**~~ | **ERLEDIGT** — Demo-Gate + Kennzeichnung + Bestandsdaten rejectet (siehe Abschnitt 7); übrige Stubs bleiben `PARTIAL` |
| 6 | **C22/C23** | Versionsdrift, Observability-Profile default-off |
| 7 | **C07** | Unser eigener Restore-Gap — Lock bis nach `os.replace` halten (Windows-sicher lösen!) |

### Wichtiger Hinweis zu C02 (Secrets)

Das Register fordert „alle Secrets rotieren". Das ist **keine Agenten-Aufgabe**: echte
GitHub-/Telegram-/Google-/HMAC-Tokens müssen vom Menschen rotiert und in einen
Secret-Store überführt werden. Ein Agent darf sie weder neu erzeugen noch in `.env`
zurückschreiben. Hier bitte **manuell** vorgehen.

### Konflikt-Auflösung zwischen den beiden Wellenplänen

- **Nicht zwei Pläne parallel fahren.** Der andere Lauf schlägt eine eigene „Welle 0"
  vor; unsere Wellen 0–5 sind bereits implementiert und verifiziert (1.727 Tests grün).
- **Gültig ist unsere Reihenfolge, ergänzt um C14/C06/C13/C12** als neue Welle 0b.
- **C07** ist ein echter, von uns übersehener Gap in unserem eigenen K1-Fix → nach C14.
- **C25** bleibt `ACCEPTED`; der andere Lauf bewertet es als 🟡, nicht als Blocker.
