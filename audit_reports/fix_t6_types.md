# Fix T6 — MyPy-Fehler in den sechs Ownership-Dateien (25.11.2026)

> Punkt aus dem Full-Run-Output `sh_2124093e1001f5XXGxcQnlxcxm.out`; Grundlage
> `mypy.ini` und die Methodik aus `audit_reports/fix_m_b_backend_types.md`.
> **Exklusives Datei-Ownership eingehalten:** nur die 6 zugewiesenen Dateien.
> Kein `mypy.ini`-Edit, kein globales Disable, kein Pauschal-Ignore, keine
> Änderung an Dateien anderer Agenten.

## 1. Zahlen (exakt)

| Metrik | Vorher | Nachher |
|---|---:|---:|
| MyPy-Fehler in den 6 Ownership-Dateien | **100** | **0** |
| Geänderte Dateien | — | **6** |
| Zusätzliche latente Fehlerstellen (isolierter Lauf) | — | **2** (behoben) |
| Gezielte codierte Ignores mit Begründung | — | **1** (`no-redef`, PathJail-Fallback) |

Verteilung wie assigned: `routergate.py` (22), `watchdog.py` (21),
`notebooks.py` (15), `concurrency_throttle.py` (14), `corporate.py` (14),
`email_service.py` (14).

## 2. Auflösung pro Datei

| Datei | Fehler | Fix |
|---|---:|---|
| `archon/routers/routergate.py` | 22 | Vier Handler (`benchmark`, `estimate-cost`, `hedged-completion`, `bandit-outcome`): `payload = payload.model_dump()` → `data = ...`; alle Folgeverwendungen auf `data` umgestellt. Keine Endpoint-Logik, keine Defaults verändert. |
| `archon/routers/watchdog.py` | 21 | `api_save_watchdog_config`: `payload = payload.model_dump(exclude_unset=True)` → `data = ...`; alle `in`/`[]`/`.get()`-Zugriffe auf `data`. `exclude_unset`, Grenzwerte (`max(5, …)`, `max(1, …)`) und `setdefault("channels", {}).update(...)` unverändert. |
| `archon/routers/notebooks.py` | 15 | Vier `as_payload()`-Zuweisungen → `data` + Folgeumbenennung. Upload-Pfad: `isinstance(file, UploadFile)` statt Truthiness-Narrowing (`form.get()` ist `UploadFile \| str \| None`), `file.filename or ""` für den `str`-Parameter von `add_source_file`. `PathJailError`-Fallback mit gezieltem `# type: ignore[no-redef]` und Begründung — identisch mit dem bestehenden Muster in `main.py:1115`. |
| `backend/concurrency_throttle.py` | 14 | Reine Typangaben: `_CONFIG_CACHE: Mapping[str, Any]` und `_BP_CACHE: Mapping[str, Any]` (statt inferiertem `MappingProxyType[str, float \| None]`). **Event-Loop-kritisch: keine Scheduling-Logik, kein Lock, kein TTL, keine `to_thread`-Hops verändert** — nur die statische Sicht auf die unveränderlichen `(ts, cfg)`- bzw. `(ts, data)`-Paare. |
| `archon/routers/corporate.py` | 14 | Vier `as_payload()`-Zuweisungen → `data` + Folgeumbenennung. Zusätzlich `layout_raw = data.get("layout")` vor dem `isinstance`-Check, damit `save_template_layout` ein `dict` statt `Any \| dict \| None` bekommt. RBAC-Checks und `ValueError`→404-Pfade unangetastet. |
| `backend/email_service.py` | 14 | Loop-Variable im `msg.walk()`-Zweig `part` → `msg_part` (Getter `payload_bytes` → `part_payload`): `part` war im selben Scope als IMAP-Rohantwort-Tupel (`bytes \| tuple \| None`) gebunden und kollidierte mit dem `Message`-Objekt. `cast(bytes, …)` an beiden `get_payload(decode=True)`-Stellen (typeshed: `Message \| bytes \| None`) — zur Laufzeit ein No-op. Zusätzlich `import email.utils` für `parsedate_to_datetime` (Submodul war nur im Full-Run durch Fremd-Imports sichtbar). |

## 3. Verifikation (selbst ausgeführt, 25.11.2026)

| Gate | Kommando | Ergebnis |
|---|---|---|
| MyPy (6 Dateien) | `.venv\Scripts\mypy.exe --config-file mypy.ini --no-pretty archon/routers/routergate.py archon/routers/watchdog.py archon/routers/notebooks.py backend/concurrency_throttle.py archon/routers/corporate.py backend/email_service.py` | **Success: no issues found in 6 source files** |
| Syntax | `.venv\Scripts\python.exe -m compileall -q <dieselben 6 Dateien>` | **Exit 0**, keine Ausgabe |
| Full-Suite | `.ci_venv\Scripts\python.exe -m pytest tests/ -q --tb=short` | **2342 passed, 16 skipped, 2 warnings in 197.21 s** |
| Full-Sanity | `.venv\Scripts\mypy.exe --config-file mypy.ini --no-pretty archon backend utils scripts plugins` | 58 Fehler in 42 Dateien — **alle ausserhalb des Ownerships** (0 in den 6 Dateien); die übrigen 7 Agenten arbeiten parallel weiter. |

`ARCHON_DATA_DIR` war ausschliesslich das frische
`C:\Users\micha\AppData\Local\Temp\archon-t6-types-5584`. `./data/**` wurde nicht
beschrieben. `warn_unused_ignores = True` und `warn_redundant_casts = True`
bleiben erfüllt; der einzige Ignore ist codiert und direkt im Code begründet.

## 4. Bemerkungen

1. Alle 100 Fehler waren Rebindings (`model_dump()` / `as_payload()` auf den
   Parameter `payload`) oder Variablen-Scope-Konflikte. Die Umbenennung auf
   `data` ist semantisch inert — identische Keys, identische Defaults.
2. `concurrency_throttle.py` wurde bewusst **nur** annotiert. Der
   Single-Flight-Double-Check, die atomare `MappingProxyType`-Zuweisung und
   alle `asyncio.to_thread`-Hops bleiben bytegleich im Verhalten.
3. Die zwei zusätzlichen Fehler (`email_service.py:139`, `corporate.py:147`)
   wurden erst im isolierten Lauf sichtbar, weil der Full-Run Fremd-Imports
   bzw. den alten Pydantic-Typenfilter nutzte. Beide sind ebenfalls behoben.
4. Keine Pauschal-Pragmas, keine `mypy.ini`-Änderung, keine neuen Module.
