# Fix T2 — MyPy-Fehler in `archon/routers/mesh.py` und `archon/routers/auth.py` (25.11.2026)

> Subagent-Auftrag aus dem Full-Run-Output `sh_2124093e1001f5XXGxcQnlxcxm.out`.
> Exklusives Ownership eingehalten: **nur** `archon/routers/mesh.py` und
> `archon/routers/auth.py`. Keine fremden Dateien, kein `data/**`, keine
> `mypy.ini`-Aenderung, kein globales Error-Code-Disable, keine Pauschal-Ignores.
> **Keine Laufzeitveraenderung.**

## 1. Zahlen (exakt)

| Metrik | Vorher | Nachher |
|---|---:|---:|
| MyPy-Fehler `archon/routers/mesh.py` | 60 | 0 |
| MyPy-Fehler `archon/routers/auth.py` | 53 | 0 |
| Summe (Full-Run-Slice, 2 Dateien) | **113** | **0** |
| Umgeschriebene `payload = payload.model_dump()`-Zeilen | — | 23 (13 mesh + 10 auth) |
| Folgeverwendungen auf neue Variable `data` umgestellt | — | 85 Zeilen |
| Neue `# type: ignore`-Kommentare | — | **0** |

## 2. Methode

Der Fehlerkern war in beiden Dateien identisch: Ein Pydantic-Request-Modell
wurde in der Parameter-Variable `payload` durch ein Dict ersetzt
(`payload = payload.model_dump()`). MyPy behaelt daraufhin den deklarierten
Modelltyp bei und meldet `[assignment]` plus eine Kaskade von
`[attr-defined]` / `[index]` / `[operator]` an allen Folgezugriffen.

- Alle 23 Zuweisungen wurden auf eine **neue lokale Variable `data`** umgestellt;
  alle Zugriffe innerhalb derselben Funktion (`data.get(...)`, `data[...]`,
  `key in data`) folgen. Die FastAPI-Signatur bleibt unveraendert
  (`payload: XxxRequest = Body(...)`).
- Nicht angefasst: `api_ingest_inbound_event` in `mesh.py` (dort ist `payload`
  bereits von Anfang an ein Dict aus `inbound.model_dump()`) und die lokale
  Audit-Payload in `auth.py`.

### Gezielte Einzelfixes (ohne Ignore)

- `auth.py:442/443` (`api_auth_create_user`): `username`/`password` sind in
  `AuthCreateUserRequest` **Pflichtfelder** und damit nach `model_dump()` immer
  vorhanden. `data["username"]` / `data["password"]` statt `data.get(...)`
  beseitigt `[arg-type]` (erwartet `str`, `.get()` lieferte `Any | None`) und
  ist verhaltensidentisch.
- `mesh.py:220` (`api_list_skill_proposals`): `status` ist `Optional[str]`,
  `list_proposals` erwartet `str`. `status or ""` ist verhaltensidentisch,
  weil die Implementation mit `if status:` filtert und `None` wie `""`
  behandelt (alle Vorschlaege). Kein Ignore noetig.
- Kommentar in `api_execute_sandbox` auf `in data` korrigiert (Dokumentation
  der umgestellten Variable, keine Code-Aenderung).

Session-/RBAC-Logik in `auth.py` (`get_current_user_from_request`,
`require_admin`, `require_operator_or_admin`, `_resolve_target_passkey_user`,
alle HITL-/Passkey-Gates) ist **unveraendert** geblieben.

## 3. Verifikation

| Gate | Kommando | Ergebnis |
|---|---|---|
| MyPy | `.venv\Scripts\python.exe -m mypy --no-incremental archon/routers/mesh.py archon/routers/auth.py` | `Success: no issues found in 2 source files` (0 errors, vorher 113) |
| Byte-Kompilierung | `.venv\Scripts\python.exe -m compileall -q archon/routers/mesh.py archon/routers/auth.py` | OK (Exit 0) |
| Regression | `.venv\Scripts\python.exe -m pytest -q ...` mit `ARCHON_DATA_DIR=C:\Users\micha\AppData\Local\Temp\opencode\archon_t2_data` | **nicht ausgefuehrt**: der Shell-Tool-Spawn von `C:\Users\micha\AppData\Local\Microsoft\WindowsApps\pwsh.exe` schlug mit `Zugriff verweigert (os error 5)` fehl (wiederholt, auch fuer `echo`). MyPy und compileall liefen vorher erfolgreich im selben Tool. |

Der Regression-Lauf ist nach Wiederherstellung der Shell nachzuholen (exakt):

```powershell
$env:ARCHON_DATA_DIR='C:\Users\micha\AppData\Local\Temp\opencode\archon_t2_data'
& .\.venv\Scripts\python.exe -m pytest -q tests/test_p0_auth_hardening.py tests/test_p0_api_validation_memory_mesh.py tests/test_med2_d_routers.py tests/test_auth_rbac.py tests/test_fix_r08_auth_failclosed.py tests/test_router_configure.py tests/test_fix_r09_router_guards.py
```

Es wurde bewusst **nie** `./data` als Testdatenverzeichnis verwendet.
