# Fix T4 — MyPy-Typfehler in ERP-/ZUGFeRD-/Contract-Routern (25.11.2026)

> Subagent-Auftrag aus dem Full-Run-Output
> `C:\Users\micha\.local\share\opencode\shell\b1d671a3fa1a5350068c0dcbd566faeb5a40d06f\sh_2124093e1001f5XXGxcQnlxcxm.out`.
> Exklusives Ownership: **nur** `archon/routers/erp.py` (34 Fehler),
> `backend/erp_zugferd_pdf.py` (31), `archon/routers/contracts.py` (20).
> Keine Datei ausserhalb dieses Scopes beruehrt. Kein globales Disable,
> kein `# mypy: ignore-errors`, keine Pauschal-`# type: ignore`.

## 1. Muster der Fehler

Alle 85 Fehler hatten dieselbe Ursache: Ein Pydantic-Body (`Erp*Request`,
`Contract*Body`) oder ein `dict`-Wert aus einem heteroegen Dict wurde
**in derselben Variablen** vom Modell in ein Dict umgewandelt
(`payload = payload.model_dump()` / `payload = as_payload(payload)`).
Mypy behaelt danach den deklarierten Modell-Typ bei und meldet
`assignment`, `attr-defined`, `index`/`operator` sowie `arg-type` an den
Folgestellen. In `erp_zugferd_pdf.py` kam das gleiche Problem bei
`x = d.get(k) if isinstance(d.get(k), dict) else {}` vor: der zweite
`.get()`-Aufruf laesst sich nicht auf den ersten schmalern.

## 2. Aenderungen (3 Dateien)

### 2.1 `archon/routers/erp.py` — 34 Fehler

In allen zehn POST-Endpunkten:

- `payload = payload.model_dump()` → `data = payload.model_dump()`
- alle Folgeleasure `payload.get(...)` → `data.get(...)`
- `erp_manager.save_* (payload=payload, ...)` → `payload=data`
  (Dict wird weitergegeben, **nicht** das Pydantic-Modell)
- `update_sync_config(payload, ...)` → `update_sync_config(data, ...)`
- `if "pocketbase_url" in payload or ...` → `in data`

Die Request-Signatur behaelt bewusst den Namen `payload` (FastAPI-Body).
Betroffen: `save_entity`, `save_contact`, `add_interaction`, `save_item`,
`save_document`, `convert_document`, `cancel_document`,
`import_bank_statement`, `match_bank_transaction`, `sync_pocketbase`.

### 2.2 `archon/routers/contracts.py` — 20 Fehler

Analog zu ERP:

- `payload = as_payload(payload)` (bzw. `..., exclude_none=True`)
  → `data = as_payload(...)`
- alle `payload.get(...)` / `payload[...]` / `in payload` → `data`
- `ContractManager.create_or_update(payload)` → `create_or_update(data)`

Der Kommentar in `api_create_contract` wurde auf `"key" in data`
korrigiert. `delivery_payload=` als Keyword-Argument bleibt unveraendert.

### 2.3 `backend/erp_zugferd_pdf.py` — 31 Fehler

Neuer lokaler Helfer direkt nach den Layout-Konstanten:

```python
def _as_dict(value: Any) -> Dict[str, Any]:
    """Gibt ein Dict unverändert zurück, sonst ein leeres Dict (Typ-Narrowing fuer mypy)."""
    return value if isinstance(value, dict) else {}
```

Damit werden die sieben `isinstance(...get(...))`-Konstruktionen ersetzt:

- `build_zugferd_invoice_pdf`: `seller_addr`, `seller_tax`,
  `seller_bank`, `seller_contact`, `seller_reg`
- `build_corporate_template_pdf`: `meta`, `layout`

**Keine** Aenderung an Inhalten, Betraegen, Steuern, Texten oder
PDF-Struktur: der Helfer gibt bei einem Dict exakt dasselbe Dict zurueck
und sonst exakt dasselbe `{}` wie die vorherige Bedingung. GoBD-/ZUGFeRD-
Logik bleibt unveraendert.

## 3. Verifikation

| Pruefung | Status |
|---|---|
| Statische Gegenprobe gegen den Full-Run-Output | 34 + 20 + 31 = 85 Fehlerquellen identifiziert; alle 85 durch die oben beschriebenen Aenderungen abgedeckt (Shapes: `assignment`/`attr-defined`/`arg-type`/`index`/`operator`/`union-attr`). Kein Ignore, kein Disable. |
| `mypy --config-file mypy.ini <3 Dateien>` | **Nicht ausgefuehrt.** Das Shell-Tool lieferte waehrend des gesamten Runs `failed to spawn ...\pwsh.exe: Zugriff verweigert (os error 5)`. Auch einfachste Kommandos (`Get-Location`, `echo`) scheiterten; die Ursache liegt ausserhalb des Ownership-Scopes (parallele Agenten / Host-Prozess). |
| `compileall` | **Nicht ausgefuehrt** (gleiche Shell-Blockade). Die Aenderungen sind syntaktisch lokale Variablen-Umbenennungen und ein 3-Zeilen-Helfer; `read`-Kontrolle der geaenderten Bereiche ergibt gueltige Einrueckung und geschlossene Ausdruecke. |
| `pytest` mit `ARCHON_DATA_DIR=<temp>` | **Nicht ausgefuehrt** (gleiche Shell-Blockade). Es wurde bewusst **kein** `./data` verwendet oder beschrieben. Empfohlener Befehl fuer den Parent: `$env:ARCHON_DATA_DIR='<temp>'; $env:ARCHON_TEST_DB_ISOLATION='1'; .venv\Scripts\python.exe -m pytest tests/test_p0_api_validation_erp.py tests/test_erp_manager.py tests/test_erp_m28_exports.py tests/test_contract_manager.py -q`. |

Der Parent-Agent bitte die drei genannten Pruefungen im eigenen Shell-Kontext
nachholen; bei abweichenden Ergebnissen ist dieser Report zu korrigieren.

## 4. Abgrenzung

- Keine Produktiv-DB, keine `.env`, keine Container, kein `./data` beruehrt.
- Keine Aenderung an `backend/erp_manager.py`, `backend/corporate_manager.py`
  oder anderen Dateien, die im selben Full-Run Fehler melden — diese liegen
  bei anderen Agenten.
- `mypy.ini` unveraendert; keine new Modul- oder Ignore-Regel eingefuehrt.
