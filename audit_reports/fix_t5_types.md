# Fix-Report T5 — MyPy-Router-Typen (guardian / security / theme / autonomy_settings)

## Scope
Exklusive Dateien dieses Agenten (4 Dateien, 102 MyPy-Fehler im Full-Run):

- `archon/routers/guardian.py` (26 Fehler)
- `archon/routers/security.py` (26 Fehler)
- `archon/routers/theme.py` (26 Fehler)
- `archon/routers/autonomy_settings.py` (24 Fehler)

## Ursache
Pydantic-Request-Modelle wurden im Handler per `payload = payload.model_dump()` /
`payload = as_payload(payload)` mit einem `dict` **überschrieben**. Der Parameter behielt
statisch den Modell-Typ (`MaskSecretsRequest`, `PassthroughBody`, `GuardianConfigSave`, …),
während die Folgeverwendungen Dict-Operationen (`.get()`, `in`, Indexzugriff) nutzten.

## Fix (ausschließlich Typ-/Namensänderungen, keine Logikänderung)
- Das Ergebnis von `model_dump()` / `as_payload()` wird in eine neue lokale Variable
  `data` (bzw. `body` in `api_bake_theme_into_main_design`) geschrieben; alle
  Folgeverwendungen wurden correspondingly umbenannt. Die Request-Parameter bleiben
  unverändert Pydantic-modelliert.
- `security.py`: **Security-Chokepoint unverändert** — `require_admin_or_503(...)`,
  PII-Rehydrate-, Egress-Check- und RBAC-Check-Aufrufe sowie deren Defaults sind
  bytegleich geblieben. Einzig der `custom_vault`-Ausdruck erhielt einen
  Laufzeit-no-op `cast(...)` wegen der inkonsistenten Kallee-Signatur
  (`Dict[str, str] = None`); der übergebene Wert (inkl. `None`) bleibt identisch.
  Keine Policy-Logik, keine globalen `# type: ignore`, keine Pauschal-Ignores.
- `guardian.py` zusätzlich (reine Typannotationen, Werte unverändert):
  - `profiles_stats: List[Dict[str, Any]]` (sort-key liefert jetzt `Any`, vergleichbar)
  - `min_ts: float = 0` (Zeitfenster ist float), `p_cache = 0.0` und
    `grand_cache_tokens = 0.0` (Token-/Kosten-Typen konsistent)
  - `cfg: Dict[str, Any]` in `api_get_guardian_config` und `api_toggle_guardian_plugin`
  - `DEFAULT_PLUGIN_CONFIGS: Dict[str, Dict[str, Any]]` (dict(...)-Overload)

## Verifikation
- `python -m mypy --no-pretty --no-color-output archon/routers/{guardian,security,theme,autonomy_settings}.py`
  → **Success: no issues found in 4 source files** (0 Fehler, vorher 102).
  Beim Umbenennen trat in `security.py:106` ein zuvor maskierter Fehler zutage
  (`rehydrate_text(custom_vault=...)` ist als `Dict[str, str] = None` annotiert,
  verarbeitet `None` aber bewusst als "Session-Vault verwenden"). Gelöst mit einem
  no-op `cast(Dict[str, str], ...)` — **kein** `or {}`-Fallback, damit die
  Rehydrate-Policy unverändert bleibt; kein `# type: ignore`.
- `python -m compileall -q <die vier Dateien>` → **OK**.
- `pytest -q` mit `ARCHON_DATA_DIR=C:\Users\micha\AppData\Local\Temp\opencode\t5_verify_data`
  (nie `./data`): 456 passed in den routenrelevanten Suiten
  (`test_p0_api_validation_security`, `test_audit_fixes_batch`,
  `test_rbac_admin_routes_paket2`, `test_orange_b_m09_...`, `test_fix_w3_a_orchestration`)
  sowie 35 passed in `test_security_and_validation`, `test_security_hardening_routes`,
  `test_audit_b2_rbac_tenant`, `test_autonomy_engines`, `test_orange_a_security`.
  → **491 passed, 0 failed**.
