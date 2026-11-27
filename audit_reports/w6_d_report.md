# Welle W6, Partition D — Audit-Report (D09-H1, D09-M4)

> **Erstellt:** 27.11.2026 · **Branch:** `main` · **HEAD bei Start:** `3cf519f6` ·
> **Status:** statisch umgesetzt, lokal verifiziert, **nicht committet** (Koordinator
> verifiziert zentral und committet).

---

## 1. Vorgabe des Benutzers (27.11.2026) — strikt eingehalten

`D09-H1` wird **ausschließlich** als Image-Digest-Pinning + Adapter-Smoke-Test als
CI-Gate umgesetzt:

- **Keine Zerlegung** des 10.290-bzw. 11.232-Zeilen-Patches.
- **Keine Entflechtung** von `main.py` / `core_dispatcher.py`. `main.py` hat nur noch
  ~100–120 Zeilen Potenzial; jeder größere Umbau ist unerwünscht.
- `scripts/patches/hermes_telegram_adapter.py` blieb **unverändert** (Byte-identisch,
  kein Edit, kein Reformat).

**Expliziter Hinweis:** Die im Audit `domain_09.md` D09-H1 genannten Etappen (2)
„Dispatcher entlang `archon/services/dispatch_*.py` aufteilen" und (3) „`main.py`
bis zur reinen App-Komposition reduzieren" wurden **bewusst NICHT ausgeführt**.
Sie sind durch die Benutzerentscheidung vom 27.11.2026 ausdrücklich ausgeschlossen
und auch nicht als offene Folgearbeit in diesem Report aufgeführt. Ebenso wenig
wurde der Patch in `scripts/patches/telegram/*.py` zerlegt oder ein `register(ctx)`
neu geschrieben — der vorhandene Entry Point wird nur geprüft.

---

## 2. Dateibesitz (nur diese Dateien berührt)

| Datei | Änderung |
|---|---|
| `scripts/patches/MANIFEST.json` | **neu** — SSOT für Digest, Mount und API-Vertrag |
| `scripts/telegram_adapter_smoke_test.py` | **neu** — hartes Gate, Exit 0/1 |
| `docker-compose.yml` | zwei dokumentierende Kommentarblöcke (Digest-Bindung, Mount-Gate); **keine** Wertänderung |
| `main.py` | **nur D09-M4**: Import `ConfigDict`, `Body` entfernt, Modell + eine Route |
| `tests/test_w6_d_patch.py` | **neu** — 11 Regressionstests |
| `audit_reports/w6_d_report.md` | **neu** — dieser Report |

Nicht berührt: `.github/workflows/ci.yml` (Partition E), `scripts/patches/hermes_telegram_adapter.py`,
sowie alle Dateien der Partitionen W6-A/B/C/E und W3–W5. `git add` / Commit wurden
**nicht** ausgeführt. Hinweis für den Koordinator: `.gitignore:55` (`**/*report*`)
ignoriert diesen Report — beim Commit `git add -f audit_reports/w6_d_report.md`
verwenden (wie in HANDOFF §2.5 vorgesehen).

---

## 3. D09-H1 (HIGH 8, REDuziert) — Image-Digest + Smoke-Test

### Befund

`docker-compose.yml` mountet den 11.232-Zeilen-Adapter read-only über die
Hermes-Adapterdatei. Der Image-Digest war zwar bereits gepinnt
(`nousresearch/hermes-agent:v0.23.1@sha256:276d44685c…da08`, identisch in `hermes`
und `hermes-dashboard`), es gab aber **keine Verbindung** zwischen diesem Pin und
dem gemounteten Patch: `compileall` prüft nur Syntax, nicht die API-Kompatibilität
des fremden Codes. Ein Image-Bump konnte den Patch stillschweigend unwirksam machen.

### Fix

1. **`scripts/patches/MANIFEST.json`** (neu, SSOT):
   - `hermes_image.reference` + `digest` + die beiden `services`,
   - `adapter_mount` (`source`, `target`, `mode: ro`, `service: hermes`),
   - `adapter_api_contract`: 8 exakte Hook-Signaturen, `TelegramAdapter(BasePlatformAdapter)`,
     9 `register_platform(...)`-Kwargs, 6 Image-Importmodule, 4 Archon-Patch-Marker
     (`_archon_req` ≥ 5 — die reale Zahl im Patch; die alte Doku nannte ≥ 6, war aber
     nie per Gate verdrahtet).
2. **`scripts/telegram_adapter_smoke_test.py`** (neu): stdlib-only, importierbar und
   als Skript lauffähig. Prüft
   - Manifest-Struktur und Digest-Form (`sha256:` + 64 Hex),
   - Digest in **beiden** Hermes-Services gegen das Manifest,
   - exakten Read-Only-Mount (genau ein Treffer im `hermes`-Dienst),
   - `compile()`-Syntax der Adapterdatei,
   - exakte Positionsparameter aller Hook-Funktionen via `ast`,
   - Basisklasse `TelegramAdapter`, Image-Importmodule, `register_platform`-Kwargs,
   - Patch-Marker counts.
   Jeder Fehler → `Exit 1`, vollständige Übereinstimmung → `Exit 0`.
   Vertrag für Partition E: `python scripts/telegram_adapter_smoke_test.py`.
