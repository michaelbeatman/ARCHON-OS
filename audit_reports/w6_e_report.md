# W6-E — Code-Standards & CI-Gates (Partition E)

> **Welle/Partition:** W6-E · **Branch:** `main` · **HEAD bei Start:** `3cf519f6`
> **Dateibesitz:** `mypy.ini`, `.importlinter`, `requirements-ci.lock.txt`,
> `.github/workflows/ci.yml`, `Dockerfile`, `backend/requirements.txt` (gelöscht),
> `backend/operations_bulk.py`, `tests/test_w6_e_ci.py`, dieser Report.
> **Kein Commit, kein `git add`** durch diesen Subagenten.

## 1. Verbindliche Vorgaben geprüft

- `docs/system/NEVER_DO_LIST.md` gelesen: kein PostgreSQL/DSN/Migrationstool,
  kein Coroutine-/Event-Replay. **Keine der Änderungen berührt diese Verbote**
  (SQLite-only beim Undo-Store, keine Replay-Logik).
- `audit_reports/HANDOFF_W4_W7.md` §2/§7/§9 und `audit_reports/domain_09.md` gelesen.
- Fremddateien nicht verändert: insbesondere nicht `docker-compose.yml`,
  `scripts/patches/**`, `scripts/telegram_adapter_smoke_test.py`, `main.py`,
  `backend/auth_service.py`, `tests/test_import_layer_contracts.py`.
- Keine Secrets / `sk-<Zeichen>` in Tests; kein `# noqa` in Zeilen, die Strings öffnen.

## 2. Umsetzung je Fund

### D09-M1 (MED 5) — MyPy-Zielversion

