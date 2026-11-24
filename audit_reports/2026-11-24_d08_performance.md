# Audit D08 — Performance, Concurrency & Engpässe
**Projekt:** Archon OS v0.5.7.4 · **Stand:** 24.11.2026
**Domäne:** Performance, Concurrency & Engpässe (Subagent D08)
**Methode:** Echter Code gelesen (nicht Docs/Kommentare), gezielte Regex-Suche, LOC-Messung via `read`-Offset-Overflow. Shell/PowerShell war in dieser Session gesperrt (`Zugriff verweigert os error 5`), daher **keine Byte-Größenmessung** möglich — Größenangaben zu JSON/CSV stammen aus der Aufgabenstellung und werden als *behauptet* gekennzeichnet; alle LOC/Zählwerte sind gemessen.

---

## 1. Scope & Methodik

### 1.1 Geprüfte Dateien (Auszug, alle an Produktionspfaden)
| Datei | LOC (gemessen) |
|---|---|
| `main.py` | 2.761 |
| `core_dispatcher.py` | 2.546 |
| `backend/operations_api.py` | 3.549 |
| `archon/core/orchestration.py` | 1.560 |
| `archon/core/mission_control.py` | 1.155 |
| `api_provider.py` | 1.090 |
| `local_memory_bridge.py` | 984 |
| `archon/routers/templates.py` | 545 |
| `archon/core/runtime.py` | 244 |
| `archon/core/cache.py` | 119 |
| `backend/async_write_batcher.py` | 205 |
| `static/index.html` | 13.790 |
| `static/hermes-webui/i18n.js` | 26.390 |
| `static/hermes-webui/panels.js` | 13.391 |
| `static/js/agent_profiles.js` | 4.626 |
| `static/js/chat_engine.js` | 1.280 |

### 1.2 Quantitative Suche (Treffer, gemessen)
- `asyncio.to_thread`: **>200 Treffer** über die Codebasis (Top: `core_dispatcher.py` 10, `archon/routers/v2_capabilities.py` ~30, `backend/operations_api.py` ~25, `backend/workflow_scheduler.py` 8, `main.py` 12). Offloading ist flächendeckend vorhanden.
- `run_io_bound`: **4 Treffer** (`archon/core/runtime.py:98,102`, `archon/core/orchestration.py:335-336`, `archon/routers/kanban.py:16,136,169,176,210`).
- `json.load(`: **~160 Treffer** in Produktionscode (ohne Tests). Die allermeisten liegen in `def`-Funktionen oder sind mit TTL/mtime-Cache versehen — Ausnahmen siehe Befunde 1, 2, 20, 25.
- `SELECT *`: **>120 Treffer**, davon ~25 ohne `LIMIT` auf potenziell großen Tabellen (siehe Befunde 15–19).
- `CREATE INDEX IF NOT EXISTS`: **~60 Treffer** — Indizes sind breit vorhanden.
- `PRAGMA journal_mode=WAL` + `synchronous=NORMAL`: **~40 Dateien** — Tuning ist flächendeckend umgesetzt.
- `new EventSource(`: **11 Treffer** in `static/` (1 Bussocket `chat_engine.js:121`, 6 streamspezifische in `messages.js`, je 1 in `terminal.js`, `sessions.js` ×2, `panels.js:2810`).
- `setInterval(`: **>40 Treffer** in `static/js` + `static/hermes-webui` (Polling-Fallbacks und Heartbeats).
- `AbortController`: **~8 Treffer** (u. a. `crm_studio.js:180`, `erp_studio.js:1434`, `css_live_studio.js:1612-1619`, `agent_profiles.js:2722`) — punktuell, nicht flächendeckend.

### 1.3 Bewusst nicht vertraut
Kommentare wie „gemessen 1,0–3,5 s" (`archon/core/cache.py:4-5`) oder „verhindert pids_limit-Exhaustion" (`runtime.py:103`) wurden als **Behauptungen** behandelt und nur dort als Evidenz akzeptiert, wo der Code sie stützt.

---

## 2. Befundtabelle

