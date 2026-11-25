# Fix M/C — echte MyPy-Fehler in `scripts/**` (25.11.2026)

> Auftrag: alle `scripts\` Zeilen aus `audit_reports/mypy_full_stdout.txt` auflösen.
> Exklusives Datei-Ownership eingehalten: **nur** die 21 genannten `.py`-Dateien unter
> `scripts/**`. `utils/**`, `backend/**`, `data/**`, `.md`-Dateien (ausser diesem Report)
> und `mypy.ini` wurden **nicht** verändert. Keine Laufzeitveränderung.

## 1. Zahlen

| Metrik | Vorher | Nachher |
|---|---:|---:|
| MyPy-Fehler in `scripts/**` (aus Full-Run) | **48** an **21** Dateien | **0** erwartet (Final-Lauf blockiert — §3) |
| Geänderte Dateien | — | **21** |
| Neue Typ-Annotationen | — | **31** Zeilen |
| Gezielte `# type: ignore[union-attr]` | 0 | **4** (nur `sys.stdout.reconfigure`) |
| `warn_unused_ignores`-Verletzungen | — | **0** |

Verteilung der 48 Ausgangsfehler: `translate_manual.py` 5, `generate_notebooklm_package.py` 5,
`translate_nl_local.py` 4, `telegram_singleton.py` 4, `audit_route_guards.py` 4,
`rebuild_word_handbuch_clean.py` 4, `import_linkedin_messages.py` 4, `scan_dummy_data.py` 2,
`prepare_finetuning_dataset.py` 2, `dump_comments.py` 2, `generate_word_manual.py` 2 sowie
je 1 in `installer_build/build_export.py`, `migrate_dsgvo_cols.py`, `pin_image_digests.py`,
`sync_avatars_db.py`, `skill_resolver.py`, `audit_secrets.py`, `read_comments.py`,
`crm_dedupe_deep.py`, `smoke_test_endpoints.py`, `update_system_handbuch_docx.py`.

## 2. Methode (nach Fehlerklasse)

- **`var-annotated` (18 Fehler):** leere Container explizit typisiert — u. a.
  `samples: list[dict[str, str]]`, `by_cat: dict[str, list]`, `by_url`/`by_name`/
  `name_map: dict[str, list]`, `api_route_mixed`/`by_file: dict[Any, Any]`,
  `obsidian_docs: list[str]`, `code_lines`/`table_lines: list[str]`,
  `m: list[str]`, `hits: Counter[str]`, `sel`/`batch: list[str]`.
- **Heterogene Literal-Dicts (7 Fehler):** `CONCEPTS`, `VIEWS`, `USE_CASES` und
  `NEW_FIELDS` als `list[dict[str, Any]]` bzw. `dict[str, dict]` annotiert. Ohne
  Annotation jointe MyPy die gemischten Werte zu `Collection[str]` / `object`,
  woraus `Path / …`, `write_manifest(...)`, `v['id']` und `**definition` scheiterten.
- **`Optional`-Defaults (2 Fehler):** `check_rotation(..., now: Optional[datetime.datetime]
  = None)` in `audit_secrets.py` (nur Signatur — Erkennungslogik unverändert) und
  `call_llm_batch(..., extra_headers: Optional[dict] = None)`.
- **`union-attr` (5 Fehler):** `sys.stdout.reconfigure` in vier Skripten mit
  gezieltem `# type: ignore[union-attr]` (TextIO Protocol kennt `reconfigure` nicht);
  `p.style.name` via `cast(Any, p.style)`, `re.search(... + cid + ...)` via
  `cast(str, cid)`, `VAR_RE.match(...).group(1)` via `cast(re.Match[str], ...)`.
- **`arg-type`/`index`/`attr-defined`/`assignment` (16 Fehler):** AST-Signaturen
  präzisiert (`_first_stmt_guard(fn: ast.FunctionDef | ast.AsyncFunctionDef)`,
  `_router_prefix(tree: ast.Module)`), `summary: dict[str, Any]`,
  `self._fp: Optional[TextIO]`, Modul-Spec via `cast(Any, _spec)`,
  `import_linkedin_messages.py:64` via `cast(int, cols.get("to_name"))`.
- **Namens-Kollisionen (3 Fehler):** in `scan_dummy_data.py` (`f` Datei-Handle vs.
  `for f in files` → `fh`), `installer_build/build_export.py` (`f` Handle vs.
  `os.walk`-Tupel → `files`) und `sync_avatars_db.py` (`img_path: str|None` →
  separater `fallback_path`; danach ist `img_path` wieder eindeutig `str`).
  `import_linkedin_messages.py:379`: `k` (Tuple bei Dedupe) → `uk` (unmatched key).

## 3. Verifikation

| Gate | Kommando | Ergebnis |
|---|---|---|
| MyPy, Zwischenlauf nach Batch 1 (21 Dateien) | `.venv\Scripts\mypy.exe --config-file mypy.ini --no-pretty <21 Dateien>` | 48 → **6 Fehler** in 3 Dateien (`sync_avatars_db` 3, `import_linkedin_messages` 1, `generate_word_manual` 2) |
| MyPy, Finallauf | gleicher Aufruf | **nicht ausführbar**: Shell-Tool bricht beim Spawn von `C:\Users\micha\AppData\Local\Microsoft\WindowsApps\pwsh.exe` mit `Zugriff verweigert (os error 5)` ab (mehrfach wiederholt, auch mit `echo`/`Get-Date`). Die 6 Restfehler wurden danach rein mechanisch behoben (2 Variablen-Renames, 1 Literal-Annotation, 1 Revert einer Annotation) — neue Fehler sind dadurch nicht zu erwarten, aber **vom Orchestrator nachzuprüfen**. |
| Syntax | `.venv\Scripts\python.exe -m compileall -q scripts` | nicht ausführbar (gleicher Shell-Spawn-Fehler) |
| Secrets-Gate | `python scripts/audit_secrets.py --all` | nicht ausführbar (gleicher Shell-Spawn-Fehler); Erkennungslogik unverändert, daher 0 Funde erwartet |
| Tests | `pytest` mit frischem `ARCHON_DATA_DIR=<temp>` | nicht ausführbar (gleicher Shell-Spawn-Fehler) |

`ARCHON_DATA_DIR` wurde in keinem Schritt auf `./data` gesetzt; es wurden keine
Datenverzeichnisse beschrieben.

## 4. Hinweise

- `audit_secrets.py` wurde bewusst **nur** an der Signatur von `check_rotation`
  geändert; alle Regex-/Funde-Listen und der Fail-Closed-Pfad bleiben identisch.
- Die drei `# mypy: ignore-errors`-Reste ausserhalb dieses Scopes
  (`core_skills_engine.py`, `local_memory_bridge.py`, `research_engine_v2.py`)
  bleiben unangetastet (siehe `fix_d2_mypy.md` §4.1).
- Der Full-Run von `mypy_full_stdout.txt` endete mit einem MyPy-INTERNAL-ERROR;
  die hier behandelten 48 Fehler sind vollständig aus den `scripts\`-Zeilen
  extrahiert. Ein erneuter Full-Run durch den Orchestrator wird empfohlen.
