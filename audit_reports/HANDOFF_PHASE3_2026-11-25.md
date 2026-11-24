# HANDOFF — Phase 3 Remediation (25.11.2026)

> **Status:** Welle 1 (9 Fix-Agenten) **abgeschlossen** · Welle 2 (6 Delegations-Agenten) **läuft noch**
> **Basis:** HEAD `cee78206` (main) · G-05 wiederhergestellt · B1–B8 bereits vor dieser Welle behoben/gepusht/CI-grün
> **Für:** Antigravity (Übernahme der Restarbeiten)

---

## 1. Ausgangslage

| Welle | Agenten | Status | Ergebnis |
|---|---|---|---|
| 0 | Antigravity (vorher) | ✅ gepusht, CI 7/7 grün | B1–B8 (8 BLOCKER) |
| 1 | A1–A9 (parallel) | ✅ alle 9 zurück | **~119 direkte Fixes**, Logs `fix_a*.md` |
| 2 | D1–D6 (parallel) | 🔄 **läuft noch** | ~40 Delegationen, Logs `fix_d*.md` (folgen) |

**Wichtig:** Es wurde **nichts committet oder gepusht** — alle Änderungen liegen uncommitted im Working Tree.

---

## 2. Welle 1 — abgeschlossene Fix-Logs (alle in `audit_reports/`)

| Agent | Log | Fixes | Delegiert | Schwerpunkt |
|---|---|---:|---:|---|
| A1 | `fix_a1_config.md` | 13 | 8 | ENVIRONMENT/Readiness-Defaults, Test-Hash-Lock, Digest-Gate, Langfuse-EOL, Alertmanager, DR-Ziel |
| A2 | `fix_a2_audit.md` | 9 | 6 | `ARCHON_AUDIT_STRICT`, Platzhalter→`valid=False`, Trigger/Anker unbedingt, Spaltenkonsistenz, Verify-409, 8 Blockpfade |
| A3 | `fix_a3_persistence.md` | 27 | 6 | Art.17/11 DBs, Tenant-Resolver fail-closed, FK/busy_timeout, Konsolidierung, Restore, PB-Cleanup |
| A4 | `fix_a4_orchestration.md` | 13 | 7 | Cache-Gate, Cancel-Status, Policy-Veto, Critique vor Konsens, Autorität, B7-Vollständigkeit |
| A5 | `fix_a5_trajectory.md` | 15 | 4 | Flightlog-Spiegelung, Legacy-Cap, Token-Cap, Event-Loop-Blocks, 90-s-Deadline Stream |
| A6 | `fix_a6_security.md` | 5 | 4 | Schwellen-Invariante, Egress-Fail-Open, Vier-Augen-Belege, Art.50-Tokenbindung |
| A7 | `fix_a7_integrations.md` | 6 | 5 | 5 n8n-Stubs→echte Nodes, HMAC-Receiver, signierender Adapter, Modellliste, Deploy-Diff |
| A8 | `fix_a8_roles.md` | 17 | 12 | 71 distinct `negative_scope`, EN-Scopes, semantisches Gate, Art.4-Register, DEFAULT_ROLES entfernt |
| A9 | `fix_a9_tracing.md` | 14 | 12 | OTel child_span, Hop-Persistenz, Telegram/Browser-Kontext, Exemplare, Watchdog-Stopp, Cancel-Swallower |

**Summe Welle 1: 119 direkte Fixes.**

---

## 3. Welle 2 — laufende Delegations-Agenten (bitte Logs abholen)

| Agent | Session-ID | Log (erwartet) | Scope |
|---|---|---|---|
| D1 | `ses_df01e68a1ffdSywZ64NTkV9Vek` | `fix_d1_main.md` | `main.py`, `archon/core/runtime.py`, `process_lock.py`, `otel_tracer.py`, Receipt-Ledger, Brain/SettingsState, ConfigValidator, 2 Tests |
| D2 | `ses_df01e689fffeGGxxIKvk3Q7BDR` | `fix_d2_core.md` | `core_dispatcher.py`, `llm_egress_guard.py`, `local_security_guard.py`, `handoff_desk.py`, `operations_api.py`, `delegation.py` |
| D3 | `ses_df01e6899ffd021vYRk6GLWUMh` | `fix_d3_workflow.md` | `workflow_scheduler.py`, `workflow_dag_runner.py`, `workflow_templates.py`, `mission_control.py`, `agent_profiles.json` |
| D4 | `ses_df01e688fffemSVCNj1rJMoOES` | `fix_d4_frontend.md` | `frontend/**`, `static/index.html`, `v2_capabilities.py` |
| D5 | `ses_df01e688effeNkHqdvNLNzTyI1` | `fix_d5_ci.md` | `ci.yml`, `tests/**`, `00_SOLL_SPEC.md`, Docs, busy_timeout-Drift, `.env.example` |
| D6 | `ses_df01e688dffeHWfbL4ImkGtuvf` | `fix_d6_compliance.md` | `compliance_engine.py`, `ephemeral_sandbox.py`, `onboarding.py`, `containers.py`, `operations_keys.py`, Proxy-Cleanup |

> Diese Agenten arbeiten **ausschließlich mit `read`/`edit`/`write`/`grep`** (Shell ist blockiert). Ihre Logs erscheinen automatisch in `audit_reports/`. Bitte nach Abschluss sichten und verifizieren.

