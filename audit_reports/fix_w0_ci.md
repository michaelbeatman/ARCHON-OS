# Fix-Report W0/F002 — Verifikations-Grundlage (CI-Hashes, SBOM, MyPy, Docker-Kontext)

**Datum:** 25.11.2026 · **Fix-ID:** F002 (MASTER_PLAN §5, Welle W0) · **Domäne:** 09
**Quellen:** `audit_reports/domain_09.md` (M1, M2, M6, Positivliste), `audit_reports/MASTER_PLAN.md` §5 (F002/F044).

## 1. Geänderte Dateien (exklusiver Ownership-Rahmen eingehalten)

| Datei | Änderung |
|---|---|
| `requirements-ci.lock.txt` | **neu.** 61 gepinnte Pakete / 148 SHA-256-Hashes, inkl. vollständiger Transitiv-Kette von `pip-audit`, `bandit`, `ruff`, `mypy`, `coverage`, `cyclonedx-bom` und `pyyaml`/`requests`/`psutil`. |
| `mypy.ini` | **neu.** MyPy-SSOT: `python_version=3.11` (lokale `.ci_venv`), `warn_unused_ignores=True`, `check_untyped_defs=True`, `disallow_untyped_defs=False` im Legacy-Bestand, `True` für `archon.services.*` und für per-Diff neue Dateien im CI-Gate, `ignore_missing_imports=True` mit Ausnahmen für stubführende Pakete. |
| `.github/workflows/ci.yml` | Alle `pip install --upgrade pip`, `pip install pyyaml requests psutil`, `pip-audit>=`/`bandit>=` und `ruff==`/`mypy==`/`coverage==` durch `pip install --require-hashes --no-deps -r requirements-ci.lock.txt` ersetzt (5 Jobs). `pip list --format=json` → CycloneDX-1.5-JSON `sbom-python.cdx.json` + hartes `components[].hashes`-Gate. MyPy nutzt `--config-file mypy.ini`; neues Modul-Gate mit `--disallow-untyped-defs`. |
| `.github/workflows/pages.yml` | **unverändert** (geprüft: alle `uses:` mit 40-Zeichen-Commit-SHA). |
| `.dockerignore` | Ergänzt: `_archive_legacy/`, `archive/`, `scratch/`, `dist/`, `site/`, `.mypy_cache/`, `.ruff_cache/`, `.ci_venv/`, `.venv-tools/`, `quartz_app/`, `notebooklm/`, `LinkedIn-backup/`, `pocketbase-media/`. |
| `Dockerfile`, `backend/Dockerfile` | Nur Kommentarangleichung: CI und Image verwenden jetzt dieselbe No-Upgrade-/Hash-Regel. Kein Verhaltenswechsel im Image. |
| `audit_reports/fix_w0_ci.md` | **neu.** Dieser Report. |

**Nicht angefasst:** beliebige `.py`-Dateien. Kein `# mypy: ignore-errors` entfernt — das bleibt F044 (W4). Keine Gates deaktiviert, kein `continue-on-error` ergänzt.

## 2. Exakt verifiziert

