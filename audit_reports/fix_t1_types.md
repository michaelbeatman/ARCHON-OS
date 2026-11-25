# Fix T1 — MyPy-Fehler in `backend/erp_manager.py` und `backend/corporate_manager.py` (25.11.2026)

> Subagent-Auftrag aus dem Full-Run-Output `sh_2124093e1001f5XXGxcQnlxcxm.out`.
> Exklusives Ownership eingehalten: **nur** `backend/erp_manager.py` und
> `backend/corporate_manager.py`. Keine fremden Dateien, kein `data/**`, keine
> `mypy.ini`-Aenderung, kein globales Error-Code-Disable, keine Pauschal-Ignores.
> **Keine Laufzeitveraenderung.**

## 1. Zahlen (exakt)

| Metrik | Vorher | Nachher |
|---|---:|---:|
| MyPy-Fehler `backend/erp_manager.py` | 61 | 0 |
| MyPy-Fehler `backend/corporate_manager.py` | 31 | 0 |
| Summe (Full-Run-Slice, 2 Dateien) | **92** | **0** |
| Neue `# type: ignore`-Kommentare | — | **0** |
| Neue `cast(...)` (reine Typ-Hinweise, zur Laufzeit No-Op) | — | 3 |
| Neue Helper `_as_dict(...)` (1 je Datei, verhaltensidentisch zum ternary) | — | 2 |

## 2. Methode

Der im Auftrag genannte `payload = as_payload(payload)`- / `model_dump()`-Fall
trifft auf diese beiden Dateien **nicht** zu (kein `as_payload` im Backend).
Die 92 Fehler hatten zwei andere Ursachen:

### 2.1 `dict[Any, Any]` statt `Dict[str, Any]` (Root Cause, ~80 Fehler)

Ein unannotiertes `DEFAULT_PRIMARY_COMPANY` bzw. lokale
`ex = dict(row) if row else {}`-Zuweisungen wurden von MyPy als
`dict[str, object]` / `dict[Any, Any]` inferiert. Deren `.get()` liefert
`Any | None`, woraus `[union-attr]` an `.strip()`/`.get()` und `[arg-type]` an
`int()`/`float()`/`.format_doc_number()`-/`.get_document()`-Aufrufen entstand.

Korrektur ausschliesslich durch **Typ-Annotationen** (kein Laufzeit-Effekt):

- `corporate_manager.py:27`: `DEFAULT_PRIMARY_COMPANY: Dict[str, Any]`.
  Damit sind alle `company.get(...)`-Zweige (`get_template_layout`,
  `validate_ustg_compliance`, `render_template`) einheitlich `Any` — 25 Fehler
  mit **einer Zeile** behoben (inkl. `active_cid`, `c_name`, `recipient_name`).
- `erp_manager.py`: `existing_dict` / `ex` (4 Stellen: `save_entity`,
  `save_contact`, `save_item`, `save_document`) und `ent` (`save_document`)
  auf `Dict[str, Any]` annotiert. Damit verschwanden alle
  `Any | None`-Kaskaden in den SQL-Upserts und bei `doc_type`.

### 2.2 Doppelt ausgewertetes `isinstance`-Ternary (~12 Fehler)

Muster: `x = obj.get("k") if isinstance(obj.get("k"), dict) else {}`.
MyPy kann die Verengung nicht auf den zweiten `.get()`-Aufruf im wahren
Zweig anwenden; `x` bleibt `Any | dict | None`.

Korrektur: kleiner, verhaltensidentischer Helper je Datei

```python
def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}
```

und Aufruf mit dem **einmal** ausgewerteten Wert. Ersetzt wurden 6 Stellen in
`corporate_manager.py` und 5 in `erp_manager.py` (`seller_addr/-contact/-tax/-bank`,
`snap`). Bei `ent = … else ent_detail` (nicht `else {}`) wurde stattdessen ein
lokales `ent_raw` eingefuehrt, damit derelse-Zweig exakt `ent_detail` bleibt.

### 2.3 Drei `Optional`-Rueckgaben (`[return-value]`)

`save_entity`, `save_document` (2 Pfade) deklarieren `-> Dict[str, Any]`, rufen
aber `get_entity_detail`/`get_document` (`-> Optional[Dict[str, Any]]`) auf.
Nach dem erfolgreichen Upsert existiert der Datensatz; ein `cast(Dict[str, Any], …)`
ist hier ein reiner Typ-Hinweis ohne Laufzeitwirkung (kein `or {}`, keine
Exception, kein Ignore).

### 2.4 Falsche Listenannotation

`docs_to_mark_paid: List[str] = []` speichert Tupel →
`List[Tuple[str, str]]`. Behebt `[arg-type]`, `[call-overload]` und
`[str-unpack]` in `import_bank_transactions`.

## 3. Verifikation

| Gate | Kommando | Ergebnis |
|---|---|---|
| MyPy (Pflicht) | `.venv\Scripts\mypy.exe --config-file mypy.ini backend/erp_manager.py backend/corporate_manager.py` | `Success: no issues found in 2 source files` (0 errors, vorher 92) |
| Byte-Kompilierung | `.ci_venv\Scripts\python.exe -m compileall -q backend` | OK (Exit 0) |
| Regression | `.ci_venv\Scripts\python.exe -m pytest -q …` mit `ARCHON_DATA_DIR=C:\Users\micha\AppData\Local\Temp\opencode\archon_t1_test_data` | **nicht ausgefuehrt**: der Shell-Tool-Spawn von `C:\Users\micha\AppData\Local\Microsoft\WindowsApps\pwsh.exe` schlug wiederholt mit `Zugriff verweigert (os error 5)` fehl (auch fuer `echo`). MyPy und compileall liefen im selben Tool erfolgreich. |

Der Regression-Lauf ist nach Wiederherstellung der Shell nachzuholen (exakt):

```powershell
$env:ARCHON_DATA_DIR='C:\Users\micha\AppData\Local\Temp\opencode\archon_t1_test_data'
& .\.ci_venv\Scripts\python.exe -m pytest -q tests/test_erp_manager.py tests/test_corporate_manager.py tests/test_erp_m28_exports.py tests/test_audit_fixes_batch.py tests/test_block4_legal_compliance.py tests/test_m29_template_editor.py tests/test_orange_b_r21.py tests/test_orange_b_r23.py tests/test_sanierungsplan_fixes.py
```

Es wurde bewusst **nie** `./data` als Testdatenverzeichnis verwendet.
