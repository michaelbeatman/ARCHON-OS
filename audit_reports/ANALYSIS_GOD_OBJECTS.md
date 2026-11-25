# ANALYSE-DOSSIER — God-Objects, Importzyklen & Komplexitätsausreißer

**Erstellt:** 25.11.2026 · **Agent:** Hy4 (nicht Flash) · **Status:** Reine Analyse, **kein Code geändert**
**Ownership:** strikt No-Code. Einzige Schreibmenge dieses Auftrags ist diese Datei `audit_reports/ANALYSIS_GOD_OBJECTS.md`.
**Grundlage:** `audit_reports/HANDOFF_HY4_DEBUG_2026-11-25.md` (korrigierte Fassung), `audit_reports/PROPOSAL_3b_MODULARITY.md` (korrigierte Fassung, §Korrektur/Nachtrag), `audit_reports/domain_09.md`, `audit_reports/tool_scans/radon.txt`.

---

## 0. Rahmen, Snapshot, Methodik

### 0.1 Snapshot der Analysebasis

| Merkmal | Wert |
|---|---|
| Git HEAD | `bd9209be` (Backup-Commit) |
| Working Tree | **dirty**: ~180 `M` + ~40 `??` (praktisch das gesamte Typ-Härtungs-Ergebnis uncommittet) |
| Alle Analyseobjekte | `M` (modified) — `main.py`, `core_dispatcher.py`, `operations_api.py`, `workflow_dag_runner.py`, `delegation.py`, `orchestration.py`, `hermes_config.py`, Telegram-Patch |
| Final-Gate | **noch offen** (Full-Suite nach den 2 Orchestrator-Bugfixes, `ruff --select F821`, CVE-Entscheidung) |
| `.importlinter` | `??` untracked |
| Produktiv | Login ok, Container healthy, `/livez` `/readyz` `/health` 200 |

> **Wichtig:** Alle Zahlen dieses Dossiers beziehen sich auf den **aktuellen Working Tree**, nicht auf `bd9209be`. Sollte das Final-Gate noch Dateiänderungen erzeugen (z. B. Lockfile-Bumps bei der CVE-Entscheidung), müssen die Zeilenzahlen vor Split-Beginn erneut verifiziert werden. Die god-object-relevanten Dateien selbst sind von Lockfile-Änderungen nicht betroffen.

### 0.2 Schutzregeln (aus Handoff §2, für dieses Dossier übernommen)

1. **Nie** Tests gegen `./data` — immer `ARCHON_DATA_DIR='C:\Users\micha\AppData\Local\Temp\opencode\archon-<zweck>'` (siehe `INCIDENT_2026-11-25_LOGIN_OUTAGE.md`).
2. Nicht ändern: `.env`, `data/memory.db`, Audit-Kette, laufende Container. Kein stummes Re-Signieren.
3. NEVER_DO_LIST: kein Coroutine-Replay, keine PostgreSQL-Migration.
4. `pwsh.exe`-Spawn zeitweise blockiert (os error 5), gehäuft bei **parallelen Shell-Agenten**. → Dieses Dossier wurde **ohne Shell** erstellt (`read` / `grep` / `glob` / `write` only), damit es parallel zum Gate in der Shell laufen kann.
5. Kein Clean-Code-Zertifikat vor vollständig sauberem Stand.

### 0.3 Methodik / Abgrenzung

- Erhoben mit `read`, `grep`, `glob`. **Kein Testlauf, kein Scanner-Lauf, kein Build, kein `git`-Write, keine Code-Änderung.**
- **Zeilenzahlen — korrigiert nach unabhängiger Verifikation:** Die Erstfassung übernahm Werte aus der vorangegangenen Bestandsaufnahme, die per `-split` auf `\n` gezählt wurden. Diese Zählung liefert bei **trailing newline** ein leeres Element extra (Off-by-one). SSOT ist die `read`-Meldung / `(Get-Content).Count`. **6 von 9** Zahlen waren um −1 verschoben und sind jetzt korrigiert: `operations_api.py` **4.511**, `core_dispatcher.py` **3.803**, `workflow_dag_runner.py` **3.035**, `delegation.py` **2.346**, `hermes_config.py` **776**, Telegram-Patch **11.232**. Exakt waren `main.py` **3.638** und `orchestration.py` **1.941** (kein trailing newline). Siehe Anhang D.5 #15.
- `radon.txt` ist **UTF-16-LE mit BOM** (`FF FE`); die Zahlen in §1.2 stammen aus dem dekodierten Report (4.650 Blöcke, Ø B = 7.138).
- Symbol-Ebene = konkrete `from X import Y` / `mod.attr`-Referenzen über das gesamte Repo inkl. `tests/`, nicht nur Modul-Ebene.
- **Nicht ausgeführt:** alle Splits, alle Config-Korrekturen, alle Characterization-Tests. Dieses Dokument ist die Entscheidungsgrundlage dafür.

### 0.4 Auftrags-Entscheidungen (vom Nutzer 25.11. bestätigt)

