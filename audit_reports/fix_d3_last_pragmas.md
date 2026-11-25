# Fix D3 — die letzten 3 `# mypy: ignore-errors` (25.11.2026)

> Punkt 3a-Rest aus `HANDOFF_FINAL_2026-11-25.md`; Abschluss von F044/H-09-1 nach
> `audit_reports/fix_d2_mypy.md` §4.1. Exklusives Ownership eingehalten: nur
> `core_skills_engine.py`, `local_memory_bridge.py`, `research_engine_v2.py` und
> die neue Testdatei `tests/test_fix_d3_last_pragmas.py` sowie dieser Report.
> Keine Produktiv-DB, kein `./data`, keine Doku anderer Agenten, keine
> Laufzeitveränderung, kein Replay, keine Migration.

## 1. Zahlen (exakt)

| Metrik | Vorher | Nachher |
|---|---:|---:|
| `# mypy: ignore-errors` in den 3 Root-Modulen | 3 | **0** |
| `# mypy: ignore-errors` repo-weit (Archon-Quellen) | 3 (nach D2) | **0** |
| MyPy-Fehler in den 3 Dateien | **15** | **0** |
| `# type: ignore[…]`-Zeilen neu in den 3 Dateien | 0 | **6** (davon 1 Ignore mit 2 Fehlern) |
| Neue Typ-Annotationen (ohne Laufzeitwirkung) | — | **6 Zeilen** |
| `warn_unused_ignores`-Verletzungen | — | **0** |

`mypy.ini` blieb unverändert (`python_version = 3.11`, `warn_unused_ignores = True`,
`no_implicit_optional = True`, `ignore_missing_imports = True`, `follow_imports = silent`).

Verteilung der 15 Fehler: `core_skills_engine.py` 6, `local_memory_bridge.py` 8,
`research_engine_v2.py` 1.

## 2. Auflösung (keine Laufzeitveränderung)

- **`core_skills_engine.py`** — 6 Fehler, **0 Ignores**: `Any` in den `typing`-Import
  aufgenommen; `store: Dict[Any, Any]`, `target_module: Any = None`,
  `typed_args: List[Any]`, `val: Any = args[i]` annotiert. Reine Annotationen,
  Kontrollfluss und CLI-Pfad unverändert.
- **`local_memory_bridge.py`** — 8 Fehler, **5 Ignores**: `categories: Dict[str, int]`
  als echte Annotation. Die 5 Signaturen mit präexistierendem `= None`-Default
  (Z. 821, 938, 982, 998, 1006) wurden **nicht** angefasst — `# type: ignore[assignment]`
  hält den `no_implicit_optional`-Fehler ab, ohne `Optional[...]` in eine
  bestehende API-Signatur zu schreiben. Z. 998 deckt ein Ignore zwei Fehler
  (`state_data`, `pause_reason`) ab.
- **`research_engine_v2.py`** — 1 Fehler, **1 Ignore**: SSRF-Guard
  `_is_global_ip(info[4][0])` (Z. 134) erhält `# type: ignore[arg-type]` mit
  datierter Begründung direkt darüber: `getaddrinfo` liefert für AF_INET/AF_INET6
  (SOCK_STREAM + Hostname) `str`; AF_UNIX wird hier nicht angefragt. Ein `str(...)`
  im Security-Pfad wäre eine Laufzeitänderung und wurde bewusst nicht gemacht.

## 3. Verifikation (selbst ausgeführt, 25.11.2026)

| Gate | Kommando | Ergebnis |
|---|---|---|
| MyPy (Ownership) | `.venv\Scripts\mypy.exe --config-file mypy.ini --no-pretty core_skills_engine.py local_memory_bridge.py research_engine_v2.py` | **Success: no issues found in 3 source files** |
| MyPy + neuer Test | gleicher Lauf inkl. `tests/test_fix_d3_last_pragmas.py` | **Success: no issues found in 4 source files** |
| Syntax | `.venv\Scripts\python.exe -m compileall -q <3 Module> tests\test_fix_d3_last_pragmas.py` | **Exit 0** |
| Gezielte Tests | `.ci_venv\Scripts\python.exe -m pytest tests/test_fix_d3_last_pragmas.py tests/test_fix_d2_mypy.py -q` | **7 passed in 2,54 s** (4 neue + 3 aus D2) |
| Full-Suite | `.ci_venv\Scripts\python.exe -m pytest tests/ -q --tb=short` | **2342 passed, 16 skipped, 0 failed** in 269,34 s |

`ARCHON_DATA_DIR` war ausschliesslich das frisch angelegte
`C:\Users\micha\AppData\Local\Temp\opencode\archon-d3-verify`. `./data` wurde
weder beschrieben noch in den Test-Scan einbezogen. Die 2 Warnings der
Full-Suite sind vorbestehend (Starlette-`timeout`-Deprecation und ein
nicht-awaitter Coroutine-Fallback in `trigger_boardroom_debate.py`).

## 4. Neue Datei / Befunde

`tests/test_fix_d3_last_pragmas.py` (4 Tests): prüft (1) keine Pauschal-Pragmas
in den Archon-Quellen repo-weit, (2) keine Pragma-Reste in den 3 D3-Modulen,
(3) die 6 codierten Ignores, (4) `warn_unused_ignores = True`. Der Scan prune
Hidden-Verzeichnisse (`.venv`, `.ci_venv`, `.mt-it`, `.git`) sowie `data`,
`node_modules`, `site-packages`, `archive` — ohne diesen Prune meldet der Test
fälschlich 64 Pragmas aus vendored `torch`/`setuptools`-Dateien unter
`.mt-it/mt-env` und einem `data/backups/`-Snapshots. Diese sind kein
Archon-Ownership und wurden nicht verändert.

Damit ist H-09-1 / F044 abgeschlossen: **43 → 0** Pauschal-Pragmas im Repo.
