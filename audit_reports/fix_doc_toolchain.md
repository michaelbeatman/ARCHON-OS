# Fix-Report: Dokumentation der statischen Analyse-Toolchain

**Datum:** 25.11.2026 · **Scope:** ausschliesslich Dokumentation (Subagent, exklusives Ownership) · **Status:** abgeschlossen (Doku), Scan-Ergebnisse ausstehend

---

## 1. Was dokumentiert wurde

| Datei | Änderung |
|---|---|
| `THIRD_PARTY_LICENSES.md` | Abschnitt 6 „Development / CI tooling" auf alle Scanner erweitert: ruff, vulture, radon, import-linter (`lint-imports`), detect-secrets, bandit, pip-audit, semgrep, coverage, pyright; mypy/pytest/cyclonedx-bom erhalten. Je Zeile: Version, Lizenz/Copyright, Zweck, Dev-only-Kennzeichnung,Hash-Pin-Status. |
| `docs/system/STATIC_ANALYSIS_TOOLCHAIN_GUIDE.md` | **Neu.** §0-Regel (Produzent → Konsument → Effekt → Verifikation, sonst Theater), Scan-Ablauf, Übersichtstabelle und 10 Tool-Details mit „Was es findet / 1-Zeilen-Befehl / Log-Pfad / CI-Status / Verifikation". Zertifikatshinweis: erst bei vollständig sauberem Stand, nicht jetzt. |
| `README.md` | Eine Linkzeile auf den neuen Guide (direkt nach dem MyPy-Type-Gate-Guide). |
| `audit_reports/fix_doc_toolchain.md` | **Neu.** Dieser Report. |

---

## 2. Fakten, die gegen echte Dateien geprüft wurden

- **`requirements-ci.lock.txt` — tatsächlich vorhandene Hash-Pins (nur diese):**
  `mypy==2.4.1` (4 Hashes, Zeile 165), `ruff==0.17.6` (3, Zeile 287),
  `bandit==1.9.4` (2, Zeile 32), `pip-audit==2.10.1` (2, Zeile 202),
  `coverage==7.17.5` (4, Zeile 68), `cyclonedx-bom==9.0.0` (2, Zeile 75).
- **Kein Hash-Pin** (explizit so dokumentiert, nichts erfunden): vulture, radon,
  import-linter, detect-secrets, semgrep, pyright.
- **`scripts/run_static_toolchain.ps1`** enthält 10 `Run-Scan`-Aufrufe: ruff,
  vulture, radon, import-linter, detect-secrets, bandit, pip-audit, semgrep,
  coverage, coverage-report. Ausgaben via `Tee-Object` nach
  `audit_reports/tool_scans/<name>.txt`, jeweils `EXIT=<code>`; `ARCHON_DATA_DIR`
  zeigt auf ein Temp-Verzeichnis. **pyright ist nicht enthalten.**
- **`.importlinter`**: `root_package = archon`, Contract
  `backend-no-router-imports`, 2 `ignore_imports`-Zeilen.
- **`mypy.ini`**: `python_version = 3.11`, `warn_unused_ignores = True`,
  `check_untyped_defs = True`, `ignore_missing_imports = True`,
  `disallow_untyped_defs = False` global / `True` für `archon.services.*`.
- **CI-Status (aus `.github/workflows/ci.yml`, nicht geraten):**
  - Hartes Gate: ruff (Zeilen 496/514), mypy (527/540), bandit (448),
    pip-audit (444).
  - Coverage (553): „pytest muss laufen", `coverage report` **ohne
    `--fail-under`** → kein erzwungener Prozentwert (im Guide so festgehalten).
  - Kein Gate: vulture, radon, import-linter, detect-secrets, semgrep, pyright.
- **§0-Regel** wörtlich aus `audit_reports/00_SOLL_SPEC.md` Zeilen 26–33 übernommen.
- **Zertifikatsregel** aus `docs/system/ROADMAP_2026.md`, Ideen-Pool Zeile 743:
  Zertifikat erst bei vollständig sauberem Stand — jetzt nicht.

---

## 3. Was **nicht** möglich / nicht getan wurde

- **Shell gesperrt:** `pwsh.exe: Zugriff verweigert (os error 5)`. Daher
  **keine** `.venv\Scripts\*.exe --version`-Aufrufe. Versionen ohne Lock-Eintrag
  stehen als „lokal installiert, Version im Scan-Log"; keine Version erfunden.
- **Keine Scans selbst ausgeführt.** Die 10 parallelen Scan-Agenten schreiben
  ausschliesslich nach `audit_reports/tool_scans/*.txt`; dieses Ownership wurde
  nicht angefasst.
- **Kein Clean-Code-Zertifikat** ausgestellt — der Stand ist nicht sauber und
  sechs Tools haben keinen Konsumenten/Effekt im Sinne von §0.
- **Keine Änderung** an Code, Config (`.importlinter`, `mypy.ini`, `ci.yml`,
  `requirements-*.lock.txt`), Tests, Produktiv-DB, `.env` oder Containern.
  `README.md` erhielt genau eine Linkzeile.

---

## 4. Verifikation dieser Doku

- Alle Versions-/Hash-Angaben per `read`/`grep` gegen `requirements-ci.lock.txt`
  verifiziert (Zeilennummern im Guide und in `THIRD_PARTY_LICENSES.md` genannt).
- CI-Aussagen per `read` von `.github/workflows/ci.yml` (Zeilen 440–561) belegt;
  insbesondere kein `--fail-under` bei coverage.
- Linkziele des neuen Guides und der README-Zeile existieren im Repo.
- Kein Testlauf möglich (Shell gesperrt); Doku-Änderungen sind rein textuell.

---

## 5. Offene Aufgaben (nicht in diesem Scope)

1. Nach Freigabe der Shell: `*.exe --version` nachholen und Scan-Logs gegen die
   Lock-Versionen abgleichen.
2. Hash-Pins für die sechs ungepinnten Tools ergänzen — bewusst, nicht rückwirkend
   in dieser Doku-Session.
3. Für vulture/radon/import-linter/detect-secrets/semgrep/pyright je einen
   CI-Gate mit Negativtest verdrahten, sonst bleibt es nach §0 Theater.
4. Für pyright zuerst einen Produzenten (Scan im Skript) schaffen; kein
   `pyright --strict` ohne Priorisierung.
5. Erst nach vollständig sauberem Stand: Clean-Code-Zertifikat bündeln.