| Frage | Entscheidung |
|---|---|
| Scope | **Alle drei Klassen A + B + C** |
| Analyse | **Jetzt, auf dem dirty Tree, rein lesend, kein Code anfassen** |
| Splits erst nach | 1. Final-Gate grün → 2. Commit des grünen Stands → 3. **Worktree** |
| Grundlage | `PROPOSAL_3b` erweitert (Klasse B, `core_dispatcher.py`, echte Zahlen, import-linter-Korrektur), nicht neu erfunden |
| Priorität | Risiko × Testabdeckung, **nicht** Größe → Telegram zuletzt |
| Nächster Schritt | Dieses Dossier |
| Commit-Reihenfolge | Dossier **mit** in den grünen Baseline-Commit (§6 #2), damit der Worktree die Analyse hat |
| S1–S4 Freigabe | „mach alles mit Subagenten / leg einfach los" = **explizite Freigabe** nach `PROPOSAL_3b` §4. Ausführung sequenziell im Worktree: 1 Commit + Full-Gate + Kurzreport pro Schritt |
| **Nachgelagerte Bereinigung (ergänzt 25.11.)** | Die vier Artefakte `.importlinter`, `audit_reports/tool_scans/`, `audit_reports/mypy_full_stdout.txt`, `scripts/run_*scans.ps1` werden **im Anschluss an die Zerlegung, vor dem abschließenden Scan** inhaltlich bereinigt. Für den **jetzigen** Baseline-Commit: bewusst **ausschließen**, nicht als grün deklarieren → §5 „Nachgelagerte Phase" |
| Abschluss-Scan | nach der Bereinigung; Clean-Code-Zertifikat bleibt bis zum vollständig sauberen Stand zurückgestellt (Handoff §2.5) |

---

## 1. Gesamtbefund: drei getrennte Klassen

| Klasse | Problem | Messgröße | In `PROPOSAL_3b` S1–S4 enthalten? |
|---|---|---|---|
| **A** | Große Dateien / Monolithen | Zeilenzahl | ja (S2–S4), aber **unvollständig** |
| **B** | Komplexitäts-Ausreißer (God-**Functions**) | radon CC Rang F | **nein — blinder Fleck** |
| **C** | Importverflechtung / Zyklen / Layergrenzen | reziproke Importzeilen | ja (S1), aber Config falsch |

### 1.1 Klasse A — Große Dateien (verifiziert, Working Tree)

| Datei | Docs (alt) | **Real** | Δ | Top-Level def/class | Routen | Imports |
|---|---:|---:|---:|---:|---:|---:|
| `scripts/patches/hermes_telegram_adapter.py` | 11.233 | **11.232** | 0 \* | 32 (265 gesamt) | – | 134 |
| `backend/operations_api.py` | ~3.923 | **4.511** | **+588** | 81 | 42 | 138 |
| `core_dispatcher.py` | *nicht gelistet* | **3.803** | **neu** | 47 | – | 104 |
| `main.py` | 3.393 | **3.638** | **+245** | 86 | 85 Dekoratoren / **75 `include_router`** | 280 |
| `backend/workflow_dag_runner.py` | 2.795 | **3.035** | +240 | 44 | – | 71 |
| `archon/core/delegation.py` | – | **2.346** | – | 52 | – | 75 |
| `archon/core/orchestration.py` | – | **1.941** | – | 25 | – | 53 |
| `archon/routers/hermes_config.py` | – | **776** | – | 7 | 4 | 24 |

> \* Die `11.233` in den Ausgangsdokumenten ist dieselbe Datei, nur per `-split`-Zählung auf Zeilenumbruch (off-by-one bei trailing newline). SSOT ist `read` / `(Get-Content).Count` → **11.232**. Kein realer Zeilenverlust; siehe §0.3 und Anhang D.5 #15.

**Korrekturen gegenüber den Ausgangsdokumenten:**
- `core_dispatcher.py` (3.803) ist **größer als `main.py`** und in keinem God-Object-Report geführt → muss in Klasse A aufgenommen werden.
- `main.py` ist **kein reiner Monolith mehr**: Zeile 3147 ff. (`AUSGELAGERTE ROUTER`) zeigt eine bereits erfolgte Modularisierung. Das verbleibende Problem ist ein überladener Kompositions-/Lifespan-Rumpf plus ~50 nach `main` zurückimportierte Symbole (siehe §2.3).
- `docker-compose.yml`: Mount steht in Zeile **405**, nicht 383 (Doku-Drift). Beide Hermes-Services (`:374`, `:437`) sind bereits **digest-gepinnt**: `nousresearch/hermes-agent:v0.23.1@sha256:276d4468…`. S4 „Image-Version im Manifest pinzen" ist damit **bereits erfüllt**; das eigentliche Loch ist die fehlende *Kopplung* (kein Smoke-Test bei `HERMES_IMAGE`-Bump).
- **`register(ctx)` existiert bereits** (`hermes_telegram_adapter.py:11212-11232`, `ctx.register_platform(...)` mit 17 Keywords). `PROPOSAL_3b` S4 fordert einen „schlanken `register(ctx)`-Entry" — der ist vorhanden, nur am Ende einer 11.232-Zeilen-Datei. S4 muss ihn **abtrennen**, nicht neu bauen.
- **Zwei widersprüchliche Hermes-Digests:** `docker-compose.yml:374/437` = `sha256:276d4468…` (mit Adapter-Mount `:405`), `docker-compose.hermes.yml:32/75` = `sha256:e6d81ae5…` (**ohne** Adapter-Mount). Kein Manifest/Lockfile koppelt Patch ↔ Image; einzige Kopplung ist prosaisch in `scripts/patches/telegram_adapter_gate_patch.md:16-18` („Nach jedem Hermes-Image-Update diesen Patch ERNEUT anwenden"). `config/version.json` (v0.5.7.8) enthält keine Hermes-Version, keinen Digest, keinen Patch-Hash.

### 1.2 Klasse B — Komplexität (radon)

4.650 Blöcke, Durchschnitt **B (7.138)** → Repo-Durchschnitt gesund. Aber **~60 Blöcke mit CC ≥ 50** und eine höhere Gesamtzahl im Rang **F (CC ≥ 41)**. Spitzen:

| CC | Symbol | Datei:Zeile |
|---:|---|---|
| **246** | `default_agent_node_executor` | `backend/workflow_dag_runner.py:1211` |
| 158 | `TelegramAdapter._handle_callback_query` | `scripts/patches/hermes_telegram_adapter.py:6873` |
| 147 | `GDPRComplianceEngine.erase_subject_data` | `backend/gdpr_compliance_engine.py:673` |
| 138 | `api_save_hermes_form_config` | **`archon/routers/`**`hermes_config.py:287` |
| 135 | `_watch_delegated_task` | `archon/core/delegation.py:1383` |
| 118 | `_execute_kanban_task_inner` / `get_projects_overview` | `backend/operations_api.py:1554` / `:3236` |
| 118 | `api_get_hermes_profiles` | `archon/core/profiles.py:376` |
| 116 | `_run_synthesis_cascade` | `archon/core/orchestration.py:1385` |
| 114 | `_execute_delegation` | `archon/core/delegation.py:1958` |
| 110 | `execute_workflow_node_plugin` | `backend/workflow_node_plugins.py:679` |
| 105 | `ChainedAuditLog.verify_integrity` | `backend/audit_log.py:902` |
| 99 / 98 | `ERPManager.save_document` / `parse_bank_statement` | `backend/erp_manager.py:1587` / `:2807` |
| 91 | `_execute_mission_control_task` | `archon/core/orchestration.py:286` |

Hinweis: Handoff §3 nennt `hermes_config.py` ohne Pfad; die Datei liegt in **`archon/routers/`**, nicht `archon/core/`.

**Vollständige F-Liste (CC ≥ 50)** siehe Anhang A.

### 1.3 Klasse C — Importverflechtung (nachgezählt)

| Richtung | Importzeilen | davon Top-Level | Charakter |
|---|---:|---:|---|
| `backend` → `archon` | **81** | **41** | überwiegend `archon.core.*`, aber 26 top-level `archon.routers.operations_*` |
| `archon` → `backend` | **634** | **27** | ~607 Lazy-Imports in Funktionsräumen |
| **Summe** | **715** | 68 | statt dokumentierter „~80 reziprok" |

Der in `domain_09.md` / `PROPOSAL_3b` beschriebene Zyklus ist **weiterhin aktiv**, nur mit anderen Symbolnamen:

```
backend/operations_api.py:190   def _get_kanban_connection(...)
        ▲  (lazy import, 11 Stellen)
archon/core/delegation.py:1070,1102,1281,1292,1347,1553,1840,1885,2147  → _get_kanban_connection
archon/core/delegation.py:1053  → _load_kanban_meta
archon/core/delegation.py:2236  → _execute_kanban_task_async
        ▼  (top-level, 26 Zeilen)
backend/operations_api.py:28-30 → archon.core.provider_registry, archon.routers._rbac
backend/operations_api.py       → archon.routers.operations_{org,dag,prompts,receipts,
                                   sysops,dunning,finetuning,approvals,keys,emails,
                                   security,bot_screen,autonomy,pbd} (je 2×)
```

Alle 15 `archon/routers/operations_*.py` definieren einen echten `APIRouter()` → es ist eine **echte Layer-Inversion** (Service importiert Router), kein Namensartefakt.

**`.importlinter`-Korrektur (bestätigt):**

```
[importlinter]
root_package = archon
include_external_packages = False       ← macht source_modules = backend unauflösbar
[importlinter:contract:backend-no-router-imports]
source_modules = backend
forbidden_modules = archon.routers
ignore_imports =
    backend.operations_api -> archon.routers._rbac
    backend.operations_api -> archon.core.provider_registry
```

- `exit 1 / "No matches for ignored import"` = **Config-Fehler**, nicht „keine Verletzung". Die Handoff-Aussage „Importe offenbar bereits aufgelöst" war falsch (bereits korrigiert).
- `ignore_imports` deckt `_rbac` und `provider_registry` ab, **nicht** aber die 26 `operations_*`-Importe → eine korrekt gerootete Config würde ~26 Verstöße melden.
- **Präzisierung zum Gate (verifiziert):** `grep` über `.github/workflows/*.yml` → **0 Treffer**. Der Contract ist in **keiner CI und in keinem pytest-Test** verdrahtet. Er läuft **nur** in der lokalen PowerShell-Static-Toolchain (`scripts/run_static_toolchain.ps1:25`, `scripts/run_remaining_scans.ps1:15`, je `.venv\Scripts\lint-imports.exe`). Handoff §4 („kein Gate → Theater") gilt damit für **CI**, ist aber unvollständig: die lokalen Skripte rufen den Linter sehr wohl auf — und liefern wegen der falschen Config genau das dokumentierte `exit 1 / No matches for ignored import`. S1 muss daher **zwei** Dinge tun: Config korrigieren **und** ein hartes CI-Gate neu anlegen; zusätzlich fehlt jeder pytest-Test auf Layergrenzen/Importzyklen (Anhang D.3).

---

## 2. Abhängigkeitsgraph auf Symbol-Ebene

### 2.1 `_get_kanban_connection` — der eigentliche Zyklus-Knoten

Definition: `backend/operations_api.py:190`. **28 Aufrufe innerhalb** `operations_api.py` selbst (`:687 … :4098`), plus externe Konsumenten:

| Konsument | Art | Zeilen |
|---|---|---|
| `archon/core/delegation.py` | lazy `from backend.operations_api import ...` | 1070, 1102, 1281, 1292, 1347, 1553, 1840, 1885, 2147 (+ 1053 `_load_kanban_meta`, 2236 `_execute_kanban_task_async`) |
| `archon/routers/operations_org.py` | **via `_get_ops_deps()`** — 6-Tupel, positional | 43, 223, 310, 352, 474, 582, 675, 712, 986 |
| `archon/routers/operations_bot_screen.py` | lokaler Wrapper `:36` → lazy Re-Import `:37` | 65, 105, 174 |
| `archon/routers/mission_control.py` | lazy | 117–118 |
| `archon/routers/mesh.py` | lazy | 381–382 |
| `archon/routers/kanban.py` | `TaskStatusUpdateRequest`, `update_task_status` | 285 |
| `core_dispatcher.py` | lazy | 3222–3223 |
| `backend/workflow_dag_runner.py` | lazy | 965–967 |
| `backend/workflow_scheduler.py` | lazy | 1635–1636 |
| `backend/workflow_templates.py` | lazy | 1000–1003 |
| `main.py` | `router as operations_router` | 2752 |
| Tests | `monkeypatch.setattr(ops, "_get_kanban_connection", ...)` | `test_fix_w2_c_governance_roles.py:135`, `test_orange_b_r20.py:58`, `test_orange_b_r16.py:26,71,96,135,157`, `test_fix_batch4.py:164` |

**Fazit:** `_get_kanban_connection` ist ein **de-facto öffentliches, privat benanntes Singleton** mit ~45 Referenzstellen über 4 Schichten. Es ist der erste Kandidat für `backend/contracts.py` — aber der Name ist `_`-präfixiert und wird von Tests per `monkeypatch.setattr` auf dem Modul gepatcht. Ein Verschieben in ein Contracts-Modul **ändert den Patch-Punkt** und bricht `test_orange_b_r16.py` / `test_fix_w2_c_governance_roles.py`. → Vor S1 muss entschieden werden: Re-Export im alten Modul belassen (Adapter) oder Tests migrieren.

**`_get_ops_deps()` (`operations_org.py:73-82`)** ist ein **positional 6-Tupel**:
`(_load_profiles_map, _get_fallback_avatar, _get_kanban_connection, PROFILES_FILE, WORKSPACE_DIR, _PROFILES_MAP_CACHE)`.
Jede Änderung der Reihenfolge oder des Tupels wirkt still auf 10 Aufrufstellen. Das ist der fragilste Contract im gesamten `operations_*`-Cluster und muss vor S3 eingefroren oder durch ein benanntes Objekt ersetzt werden.

### 2.2 `DelegationPayload` — Doku veraltet, SSOT bereits konsolidiert

- `archon/core/delegation.py:33` `class HandoffDelegationPayload(BaseModel)` = **einzige SSOT**.
- `:114` `DelegationPayload = HandoffDelegationPayload`, `:115` `KanbanDelegationPayload = HandoffDelegationPayload` → **nur noch Aliase**.
- `backend/operations_api.py:67-70` importiert **lazy** `HandoffDelegationPayload` + `canonicalize_delegation_payload` (nicht das alte `DelegationPayload` aus `PROPOSAL_3b:24`).
- `tests/test_reaudit_stage7.py:24` prüft `DelegationPayload is HandoffDelegationPayload`; `:68` prüft per Source-Text `"from archon.core.delegation import DelegationPayload" not in src`.
- `tests/test_fix_w3_a_orchestration.py:147-149` prüft Alias-Identität.

**Fazit:** Der dokumentierte Zyklus `operations_api.py:99 lazy DelegationPayload` **existiert so nicht mehr**. Der Zyklus läuft heute über `_get_kanban_connection` (§2.1). S1 muss die Contracts-Diskussion auf `_get_kanban_connection` / `_get_ops_deps` umstellen, nicht auf `DelegationPayload`.

### 2.3 `main.py` — verdeckter Rückwärts-Zyklus (NEU, in keinem Audit dokumentiert)

`main.py` lädt 75 Router per `include_router` (`:3147-3454`). **Gleichzeitig** importieren ≥27 Produktionsmodule `main` **zurück** — fast ausschließlich lazy in Funktionsräumen, an ≥90 Stellen:

`agent_chat`, `autonomy_settings`, `container_ops`, `core_settings`, `decisions`(13×), `docker_services`, `documents`, `hermes_ops`, `hr`, `hermes_proxy`, `memory_ops`, `mesh`, `operations_sysops`, `oracle_seo`, `prompts`, `proxies`, `quickchat`, `research`, `telemetry`, `telegram`, `ui`, `updater`, `watchdog`, `mission_sync` (`import main as app_main`), `mcp_gateway` (`from main import _request_has_service_token`), `autonomous_standup` (`from main import get_hud_telemetry`).

Genutzte Symbole (`app_main.*`) — **~50 Namen, die stabile Contracts sind**:

| Gruppe | Symbole |
|---|---|
| Persistenz/Helpers | `load_agents`, `save_agents`, `load_roles`, `save_roles`, `load_services`, `save_services`, `load_memory`, `save_memory`, `load_profiles_list`, `_load_json`, `_save_json`, `_get_state_db`, `_save_message_to_db`, `add_ticker`, `ticker_entries`, `create_rolling_backup` |
| Pfade/Konstanten | `WORKSPACE_DIR`, `MEMORY_DIR`, `OBSIDIAN_VAULT`, `OBSIDIAN_VAULT_DIR`, `PERSONALAKTEN_DIR`, `PROJEKTE_DIR`, `SETTINGS_FILE`, `STATE_DB_PATH`, `GATEWAY_CONFIG_FILE`, `QUICKCHAT_SESSIONS_DIR`, `DEFAULT_ROLES`, `soul_path`, `profile_dir`, `agent_log_path`, `__file__` |
| Gateway/Hermes | `forward_to_hermes`, `_get_shared_proxy_client`, `_run_docker_exec`, `_get_all_installed_profiles`, `_load_gateway_config`, `_save_gateway_config`, `_update_profile_status` |
| Auth/Decisions | `get_current_user_from_request`, `_get_service_token`, `_decision_self_api`, `_request_has_service_token`, `auth_service`, `app` |
| Export/Dispatch | `core_dispatcher`, `api_get_hermes_profiles`, `api_telegram_relay`, `get_hud_telemetry`, `detect_container_port` |
| Quickchat | `_quickchat_state_session_id`, `_ensure_state_session` |

**Fazit:** S2 („`main.py` → < 300 Zeilen reine App-Komposition") ist **nicht** ein einfaches Auslagern. Jeder dieser ~50 Namen müsste entweder in `archon/core/runtime.py` (existiert bereits, wird von `contracts.py:27-31` genutzt) oder in ein neues `archon/services/app_state.py` wandern — **und alle ≥90 Rückwärts-Importe mitgezogen werden**. Ohne diesen Schritt erzeugt S2 genau die Import-Order-Probleme, die S1 verhindern soll. Das ist der Grund, warum S1 vor S2 stehen muss.

**Zusatzbefund (verifiziert):** Der einzige import-bezogene Struktur-Test `tests/test_audit_b2_rbac_tenant.py:24-39` prüft `assert "import main" not in segment` **nur innerhalb von `ast.FunctionDef`-Knoten, deren Name in `RBAC_FUNCS` liegt** (`:29-37`, `assert found >= 15`). Er ist eine RBAC-Zentralisierungsregel für die Wrapper — **kein** Import-Layer-Test. Die ≥90 Rückwärts-Importe aus §2.3 liegen in anderen Funktionen und werden von ihm **nicht erfasst**. Es gibt also **keinen Test**, der einen `main.py`-Split gegen diese Rückwärts-Abhängigkeiten absichert.

### 2.4 `core_dispatcher.py` — impliziter Hub mit mutable globals

≥30 Produktionsmodule + ≥30 Testdateien importieren `core_dispatcher`. Genutzte Symbole:

| Kategorie | Symbole |
|---|---|
| Dispatch (stabil) | `dispatch_to_omniroute_or_container`, `dispatch_to_external_agent`, `_gate_container_dispatch`, `_dispatch_to_omniroute_or_container_impl`, `_build_dispatch_context_sync`, `_reserve_trajectory_budget_sync`, `execute_with_self_correction` |
| Weitere Einstiege | `trigger_n8n_execution`, `run_boardroom_debate`, `stream_boardroom_debate`, `detect_target_action`, `close_dispatcher_clients`, `_record_failed_cancel`, `AUTO_MODEL_MAP` |
| **Mutable Modul-Globals (werden von Routern geschrieben!)** | `CATEGORIZED_FRAMEWORKS`, `CATEGORIZED_FRAMEWORKS_EN`, `DEFAULT_CATEGORIZED_FRAMEWORKS`, `MAX_CONCURRENT_AGENT_TASKS` (`operations_org.py:818`), `_DISPATCHER_HTTP_CLIENTS`, `httpx` |
| Tests patchen | `core_dispatcher.dispatch_to_omniroute_or_container`, `cd.httpx.AsyncClient`, `cd.run_boardroom_debate`, `cd._gate_container_dispatch` |

**Fazit:** `core_dispatcher.py` ist nicht nur groß, sondern ein **globaler veränderbarer Zustandsträger**. Ein Split nach Dateigröße wäre hier besonders gefährlich, weil `CATEGORIZED_FRAMEWORKS` / `MAX_CONCURRENT_AGENT_TASKS` / `_DISPATCHER_HTTP_CLIENTS` zur Laufzeit von Routern und Tests überschrieben werden. **Empfehlung: `core_dispatcher.py` nicht nach Größe splitten, sondern zuerst die Globals in einen State-Store überführen** — als eigenes Backlog-Item, nicht in den 5 priorisierten Schritten.

### 2.5 `backend/workflow_dag_runner.py` — öffentliche Oberfläche

Importiert von 10 Produktionsmodulen + 10 Testdateien:

`run_workflow_dag`, `get_workflow_run`, `list_workflow_runs`, `resume_workflow_run`, `resume_suspended_workflow_run`, `schedule_workflow_resume`, `request_dag_replan`, `validate_dag_def`, `default_agent_node_executor`, `_execute_research_dag_node`, `_update_kanban_task_status`, `_connect`.

→ Der Name `default_agent_node_executor` ist **trotz fehlendem `_`** ein intern genutztes, aber von `test_stage1_stage3_hardening_and_bus.py` (5 Stellen: 350, 364, 385, 390, 407, 433, 741, 754) direkt importiertes Symbol. Es ist der **Default-Executor** (`:2083`: `eff_executor = executor_fn or default_agent_node_executor`) → bei einer Zerlegung muss genau dieser Name als Einstieg erhalten bleiben (Facade-Muster).

### 2.6 `archon/core/delegation.py` — öffentliche Oberfläche

`HandoffDelegationPayload`, `canonicalize_delegation_payload`, `DelegationReceipt`, `resume_pending_delegation_watchers`, `_apex_ids`, `canonical_agent_id`, `active_soul_tier_text`, `_check_delegation_permission`, Aliase `DelegationPayload` / `KanbanDelegationPayload`; Konsumenten: `chat.py`, `operations_api.py`, `workflow_scheduler.py`, `main.py:1749,2085,2096`, `workflow_scheduler.py:1650`.

### 2.7 Telegram-Patch — externer Graph (kein Repo-Import)

Der Patch hat **keinen einzigen Repo-Import** und keine `hermes.*`-/relativen Imports. Er hängt den Hermes-Root per `sys.path.insert(0, …parents[3])` (`:316`) ein und importiert ausschließlich Image-interne Module:

| Namespace | Symbole (Auszug) | Im Repo? |
|---|---|---|
| `gateway.platforms.base` | `BasePlatformAdapter`, `MessageEvent`, `MessageType`, `ProcessingOutcome`, `SendResult`, `classify_send_error`, `utf16_len`, `cache_*` | ❌ |
| `plugins.platforms.telegram.telegram_ids` / `.telegram_network` | `normalize_telegram_chat_id`, `TelegramFallbackTransport`, `discover_fallback_ips` | ❌ **Satelliten nur im Image** |
| `gateway.config`, `gateway.session`, `gateway.run`, `hermes_cli.*`, `agent.*`, `tools.*` | `Platform`, `PlatformConfig`, `build_session_key`, `cfg_get`, `atomic_config_write`, `redact_sensitive_text`, `ensure` | ❌ |

**Konsequenz für S4:** Ein Split nach `scripts/patches/telegram/*.py` erzeugt Module, die **nur im Container importierbar** sind. Lokale Tests bleiben unmöglich, solange die `gateway.*`-Satelliten nicht gemockt werden. Das ist der eigentliche Grund für „zuletzt" — nicht die Zeilenzahl.

`register(ctx)` (`:11212-11232`) übergibt an `ctx.register_platform` 17 Keywords; die Callables sind die stabilen Contracts: `_build_adapter`, `telegram_deps_present`, `check_telegram_requirements`, `_is_connected`, `interactive_setup`, `_apply_yaml_config`, `_standalone_send`, `_resolve_notifications_mode`. Der Container-Importname `plugins.platforms.telegram.adapter` (**Dateiname `adapter.py`**) ist die harte äußere Schnittstelle → nach Split als Re-Export erhalten. Vollständige API-Liste siehe Anhang C.

---

## 3. Dossiers pro Objekt

> **Legende Risikoklasse:** 🟢 niedrig / 🟡 mittel / 🟠 mittel-hoch / 🔴 hoch / ⚫ Sonderfall (nicht importierbar).
> **Alle Split-Vorschläge sind Pläne, keine ausgeführten Änderungen.** Je Schritt: 1 Commit + Full-Gate.

### D0 — S1: Import-Contract-Config & Layer-Regel 🟢

| Feld | Wert |
|---|---|
| Objekt | `.importlinter` (untracked), `.github/workflows/ci.yml` (kein import-linter-Schritt), 41 top-level `backend`→`archon`-Zeilen |
| Befund | Config falsch gerootet; Contract nicht in CI; `ignore_imports` unvollständig (26 `operations_*`-Importe fehlen) |
| Symbol-Graph | §1.3, §2.1, §2.2. Realer Zyklus läuft über `_get_kanban_connection`, **nicht** über `DelegationPayload` |
| Stabile Contracts | `HandoffDelegationPayload` (+ Aliase), `_get_kanban_connection`, `_get_ops_deps()`-Tupel, `_load_kanban_meta`, `_execute_kanban_task_async`, `_get_active_kanban_db_path`, `TaskStatusUpdateRequest`, `QualityReviewRequest`, `update_task_status` |
| Tests | **Kein echtes Import-Layer-Gate.** `grep` in `tests/` nach `importlinter` / `lint-imports` / `forbidden_modules` / `root_package` → **0 Treffer**; `archon.routers` erscheint 297× nur als Import-Ziel in RBAC-/API-Tests. Einziger import-bezogener Struktur-Test: `test_audit_b2_rbac_tenant.py:25-39` (scoped auf RBAC-Wrapper, siehe §2.3). Source-Text-Assertions ohne Layer-Bezug: `test_reaudit_stage7.py:68`, `test_fix_w3_b_performance.py:386-388`, `test_audit_p1_governance.py:16`. Der Linter läuft nur in `run_static_toolchain.ps1:25` / `run_remaining_scans.ps1:15` |
| Fehlende Characterization-Tests | 1) Negativtest: künstlicher `backend → archon.routers`-Import muss `lint-imports` rot machen. 2) Positivtest: sauberer Stand → exit 0. 3) Import-Order-Test: `import backend.operations_api` und `import archon.core.delegation` in **beider** Reihenfolge. 4) pytest-Test, der `.importlinter` einliest und die Contracts asserted. 5) AST-Check `backend/**` auf `archon.routers` unter Berücksichtigung der `ignore_imports`-Ausnahmen. 6) Zyklus-Erkennung (nicht nur gerichtete Regel). **Ohne 4–6 kann ein `main.py`-Split `backend → archon.routers` brechen, ohne dass irgendein Test rot wird** |
| Risiko | 🟢 — reine Config + CI-Job, kein Laufzeitpfad. **Aber:** S1 macht ~26 bestehende Verstöße erst sichtbar → danach ist der Stand „rot", solange sie nicht aufgelöst sind. Das muss vor dem grünen Commit eingeplant werden |
| Split-Plan | (a) `root_package` auf Repo-Root / `include_external_packages` korrigieren; (b) `ignore_imports` um die 26 `operations_*`-Importe erweitern **oder** als bewusste, dokumentierte Ausnahmen mit Tilgungsplan führen; (c) `lint-imports` als hartes CI-Gate ohne `continue-on-error`; (d) Contracts-Modul **nur als Re-Export** anlegen, damit `monkeypatch.setattr(ops, "_get_kanban_connection", …)` weiter greift |
| Akzeptanz | `lint-imports` exit 0/1 reproduzierbar; `mypy`/`compileall`/Full-Suite grün; kein `from archon.routers` in `backend/**` ohne dokumentierte Ausnahme |

