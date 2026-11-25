# MyPy Type-Gate Guide

> Development-/CI-Dokumentation zu mypy 2.4.1 (MIT, (c) Jukka Lehtosalo / mypy contributors).
> SSOT für die Konfiguration ist `mypy.ini`; SSOT für die durchgeführte Sanierung ist
> `audit_reports/fix_d2_mypy.md`. mypy ist **Dev-only, keine Produktiv-Abhängigkeit**
> (siehe `THIRD_PARTY_LICENSES.md`, Abschnitt 6).

---

## 1. Was mypy prüft — kurz erklärt

Stell dir mypy wie einen **Rechtschreibprüfer für Typen** vor: Genau wie ein
Rechtschreibprüfer Wörter gegen ein Wörterbuch abgleicht, prüft mypy die
**Typangaben** im Python-Code gegen die Definitionen der Funktionen, Klassen
und Variablen. Es meldet zum Beispiel:

- eine Zahl (`int`), die an einer Stelle erwartet wird, an der ein Text (`str`) stehen müsste;
- ein Attribut oder eine Funktion, die es auf einem Objekt gar nicht gibt;
- einen Rückgabewert, der nicht zur deklarierten Signatur passt;
- einen veralteten `# type: ignore`-Kommentar, der keinen Fehler mehr abfängt
  (`warn_unused_ignores = True`).

Wichtig: mypy ändert **kein Laufzeitverhalten**. Es liest nur den Quellcode und
gibt Fehlermeldungen aus. Es ist ein Werkzeug für Entwickler und die CI, kein
Bestandteil der laufenden Archon-OS-Anwendung.

### Konfiguration (`mypy.ini`)

| Einstellung | Wert | Bedeutung |
|---|---|---|
| `python_version` | `3.11` | Referenz-Interpreter der lokalen Toolchain (`.ci_venv`); konservativere Zielversion für Typ-Pragmas. Die CI läuft auf 3.13. |
| `warn_unused_ignores` | `True` | Ein `# type: ignore` ohne passenden Fehler wird selbst zum Fehler. |
| `check_untyped_defs` | `True` | Auch Funktionen ohne Annotationen werden im Body geprüft. |
| `ignore_missing_imports` | `True` | Optionale Integrationen (n8n, Hermes, Langfuse, PocketBase, Browser-Treiber) ohne Typstubs sollen das Gate nicht an fehlenden `.pyi`-Dateien scheitern lassen. Ausnahmen: `requests`, `pydantic`, `fastapi` werden echt geprüft. |
| `disallow_untyped_defs` | `False` global / `True` für `archon.services.*` | Legacy-Bestand bleibt zunächst untyped; neue Module müssen vollständig typisiert sein. |
| `exclude` | `.ci_venv`, `.venv-tools`, `.mypy_cache`, `.ruff_cache`, `node_modules`, `archive`, `_archive_legacy`, `scratch`, `dist`, `site`, `quartz_app`, `notebooklm` | Diese Verzeichnisse werden nicht geprüft. |

---

## 2. Warum der Gate vorher wirkungslos war

Ein Gate ist nur so gut wie das, was er prüft. Vor der Sanierung stand in
**43 Python-Dateien** am Dateianfang der pauschale Sperrkommentar:

```python
# mypy: ignore-errors
```

Dieser Kommentar weist mypy an, **alle Fehler in der gesamten Datei zu
ignorieren**. Der CI-Gate lief also grün, obwohl in den betroffenen Modulen
hunderte echte Typfehler verborgen waren — er prüfte praktisch nichts. Das war
der Kernbefund aus `audit_reports/fix_d2_mypy.md` (Punkt 3a aus
`HANDOFF_FINAL_2026-11-25.md`; H-09-1 / F002+F044 aus `MASTER_PLAN.md` §4/§5).

---

## 3. Was behoben wurde

| Metrik | Vorher | Nachher |
|---|---:|---:|
| `# mypy: ignore-errors` gesamt im Repo | 43 | 3 |
| `# mypy: ignore-errors` im Ownership-Scope (D2) | 40 | 0 |
| MyPy-Fehler in bearbeiteten Dateien | 414 | 0 |

- **40 Dateien** wurden im Rahmen von Fix D2 (25.11.2026) von Pauschal-Pragmas
  befreit. Jeder der 414 Fehler wurde durch einen **gezielten** Code-Ignore
  ersetzt (z. B. `# type: ignore[assignment]`, `[arg-type]`, `[union-attr]`)
  oder — wo ohne Verhaltensänderung möglich — durch eine echte Typ-Annotation.
- **3 Reste** stehen bewusst noch in Dateien ausserhalb des damaligen
  Ownership-Scope: `core_skills_engine.py`, `local_memory_bridge.py`,
  `research_engine_v2.py` (jeweils Zeile 1). Für einen vollständigen Abschluss
  müssen diese drei Dateien separat freigegeben werden.
- `mypy.ini` musste dafür **nicht** geändert werden — die bestehende
  W0-Konfiguration erfüllt ihren Zweck.

Details, Batch-Übersicht und Verifikationsprotokoll:
[`audit_reports/fix_d2_mypy.md`](../../audit_reports/fix_d2_mypy.md).

---

## 4. Lokal prüfen

Voraussetzung: aktiviertes Virtual Environment mit den CI-Helfern aus
`requirements-ci.lock.txt`. Unter Windows lautet der Aufruf:

```powershell
.venv\Scripts\mypy.exe --config-file mypy.ini <dateien>
```

