# Fix D4 — MyPy-Dokumentation & Third-Party-Lizenzausweis (25.11.2026)

> Dokumentationsauftrag zu Fix D2 (`audit_reports/fix_d2_mypy.md`).
> Exklusives Datei-Ownership eingehalten: **nur** `THIRD_PARTY_LICENSES.md`,
> `docs/system/MYPY_TYPE_GATE_GUIDE.md` (neu), `README.md` (eine Zeile) und
> dieser Report. **Keine** Python-/Config-/Test-/Docker-Datei berührt.
> Keine Produktiv-DB, kein `.env`, keine Container angefasst.
> NEVER_DO_LIST: kein Replay, keine PostgreSQL-Migration, keine Laufzeitänderung.

## 1. Gelesene Quellen (SSOT)

| Datei | Zweck |
|---|---|
| `THIRD_PARTY_LICENSES.md` | Abschnitt 6 „Frontend & Backend Open-Source Libraries" — Einordnung der Fremdmodule |
| `mypy.ini` | SSOT der mypy-Konfiguration (`python_version = 3.11`, `warn_unused_ignores`, `disallow_untyped_defs` nur für `archon.services.*`) |
| `requirements-ci.lock.txt` | Versionen + SHA-256-Hash-Pins: mypy 2.4.1, ruff 0.17.6, bandit 1.9.4, pip-audit 2.10.1, cyclonedx-bom 9.0.0 |
| `.github/workflows/ci.yml` | mypy-Schritte im Job `quality-gates` (Changed-Files-Ratchet + Neumodul-Gate) |
| `audit_reports/fix_d2_mypy.md` | 43 → 3 Pauschal-Pragmas, 40 im Ownership-Scope, 414 Fehler → 0, drei Reste ausserhalb Scope |

## 2. Änderungen (4 Dateien)

### 2.1 `THIRD_PARTY_LICENSES.md`

Neuer Unterabschnitt **„Development / CI tooling (nicht zur Laufzeit)"** in
Abschnitt 6, eingefügt nach dem bestehenden `pytest / pytest-xdist`-Eintrag:

- mypy **2.4.1** — MIT License, (c) Jukka Lehtosalo / mypy contributors —
  statisches Typ-Gate, SSOT `mypy.ini`.
- pytest / pytest-xdist — MIT License (bereits gelistet, zur Vollständigkeit
  erneut aufgeführt; Version in `requirements-test.lock.txt`).
- Ergänzte CI-Helfer mit Version aus `requirements-ci.lock.txt` und Lizenz:
  ruff **0.17.6** (MIT, Astral Software Inc.), bandit **1.9.4** (Apache-2.0,
  PyCQA/OpenStack), pip-audit **2.10.1** (Apache-2.0, Trail of Bits),
  cyclonedx-bom **9.0.0** (Apache-2.0, OWASP CycloneDX contributors).
- Zweck-Spalte für jedes Tool, Beispiel-Hash-Pin (vier `sha256`-Zeilen aus dem
  Lockfile) und Installationsbefehl `--require-hashes --no-deps`.
- Expliziter Hinweis: **Dev-only, keine Produktiv-Abhängigkeit**; die Tools
  werden nicht zur Laufzeit importiert und nicht in `requirements.lock.txt`
  geführt. Lizenzangaben folgen den Upstream-Projektmetadaten (kein Vendoring
  im Repo).

### 2.2 `docs/system/MYPY_TYPE_GATE_GUIDE.md` (neu, 8,5 KB)

Acht Abschnitte:

1. **Was mypy prüft** — „Rechtschreibprüfer für Typen" (einfache Erklärung),
   Tabellen der relevanten `mypy.ini`-Einstellungen, klarer Hinweis „keine
   Laufzeitveränderung".
2. **Warum der Gate wirkungslos war** — `# mypy: ignore-errors` in 43
   Python-Dateien unterdrückte sämtliche Fehler.
3. **Was behoben wurde** — 40 durch D2 + 3 Rest (`core_skills_engine.py`,
   `local_memory_bridge.py`, `research_engine_v2.py`), 414 Fehler → 0; Verweis
   auf den D2-Report.
4. **Lokal prüfen** — `.venv\Scripts\mypy.exe --config-file mypy.ini <dateien>`,
   Python-3.11/3.12-Hinweis (`python_version = 3.11`, CI auf 3.13), keine
   Flags, die die SSOT überschreiben.
