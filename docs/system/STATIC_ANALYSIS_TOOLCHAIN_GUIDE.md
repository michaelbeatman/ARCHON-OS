# Static Analysis Toolchain Guide

> Dev-/CI-Dokumentation zur statischen Analyse-Toolchain von Archon OS (25.11.2026).
> Quellen: `scripts/run_static_toolchain.ps1`, `.importlinter`, `mypy.ini`,
> `.github/workflows/ci.yml`, `requirements-ci.lock.txt`, `THIRD_PARTY_LICENSES.md`
> (Abschnitt 6), `docs/system/ROADMAP_2026.md` (Ideen-Pool) und
> `audit_reports/00_SOLL_SPEC.md` (§0). Alle gelisteten Tools sind
> **Dev-only, keine Produktiv-Abhängigkeit**.
>
> **Ehrlichkeitshinweis zur Erstellung:** Die Shell war in dieser
> Dokumentations-Session gesperrt (`pwsh.exe: Zugriff verweigert, os error 5`).
> Es wurden **keine** `.exe --version`-Aufrufe und **keine** Scans ausgeführt.
> Versionen stammen, wo vorhanden, aus dem tatsächlichen Hash-Lock; alle anderen
> stehen als „lokal installiert, Version im Scan-Log". Die parallelen
> Scan-Agenten schreiben ausschliesslich nach `audit_reports/tool_scans/*.txt`.
> Dieses Dokument ist reine Doku — kein Code, keine Config, keine Tests, keine
> Produktiv-DB, kein `.env`, keine Container wurden verändert.

---

## 1. §0-Regel: jedes Tool braucht Produzent → Konsument → Effekt → Verifikation