| # | Dateipfad | Zeile(n) | Kritikalität | Kategorie | Technischer Nachweis | Impact | Empfehlung |
|---|---|---|---|---|---|---|---|
| 1 | `api_provider.py` / `core_dispatcher.py` | 709–743 / 968–972 | **Hoch** | Blocking I/O im Dispatch | Jeder Dispatch ruft `api_provider.collect_keys()` synchron im `async def` auf; `collect_keys()` lädt den Provider-Katalog (`_load_json`, ~190 Provider), liest 2 zentrale `.env` und sweep-t **alle** Profile-Verzeichnisse (`os.listdir(PROFILES_DIR)` + `_read_flat_env` pro `.env`, Zeilen 736–742). Kein TTL-Cache für `collect_keys()`. | Bei ~70 Profilen: 70+ `open()`-Syscalls + Parser pro LLM-Call, serial im Event-Loop →Latenz und Loop-Starvation unter Parallelität. | `functools.lru_cache`/TTL auf `collect_keys()` (mtime-Invalidierung wie in `_load_json`) oder einmalig beim Startup in den Cache laden und per HITL invalidieren. |
| 2 | `archon/routers/chat.py` | 1059–1069 (Funktion ab 156/175, Generator → 1073) | **Hoch** | Blocking I/O in async SSE | Im `async`-Generator `chat_event_stream()` werden `_save_message_to_db(...)` und `_record_session_model_usage(...)` **ohne** `asyncio.to_thread` direkt aufgerufen (sqlite3-Schreibzugriffe). | Jeder abgeschlossene Chat-Stream blockiert den Event-Loop für die Dauer zweier SQLite-Commits; bei N parallelen Chats_ADDITIV. | Beide Aufrufe via `await asyncio.to_thread(...)` auslagern (Muster bereits an `chat.py:777,787,797,1172` vorhanden). |
| 3 | `archon/routers/mission_control.py` / `archon/core/mission_control.py` | 89–101, 205–207 / 847, 1037, 1133 | **Hoch** | Race Condition / Cache | `_MC_STATE_CACHE` ist ein plain `dict`, wird im async Endpoint ohne Lock gelesen/geschrieben (`res_payload` inkl. Tenant-ID), parallel dazu aus Threadpool-Mutationen (`to_thread(update_mc)`) nur `["ts"]=0.0` gesetzt. Kein `asyncio.Lock`/`threading.Lock` schützt den Cache. | Gestelte/Fremd-Tenant-Payload oder veraltete 3-s-Cache-Treffer bei parallelen Task-Updates; `data` und `tenant` können aus verschiedenen Requests stammen (torn state). | Cache-Zugriff unter ein `threading.Lock` legen oder Cache im `ttl_cache`-Modul (`archon/core/cache.py`) mit Tenant-Key führen. |
| 4 | `core_dispatcher.py` | 915–953 | **Hoch** | Token-Overhead | `full_system_prompt` = `system_prompt` + `registry_prompt` (Prompt-Registry, Zeile 926) + `core_mem_addon` (937) + `memory_context_addon` (892) + `prefetch_addon` (911) — **ohne** Längenbudget/Truncation. `history[-8:]` (957) und `learnings limit=4` (884) sind begrenzt, der Rest nicht. | Bei 70 Profilen mit Full-SOUL plus Registry-Prompt plus Memory-Blöcken wächst der System-Prompt unkontrolliert; direkte Kosten- und Latenzwirkung pro Dispatch. | Globales Token-Budget für den System-Prompt (z. B. 4–6k Tokens) mit Priorisierung: SOUL > Registry > Core-Memory > Prefetch; `token_clipper` vorhanden, aber hier nicht verdrahtet. |
| 5 | `backend/operations_api.py` | 237–272 | **Hoch** | N+1-Datei-I/O | Beim Cache-Miss iteriert `_load_profiles_map()` über **alle** Verzeichnisse in `get_primary_hermes_profiles_dir()` und öffnet pro Profil `profile.yaml` (YAML-Parse) **und** `SOUL.md` (Zeilen 245–267) — N+1-Dateizugriffe, ungedrosselt. | ~140 `open()`-Operationen + YAML-Parses pro Cache-Miss; der 300-s-Cache von `profiles.py` entlastet dies nicht, weil hier ein separater Cache (`_PROFILES_MAP_CACHE`) genutzt wird. | SOUL.md nur für Profile laden, die `prompt` benötigen (Lazy-Load); YAML-Parse in `asyncio.to_thread`; gemeinsamen Cache mit `profiles.py` nutzen. |
| 6 | `archon/routers/kanban.py` | 153–157 | **Hoch** | SELECT * ohne LIMIT | `SELECT * FROM tasks WHERE status != 'archived'` und `SELECT * FROM task_links` — vollständige Tabellen, kein `LIMIT`, keine Spaltenprojektion. Danach Python-Filterung. | O(Tasks + Links) Speicher und Transfer pro Request; bei wachsendem Board linear steigende Latenz. | Spaltenprojektion + `LIMIT`/Pagination; für die hier benötigte Aggregation `COUNT(*)`/`WHERE`-Pushdown in SQL. |
| 7 | `static/js/prompt_studio.js` | 192, 618 | **Hoch** | Frontend-Rendering | `filtered.forEach(t => { card.innerHTML = ... })` baut für **jeden** Treffer ein DOM-Element. Bei 832 Katalogenträgen (Doc-Behauptung) entstehen 832+ Karten inkl. `lucide.createIcons()`. | Blockiert den Hauptthread beim Rendern/ Filtern; hoher Speicher und Reflow-Aufwand, kein Virtualized Rendering. | Windowing/Virtualized List (nur sichtbare Items rendern) oder „Load more"-Pagination (50 pro Batch). |
| 8 | `backend/operations_api.py` | 493–1045 (Aufrufkette) | **Hoch** | Task-State Check-Then-Act | `update_task_status` liest Task via `to_thread(_kanban_load_task_sync)` (1045), prüft Autonomie-Gate (1072), markiert started (1078) und assigned (1088) in **getrennten** SQLite-Transaktionen; Lease-Fencing via `deadlock_supervisor.acquire_lease` (932) + Heartbeat (1168, 1213). | Zwischen den Schritten kann ein zweiter Worker denselben Task übernehmen; Fencing begrenzt, aber nicht vollständig (Heartbeat-Fenster). | Alle State-Übergänge in EINE `BEGIN IMMEDIATE`-Transaktion (MusterExists in `mission_control.update_mission_control_data`, 1100–1134). |
| 9 | `archon/core/runtime.py` / `archon/routers/operations_sysops.py` | 81–84, 162–181 / 296–341 | **Mittel** | SSE-Subscriber-Leak | `operations_sysops.api_stream_task_execution` registriert `q` in `main._SSE_SUBSCRIBERS` und der Generator läuft `while True` (313) **ohne** `request.is_disconnected()`. Entfernung nur im `finally` (329–341), das auf `CancelledError` angewiesen ist. `runtime.broadcast_event` entfernt nur bei `QueueFull`-Exception (110–120). | Bei Clients, die die Verbindung abnormal beenden, bleibt die Queue registriert und erhält bis 256 Events; over time wachsende Subscriber-Liste. | `request.is_disconnected()` in die `while`-Bedingung aufnehmen (Muster in `operations_org.py:539`) und Heartbeat-Timeout ergänzen. |
| 10 | `backend/event_mesh.py` | 886–903;整个 Datei | **Mittel** | Memory/Disk-Leak | `event_mesh_log`, `effect_ledger`, `event_mesh_outbox` werden laufend befüllt (`ingest_inbound_event`, `process_outbox`), es gibt **keine** `DELETE`-/Retention-Routine (Suche nach `DELETE FROM event_mesh_log|effect_ledger` → 0 Treffer). | Unbegrenztes DB-Wachstum; `SELECT * FROM event_mesh_log ORDER BY id DESC LIMIT ?` (891) wird mit der Zeit teurer (Index fehlt auf `id`? PK vorhanden, aber Log-Größe skaliert). | Retention-Job (z. B. 30 Tage) + `VACUUM`/Index auf `created_at`. |
| 11 | `backend/async_write_batcher.py` | 143–179 | **Mittel** | unbounded growth | `batched_telemetry_events` wird per `executemany` befüllt (157–165), `get_stats()` zählt `COUNT(*)` (184). Keine Lösch-/Retention-Logik im Modul. | Langfristig wachsende Tabelle; `COUNT(*)`-Abfrage in `get_stats()` wird linear teurer. | Partitions-/Retention-Strategie oder Ringpuffer mit `DELETE ... WHERE created_at < ?`. |
| 12 | `archon/core/mission_control.py` | 125–138, 663–670, 769–781, 805–846 | **Mittel** | Connection pro Call | Jede MC-Operation ruft `_connect_kanban()` auf (neuer `sqlite3.Connection`) und schließt ihn in `finally`; kein Pool, kein Thread-local Reuse. `_MC_STATE_CACHE` wird nur invalidiert, nie als Daten-Cache genutzt. | Bei hoher Task-Frequenz viele connect/close-Zyklen; WAL-PRAGMA nur einmal pro Pfad (`_KANBAN_PRAGMA_INITIALIZED`, 110) — korrekt, aber der Connect-Overhead bleibt. | Thread-lokale Connection oder kleiner Pool (`queue.Queue` von Connections) analog `hermes_proxy.py`. |
| 13 | `api_provider.py` | 991–1034 | **Mittel** | Datei pro Call | `list_profiles_with_model()` liest `agent_profiles.json` (behauptet ~1 MB) bei jedem Aufruf ohne Cache (1011–1015) und ruft für jeden Eintrag `read_profile_config(pid)` (1024) auf. | Bei 70 Profilen: 70+ Datei-Reads pro Aufruf; kein mtime-Cache wie in `_load_json` (121–145). | Auf den bestehenden `_JSON_CACHE` umstellen und `read_profile_config` mit mtime-Cache versehen. |
| 14 | `backend/audit_log.py` | 1000–1002 | **Mittel** | SELECT * ohne LIMIT | `cur.execute("SELECT * FROM audit_log ORDER BY id ASC")` — vollständiger Audit-Log in den Speicher, kein `LIMIT`. | Bei wachsendem Audit-Log linear steigender Speicher/Transfer; UI-Endpunkte werden träger. | `ORDER BY id DESC LIMIT ?` mit Default-Cap (z. B. 200) und Pagination-Cursor. |
| 15 | `backend/gdpr_compliance_engine.py` | 928 | **Mittel** | SELECT * ohne LIMIT | `conn.execute("SELECT * FROM gdpr_ropa_activities ORDER BY activity_id ASC").fetchall()` — komplette Tabelle. | Unnötiger Speicher bei großen ROPA-Inventaren. | Spaltenprojektion + `LIMIT` / Pagination. |
| 16 | `backend/execution_receipt_ledger.py` | 312 | **Mittel** | SELECT * ohne LIMIT | `SELECT * FROM execution_receipts_ledger ORDER BY id ASC` — vollständiges Ledger. | Ledger wächst mit jedem Dispatch; vollständiges Laden bei jedem `verify_chain_integrity`-Aufruf (`main.py:1179`). | Nur benötigte Spalten + `LIMIT`; für Integritätsprüfung streamen/fenstern statt `fetchall()`. |
| 17 | `backend/hybrid_search_engine.py` | 136 | **Mittel** | Full-Table-Scan pro Query | `for r in conn.execute("SELECT * FROM hybrid_knowledge_docs").fetchall()` — jede Suche lädt alle Dokumente in den RAM, danach Python-Scoring. | Suchlatenz skaliert mit Korpusgröße,negiert den Zweck des Hybrid-Indexes. | FTS5-/Vector-Index nutzen, `LIMIT` + `WHERE` Pushdown, nur Kandidaten laden. |
| 18 | `archon/routers/hr.py` | 178–212 | **Mittel** | Mehrfach-Dateilesen | `api_get_hermes_soul` liest bei **jedem** Request `SOUL.md` **und** `SOUL_FULL.md`, `SOUL_PRO.md`, `SOUL_COMPACT.md` (4 `open()` + `read()`), nur um den Modus zu erkennen. | 4-Fach-I/O pro Soul-View; bei 70 Profilen im UI entsprechendes Vielfaches. | Modus aus einer kleinen Metadaten-Datei/Header ableiten oder 3 Dateien nur bei Bedarf (`?include_variants=1`) lesen. |
| 19 | `static/index.html` | 2112–13783 | **Mittel** | Blockierendes Boot | ~50 `<script src="...">` ohne `defer` (nur 6 mit `defer`, z. B. 2157, 13713–13720); `static/hermes-webui/i18n.js` hat **26.390 LOC** und wird vollständig geparst. | Parse/Exec blockiert HTML-Parsing, verzögert First Contentful Paint; großer JS-Heap. | `defer` auf alle nicht-boot-kritischen Skripte; i18n-Kataloge in JSON auslagern und lazy pro Sprache laden (Muster `archon_i18n.js:69` vorhanden). |
| 20 | `static/js/mission_control_cockpit.js` | 39–58, 62–85 | **Mittel** | Polling + SSE doppelt | `fetchMissionControlData()` plant alle **15 s** einen Timer (57), parallel registriert `initMissionControlSSE` den `archon:sse`-Bus mit 350-ms-Debounce (70–85). Beide Pfade rufen `fetchMissionControlData` auf. | Redundante Requests, doppelte Renderzyklen, unnötige Backend-Last (jeder State-Request lädt Telemetrie + Profile via `to_thread`). | SSE als einzige Quelle; Polling nur als Fallback bei `EventSource`-Fehler mit längerem Intervall (30–60 s). |
| 21 | `static/hermes-webui/sessions.js` | 5766, 5938, 12887 | **Mittel** | Multiple Polling-Timer | Drei unabhängige `setInterval`-Poller (`_streamingPollTimer`, `_activeSessionExternalRefreshTimer`, `_cronPollTimer`) plus `panels.js:2791` (30 s Kanban-Fallback) und `panels.js:4379` (Log-Refresh). | Bei 10 offenen Tabs ~30+ Polling-Requests/Minute; `document.hidden`-Guards sind teilweise vorhanden (5767, 12888), aber nicht überall. | Auf einen zentralen Timer mit `document.hidden`-Gate und SSE-Invalidierung konsolidieren. |
| 22 | `backend/concurrency_throttle.py` | 157–174 | **Mittel** | Threadpool-Thrashing | Innerhalb der `while True`-Schleife werden pro Iteration `get_concurrency_config` und `_cached_backpressure` **erneut** via `asyncio.to_thread` gelesen (159–162). | Bei langen Warteschlangen viele Threadpool-Roundtrips pro Waiter; `to_thread` ist hierironisch eine Last statt Entlastung. | Config/Backpressure einmal vor die Schleife holen; im Loop nur bei expliziter Config-Änderung neu lesen. |
| 23 | `static/hermes-webui/panels.js` | 2787–2841 | **Niedrig** | Polling-Fallback | EventSource + `setInterval(refreshKanbanEvents, 30000)`-Fallback; nach 3 Fehlern wird SSE dauerhaft aufgegeben (2835–2839). | Akzeptabler Fallback, aber nach 3 transienten Fehlern keine Re-Eskalation zu SSE ("Give up for this session"). | Periodischer Re-Attempt (z. B. alle 5 min) mit Exponential Backoff. |
| 24 | `backend/otel_tracer.py` | 245–248 | **Niedrig** | Ressourcen-Leak | `_export_pool = ThreadPoolExecutor(max_workers=2, ...)` wird lazy erzeugt und nie `shutdown()` gerufen; keine Obergrenze für `submit()`. | Bei vielen Traces wartende Futures im Pool; Shutdown-Verzögerung. | `atexit`-Hook oder `close_dispatcher_clients()`-Analog registrieren. |
| 25 | `archon/core/profiles.py` | 289, 291–302, 376–392 | **Niedrig** | Cache-Invalidierung | 300-s-TTL-Cache; `_compute_profiles_mtime()` prüft **nur** das Oberverzeichnis und `agent_profiles.json` (296–299), nicht die `SOUL.md`/`profile.yaml` in Unterordnern. | SOUL-Änderungen werden bis zu 5 min nicht wirksam — Performance-Gewinn auf Kosten der Frische. | mtime rekursiv über die Profile-Dateien berechnen oder `invalidate()` bei `hr.py:260` (Sync dort bereits vorhanden) konsequent aufrufen. |
| 26 | `core_dispatcher.py` | 1765 ff., 1876–1891, 2034–2369 | **Mittel** | Token-Overhead Boardroom | `build_final_system_prompt()` hängt den gesamten Framework-String (u. a. 1765: ~1.200 Zeichen) an jeden Agenten-Prompt; Boardroom dispatcht Chairman + N Agenten + Aggregator + Synthese (2034–2369). | Bei N Agenten × Full-Framework × History exponentiell steigende Input-Tokens; `max_tokens` begrenzt nur Output (1200–4096), nicht Input. | Framework-Katalog in eine ID + Kurzbeschreibung komprimieren; nur dem Chairman den vollen Text geben. |