3. **`docker-compose.yml`**: dokumentiert die Bindung an das Manifest und den Gate
   direkt an den beiden relevanten Stellen; Werte unverändert.

### Verifizierung

- Positivprobe auf den echten Produktivdateien: 4 `PASS`, Exit 0.
- Negativproben (Digest-Drift, Mount `rw`, geänderte Signatur, entfernter Patch-Marker,
  Syntaxfehler) → jeweils Exit 1 / `FAIL`.
- Abschaltprobe des Exit-Vertrags (`main()` mit injiziertem Fehler) → Exit 1.

---

## 4. D09-M4 (MED 3) — letzter roher `Dict = Body(...)`

### Befund

`main.py:1562` nahm `POST /api/sandbox` mit `payload: Dict = Body(...)` entgegen.
Der Endpunkt ist eine 501-Notbremse mit `require_admin`, liest den Body nie, erzeugte
aber ein unvalidiertes FastAPI-Schema.

### Fix (nur diese eine Stelle)

- Neues Minimalmodell `SandboxLegacyRequest(BaseModel)` mit
  `model_config = ConfigDict(extra="ignore")` direkt über der Route; Signatur auf das
  Modell umgestellt. Alte Clients sind kompatibel, unbekannte Felder werden ignoriert.
- `Body` aus dem FastAPI-Import entfernt (nun unbenutzt); `ConfigDict` ergänzt.
- Route bleibt inhaltlich unverändert: `require_admin` + HTTP 501.
- **Keine** weitere Modularisierung von `main.py`.

---

## 5. Regressionstests — `tests/test_w6_d_patch.py`

11 Tests, alle grün:

| Gruppe | Tests |
|---|---|
| D09-H1 | Gate grün auf Produktivdateien + `main()==0`; Manifest-Digest == beide Services; Digest-Drift; Mount-Drift; API-Signatur-Drift; verlorener Patch-Marker; Syntaxfehler; `main()==1` bei Fehler |
| D09-M4 | kein `Body()`-Aufruf / `payload` ist `SandboxLegacyRequest`; Modell ignoriert unbekannte Felder (echte Pydantic-Instanz); Notbremse bleibt 501 mit `require_admin` |

Keine Secrets, keine `sk-<Zeichen>`-Strings, kein `# noqa` in String-zeilen.

---

## 6. Lokale Verifikation (Ergebnisse)

```
.venv\Scripts\python.exe scripts/telegram_adapter_smoke_test.py     -> Exit 0 (4 PASS)
.venv\Scripts\python.exe -m pytest tests/test_w6_d_patch.py -q      -> 11 passed
.venv\Scripts\python.exe -m ruff check --select E,F,I --ignore E501 \
    scripts/telegram_adapter_smoke_test.py tests/test_w6_d_patch.py main.py
                                                                    -> All checks passed
.venv\Scripts\python.exe -m mypy --config-file mypy.ini \
    scripts/telegram_adapter_smoke_test.py tests/test_w6_d_patch.py main.py
                                                                    -> Success (3 Dateien)
```

**Hinweis zur Shell:** In dieser Subagent-Session war `pwsh.exe` zeitweise mit
`Zugriff verweigert` blockiert; einzelne Ruff-/Pytest-/Git-Aufrufe mussten wiederholt
werden. Die obigen Ergebnisse stammen aus erfolgreichen Läufen. Der **Koordinator
verifiziert zentral** (Full-Suite, Ruff/MyPy auf dem Gesamtdiff, Commit).

---

## 7. Übergabe an Partition E

`ci.yml` gehört Partition E und wurde nicht angefasst. Zu verdrahten ist:

```yaml
- name: Telegram-Adapter-Kompatibilitaet (D09-H1)
  run: python scripts/telegram_adapter_smoke_test.py
```

Der Schritt ist hart (`continue-on-error` nicht setzen). Er benötigt keine Docker-
Umgebung, keine Secrets und keine zusätzlichen Abhängigkeiten (stdlib-only).
Bei einem Hermes-Image-Bump müssen `MANIFEST.json` **und** `docker-compose.yml`
gemeinsam geändert werden; der Patch selbst bleibt dabei unverändert und wird vom
Gate auf API-Kompatibilität geprüft.

---

## 8. NEVER_DO_LIST / Negativconstraints

Kein PostgreSQL/DSN/Migration, kein Coroutine-/Event-Replay, keine neue
Content-Domäne. Keine Commits, kein `git add`, keine fremden Dateien verändert.
