# W2-E — Silent-Failure-Schutz (Re-Audit Domäne 12)

**Datum:** 26.11.2026 · **Scope:** D12-H1, D12-M1, D12-M2, D12-M3
**Soll-Basis:** `audit_reports/00_SOLL_SPEC.md` §0 / §2.3 / §2.5 / §4,
`audit_reports/GEWICHTETE_BEFUNDLISTE.md`, `audit_reports/domain_12.md`
**NEVER_DO_LIST:** kein Coroutine-Replay, keine PostgreSQL-Migration — beides nicht verwendet.

---

## 1. Ergebnis

| ID | Befund (Kurz) | Status | Nachweis |
|---|---|---|---|
| D12-H1 | Firewall-Urteil wurde im Default verworfen; leere verschachtelte Felder/Klassifikatorfehler = `success`/`isError=false` | **Behoben** | `backend/tool_runtime.py`, `backend/mcp_gateway.py`, `archon/routers/plugins.py`, `archon/routers/operations_sysops.py` |
| D12-M1 | Deaktivierter Schema-Validator lieferte `valid=True, bypassed=True` | **Behoben** | `backend/structured_output_enforcer.py` |
| D12-M2 | Persistenzfehler nur auf stderr; Historie-Lesefehler → nacktes `[]` | **Behoben** | `backend/consensus_gate.py` |
| D12-M3 | Fehlende Juror-Scores → Default 7; fehlende `risks` → `[]` | **Behoben** | `backend/consensus_gate.py` |

**Neue Tests:** `tests/test_w2_e_firewall_contract.py` — **19/19 grün**
(`.venv\Scripts\pytest.exe tests/test_w2_e_firewall_contract.py -q`).

---

## 2. D12-H1 — Firewall-Vertrag ist jetzt der Default

### 2.1 Produzent (`backend/tool_runtime.py`)

- `guard_result(..., *, with_status=True)` — **der Default liefert das vollständige
  Urteil** (`status`, `error`, `error_code`, `result`, `security`, `empty_fields`).
  `with_status=False` ist nur noch ein expliziter, veralteter Opt-out.
  `return verdict if with_status else verdict["result"]` verwirft das Urteil nicht mehr
  implizit.
- Neue SSOT `guard_result_payload(verdict)` entpackt den gehärteten Payload für
  Konsumenten; injizierte Legacy-Guards ohne `status` bleiben kompatibel durchgereicht.
- `_guard_result_verdict()` wendet `is_empty_tool_result()` jetzt auf **verschachtelte
  Werte** an (`_walk(..., path)`). Erkannt werden leere Strings und leere Container in
  den primären Ergebnisfeldern (`result`, `content`, `output`, `text`, `data`, `payload`,
  `body`, `response`, `value`, `stdout`, `stderr`, `structuredContent`).
  - Fehlercode: `EMPTY_TOOL_RESULT` (Pfad in `empty_fields`), Vorrang vor
    Klassifikatorfehlern, damit ein leeres Feld nicht hinter einem anderen Fehler
    verschwindet.
  - **Keine Fehlalarme:** `count=0`, `errors=[]`, leere Sammlungen (`items`, `tasks`,
    `specialists`, `contacts`, …) und leere Felder innerhalb von Datensätzen
    (`tasks[0].body`) bleiben gültige Daten. Sonst wäre z. B. `archon__list_tasks`
    mit „keine Treffer" dauerhaft `error` (im Regressionslauf nachgewiesen und korrigiert).
- Bestehendes Fail-Closed-Verhalten bleibt intakt: Klassifikator-Exception →
  `TOOL_OUTPUT_CLASSIFICATION_ERROR` ohne Rohtext; Tool-`status=error` →
  `TOOL_REPORTED_ERROR`; leeres Gesamtergebnis → `EMPTY_TOOL_RESULT`.

### 2.2 Konsumenten (alle vier Pfade)

| Konsument | Vorher | Nachher |
|---|---|---|
| `backend/mcp_gateway.py::execute_tool` | `return 0, guard_result(name, res)` (Urteil verworfen) | `guard_result(..., with_status=True)`; bei `status="error"` → `{status, error, error_code, result}`; Erfolg → entpackter Payload (kompatibel mit `tools/call`-Clients) |
| `backend/mcp_gateway.py::handle_jsonrpc` (`tools/call`) | `result.get("status")` → bei String-Result `AttributeError`; `isError=false` | `isinstance`-geschützt; `isError=True`, `error_code` im Result **und** im Content-Item; String-Results ohne `.get()` sicher |
| `archon/routers/plugins.py::api_execute_plugin_tool` | hartcodiert `{"status":"success", ...}` | `with_status=True`; bei Firewall-Fehler HTTP 502 mit `error_code`; Firewall-Exception → HTTP 503; `except HTTPException: raise` verhindert, dass der generische 400er den Code frisst |
| `archon/routers/operations_sysops.py::api_call_mcp_tool` | hartcodiert `{"status":"success", ...}` | Default-Urteil geprüft; bei Firewall-Fehler HTTP 502 mit `error_code`; 503 bei Guard-Ausfall unverändert |

**Vier-Glieder-Kriterium (§0) jetzt erfüllt:** Produzent (`tool_runtime`) →
Konsumenten (MCP/Plugin/SysOps) → Effekt (`isError`/HTTP-Fehler + `error_code`) →
Verifikation (`tests/test_w2_e_firewall_contract.py`).

