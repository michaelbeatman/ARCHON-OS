# Grundprüfung 2026-11-07 — Audit-Nachmessung, P1–P8, Sicherheit, tote UI-Pfade

**Rolle:** Prüfer, read-only. Keine Code-Änderung, kein Commit, kein Deploy, kein Restart.
**Projekt:** Archon OS, `/mnt/raid/AgenticOS-2026`, Branch `refactor/a5-di-config` @ `58572a6f`
**Geprüfte Instanz:** `ARCHON-OS`, `Up 7 hours`, `127.0.0.1:8501->8501/tcp`, Image `af26a3ee66e2`
(`archon-os-dev:latest`), gestartet 2026-11-07T08:29Z.
**Messzeitpunkt:** 2026-11-07 ~16:40–17:30 (Host).
**Grundlage:** `docs/AUDIT_STATUS.md` (462 Z.), `docs/A5_INVENTUR.md`, `docs/HANDOVER_2026-11-07_nacht.md`.

**Regel dieses Dokuments:** jede Zahl ist hier selbst erhoben. Wo ich eine Zahl aus der Doku
zitiere, steht sie unter „Behauptung" und ist als solche markiert. Messskripte lagen **außerhalb**
des Repos (`~/…/cache/scratch/`), im Repo ist **nur diese Datei** neu.

Umgebungsgrenze vorab: in dieser Session waren `python - <<EOF` und `python -c` gesperrt
(unattended, kein Freigabekanal). Alle Messungen liefen daher als Datei mit
`.venv/bin/python <pfad>` bzw. als `curl`/`jq`/`grep`. In-Process-Messungen liefen mit dem
Host-Interpreter (3.11), nicht im Container; das ist bei jeder Zahl vermerkt, wo es zählt.

---

## 1. Gesamtbild Block 1 — 36 Punkte, drei Statuswechsel, 15 Zahlen-Drifts

### 1.1 Die 40-vs-36-Frage — beantwortet: **die 40 ist unbegründet, das Dokument hatte nie mehr als 36**

Belege, alle aus dem Repo selbst:

| Beleg | Fundstelle | Aussage |
|---|---|---|
| Formulierung | `docs/AUDIT_STATUS.md:5` | „Bezug: externes Code-Audit (God-File-Analyse, **~40 Punkte**, A/B/P/S)" — Tilde, Näherung, keine Liste |
| Tabellenzeilen heute | `grep -cE '^\| [ABSP][0-9]+ \|' docs/AUDIT_STATUS.md` | **36** (A1–A8, B1–B10, S1–S10, P1–P8) |
| Erste committete Fassung | `git show 5bd1678d:docs/AUDIT_STATUS.md \| grep -cE '^\| [ABSP][0-9]+ \|'` | **36** — mit **identischen** IDs, keine Zeile wurde je entfernt |
| Interne Gegenprobe | `docs/AUDIT_STATUS.md:459-462` | „zwölf" ✅ + 12 namentlich teilweise + A5/A7/A8 + B9 + P1–P8 = **36**. Die Eigenrechnung des Dokuments stimmt nur mit 36 |
| Suche nach fehlenden IDs | `grep -rn "A9\|A10\|B11\|B12\|S11\|S12\|P9" docs/*.md` | **0 Treffer** — nirgends ein Hinweis auf vier weitere Punkte |
| Quelle des Audit-Originals | Suche in `docs/`, `docs/security/`, `REFACTOR_STAND_2026-11-06.md` | **nicht vorhanden**; das externe Audit liegt nicht im Repo |

**Ergebnis:** Es fehlen keine vier Punkte *im Dokument* — es wurden nie mehr als 36 geführt.
Zwei Lesarten bleiben, beide führen zum selben Handlungsbedarf:
(a) Das externe Audit hatte ~40 Punkte, vier wurden beim Überführen nie erfasst — dann sind ihre
IDs und Inhalte **nicht mehr rekonstruierbar** (kein Original im Repo; das ist der eigentliche
Verlust, nicht die Zahl).
(b) „~40" war eine gerundete Schätzung, die über die Handover-Kette (`HANDOVER_2026-11-06_abend.md:14`,
`…-11-07.md:16`, `…-11-07_abend.md:19`, `…-11-07_nacht.md:22`) zum Faktum „40-Punkte-Audit" wurde —
ein klassischer Zahlen-Drift durch Abschrift.

**Empfehlung:** Bezeichnung im Dokument auf „36-Punkte-Audit" korrigieren. Solange das Original
fehlt, ist „40" nicht belegbar und jede Vollständigkeitsaussage darüber Spekulation.

### 1.2 Statusverteilung

| | Doku (07.11. abends) | **Ist (nachgemessen)** | Änderung |
|---|---|---|---|
| ✅ erledigt/belegt | 12 | **12** | — |
| 🟡 teilweise | 16 | **19** | +3 (P2, P7, P8) |
| 🔴 offen | 8 | **5** | −3 |
| ⚪ ungeprüft | 0 | 0 | — |
| **Summe** | **36** | **36** | |

Die drei Wechsel sind **Entlastungen**, keine Verschlechterungen: P2, P7 und P8 waren als
🔴 „offen" geführt, obwohl die Behauptung bei der Nachmessung ganz oder teilweise **falsch** ist.

### 1.3 Tabelle aller 36 Punkte

Status: ✅ belegt · 🟡 teilweise · 🔴 offen · ⚪ nicht messbar. „Drift" = Doku-Zahl/Zeile ≠ Messung.