---

## 4. KRITISCH: Verifikation steht noch aus

**Alle 15 Agenten konnten `pytest`, `ruff`, `mypy`, `py_compile` und Generatoren NICHT ausführen** — durchgehender Fehler:
```
failed to spawn C:\Users\micha\AppData\Local\Microsoft\WindowsApps\pwsh.exe: Zugriff verweigert (os error 5)
```
Auch in der Koordinator-Session reproduzierbar. Die Agenten haben ausschließlich statisch (read/grep, py_compile wo möglich) verifiziert.

### Zwingend nachzuholen (mit funktionierender Shell):

```powershell
# 1. SOUL-SSOT neu generieren — A8 hat Quellen+Generatoren umgestellt, ABER NICHT ausgeführt!
.venv\Scripts\python.exe scripts/build_souls_ssot.py --sync-downstream
.venv\Scripts\python.exe scripts/build_souls_ssot.py --check
.venv\Scripts\python.exe scripts/sync_profile_ssot.py --check --json
.venv\Scripts\python.exe scripts/check_soul_ssot_drift.py --allow-missing --min-checked 568

# 2. Vollständige Testsuite
$env:ARCHON_TEST_DB_ISOLATION=1; .venv\Scripts\python.exe -m pytest tests/ -q

# 3. Lint & Types (geänderte Dateien)
.venv\Scripts\python.exe -m ruff check <geänderte Dateien>
.venv\Scripts\python.exe -m mypy --python-executable .ci_venv\Scripts\python.exe --ignore-missing-imports --follow-imports=silent <geänderte Dateien>

# 4. Pre-Flight
.venv\Scripts\python.exe scripts/validate_config.py --strict
.venv\Scripts\python.exe scripts/audit_secrets.py --all
docker compose -f docker-compose.yml config --quiet
```

**Ohne Schritt 1 wird CI ROT:** A8s neues semantisches Gate verlangt ≥60 distinct `negative_scope`-Bodies und HITL-Marker für 26 HIGH_RISK — die alten `souls/**`-Artefakte haben noch 10 Boilerplates. Außerdem `SOUL_SHA256_MISMATCH` im Inventar bis zur Regeneration.

---

## 5. Bekannte Rest-Risiken nach Welle 1+2

| Risiko | Detail | Lösung |
|---|---|---|
| **Art.4-Register `certificate_sha256: null`** | A8 hat Bootstrap-Eintrag angelegt, aber bewusst **nicht selbst signiert**. HIGH_RISK-Rollen bleiben korrekt fail-closed. | Admin muss über `POST /api/governance/ai-act/literacy-register` (Vier-Augen) verifizierten Nachweis hinterlegen. |
| **Physische Artefakte nicht gelöscht** | A3 H5: `data_corrupted.db`, `data_temp.db` (malformed, identischer Hash), `memory.db.corrupt.*`, `_corrupt_backup_20261124/`, `*.json.bak*` — Laufzeit-Cleanup ist im Code, Einmal-Löschung nicht erfolgt. | Nach Hash-Check manuell löschen. |
| **`data/agent_profiles.json` Stale-Cache** | A4 meldet Divergenz (51 vs. 71 IDs, `micha` enthält). D3 soll Reihenfolge fixen; Cache-Regeneration ggf. offen. | Aus Root-SSOT neu generieren. |
| **n8n-Startup-Hook** | A7 hat Workflows/Bundle/HMAC fertig, aber Produktiv-Startup-Einbindung (Lifespan) hängt an D1. | D1-Log prüfen. |
| **Shadow-Rollen** | A8 hat `DEFAULT_ROLES` in `roles_data.py` entfernt; Konsumenten in `brain.py`/`settings_state.py` müssen umgestellt sein (D1/D6). | Logs prüfen. |

---

## 6. Reihenfolge für Antigravity

1. **Welle-2-Logs abholen** (`fix_d1_main.md` … `fix_d6_compliance.md`) und auf `DELEGATED`Rest prüfen.
2. **SOUL-Regeneration** (Schritt 1 oben) — höchste Priorität, sonst CI rot.
3. **Test-/Lint-/Type-Gates** (Schritt 2–4) — Fehler aus den statischen Edits systematisch fixen.
4. **Rest-Artefakte/Risiken** aus §5 abarbeiten.
5. **Commit + Push + CI-Lauf** — erst wenn 7/7 grün.
6. **`MASTER_PLAN.md` aktualisieren**: Funde als `FIXED` markieren, Re-Score, `FINAL_VERIFICATION.md` schreiben (analog archiviertem Lauf).

---

## 7. Erwartete Resultate nach Abschluss

| Metrik | Vor Remediation | Ziel |
|---|---:|---:|
| BLOCKER | 8 | **0** (B1–B8 bereits) |
| HIGH | 59 | **0** |
| MED | 104 | **0** (bzw. dokumentiert akzeptiert) |
| Reifegrad | 5,0/10 | **≥ 8/10** |
| CI | 7/7 grün | 7/7 grün |

---

**Kein Produktivcode wurde in dieser Koordinator-Session direkt verändert** — alle Edits stammen von den 15 Subagenten. Kein Commit, kein Push. Antigravity übernimmt ab hier.
