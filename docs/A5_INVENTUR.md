# A5/A7/A8 — Inventur und Etappenplan

Stand: 2026-11-07 abends · Branch `refactor/a5-di-config` @ `4956f518`
Basis: `refactor/critical-hardening` @ `314ea093` · **57 Commits seit `main`**

Dieses Dokument ist die Messgrundlage für die A5/A7/A8-Etappen. Jede Zahl ist mit dem
genannten Befehl am 2026-11-07 selbst erhoben — keine Schätzung, keine Abschrift.
Legende Kategorien: **K** = unveränderlich · **KP** = Pfad-Konstante (B10) ·
**M** = mutabler Modul-State · **R** = Runtime-Objekt/-Wert.

---

## 0. Messgrundlage (Ausgangsstand, verifiziert)

| Größe | Wert | Messbefehl |
|---|---|---|
| `main.py` | **11.291** Zeilen | `wc -l main.py` |
| Decorator-Routen | **308** | `grep -cE '@app\.(get\|post\|put\|patch\|delete\|websocket\|api_route)\(' main.py` |
| Router-Dateien | **20**, davon **6** mit `configure()` | `ls archon/routers/*.py \| wc -l`; `grep -ln "def configure(" archon/routers/*.py` |
| Modul-Globals (grep) | **52** | `grep -cE '^[A-Z_][A-Z0-9_]* = ' main.py` |
| Modul-Globals (AST) | **58** | AST-Scan über `ast.Assign` + `ast.AnnAssign` auf Modulebene |
| `Depends()` in `main.py` | **0** | `grep -c "Depends(" main.py` |
| Parität | **585/861**, Exit 0 | `scripts/route_parity.py --check scripts/parity_baselines/openapi_baseline_2026-11-07.json` |
| Router-Namen | Exit 0 | `scripts/check_router_names.py` |
| Tests | **234 passed, 8 skipped** | `pytest tests/ -q --no-header -p no:cacheprovider` |

**Warum 52 ≠ 58 — und warum die AST-Zahl die richtige ist.**
Das grep-Muster verlangt `NAME = ` direkt hinter dem Namen. Sechs Globals sind aber
**annotiert** und fallen damit durch das Muster:

```
55   _STARTUP_HOOKS: List[Any] = []
56   _SHUTDOWN_HOOKS: List[Any] = []
1688 _BACKGROUND_TASKS: list = []
10145 _FABRIC_CACHE: Optional[List[Dict[str, Any]]] = None
10152 _PROMPT_STUDIO_CACHE: Optional[List[Dict[str, Any]]] = None
10363 _PROXY_HTTP_CLIENTS: Dict[int, httpx.AsyncClient] = {}
```