### D1 — `default_agent_node_executor` (CC 246) 🟠

| Feld | Wert |
|---|---|
| Objekt | `backend/workflow_dag_runner.py:1211`, CC **246** (Rang F), eingebettet in 3.035-Zeilen-Datei |
| Verantwortungs-Cluster (aus Code) | ① Agentenprofil-Auflösung (`api_get_hermes_profiles`, `resolve_agent_id`) → ② `research`-Node → ③ Workflow-Node-Plugins (`is_workflow_node_plugin`, `execute_workflow_node_plugin`) → ④ `media_render`/`clip_matrix` (`generate_video_clip_matrix`) → ⑤ Prompt-Assembly + Upstream-Outputs → ⑥ Tool-Call-Loop (`allowed_tools`, `max_turns ≤ 6`, Trajectory-Hop-Cap, `execute_agent_tool`, Flightlog-Spiegelung) → ⑦ `core_dispatcher.dispatch_to_omniroute_or_container` → ⑧ Kanban-Status-Sync (`_update_kanban_task_status`) → ⑨ Budget/Trace/Span → ⑩ Silent-Failure-Erkennung + Result-Normalisierung |
| Symbol-Graph | `import core_dispatcher` (`:1206`, `:1214`), `backend.agent_aliases.resolve_agent_id` (`:1215`), `archon.core.profiles.api_get_hermes_profiles` (`:1224`), `backend.workflow_node_plugins` (`:1238`), `backend.content_machine.generate_video_clip_matrix` (`:1279`), `backend.trajectory_budget.reserve_hop` (`:1463`), `backend.tool_runtime.execute_agent_tool` (`:1476`), `backend.flightlog_backtester.mirror_flight_event_to_trace` (`:1490`). Default-Setzung `:2083` |
| Öffentliche Oberfläche | `default_agent_node_executor(node, upstream) -> Dict` — **muss als Facade erhalten bleiben**; `run_workflow_dag`, `validate_dag_def`, `_execute_research_dag_node`, `_connect` bleiben unangetastet |
| Tests | **Korrigiert — priorisierungsrelevant:** 15 Testdateien referenzieren `workflow_dag_runner`, aber den **Executor selbst** charakterisieren nur **4 direkte Verhaltenstests**, alle in `test_stage1_stage3_hardening_and_bus.py`: `test_dag_runner_multi_turn_tool_loop_and_output_schema` (`:349-381`, `agent` + Tool-Loop), `test_dag_runner_media_render_node` (`:384-402`), `test_workflow_node_plugins_vst_discovery_and_execution` (`:405-449`, `ffmpeg`), `test_dag_runner_schema_preserved_and_event_driven_recovery` (`:740-779`, `agent` + `quality_gate`). **`test_workflow_dag_e2e.py` umgeht den Executor vollständig**: alle 8 E2E-Tests übergeben `executor_fn=mock_exec` / `failing_exec` / `slow_exec` / `clean_exec` / `slop_exec` (`:85-408`) → sie charakterisieren die **Engine**, nicht den Executor. Recovery/DB: `test_fix_w3_d_trajectory_dag.py` (11 V-Tests), `test_p2_checkpoint_resume.py` |
| Fehlende Characterization-Tests | **Größte Lücke im gesamten Mapping.** Abgedeckt sind nur `agent` (2×), `media_render`, `ffmpeg`. Ungetestet: `research`-Branch (`:1234`), `clip_matrix` (`:1270`), Plugin-Fehlerpfad, Dispatcher-Exception/Timeout, erschöpfter Schema-Repair, `max_turns`-Erschöpfung, `_blocked_node_result`/`TRAJECTORY_TOKEN_CAP` (`:1205`), `resolve_agent_id`-Auflösung (`:1215/:1218`), Profil-Ladefehler (`:1222-1224`), Kanban-Sync-Fehler, `allowed_tools`-Negativfall, Hop-Cap, `dry_run`, `upstream`-Varianten. **Abgrenzung:** die `ntype`-Kaskade `gate` / `quality_gate` / `map` / `dynamic_fanout` / `fanout` (`:2262-2413`) liegt in `run_workflow_dag_impl`, **nicht** im Executor → eigene Golden-Tests, nicht Teil von D1. Benötigt: Verzweigungsmatrix mit Golden-Output (`status`, `block_kind`, `kanban_task_id`, `tool_trace`, `error`) je Executor-Branch |
| Risiko | 🟠 — kein Lifespan/RBAC, aber **DAG-Hotpath** mit Budget-, Lease-, Kanban- und Trace-Seiteneffekten **und nur 4 direkte Verhaltenstests**. Domain 02/07/08 dokumentieren hier ohnehin offene MED-Befunde (unbekannte `agent_id`, Run-Cap, sync SQLite-Schreibblöcke, CancelledError-Persistenz). Ein Split **ohne** Characterization-Tests würde diese Befunde verschleiern |
| Split-Plan | **Reine Extraktion, keine Logikänderung:** `default_agent_node_executor` wird zur dünnen Facade; Cluster ②–⑥ wandern in `backend/workflow_nodes/{research,plugins,media,prompt,tools}.py`; ⑧–⑩ in `backend/workflow_nodes/finalize.py`. Reihenfolge: erst Characterization-Tests (grün), dann **ein Cluster pro Commit**, je Commit Full-Gate |
| Akzeptanz | Alle 15 Testdateien grün; Golden-Outputs byte-identisch; CC der Facade < 20; kein `import`-Zyklus neu; `default_agent_node_executor` weiter importierbar |