`mypy.ini:5-9`: `python_version = 3.11` → **`3.13`**, Begründungskommentar
ersetzt (ausgelieferte Runtime statt „konservativerer" 3.11-Lauf).
`.github/workflows/ci.yml`: Kommentar im MyPy-Ratchet auf 3.13 korrigiert;
kein Flag überschreibt die Config (weiterhin `mypy --config-file mypy.ini`).
**Test:** `test_w6_e_mypy_targets_python_313` (Config + Abwesenheit eines
override-Flags).

> Hinweis an Koordinator: der 3.13-Stub-Wechsel kann in *anderen* Modulen
> `# type: ignore`-Codes verschieben (Partition C begrenzt `auth_service.py`).
> Bitte im Zentrallauf `mypy --config-file mypy.ini` auf den geänderten
> Dateien prüfen; die Config wird **nicht** wieder abgesenkt.

### D09-M2 (MED 4) — Import-Layer-Gate

- `.importlinter`: beide Contracts bleiben deklariert, aber der zweite
  (`core-no-router-imports`) steht jetzt ebenfalls auf
  `allow_indirect_imports = false` (streng, transitiv). Veraltete Kommentare
  („nur direkte Importe", „lokales Tool") korrigiert.
- `requirements-ci.lock.txt`: `import-linter==2.17` (CLI `lint-imports`)
  hash-gepinnt ergänzt, inkl. Transitiv-Kette `grimp==3.20` und
  `click==8.5.1` — **alle Hashes am 27.11.2026 aus der PyPI-JSON-API**,
  keine erfundenen Werte. `rich`/`typing-extensions` waren bereits im Lock.
- `.github/workflows/ci.yml`: neuer harter Schritt
  `lint-imports --no-logo .importlinter` im Job `validate-and-audit`
  (dort wird der CI-Hash-Lock installiert), ohne `continue-on-error`.
  Damit werden **beide Contracts inkl. transitiver Kanten** geprüft.

**Tests:** Config-Sections/Optionen, Hash-PinsFormat, harter CI-Schritt,
kein `continue-on-error`-Key, Negativprobe der BFS-Kette
`backend → archon.core → archon.services → archon.routers` sowie
Produktivscan auf echte transitive Pfade (0 erwartet).

**Testbedarf außerhalb meines Besitzes (an Koordinator):**
`tests/test_import_layer_contracts.py` liest heute nur
`CONTRACT_SECTION = "importlinter:contract:backend-no-router-imports"` und
folgt keinen transitiven Importen. Dort bitte ergänzen:
`CORE_CONTRACT_SECTION`, Parametrisierung von `_router_imports()` auf
`archon/core/**` und einen Graph-Traversal-Schritt für
`backend → archon.core → archon.routers` (Negativprobe im Stil von `:160-209`).
Ich habe diese Datei **nicht** verändert; die Äquivalenzprüfung liegt in
`tests/test_w6_e_ci.py`.

### D09-M5 (MED 5) — statische Gates auf Root-Monolithen

`.github/workflows/ci.yml`: `compileall`, `bandit -q -lll` und (konsistent)
`ruff check --select E9,F63,F7,F82` nutzen jetzt dieselbe **explizite
Root-Dateiliste** (15 Module, u. a. `api_provider.py`, `views_core.py`,
`core_skills_engine.py`, `watchdog_daemon.py`, `local_security_guard.py`,
`backup_archon.py`).
`Dockerfile`: zusätzlicher Build-Gate `RUN python -m compileall -q *.py`
direkt nach `COPY *.py ./` — das Image kann keinen syntaxfehlerhaften
Root-Monolithen mehr bauen.

**Tests:** jeder der drei Steps muss alle 15 Root-Module listen;
`ALL_ROOT_MODULES` wird gegen den Checkout abgeglichen (neue Root-Dateien
machen den Test rot); Dockerfile enthält Copy + Compile-Gate.

### D09-M6 (MED 5) — Undo-Store ohne Lock

`backend/operations_bulk.py`:
- `threading.RLock()` als `_UNDO_LOCK` (reentrant, weil `_prune_undo_store()`
  aus bereits gesperrten Pfaden gerufen wird).
- `_prune_undo_store()`: Iteration/TTL-Pop/Max-Size-Cap unter Lock.
- Schreiben + Pruning in **einem** kritischen Abschnitt.
- Undo-Pfad: TTL-Prüfung und **CAS-Verbrauch** (`pop`) unter Lock, *bevor*
  die DB-Arbeit beginnt. Das spätere zweite `pop()` wurde entfernt — ein
  paralleler zweiter Request läuft jetzt in den 404-Pfad statt denselben
  Snapshot erneut zu spielen.
- Der Store bleibt bewusst ein reines `dict`: `backend/operations_api.py`
  re-exportiert ihn by identity und
  `tests/test_d3_bulk_characterization.py:72` prüft genau das.

**Tests:** Reentranz (kein Deadlock), zwei parallele Undo-Requests auf
denselben Token (genau 1× `success`, 1× HTTP 404), abgelaufener Token →
400 + Entfernung aus dem Store.

> Persistenz in einer SQLite-Tabelle mit `tenant_id`/`expires_at`
> (workerübergreifende Tokens) ist bewusst **nicht** in dieser Welle
> umgesetzt: sie würde den re-exportierten Dict-Vertrag und die
> Call-Time-Dependency-Injection der D3-Extraktion brechen. Der aktuelle
> CAS ist prozessweit korrekt; die SQLite-Variante bleibt als eigene,
> API-kompatible Etappe.

### D09-M8 (MED 3) — Backend-Manifest

Vorher geprüft: `backend/Dockerfile:12-13` und `Dockerfile:29` installieren
bereits `requirements.lock.txt` aus dem Root; `ci.yml` und alle Skripte
referenzieren `backend/requirements.txt` **nicht** (nur Audit-Dokus).
Die Datei wurde daher **gelöscht**; Root-Lock ist die einzige SSOT.

**Test:** Datei existiert nicht mehr; beide Dockerfiles referenzieren
`requirements.lock.txt`, keiner `backend/requirements.txt`.

### Vertrag W6-D (verbindlich) — Telegram-Adapter-Smoke-Test

`.github/workflows/ci.yml`, Job `test-suites`: neuer harter Schritt
`python scripts/telegram_adapter_smoke_test.py` (Exit 1 = rot, kein
`continue-on-error`, kein `|| true`). Das Skript wird von Partition D
angelegt und wurde **nicht** von mir erstellt oder verändert.

**Test:** Step vorhanden und hart verdrahtet.

> Sequenzierung: bis W6-D das Skript liefert, ist dieser Schritt im CI rot.
> Bitte vom Koordinator gemeinsam mit dem W6-D-Commit verifizieren.

## 3. Datei-Änderungen (Übersicht)

| Datei | Änderung |
|---|---|
| `mypy.ini` | `python_version = 3.13` + Kommentar |
| `.importlinter` | 2. Contract streng/transitiv, Kommentare aktualisiert |
| `requirements-ci.lock.txt` | `import-linter`, `grimp`, `click` hash-gepinnt |
| `.github/workflows/ci.yml` | compileall/bandit/ruff-Dateilisten, `lint-imports`-Gate, Smoke-Test-Gate, Kommentar |
| `Dockerfile` | Build-Compile-Gate für Root-`*.py` |
| `backend/requirements.txt` | gelöscht |
| `backend/operations_bulk.py` | `RLock`, atomisches TTL/CAS, Kommentare |
| `tests/test_w6_e_ci.py` | neu, 15 Regressionstests |
| `audit_reports/w6_e_report.md` | neu (dieser Report) |

## 4. Verifikationsstatus

Die Shell war in dieser Subagent-Session **teilweise blockiert**
(`pwsh.exe: Zugriff verweigert` bei `git status`, `Remove-Item`); die
Löschung von `backend/requirements.txt` gelang über `cmd /c del`. Ein
lokaler Python-Interpreter ist nicht verfügbar (`python`/`py` zeigen nur
auf den Windows-Store-Stub). Deshalb: **statisch sauber editiert, nicht
selbst ausgeführt.** Der Koordinator verifies zentral:

```powershell
$env:ARCHON_TEST_DB_ISOLATION='1'
$files = @('backend/operations_bulk.py','tests/test_w6_e_ci.py')
.venv\Scripts\python.exe -m ruff check --select E,F,I --ignore E501 --output-format=concise $files
.venv\Scripts\python.exe -m mypy --config-file mypy.ini $files
.venv\Scripts\python.exe -m pytest tests/test_w6_e_ci.py tests/test_d3_bulk_characterization.py tests/test_import_layer_contracts.py -q
lint-imports --no-logo .importlinter
python -m compileall -q *.py
```

Erwartung: 15 neue Tests grün, D3-Characterization unverändert grün,
`lint-imports` 2 kept / 0 broken, MyPy/Ruff auf den geänderten `.py` grün.
Full-Suite mindestens auf Baseline-Niveau (HANDOFF §3).

## 5. NEVER_DO-Check

Kein PostgreSQL/DSN/Migrationstool, kein Coroutine-/Event-Replay, keine
Content-Domäne. Alle Fixe bleiben innerhalb der erlaubten Partition E.
Kein Commit, kein `git add`, keine fremden Dateien „nebenbei" lintet oder
umbenannt.

## 6. Kurzfazit

Sechs Funde (D09-M1/M2/M5/M6/M8 + W6-D-Vertrag) sind code- und
testseitig umgesetzt. Die drei zuvor unsichtbaren Root-Monolithen sind in
allen statischen Gates erfasst; der Import-Layer wird erstmals durch das
echte `lint-imports`-Binary (beide Contracts, transitiv) erzwungen; der
Undo-Token ist thread-sicher und genau einmal verbrauchbar. Offen bleibt
allein die zentrale Verifikation und das Einliefern des W6-D-Skripts.