Wörtlich aus `audit_reports/00_SOLL_SPEC.md` §0 („100 % korrekt verdrahtet"):

1. **Produzent** – erzeugt Zustand / Event / Artefakt.
2. **Konsument** – liest es im echten Ablauf (nicht nur in Tests, nicht nur manuell per Endpoint).
3. **Effekt** – sichtbare/nachweisbare Wirkung (DB-Status, Datei, Webhook, Audit-Event).
4. **Verifikation** – Test oder Metrik, die Scheitern sichtbar macht.

> **Fehlt ein Glied → „Theater" / verdrahteter Schein → Befund.**

Auf Scanner angewendet:

| Glied | Bedeutung für ein Analyse-Tool |
|---|---|
| Produzent | Das Tool läuft und schreibt Befunde in `audit_reports/tool_scans/<name>.txt` (inkl. `EXIT=<code>`). |
| Konsument | Ein CI-Gate (oder ein Mensch im Review) liest den Exit-Code bzw. die Befunde **im echten Ablauf**. |
| Effekt | Der Build wird **rot** / der Merge blockiert — nicht nur eine Datei, die niemand öffnet. |
| Verifikation | Ein Negativtest: ein bewusst kaputter Fund muss das Gate zuverlässig rot werden lassen. |

Ein Tool, das nur ein `.txt` produziert, das niemand konsumiert und das nichts
blockiert, ist **Theater** — genau das meint der Ideen-Pool-Eintrag in
`docs/system/ROADMAP_2026.md`: „ein Tool ohne Konsument/Effekt ist Theater (§0) —
jedes Tool braucht einen CI-Gate, der wirklich rot werden kann".

**Zertifikat:** Ein „Clean-Code-Zertifikat" wird **erst bei einem vollständig
sauberen Stand** gebündelt und veröffentlicht (GitHub/Release) — **jetzt nicht**.
Der aktuelle Stand ist nicht sauber; die Logs enthalten Funde. Das Zertifikat
soll Best Practice werden, nicht ein Etikett für Zwischenstände.

---

## 2. Wie die Scans laufen

`scripts/run_static_toolchain.ps1` ist read-only:

```powershell
powershell -File scripts\run_static_toolchain.ps1
```

- Setzt `ARCHON_DATA_DIR` auf ein Temp-Verzeichnis
  (`C:\Users\micha\AppData\Local\Temp\opencode\archon-toolchain-scan`) — keine
  Produktiv-DB.
- Legt `audit_reports/tool_scans/` an und schreibt pro Lauf eine Datei
  `<name>.txt` via `Tee-Object`, am Ende `EXIT=<code>`.
- Kein Code wird verändert; `$ErrorActionPreference = 'Continue'`.

`mypy` hat einen eigenen, ausführlichen Gate-Guide:
[`MYPY_TYPE_GATE_GUIDE.md`](MYPY_TYPE_GATE_GUIDE.md) (SSOT `mypy.ini`).

---

## 3. Übersicht: Was findet welches Tool, wo liegt das Log, was macht die CI?

| Tool | Was es findet | 1-Zeilen-Befehl (aus dem Skript) | Log in `audit_reports/tool_scans/` | CI-Status (Stand 25.11.2026) | §0-Kette |
|---|---|---|---|---|---|
| **ruff** | Syntaxfehler, undefinierte Namen/Imports, ungenutzte Imports/Variablen, Import-Sortierung | `.venv\Scripts\ruff.exe check . --statistics --output-format concise` | `ruff.txt` | **Hartes Gate**: E9/F63/F7/F82 (`ci.yml:496`) + Changed-Files-Ratchet E,F,I ohne E501 (`ci.yml:514`) | voll (CI rot möglich) |
| **vulture** | toter Code / unerreichbare Symbole → Hinweis auf „verdrahteten Schein" | `.venv\Scripts\vulture.exe . --min-confidence 80` | `vulture.txt` | **Kein CI-Gate** — nur lokaler Read-only-Scan | unvollständig (K/E/V fehlen) |
| **radon** | Cyclomatic Complexity / God-Objects (`cc -a -s`) | `.venv\Scripts\radon.exe cc -a -s archon backend scripts utils` | `radon.txt` | **Kein CI-Gate** — nur lokaler Read-only-Scan | unvollständig (K/E/V fehlen) |
| **import-linter** | Verletzung von Layergrenzen; SSOT `.importlinter` mit Contract `backend-no-router-imports` (zwei `ignore_imports`) | `.venv\Scripts\lint-imports.exe` | `import-linter.txt` | **Kein CI-Gate** — nur lokaler Read-only-Scan | unvollständig (K/E/V fehlen) |
| **detect-secrets** | versehentlich committete Secrets/Credentials | `.venv\Scripts\detect-secrets.exe scan --all-files` | `detect-secrets.txt` | **Kein CI-Gate** — nur lokaler Read-only-Scan | unvollständig (K/E/V fehlen) |
| **bandit** | Security-Anti-Patterns; `-lll` = nur HIGH-Severity | `.venv\Scripts\bandit.exe -q -lll -r archon backend scripts utils` | `bandit.txt` | **Hartes Gate**: `bandit -q -lll -r main.py core_dispatcher.py backend archon -x tests,scripts` (`ci.yml:448`) | voll (CI rot möglich) |
| **pip-audit** | bekannte CVEs in den hash-geprüften Lockdateien | `.venv\Scripts\pip-audit.exe -r requirements.lock.txt` | `pip-audit.txt` | **Hartes Gate**: `pip-audit -r requirements.lock.txt` (`ci.yml:444`) | voll (CI rot möglich) |
| **semgrep** | Taint-/Policy-Regeln: Egress, Body-Actor, HITL-Skip; lokales Profil `p/ci` | `.venv\Scripts\semgrep.exe scan --config p/ci --quiet --metrics off archon backend` | `semgrep.txt` | **Kein CI-Gate** — nur lokaler Read-only-Scan | unvollständig (K/E/V fehlen) |
| **coverage** | nie ausgeführte Pfade (Zeilenabdeckung) | `.venv\Scripts\coverage.exe run --source=archon,backend -m pytest tests/ -q --tb=no` | `coverage.txt` + `coverage-report.txt` (`coverage report --skip-covered`) | CI-Lauf `coverage run -m pytest tests/ -q` + `coverage report` als „HARTES GATE – pytest muss laufen" (`ci.yml:553`). **Ehrlich:** kein `--fail-under` → der Prozentwert selbst ist *nicht* als Schwelle erzwungen. | teilweise (Effekt = pytest muss laufen; kein %-Gate) |
| **pyright** | strengere Typprüfung als mypy | **nicht im Skript enthalten** — vorgeschlagen: `.venv\Scripts\pyright.exe archon backend` (nicht ausgeführt) | **kein Log** (kein Scan im Skript) | **Kein CI-Gate**; Ideen-Pool: „strengere Typen, erst später", kein `pyright --strict` direkt | unvollständig (P fehlt → Theater) |
| **mypy** | Typfehler, veraltete `# type: ignore` | `.venv\Scripts\mypy.exe --config-file mypy.ini <dateien>` | eigener Gate-Guide, kein `tool_scans`-Log | **Hartes Ratchet-Gate** für geänderte und neue `.py`-Dateien (`ci.yml:527`, `ci.yml:540`) | voll (CI rot möglich) |

---

## 4. Tool-Details

### 4.1 ruff — Linting

- **Findet:** E9 (Syntaxfehler), F63/F7/F82 (ungültige Syntax, undefinierte Namen),
  dazu E/F/I im Changed-Files-Ratchet. Der Legacy-Ignore aus `ruff.toml` gilt
  laut Kommentar im CI-Workflow nicht für den Ratchet (F401/F841 greifen wieder).
- **Befehl:** `.venv\Scripts\ruff.exe check . --statistics --output-format concise`
- **Log:** `audit_reports/tool_scans/ruff.txt`
- **CI:** ja, hartes Gate (`ci.yml:496`) und Ratchet (`ci.yml:514`).
- **Verifikation:** bewusst undefinierten Namen in eine geänderte Datei einbauen →
  Ratchet muss rot werden.
- **Lizenz/Version:** MIT, Astral Software Inc.; `ruff==0.17.6` mit 3 Hash-Zeilen
  in `requirements-ci.lock.txt` (Zeile 287). Dev-only.

### 4.2 vulture — toter Code

- **Findet:** ungenutzte Funktionen, Klassen, Variablen, Attribute. Relevanz für
  §0: toter Code ist der klassische „verdrahtete Schein".
- **Befehl:** `.venv\Scripts\vulture.exe . --min-confidence 80`
- **Log:** `audit_reports/tool_scans/vulture.txt`
- **CI:** **nein**. Es gibt keinen Gate, der auf Vulture-Funde reagiert → aktuell
  Produzent ohne Konsument/Effekt → Theater-Gefahr gemäss §0.
- **Nächster Schritt (nicht jetzt):** Befunde triagieren, dann Ratchet-Gate mit
  Verifikationsnegativtest einführen.
- **Lizenz/Version:** MIT; kein Hash-Pin im CI-Lock, Version aus dem Scan-Log.
  Dev-only.

### 4.3 radon — Komplexität

- **Findet:** Cyclomatic Complexity, Blöcke und Strukturen (`cc -a -s`), damit
  God-Objects und unwartbare Hotspots.
- **Befehl:** `.venv\Scripts\radon.exe cc -a -s archon backend scripts utils`
- **Log:** `audit_reports/tool_scans/radon.txt`
- **CI:** **nein** — reiner Lokalscan, kein Schwellenwert-Gate.
- **Verifikation:** fehlt; ein Gate bräuchte eine definierte Schwelle plus Test,
  dass Überschreitung rot wird.
- **Lizenz/Version:** MIT; kein Hash-Pin im CI-Lock, Version aus dem Scan-Log.
  Dev-only.

### 4.4 import-linter — Layergrenzen

- **Findet:** verbotene Imports zwischen Paketen. SSOT ist `.importlinter`:
  `root_package = archon`, `include_external_packages = False`, Contract
  `backend-no-router-imports` (forbidden: `archon.routers`), mit zwei
  `ignore_imports` (`backend.operations_api -> archon.routers._rbac` und
  `backend.operations_api -> archon.core.provider_registry`).
- **Befehl:** `.venv\Scripts\lint-imports.exe`
- **Log:** `audit_reports/tool_scans/import-linter.txt`
- **CI:** **nein** — kein Gate; die Config existiert, wird aber nur lokal ausgewertet.
- **Verifikation:** fehlt; Negativtest wäre ein neuer `backend -> archon.routers`-Import.
- **Lizenz/Version:** MIT; kein Hash-Pin im CI-Lock, Version aus dem Scan-Log.
  Dev-only.

### 4.5 detect-secrets — Secrets im Repo

- **Findet:** wahrscheinliche API-Keys/Tokens/Credentials in Dateien (`--all-files`).
- **Befehl:** `.venv\Scripts\detect-secrets.exe scan --all-files`
- **Log:** `audit_reports/tool_scans/detect-secrets.txt`
- **CI:** **nein** — kein Gate. Wichtig: Funde dürfen nie in Produktiv-Logs oder
  nach außen kopiert werden; der Scan bleibt lokal/read-only.
- **Verifikation:** fehlt; ein Gate müsste einen Test-String mit bekanntem Secret
  zuverlässig rot werden lassen.
- **Lizenz/Version:** Apache-2.0, Yelp; kein Hash-Pin im CI-Lock, Version aus dem
  Scan-Log. Dev-only.

### 4.6 bandit — SAST

- **Findet:** Security-Anti-Patterns (z. B. `subprocess`, schwache Hashes,
  bindingsweit). `-lll` begrenzt auf HIGH-Severity.
- **Befehl:** `.venv\Scripts\bandit.exe -q -lll -r archon backend scripts utils`
- **Log:** `audit_reports/tool_scans/bandit.txt`
- **CI:** ja, hartes Gate in `ci.yml:448` (leicht anderer Scope:
  `-r main.py core_dispatcher.py backend archon -x tests,scripts`).
- **Verifikation:** bewusst unsicheres Konstrukt in eine gescannte Datei einbauen
  → Gate muss rot werden.
- **Lizenz/Version:** Apache-2.0, PyCQA/OpenStack; `bandit==1.9.4` mit 2
  Hash-Zeilen in `requirements-ci.lock.txt` (Zeile 32). Dev-only.

### 4.7 pip-audit — CVEs

- **Findet:** bekannte Schwachstellen in Abhängigkeiten der hash-geprüften
  Lockdateien (`requirements.lock.txt` im Skript und in der CI).
- **Befehl:** `.venv\Scripts\pip-audit.exe -r requirements.lock.txt`
- **Log:** `audit_reports/tool_scans/pip-audit.txt`
- **CI:** ja, hartes Gate in `ci.yml:444` („keine bekannten CVEs").
- **Verifikation:** CVE-testweise in einer isolierten Test-Lockdatei → Gate muss
  rot werden (nie an der Produktiv-Datei ausprobieren).
- **Lizenz/Version:** Apache-2.0, PyPA/Trail of Bits; `pip-audit==2.10.1` mit 2
  Hash-Zeilen in `requirements-ci.lock.txt` (Zeile 202). Dev-only.

### 4.8 semgrep — Taint-/Policy-Regeln

- **Findet:** laut Ideen-Pool Egress-, Body-Actor- und HITL-Skip-Muster. Der
  lokale Lauf verwendet das mitgelieferte `p/ci`-Regelset mit `--metrics off`
  (kein Telemetrie-Abfluss).
- **Befehl:** `.venv\Scripts\semgrep.exe scan --config p/ci --quiet --metrics off archon backend`
- **Log:** `audit_reports/tool_scans/semgrep.txt`
- **CI:** **nein** — kein Gate. Für echte Wirksamkeit wären eigene Archon-Regeln
  (Egress/HITL) statt `p/ci` nötig; das ist offen.
- **Verifikation:** fehlt; Negativtest mit einer bewusst verbotenen Egress-Stelle.
- **Lizenz/Version:** LGPL-3.0, Semgrep Inc.; kein Hash-Pin im CI-Lock, Version
  aus dem Scan-Log. Dev-only.

### 4.9 coverage — unausgeführte Pfade

- **Findet:** Zeilen, die von `pytest tests/` nie ausgeführt werden.
- **Befehl:** `.venv\Scripts\coverage.exe run --source=archon,backend -m pytest tests/ -q --tb=no`
  danach `.venv\Scripts\coverage.exe report --skip-covered`
- **Log:** `audit_reports/tool_scans/coverage.txt` und `coverage-report.txt`
- **CI:** ja im Sinne von „pytest muss laufen" (`ci.yml:553`). **Ehrlich:** ohne
  `--fail-under=<n>` gibt es keinen erzwungenen Prozentwert; die Abdeckungszahl
  ist Informationswert, kein harter Schwellenwert.
- **Verifikation:** pytest-Scheitern muss den Job rot machen; ein `%`-Gate fehlt.
- **Lizenz/Version:** Apache-2.0, Ned Batchelder; `coverage==7.17.5` mit 4
  Hash-Zeilen in `requirements-ci.lock.txt` (Zeile 68). Dev-only.

### 4.10 pyright — strengere Typen (noch nicht verdrahtet)

- **Findet:** Typfehler mit strengerer Analyse als mypy; im Ideen-Pool als
  „strengere Typen, erst später" geführt. **Kein** `pyright --strict` direkt —
  zu viele Funde ohne Priorisierung (so die Roadmap-Vorgabe).
- **Befehl:** nicht in `scripts/run_static_toolchain.ps1` enthalten; ein
  `pyright`-Scan ist **vorgeschlagen, nicht ausgeführt**.
- **Log:** **keines** unter `audit_reports/tool_scans/` — es gibt keinen Produzenten.
- **CI:** **nein**, kein Gate; mypy bleibt der einzige Typ-Gate.
- **Verifikation:** fehlt vollständig (P/K/E/V offen) → nach §0 aktuell Theater,
  wenn man es als „Toolchain" bezeichnen würde.
- **Lizenz/Version:** MIT, Microsoft; kein Hash-Pin im CI-Lock, Version unbekannt
  (Shell gesperrt). Dev-only.

---

## 5. Offene Punkte / ehrlicher Status

1. **Sechs Tools ohne CI-Gate:** vulture, radon, import-linter, detect-secrets,
   semgrep, pyright. Sie erfüllen §0 nicht; ein Gate mit Negativtest fehlt.
2. **Hash-Pins fehlen** für vulture, radon, import-linter, detect-secrets,
   semgrep, pyright. Es wird **nichts erfunden**; die Tabelle in
   `THIRD_PARTY_LICENSES.md` Abschnitt 6 weist das offen aus.
3. **Versionen ungeprüft:** keine `.exe --version`-Ausführung möglich (Shell
   gesperrt). Bei Bedarf nach Freigabe der Shell nachholen und die Scan-Logs
   gegen die Lock-Versionen abgleichen.
4. **Kein Zertifikat:** Funde sind zu erwarten; das „Clean-Code-Zertifikat" erst
   nach vollständig sauberem Stand (Ideen-Pool `ROADMAP_2026.md`).
5. **Scope dieser Session:** nur Dokumentation. Keine Änderung an
   `scripts/run_static_toolchain.ps1`, `.importlinter`, `mypy.ini`, `ci.yml`,
   Tests, Produktiv-DB, `.env` oder Containern.

---

## 6. Verweise

- Lizenzen & Hash-Pins: [`THIRD_PARTY_LICENSES.md`](../../THIRD_PARTY_LICENSES.md) (Abschnitt 6)
- Scanner-Skript: [`scripts/run_static_toolchain.ps1`](../../scripts/run_static_toolchain.ps1)
- Import-Verträge: [`.importlinter`](../../.importlinter)
- Typ-Gate: [`MYPY_TYPE_GATE_GUIDE.md`](MYPY_TYPE_GATE_GUIDE.md), [`mypy.ini`](../../mypy.ini)
- CI-Gates: [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)
- Hash-Lock: [`requirements-ci.lock.txt`](../../requirements-ci.lock.txt)
- Ideen-Pool / Zertifikatsregel: [`ROADMAP_2026.md`](ROADMAP_2026.md)
- §0-Vier-Glieder-Kriterium: [`audit_reports/00_SOLL_SPEC.md`](../../audit_reports/00_SOLL_SPEC.md)
- Scan-Logs: `audit_reports/tool_scans/*.txt` (von den parallelen Scan-Agenten)
- Doku-Fix-Report: [`audit_reports/fix_doc_toolchain.md`](../../audit_reports/fix_doc_toolchain.md)