52 + 6 = 58. Die Kennzahl A5 im Audit („40+ Modul-Globals") ist also mit **58** ehrlicher
anzusetzen; alle sechs Nachzügler sind mutabler State und in dieser Etappe nicht anfassbar.

---

## 1. Kategorien-Tabelle — alle 58 Globals

Leser-Zahl = Treffer in `main.py`+`archon`+`backend`+`utils`+`tests`+`scripts` ohne die
Definitionszeile. **Achtung bei den Hermes-Caches:** `archon/routers/skills.py:54-60` hält
**eigene Kopien** dieser Namen mit eigenem `global`. Die dort gezählten Treffer sind eine
zweite Bindung, kein Leser der `main.py`-Variable.

| Zeile | Name | Kat | Werttyp | Leser | Entscheidung / Grund |
|---|---|---|---|---|---|
| 55 | `_STARTUP_HOOKS` | M | List | 3 | bleibt — mutabel (`.append` beim Startup) |
| 56 | `_SHUTDOWN_HOOKS` | M | List | 3 | bleibt — mutabel |
| 89 | `_APP_START_TS` | R | `time.time()` | 1 | bleibt — Auswertungszeitpunkt; eine Auslagerung würde den Zeitpunkt auf den Import von `constants.py` verschieben |
| 136 | `_AUTH_PUBLIC_EXACT` | M | Set | 1 | bleibt — Set-Literal ist mutabel (Fallstrick 24) |
| 137 | `_AUTH_PUBLIC_PREFIXES` | **K** | Tuple | 1 | **verschoben** |
| 141 | `_AUTH_PROTECTED_PREFIXES` | **K** | Tuple | 1 | **verschoben** |
| 151 | `_SERVICE_TOKEN_CACHE` | M | Dict | 3 | bleibt — Mutations-Cache (`ts`/`token`) |
| 331 | `MEMORY_FILE` | KP | `os.path.join` | 2 | bleibt — B10 |
| 332 | `AGENTS_FILE` | KP | `os.path.join` | 3 | bleibt — B10 |
| 333 | `ROLES_FILE` | KP | `os.path.join` | 5 | bleibt — B10 **und** Dublette zu Z. 2524 |
| 334 | `KANBAN_FILE` | KP | `os.path.join` | 0 | bleibt — B10 (zusätzlich toter Code) |
| 335 | `SERVICES_FILE` | KP | `os.path.join` | 3 | bleibt — B10 **und** Dublette zu Z. 2525 |
| 336 | `THEME_FILE` | KP | `os.path.join` | 2 | bleibt — B10 |
| 337 | `THEME_LIVE_FILE` | KP | `os.path.join` | 6 | bleibt — B10 |
| 338 | `GATEWAY_CONFIG_FILE` | KP | `os.path.join` | 2 | bleibt — B10 |
| 339 | `QUICKCHAT_SESSIONS_DIR` | KP | `os.path.join` | 2 | bleibt — B10 |
| 349 | `DEFAULT_AGENTS` | M | List | 4 | bleibt — Liste |
| 398 | `DEFAULT_SERVICES` | M | List | 2 | bleibt — Liste |
| 466 | `GHOST_AGENT_IDS` | M | Set | 2 | bleibt — Set |
| 488 | `COUPLED_AGENTS_FILE` | KP | `os.path.join` | 5 | bleibt — B10 |
| 700 | `THEMES_DIR` | KP | `os.path.join` | 6 | bleibt — B10 |
| 732 | `DESIGN_THEMES_TARGETS` | M | List | 3 | bleibt — Liste |
| 1122 | `FRAMEWORKS_FILE` | KP | `os.path.join` | 7 | bleibt — B10; **wird von `archon/routers/boardroom.py` importiert** |
| 1123 | `BOARDROOM_HISTORY_FILE` | KP | `os.path.join` | 5 | bleibt — B10; **wird von `boardroom.py` importiert** |
| 1688 | `_BACKGROUND_TASKS` | M | List | 3 | bleibt — mutabel |
| 2524 | `ROLES_FILE` | KP | `os.path.join` | 5 | bleibt — **doppelte Definition** (siehe §5) |
| 2525 | `SERVICES_FILE` | KP | `os.path.join` | 3 | bleibt — **doppelte Definition** (siehe §5) |
| 2527 | `DEFAULT_ROLES` | M | List | 7 | bleibt — Liste |
| 2740 | `HERMES_PROFILES_DIR` | KP | `os.path.join` | 10 | bleibt — B10; **von `archon/core/profiles.py` importiert** |
| 2742 | `_HERMES_SKILLS_CACHE` | R | `None` | 11 | bleibt — Cache-Halter, wird neu zugewiesen |
| 2743 | `_HERMES_SKILLS_CACHE_TIME` | M | int | 5 | bleibt — Zähler, wird neu zugewiesen |
| 2744 | `_HERMES_SKILLS_CACHE_TTL` | K | float | 2¹ | bleibt — **in `main.py` 0 Leser** (toter Code), echte Kopie lebt in `skills.py:54` |
| 2747 | `_SKILL_INDEX_DISK_PATH` | KP | `os.path.join` | 4 | bleibt — B10 |
| 2766 | `ALL_HERMES_TOOLS` | M | List | 0 | bleibt — Liste (zusätzlich unbenutzt) |
| 3050 | `_DECISION_TYPEN` | **K** | Tuple | 2 | **verschoben** |
| 3814 | `_ORG_HIERARCHY_CACHE` | M | Dict | 3 | bleibt — Mutations-Cache |
| 3853 | `DELEGATION_PROTOCOL_PROMPT` | **K** | str (28 Z.) | 1 | **verschoben** |
| 3882 | `DELEGATION_ALIAS_MAP` | M | Dict | 4 | bleibt — Dict |
| 5068 | `_GUARDIAN_STATS_CACHE` | M | Dict | 2 | bleibt — Mutations-Cache |
| 5641 | `DEFAULT_PLUGIN_CONFIGS` | M | Dict | 1 | bleibt — Dict |
| 6964 | `HELP_CONTEXT_DATA` | M | Dict | 2 | bleibt — Dict |
| 7557 | `_PAPERCLIP_AGENTS_CACHE` | R | `None` | 2 | bleibt — Cache-Halter |
| 7558 | `_PAPERCLIP_AGENTS_CACHE_TIME` | M | float | 2 | bleibt — Zähler |
| 7559 | `_PAPERCLIP_AGENTS_CACHE_TTL` | K | float | 0 | bleibt — **toter Code** (0 Leser, auch projektweit) |
| 7571 | `STUDIO_BG_UPLOAD_DIR` | **K** | str (`__file__`) | 2 | **verschoben** — nicht `/opt/data`-basiert, also kein B10-Gut |
| 7783 | `SETTINGS_FILE` | KP | `os.path.join` | 62 | bleibt — B10; **von 16 Routern + 5 Backend-Modulen importiert** |
| 8299 | `_VAULT_FILES_CACHE` | M | Dict | 6 | bleibt — Mutations-Cache |
| 8400 | `KANBAN_CARDS_FILE` | KP | `os.path.join` | 3 | bleibt — B10 |
| 8438 | `_TELEMETRY_CACHE` | M | Dict | 3 | bleibt — Mutations-Cache |
| 8498 | `CONFIG_FILE` | KP | `os.path.join` | 3 | bleibt — B10 |
| 9868 | `_LIVE_TELEMETRY_CACHE` | M | Dict | 7 | bleibt — Mutations-Cache |
| 10008 | `_MC_STATE_CACHE` | M | Dict | 13 | bleibt — Mutations-Cache, **von `mission_control.py` importiert** |
| 10132 | `PROMPT_TEMPLATES_PATHS` | M | List | 2 | bleibt — Liste, **von `templates.py` importiert** |
| 10145 | `_FABRIC_CACHE` | R | `None` | 6 | bleibt — Cache-Halter |
| 10152 | `_PROMPT_STUDIO_CACHE` | R | `None` | 6 | bleibt — Cache-Halter |
| 10363 | `_PROXY_HTTP_CLIENTS` | M | Dict | 2 | bleibt — Client-Pool |
| 10377 | `_OMNIROUTE_PROXY` | R | `None` | 4 | bleibt — Proxy-Objekt |
| 10408 | `_N8N_PROXY` | R | `None` | 4 | bleibt — Proxy-Objekt |

¹ Die zwei Leser liegen in `archon/routers/skills.py` und betreffen dessen **eigene** Kopie.

**Verteilung (gemessen):** K 7 · KP 20 Einträge (18 eindeutige Namen, 2 Dubletten) ·
M 24 · R 7 = **58**. Leser-Stellen: K 9 · KP 138 · M 83 · R 34.

### Verschoben in dieser Etappe (5 Namen, 7 Leser-Stellen)

`_AUTH_PUBLIC_PREFIXES`, `_AUTH_PROTECTED_PREFIXES`, `_DECISION_TYPEN`,
`DELEGATION_PROTOCOL_PROMPT`, `STUDIO_BG_UPLOAD_DIR`

Jeder Kandidat wurde vor dem Schnitt per AST auf **Reassignment-Freiheit** geprüft
(`Stores=0`, `global`-Deklarationen=0, genau eine Zuweisung = die Definition).

### Bewusst nicht verschoben (K-Namen, die formal passen)

| Name | Grund |
|---|---|
| `_HERMES_SKILLS_CACHE_TTL` | in `main.py` **0 Leser**; die produktive Kopie ist `archon/routers/skills.py:54`. Eine Auslagerung würde die Legende „einzige Quelle" verletzen, ohne etwas zu bündeln — richtige Maßnahme ist **Löschen**, nicht Verschieben (Etappe 3). |
| `_PAPERCLIP_AGENTS_CACHE_TTL` | projektweit **0 Leser** — toter Code, gehört gelöscht (Etappe 3). |

---

## 2. A8 — Bestand der Konfigurationsquellen (nur Bestand, keine Bewertung)

| Datei / Quelle | Zweck | Gelesen von | Treffer |
|---|---|---|---|
| `.env.archon` | Env-Variablen für den Container | `docker-compose.dev.yml:10-11` (`env_file`) | 1 Deklaration |
| `os.environ` / `os.getenv` | Laufzeit-Env (Tokens, Limits, Pfade) | `main.py`, `archon/core/runtime.py`, `archon/routers/hermes_profiles.py`, `backend/*` | **52 Lesezugriffe in 23 Dateien** |
| `agent_workspace/settings.json` (1.195 B) | App-Einstellungen (real geschrieben) | `main.py:7783` `SETTINGS_FILE` → 62 Treffer in 22 Dateien | 62 |
| `settings.json` (Repo-Root, 32.520 B) | **zweite** Einstellungsdatei, anderer Inhalt | `main.py:7343` (Kandidatenliste) | 1 |
| `config/coupled_agents.json` | Agenten-Kopplung | `main.py:488` `COUPLED_AGENTS_FILE` | 5 |
| `config/agents.json`, `config/design_themes.json`, `config/kanban_meta.json`, … | Domänen-Konfiguration | `main.py` (Kandidatenlisten) | s. `ls config/` |
| `roles.json` | Rollen/Modelle (59 Rollen) | `main.py:333`, `:2524` (zwei Pfade!), `scripts/apply_profile_sync.py` | 8 |
| `agent_profiles.json` | Agenten-Profile (2,6 MB) | `main.py:1193-1197` (5 Kandidatenpfade) | 60 |
| `services.json` | Service-Katalog | `main.py:335`, `:2525` | 2 |
| `gateway_config.json` | Hermes-Gateway | `main.py:338` | 1 |
| `agent_configs.json` | Obsidian-Agent-Configs | `main.py:8498` `CONFIG_FILE` | 1 |
| `kanban_data.json` | Kanban-Board | `main.py:334` `KANBAN_FILE` | 1 |
| `~/.hermes/profiles/<rolle>/profile.yaml` | Hermes-Profil (Modell/Provider) | `main.py:6813`, `:7720`, `archon/core/profiles.py` | 14 |

**Zwei Befunde, die im Bestand sichtbar sind (noch keine Bewertung):**
1. **Zwei `settings.json`** mit unterschiedlicher Größe und unterschiedlichem Inhalt
   (Pitfall 5 des Betriebsskills) — nur eine davon ist `SETTINGS_FILE`.
2. **`ROLES_FILE` und `SERVICES_FILE` sind doppelt definiert** (Z. 333/2524 bzw. 335/2525)
   mit **unterschiedlicher Wurzel** (`MEMORY_DIR` vs. `WORKSPACE_DIR`). Die zweite Zuweisung
   gewinnt zur Laufzeit; die erste ist wirkungslos. Das ist derselbe Fehlerklasse-Typ wie
   „zwei Wahrheiten" und gehört in die B10-Config-Schicht.

---

## 3. A7 — Wo heute DI passiert und wo nicht

**Bestand (gemessen):**

| Mechanismus | Vorkommen | Beleg |
|---|---|---|
| `configure(**deps)` in Routern | **6 von 20** (`boardroom`, `governance`, `hermes_profiles`, `mission_control`, `skills`, `system`) | `grep -ln "def configure(" archon/routers/*.py` |
| Aufruf in `main.py`, gebündelt vor `include_router` | 6 Blöcke, Z. 11197–11282 | `grep -n "configure" main.py` |
| `_DEPS`-Muster + Warnung bei fehlenden Namen | in allen 6 | `archon/routers/system.py:22-31` |
| Keyword-only-Dependencies + `RuntimeError` statt stillem Fallback | `archon/core/orchestration.py` (`update_mc`, 4 Funktionen) | `grep -n "update_mc" archon/core/orchestration.py` |
| **FastAPI `Depends()`** | **0** | `grep -c "Depends(" main.py` |
| Router ohne jede DI | **14 von 20** — importieren Helfer direkt aus `archon.core.runtime` | AST-Scan über `archon/routers/*.py` |

**Bewertung.** Die 14 Router ohne `configure()` sind **kein** Mangel: sie brauchen keine
Injektion, weil `WORKSPACE_DIR`, `SETTINGS_FILE`, `_load_json`, `logger` prozessweite
Singletons sind. `Depends()` ist das falsche Werkzeug für Singletons — es ist für
**request-scoped** Ressourcen da (DB-Verbindung, Auth-Prinzipal, Request-Konfiguration).
Eine pauschale Umstellung von `configure()` auf `Depends()` wäre reine Form ohne Nutzen und
würde 6 funktionierende Injektionen gegen 1 Request-Signatur je Route tauschen.

**Der kleinste sinnvolle Schritt (Empfehlung, nicht umgesetzt):**

Es gibt heute **genau eine** Stelle, die eine request-scoped Ressource von Hand öffnet:
`archon/routers/system.py:137` — in `api_system_hermes_restart()` steht
`with _get_state_db() as conn:` **im** Handler. Das ist der Lehrbuchfall für `Depends()`.

```
archon/core/state_db.py   + def get_state_db() -> Iterator[sqlite3.Connection]:   (yield-Provider)
archon/routers/system.py  - with _get_state_db() as conn:
                          + conn: sqlite3.Connection = Depends(get_state_db)
```

Aufwand: **1 Provider, 1 Route**. Risiko: minimal — `Depends()` ändert nur die
Handler-Signatur, nicht die Routen-Menge; Parität bleibt 585/861, `_get_state_db()` bleibt
für die 13 übrigen Aufrufstellen unverändert. **Warum dieser und kein anderer Router:**
`swarm.py` (1 Route) und `security.py` (9 Routen) haben gar keine Ressource, die man
injizieren könnte — dort wäre `Depends()` Attrappe. `mission_control.py` und
`hermes_profiles.py` haben bereits `configure()`; sie umzubauen ist der *zweite* Schritt,
nicht der erste.

### 3.1 Rollout-Befund (Etappe 5) — keine weitere Umstellung, mit Begründung

**Pilot umgesetzt** (Etappe 3): `archon/core/state_db.py:get_state_db_dep()` (async-Generator,
weil der Handler `async def` ist) → `archon/routers/system.py:123`
`conn: sqlite3.Connection = Depends(get_state_db_dep)`.

**Inventar der verbleibenden Stellen** (AST-Scan über alle 20 Router, Route = Funktion mit
`@router.*`-Dekorator):

| Datei | Route | Ressource | Handler-Typ | Lebensdauer | Entscheidung |
|---|---|---|---|---|---|
| `hermes_profiles.py:372` | `POST /api/hermes/profiles` (`api_save_hermes_profile`) | `sqlite3.connect(avatars_db_path)` | **`def`** (Threadpool) | ein `with`-Block im Rumpf | **nicht umgestellt** |
| `hermes_profiles.py:452` | `POST /api/hermes/profiles/{id}/avatar` (`api_upload_hermes_profile_avatar`) | `sqlite3.connect(avatars_db_path)` | **`def`** (Threadpool) | ein `with`-Block im Rumpf | **nicht umgestellt** |

Sonst öffnet **kein** Router-Handler eine request-scoped Ressource (`_get_state_db` /
`_get_profile_state_db` / `sqlite3.connect`) — nachgewiesen durch
`tests/test_a7_router_db_open.py`.

**Drei Abbruchgründe, jeder einzeln belegt:**

1. **Thread-Affinität (entscheidend).** `sqlite3.connect()` gilt `check_same_thread=True`.
   Ein per Dependency erzeugter Connection wird in einem **anderen** Thread benutzt als dem
   des sync-Handlers. Gemessen (Python 3.11.16, zwei Threads mit verschiedenen Idents):
   `ProgrammingError: SQLite objects created in a thread can only be used in that same
   thread.` Gegenprobe: derselbe Test blieb einmal **grün**, weil Python Thread-Idents
   recycelt — der Fehler ist also **lastabhängig und nicht deterministisch**. Genau das ist
   die schlechteste Sorte Fehler: Tests grün, Betrieb rot. Beim Pilot (`async def`-Handler)
   war das kein Thema, weil ein async-Provider im selben Event-Loop-Thread läuft.
2. **Fehlerpfad.** Heute fängt ein umgebendes `try/except Exception → logger.warning` einen
   fehlgeschlagenen `connect` ab und der Handler läuft weiter. Eine Dependency wird **vor**
   dem Handler aufgelöst — der Fehler würde zum 500 statt zur Warnung. Identisches Verhalten
   ließe sich nur herstellen, indem der Provider selbst `None` liefert und die
   Fehlerbehandlung des Handlers dupliziert; das wäre mehr Code als heute, an der falschen
   Stelle.
3. **Kein realer HTTP-Beleg möglich.** Beide Routen sind **mutierend** (schreiben
   `profile.yaml`, `agent_profiles.json`, `avatars.db`). Ein echter Aufruf würde
   Produktivdaten ändern — laut Auftrag nur mit Rückfrage zulässig.

**Fazit:** Das Pilot-Muster überträgt sich **nicht** auf sync-Handler mit dynamischem Pfad und
eigener Fehlerbehandlung. Die beiden Stellen bleiben, bis es einen Connection-Pool oder eine
`check_same_thread=False`-Strategie mit eigener Testabdeckung gibt — das ist ein eigener
Schnitt, kein Rollout.

---

## 4. Etappenplan (Aufwand aus Messwerten, nicht aus Gefühl)

Aufwandsmaß = **Anzahl Namen × Leser-Stellen** (Reader-Sites, die beim Verschieben
angefasst bzw. verifiziert werden müssen).

| Etappe | Inhalt | Namen | Leser-Stellen | Eingriff | Abbruchkriterium |
|---|---|---|---|---|---|
| **1 (diese)** | K-Konstanten → `archon/core/constants.py` | **5** | **7** | 1 neues Modul, 1 Import-Block, 5 Definitionen entfernt | Parität ≠ 585/861 **oder** `check_router_names` ≠ 0 **oder** Tests ≠ 234/8 **oder** `NameError` im Log **oder** `/health` ≠ 200 → `git checkout -- main.py archon/core/constants.py`, abbrechen |
| **2** | KP-Pfade → eigene Config-Schicht | 18 | 138 | **gehört zu B10**, eigener Branch/Tag, eigene Baseline | dito + Parität gegen **neue** Baseline; eine Verschiebung ohne neue Baseline ist ungültig |
| 2a | davon Dubletten `ROLES_FILE`/`SERVICES_FILE` auflösen | 2 | 8 | reine Reduktion, kein neues Modul | wie Etappe 1 |
| **3** | toten Code entfernen (`_HERMES_SKILLS_CACHE_TTL`, `_PAPERCLIP_AGENTS_CACHE_TTL`, `KANBAN_FILE`, `ALL_HERMES_TOOLS`) | 4 | 0 | Löschen, kein Verschieben | wie Etappe 1 |
| **4** | M-State bündeln (Caches in ein `state`-Modul) | 24 | 83 | riskant: 8 Namen werden **über Modulgrenzen** gelesen (`_MC_STATE_CACHE`, `PROMPT_TEMPLATES_PATHS`, `_HERMES_SKILLS_CACHE*`, `_FABRIC_CACHE`, `_PROMPT_STUDIO_CACHE`) — Fallstrick 24/27 | nur mit eigener Testabdeckung; bei jedem Namen `.clear()`-Muster statt Neuzuweisung prüfen |
| **5** | A7 — erster `Depends()`-Provider | 1 Provider | 1 Route | `state_db.get_state_db()` + `system.py:137` | Parität + Tests; **keine** Sammelumstellung der 6 `configure()`-Router |

**Reihenfolge-Begründung:** Etappe 1 hat 7 Leser-Stellen und 0 Modulgrenzen — das kleinste
Risiko überhaupt. Etappe 2 ist mit 138 Leser-Stellen der größte Block und gehört deshalb in
B10 mit eigener Baseline. Etappe 4 ist die einzige mit Modulgrenzen-Lesern und wird
zuletzt angefasst.

---

## 5. Nicht-Ziele dieser Etappe (ausdrücklich)

- **Keine** Änderung an mutablen Globals (Listen, Dicts, Sets, Caches) — Fallstrick 24.
- **Keine** Pfad-Konstanten — das ist B10 mit eigener Baseline.
- **Keine** Umstellung von `configure()` auf `Depends()`.
- **Keine** Änderung an `archon/routers/*`, `backend/*`, `utils/*`.
- **Keine** Löschung toten Codes (eigene Etappe, eigene Begründung im Commit).
- **Kein** Anfassen fremder untracked Dateien (`frontend/`, `docs/BETRIEB_HANDBUCH_INTERN.md`,
  `hermes_skills_*.json`, `archon/core/agent_profiles.json`, `.archon_backup_*`).
- **Keine** Aussage über Laufzeitverhalten der Endpunkte — diese Etappe belegt Bindung und
  Guards, nicht Verkehr.