**Summe: 26 Befunde** — Kritikalität: Hoch 8, Mittel 14, Niedrig 4.

---

## 3. Domänen-Urteil

**Note 3 (von 5)** — *„Solide Basis mit punktuellen, aber echten Engpässen."*

**Begründung:**
- **Stark:** WAL/Synchronous-Tuning (~40 Dateien), Indizes (~60), `asyncio.to_thread` flächendeckend (>200), HTTP-Client-Pools in allen drei behaupteten Dateien tatsächlich vorhanden, `run_io_bound` mit exakt `max_workers=4`, punktuelle Task-Abfrage (`_load_single_task_from_conn`) real implementiert, zentraler `archon:sse`-Bus mit Queue-Größenlimit (256), vorkompiliertes Tailwind-CSS ohne Runtime-JIT.
- **Schwach:** Genau die heißen Pfade, die am häufigsten laufen (Dispatch: `collect_keys`, Chat-SSE: SQLite-Writes, MC-State-Cache-Race), sind **nicht** konsequent optimiert. Frontend rendert 832 Templates unvirtualisiert und pollt trotz SSE. DB-Lese-Endpunkte mit `SELECT * ...fetchall()` ohne LIMIT sind zahlreich. Token-Budget fehlt im zentralen Prompt-Aufbau.