Beispiel für geänderte Dateien:

```powershell
.venv\Scripts\mypy.exe --config-file mypy.ini main.py core_dispatcher.py backend/operations_api.py
```

**Python-Hinweis:** `mypy.ini` fixiert `python_version = 3.11`. Prüfe lokal
nach Möglichkeit mit einem Python-3.11- oder 3.12-Interpreter; das ist die
konservativste Basis für Typ-Pragmas. Die CI läuft auf Python 3.13. Wichtig ist,
dass die Konfiguration aus `mypy.ini` gilt und **nicht** durch zusätzliche Flags
überschrieben wird — der CI-Gate verwendet bewusst nur
`--config-file mypy.ini`.

> Tipp aus Fix D2: Bei einem frischen Temp-Verzeichnis für `ARCHON_DATA_DIR`
> laufen die Tests stabil. Reproduktionsdetails und bekannte Ausnahmen stehen
> im D2-Report.

---

## 5. Wie der CI-Gate arbeitet

Der Gate läuft in `.github/workflows/ci.yml` im Job **„6. Quality Gates
(scharf)"** (Job `quality-gates`). Er ist ein **Changed-Files-Ratchet**:alter
Code bleibt unangetastet, aber jede geänderte Datei muss sauber sein
(kein `continue-on-error`, kein stilles Grün).

1. Die Step **„Changed-Files-Ratchet – Diff-Bereich bestimmen"** ermittelt per
   `git diff` die geänderten `.py`/`.pyi`-Dateien:
   - bei Pull Requests: `origin/<base_ref>...HEAD`
   - bei Push: `HEAD^ HEAD`
2. Die Step **„mypy – geänderte Dateien (HARTES RATCHET-GATE)"** ruft für genau
   diese Dateien auf:

   ```bash
   mypy --config-file mypy.ini $FILES
   ```

   Gibt es keine geänderten Python-Dateien, wird der Schritt mit einem Hinweis
   übersprungen.
3. Zusätzlich prüft die Step **„mypy – neu hinzugefügte Module
   (disallow_untyped_defs, HARTES GATE)"** neu angelegte Dateien mit
   `--disallow-untyped-defs`. Bestandsmodule mit altem `# mypy: ignore-errors`
   bleiben davon unberührt.

Die mypy-Abhängigkeit kommt hash-geprüft aus `requirements-ci.lock.txt`
(`--require-hashes --no-deps`), es gibt keine Versionsbereiche und keinen
ungepinnten pip-Upgrade. Siehe auch
[`CI_PIPELINE_E2E_TESTING_GUIDE.md`](CI_PIPELINE_E2E_TESTING_GUIDE.md).

---

## 6. Umgang mit gezielten `# type: ignore[…]`

Pauschal-Pragmas (`# mypy: ignore-errors`) sind **nicht** erwünscht — sie
schalten die Prüfung für die ganze Datei ab und haben den Gate jahrelang
wirkungslos gemacht. Der korrekte Weg ist ein **gezielter Ignore der Form
`# type: ignore[code]`**:

```python
value = do_something()  # type: ignore[arg-type]
```

Regeln:

- **Immer den Code angeben** (`[assignment]`, `[arg-type]`, `[union-attr]`,
  `[return-value]`, `[call-arg]`, …). mypy zeigt den passenden Code in der
  Fehlermeldung an (`show_error_codes = True`).
- **Nur die einzelne Zeile** betreffen, nie die ganze Datei.
- Der Ignore steht **vor** einem bereits vorhandenen Trailer-Kommentar — mypy
  erkennt `# code # type: ignore[x]` nicht zuverlässig (siehe D2, Methode).
- `warn_unused_ignores = True` sorgt dafür, dass ein Ignore, der keinen Fehler
  mehr abfängt, selbst auffällt und entfernt werden muss.
- Wo möglich ist eine echte Typ-Annotation statt eines Ignores vorzuziehen —
  aber **niemals** mit einer Laufzeitveränderung (siehe D2, Ausnahme
  `core_dispatcher.py:1998`).

---

## 7. NEVER_DO_LIST bleibt unberührt

Diese Dokumentation und der MyPy-Gate ändern **nichts** an der
[`NEVER_DO_LIST`](NEVER_DO_LIST.md). Insbesondere gilt:

- kein Replay,
- keine PostgreSQL-Migration,
- keine Produktiv-DB, kein `.env`, keine Container werden angefasst,
- keine Laufzeitveränderung durch Typ-Kommentare.

Der Gate ist ein rein statisches, dev-/CI-seitiges Werkzeug. Bei Konflikten
zwischen einem mypy-Fund und einer Regel der NEVER_DO_LIST gilt weiterhin die
NEVER_DO_LIST; es wird nicht „still weggeflickt", sondern der Fund wird
dokumentiert und an den Orchestrator eskaliert.

---

## 8. Verweise

- Konfiguration: [`mypy.ini`](../../mypy.ini)
- Hash-Lock (Version 2.4.1): [`requirements-ci.lock.txt`](../../requirements-ci.lock.txt)
- CI-Gate: [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) (Job `quality-gates`)
- Sanierungs-Report: [`audit_reports/fix_d2_mypy.md`](../../audit_reports/fix_d2_mypy.md)
- Doku-Fix-Report: [`audit_reports/fix_d4_docs_mypy.md`](../../audit_reports/fix_d4_docs_mypy.md)
- Lizenzen: [`THIRD_PARTY_LICENSES.md`](../../THIRD_PARTY_LICENSES.md) (Abschnitt 6)