5. **CI-Gate** — `quality-gates`-Job, Diff-Range (`origin/<base>...HEAD`
   bzw. `HEAD^ HEAD`), geänderte Dateien, zusätzlicher Neumodul-Gate mit
   `--disallow-untyped-defs`, hash-geprüftes CI-Lockfile.
6. **Gezielte `# type: ignore[code]`** — Code immer angeben, nur einzelne
   Zeile, Position vor Trailer-Kommentar, `warn_unused_ignores`, echte
   Annotation bevorzugen, aber nie mit Laufzeitänderung.
7. **NEVER_DO_LIST bleibt unberührt** — kein Replay, keine PostgreSQL-
   Migration, keine Produktiv-DB/`.env`/Container; bei Konflikt gilt die
   NEVER_DO_LIST, Funde werden eskaliert statt „still weggeflickt".
8. **Verweise** — `mypy.ini`, `requirements-ci.lock.txt`, `ci.yml`,
   `fix_d2_mypy.md`, dieser Report, `THIRD_PARTY_LICENSES.md`.

### 2.3 `README.md`

Eine Zeile im Bereich „Project Structure & Documentation" ergänzt:

```markdown
- **MyPy Type-Gate Guide:** [docs/system/MYPY_TYPE_GATE_GUIDE.md](docs/system/MYPY_TYPE_GATE_GUIDE.md)
```

### 2.4 `audit_reports/fix_d4_docs_mypy.md`

Dieser Report.

## 3. Verifikation (ehrlich)

Shell war **verfügbar**. Ausgeführt und geprüft:

| Prüfung | Ergebnis |
|---|---|
| `git diff -- README.md THIRD_PARTY_LICENSES.md` | nur die geplanten Doku-Änderungen in diesen beiden Dateien; der README-Link ist intact. Weitere README-/CHANGELOG-Änderungen im Diff stammen von parallelen Agenten, nicht von mir. |
| `git diff --stat` | `THIRD_PARTY_LICENSES.md` +35 Zeilen; `README.md` enthält zusätzlich meine eine Zeile. Die vielen geänderten `.py`- und `audit_reports/domain_*.md`-Dateien sind **nicht** von mir. |
| `Get-Item docs/system/MYPY_TYPE_GATE_GUIDE.md` | vorhanden (8.488 Bytes); Pfad/Dateiname korrekt. |
| `Select-String` auf den Guide | Pflichtinhalte vorhanden: Rechtschreibprüfer-Metapher, 40/3-Reste, `.venv\Scripts\mypy.exe --config-file mypy.ini`, gezielte Ignores, NEVER_DO_LIST, Verweis auf `fix_d2_mypy.md`. |
| Relative Linkziele im Guide | `../../audit_reports/…`, `../../mypy.ini`, `../../requirements-ci.lock.txt`, `../../.github/workflows/ci.yml`, `../../THIRD_PARTY_LICENSES.md` und zwei Within-`docs/system/`-Links zeigen auf existierende Dateien. |

**Nicht ausgeführt:** kein mypy-Lauf, kein pytest-Lauf, kein CI-Lauf — dieser
Auftrag ist rein dokumentarisch und ändert keinen Code. Die Zahlen im Guide
sind aus `audit_reports/fix_d2_mypy.md` übernommen, nicht neu gemessen.

## 4. Bemerkungen / abgegrenzte Zuständigkeiten

1. **Drei Pragma-Reste:** Der Guide dokumentiert den D2-Snapshot (25.11.2026)
   mit 43 → 3. Im working tree entfernt ein **parallel arbeitender Agent** an
   drei Python-Dateien (`core_skills_engine.py`, `local_memory_bridge.py`,
   `research_engine_v2.py`) jeweils Zeile 1. Ich habe diese Dateien nicht
   berührt; falls diese Änderung landet, ist der D2-Snapshot weiterhin als
   historische Doku korrekt, der Zähler „3" ist dann nur noch der Ausgangswert
   für einen Folgeclose.
2. **Lizenzen der CI-Helfer** wurden aus den bekannten Upstream-Projekten
   dokumentiert, nicht aus im Repo vorhandenen Lizenzdateien (die Pakete
   werden nicht vendoriert). Bei abweichender upstream-lizenzrechtlicher
   Bewertung ist `THIRD_PARTY_LICENSES.md` entsprechend zu korrigieren.
3. **`pytest`-Version** wurde bewusst nicht erfunden: pytest steht nicht in
   `requirements-ci.lock.txt`, sondern in `requirements-test.lock.txt`; die
   Tabelle verweist dorthin, statt eine nicht belegte Version zu nennen.