Note 2 wäre zu hart (die Infrastruktur ist überdurchschnittlich gut gehärtet), Note 4 zu mild (diebefunde 1–8 sind produktionsrelevant).

---

## 4. Top-5-Risiken

1. **Dispatch-Pfad liest 70+ `.env`-Dateien synchron pro LLM-Call** (`api_provider.py:709-743`, `core_dispatcher.py:968-972`) — direkter Event-Loop-Blocker unter Parallelität, kein Cache.
2. **Chat-SSE schreibt SQLite synchron im Event-Loop** (`chat.py:1059-1069`) — jeder Streamabschluss blockiert alle anderen Requests.
3. **`_MC_STATE_CACHE` wird ungesynchronisiert aus async Handler und Threads beschrieben** (`mission_control.py:205-207` vs. `847/1037/1133`) — Race mit tenantenübergreifenden/gestalen State-Payloads.
4. **System-Prompt ohne Token-Budget** (`core_dispatcher.py:915-953`) — SOUL + Registry + Memory + Prefetch summieren sich unkontrolliert; 70 Profile × Full-SOUL ⇒ massiver Input-Overhead.
5. **`SELECT * ...fetchall()` ohne LIMIT in zentralen Lese-Endpunkten** (`kanban.py:153-157`, `audit_log.py:1000`, `hybrid_search_engine.py:136`, `execution_receipt_ledger.py:312`) — lineare Degradation mit wachsender DB.