| Prüfung | Status | Nachweis |
|---|---|---|
| Echte Hashes, keine Erfindung | **verifiziert** | Alle Hashes wurden zur Generierungszeit aus der offiziellen PyPI-JSON-API gelesen (`https://pypi.org/pypi/<name>/<version>/json`, Feld `urls[].digests.sha256`, Abruf 25.11.2026). Die geschriebene Datei wurde anschließend per `grep` geprüft: 61 `name==version`-Zeilen, 148 `--hash=sha256:`-Zeilen, **alle 148** entsprechen `[0-9a-f]{64}` (mit/ohne Backslash-Fortsetzung). Stichprobe von 16 Hashes aus 6 Paketen (`ruff`, `mypy`, `pip`, `requests`, `cyclonedx-bom`, `pyyaml`) wurde erneut gegen PyPI nachgeschlagen: 16/16 echt. |
| CI-Lock ist geschlossen | **verifiziert (statisch)** | Abhängigkeiten wurden aus den `Requires-Dist`-Metadaten der PyPI-JSON-Antworten mit Python-3.13-Linux-Markern aufgelöst (7 Iterationen bis Fixpunkt). Seeds: `pip=26.3`, `pyyaml=6.0.4`, `requests=2.34.2`, `psutil=7.2.2`, `pip-audit=2.10.1`, `bandit=1.9.4`, `ruff=0.17.6`, `mypy=2.4.1`, `coverage=7.17.5`, `cyclonedx-bom=9.0.0`. Überlappende Runtime-Versionen (z. B. `lxml 6.1.3`, `typing-extensions 4.16.0`) wurden mit `requirements.lock.txt` abgeglichen, damit `--no-deps` keine Versionen überschreibt. Jedes Paket hat mindestens einen Hash. |
| Keine ungepinnten Helfer mehr in `ci.yml` | **verifiziert** | `grep` auf `pip install --upgrade pip`, `pip install pyyaml`, `pip-audit>=`, `bandit>=`, `ruff==0`, `mypy==2`, `coverage==7`, `pip list --format=json`, `sbom-python.json`: 0 Treffer im ausführbaren Code (nur erläuternde Kommentare ohne diese Zeichenfolgen). |
| SBOM ist echtes CycloneDX-1.5-JSON | **verifiziert (Wiring, nicht Laufzeit)** | `cyclonedx-py requirements - --spec-version 1.5 --output-format JSON` liest beide Hash-Locks aus `stdin`; Ausgabe `sbom-python.cdx.json`. Upstream-Quelle (`cyclonedx_py/_internal/requirements.py`) verifiziert: der Requirements-Parser übernimmt `--hash=sha256` in `externalReferences[].hashes`, nicht in `component.hashes`. Der Zwischenschritt hebt genau diese echten Werte auf `components[].hashes`. Das Gate prüft `bomFormat=="CycloneDX"`, `specVersion=="1.5"`, `>=80` Komponenten und pro Komponente einen `SHA-256`-Hash mit 64 Hex-Zeichen; bei Verstoß exit ≠ 0. |
| MyPy-Konfiguration | **verifiziert (Dateiinhalt)** | `mypy.ini` enthält die geforderten Werte; `ci.yml` ruft `mypy --config-file mypy.ini` (alter Aufruf mit `--ignore-missing-imports --follow-imports=silent` entfernt). Keine Python-Datei verändert. |
| `.dockerignore` | **verifiziert** | Alle 12 geforderten Pfade vorhanden. |
| YAML-Struktur `ci.yml` / `pages.yml` | **statisch geprüft** | Keine Tabs; 51 `      - name:`-Schritte konsistent eingerückt; 10 Heredoc-Öffner `<<'PY'` und 10 zugehörige `PY`-Terminatoren; `pages.yml` unverändert. |

## 3. Ehrlich NICHT verifiziert (Umgebungslimitation)

- **Keine Shell:** `pwsh.exe: Zugriff verweigert (os error 5)` — wie bereits in `domain_09.md` und `MASTER_PLAN.md` §1 dokumentiert. Daher **nicht ausgeführt**: `pip install --require-hashes --no-deps -r requirements-ci.lock.txt`, `pip check`, `cyclonedx-py …`, `mypy`, `pytest`, `yaml.safe_load`, `docker compose config`.
- **Kein Browser-Relay verbunden** (`browse.status: connected=false`) — alternative YAML-Validierung über Browser-JavaScript war nicht möglich.
- **`yaml.safe_load` der Workflows wurde lokal nicht ausgeführt.** `ci.yml` enthält jedoch weiterhin den harten YAML-Parse-Gate (`yaml.safe_load` über `.github/workflows/*.yml` und `docker-compose*.yml`), der beim ersten CI-Lauf alle Workflows (einschließlich dieser Änderung) maschinell validiert. Falls dort ein Fehler auftaucht, ist er nicht verdeckt (`|| true` gibt es nicht).
- Die im Lockfile hinterlegten Hashes sind echte PyPI-Digests; die **vollständige Installation** mit allen Artefaktauswahlen auf einem GitHub-Runner ist erst im CI-Lauf bewiesen. Die Auswahlfilter (sdist + `none-any` + `manylinux`-cp313/abi3/py3 für x86_64/aarch64) decken die Ubuntu-Runner-CPython-3.13-Auswahl ab; musllinux-/macOS-/Windows-Wheels sind bewusst nicht enthalten.
- `mypy.ini` ist Konfiguration; die eigentliche Typprüfung bleibt durch die `# mypy: ignore-errors`-Pragmas in 43 Modulen eingeschränkt. Das Öffnen dieser Module ist F044 (W4) und **nicht** Teil dieses Fixes.

## 4. Erwartete CI-Wirkung

- M1 (ungepinnte CI-Helfer) und M2 (`pip list` als SBOM) sind im Wiring geschlossen; M6 (Build-Context) ist geschlossen.
- Positivliste aus `domain_09.md` bleibt intakt: Python 3.13 in den Jobs, 40-Zeichen-Action-Pins, aufgelöster Digest-Gate mit Negativprobe, `npm ci` + `tsc --noEmit` + Build, `pip-audit`/`bandit` ohne `continue-on-error`.
- Kein neues `continue-on-error`, keine deaktivierten Gates, keine erfundenen Hashes.