### D2 — `main.py` 🔴

| Feld | Wert |
|---|---|
| Objekt | 3.638 Zeilen, 86 Top-Level-Funktionen, 280 Imports, 75 `include_router`, 85 Routen-Dekoratoren |
| Inhalt | App-Komposition (`:353`), Lifespan (`:294-343`), Startup/Shutdown-Hooks (`:138-139`, `:2995`, `:3136-3144`), 5 Fail-Fast-Hooks (`:152-158`, `:3457`, `:3489`, `:3632-3638`), `_ROUTER_LOAD_ERRORS` (`:130`), RBAC-Injektion (`:3155-3159`), ~1.200 Zeilen REST-Endpunkte (`:1283` ff.), Persistenz-Helfer (`:1192` ff.), Kontext-Meter (`:1878` ff.) |
| Symbol-Graph | **Rückwärts-Zyklus §2.3**: ≥27 Router-Module importieren `main` zurück (≥90 Stellen, ~50 Symbole). `core_dispatcher` top-level (`:46`). `operations_api.router` (`:2752`). `archon.core.delegation` (`:1749, 2085, 2096`). 75 Router-Registrierungen mit **Reihenfolge = Pfad-Präzedenz** (`:3149-3150`) |
| Stabile Contracts (S2 **muss** erhalten) | ① Registrierungsreihenfolge der 75 Router; ② je Router `try/except` + `_ROUTER_LOAD_ERRORS.append(...)` (`:3160-3209`); ③ `_rbac_configure(require_admin=require_admin)` **vor** den Routern (`:3156-3157`); ④ `_assert_router_health()` fail-closed inkl. `ARCHON_ALLOW_BROKEN_ROUTERS`-Opt-Out (`:3457-3486`); ⑤ `_FAIL_FAST_HOOKS`-Menge (`:152-158`) und `raise` statt Log im Lifespan (`:318-324`); ⑥ `insert(0, …)`-Reihenfolge der 5 Hooks; ⑦ `_SHUTDOWN_HOOKS` in `reversed()` (`:328`); ⑧ `app`, `auth_service`, `core_dispatcher`, `get_hud_telemetry`, `detect_container_port`, `_request_has_service_token`; ⑨ die ~50 `app_main.*`-Symbole aus §2.3 |
| Tests | **Tragende Verhaltenstests:** `test_loop_liveness.py` (4 Tests: `/livez` 200/503, echte Event-Loop-Blockade, Monitor-Staleness, Healthcheck-Schwellwerte `:12/:46/:81/:107`), `test_fix_w1_a_audit.py:281-298` (`test_integrity_fail_fast_hook_raises_and_marks_flag` — **nur isoliert**, s. Lücken), `test_rbac_admin_routes.py:134-210` + `test_rbac_admin_routes_paket2.py:246-364` (7+9 RBAC-Tests inkl. `test_shared_router_guard_is_wired_in_app`), `test_audit_fixes_batch.py` (7 `TestClient(app_main.app)`-Blöcke). **S-Tests (wertlos für Split):** `test_rag_key_env.py:104/:145/:157` (patched `main._STARTUP_HOOKS` / `_check_rag_api_key_config`), `test_fix_batch13.py:22/:33/:133` (`hasattr`), `test_fix_batch5.py:102`, `test_a5_*.py`, `test_reaudit_stage13.py:40-51`, `test_audit_p0_ui_livez.py:11-17`. **Faktische Contracts (monkeypatch):** `app_main.auth_service.{is_auth_enabled,verify_session,get_fallback_admin}`, `require_admin_or_503`, `get_current_user_from_request`, `_get_service_token`, `forward_to_hermes`, `_verify_all_audit_chains`, `WORKSPACE_DIR`, `AGENTS_FILE`, `ROLES_FILE`, `_load_json`/`_save_json`, `load_roles`, `load_services`, `add_ticker`, `_run_docker_exec`, `_STARTUP_HOOKS`, `backend.loop_liveness.check_loop_liveness` (`test_loop_liveness.py:73`) |
| Fehlende Characterization-Tests | **Bestätigte Lücken:** ① `/livez` ↔ `_FAIL_FAST_HOOKS` / `_AUDIT_COMPROMISED` nicht **verdrahtet** getestet (`test_fix_w1_a_audit.py:281` prüft nur den Hook isoliert + `assert "_assert_audit_integrity" in _FAIL_FAST_HOOKS`). ② Lifespan-Shutdown-Timeout / `_SHUTDOWN_HOOKS`-`reversed()`-Reihenfolge / Graceful-Drain → `_close_all_http_clients()` → Task-Cancel: `tests/conftest.py:34-58` ist nur eine Isolation-Fixture, `test_graceful_shutdown.py` testet nur den Singleton (`test_database_wal_flush` ist laut `fix_w4_d2_residuals.md:100` **rot**). ③ n8n-Startup-Opt-in-Hook / `_N8N_STARTUP_STATUS` → `/readyz`-Degradation. ④ Router-Registrierungsreihenfolge + `_rbac.configure()` nur per Source-Assertion (`test_rbac_admin_routes_paket2.py:364-371`). ⑤ `HealingAttemptPayload` / `request.state.hitl_apply_patch` nur indirekt. Ohne ①–③ ist S2 ein Blindflug |
| Risiko | 🔴 **höchstes Risiko aller Objekte** — berührt genau die W0–W5-gehärteten Pfade: Lifespan-Fail-Fast, `/livez`/`/readyz`, RBAC-Rollenzaun, Audit-HMAC, Auth-Bind. Ein „Router-404 bei healthy /health" oder fail-open ist das dokumentierte Schadensbild |
| Split-Plan | `PROPOSAL_3b` S2, aber **erweitert um §2.3**: Schritt 2a zuerst die ~50 `app_main.*`-Symbole nach `archon/core/runtime.py` / `archon/services/app_state.py` heben und alle ≥90 Rückwärts-Importe umstellen (1 Commit, Full-Gate). Schritt 2b Lifespan → `archon/services/lifecycle.py`. 2c Middleware/Auth → `archon/middleware/`. 2d Router-Registrierung → `archon/routers/__init__.py`. **Ziel < 300 Zeilen erst am Ende**, nicht als erstes Kriterium |
| Akzeptanz | `/livez` `/readyz` `/health` unverändert; Fail-Fast-Hooks raise; Shutdown-Timeout; Router-Reihenfolge; Full-Suite 0 rot; Negativprobe mit absichtlich defektem Router → Start bricht ab |

### D3 — `backend/operations_api.py` 🟠