---

## 5. Geprüfte Doc-Behauptungen

| Behauptung | Urteil | Nachweis |
|---|---|---|
| `asyncio.to_thread` für blockierende I/O | **⚠️** | >200 Treffer, flächendeckend; **aber** `chat.py:1060/1069` sync SQLite im async SSE-Generator (Befund 2), `api_provider.collect_keys()` sync im Dispatch (Befund 1). |
| `run_io_bound` mit `ThreadPoolExecutor(max_workers=4)` | **✅** | `archon/core/runtime.py:97-107` exakt `max_workers=4`, `archon/core/orchestration.py:335-336` nutzt es für Obsidian-Sync. |
| HTTP-Client-Pools in `core_dispatcher.py` / `hermes_proxy.py` / `system.py` | **✅** | `core_dispatcher.py:370-393` (WeakKeyDictionary pro Loop, `max_connections=100`), `hermes_proxy.py:43-60` (`max_connections=30`), `system.py:205-216` (`max_connections=20`). Alle drei real. |
| WAL/Cache-Tuning und Indizes | **✅** | ~40 Dateien mit `PRAGMA journal_mode=WAL` + `synchronous=NORMAL`, ~60 `CREATE INDEX IF NOT EXISTS`; `archon/core/cache.py:46-103` mit TTL + Single-Flight. |
| Punktuelle Task-Abfragen statt ganzem State („mc_get_task_sqlite lädt nur angeforderten Task") | **✅** | `archon/core/mission_control.py:673-766` (`_load_single_task_from_conn`: `WHERE t.id = ? ... LIMIT 1` + gezielte `task_links`-Abfrage), `769-781`, `851-887`. Voll-State-Loader existiert nur noch für `update_mission_control_data` (bewusst RMW). |
| Zentraler `archon:sse`-Bus statt doppelter Verbindungen | **⚠️** | `operations_org.py:522-564` leitet legacy `/comm-feed/stream` über den zentralen Bus, `chat_engine.js:121` eine Bussocket, Next.js `useArchonEvents.ts:27-32` eine. **Aber:** 11 `new EventSource(...)` insgesamt (`sessions.js:6085,6235`, `terminal.js:489`, `messages.js` ×6, `panels.js:2810`) und Polling-Fallbacks (`panels.js:2791`, `mission_control_cockpit.js:57`) — keine echten Dublette zum *Bus*, aber viele parallele Streams. |
| Vorkompiliertes Tailwind-CSS ohne Runtime-JIT-CDN | **✅** | `static/index.html:13` und `hermes-hud/index.html:7` laden `/static/css/tailwind.generated.css?v=20261115`; `tailwind.cdn.js` wird **nicht** im HTML eingebunden (nur offline vom Build-Skript `scripts/build_tailwind_css.mjs:16,145` genutzt). Tests `test_sanierungsplan_fixes.py:471` prüfen das. |
| Debounce/AbortController bei Suchen | **⚠️** | Vorhanden in `crm_studio.js:180,341-342`, `erp_studio.js:1434`, `css_live_studio.js:1612-1619`, `agent_profiles.js:561-562,2722`. **Nicht** durchgängig: `prompt_studio.js` filtert clientseitig ohne Debounce (832 Items), `templates.py:284-295` serverseitige Suche ohne Rate-Limit, `settings_search.js` ohne `AbortController` (nur `archon_i18n.js:69` fetch). |
| Lazy Iframes | **✅** | `static/index.html:1282,1392-1395,1452` nutzen `data-src` statt `src`; `operations_kanban.js:219-226` setzt `src` erst bei Bedarf. |
| Token-Overhead durch 3-Stufen-SOUL.md | **⚠️** | Die 3 Varianten existieren nachweislich (`hr.py:184-195`: `SOUL_FULL.md`, `SOUL_PRO.md`, `SOUL_COMPACT.md`; `profiles_service.py:358-372` synchronisiert sie). Aber: der Dispatch lädt den **aktiven** SOUL-Text ungeprüft und ohne Budget in den System-Prompt (`core_dispatcher.py:953`), und `hr.py:178-195` liest alle 3 Varianten pro Request. Der Overhead ist **nicht** durch die 3-Stufen-Struktur reduziert, sondern wird durch sie sogar noch zusätzlich gelesen. `max_tokens` ist gesetzt (Dispatcher 1200–4096), begrenzt aber nur den Output, nicht den Input. |

---

## Anhang — Positivbefunde (ausdrücklich geprüft und bestätigt)
- `archon/core/cache.py:60-97`: Single-Flight-Event verhindert Thundering Herd; Pruning nur abgelaufener Einträge (85–87).
- `backend/async_write_batcher.py:38-72`: `MappingProxyType` mit atomarer Referenzzuweisung für Double-Check-Locking — korrekt.
- `backend/role_budget_engine.py:1081-1182`: `reserve()` nutzt `_BUDGET_LOCK` + `BEGIN IMMEDIATE` und prüft Task-, Tages- und Monatslimit atomar; `settle()` (1184 ff.) separat.
- `archon/core/orchestration.py:1027-1073`: Fan-in-Prüfung + Flag in einem `update_mc`-Mutator unter `asyncio.Lock` — der frühere Snapshot-Overwrite ist behoben.
- `archon/core/task_registry.py:21-69`: `_TASKS` mit Done-Callback-Cleanup und `cancel_all()` mit 10-s-Timeout — kein Orphan-Task-Leak.
- `archon/core/runtime.py:87,110-120,169`: SSE-Queues auf 256 begrenzt, `QueueFull` verwirft statt zu blockieren.
- `static/index.html:1282,1392,1452`: Lazy-Iframes mit `data-src` (siehe Doc-Behauptung).