| # | Behauptung in der Doku | Eigene Messung | Befehl | Status | Drift |
|---|---|---|---|---|---|
| **A1** | `wc -l main.py` → 11.291, −30 % | **11.252** | `wc -l main.py` | 🟡 | **ja**: 11.291 → 11.252 (und die Doku widerspricht sich selbst, s. Kennzahlen Z. 81) |
| **A2** | `ls archon/core/*.py` → 8, Routers → 20 | core **10**, routers **20** | `ls archon/core/*.py \| wc -l` | ✅ | **ja**: 8 → 10. Die 8 gelten für **`314ea093`** (dem im Dokumentenkopf genannten Commit, dort per `git ls-tree` bestätigt); neu sind **`archon/core/constants.py`** und **`archon/core/paths.py`** aus den A5-Etappen |
| **A3** | Middleware/Lifespan/Config weiter in `main.py` | `main.py` hält 1 Lifespan, 7 Middleware-/Event-Treffer, 347 `def`-Zeilen, 11.252 Z. | `grep -cE 'add_middleware\|@app\.(middleware\|on_event\|lifespan)' main.py` → 7 | 🟡 | nein (qualitativ, keine Zahl) |
| **A4** | „`main.py` importiert weiter 50+ Module" | **39** distinkte Module auf Modulebene; **224** Import-Anweisungen gesamt (inkl. funktionslokal) | `grep -oE '^(from\|import) [A-Za-z_0-9.]+' main.py \| awk '{print $2}' \| sort -u \| wc -l` | 🟡 | **ja**: „50+" → 39 (modulweit) / 224 Zeilen (andere Zählgrenze) |
| **A5** | `grep -cE '^[A-Z_][A-Z0-9_]* = '` → 25 | grep **25**, AST **31** (31 eindeutige Namen) | grep wie oben; AST-Scan über `Assign`+`AnnAssign` | 🟡 | nein (25 stimmt; AST-Differenz 6 = annotierte Globals, wie in `A5_INVENTUR.md` §0 begründet) |
| **A6** | `grep -c "asyncio.to_thread" main.py` → 15 | main.py **15**, repo-weit **31** (archon 14, backend 2) | `grep -rn asyncio.to_thread --include=*.py main.py archon backend utils \| wc -l` | 🟡 | **ja (Definitionsfrage)**: 15 gilt nur für `main.py`. Schon in der Gegenprobe des Handovers benannt, in `AUDIT_STATUS.md` weiter unscharf |
| **A7** | 0 `Depends()` in `main.py`, **1** in `archon/routers/system.py:123` | 0 in `main.py`, **1** in `archon/routers/system.py:`**`182`** | `grep -rn "Depends(" --include=*.py main.py archon` | 🟡 | **ja**: Zeile 123 → 182 |
| **A8** | „unverändert, 15+ Dateien" | **26** Dateien mit `os.environ`/`os.getenv` | `grep -rln "os.environ\|os.getenv" --include=*.py main.py archon backend utils \| wc -l` | 🔴 | **ja**: „15+" → 26 |
| **B1** | 4 Schreiber nutzen `update_mc` + Delta, `RuntimeError` statt Fallback | `update_mc` **26** Treffer in `orchestration.py`, `save_mc(` **1** (Docstring), `raise RuntimeError` **7**; Suite grün | `grep -c update_mc archon/core/orchestration.py` | ✅ | nein |
| **B2** | eine Klasse in `utils/reverse_proxy.py` | **1** `class` in 5.839 B | `grep -c "class " utils/reverse_proxy.py` | ✅ | nein |
| **B3** | Rest offen: `backend/hermes_updater.py:63` roher `AF_UNIX` | bestätigt, **Z. 63** | AST-Scan repo-weit, s. §4.3 | 🟡 | nein (58→63 war schon nachgezogen) |
| **B4** | `grep -c "safe_path" main.py` → 12 | **12** | wie angegeben | ✅ | nein |
| **B5** | 10 `execute(f"`; latenter Punkt `local_memory_bridge.py:454`, `{table}` in **Z. 459/471** | 10 `execute(f"` bestätigt; `{table}` steht an **5 Stellen: 438, 445, 463, 477** (nicht 459/471); Aufrufer `main.py:7794, 7986, 7987` (nicht 7831/8023/8024) | `grep -n "{table}" local_memory_bridge.py` | 🟡 | **ja**: Zeilen 459/471 → 463/477, plus **2 ungenannte Stellen** (438, 445) |
| **B6** | `except: pass` 0, nackte `except:` 2 | **0** / **2** | `grep -rn "except.*:.*pass" … \| wc -l`; `grep -rn "except:" … \| wc -l` | ✅ | nein |
| **B7** | „TTL-Caches eingeführt, keine einheitliche Strategie" | **8** `@ttl_cache`-Dekoratoren + **7** handgebaute Cache-Halter mit 7 verschiedenen TTLn (10 s…900 s) + 1 mtime-Invalidierung; **2** der teuersten Endpunkte (`/api/services`, `/api/roles`) haben **gar keinen** Cache | s. §3.5 | 🟡 | präzisiert, keine Zahl falsch |
| **B8** | genau **ein** blockierendes `httpx.Client` (`main.py:8942`) in `def send_prompt_to_agent` | **genau eins**, in `main.py:`**`8903`** | `grep -rn "httpx\.Client(" --include=*.py main.py archon backend utils` | ✅ | **ja**: 8942 → 8903 |
| **B9** | `grep -c "api_route(" main.py` → 50 | **50** | wie angegeben | 🔴 | nein |
| **B10** | 145 (main+archon+backend+utils), 195 mit scripts/tests | **145** / **195** (75+20+41+9 / +42+8) | `grep -rn "/opt/data" --include=*.py …` | 🟡 | nein |
| **S1** | = B3, Hauptpfad abgesichert, `hermes_updater` offen | bestätigt (§4.3) | AST-Scan | 🟡 | nein |
| **S2** | Path-Jail aktiv, 403 außerhalb | Code vorhanden (`utils/path_jail.py`), `safe_path` 12× in `main.py`; Live-403 nicht erneut geprüft (kein mutierender Request) | `sed -n 1,25p utils/path_jail.py` | ✅ (nur gelesen) | nein |
| **S3** | „117 Dateien auf 600" | **nicht reproduzierbar**: die Zahl hat keine Definition. Gemessen: `.env`, `.env.archon`, `.env.backup_pre_v02` = **600**; repo-weit **2.451** Dateien mit 600 (ohne `.venv`/`node_modules`). **Neu: Secrets mit Fremd-Leserecht** (§4.1) | `find . -type f -perm 600 … \| wc -l`; `find … -perm /o=r …` | 🟡 | **ja**: 117 nicht belegbar, dafür 5 konkrete Dateien mit 664/666/755 |
| **S4** | Rollenprüfung vorhanden („`main.py:7376`, `/api/auth/toggle`"), keine systematische Prüfung | `/api/auth/toggle` prüft `role != "admin"` in **`main.py:7298`**; **6** von **78** schreibenden Admin-nahen Routen prüfen eine Rolle — **72 nicht** (§4.2) | AST-Scan, s. §4.2 | 🟡 | **ja**: 7376 → 7298; und die Zahl 6/78 ist neu |
| **S5** | explizite Origin-Liste + LAN-Regex, kein `*` | bestätigt: 8 Origins, Regex ohne Wildcard, `allow_credentials=True` | `sed -n 100,118p main.py` | ✅ | nein |
| **S6** | alter Pfad 501, neuer Pfad isoliert; Handler `main.py:8372` | Handler jetzt **`main.py:8335`**, gibt 501 zurück (Code gelesen). **Live nicht erneut gefahren** (POST, wenn auch wirkungslos) | `grep -n "Sandbox deaktiviert" main.py` | ✅ (nur gelesen) | **ja**: 8372 → 8335 |
| **S7** | `safe_load` 22/74, `yaml.load(` 0 | **22** / **74** / **0** | wie angegeben | ✅ | nein |
| **S8** | Rate-Limit-Middleware, 10 Tests | `utils/rate_limit.py` 6.781 B, 4 Env-Schalter in `main.py:124-130`; `tests/test_rate_limit.py` läuft in der Suite grün | `ls -l utils/rate_limit.py`; `pytest tests/` | ✅ | nein |
| **S9** | „Rechte gehärtet, Klartext in `.env` bleibt" | `.env`, `.env.archon`, `.env.backup_pre_v02` = 600 ✅ — **aber 8 Snapshot-Kopien**, davon **1 × 666**, plus 2 OAuth-Token-Dateien 666 (§4.1) | `stat -c '%a %n' …` | 🟡 | **ja**: „gehärtet" gilt nur für die drei aktiven Dateien |
| **S10** | `utils/egress_guard.py` + 22 Tests | Datei 4.573 B vorhanden, `tests/test_egress_guard.py` grün in der Suite | `ls -l utils/egress_guard.py` | ✅ | nein |
| **P1** | 🔴 kein DB-Pooling, kein Messwert | **kein Pool** (0 Treffer für `ConnectionPool`/`check_same_thread`); Öffnen+PRAGMA+Query+Schließen **1,25 ms** Median / 1,66 ms p95 (§3.1) | s. §3.1 | 🔴 (bestätigt, aber **billig**) | Messwert ist neu |
| **P2** | 🔴 synchrone Docker-Calls | **alle 8** Docker-nahen Routen sind **sync `def`** → Threadpool, **kein** Event-Loop-Block. **Aber**: `/api/v1/container/metrics` = **1.006 ms** und liefert **falsche Daten** (§3.2) | s. §3.2 | 🟡 | **Behauptung teilweise falsch**, neuer Defekt gefunden |
| **P3** | 🔴 N+1 | N+1 **vorhanden** (11 SQL-Aufrufe in Schleifen), aber max. **8** Queries/Request; Wirkung **8–27 ms** (§3.3) | s. §3.3 | 🔴 (bestätigt, Wirkung klein) | Messwert neu |
| **P4** | 🔴 kein Request-Batching | **20** View-Fetches + ≥4 Nachlade-Requests beim Start; **411** `fetch(`-Aufrufe in 29 Dateien; 2 Poll-Schleifen à 10 s; `/api/hermes/profiles` = **2,6 MB** (§3.4) | s. §3.4 | 🔴 (bestätigt) | Messwert neu |
| **P5** | 🟡 redundante Vault-Reads / TTL-Cache | Vault-Cache 300 s ✅, aber die **teuersten** Reads sind ungecacht (§3.5) | s. §3.5 | 🟡 | präzisiert |
| **P6** | 🟡 Modell-Re-Instanziierung | **kein** SDK-Modell im Prozess (0× `ChatOpenAI`/`OpenAI`); aber **13** `httpx.AsyncClient`-Stellen, Neuerzeugung **10,8 ms** pro Request (§3.6) | s. §3.6 | 🟡 | umformuliert: Client-, nicht Modell-Re-Instanziierung |
| **P7** | 🔴 kein Streaming | **falsch**: **5** SSE-Endpunkte; `/api/v1/events/stream` live **200**, `transfer-encoding: chunked`, erstes Event sofort (§3.7) | s. §3.7 | 🟡 | **Behauptung widerlegt** |
| **P8** | 🔴 Cache-Keys ohne ETag | **statisch widerlegt**: `/`, `/static/index.html`, `/static/js/*.js` senden `etag` + `last-modified`, bedingte Anfrage → **304**. **Für JSON-APIs stimmt es**: keine `ETag`/`Last-Modified` (§3.8) | s. §3.8 | 🟡 | **Behauptung halb widerlegt** |
| **Kennzahlen** | Tests „243 passed, 8 skipped" | **258 passed, 8 skipped** (11,37 s) | `.venv/bin/python -m pytest tests/ -q --no-header -p no:cacheprovider` | — | **ja**: +15 Tests |
| **Kennzahlen** | Live-Pfade 585 / 861, Exit 0 | **585 / 861**, Exit 0 | `scripts/route_parity.py --check …` | ✅ | nein |
| **Kennzahlen** | 308 Decorator-Routen, 20 Router / 6 mit `configure()` | **308**, **20 / 6** | s. Doku | ✅ | nein |
| **Kennzahlen** | Tracebacks (5 min) 0 | **0** (10-min-Fenster) | `docker logs --since 10m ARCHON-OS \| grep -cE "Traceback\|NameError"` | ✅ | nein |

### 1.4 Die drei Zählfallen, konkret belegt

| Falle | Beispiel | Beweis |
|---|---|---|
| **Commit-Bindung** — die Zahl war für einen älteren Stand richtig | A2 = 8: gilt exakt für `314ea093` (der im Kopf genannte Commit), heute 10. A1 = 11.291: Stand vor der letzten Extraktions-Etappe, heute 11.252 | `git ls-tree --name-only 314ea093 archon/core/ \| wc -l` → 8; `wc -l main.py` → 11.252 |
| **grep vs. AST** — dasselbe Objekt, zwei Zahlen | A5: grep **25**, AST **31** (6 annotierte Globals fallen durch das Muster `^NAME = `) | `A5_INVENTUR.md` §0 listet die 6 Zeilen namentlich; AST-Scan reproduziert 31 |
| **fehlende Pfadgrenze** — die Zahl gilt nur für einen Teilbaum | A6 = 15 gilt nur für `main.py`, repo-weit **31**. A4 „50+" ist modulweit **39**, als Import-Zeilen **224**. B10 = 145 ohne / 195 mit `scripts`+`tests`. S3 „117" hat **gar keine** Grenze | §1.3, §3 |

**Bilanz Block 1:** 36 Punkte, davon **12 mit Zahlen- oder Zeilendrift** in der Punktetabelle
(Spalte „Drift" = `ja`; zwei weitere präzisiert). Die Drift-Liste in §2 führt **17** Abweichungen,
inklusive der drei Statuswechsel und der 40-vs-36-Frage. Kein einziger Punkt
musste von ✅ auf 🔴 zurückgestuft werden — die Substanz der Doku hält. Die Drifts sind
Fortschreibungsfehler (Zeilen nach Refactorings, Testzahl, Dateizahl), keine Falschaussagen
über den Zustand. Drei Punkte (P2, P7, P8) waren schlechter dokumentiert als die Realität.

---

## 2. Drift-Liste — „Doku sagt X / Realität ist Y / Beleg"

| # | Doku sagt | Realität | Beleg |
|---|---|---|---|
| 1 | `main.py` = 11.291 (Zeile A1) | **11.252** | `wc -l main.py` (die eigene Kennzahlen-Tabelle Z. 81 sagt bereits 11.252 — das Dokument widerspricht sich) |
| 2 | `archon/core/*.py` = 8 | **10** — die 8 stimmen für `314ea093`; seither **+`constants.py`**, **+`paths.py`** (A5) | `ls archon/core/*.py`; `git ls-tree --name-only 314ea093 archon/core/ \| wc -l` → 8 |
| 3 | `main.py` importiert „50+ Module" | **39** Module auf Modulebene (224 Import-Zeilen gesamt) | `grep -oE '^(from\|import) …' \| sort -u \| wc -l` |
| 4 | `Depends()` in `system.py:123` | **`:182`** | `grep -rn "Depends(" archon` |
| 5 | `httpx.Client` in `main.py:8942` | **`:8903`** | `grep -rn "httpx\.Client(" main.py` |
| 6 | Sandbox-Handler `main.py:8372` | **`:8335`** | `grep -n "Sandbox deaktiviert" main.py` |
| 7 | Rollenprüfung `main.py:7376` | **`:7298`** (Route beginnt 7295) | `grep -n "auth/toggle" -A 4 main.py` |
| 8 | `{table}`-Interpolation `local_memory_bridge.py:459/471` | **`:438, :445, :463, :477`** — zwei Stellen mehr als dokumentiert | `grep -n "{table}" local_memory_bridge.py` |
| 9 | Aufrufer `evict_stale_memories` `main.py:7831/8023/8024` | **`:7794, :7986, :7987`** | `grep -rn "evict_stale_memories(" main.py` |
| 10 | „15+ Dateien" mit verstreuter Config (A8) | **26** Dateien | `grep -rln "os.environ\|os.getenv" … \| wc -l` |
| 11 | Tests „243 passed, 8 skipped" | **258 passed, 8 skipped** | `pytest tests/ -q` |
| 12 | „117 Dateien auf 600" (S3) | **nicht reproduzierbar** (keine Definition der Grundgesamtheit); repo-weit 2.451 Dateien mit 600, die drei aktiven `.env*` sind 600 ✅ | `find . -type f -perm 600 … \| wc -l` |
| 13 | **P7**: „kein Streaming" | **5 SSE-Endpunkte, live chunked 200** | §3.7 |
| 14 | **P8**: „Cache-Keys ohne ETag" | **statisch: ETag + Last-Modified + 304**; nur JSON-APIs ohne | §3.8 |
| 15 | **P2**: „synchrone Docker-Calls im async-Kontext" | **kein** Docker-Call in einem `async def`-Handler; alle 8 sind sync → Threadpool. Dafür 1 s Verbrennung + Falschdaten bei `metrics` | §3.2 |
| 16 | „40-Punkte-Audit" | **36 Punkte**, seit der ersten Fassung | §1.1 |
| 17 | **A6** = 15 | 15 gilt nur für `main.py`; repo-weit **31** | §1.3 |

---

## 3. Block 2 — P1–P8, erstmals gemessen (gegen die laufende Instanz)

Alle Messungen sequenziell, GET, mit Service-Token, ohne Schreibzugriff. Stichprobe n=10 bzw. 15,
p95 = 95-%-Perzentil der Stichprobe (Index `round(0.95·(n−1))`), nicht interpoliert.

### 3.1 P1 — Kein DB-Pooling: **belegt, aber wirtschaftlich irrelevant**

**Code-Beleg (Verbindungsstrategie):**
* `archon/core/state_db.py:31` — `conn = sqlite3.connect(STATE_DB_PATH, timeout=15.0, factory=ClosingConnection)`; **pro Aufruf eine neue Verbindung**, geschlossen von `ClosingConnection.__exit__` (Z. 13-19). Kein Pool: `grep -rn "ConnectionPool\|sqlite3.*pool"` → **0** Treffer.
* 149 `sqlite3.connect`-Stellen repo-weit; in `main.py` 6 (Z. 1597, 3393, 5072, 8370, 9444, 9873), im Router-Pfad `archon/routers/hermes_profiles.py:372, 452`.
* DB: `~/.hermes/state.db`, 19,24 MB, `journal_mode=wal`, `page_count=4698`.

**Messung (`200` Öffnungen, read-only):**

```
connect+close (ohne Query)        : median 0,051 ms
connect+PRAGMA+SELECT+close       : median 1,250 ms   p95 1,657 ms   min 1,070   max 2,788
```

**Urteil: belegt vorhanden, aber entlastet.** 1,25 ms pro DB-Request sind kein Flaschenhals;
WAL macht den Verbindungsaufbau fast kostenlos. Der Grund, P1 *nicht* als 🔴 zu führen, ist
messbar: Ein Pool würde messbar **≈1 ms/Request** sparen — bei den gemessenen HTTP-Latenzen
(§3.4: 58 ms, 64 ms, 82 ms) ist das < 2 %. **Die echten Kosten liegen woanders: JSON-Parsing
2,6-MB-großer Dateien und 2,6-MB-Antworten.**

**Wichtiger Nebenfund:** `archon/core/state_db.py` öffnet die Verbindung mit
`check_same_thread=True` (Default). Das ist die dokumentierte Ursache dafür, dass A7/DI nicht
weiter ausgerollt wurde — und es bleibt die Sperre für jede Connection-Pool-Strategie.

### 3.2 P2 — Synchrone Docker-Calls: **Behauptung falsch, dafür ein harter Defekt**

**Code-Beleg (AST über `main.py`, `archon/routers/*.py`):**

| Datei:Zeile | Route | Handler-Typ | Docker-Aufruf |
|---|---|---|---|
| `main.py:1033` | `GET /api/services` (u. `/api/v1/services`) | **sync `def`** | `get_docker_containers_from_socket()` |
| `main.py:8530` | `GET /api/v1/container/logs` | sync `def` | `docker_socket_request` |
| `main.py:8559` | `GET /api/v1/container/all-logs` | sync `def` | `docker_socket_request` |
| `main.py:8589` | `GET /api/v1/hermes/profile-logs` | sync `def` | `docker_socket_request` |
| `main.py:8690` | `GET /api/v1/container/metrics` | sync `def` | `docker_socket_request` |
| `main.py:8734` | `GET /api/v1/container/files` | sync `def` | `docker_socket_request` |
| `main.py:8781` | `GET /api/v1/container/file/content` | sync `def` | `docker_socket_request` |
| `archon/routers/governance.py:126` | `POST /api/governance/promptfoo/run-eval` | sync `def` | `docker_socket_request` |

**Kein** Docker-Aufruf steht in einem `async def`-Handler (eigener AST-Scan: 0 Treffer).
Damit blockiert keiner davon den Event-Loop — FastAPI führt sync-Handler im Threadpool aus.
Die Audit-Behauptung „synchrone Docker-Calls im async-Kontext" ist für den HTTP-Pfad **widerlegt**.

**Live-Latenz (n=15):**

| Route | Median | p95 |
|---|---|---|
| `/api/v1/container/metrics?container_name=ARCHON-OS` | **1.006,3 ms** | 1.009,9 ms |
| `/api/v1/container/files?container_name=ARCHON-OS` | 118,8 ms | 163,0 ms |
| `/api/v1/container/all-logs?tail=20` | 14,7 ms | 43,8 ms |
| `/api/v1/container/logs?…&tail=250` | 7,8 ms | 14,2 ms |
| `/api/services` | 6,1 ms | 11,5 ms (p95 231,6 ms bei n=10) |
| `/api/v1/services` | 4,9 ms | 7,4 ms |

**Der Defekt hinter den 1.006 ms** — reproduzierbar, dreimal bestätigt:

```bash
curl -s -w " |%{time_total}s\n" -H "X-Archon-Service-Token: $T" \
  "http://127.0.0.1:8501/api/v1/container/metrics?container_name=ARCHON-OS"
# {"status":"Stopped","cpu":0.0,"memory_mb":0.0,"memory_pct":0.0} |1.007757s
# {"status":"Stopped",…} |1.007935s
# {"status":"Stopped",…} |1.004830s
```

Ursache, aus dem Code: `main.py:8479` `def docker_socket_request(…, timeout: float = 1.0)` reicht
1,0 s an `DockerClient._request_raw` weiter (`utils/docker_client.py:117`), dort
`sock.settimeout(timeout)` (Z. 135) und `_read_response` bricht bei `socket.timeout` ab (Z. 157-159)
und liefert das bis dahin Gelesene. `/containers/{name}/stats?stream=false` braucht aber
**~1–2 s**, bis Docker den CPU-Delta berechnet — das habe ich am Daemon selbst gemessen:

```
docker stats --no-stream ARCHON-OS   →  real 1,037 s   (zweite Messung: 2,00 s)
```

Also: die Antwort wird **immer** abgeschnitten, der Handler sieht `falsy` Body und gibt
`{"status": "Stopped", cpu 0.0, memory_mb 0.0}` zurück. **Das UI zeigt jeden Container als
„gestoppt, 0 % CPU", und jeder Aufruf kostet garantiert eine Sekunde Threadpool-Zeit.**
Das ist kein Performance-Thema mehr, sondern ein Datenrichtigkeits-Fehler.

**Urteil: teils entlastet (kein async-Block), teils schlimmer als gedacht (Falschdaten + 1 s).**

### 3.3 P3 — N+1: **vorhanden, aber billig**

**Statisch (AST: `execute`/`executemany`/`connect` innerhalb von `for`/`while`):** 11 Stellen

| Datei:Zeile | Route | Muster |
|---|---|---|
| `main.py:1516` (`Schleife@1593`) | `POST /api/v1/watchdog/dispatch_action` | `sqlite3.connect` **pro Iteration** |
| `main.py:5037` (`@5068`) | `GET /api/guardian/stats` | `connect`+`execute` pro Iteration |
| `backend/operations_api.py:627` (`@677, @692, @724`) | `POST /kanban/bulk` | 3 Query-Schleifen |
| `backend/operations_api.py:779` (`@796`) | `POST /kanban/bulk/undo` | 1 |
| `backend/operations_api.py:1058` (`@1079`) | `POST /kanban/reset-zombies` | 1 |
| `backend/operations_api.py:1733` (`@1739, @1743, @1757`) | `GET /api/operations/kanban/stats` | 3 |
| `backend/operations_api.py:3811` (`@3824`) | `GET /api/operations/comm-feed/stream` | 1 |

**Queries pro Request (Summe im Handler-Rumpf, statisch):** Maximum **8**
(`/api/hermes/memory/purge`, 7 `execute` + 1 `connect`), dann **7** (`/kanban/bulk`), **5**
(`/api/chat/sessions`: 2 Verbindungen — Profil-DB `telegram_bot` + Root-DB — und 2 Queries),
**4** (`/kanban/reset-zombies`, `…/quality-review`, `…/approve`, `…/tasks/{id}`, `/kanban/stats`).

**Live (n=15, soweit GET und ohne Parameter):**

| Route | Median | p95 | Queries (statisch) |
|---|---|---|---|
| `/api/guardian/stats` | 27,0 ms | 40,9 ms | 2 (in Schleife) |
| `/api/operations/kanban/stats` | 8,4 ms | 12,6 ms | 4 (3 in Schleifen) |
| `/api/v1/memory/stats` | 82,0 ms | 121,8 ms | — (anderer Pfad) |
| `/api/operations/comm-feed` | 11,8 ms | 19,9 ms | 2 |
| `/api/kanban` | 6,7 ms | 8,3 ms | 3 |

**Urteil: belegt, Wirkung klein.** Lokales SQLite auf WAL mit ≤8 Queries liegt im
einstelligen bis niedrigen zweistelligen Millisekundenbereich. N+1 ist hier ein
**Struktur-, kein Latenzproblem** — es skaliert mit der Datenmenge (Kanban-Tasks), nicht mit der
Nutzerzahl. Ehrlicher Befund: **kein Handlungsbedarf aus Performance-Sicht**, aber
`main.py:1516` und `main.py:5037` öffnen die DB **pro Schleifendurchlauf** — das ist der Punkt,
der unter Last kippt.

### 3.4 P4 — Kein Request-Batching: **belegt, mit Zahl**

**Code:** `static/index.html:2668` `initArchonApp()` — **20** `fetch()`-Aufrufe für
HTML-Partials in einem `Promise.all` (parallel, gut), danach **4** Nachlade-Requests
(`loadHermesProfilesView`, `loadRolesFromServer`, `loadModelsFromServer`, `loadAgentsFromServer`,
Z. 2721-2727), danach **3** Poll-Schleifen: `updateStats` (`/api/v1/telemetry/dashboard`, 10 s),
`pollWatchdogAlarms` (`/api/v1/watchdog/alarms`, 10 s), `startLogPolling`.
`/api/hermes/profiles/{id}/status` wird zusätzlich pro Klick einzeln gerufen.
`fetch(`-Aufrufe gesamt im aktiven Frontend: **411** in **29** Dateien.

**Messung Startphase (3 Läufe, parallel wie im Code):**

```
20 View-Partials parallel: 195 ms / 128 ms / 208 ms total, 20/20 HTTP 200, 1,18 MB
```

**Messung Nachlade-/Poll-Endpunkte (n=10 bzw. 15):**

| Route | Median | p95 | Bytes |
|---|---|---|---|
| `/api/hermes/profiles` | **58,3 ms** | **1.103,8 ms** | **2.608.379** (2,6 MB) |
| `/api/roles` | 64,2 ms | 84,3 ms | 2,6 MB (roles.json = 2.630.812 B) |
| `/api/v1/telemetry/dashboard` | 7,0 ms | 352,3 ms | 98 |
| `/api/agents` | 4,2 ms | 9,7 ms | 978 |
| `/api/models` | 3,2 ms | 5,5 ms | 87 |
| `/api/v1/watchdog/alarms` | 4,8 ms | 7,6 ms | 13 |
| `/api/v1/container/logs?…&tail=250` | 10,5 ms | 18,7 ms | 21.018 |

**Urteil: belegt.** Zwei unabhängige Ursachen:
1. **Fragmentierung:** 24 Requests für einen Seitenaufbau, davon 20 für statische Partials, die
   auch ein einziges Bundle sein könnten.
2. **Payload statt Roundtrip:** `/api/hermes/profiles` liefert **2,6 MB** pro Aufruf
   (p95 1,1 s) und `/api/roles` **2,6 MB**, jeweils ohne Feldauswahl. Der Roundtrip ist nicht das
   Problem — die Nutzlast ist es. `json.dumps` allein kostet 14,9 ms (2,63 MB, gemessen §3.6);
   dazu kommen 2,6 MB über Loopback bei jedem Poll.

### 3.5 P5 — TTL-Caches: Bestand, Trefferquote, Invalidierung

**Dekorierte Caches (`@ttl_cache`, `archon/core/cache.py`) — 8 Stellen:**

| Datei:Zeile | TTL |
|---|---|
| `main.py:928` | 10 s |
| `main.py:1938` (`/api/v1/brain/galaxy-data`) | 60 s |
| `main.py:2224` | 60 s |
| `archon/routers/system.py:430` | 30 s |
| `backend/fleet_self_healing.py:74` | 30 s |
| `backend/system_updater.py:197` | 120 s |
| `backend/system_updater.py:354` | 60 s |
| `archon/core/cache.py:9` (Vorlage) | 30 s |

**Handgebaute Cache-Halter — 7 mit TTL:**

| Cache | TTL | Invalidierung (Datei:Zeile) |
|---|---|---|
| `_HERMES_PROFILES_CACHE` | 300 s **+ mtime-Vergleich** (gut) | `archon/core/profiles.py:79` `invalidate_hermes_profiles_cache()`; aufgerufen aus `main.py:2790, 6823, 7618, 7646, 7703, 7731` |
| `_HERMES_SKILLS_CACHE` | 300 s (`archon/routers/skills.py:54`, Prüfung Z. 273) | **keine** Invalidierungsstelle gefunden |
| `_VAULT_FILES_CACHE` | 300 s (`main.py:8347`) | `main.py:8317, 8330` (`["ts"] = 0.0`) |
| `_LIVE_TELEMETRY_CACHE` / `_TELEMETRY_CACHE` | 10 s (`main.py:5043`) | `main.py:5043` (Zeitstempel-Vergleich) |
| `_MC_STATE_CACHE` | 3 s (`archon/core/mission_control.py:37`) | Zeitstempel |
| `_SERVICE_TOKEN_CACHE` | 30 s (`main.py:157`) | Zeitstempel |
| `_PAPERCLIP_AGENTS_CACHE` | 300 s | `main.py:7526` `invalidate_paperclip_agents_cache()` |
| `hermes_updater` GitHub-Cache | 900 s (`backend/hermes_updater.py:44`) | `_cache_lock_time` |

**Trefferquote:** *nicht messbar ohne Instrumentierung* (kein Hit/Miss-Zähler im Code). Abschätzung
aus TTL gegen Poll-Intervall — als **Schätzung gekennzeichnet**: `updateStats` pollt alle 10 s
gegen einen 10-s-Cache ⇒ Trefferquote ≈ 0 % (der Cache läuft genau dann ab, wenn der nächste Poll
kommt). `/api/services` und `/api/roles` haben **keinen** Cache ⇒ 0 % per Konstruktion.

**Urteil: 🟡 bestätigt, mit Präzisierung.** Die Strategie ist uneinheitlich (7 TTLn von 3 s bis
900 s, zwei verschiedene Bauweisen), aber nicht wirkungslos. **Der eigentliche Befund ist die
Lücke:** ausgerechnet die zwei teuersten Antworten (2,6 MB je `/api/roles`, 2,6 MB je
`/api/hermes/profiles` — letzteres hat einen Cache, `/api/roles` nicht) sind ungecacht, während
98-Byte-Antworten einen 10-s-Cache haben.

### 3.6 P6 — Modell-/Client-Re-Instanziierung: **Client ja, Modell nein**

**Code:** Es gibt **kein** In-Process-Modell: `grep -rn "ChatOpenAI(\|OpenAI(\|AsyncOpenAI(\|GenerativeModel("` → **0 Treffer**. Alle LLM-Aufrufe gehen als HTTP an `openrouter.ai`/`omniroute` (`main.py:5003`, `main.py:8893`).

**Aber 13 `httpx.AsyncClient(`-Stellen**, mehrere davon **pro Request** neu erzeugt:
`main.py:539, 5002, 9206`, `archon/routers/system.py:122`, `backend/voice_pipeline.py:59, 78, 105, 159, 187`,
`backend/agent_router.py:137`, `utils/notebook_engine.py:415`, `utils/reverse_proxy.py:34`.
Ein geteilter Pool existiert nur für die Proxy-Pfade (`_PROXY_HTTP_CLIENTS`, `main.py:10330`).

**Messung (in-process, Host-Python, ohne Netz):**

```
httpx.AsyncClient() erzeugen + schließen : median 10,839 ms   (n=200)
httpx.Client()       erzeugen + schließen : median 11,523 ms
json.dumps(agent_profiles.json, 2,63 MB)  : median 14,9 ms  → 2,61 MB Wire
json.dumps(roles.json, 2,63 MB)           : median 14,8 ms  → 2,61 MB Wire
```

**Urteil: 🟡, umformuliert.** „Modell-Re-Instanziierung" trifft nicht zu — es gibt keine
Modellobjekte. Das reale Äquivalent ist die **Transport-Re-Instanziierung: ~10,8 ms pro
LLM-Aufruf** nur für den Client (SSL-Kontext, Pool-Aufbau), plus 14,9 ms für die 2,6-MB-
Serialisierung in `/api/hermes/profiles`. Bei einem einzelnen Chat-Aufruf sind 11 ms neben
Sekunden Modell-Latenz irrelevant; bei 10 parallelen Aufrufen sind es 108 ms reine
Client-Verwaltung und 10 zusätzliche Verbindungen zum Provider.

### 3.7 P7 — Kein Streaming: **widerlegt, live belegt**

**Code:** 5 echte SSE-Endpunkte:

| Datei:Zeile | Route/Verwendung |
|---|---|
| `main.py:9959` | `GET /api/v1/events/stream` (`sse_events_stream`, `StreamingResponse` Z. 9959, Heartbeat 20 s) |
| `main.py:4723` | `mission_event_stream()` im Chat-Pfad |
| `main.py:4966` | `chat_event_stream()` |
| `archon/routers/boardroom.py:444` | Boardroom-Stream |
| `backend/operations_api.py:2817/2857`, `3816/3880` | Comm-Feed-Streams |

**Live-Beweis (read-only, 3 s Timeout):**

```bash
timeout 3 curl -sN -H "X-Archon-Service-Token: $T" http://127.0.0.1:8501/api/v1/events/stream | head -3
# data: {"type": "connected", "timestamp": 1794066105.2247386}
```

```
HTTP/1.1 200 OK
cache-control: no-cache, no-transform
x-accel-buffering: no
content-type: text/event-stream; charset=utf-8
transfer-encoding: chunked
```

**Urteil: nicht messbar ist hier nichts — die Behauptung ist falsch.** Streaming existiert und
funktioniert. Was **fehlt**, ist Streaming für die großen JSON-Antworten (2,6-MB-Payloads, §3.4)
und für Upload-/Report-Pfade; das ist aber ein anderer Punkt als „kein Streaming".

### 3.8 P8 — Cache-Keys ohne ETag: **halb widerlegt**

```bash
curl -sI http://127.0.0.1:8501/                     # etag "6a71793…" + last-modified + no-cache
curl -sI http://127.0.0.1:8501/static/js/chat_engine.js  # etag "2babf9b…" + last-modified
curl -s -o /dev/null -w "%{http_code}" -H "If-None-Match: \"2babf9b435fe81cdc27599ad9ca359b0\"" \
     http://127.0.0.1:8501/static/js/chat_engine.js   # → 304
```

| Route | ETag | Last-Modified | 304 bei `If-None-Match` |
|---|---|---|---|
| `/` | ✅ | ✅ | (nicht separat geprüft) |
| `/static/index.html` | ✅ | ✅ | — |
| `/static/js/chat_engine.js` | ✅ | ✅ | **✅ 304** |
| `/health` | **❌** | ❌ | — |
| `/api/roles` | **❌** | ❌ | — |

**Urteil:** Für statische Auslieferung **widerlegt** (Starlette `StaticFiles` liefert ETag,
`add_no_cache_for_avatars` ergänzt `Cache-Control`). Für JSON-APIs **bestätigt**: keine
`ETag`/`Last-Modified`, also kein 304 für die 2,6-MB-Antworten — genau dort, wo es zählen würde
(§3.4). Halb richtig, halb falsch; Status 🟡.

---

## 4. Block 3 — Sicherheit

### 4.1 S9 — Telegram-Token im Klartext

Token **niemals ausgegeben**; Maskierung auf die ersten Zeichen des Werts:

| Fundstelle | Rechte | Inhalt (maskiert) |
|---|---|---|
| `.env` | **600** micha:micha | `TELEGRAM_BOT_TOKEN=88…` (Wert maskiert) |
| `.env.archon` | **600** | dito |
| `.env.backup_pre_v02` | **600** | dito |
| `docker-compose.yml` | 644 | `- TELEGRAM_BOT_TOKEN=${TE…` (Env-Referenz, kein Wert) |
| `data/snapshots/pre_update_2026110{3,4}_*/.env` (7 Dateien) | 600 | Kopien des Tokens |
| **`data/snapshots/manual_20261031_154716/.env`** | **666** ⚠️ | Kopie des Tokens, **weltlesbar** |

Weitere Secrets mit Fremd-Leserecht (nicht Telegram, aber gleiche Klasse):
`gmail_token.json` **666**, `google_token.json` **666**, `credentials.json` **755**,
`paperclip/docker/.env` **664**, `frontend/.env.local` (755, untracked Fremdbaum).

**In Logs?** Nein — Stichprobe `omniroute_data/data/call_logs/*.json`: der Treffer ist der
Prompt-Text `TELEGRAM_BOT_TOKEN\" with your`, kein Tokenwert. `docker logs` wurde nicht nach dem
Wert durchsucht (Grund: jeder Treffer hätte den Wert in meine Ausgabe geholt).

**Über einen Endpunkt lesbar?** Nur Code-Prüfung, kein Abruf mit Ausgabe:
`main.py:5888-5894` liest `TELEGRAM_BOT_TOKEN=` aus `.env` und gibt ihn **maskiert** zurück
(`utils.secret_files.mask_secret`, Z. 5893-5894). `main.py:6078-6083` schreibt zurück und
erkennt den maskierten Platzhalter (`"•" in _new`, Z. 6080) als „unverändert".
`GET /api/hermes/raw_config` maskiert per `mask_yaml_secrets` (`main.py:6854-6866`).
**Kein Endpunkt liefert den Rohwert.**

**Urteil:** Die Doku-Aussage „Rechte gehärtet" gilt **nur für die drei aktiven Dateien**. Neu und
schwerwiegender als dokumentiert: 8 Snapshot-Kopien, davon eine weltlesbar (666) — seit
31.10.2026. **Konsequenz: Token rotieren**, nicht nur `chmod`.

### 4.2 S4 — Schwache Admin-Auth: Rollenprüfung nur auf 6 von 78 Routen

**Basisschutz (gut):** `auth.enabled = true`, `mode = multi_user` — belegt in
`agent_workspace/settings.json` **und** `settings.json` (Root). Der globale
`auth_gate`-Middleware (`main.py:181-225`) liefert **401** für `/api/*` ohne gültige Session
(live bestätigt: `curl /api/roles` ohne Token → **401**). Also: **Anonyme kommen nicht rein.**

**Lücke: Authentifizierung ≠ Autorisierung.** Der Gate prüft nur „eingeloggt", nicht „Admin".

| Kategorie | Anzahl |
|---|---|
| Schreib-Routen (POST/PUT/PATCH/DELETE) mit Admin-/System-Bezug | **78** |
| davon mit Rollen-/Token-Prüfung **im Handler** | **6** |
| davon **ohne** jede Prüfung (nur globales Session-Gate) | **72** |

**Die 6 geprüften** (alle mit `get_current_user_from_request(...).get("role") != "admin"` → 403):

| Datei:Zeile | Route |
|---|---|
| `main.py:7296` | `POST /api/auth/toggle` |
| `main.py:7369` | `POST /api/auth/users` |
| `main.py:7386` | `PATCH /api/auth/users/{user_id}` |
| `main.py:7403` | `POST /api/auth/change-password` |
| `main.py:7436` | `DELETE /api/auth/users/{user_id}` |
| `main.py:8143` | `POST /api/v1/hermes/update/apply` |

**Die schwerwiegendsten der 72 ohne Prüfung** (jeder eingeloggte Nutzer, auch ein Viewer, darf):

| Datei:Zeile | Route | Wirkung |
|---|---|---|
| `main.py:8949` | `POST /api/v1/container/exec` | **Befehl in beliebigem Container** |
| `main.py:1037/1043` | `POST /api/docker/start` · `/api/docker/stop` | Container-Lebenszyklus |
| `main.py:10784` | `POST /api/sandbox/execute` | Codeausführung |
| `main.py:10556` | `POST /api/snapshots/{snapshot_id}/restore` | **Restore über alten Stand** |
| `archon/routers/system.py:298/307/323/332` | `POST /api/v1/system/update/{push,apply,rollback,backup}` | **Update/Rollback des Systems** |
| `main.py:624` | `POST /api/roles` | Rollen/Modelle überschreiben |
| `main.py:7749, 6414, 3362, 6870` | `POST /api/settings`, `/api/hermes/settings`, `/api/hermes/config`, `/api/hermes/raw_config` | gesamte Konfiguration |
| `main.py:1395-1462` | `POST /api/v1/gateway/{start,stop,config,autostart,stop-all}` | Gateway-Steuerung (Telegram-Konflikt!) |
| `main.py:1516/1629` | `POST /api/v1/watchdog/{dispatch_action,run_now}` | Kill-Switch-Aktionen |
| `archon/routers/plugins.py:34/51/76` | `POST /api/v1/plugins/{id}/{toggle,reload,config}` | Plugin-Code laden |
| `main.py:8525/9162/9171` | `POST /api/v1/container/{settings,action,inject_config}` | Container-Konfiguration |

**Urteil: 🟡 → belegt, und zwar schlechter als „fehlendes MFA".** MFA ist nicht das Problem;
es gibt **kein Rollenkonzept** außer auf den sechs Auth-Verwaltungsrouten. Ein `viewer`-Konto
darf heute den Docker-Socket bedienen. Kein Live-Request gegen diese Routen abgesetzt
(Auftrag: keine mutierenden Admin-Aufrufe) — der Beleg ist rein statisch, aber vollständig
(alle 78 Zeilen habe ich einzeln aus dem AST gezogen).

### 4.3 B3 / S1 — Docker-Socket: Rest-Befund bestätigt, vollständige Liste

**Repo-weiter AST-Scan über `main.py`, `archon/**`, `backend/*.py`, `utils/*.py`** auf
`socket.socket`, `AF_UNIX`, `AF_INET`, `SOCK_STREAM`:

| Datei:Zeile | Aufruf | Einordnung |
|---|---|---|
| **`backend/hermes_updater.py:63`** | `socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)` | **offen** — `DockerSocketClient`, kein Allowlist-Check, kein Namens-Regex; im Live-Pfad von `get_installed_hermes_info()` und `recreate_container_with_new_image()` |
| `utils/docker_client.py:131` | `socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)` | **der Guard selbst** (hinter `_check_allowed`, Z. 96-101) |
| `backend/privacy_router.py:103` | `socket.socket(socket.AF_INET, socket.SOCK_STREAM)` | andere Risikoklasse: TCP-Latenzprobe zu Provider-URLs, **kein** Docker-Socket |
| `backend/privacy_router.py:152` | dito | dito |

**Ergebnis: genau zwei `AF_UNIX`-Stellen im Repo.** Eine ist der bewachte Client, eine ist der
unbewachte in `hermes_updater.py`. Die Doku-Aussage ist damit **exakt bestätigt** und die
Vollständigkeit ist jetzt belegt (nicht nur behauptet): es gibt **keine weitere** rohe
Unix-Socket-Stelle — auch nicht in `scripts/`, `tests/` oder den Archiven (dort nur Textstellen).
Der `main.py`-Hauptpfad geht ausschließlich über `utils.docker_client` (Fassade
`docker_socket_request`, `main.py:8479`) oder über `http://docker-socket-proxy:2375`
(`main.py:8420`, `archon/routers/system.py:141`, `backend/post_task_pipeline.py:522, 526`).

---

## 5. Block 4 — Erreichbarkeit: tote UI-Pfade (systematisch)

**Aktiver Baum** (wie ausgeliefert): `static/index.html` (834.099 B), `static/js/*.js` (27 Dateien),
`static/erp_studio.js`, `static/mobile.html`, `static/views/*.html` (19 Dateien) = **50 Quellen,
4,12 Mio. Zeichen**. **Nicht** gezählt: `archive/`, `frontend/`, `frontend_recovered_*`,
`static/static/**` (Duplikatbaum), `static/hermes-webui/**`, `vendor/`.

### 5.1 Tote JS-Funktionen: 69 von 1.628 Definitionen

Methode: alle `function name(`/`async function name(` plus `const name = (…) =>`-Zuweisungen;
Referenzzählung in einem Tokenizer-Durchlauf über alle 50 Quellen; „tot" = **keine Referenz
außerhalb der Definitionszeile** (Funktionen, die nur als Callback übergeben werden, haben eine
Referenz und sind damit **nicht** in der Liste).

Auszug, nach Relevanz (vollständige Liste: 69 Einträge, davon 2 Artefakte aus der minifizierten
`tailwind.cdn.js`, die ich als Messrauschen werte → **67 echte**):

| Funktion | Datei:Zeile | Einordnung |
|---|---|---|
| `triggerHermesCoreRestart` | `static/index.html:8182` | **bekannter Fall** — ruft `POST /api/system/hermes/restart` (Z. 8196) und greift auf `#btn-restart-hermes-core` (Z. 8190) zu. Beides unerreichbar |
| `refreshLogStreamSourceList`, `initLogStreamStickyScroll`, `askAdminAgentAboutLog`, `onLogStreamTailChange` | `index.html:6187, 6283, 6431, 6493` | ganzer Log-Stream-Block ohne Aufrufer |
| `setBrainSubTab`, `handleCreateNotebook`, `handleUploadSourceToNotebook`, `openAttachVaultModal`, `submitNotebookQuery` | `index.html:7015, 7121, 7213, 7255, 7370` | komplette Notebook-/Brain-Funktionsgruppe |
| `filterGalaxyGroup`, `toggleGalaxyAutoRotate`, `resetGalaxyCamera`, `searchGalaxyNodes`, `fallbackQuartzIframe`, `openBrainThemeStudioModal` | `index.html:7541-7704` | Galaxy-Controls |
| `toggleHealthPopover`, `openShowroomHtmlModal`, `exportCurrentFileToDesktop`, `removeCustomLogo` | `index.html:8097, 5607, 5787, 2657` | Einzelaktionen |
| `loadKanbanFromServer`, `createNewRoleInSettings`, `deleteSelectedRoleFromSettings`, `saveRoleSettingsChanges`, `filterRoleDropdownByCategory`, `toggleJevFromMasterChat` | `js/wissensbibliothek.js:1702, 1479, 1492, 1503, 1414, 1164` | Rollen-/Kanban-Pflege |
| `addNewAgent`, `deleteAgent`, `submitCreateAgent`, `openCreatePresetModal`, `renderBoardroomThread`, `handleDockerContainerSelectChange` | `js/skill_markt.js:524, 540, 3106, 470, 2646, 3083` | Agenten-Erstellung |
| `resumeBotTakeover`, `solveSimulatedCaptcha`, `handleBotScreenClick`, `initCommRealtimeStream` | `js/operations_kanban.js:3317, 3332, 3343, 3357` | Bot-Takeover (kein Aufrufer) |
| `openSoulModal`, `closeSoulModal`, `saveSoulMarkdown`, `togglePinAgentToCurrentTask`, `switchPersonalakteTab`, `openDirectChatForCurrentProfile` | `js/agent_profiles.js:2311-2328` | **zweite Definition** derselben Namen — `openSoulModal` existiert zusätzlich in `index.html:7633`; `js/agent_profiles.js` wird später geladen und **überschreibt** die Inline-Definition |
| `initMissionControlSSE` | `js/mission_control_cockpit.js:39` | SSE-Init ohne Aufrufer |
| `selectConnectionMode`, `testRemoteConnection`, `toggleKeyVisibility` | `js/wissensbibliothek.js:676, 692, 913` | Verbindungs-Setup |

Stichproben-Verifikation per `grep`: `triggerHermesCoreRestart` (nur Definition + eigener
`getElementById`), `togglePinAgentToCurrentTask` (nur Definition), `openSoulModal` (Definition in
zwei Dateien, Aufruf nur im **Duplikatbaum** `static/static/index.html:2197`).

**Nebenbefund:** `openSoulModal` ist **doppelt definiert** (`index.html:7633` **und**
`js/agent_profiles.js:2311`) — die zweite gewinnt, die Inline-Version ist toter Code. Dieselbe
Klasse wie `ROLES_FILE`/`SERVICES_FILE` in `main.py` (Handover-Fehlerklasse a).

### 5.2 Buttons ohne Ziel: 175 von 1.640 `getElementById`-Zielen ohne DOM-Element

| Kategorie | Anzahl |
|---|---|
| `getElementById("…")`-Ziele im aktiven Baum | **1.640** |
| davon ohne `id="…"` im aktiven Baum | **175** |
| davon nur im **Duplikatbaum** (`static/static/**`) definiert | 9 |
| davon **nirgends** im Repo definiert → echt tot | **166** |

Die Klasse, zu der `btn-restart-hermes-core` gehört, umfasst also **166 Zugriffe**.
Belegte Beispiele (mit Folgefehler):

| ID | Datei:Zeile des Zugriffs | Folge |
|---|---|---|
| `btn-restart-hermes-core` | `index.html:8190` | `null.src`/`null.onclick` → TypeError, Funktion tot |
| **`view-system-settings`** | `index.html:8177` | **die View heißt `view-*-mount`** — 27 View-Container existieren, dieser nicht |
| `logstream-tail-select`, `-level-select`, `-metric-cpu`, `-metric-ram`, `-autoscroll-btn`, `-playpause-icon`, `-live-badge`, `-metrics-pill`, `-active-subtitle` | `index.html:6488, 6494, 6155-6157, 6441-6458, 6109` | ganzer Log-Stream-Header ohne Elemente |
| `erp-f-id`, `erp-f-display-name`, `erp-f-legal-form`, `erp-f-street`, `erp-f-notes`, … (≈25 IDs) | `js/erp_studio.js:1000-1063` | `createNewErpAddress()` setzt `.value` auf `null` → **TypeError bei „Neue Firma"**; in `views/view_operations_erp.html` existiert keine dieser IDs |
| `erp-flag-customer`, `erp-flag-supplier` | `js/erp_studio.js:866, 868` | dito |
| `new-agent-role`, `new-agent-id`, `new-agent-name`, `new-agent-model` | `js/skill_markt.js:3033-3087` | Agent-anlegen-Formular ohne Felder |
| `brain-tab-btn-galaxy/quartz/notebook`, `brain-subview-*`, `3d-galaxy-canvas`, `quartz-garden-iframe` | `index.html:7017-7022, 7452, 8035` | Brain-View-Controls |
| `inbox-*` (14 IDs: `inbox-side-tab-board`, `inbox-badge-*-tag`, `inbox-stream-col-*`, …) | `index.html:3387-3691` | Inbox-Header |
| `push-next-version-badge` | `js/system_settings.js:2651` | Update-Badge |

### 5.3 Frontend-Aufrufe ohne Route: **0**

247 distinkte `/api`-Pfade werden im aktiven Frontend per `fetch(` mit **Literal** aufgerufen.
Vergleich gegen die 861 Live-Operationen (Präfix `{}` für Parameter):

```
=== API-Pfade im Frontend OHNE exakte Live-Route: 0 ===
```

**Das ist der Befund:** In der Klasse „404-Kandidat" gibt es **keinen** Fall über literale URLs.
Das Risiko sitzt ausschließlich in **13** `fetch(<variable>)`-Aufrufen (z. B. `index.html:4647`,
`6138`, `8253`, `12365`), die den Pfad zusammensetzen
(`/api/hermes/profiles/${id}/status`, `/api/operations/vault/file?path=…`,
`/api/operations/kanban/projects/{id}`). Diese sind **statisch nicht auflösbar** und deshalb
hier **nicht** als tot oder lebendig klassifiziert. Eine Live-Prüfung hätte Requests gegen
mutierende Routen erfordert — unterblieben.

### 5.4 Routen ohne Aufrufer: 543 von 861 Operationen (180 GET) — Obergrenze

```
Live-Operationen: 861 | ohne Frontend-Aufruf: 543 | davon GET: 180
```

**Einschränkung, ehrlich:** Die Zahl ist eine **Obergrenze**. 13 variable-URL-`fetch`-Aufrufe
können Routen erreichen, die mein Literal-Scan nicht sieht; ein Pfad gilt als benutzt, wenn
**irgendeine** Methode ihn aufruft. Die Untergrenze ist nicht bestimmbar ohne Instrumentierung
der laufenden Instanz (Zugriffs-Logging), was ein Eingriff wäre.

Die 10 auffälligsten unbenutzten GET-Routen (Sicherheits-/Systembezug):

| Route | Anmerkung |
|---|---|
| `GET /api/proxy` | war der SSRF-Kanal (S10) — seit dem Fix zusätzlich tote Angriffsfläche |
| `GET /api/hermes/raw_config` | liefert maskierte Roh-Konfiguration, kein Frontend-Aufruf |
| `GET /api/hermes/config` | dito |
| `GET /api/security/egress-logs` | Sicherheits-Telemetrie ohne Konsument |
| `GET /api/security/receipts/verify` | Audit-Funktion ohne UI |
| `GET /api/system/drain/status` · `GET /api/v1/system/drain/status` | zwei parallele Pfade, beide unbenutzt |
| `GET /api/system/resource-backpressure` | — |
| `GET /api/system/write-batcher/stats` | — |
| `GET /api/system/backup-db/list` · `GET /api/system/standup/latest` | — |
| `GET /api/v1/container/all-logs` | Docker-Route ohne Aufrufer (aber `logs` wird benutzt) |
| `GET /api/governance/ai-act/{stats,inventory,export}`, `…/data-classification/{items,taxonomy}` | komplette Governance-Gruppe ohne UI |

**`/api/system/hermes/restart` — Sonderfall, der genau die Befundklasse zeigt:**
Die Route **existiert** live (`POST /api/system/hermes/restart`) und wird im Frontend **textuell**
referenziert (`index.html:8196`) — deshalb erscheint sie **nicht** in der Liste „ohne Aufrufer".
Ihr einziger Aufrufer ist aber `triggerHermesCoreRestart()`, und **diese Funktion hat null
Aufrufer** (§5.1), ihr Button `#btn-restart-hermes-core` **existiert nicht** (§5.2).
Ergebnis: Route aktiv, Erreichbarkeit null. **Eine reine Pfad-vs-Pfad-Prüfung hätte diesen
Befund verpasst** — genau deshalb müssen 5.1, 5.2 und 5.4 zusammen gelesen werden.

---

## 6. Priorisierung — 5 Maßnahmen mit dem besten Verhältnis Wirkung/Aufwand

| # | Maßnahme | Wirkung | Aufwand | Beleg |
|---|---|---|---|---|
| **1** | **`/api/v1/container/metrics`: Socket-Timeout anheben** (`main.py:8690` ruft mit Default 1,0 s; `docker stats` braucht 1–2 s). Z. B. `docker_socket_request("GET", …, timeout=3.0)` **oder** Docker-`stats` einmalig 2 s sammeln und 5 s cachen. | **hoch**: beendet eine garantierte 1-s-Blockade **und** liefert wieder echte Werte statt „Stopped/0 %" | **5–15 min** | §3.2: 3× `1.007 s` + `{"status":"Stopped"}`, `docker stats` real 1,04 s / 2,00 s |
| **2** | **`/api/roles` cachen und Payload verschlanken** (`load_roles()` parst bei **jedem** Aufruf 2,63 MB; `@ttl_cache(seconds=60)` + Feldauswahl). Gleiches Muster für `/api/hermes/profiles` (2,6 MB, p95 1,1 s). | **hoch**: 64 ms → ~1 ms Median, 2,6 MB → <100 kB pro Poll, p95-Spitzen von 1,1 s weg | **1–3 h** | §3.4, §3.5: 64,2 ms / 2.630.812 B; `json.load` 18,9 ms |
| **3** | **Token-Rechte + Rotation**: `chmod 600` auf `data/snapshots/*/.env`, `gmail_token.json`, `google_token.json`, `credentials.json`, `paperclip/docker/.env`; **Telegram-Token rotieren** (war seit 31.10. weltlesbar); `.env`-Kopien aus Snapshots entfernen. | **hoch**: schließt eine reale Secret-Exposition | **10 min** + Rotation | §4.1: `666 data/snapshots/manual_20261031_154716/.env`, `666 gmail_token.json`, `666 google_token.json` |
| **4** | **RBAC-Pilot**: `require_admin`-Dependency auf die 6 gefährlichsten der 72 ungeschützten Routen (`container/exec`, `system/update/{apply,rollback}`, `docker/{start,stop}`, `sandbox/execute`) — Muster existiert bereits (`main.py:7298`). | **hoch**: ein `viewer` darf heute Befehle in Containern ausführen | **0,5–1 Tag** | §4.2: 6/78 mit Prüfung |
| **5** | **Tote UI-Cluster entfernen oder DOM nachziehen** — beginnend mit den drei belegten Bruchstellen: `#view-system-settings` (falscher Name), die ~25 `erp-f-*`-IDs (`createNewErpAddress()` wirft TypeError), `#btn-restart-hermes-core` + `triggerHermesCoreRestart()`. | **mittel**: beseitigt stille TypeErrors und die irreführende „Restart"-Fläche | **2–4 h** für die drei Cluster; Rest (166 IDs) als eigene Aufräum-Etappe | §5.1, §5.2 |

**Nicht in die Top 5, obwohl im Audit:** P1 (Pooling spart 1,25 ms/Request — §3.1), P3 (N+1 kostet
8–27 ms — §3.3), B3-Rest (`hermes_updater.py:63`, echter Härtungspunkt, aber kein Live-Symptom
belegt) und P4-Fragmentierung (20 Partials sind parallel und in 128–208 ms erledigt — §3.4).

---

## 7. Prüftiefe

**Selbst gemessen (Befehl ausgeführt, Zahl selbst erhoben):**
A1, A2, A4, A5, A6, A7, A8, B1, B2, B3 (AST), B4, B5, B6, B7, B8, B9, B10, S3, S4 (AST), S5,
S7, S9, S10 (Dateibestand), Kennzahlen (Parität, Routen, Tests, Tracebacks), **P1–P8 vollständig**,
Block 4 vollständig (AST/Tokenizer über 50 Quellen + Live-`curl`).

**Nur gelesen (Code geprüft, nicht live ausgelöst — bewusst, weil mutierend oder eingreifend):**
S2 (Path-Jail: Code + Aufrufzahl), S6 (Sandbox: 501-Handler gelesen, **kein** POST abgesetzt),
S8 (Rate-Limit: Code + Testdatei in der grünen Suite), S10 (Egress-Guard: Datei + Testdatei),
S4-Rollentests (keine Requests gegen Admin-Routen), S9-Endpunktpfad (Maskierung im Code geprüft,
kein Abruf mit Wertausgabe).

**Nicht prüfbar (mit Grund):**
* **P5-Trefferquote** — kein Hit/Miss-Zähler im Code; Instrumentierung wäre ein Eingriff. Nur
  Abschätzung aus TTL gegen Poll-Intervall, als Schätzung markiert.
* **S3 „117 Dateien auf 600"** — die Zahl hat keine Definition (welche Grundgesamtheit?). Repo-weit
  sind 2.451 Dateien auf 600; die Aussage ist damit weder bestätigt noch widerlegt.
* **Block 4.3/5.4-Randfälle** — 13 `fetch(<variable>)`-Aufrufe sind statisch nicht auflösbar;
  die Zahl 543 ist deshalb eine Obergrenze. Zugriffs-Logging wäre nötig und ist ein Eingriff.
* **A3/A4 qualitativ** — „God Object" und „enge Kopplung" sind Bewertungen, keine Messgrößen;
  ich liefere nur die Zählwerte (347 `def`-Zeilen, 39 Module), keine Note.
* **Container-Interpreter** — alle In-Process-Messungen (P1, P6) liefen mit Python 3.11 auf dem
  Host, nicht im Container (dort `python -c` gesperrt). Die Größenordnungen sind vergleichbar, die
  Absolutwerte können im Container um wenige Prozent abweichen.
* **Höhe der S4-Auswirkung** — welcher Nutzer welche Rolle hat, habe ich nicht aus der
  Auth-DB gelesen (kein Zugriff auf Nutzerdaten nötig für den Befund „72 Routen prüfen nicht").

---

## 8. Working-Tree-Beleg

`git status --short` **nach** dem Schreiben dieses Dokuments, echter Befehlslauf:

```
?? .archon_backup_20261105_1015/omniroute_combos_vor_fix_20261106.json
?? .archon_backup_20261105_1015/skill_rollout_20261106_121401/
?? archon/core/agent_profiles.json
?? docs/BETRIEB_HANDBUCH_INTERN.md
?? docs/GRUNDPRUEFUNG_2026-11-07.md
?? docs/screenshots_20261106/
?? docs/system/HANDBUCH_Vorlage_Vorschau.pdf
?? frontend/
?? frontend_recovered_20261106_122145/
?? hermes_skills_cache.json
?? hermes_skills_index.json
?? scripts/gateway_watchdog.sh
```

`git diff --stat` → **leer** (keine Änderung an einer getrackten Datei).

Vergleich mit dem Handover-Stand (`HANDOVER_2026-11-07_nacht.md`, Abschnitt „Fremde uncommittete
Dateien", **11 Einträge**): alle 11 sind unverändert vorhanden, **neu ist genau ein Eintrag** —
`docs/GRUNDPRUEFUNG_2026-11-07.md`. Die fremden Bäume (`frontend/`, `frontend_recovered_*`,
`docs/screenshots_20261106/` …) sind nicht angefasst: sie erscheinen als Verzeichnis-Eintrag,
weil sie untracked sind, und waren es vorher auch.

**Nicht passiert (Auftrag):** kein `git add`, kein Commit, kein Deploy, kein Restart, kein Pull.
Die laufende Instanz `ARCHON-OS` (Up 7 h, Image `af26a3ee66e2`) wurde nur gelesen: `GET`-Requests
mit Service-Token, `curl -sI`, `docker logs --since`, `docker stats --no-stream`, `docker inspect`.
Kein Schreibzugriff auf Daten, keine Massenlast (max. 20 parallele GETs für die Startphase, wie der
Client sie selbst auslöst), keine parallelen Stresstests.

---

*Erstellt 2026-11-07, read-only-Prüfung. Kein Commit, kein Deploy, kein Restart. Messskripte lagen
außerhalb des Repos und wurden nicht eingecheckt. Der Working Tree enthält weiterhin ausschließlich
die 11 fremden untracked Einträge aus dem Handover plus dieses Dokument.*