---

## 3. D12-M1 — Bypass ist kein Erfolg

`backend/structured_output_enforcer.py`, deaktivierter Validator:

```python
{"valid": False, "bypassed": True, "repaired": False,
 "error": "structured_output_validation_disabled", "raw_output": ..., "data": {}}
```

Damit greift der Dispatcher-Check (`valid is False`) auch im Bypass-Fall. Der
`strict_schema_validation=false`-Zweig liefert konsistent ebenfalls
`valid=False, bypassed=True`. Keine erfundenen Pflichtfelder.

---

## 4. D12-M2/M3 — Konsens-Gate

### 4.1 Persistenz (D12-M2)

- `_record_decision()` → `(persisted: bool, error_code: Optional[str])`;
  `print(..., file=sys.stderr)` ersetzt durch `logger.error`.
- Beide Aufrufer (`review_task_output`, `run_tri_agent_council`) prüfen das Ergebnis
  über `_persistence_outcome()`. Bei Schreibfehler:
  `status="error"`, `error_code="CONSENSUS_PERSISTENCE_FAILED"`, `approved=False`,
  `persisted=False` — **keine Freigabe ohne Persistenznachweis**.
- `get_consensus_history()` liefert bei Fehler
  `{"status":"error","error_code":"CONSENSUS_HISTORY_READ_FAILED","history":[],...}`
  statt nackter `[]`; Erfolg: `{"status":"ok","count":…,"history":[…]}`.
  Beschädigte `votes_json` werden mit `votes_parse_error=True` markiert.

### 4.2 Keine erfundenen Bewertungen (D12-M3)

- `review_task_output()`: fehlender/unverwertbarer `score` → `None`, fehlende `risks`
  → `None`, fehlende `critique` → `unverified_fields`. `evaluation_failed=True` +
  `needs_human_review=True`, `approved=False`, `status="needs_human_review"`.
  Ein `APPROVED` ohne Beleg wird auf `NEEDS_HUMAN_REVIEW` umgewertet.
  (`score=0` bleibt nur im Ausnahme-/REVIEW_FAILED-Pfad als Fehler-Sentinel erhalten.)
- `run_tri_agent_council()`: kein `7`-Default mehr. Fehlt ein Juror-Score oder eine
  Begründung → `avg_score=None`, `status="needs_human_review"`, `approved=False`,
  `unverified_fields=[...]`, `summary` mit „Schnitt: nicht verifiziert".
  Auch der Juror-Fallback meldet `score=None` statt `0`.
- Deaktiviertes Gate / niedrige Priorität: `risks=None`, `needs_human_review=True`
  statt beruhigendem `[]`.

---

## 5. Verifikation

```powershell
.venv\Scripts\pytest.exe tests/test_w2_e_firewall_contract.py -q
# 19 passed
.venv\Scripts\pytest.exe tests/test_fix_w2_b_silent.py tests/test_fix_w4_d2_residuals.py `
  tests/test_med2_d_routers.py tests/test_orange_b_m09_n04_n05_n06_n08_z08_d06_d15_d20.py -q
# 55+ bestanden; Details siehe §6
```

Gemockt wurden LLM-Klassifikator, `core_dispatcher`, SQLite, Plugin-Manager und
API-Key-Session — keine externen Calls, kein Replay, keine DB-Migration.

---

## 6. Bekannte Restpunkte / Follow-up (außerhalb meines Dateibesitzes)

1. **`backend/workflow_node_plugins.py:714`** (DAG-Node-Handler) ruft
   `guard_result(f"node_plugin:{id}", res)` weiterhin ohne Entpackung. Da der Default
   jetzt das Urteil ist, muss der zuständige Agent dort auf
   `guard_result_payload(verdict)` umstellen und `verdict["status"] == "error"`
   prüfen. Der zugehörige Test `test_stage1_stage3_hardening_and_bus.py::test_workflow_node_plugins_vst_discovery_and_execution`
   liest `res["status"]`/`res["planned_only"]` direkt und ist davon betroffen.
2. **`archon/routers/mesh.py:447`** verpackt `get_consensus_history()` weiterhin unter
   `{"status":"success", …}`. Bei einem strukturierten Lesefehler sollte der Router
   den Fehlerstatus durchreichen (z. B. HTTP 503). Nicht in meinem Besitz.
3. **`tests/test_fix_w4_d2_residuals.py::test_tool_runtime_finalize_records_tool_span`**
   assertet `isinstance(guard_result(...), str)` — das ist genau der alte, fehlerhafte
   Default-Vertrag. Der Test muss vom Test-Owner auf `guard_result_payload(...)`
   umgestellt werden; die Span-Assertions selbst bleiben gültig.
4. **Umgebung:** `test_fix_w2_b_silent.py::test_h12_1_guard_result_with_status_passes_firewall_verdict`
   und die `TestM48McpGateway`-Suite scheitern in dieser Sandbox an einem
   beschädigten globalen Audit-/Klassifikator-DB-Bild (`database disk image is
   malformed`, `Zero-Egress: omniroute:20128`), nicht an den W2-E-Änderungen.
   Meine Tests stubpen den Klassifikator deshalb explizit.

**Keine Commits erstellt. Keine fremden Quelldateien verändert.**