| Feld | Wert |
|---|---|
| Objekt | **4.511 Zeilen** (größter Python-Monolith), 81 Top-Level-Funktionen, 42 Routen, 138 Imports |
| Inhalt | Kanban-DB-Zugriff (`_get_kanban_connection`, `_resolve_kanban_db_path`), Task-Ausführung (`_execute_kanban_task_inner` CC 118), Review-Gate (`QualityReviewVerdict`, `_load_kanban_delegation_payload`), Projekte-Overview (`get_projects_overview` CC 118), Obsidian-Mapping (`_resolve_task_obsidian_rel` CC 65), 26 top-level `archon.routers.operations_*`-Importe, modulglobale States (`_KANBAN_UNDO_STORE`, `_PROFILES_MAP_CACHE` — vgl. `domain_09.md` M8) |
| Symbol-Graph | §2.1 + §2.2. **Bidirektional**: top-level `archon.core.provider_registry` / `archon.routers._rbac` / 13 `operations_*`-Router; lazy `archon.core.delegation.HandoffDelegationPayload`. Wird selbst von `delegation.py`, `core_dispatcher.py`, `workflow_*`, `main.py`, 6 Routern und 6 Testdateien importiert |
| Stabile Contracts | `_get_kanban_connection` (~45 Referenzstellen), `_load_kanban_meta`, `_execute_kanban_task_async`, `_get_active_kanban_db_path`, `_resolve_task_obsidian_rel`, `_build_kanban_obsidian_map`, `_PROFILES_MAP_CACHE`, `PROFILES_FILE`, `WORKSPACE_DIR`, `_load_profiles_map`, `_get_fallback_avatar`, `router`, `KANBAN_DB_PATH`, `VALID_KANBAN_STATUSES`, `TaskStatusUpdateRequest`, `QualityReviewRequest`, `QualityReviewVerdict`, `update_task_status`, `_get_ops_deps()`-Tupel |
| Tests | **V:** `test_fix_batch7.py` (5 Tests: Reopen/Failed-Todo/Bot-Screen-Abort/Container-Fehler/Post-Kanban-DB-Sync `:28/:80/:123/:142/:160`), `test_d11_handoff_hardening.py:74-147` (`test_d11_kanban_delegation_payload_survives_worker_start`), `test_fix_w2_c_governance_roles.py:26-27/:47/:73/:114`, `test_orange_b_r16.py` (5× `mock.patch.object(ops, "_get_kanban_connection")`), `test_orange_b_m12.py:20/:39`, `test_orange_b_r20.py`, `test_fix_batch4.py:164`, `test_fix_batch14.py:45`, `test_audit_fixes_batch.py:950`. **S (markiert):** `test_fix_batch15.py:58-63`, `test_orange_b_d18.py:20`, `test_fix_w3_b_performance.py:195/:204/:384/:388/:393/:401/:421`, `test_workflow_dag_e2e.py:247-258` (`ast.parse` + `assert "to_thread" in body_src`), `test_orange_b_f14.py:56-83`, `test_reaudit_stage7.py:63`, `test_reaudit_stage8.py:41`, `test_reaudit_stage12.py:12`. **Faktische Contracts:** `ops_mod._resolve_kanban_db_path`, `_get_active_kanban_db_path`, `_KANBAN_JOURNAL_INIT`, `KANBAN_DB_PATH`, `backend.operations_api.require_admin_or_503`, `_build_kanban_obsidian_map`, `_resolve_task_obsidian_rel`, `_load_kanban_delegation_payload`, `QualityReviewRequest`, `TaskStatusUpdateRequest` |
| Fehlende Characterization-Tests | Golden-Tests für `_execute_kanban_task_inner` (Status-Matrix), `get_projects_overview` (Aggregation), `_resolve_task_obsidian_rel` (Pfadjail), Undo-Store-TTL, `_get_ops_deps()`-Tupel-Reihenfolge. **Zusätzlich:** `operations_api.py:923-936` (Allokationsfehler nur auf `stderr`, soll laut `fix_w3_d_trajectory_dag.md:117-120` Task auf `blocked`/`budget_allocation_failed` setzen) hat **keinen Verhaltenstest** — `test_fix_w3_b_performance.py:415` ist ein S-Test. **Warnung:** die S-Tests brechen bei **jedem** Split, auch bei identischem Verhalten → vor S3 durch G7 auf Verhaltensassertions umstellen |
| Risiko | 🟠 — Kanban/Delegation/HITL/GoBD-nah, aber kein Lifespan. Risiko liegt in der **stillschweigenden Änderung des `monkeypatch`-Patch-Punkts** und im positionalen `_get_ops_deps()`-Tupel |
| Split-Plan | `PROPOSAL_3b` S3 (entlang der 15 bereits existierenden `operations_*`-Router, „nur hohles Modul, keine Logikänderung"). **Korrektur:** Das ist *kein* hohles Modul — 26 Top-Level-Importe + ~45 `_get_kanban_connection`-Referenzen + 2 CC-118-Blöcke sind echte Logik. Reihenfolge: erst Contracts-Modul als Re-Export (D0), dann `_get_ops_deps()` auflösen, dann **ein Router-Cluster pro Commit** |
| Akzeptanz | Alle 21 Testdateien grün; `monkeypatch.setattr(ops, "_get_kanban_connection", …)` greift weiter; kein `from archon.routers` mehr in `backend/**`; Full-Suite 0 rot |

### D4 — `scripts/patches/hermes_telegram_adapter.py` ⚫

| Feld | Wert |
|---|---|
| Objekt | 11.232 Zeilen, **2 Klassen**, **30 Modulebene-Funktionen**, **`TelegramAdapter` mit 204 Methoden** (73 async / 131 sync), 134 Imports, 19 Modulebenen-Konstanten |
| Basis / Einbindung | `TelegramAdapter(gateway.platforms.base.BasePlatformAdapter)` (`:817`, `super().__init__(config, Platform.TELEGRAM)` `:904`). `docker-compose.yml:405` mountet die **Einzeldatei** auf `/opt/hermes/plugins/platforms/telegram/adapter.py:ro`. Image bereits digest-gepinnt (`:374`, `:437`) |
| **Entry-Point** | **`register(ctx)` existiert bereits** (`:11212-11232`) → `ctx.register_platform(...)` mit **17 Keywords**. Kein `__main__`, kein `main()`, kein `setup()`; `interactive_setup()` (`:11071`) ist ein registrierter Hook, kein CLI-Einstieg |
| Symbol-Graph | **Kein Repo-Import.** Hermes-Root per `sys.path.insert(0, …parents[3])` (`:316`); `gateway.*`, `hermes_cli.*`, `agent.*`, `tools.*`, `plugins.platforms.telegram.{telegram_ids,telegram_network}`. Satelliten liegen **nicht im Repo**, nur im Image → §2.7 / Anhang C |
| Stabile Contracts | ① Container-Importname `plugins.platforms.telegram.adapter` / Dateiname `adapter.py`; ② `TelegramAdapter` (es gibt **keine** Klasse `Adapter`); ③ die 8 an `register_platform` übergebenen Callables; ④ `register(ctx)` selbst; ⑤ `gate_decision_answer` + `GATE_OK_TEXT`/`GATE_REJECT_TEXT` (vom AST-Test direkt geladen); ⑥ `TELEGRAM_AVAILABLE` (Laufzeit-Umschaltung `:288/290/453/512`), `_ARCHON_TRACE_STATE`/`_ARCHON_TRACE_BY_REF`, `logger`; ⑦ `_mirror_to_archon_inbox` (`:2-31`, hardcoded `/opt/data/inbox/telegram/`); ⑧ die überschriebenen `BasePlatformAdapter`-Methoden + PTB-Handler (Anhang C.3) |
| Komplexität | **8 Methoden Rang F**: `_handle_callback_query` **CC 158 / 765 Zeilen**, `_handle_media_message` 73 / 300 Z., `_apply_yaml_config` 72 / 126 Z., `send` 72 / 327 Z., `_handle_model_picker_callback` 53 / 335 Z., `connect` **47 / 536 Zeilen**, `_handle_command` 45 / 154 Z., `_build_message_event` 44 / 170 Z. Die **Klasse selbst ist nur B (10)** → das Problem sind einzelne Methoden, nicht die Klassenstruktur |
| Tests | **2 Testdateien, beide ohne Modulimport.** `test_telegram_gate_meldung.py` (10 Tests) parst die Datei per `ast`, extrahiert nur Top-Level-`FunctionDef`/`Assign` und `exec`-kompiliert `gate_decision_answer` + 2 Konstanten (`:26-48`); Begründung `:8-11`: `gateway.*` fehlt im Repo. `test_reaudit_stage6.py:35-40` reiner Textcheck. `ci.yml:166-167` `compileall` prüft **nur Syntax**. 0 Treffer in `tests/` für `TelegramAdapter` / `BasePlatformAdapter` / `register_platform` / `_build_adapter` |
| Fehlende Characterization-Tests | Smoke-Test gegen die gepinnte Hermes-Version: `register(ctx)` mit Mock-`ctx` (17 Keywords prüfen), `BasePlatformAdapter`-Vertrag, PTB-Handler-Registrierung, `_apply_yaml_config`-Kette, Callback-Präfix-Dispatcher. **Muss `gateway.*` mocken**, sonst lokal nicht lauffähig; bei `HERMES_IMAGE`-Bump erzwingen |
| Versionskopplung | **Keine maschinelle Kopplung.** `config/version.json` ohne Hermes-Version/Digest/Patch-Hash; `requirements*.txt` 0 Treffer; `scripts/patches/` nur 3 Dateien, kein Manifest. Einzige Kopplung: `telegram_adapter_gate_patch.md:16-18` (manuell „nach jedem Image-Update erneut anwenden"). **`docker-compose.hermes.yml:32/75` nutzt einen anderen Digest (`sha256:e6d81ae5…`) und keinen Adapter-Mount** → Inkonsistenz |
| Risiko | ⚫ **Sonderfall / zuletzt.** Nicht lokal importierbar, nur Syntax geprüft, Fork-Overhead gegen Upstream, Produktiv-Mount. `PROPOSAL_3b` S4 „schlanker `register(ctx)`-Entry" ist **bereits erfüllt** — der echte Aufwand ist Abtrennen + Smoke-Gate |
| Split-Plan | S4, korrigiert: (a) `adapter.py` bleibt als **dünner Re-Export** mit `register(ctx)`, allen 8 Callables **und** `gate_decision_answer`/Konstanten (wegen AST-Test); (b) Logik nach `scripts/patches/telegram/*.py`, **mit `gateway.*`-Mock-Gerüst**; (c) Digest-Kopplungs-Gate statt neuem Pin; (d) `docker-compose.hermes.yml` angleichen oder bewusst als abweichend dokumentieren |
| Akzeptanz | `register(ctx)` gegen Mock-`ctx` grün; `test_telegram_gate_meldung.py` grün; Smoke gegen `v0.23.1@sha256:276d4468…`; Mount-Pfad `:405` unverändert; Produktiv-Telegram unverändert |

### D5 — `core_dispatcher.py` (Backlog, nicht in den 5 Schritten) 🔴

| Feld | Wert |
|---|---|
| Objekt | **3.803 Zeilen** — größer als `main.py`, in keinem God-Object-Report geführt |
| Besonderheit | Globaler Hub (§2.4): ≥30 Produktions- + ≥30 Test-Imports; **mutable Modul-Globals werden von Routern zur Laufzeit überschrieben** (`CATEGORIZED_FRAMEWORKS`, `MAX_CONCURRENT_AGENT_TASKS`, `_DISPATCHER_HTTP_CLIENTS`) |
| Tests | Zahlreiche `inspect.getsource(...)`-Assertions (`test_fix_w3_b_performance.py:51,52,125,128-131`, `test_fix_w2_a_security.py:55`) — **reine Source-Text-Tests**, die bei jedem Split brechen. **Zusätzlich rot:** `test_show_hn_blockers.py:55` (`test_core_dispatcher_omniroute_alias_and_ollama_fallback`) ist laut `fix_w4_d2_residuals.md:71-74` `status="blocked"` und **nicht im Ownership** → zählt nicht als Characterization, darf nach dem Ownership-Modell aber auch **nicht gelöscht/skipt** werden (Eskalation an G7). Der Dispatch-Chokepoint `reserve_hop`/`reserve_tokens` ist nur als S-Test (`test_med2_a_dispatch.py:228`) vorhanden |
| Empfehlung | **Nicht nach Zeilenzahl splitten.** Erst die Globals in einen expliziten State-Store überführen + Source-Text-Tests auf Verhalten umstellen. Als eigenes Backlog-Item nach den 5 priorisierten Schritten führen |

### D6 — Übrige Klasse-B-Ausreißer (kompakt)

| Symbol | CC | Datei | Testdateien (Referenz) | Anmerkung |
|---|---:|---|---:|---|
| `_watch_delegated_task` / `_execute_delegation` | 135 / 114 | `archon/core/delegation.py` | 26 | Teil von D3-Zyklus; nach S1 gemeinsam mit D3 betrachten |
| `_run_synthesis_cascade` / `_execute_mission_control_task` | 116 / 91 | `archon/core/orchestration.py` | 16 | **Bestabgedecktes Objekt**: `test_orchestration.py` (8 Klassen / ~40 isolierte Unit-Tests, laut Docstring kein FS/Netz/Telegram/Docker/`core_dispatcher`). Aber `_run_synthesis_cascade` nur per `inspect.getsource` (`test_audit_b1_b8_blockers.py:177-179`) → CC-116-Block in `PROPOSAL_3b` nicht geplant |
| `api_save_hermes_form_config` | 138 | `archon/routers/hermes_config.py` | 3 | **dünnste Testabdeckung** aller B-Ausreißer → Characterization-Tests zuerst |
| `erase_subject_data` | 147 | `backend/gdpr_compliance_engine.py` | – | DSGVO-Löschpfad, kein Split ohne Golden-Test |
| `verify_integrity` | 105 | `backend/audit_log.py` | – | **Audit-Kette — Schutzregel §2.2: nicht ändern** |
| `execute_workflow_node_plugin` | 110 | `backend/workflow_node_plugins.py` | – | direkter Nachbar von D1 |

---

## 4. Ownership-Matrix

Vorbild ist das in den `fix_*`-Dokumenten durchgehend verwendete Modell: *„Ownership: ausschließlich die im Auftrag genannten Dateien"*, *„Datei gehört A5"*, *„nicht in diesem Auftrag / außerhalb meines Ownership"* (`fix_d1_main.md`, `fix_w3_a_orchestration.md`, `fix_a4_orchestration.md:62-63`, `fix_w1_d_tenant_ledger.md:161-162`). Übertragen auf dieses Projekt:

| Rolle | Ownership (Schreibmenge) | Darf **nicht** anfassen | Gate-Verantwortung |
|---|---|---|---|
| **G0 — Dossier-Owner** (Hy4, dieser Lauf) | **nur** `audit_reports/ANALYSIS_GOD_OBJECTS.md` | jeglicher Code, Config, Tests, git index | keine (rein lesend) |
| **G1 — Gate-Owner** (parallel, Shell) | `.ci_venv`-Läufe, Temp-`ARCHON_DATA_DIR`, git index, evtl. Lockfiles | God-Object-Dateien, `./data`, `.env`, Audit-Kette, Container | Final-Gate grün + Commit |
| **G2 — Contract-Owner** (S1 / D0) | `.importlinter`, `.github/workflows/ci.yml`, neues Contracts-Modul (**nur Re-Export**), Layer-Tests | `operations_api.py`-Logik, `delegation.py` | `lint-imports` + Full-Suite |
| **G3 — DAG-Owner** (D1) | `backend/workflow_dag_runner.py`, `backend/workflow_nodes/**`, DAG-Tests | `main.py`, `core_dispatcher.py`, `operations_api.py` | Characterization + E2E pro Cluster |
| **G4 — App-Owner** (S2 / D2) | `main.py`, `archon/services/lifecycle.py`, `archon/middleware/**`, `archon/routers/__init__.py`, `archon/core/runtime.py` | `backend/**`, DAG, Telegram-Patch | Lifespan-/Health-/RBAC-Tests |
| **G5 — Operations-Owner** (S3 / D3) | `backend/operations_api.py`, `archon/routers/operations_*`, `_get_ops_deps()` | `main.py`, `core_dispatcher.py` | Kanban-/Delegation-/HITL-Tests |
| **G6 — Adapter-Owner** (S4 / D4) | `scripts/patches/hermes_telegram_adapter.py`, `scripts/patches/telegram/**`, Compose-Mount, Smoke-Test | alle `archon/**`, `backend/**` | Hermes-Adapter-Smoke |
| **G7 — Test-Owner** (NEU, eigene Rolle) | **ausschließlich** `tests/**` (Umstellung S→V, neue Characterization-Tests, Eskalationsvermerke) | alle Produktivdateien, Config, Compose | grüne Characterization-Tests **vor** jedem Split-Commit |

**Modell im Original (verifiziert in `fix_w3_d_trajectory_dag.md`, `fix_w4_d2_residuals.md`, `fix_d1_main.md`):** Jeder Report deklariert einen Agenten/Fix-ID mit **exklusiver Positivliste** (`Owner-Dateien (ausschliesslich geaendert)` `:4-7`, `Geänderte Dateien (exklusives Ownership)` `:13-31`, `Scope: ausschliesslich die 10 freigegebenen Dateien` `:3-5`) **und** einer expliziten **Negativliste** (`Nicht angefasst` `:8-10`, `Nicht geändert (bewusst)` `:33-35`). Zugehörigkeit wird über `datei.py:ZEILE` (`alt`/`jetzt`, `~Z.`, `ff.`) vermerkt; „Datei gehört X nicht" mit `gehoert nicht zu W3-D — nicht geaendert` (`:110`) / `nicht besessen` / `Datei nicht im Ownership → nicht geändert; an Test-Owner eskalieren` (`fix_w4_d2_residuals.md:71-74`). Findings fließen als **Delegation (Quelle `A<n>-Nr.<x>`)** vom Audit- zum Delegations-Agenten; nicht Bearbeitetes erhält Status **DELEGATED** mit Grund + Empfehlung (`fix_d1_main.md:29-33`). **Der Test-Owner ist eine eigene Rolle**: rote/obsolete Tests werden **eskaliert, nicht gelöscht/skipt/umgeschrieben** (`fix_w3_d_trajectory_dag.md:121-127`). Kompatibilität wird per `datei.py::testname bleibt kompatibel` festgehalten (`fix_d1_main.md:15`). Verifikation wird als Kette `Mechanik | Produzent | Konsument | Effekt | Verifikation` mit Testfunktionsnamen geführt (`fix_w4_d2_residuals.md:41-48`).

**Regeln (aus dem `fix_*`-Modell übernommen):**
1. **Ein Owner pro Datei.** Keine Datei in zwei Rollen. Bei Kollision (z. B. `delegation.py` zwischen G2 und G5) entscheidet G2 vor, G5 nach — nie gleichzeitig.
2. **Ein Schritt = ein Commit = ein Full-Gate.** Kein Schritt ohne grünes Gate (PROPOSAL_3b §2/§3, Handoff §5.5).
3. **Außerhalb Ownership = dokumentieren, nicht ändern.** Befunde an Nachbarrollen werden als Delegation vermerkt, nicht still gefixt.
4. **Kein paralleles Schreiben auf demselben Worktree.** Gate (G1) auf dem Hauptbaum, Splits (G2–G6) im **Worktree** wie vom Handoff vorgesehen.
5. Schutzregeln §0.2 gelten für **alle** Rollen.
6. **Test-Owner ist eine eigene Rolle (G7).** Rote oder obsolete Tests werden **eskaliert**, nicht gelöscht/skipt/umgeschrieben. Vor jedem Split-Commit müssen die in Anhang D.2 gelisteten S-Tests von G7 auf Verhaltensassertions umgestellt sein — der Split-Owner darf sie nicht selbst anfassen.

---

## 5. Priorisierung (vom Nutzer festgelegt, hier mit Gate-Kopplung)

| # | Schritt | Objekt | Dossier | Risiko | Testabdeckung | Begründung (Risiko × Testabdeckung) | Gate danach |
|---|---|---|---|---|---|---|---|
| **1** | **S1** korrigierte Import-Contract-Config | `.importlinter`, CI, Contracts | D0 | 🟢 | 0 echte Layer-Tests | billig, niedriges Risiko, **macht Verstöße erst sichtbar**; Voraussetzung für alles Weitere | `lint-imports` + Full-Suite |
| **2** | **B** CC-246 zerlegen | `workflow_dag_runner.py:1211` | D1 | 🟠 | **4 direkte V-Tests** (nicht 15) | **Begründung korrigiert:** der Executor ist *nicht* „von echten Tests umgeben" — `test_workflow_dag_e2e.py` ersetzt ihn durchgehend durch `mock_exec`. Genau deshalb ist die Entscheidung „**Characterization-Tests zuerst**" hier **noch zwingender** als angenommen. **Reihenfolge bleibt** (Risiko × Testabdeckung) | Verzweigungsmatrix + 4 bestehende V-Tests + Engine-E2E |
| **3** | `main.py` | App-Komposition | D2 | 🔴 | 124 (aber dünn bei Lifespan) | erst **nach** Contract (§2.3 Rückwärts-Imports!), mit Worktree + Gate pro Schritt | `/livez`/`/readyz`, Fail-Fast, Shutdown, Full-Suite |
| **4** | `operations_api.py` | 4.511-Zeilen-Monolith | D3 | 🟠 | 21 | mittel-hoch; Patch-Punkt `_get_kanban_connection` und `_get_ops_deps()`-Tupel einfrieren | 21 Testdateien + Layer-Check |
| **5** | Telegram-Patch | 11.232 Zeilen | D4 | ⚫ | **2** (nur AST-/Textchecks) | **zuletzt** — Fork-Overhead, `gateway.*`-Satelliten nur im Image → lokal nicht importierbar, `register(ctx)` bereits vorhanden, nur Compileall-Syntax-Gate | Hermes-Adapter-Smoke + Re-Export-Check |

**Backlog (nicht in den 5 Schritten):** D5 `core_dispatcher.py` (Globals + Source-Text-Tests), D6 übrige B-Ausreißer, `domain_09.md` M8 (globale mutable Singletons), `domain_02/07/08` MED-Befunde im DAG-Hotpath.

**Abhängigkeiten, die die Reihenfolge erzwingen:**
- Schritt 1 **vor** 3: `main.py`-Rückwärts-Imports (§2.3) sind eine Layer-Verletzung, die S1 erst sichtbar macht und die Contracts-Schicht bereitstellt.
- Schritt 1 **vor** 4: `_get_kanban_connection` ist der Zyklus-Knoten; ohne Re-Export-Contract bricht S3 die `monkeypatch`-Tests.
- Schritt 2 **vor** 4: D1 berührt `_get_kanban_connection` (`:965`) — wenn D3 zuerst zieht, verschiebt sich der Patch-Punkt unter dem DAG-Owner weg.
- Schritt 5 **zuletzt**: keine Repo-interne Abhängigkeit, aber Produktiv-Mount und fehlende Testbarkeit.

### Nachgelagerte Phase (vom Nutzer 25.11. ergänzt: „im Anschluss, vor dem abschließenden Scan")

| Artefakt | Status | Maßnahme im Anschluss | Warum **erst dann** |
|---|---|---|---|
| `.importlinter` | `??`, fehlkonfiguriert | korrigierte Config + `ignore_imports`-Ausnahmen + CI-Gate | wird in **S1** korrigiert — vorher bereinigen würde S1 vorwegnehmen und im Worktree kollidieren |
| `scripts/run_*scans.ps1` | `??` | `lint-imports`-Aufruf gegen die **korrigierte** Config verdrahten | rufen heute den kaputten Linter auf (Anhang D.3) → erst nach S1 sinnvoll |
| `audit_reports/tool_scans/` | `??` | „NOT EXECUTED"-Logs fehlgeschlagener Läufe entfernen, durch **saubere** Läufe ersetzen | Handoff §3: nicht als echte Ergebnisse zählen; der Abschluss-Scan erzeugt sie neu — jetzt löschen wäre vergebens |
| `audit_reports/mypy_full_stdout.txt` | `??` | Roh-Log durch das Gate-Ergebnis ersetzen | dto., kein Gate-Ergebnis |

**Reihenfolge gesamt:** Gate grün → lokaler Baseline-Commit (**ohne** diese 4 Artefakte, **mit** Dossier) → Worktree → S1 → B → S2 → S3 → S4 → **Artefakt-Bereinigung** → **Abschluss-Scan** → (optional) Zertifikat.

**Abschluss-Scan (Arbeitsdefinition):** Final-Gate komplett nach Handoff §5.5 (`pytest tests/ -q` mit `ARCHON_DATA_DIR=<temp>`, `compileall`, `tsc --noEmit`, `npm run build`, `docker compose config --quiet`, `audit_secrets.py --all`) **plus** Static-Toolchain mit **korrigiertem** `lint-imports`, `mypy --config-file mypy.ini`, `ruff`, `bandit -q -lll`, `pip-audit`, `radon`. Erst wenn das vollständig grün ist, kommt das Zertifikat wieder auf die Tagesordnung.

---

## 6. Offene Punkte / Entscheidungen vor Split 1

| # | Punkt | Warum es vor dem ersten Commit geklärt sein muss |
|---|---|---|
| 1 | **Final-Gate abschließen** | Full-Suite nach den 2 Bugfixes, `ruff check . --select F821` (zweiter F821 verifizieren), CVE-Entscheidung. Erst dann grüner Commit → Worktree |
| 2 | **Commit-Reihenfolge mit diesem Dossier** | Das Dossier entsteht parallel zum Gate. Bewusst entscheiden: mit in den grünen Commit, als Doc-Only-Commit danach, oder erst in den Worktree. Sonst landet es halb im Commit |
| 3 | **S1 macht ~26 Verstöße sichtbar** | Ein korrektes `lint-imports` ist **rot**, solange die 26 `operations_*`-Importe nicht aufgelöst oder dokumentiert ausgenommen sind. Das kollidiert mit „grüner Commit vor Worktree" → entweder Ausnahmen mit Tilgungsplan oder S1 **nach** dem Commit im Worktree |
| 4 | **`monkeypatch`-Patch-Punkt** | Re-Export in `backend/contracts.py` muss `_get_kanban_connection` **auf `backend.operations_api`** weiter erreichbar halten, sonst brechen `test_orange_b_r16.py`, `test_orange_b_r20.py`, `test_fix_w2_c_governance_roles.py` |
| 5 | **Source-Text-Tests umstellen (G7)** | `test_fix_w3_b_performance.py`, `test_reaudit_stage7.py`, `test_audit_p1_governance.py`, `test_fix_w2_a_security.py` u. v. a. prüfen `inspect.getsource` / Dateiinhalt / AST-Segmente. Sie brechen bei jedem Split bei identischem Verhalten → vor Schritt 2/4 auf Verhaltensassertions migrieren. **Vollständige Kurzliste Anhang D.2.** Ausnahme: `test_unbound_calls.py` behalten (erkennt ungebundene Namen nach Router-Extraktion) |
| 6 | **`_get_ops_deps()`-Tupel** | Positionales 6-Tupel an 10 Stellen. Einfrieren oder durch benanntes Objekt ersetzen — Entscheidung vor S3 |
| 7 | **`core_dispatcher.py` Globals** | `CATEGORIZED_FRAMEWORKS`, `MAX_CONCURRENT_AGENT_TASKS`, `_DISPATCHER_HTTP_CLIENTS` werden zur Laufzeit geschrieben. Kein Größen-Split ohne State-Store (D5) |
| 8 | **Hermes-Kopplung statt Pin (korrigiert)** | Digest ist bereits gesetzt, `register(ctx)` (`:11212`) existiert bereits. Nötig ist ein **Kopplungs-Gate**, das bei `HERMES_IMAGE`-Bump den Adapter-Smoke erzwingt — plus Angleichen von `docker-compose.hermes.yml` (anderer Digest `e6d81ae5…`, kein Mount) |
| 9 | **Charakterisierungs-Reihenfolge** | Für D1 (10 Cluster) und D2 (Lifespan-Invarianten) müssen die Golden-Tests **vor** dem ersten Split-Commit grün sein |
| 10 | **Schutzregel Audit-Kette** | `audit_log.py:902 verify_integrity` (CC 105) und die Audit-Kette dürfen nach §0.2 nicht angefasst werden → aus D6 ausschließen |
| 11 | **AST-Test als Split-Bremse (NEU)** | `test_telegram_gate_meldung.py:26-48` lädt `gate_decision_answer` + `GATE_OK_TEXT`/`GATE_REJECT_TEXT` per `ast` **ausschließlich aus Top-Level-Knoten der Originaldatei**. Wandern sie in ein Untermodul, bricht der Test — auch bei identischem Verhalten. → Re-Export in `adapter.py` zwingend (analog zu Punkt #5) |
| 12 | **`gateway.*`-Satelliten nur im Image (NEU)** | `telegram_ids` / `telegram_network` und alle `gateway.*`-Module liegen nicht im Repo. Ausgelagerte `telegram/*.py` sind **lokal nicht importierbar** → Smoke-Test braucht ein `gateway.*`-Mock-Gerüst oder läuft im Container |
| 13 | **`PROPOSAL_3b` S4 umformulieren (NEU)** | S4 fordert einen „schlanken `register(ctx)`-Entry" — der existiert schon (`:11212-11232`, 17 Keywords). Korrekte Maßnahme: **Abtrennen** als dünnen Re-Export, nicht Neu-Erfinden |
| 14 | **Priorisierungsgrundlage Schritt 2 korrigiert (NEU)** | „von echten Tests umgeben (15 Testdateien)" trifft auf **die Datei**, nicht auf **den Executor** zu: 4 direkte V-Tests, E2E nutzt `mock_exec`. Reihenfolge bleibt, aber Characterization ist hier **Vorbedingung**, nicht Absicherung (Anhang D.5) |
| 15 | **Rote Tests zählen nicht als Characterization (NEU)** | `test_show_hn_blockers.py:55` (`fix_w4_d2_residuals.md:71-74`), `test_jev_router.py::test_connection_probe_fail_open` (`:75-77`), `test_graceful_shutdown.py::test_database_wal_flush` (`:100`). Nach Ownership-Modell an **G7 eskalieren**, nicht löschen/skippen — sonst wird der „grüne Stand" vortäuscht |
| 16 | **`main.py`-Rückwärts-Imports sind ungetestet (NEU)** | `test_audit_b2_rbac_tenant.py:37` verbietet `import main` nur **innerhalb der RBAC-Wrapper-Funktionen**. Die ≥90 Rückwärts-Importe (§2.3) fallen nicht darunter → kein Test sichert S2 ab |
| 17 | **Zwei Hermes-Digests (NEU)** | `docker-compose.yml` `276d4468…` mit Mount vs. `docker-compose.hermes.yml` `e6d81ae5…` ohne Mount. Vor S4 entscheiden, welches SSOT ist — sonst testet der Smoke gegen das falsche Image |

---

## Anhang A — radon F-Blöcke (CC ≥ 50), Auszug

```
246  backend/workflow_dag_runner.py:1211        default_agent_node_executor
158  scripts/patches/hermes_telegram_adapter.py:6873  TelegramAdapter._handle_callback_query
147  backend/gdpr_compliance_engine.py:673      erase_subject_data
138  archon/routers/hermes_config.py:287        api_save_hermes_form_config
135  archon/core/delegation.py:1383             _watch_delegated_task
118  backend/operations_api.py:1554             _execute_kanban_task_inner
118  backend/operations_api.py:3236             get_projects_overview
118  archon/core/profiles.py:376                api_get_hermes_profiles
116  archon/core/orchestration.py:1385          _run_synthesis_cascade
114  archon/core/delegation.py:1958             _execute_delegation
110  backend/workflow_node_plugins.py:679       execute_workflow_node_plugin
105  backend/audit_log.py:902                   ChainedAuditLog.verify_integrity
 99  backend/erp_manager.py:1587               ERPManager.save_document
 98  backend/erp_manager.py:2807               ERPManager.parse_bank_statement
 95  archon/services/profiles_service.py:207   save_profile
 95  backend/onboarding_wizard.py:1375         get_onboarding_status
 91  archon/core/orchestration.py:286          _execute_mission_control_task
 91  backend/corporate_manager.py:554          CorporateManager.render_template
 82  backend/workflow_dag_runner.py:2070       _run_workflow_dag_locked
 79  backend/gdpr_compliance_engine.py:426     export_subject_data
 78  backend/onboarding_wizard.py:1375         get_onboarding_status
 77  backend/erp_manager.py:2108               _prepare_einvoice_context
 73  scripts/patches/hermes_telegram_adapter.py:10139  _handle_media_message
 73  backend/workflow_templates.py:792         save_workflow_template
 72  backend/agent_router.py:1461              _stream_chat_completion_unreserved
 72  backend/contract_manager.py:197           ContractParser.parse
 72  scripts/patches/hermes_telegram_adapter.py:11083  _apply_yaml_config
 72  scripts/patches/hermes_telegram_adapter.py:4981   TelegramAdapter.send
 70  backend/llm_kernel.py:231                 dispatch_llm
 69  backend/workflow_scheduler.py:1174        _dispatch_workflow_event_impl
 65  backend/agent_router.py:1160              _chat_completion_unreserved
 65  backend/operations_api.py:2996            _resolve_task_obsidian_rel
 64  backend/squad_pack_manager.py:112         export_pack
 63  archon/routers/container_ops.py:48        send_prompt_to_agent
 62  scripts/check_router_names.py:93          scan_file
 62  scripts/translate_manual.py:282           main
 60  backend/workflow_node_plugins.py:375      _run_ffmpeg_plugin
 59  backend/agent_router.py:686               _build_request_payload
 59  backend/corporate_manager.py:421          validate_ustg_compliance
 59  backend/workflow_dag_runner.py:541        validate_dag_def
 58  archon/routers/brain.py:144               api_brain_galaxy_data
 58  archon/routers/guardian.py:861            api_get_plugin_config
 58  archon/routers/telemetry.py:513           api_get_agent_projects
 58  backend/operations_calendar.py:422        sync_source
 57  archon/routers/guardian.py:1033           api_save_plugin_config
 57  backend/db_consolidation.py:507           run_consolidation
 56  archon/routers/chat.py:742                api_chat_stream
 56  archon/routers/templates.py:360           render_template_prompt
 56  backend/email_service.py:63               sync_imap_inbox
 56  backend/treasury_engine.py:433            request_payment
 56  scripts/skill_resolver.py:140             resolve_and_prepare_skill_context
 55  archon/routers/telemetry.py:150           _collect_ops_activity
 55  backend/llm_egress_guard.py:518           enforce_egress_firewall_for_url
 53  archon/core/orchestration.py:854          _trigger_sandy_staffing_nomination
 53  backend/content_machine.py:2137           generate_video_clip_matrix
 53  backend/erp_zugferd_pdf.py:602            build_corporate_template_pdf
 53  scripts/patches/hermes_telegram_adapter.py:6513  _handle_model_picker_callback
 52  scripts/audit_route_guards.py:242         main
 51  archon/routers/system.py:703              _load_legal_profile
 51  backend/erp_zugferd_pdf.py:298            build_zugferd_invoice_pdf
 51  backend/internet_watchdog.py:282          run_watchdog_scan
 50  scripts/apply_formatting_to_rest.py:40    process_document
```

Vollständige Telegram-Adapter-F-Liste (8 Methoden + Zeilenumfang) und Hermes-API-Oberfläche siehe **Anhang C**.

Quelle: `audit_reports/tool_scans/radon.txt` (UTF-16-LE, 4.650 Blöcke, Average complexity **B (7.138)**).

---

## Anhang B — Verifikationskommandos (zur Nachprüfung, **nicht ausgeführt**)

```bash
# Symbol-Ebene
rg -n '_get_kanban_connection' --glob '*.py'
rg -n 'import main as app_main|from main import' --glob '*.py'
rg -n '^\s*(from|import) (archon|backend)' backend archon
rg -n 'import-linter|lint-imports' .github/workflows/

# Zeilenzahlen / Struktur
(get-content main.py).Count                                       # 3638
(get-content backend/operations_api.py).Count                       # 4511
(get-content core_dispatcher.py).Count                              # 3803
(get-content backend/workflow_dag_runner.py).Count                  # 3035
(get-content archon/core/delegation.py).Count                       # 2346
(get-content archon/core/orchestration.py).Count                    # 1941
(get-content archon/routers/hermes_config.py).Count                 #  776
(get-content scripts/patches/hermes_telegram_adapter.py).Count     # 11232
rg -c 'include_router' main.py                                     # 75
# NICHT (-split "`n").Count — zaehlt bei trailing newline +1 (siehe §0.3 / D.5 #15)

# Final-Gate (GEHÖRT G1, nicht diesem Dossier) — mit ARCHON_DATA_DIR=<temp>!
pytest tests/ -q
ruff check . --select F821
mypy --config-file mypy.ini .
compileall / tsc --noEmit / npm run build / docker compose config --quiet
python scripts/audit_secrets.py --all
```

---

## Anhang C — Telegram-Adapter: Hermes-API-Oberfläche & Compose-Matrix

### C.1 `register(ctx)`-Vertrag (`:11212-11232`, 17 Keywords)

`name="telegram"`, `label="Telegram"`, `adapter_factory=_build_adapter` (11006), `check_fn=telegram_deps_present` (434), `ensure_deps_fn=check_telegram_requirements` (445), `is_connected=_is_connected` (11017), `required_env=["TELEGRAM_BOT_TOKEN"]`, `install_hint`, `setup_fn=interactive_setup` (11071), `apply_yaml_config_fn=_apply_yaml_config` (11083), `allowed_users_env="TELEGRAM_ALLOWED_USERS"`, `allow_all_env="TELEGRAM_ALLOW_ALL_USERS"`, `cron_deliver_env_var="TELEGRAM_HOME_CHANNEL"`, `standalone_sender_fn=_standalone_send` (11034), `max_message_length=4096`, `emoji="✈️"`, `allow_update_command=True`.

### C.2 Importierte Hermes-Namespaces (alle **nicht** im Repo)

`gateway.platforms.base` (`BasePlatformAdapter`, `MessageEvent`, `MessageType`, `ProcessingOutcome`, `SendResult`, `cache_*_from_bytes`, `classify_send_error`, `resolve_proxy_url`, `utf16_len`, `SUPPORTED_*`), `gateway.platforms.helpers`, `gateway.platforms._http_client_limits`, `gateway.config`, `gateway.authz_mixin`, `gateway.session`, `gateway.run`, `gateway.sticker_cache`, `gateway.rich_sent_store`, `plugins.platforms.telegram.telegram_ids`, `plugins.platforms.telegram.telegram_network`, `hermes_cli.{config,commands,lifecycle,providers,models,model_cost_guard,gateway,setup}`, `hermes_constants`, `agent.{redact,secret_scope}`, `tools.{lazy_deps,approval,slash_confirm,clarify_gateway,url_safety,vision_tools,send_message_tool}`, `utils`. Drittanbieter `telegram` / `telegram.ext` / `telegram.request` mit `ImportError`-Fallback (`:289-311`, `TELEGRAM_AVAILABLE=False`).

### C.3 Überschriebene `BasePlatformAdapter`-Methoden / PTB-Handler

`message_len_fn` (@property, 898), `connect` (4152), `disconnect` (4808), `send` (4981), `send_or_update_status` (5308), `edit_message` (5342), `delete_message` (5766), `supports_draft_streaming` (5791), `send_draft` (5824), `send_update_prompt` (5952), `send_exec_approval` (6005), `send_slash_confirm` (6081), `send_clarify` (6129), `send_model_picker` (6211), `send_choice_picker` (6285), `prefers_fresh_final_streaming` (1985), `streaming_overflow_limit` (2000), `create_handoff_thread` (3575), `ensure_dm_topic` (3593), `rename_dm_topic` (3646), `send_voice` (7773), `send_multiple_images` (7924), `send_image_file` (8060), `send_document` (8154), `send_video` (8209), `send_image` (8260), `send_animation` (8361), `send_typing` (8452), `get_chat_info` (8494), `format_message` (8528), `on_processing_start` (10927), `on_processing_complete` (10936).
PTB-Handler: `_register_handlers` (4122-4150) → `_handle_text_message` (9724), `_handle_command` (9780), `_handle_location_message` (9934), `_handle_media_message` (10139), `_handle_callback_query` (6873), `_on_platform_update` (3940, `TypeHandler(Update, …, group=99)`).

### C.4 radon Rang F — vollständig (8 Methoden)

| CC | Zeile | Umfang | Methode |
|---:|---:|---:|---|
| **158** | 6873 | **765 Z.** | `TelegramAdapter._handle_callback_query` |
| 73 | 10139 | 300 Z. | `TelegramAdapter._handle_media_message` |
| 72 | 11083 | 126 Z. | `_apply_yaml_config` |
| 72 | 4981 | 327 Z. | `TelegramAdapter.send` |
| 53 | 6513 | 335 Z. | `TelegramAdapter._handle_model_picker_callback` |
| 47 | 4152 | **536 Z.** | `TelegramAdapter.connect` |
| 45 | 9780 | 154 Z. | `TelegramAdapter._handle_command` |
| 44 | 10717 | 170 Z. | `TelegramAdapter._build_message_event` |

Klasse `TelegramAdapter` (817): **B (10)**. Rang-D-Ausreißer u. a. `_verify_polling_after_reconnect` (28), `edit_message` (28), `_handle_polling_conflict` (27), `disconnect` (24).

### C.5 Compose-Matrix (Hermes)

| Datei | Zeile | Digest | Adapter-Mount |
|---|---|---|---|
| `docker-compose.yml` | 374 / 437 | `276d4468…` | ✅ `:405` |
| `docker-compose.hermes.yml` | 32 / 75 | `e6d81ae5…` | ❌ keiner |
| `docker-compose.{override,dev,demo}.yml` | – | – | 0 Treffer |

`docker-compose.hermes.yml` nutzt zusätzlich `container_name: hermes-agent` (33) und `HERMES_HOME=/home/hermes/.hermes` (44) statt `/opt/data`. `config/version.json` und `requirements*.txt`: 0 Treffer für `hermes` / `telegram` / Digest. `backend/hermes_updater.py:203-230,276-297,379` ermittelt Versionen dynamisch per `hermes --version` / GitHub-Tags — ohne Bezug auf Adapter-Datei oder Digest.

### C.6 Test-Inventar

| Test | Art | Prüft |
|---|---|---|
| `test_telegram_gate_meldung.py` (10 Tests) | **AST-`exec`, kein Modulimport** | `gate_decision_answer` + `GATE_OK_TEXT`/`GATE_REJECT_TEXT`: 200/ok, 200+error/FEHLER, reject, 503, kaputtes JSON; Aufrufstelle per `ast.walk`; Marker-Verbot (`:112-129`) |
| `test_reaudit_stage6.py:35-40` | Reiner Textcheck | kein Fallback-Status-Set im HITL-Block |
| `ci.yml:166-167` | `compileall -q … scripts …` | nur Syntax |

## Anhang D — Test-Mapping, Ownership-Modell & Korrektur-Trail

### D.1 Legende

**V** = Verhalten (Assertion auf Returnwert / HTTP-Status / DB / Span-Persistenz) · **S** = Struktur (Source-Text, `"x" in src`, `hasattr`, `inspect.getsource`, Regex/AST auf Dateiinhalt) · **V/S** = gemischt. Bestand `tests/*.py` ≈ 280 Dateien. **S-Tests sind für einen Refactor-Split wertlos** — sie brechen bei identischem Verhalten oder bleiben grün, obwohl Verhalten gebrochen ist.

### D.2 S-Tests — Kurzliste für G7 (Umstellung auf V, nicht Löschen)

`test_audit_p1_governance.py` · `test_med2_a_dispatch.py` (Source-Anteil `:88/:180/:190/:202/:228`) · `test_reaudit_d16_dispatcher.py` · `test_reaudit_stage6/8/9/11/12/13.py` · `test_fix_w3_d_trajectory_dag.py:49/:208` · `test_fix_w4_d2_residuals.py:29/:88/:133` · `test_fix_batch15.py:58` · `test_orange_b_f14.py` · `test_orange_b_d18.py:20` · `test_workflow_dag_e2e.py:247` · `test_fix_w3_b_performance.py:173/:204/:384/:388/:393/:401/:421` · `test_fix_batch13.py` · `test_fix_batch5.py:102` · `test_rag_key_env.py:104/:145/:157` · `test_a5_*.py` · `test_reaudit_stage7.py:62/:77` · `test_p2_delegation_memory_binding.py` · `test_p2_shared_queue.py` · `test_p2_deterministic_fan_in.py` · `test_p2_cancellation_wiring.py:35` · `test_med2_c_orchestration.py:80/:120/:130` · `test_d11_handoff_hardening.py:187` · `test_audit_b1_b8_blockers.py:177` · `test_telegram_gate_meldung.py:51/:112/:124` · `test_reaudit_stage6.py:35-40`.

**Ausnahme behalten:** `tests/test_unbound_calls.py` — AST-Scan auf ungebundene Namen, der einzige S-Test mit echtem Split-Nutzen (Erkennt vergessene Importe nach Router-Extraktion).

### D.3 Import-Layer-Test-Lücke (verifiziert)

| Suche in `tests/` | Ergebnis |
|---|---|
| `importlinter` / `lint-imports` / `import-linter` / `forbidden_modules` / `root_package` / `contract:` | **0 Treffer** |
| `Layergrenze` / `Importzykl` / `import cycle` / `H-09-2` | 9 Treffer, alle **DAG-/Delegations**-Zyklen, keine Importzyklen |
| `archon.routers` | 297 Treffer, ausschließlich als Import-Ziel in RBAC-/API-Tests |
| `contract` | nur `contract_manager` / `contracts.db` / `esign_contracts` |

Einziger import-bezogener Struktur-Test: `test_audit_b2_rbac_tenant.py:25-39` (`assert "import main" not in segment`, **scoped auf `RBAC_FUNCS`-Wrapper**). Außerhalb `tests/`: `scripts/run_static_toolchain.ps1:25`, `scripts/run_remaining_scans.ps1:15`; in `.github/` **0 Treffer**. ⇒ **Kein pytest-Test, kein CI-Gate** sichert die Layergrenze ab.

### D.4 Lücken-Übersicht (Characterization fehlt)

| # | Lücke | Beleg |
|---|---|---|
| 1 | `/livez` ↔ `_FAIL_FAST_HOOKS` / `_AUDIT_COMPROMISED` nicht verdrahtet getestet | `test_fix_w1_a_audit.py:281-298` nur isoliert + Registrierung |
| 2 | Lifespan-Shutdown-Timeout, `_SHUTDOWN_HOOKS`-`reversed()`, `_close_all_http_clients()` | `conftest.py:34-58` nur Fixture; `test_fix_batch5.py:102` nur „async def" |
| 3 | n8n-Startup-Opt-in / `_N8N_STARTUP_STATUS` → `/readyz`-Degradation | `fix_d1_main.md:16`; kein Test |
| 4 | **CC-246-Executor: keine Verzweigungsmatrix, nur 4 direkte V-Tests** | `test_stage1_stage3_hardening_and_bus.py:349/:384/:405/:740`; `test_workflow_dag_e2e.py:85-408` |
| 5 | `operations_api.py:923-936` Allokationsfehler → `blocked/budget_allocation_failed` nur S-Test | `fix_w3_d_trajectory_dag.md:117-120`; `test_fix_w3_b_performance.py:415` |
| 6 | `delegation.py` `_MAX_DELEGATION_DEPTH=5` vs. SSOT `trajectory_budget.MAX_DELEGATION_DEPTH=3` | `fix_w3_d_trajectory_dag.md:107-110` |
| 7 | W4-D2-Delegations-Span nur Source-Text, kein Laufzeit-`record_span` | `test_fix_w4_d2_residuals.py:29-37` vs. `fix_w4_d2_residuals.md:43` |
| 8 | Telegram: nur `gate_decision_answer` charakterisiert, kein Callback/HTTP-Pfad | `test_telegram_gate_meldung.py:8-11/:26-48` |
| 9 | Import-Layer / Importzyklen: **null** pytest-Tests, nur PowerShell-Toolchain | D.3 |
| 10 | Rote/blockierende Tests zählen nicht als Characterization | `test_show_hn_blockers.py:55`, `test_jev_router.py:75-77`, `test_graceful_shutdown.py:100` |

### D.5 Korrektur-Trail (Ausgangslage → verifizierter Ist-Stand)

| # | Ursprüngliche Annahme | **Korrigiert** | Beleg |
|---|---|---|---|
| 1 | `main.py` 3.393 Zeilen | **3.638** (+245) | `read`, Working Tree |
| 2 | `operations_api.py` ~3.923 | **4.511** (+588) | `read` |
| 3 | `core_dispatcher.py` nicht gelistet | **3.803**, größer als `main.py` | `read` |
| 4 | „~80 reziproke Importzeilen" | **715** (81 + 634) | `grep backend archon` |
| 5 | import-linter „Importe aufgelöst" | Config falsch gerootet; **0 CI-/pytest-Tests**, nur PowerShell | `.importlinter`, D.3 |
| 6 | Zyklus via `DelegationPayload` | via **`_get_kanban_connection`**; `DelegationPayload` nur Alias | `delegation.py:114`, `operations_api.py:67-70` |
| 7 | S3 „nur hohles Modul" | 26 Top-Level-Imports + ~45 Referenzen + 2 CC-118-Blöcke | §2.1, §1.1 |
| 8 | `register(ctx)` fehlt | **existiert** `:11212-11232`, 17 Keywords | Anhang C.1 |
| 9 | Hermes-Image „pinzen" | bereits digest-gepinnt, aber **2 widersprüchliche Digests** | `docker-compose.yml:374`, `hermes.yml:32` |
| 10 | CC-246 „von 15 Testdateien umgeben" | **4 direkte V-Tests**; E2E nutzt `mock_exec` | `test_workflow_dag_e2e.py:85-408` |
| 11 | S2 = Router auslagern | zusätzlich **≥90 Rückwärts-Imports / ~50 Symbole**, ungetestet | §2.3, D.3 |
| 12 | `hermes_config.py` in `archon/core/` | in **`archon/routers/`** | `glob` |
| 13 | Mount `docker-compose.yml:383` | **`:405`** | `read` |
| 14 | `ci.yml:164` compileall | **`:166-167`** | `read` |
| 15 | Zeilenzahlen per `-split`-Zählung | **Off-by-one −1 bei 6 von 9 Dateien** (trailing newline); SSOT = `read`/`(Get-Content).Count` → 4.511 / 3.803 / 3.035 / 2.346 / 776 / 11.232 | unabhängige Verifikation 25.11. |
| 16 | Dossier gegen Code ungeprüft | **Prüfpunkte 2–9 vollständig bestätigt, 0 Abweichungen** (Importzahlen 81/41/634/27, `register(ctx)` 17 Keywords, CC 246 / 4 V-Tests / `mock_exec`, `.importlinter`, beide Digests, Pfad-/Zeilenkorrekturen, Alias) | unabhängige Verifikation 25.11. |

| 17 | 10 pip-audit-CVEs / 4 Pakete → „im Lockfile anheben" (Handoff §3/§5.3) | **Nicht ausführbar / NOOP**: `mcp`, `stanza`, `wcmatch` in **keinem** Manifest/Lockfile/Dockerfile/`ci.yml`; `opentelemetry-api` im Runtime-Lock bereits **1.45.2** (= Fix, mit Hashes `requirements.lock.txt:1388-1391`). Die 1.37.0 ist nur das lokale Dev-`.venv` nach semgrep-Downgrade. CI-Gate `ci.yml:446` auditiert nur `requirements.lock.txt` → nicht betroffen. **Entscheidung: kein Bump, nur dokumentieren + lokales `.venv` sanieren** | Commit-/CVE-Vorlage 25.11. |
| 18 | `git add -A` für den grünen Commit | **Selektiv, kein `-A`**: `.gitignore` ignoriert keines der 4+2 Ausschluss-Artefakte; zusätzlich **MUSS** rein: `mypy.ini` (`ci.yml:535/548` + 2 Tests), `requirements-ci.lock.txt` (`test -f` an 5 Stellen), `tests/test_fix_d2_mypy.py`, `tests/test_fix_d3_last_pragmas.py` | Commit-/CVE-Vorlage 25.11. |

**Ergebnis der unabhängigen Verifikation (25.11., frischer Kontext, read-only):** Der Verifikationsagent meldete 4 Abweichungen, alle aus Prüfpunkt 1. Nach Ausweitung auf **alle 9** Zeilenzahlen sind es **6** — `main.py` (3.638) und `orchestration.py` (1.941) waren exakt. Alle übrigen Prüfpunkte (2–9) sind gegen den aktuellen Code **vollständig verifiziert**. **Keine inhaltliche Auswirkung** auf Klassifizierung, Priorisierung, Risikoklassen oder Split-Pläne: die Δ betrifft ausschließlich die Zählweise.

---

**Ende des Dossiers.** Keine Code-Änderung, kein Testlauf, kein Commit, kein Build durch G0.
