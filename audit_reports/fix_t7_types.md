# Fix T7 — MyPy-Fehler in 13 Ownership-Dateien (25.11.2026)

> Subagent-Auftrag aus dem Full-Run-Output
> `sh_2124093e1001f5XXGxcQnlxcxm.out`. Exklusives Ownership eingehalten:
> **nur** die 13 zugewiesenen Dateien. Keine Datei anderer Agenten berührt,
> kein globales Disable, keine Pauschal-Ignores, kein `# mypy: ignore-errors`.

## 1. Zahlen

| Metrik | Vorher | Nachher |
|---|---:|---:|
| MyPy-Fehler in den 13 Ownership-Dateien | **117** | **0** |
| Geänderte Dateien | — | **13** |
| Neue `# type: ignore` | 0 | **0** |
| Kompilierfehler (`compileall`) | — | **0** |

Verteilung der Ausgangsfehler: marketplace 13, gateway 13, mcp_n8n_driver 13,
hermes_config 11, crm 10, import_linkedin_archive 9, operations_calendar 9,
skills 9, inbox_tools 8, plugins 8, trigger_boardroom_debate 8,
batch_library_importer 8, exceptions 8.

## 2. Was geändert wurde (nach Muster)

### `as_payload()` / `model_dump()` → neue lokale Variable
Wie vorgegeben wird das Ergebnis nicht mehr in die Model-typisierte
Parameter-Variable geschrieben, sondern in eine neue Variable; alle
Folgeverwendungen wurden umbenannt:

- `marketplace.py`: `data_payload` (2 Endpunkte)
- `gateway.py`: `data` (start / stop / config / autostart)
- `crm.py`: `data` (create / update / message)
- `hermes_config.py`: `data` (settings / raw_config)
- `skills.py`: `event_payload`, `arguments_payload`, `resolved_arguments`
- `inbox_tools.py`: `data` (config / proposal / resolve)
- `plugins.py`: `data` (toggle / settings / tool-execute)

**Wichtig:** In `inbox_tools.py` blieb die Vier-Augen-Logik unangetastet —
`requested_by=_require_session_actor(request)` ist unverändert und wird
weiterhin ausschließlich aus der verifizierten Session bezogen, nie aus dem Body.
`plugins.py` behält `get_session_actor(request)` unverändert.

### Weitere Typ-Fixes
- **Optionale Default-Werte** statt implizitem `None`: `exceptions.py` (`base`),
  `batch_library_importer.py` (`vault_dir`), `trigger_boardroom_debate.py`
  (`framework`).
- **Rückgabetyp/Feldtypen korrigiert**: `exceptions._trace_context() -> str`
  (war fälschlich `tuple`, verursachte 5 Folgefehler an `_trace_headers`);
  `marketplace.py` Import-Fallbacks via `cast(Any, None)`;
  `mcp_n8n_driver.py` `tc`-Fallback via `cast(Any, None)` und
  `CAPABILITIES: List[Dict[str, Any]]`.
- **Kontainer-Variablen annotiert**: `skills.py` Cache-Zeitstempel als `float`,
  Skill-Index als `Dict[str, str]`; `hermes_config.py` `parsed`, `existing_data`,
  `aut_sync` als `Dict[str, Any]`.
- **Namens-Kollisionen aufgelöst** (alte Variable hatte fremden Typ):
  `mcp_n8n_driver.py` `cap_webhook_path` / `tool_spec`,
  `import_linkedin_archive.py` `entry` (DictReader-Zeile vs. `csv.reader`-Zeile),
  `operations_calendar.py` `answers_raw`, `msg_id_str`.
- **None-Guards statt Union-Zugriffen**: `batch_library_importer.py`
  (`para.style`, `rootfile`), `operations_calendar.py` (`updated`, `payload_b`),
  `import_linkedin_archive.py` (`getattr(sys.stdout, "reconfigure", None)`).
- **Echter Laufzeitfehler behoben**: `operations_calendar.py` behandelte den
  Rückgabewert von `safe_http_request()` (Tuple `[status, headers, body]`) wie
  ein Dict (`.get("body")`, `.get("status")`). Vier Stellen auf korrektes
  Tuple-Unpacking umgestellt — `status_code` ist jetzt der echte HTTP-Status.
- `marketplace.py`: `template_id` auf `str(...)` normalisiert;
  `inbox_tools.py`: `command` auf `str(...)` normalisiert (beide waren `Any | None`).

## 3. Verifikation

Befehle (aus Repo-Root, `.venv` = MyPy-Toolchain, `.ci_venv` = Referenz-Interpreter
laut `mypy.ini`, dort ist `cryptography` für die HITL-Tests installiert):

```powershell
.venv\Scripts\python.exe -m mypy <13 Ownership-Dateien> --no-pretty --no-error-summary
# => (keine Ausgabe, 0 Fehler)

.venv\Scripts\python.exe -m compileall -q <13 Ownership-Dateien>
# => (keine Ausgabe, 0 Fehler)

$env:ARCHON_DATA_DIR = Join-Path $env:TEMP "archon_t7_verify_data"
$env:ARCHON_TEST_DB_ISOLATION = "1"   # conftest setzt zusätzlich ein frisches Tempverzeichnis
.ci_venv\Scripts\python.exe -m pytest -q tests/
# => 2342 passed, 16 skipped in 280.30s
```

Zusätzlich: gezielte Suite (13 relevante Testdateien, u. a. `test_fix_w2_a_security`,
`test_fix_w4_a_tracing`, `test_fix_w2_b_silent`, `test_m44_m52_m53_m25`,
`test_rbac_admin_routes_paket2`) => **479 passed, 3 skipped**.

Full-Run-Mypy (687 explizite `.py`-Dateien; `mypy .` scheitert vorbestehend an
`static/hermes-webui/__init__.py` = ungültiger Paketname): **0 Fehler in den
13 Ownership-Dateien**. Die verbleibenden Fehler liegen ausschließlich in Dateien
der sechs parallel arbeitenden Agenten und wurden nicht angefasst.

Hinweis: `.venv` hat kein `cryptography`; drei Treasury/HITL-Tests scheitern dort
bereits beim Setup (`ModuleNotFoundError`). Mit dem in `mypy.ini` als Referenz
benannten `.ci_venv` laufen alle Tests grün.

## 4. Nicht verändert

- `mypy.ini`, `pytest.ini`, `conftest.py`, `requirements*.txt`
- `./data` (Tests liefen ausschließlich gegen Temp-Verzeichnisse)
- Actor-/RBAC-Logik (Vier-Augen-Prinzip in `inbox_tools.py`)
- `plugins.py`: `get_session_actor(request)`-Basierung der Session-ID
