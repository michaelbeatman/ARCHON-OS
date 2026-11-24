# Archon OS — MASTER PLAN (Phase 2: Konsolidierung & Architektur-Bewertung)

> **Eingang:** `00_SOLL_SPEC.md` + `domain_01.md` … `domain_16.md` — 16 parallele Tiefenaudits (ein Subagent pro Domäne, alle gleichzeitig gestartet).
> **Basis:** HEAD `82851c48e387f99ca9cae55e13a5beb7a6b80f7b`, Branch `main`, Working Tree clean (nur `audit_reports/**` verändert).
> **Maßstab:** `audit_reports/00_SOLL_SPEC.md`, Skala 1 = schlecht/kaputt/disfunktional · 10 = top/funktional im Sinne des Erfinders.
> **G-05 STATUS:** **WIEDERHERGESTELLT** (User-Entscheidung 24.11.2026). `main.py` God-Object, 11k-Zeilen-Telegram-Adapter, lokaler Single-User-Default auf `127.0.0.1` und prozess-lokale Provider-Breaker bleiben für pre-1.0 bewusst akzeptiert und gehen **nicht** in die Bewertung ein. n8n-Stubs sind nicht in der User-Liste und bleiben regulär bewertet (G-05a).
> **Vorläufer archiviert:** `audit_reports/_archiv_2026-11-24_pre_audit/` (ursprünglicher 16-Domänen-Lauf, `reaudit/`, `FINAL_VERIFICATION.md`, Fix-Wellen A–G).

### HANDOFF B1–B8 an Antigravity

Die 8 BLOCKER sind unverändert und werden von Antigravity direkt anhand dieses Dokuments übernommen. Kein Produktivcode wurde in dieser Welle verändert.

| ID | Domäne | Dateipfad:Zeile | Fix-Block | Kurzform |
|---|---|---|---|---|
| **B1** | D03 | `archon/routers/vault.py:106-123,191-203` | F-02 | Cross-Tenant-Vault-Fallback + fehlender Admin-Zaun |
| **B2** | D05 | `backend/audit_log.py:1400-1413,1443-1466` | F-04 | Anker-Vergiftung wäscht Tail-Löschung |
| **B3** | D06 | `archon/routers/core_settings.py:169` | F-06 | `/api/v1/jev/test`: SSRF + Key-Exfiltration |
| **B4** | D11 | `backend/llm_egress_guard.py:94-96`, `backend/audit_log.py:742-757` | F-08 | `"unknown"`-Canary bricht DispatchProof in Produktion |
| **B5** | D12 | `local_security_guard.py:228-237,146-151` | F-16 | Leere HTTP-200 des Klassifikators → `safe` |
| **B6** | D13 | `backend/workflow_dag_runner.py:1491-1501,1113-1122` | F-09 | Retry→Tool-Cycle-False-Positive blockiert DAG-Tool-Calls |
| **B7** | D14 | `archon/core/orchestration.py:1356,1373-1375,1537-1541` | F-10 | `NO_CONSENSUS` erzeugt finale Beschlussvorlage |
| **B8** | D15 | `agent_profiles.json:62`, `archon/routers/agent_chat.py:203-214` | F-18 | `negative_scope` nie im Dispatch-Prompt konsumiert |

---

## 1. Konsolidierte Befundmatrix (G-05-bereinigt)

| Domäne | B | H | M | Gesamt | Score | Schwerpunkt |
|---|---:|---:|---:|---:|---:|---|
| 01 Verdrahteter Schein | 0 | 2 | 6 | 8 | 6 | Admin-Endpunkte quittieren fehlgeschlagene Persistenz als `success`; Release-Gate ohne Konsument; 6 producerlose SSE-Eventtypen |
| 02 Orchestrierung & Routing | 0 | 2 | 10 | 12 | 7 | Semantischer Cache-Hit umgeht `evaluate_and_gate_llm_dispatch()`; Cancel-Status → `incomplete` überschrieben |
| 03 Persistenz & Vault | 1 | 9 | 17 | 27 | 4 | **Cross-Tenant-Vault-Vermischung + Viewer-Lesezugriff (B1)**; Art.17 verfehlt 11 V2-DBs und PB-Bestand; `busy_timeout`/FK-Drift |
| 04 Governance & Security | 0 | 0 | 3 | 3 | 8 | Egress-Fail-Open-Schalter mit toter `bypassed`-Abwehr; Vier-Augen-Dead-End; Art.50-Dialog ohne UI. *(Lokaler Auth-Default: G-05 akzeptiert)* |
| 05 Audit & Krypto | 1 | 4 | 4 | 9 | 5 | **Anker-Vergiftung wäscht Tail-Löschung (B2)**; Fail-Open-Prüfungen an `ENVIRONMENT=production`; `"unknown"`-Proofs |
| 06 Integrationen | 1 | 3 | 7 | 11 | 4 | **SSRF-/Key-Exfil `/api/v1/jev/test` (B3)**; 5 inaktive n8n-Stubs (G-05a); HMAC-Empfänger nicht verifizierbar |
| 07 Error & Recovery | 0 | 5 | 7 | 12 | 5 | Drei `success`-Signale in Fehlerpfaden; keine 90-s-Kettendeadline im Stream; Checkpoint-/Cancel-Verluste |
| 08 Performance | 0 | 2 | 9 | 11 | 5 | Beleg-Upload blockiert Event-Loop ~24 s; Health-Probe ~3 s; 4 HTTP-Client-Pools ohne `aclose()` |
| 09 Standards | 0 | 2 | 8 | 10 | 7 | XSS-Sink im Druck-Pfad; ungepinnte CI-Test-Tooling; Node-20-Typen; Ruff-Konfigurationswiderspruch. *(God-Object + 11k-Adapter: G-05 akzeptiert)* |
| 10 24/7-Härtung | 0 | 3 | 6 | 9 | 6 | Fail-open `/readyz`-Gate in Standard-Deploy-Pfaden; Watchdog-Supervisor wird nicht gestoppt; Alertmanager-Crashloop |
| 11 Context Drift | 1 | 3 | 10 | 14 | 5 | **`"unknown"`-Canary-Proof bricht Dispatch (B4)**; Fan-in-Korrelation am SQLite-Reload verloren; erfundenes Agent-Profil |
| 12 Silent Failures | 1 | 5 | 5 | 11 | 5 | **Klassifikator deutet leere 200 als `safe` (B5)**; Beleg-/Signaturpfade erfinden Finanzfakten; `cost_usd=0.0` |
| 13 Trajectory | 1 | 3 | 1 | 5 | 5 | **Retry→Tool-Cycle-False-Positive (B6)**; Flightlog-`run_id`-Namensraum; Legacy-Fan-out; kein Ticket-Token-Cap |
| 14 Entscheidungshoheit | 1 | 4 | 3 | 8 | 5 | **Fan-in erzeugt trotz `NO_CONSENSUS` Finalbeschluss (B7)**; Policy-Veto ohne Produzent; Schwellen-Invariante gebrochen |
| 15 Rollen & Prompts | 1 | 6 | 6 | 13 | 4 | **`negative_scope` nie konsumiert (B8)**; 71/71 nur 10 Boilerplates; 26 HIGH_RISK faktisch nicht aktivierbar |
| 16 Distributed Tracing | 0 | 6 | 2 | 8 | 5 | Selbst-parentender OTel-Span; 6 tote/teilweise Grenzen; Child-Span-IDs nie persistiert |
| **Summe** | **8** | **59** | **104** | **171** | **5,0** | |

**Domänen-Schnitt:** 86 / 16 = **5,4 / 10**. **Gesamt nach 6-Kriterien-Skala (§2): 5,0 / 10.**

**Hinweis zur Zählung:** Die Werte stammen aus den expliziten Zählungen der Domänenberichte, bereinigt um die drei G-05-Findings (siehe §5). Formatzeilen wurden nicht als Befunde gewertet.

### 1.1 Deduplikation (sachlich identische Root Causes)

| Cluster | Zusammengefasste Funde | Fix-Block | Priorität |
|---|---|---|---|
| **D-D1 Canary/Proof-Platzhalter** | D05/HIGH (Prompt-/Canary `"unknown"`) ≡ D05/HIGH (geblockte Proofs) ≡ D11/BLOCKER (B4) | Ein zentraler Fix in `record_llm_dispatch()` + `_proof_prompt_versions()` + allen Aufrufern | **BLOCKER** |
| **D-D2 `NO_CONSENSUS` → Final Decision** | D14/BLOCKER (B7) ≡ D02/MED (fehlende Marker) ≡ D14/MED (leere Synthese `approved`) | Ein Gate in `_run_synthesis_cascade()` + Markerproduzent | **BLOCKER** |
| **D-D3 Critique nach Konsens** | D02/MED ≡ D14/HIGH | Critique vor finale Konsensauswertung ziehen | HIGH |
| **D-D4 `tier`-Key fehlt in Events** | D02/MED ≡ D14/MED | `"tier"` in Events und Fan-in-Statements aufnehmen | MED |
| **D-D5 Success ohne Wirkung** | D01/HIGH+4 MED, D07/2 HIGH+3 MED, D12/HIGH+2 MED | Gemeinsames Prinzip (Write-Erfolg in Quittung), Fix je Modul | HIGH |
| **D-D6 XSS / unescapte Ausgabe** | D09/HIGH (`MediaBoardView`) ≡ D09/MED (`static/index.html`) | Ein Fix-Block: Escape-Hilfe + DOM-Aufbau | HIGH |
| **D-D7 Rohes Body-Dict** | D06/MED (`/api/healing/attempt`) ≡ D09/MED | Ein Pydantic-v2-Modell | MED |
| **D-D8 Langfuse v2 EOL** | D09/MED ≡ D10/MED | Entfernen aus Compose **und** Startern | MED |
| **D-D9 Production-Default-Konfiguration** | D05/HIGH (`ENVIRONMENT`-abhängige Audit-Prüfungen) ≡ D10/HIGH (`/readyz`-Gate). *(D04 Auth-Default entfällt durch G-05)* | `ENVIRONMENT=production`, `ARCHON_READINESS_PROBES=1`, Non-Loopback-Bind | HIGH |
| **D-D10 Fail-closed Tenant-Resolver** | D03/HIGH (`crm_service`) ≡ D03/HIGH (`async_write_batcher`) ≡ D03/HIGH (Art.17) | Ein zentraler Resolver ohne globalen Fallback | HIGH |
| **D-D11 `busy_timeout`/FK-SSOT-Drift** | D03/HIGH ≡ D03/HIGH | Zentrale `get_db_connection()` + CI-AST-Gate | HIGH |
| **D-D12 n8n-Stubs & HMAC-Empfänger** | D06/HIGH (5 inaktive Workflows) ≡ D06/HIGH (Receiver) ≡ D06/HIGH (Webhook-Adapter) | Ein Fix-Block: echte Nodes + aktiver HMAC-Empfänger + signierender Adapter | HIGH |
| **D-D13 `negative_scope`-Theater** | D15/BLOCKER (B8) ≡ D15/HIGH (10 Boilerplates) ≡ D15/HIGH (CI nur Präsenz) ≡ D15/HIGH (`roles.json`) | Ein Fix-Block: Generator + Dispatch-Injektion + semantisches CI-Gate | **BLOCKER** |
| **D-D14 HIGH_RISK nicht aktivierbar** | D15/HIGH (Hash-Mismatch) ≡ D15/HIGH (Art.4-Register fehlt) | Kanonischer SOUL-Hash + echtes Kompetenzregister | HIGH |
| **D-D15 Legacy Fan-out-Cap** | D13/HIGH ≡ D11/MED | Legacy-Payloads in dieselbe Cap-Menge | HIGH |

**Effektiv unique Root-Causes: ~145** (171 Funde minus ~26 sachlich identische Dubletten).

---

## 2. Reifegrad-Bewertung (Skala 1–10, G-05-bereinigt)

| Kriterium | Score | Begründung (mit Domänenbezug) |
|---|---:|---|
| **1. Funktionale Vollständigkeit (Echtbetrieb vs. Schein)** | **5** | Meisten Kernmechaniken real und gegen Code verifiziert: blockierende Gates (D01), Tool-Output-Firewall im Chokepoint, Outbox/DLQ mit CAS, atomare Restore-Kette (D03), HMAC-Warrants/Passkey/Taint (D04). Aber zentrale Versprechen sind „Theater": Release-Gate ohne Konsument (D01), `negative_scope` nie im Prompt (D15), Enforcer ohne Konsument (D12), Policy-Veto ohne Produzent (D14), n8n-Stubs inaktiv (D06). |
| **2. Multi-Agenten-Stabilität (Context/Loops/Roles)** | **4** | Starkes Fundament (Isolation, Guards vor teuren Calls, Fan-in-Latch, atomare BudgetBank, NO_CONSENSUS-Sperre im Haupt-Boardroom — D02 7/10). Aber: Retry→Tool-Cycle-False-Positive blockiert jeden DAG-Tool-Call (B6), Fan-in-Korrelation am SQLite-Reload verloren (D11), Critique zu spät (D02/D14), kein Ticket-Token-Cap (D13), HIGH_RISK-Rollen nicht aktivierbar (D15 4/10). |
| **3. Sicherheits-Härtung (Zero-Trust/Governance)** | **6** | Krypto-/Gate-Kern breit fail-closed: RBAC 503, Passkey mit Attestation/signCount, Taint-Default-Deny mit CAS, AST-Sperre, Proxy-only-Docker, Secrets-Gate grün (D04 jetzt 8/10). Verbleibend sind zwei echte BLOCKER — SSRF-/Key-Exfil-Endpunkt (B3) und Cross-Tenant-Vault (B1) — plus Egress-Fail-Open-Schalter. *(Lokaler Auth-Default ist G-05-akzeptiert und zählt nicht mehr.)* |
| **4. Fehlertoleranz & Silent-Failure-Schutz** | **4** | Zentralmodul `cancellation.py`, 30 `ZeroEgressBlockedError`-Handler, Retry-Caps, 500-Handler solide (D07). Aber drei `success`-Signale in Fehlerpfaden, Klassifikator deutet leere 200 als `safe` (B5), erfundene Finanzfakten/URLs (D12), Alertmanager-Crashloop (D10). |
| **5. Daten- & Trace-Integrität** | **4** | Starke Substanz: HMAC-Kette mit Epochen, sechs verankerte Nebenketten, `tracestate` vollständig, Trace-Spalten in Outbox/Audit/Receipts. Aber Anker-Vergiftung (B2), ENVIRONMENT-abhängige Fail-Open-Prüfungen, Art.17 verfehlt 11 DBs + PB-Bestand, selbst-parentender Span-Graph und sechs tote Tracing-Grenzen (D16). |
| **6. Code- & Architekturqualität** | **6** | Supply-Chain-Basics 2026-konform: Digest-Pinning, Hash-Lock, SHA-Actions, `npm ci`, 7/7 CI-Jobs mit DB-Isolation (D09 jetzt 7/10). Verbleibend: XSS im Druck-Pfad, ungepinnte CI-Test-Tooling, blockierendes I/O mit ~24 s Beleg-Upload und ~3 s Healthcheck (D08 5/10). *(God-Object + 11k-Adapter sind G-05-akzeptiert.)* |
| **Gesamt** | **5,0 / 10** | Ein architektonisch durchdachtes System mit starker Krypto-, RBAC- und Persistenzbasis, dessen Kernversprechen an den Übergängen nicht eingehalten wird. Die 8 BLOCKER und 59 HIGH sitzen in Hoheitsketten, Trajectory-Limits, Silent-Failure-Eskalation, Canary-Proofs, Tenant-Isolation und Rollen-SSOT. |

### Vergleich mit Vorläufen (nicht direkt vergleichbar)

| Lauf | Score | B / H / M | Bedingungen |
|---|---:|---|---|
| Ursprünglicher Masterplan (archiviert) | 5/10 | 12 / 79 / 93 | HEAD `83691375`, G-05 gültig, 16 Domänen |
| Re-Audit + Härtung (`FINAL_VERIFICATION.md`) | 7/10 | 6 / 59 / ~101 | Branch `fix/reaudit-stage1-2026-11-24`, G-05 gültig |
| Zwischenstand (G-05 aufgehoben) | 4,5/10 | 8 / 62 / 104 | HEAD `82851c48`, G-05 temporär aufgehoben |
| **Aktuell (G-05 wiederhergestellt)** | **5,0/10** | **8 / 59 / 104** | HEAD `82851c48`, G-05 bestätigt, tiefere G-03-Methodik |

> **Ehrliche Einordnung des Score-Verlaufs 9 → 7 → 5,0:** Die 9/10 stammte aus einem 10-Domänen-Audit auf altem HEAD mit einem Verifikationsstandard, den das eigene Register als „nur keine Regression, nicht fertig" beschreibt. Die 7/10 war das Ergebnis eines Re-Audits mit anschließender Härtung. Die aktuelle 5,0 basiert auf (a) neuerem HEAD, (b) 16 statt 10 Domänen — die sechs zusätzlichen kognitiven Domänen D11–D16 liegen bei 4–5/10 — und (c) einer methodisch schärferen G-03-Prüfung (Produzent + Konsument + Effekt + Test). Die Wiederherstellung von G-05 hebt von 4,5 auf 5,0; sie macht nur **drei** Funde rückgängig, nicht die methodische Vertiefung. 10/10 bleibt ohne Aufhebung von G-01/G-02 unerreichbar; nach Abarbeitung der 8 BLOCKER + 59 HIGH mit Verifikation ist **8/10** realistisch.

---

## 3. Abhängigkeits-Matrix (konfliktfreie Ausführungsreihenfolge)

Reihenfolge: **Fundament/Daten/Krypto → Orchestrierung/Hoheit → Rollen/Prompts → Integrationen/Resilienz → Verifikation.**

### Welle 0 — Fundament: Konfiguration, Datenbank, Krypto, Security

| ID | Fix-Block | Domänen | Kritikalität | Konfliktfrei, weil … |
|---|---|---|---|---|
| F-01 | Production-Default-Konfiguration (`ENVIRONMENT=production`, `ARCHON_READINESS_PROBES=1`, Non-Loopback-Bind). *Auth-Default selbst ist G-05-akzeptiert.* | D05, D10 | HIGH (D-D9) | Reine Config/Compose/Ansible-Änderung |
| F-02 | Fail-closed Tenant-Resolver + echte Vault-Isolation + Art.17 auf 11 V2-DBs und PB-Bestand (**B1**) | D03 | **BLOCKER** + 3 HIGH (D-D10) | Betrifft nur Resolver/Vault/Art.17 |
| F-03 | `busy_timeout=5000` + `foreign_keys=ON` zentral + CI-AST-Gate + Manifest versioniert | D03 | HIGH (D-D11) | DB-Layer; nach F-02 |
| F-04 | Audit-Hash-Chain: Anker auf `action='chain_head_anchor'`, `violation` im 30-s-Loop, Trigger/Anker unbedingt (**B2**) | D05 | **BLOCKER** | Krypto-Schicht; nach F-01 (Production-Kontext) |
| F-05 | Egress-Fail-Open-Schalter: nur mit Env-Opt-in + signiertem Audit, `bypassed` durchreichen | D04 | HIGH | Baut auf F-04 auf |
| F-06 | `/api/v1/jev/test`: Admin-Zaun + Pydantic-`HttpUrl` + `check_public_url` + `safe_http_request` (**B3**) | D06 | **BLOCKER** | Unabhängiger Endpunkt; nutzt F-05 |
| F-07 | XSS/unescapte Ausgabe (`MediaBoardView` + 3 `static/index.html`-Stellen) | D09 | HIGH (D-D6) | Frontend-only |

### Welle 1 — Orchestrierung, Trajektorie, Hoheit, Silent Failures

| ID | Fix-Block | Domänen | Kritikalität | Konfliktfrei, weil … |
|---|---|---|---|---|
| F-08 | Canary/Proof-Kette: echte Versionen, `stable` statt `unknown`, 8 Blockpfade auf Helper (**B4**) | D05, D11 | **BLOCKER** (D-D1) | Hängt an F-04, vor allen Dispatch-Fixes |
| F-09 | Trajectory: Retry-Hop als `node:<id>`, Tool-Hop `allow_repeat`, Flightlog-`run_id`, Ticket-Token-Cap (**B6**) | D13 | **BLOCKER** + 3 HIGH | Budget-Layer vor Hoheits-Entscheidungen |
| F-10 | `NO_CONSENSUS`-Gate in Fan-in + Markerproduzent + Critique vor Konsens + `tier` (**B7**) | D02, D14 | **BLOCKER** (D-D2/3/4) | Nach F-09 |
| F-11 | Policy-Veto-Produzent in Boardroom-Dispatch-Wrappern | D14 | HIGH | Erweitert F-10 |
| F-12 | Schwellen-Invariante symmetrisch | D14 | HIGH | Reine Policy-Engine-Änderung |
| F-13 | Fan-in-Korrelation über SQLite-Reload (5 Felder) | D11 | HIGH | Nach F-02 |
| F-14 | Legacy-Fan-out-Cap + `accept_handoff`-Konsument | D11, D13 | HIGH (D-D15) | Nach F-09 |
| F-15 | „Success ohne Wirkung"-Cluster (D01, D07, D12) | D01, D07, D12 | HIGH (D-D5) | Modulweise; nach F-04 |
| F-16 | Klassifikator: leere 200 → `RuntimeError`, `blocked`, `executed=False` (**B5**) | D12 | **BLOCKER** | Nach F-05/F-15 |
| F-17 | Keine erfundenen Fakten: Beleg-/Signatur-Pflichtfelder, `cost_unverified`, Image-502 | D12 | HIGH | Nach F-16 |

### Welle 2 — Rollen, Prompts, Handoff-Schemata

| ID | Fix-Block | Domänen | Kritikalität | Konfliktfrei, weil … |
|---|---|---|---|---|
| F-18 | `negative_scope` konsumieren: ≥60 distinct Bodies, Dispatch-Injektion, `roles.json`, semantisches Gate (**B8**) | D15 | **BLOCKER** (D-D13) | Nach F-10 |
| F-19 | HIGH_RISK aktivierbar: kanonischer SOUL-Hash + Art.-4-Register | D15 | HIGH (D-D14) | Nach F-18 |
| F-20 | Rollen-SSOT: 71/497 gegen Spec, `DEFAULT_ROLES` entfernen, EN-Scopes | D15, D02 | HIGH/MED | Reine SSOT-Änderung |
| F-21 | Unbekanntes `agent_id` → 404; strukturierte Chat-Nutzlast | D11 | HIGH | Nach F-18 |
| F-22 | `structured_output_enforcer` im Antwort-Chokepoint | D12 | HIGH | Nach F-17 |
| F-23 | Pydantic-v2-Bodies für rohe Dict-Endpunkte | D06, D09 | MED (D-D7) | Reine API-Modelle |

### Welle 3 — Integrationen, Resilienz, Observability, Performance

| ID | Fix-Block | Domänen | Kritikalität | Konfliktfrei, weil … |
|---|---|---|---|---|
| F-24 | n8n-Stubs mit echten Nodes + aktivem HMAC-Empfänger + signierendem Adapter | D06 | HIGH (D-D12) | Nach F-06/F-05 |
| F-25 | `HopResult`, keine nackten `continue`, 90-s-Kettendeadline im Stream | D06, D07 | HIGH | Nach F-24 |
| F-26 | Watchdog-Supervisor: gemeinsames `multiprocessing.Event`, `join()`/`terminate()` | D10 | HIGH | Eigener Prozess-Lifecycle |
| F-27 | Alertmanager nur mit Secrets + Testalarm; Langfuse aus Startern | D10 | HIGH/MED (D-D8) | Nach F-01 |
| F-28 | Event-Loop-Blockaden → `to_thread`/`gather` (Beleg, Health, HUD, Key-Scan, HITL, Eval, Showroom) | D08 | HIGH | Nach F-01 |
| F-29 | Zentrale HTTP-Client-Schließkette + `WeakKeyDictionary` | D08 | MED | Nach F-28 |
| F-30 | OTel-Span-Graph: echtes `child_span()`, Invariante `span_id != parent_span_id`, Persistenz | D16 | HIGH | Nach F-04/F-08 |
| F-31 | Tracing-Grenzen: Telegram, Browser, Collector, Prometheus, Export-Header | D16 | HIGH | Nach F-30 |
| F-32 | CI-Fundament: Test-Lockfile mit Hashes, Compose-Config-Digest-Gate, `@types/node@22`, Ruff-Header | D09 | MED | Reine Build-Infrastruktur. *(God-Object/Adapter: G-05, kein Fix nötig)* |

### Welle 4 — Verifikation & Abschluss

| ID | Schritt | Nachweis |
|---|---|---|
| V-01 | Jeder Fix-Block erhält einen Verhaltens- (nicht String-)Test | `pytest`, `py_compile`, `tsc --noEmit`, Compose-Config |
| V-02 | Vollständige Suite + SSOT-/Secrets-Gates | `ARCHON_TEST_DB_ISOLATION=1 pytest tests/ -q`; `build_souls_ssot.py --check`; `audit_secrets.py --all` |
| V-03 | Unabhängiges Re-Audit aller 16 Domänen gegen denselben HEAD | Neue Berichte + `FINAL_VERIFICATION.md` |
| V-04 | Reifegrad-Neubewertung mit derselben Skala | Ziel nach V-03: ≥ 8/10 |

---

## 4. Detaillierter Bericht — BLOCKER B1–B8 (Handoff)

| # | Domäne | Datei:Zeile | Befund (Soll-Ist) | Nachweis (Kurzform) | Fix |
|---:|---|---|---|---|---|
| **B1** | D03 | `archon/routers/vault.py:106-123,191-203` | S-3.2/3.6: Kein Mandantenordner → Shared-Root-Fallback für alle Mandanten; Lese-Endpunkt ohne Admin-Zaun erlaubt Viewern fremde Notizen | Z.120-123 `if os.path.isdir(tenant_dir): return tenant_dir; return root`; `obsidian_vault/` hat keine tenants-Unterordner | F-02 |
| **B2** | D05 | `backend/audit_log.py:1400-1413,1443-1466` | S-5.3: `chain_anchor_violation`-Event wird als normaler Head-Anker gelesen (`head=""`, `count=0`) → Tail-Löschung nach 30 s „gewaschen" | SQL filtert nur `category`, kein `action`; Violation-Payload hat `expected_head`, nicht `head` | F-04 |
| **B3** | D06 | `archon/routers/core_settings.py:169` | S-6.6/6.7: `/api/v1/jev/test` ohne Admin-Zaun, roher Body, unvalidierte URL → SSRF auf IMDS + Key-Exfil | `jev_router.py:168-180` nutzt `urlopen(req, timeout=5)`, kein `check_public_url()`, folgt 3xx | F-06 |
| **B4** | D11 | `backend/llm_egress_guard.py:94-96`, `backend/audit_log.py:742-757` | S-11.2/5.2: Stabile Prompts → `canary_version="unknown"`; `record_llm_dispatch()` wirft in Produktion, DispatchProof und Dispatch brechen ab | `prompt_registry.py:171-179` liefert nur `version_num`/`canary_percentage=0` → Fallback `"unknown"` → `RuntimeError` | F-08 |
| **B5** | D12 | `local_security_guard.py:228-237,146-151` | S-12.1/12.2: Leere HTTP-200 des Dual-LLM-Klassifikators → `llm_verdict="safe"`; Quarantine meldet `executed=True`, Tool-Output ungeprüft im Kontext | Z.228 `choices[0]...content` → `""`; keine Branch-Bedingung greift → `else: llm_verdict="safe"` | F-16 |
| **B6** | D13 | `backend/workflow_dag_runner.py:1491-1501,1113-1122` | S-13.2/3: Retry-Hop schreibt `agent_id` in `visited_agents`; Tool-Hop liest denselben Key ohne `allow_repeat` → `CYCLE_DETECTED` beim ersten Tool-Call | Isolationstest (Temp-DB): `retry:n1:0` → `visited=['coder']`; `tool:terminal` → `allowed=False` | F-09 |
| **B7** | D14 | `archon/core/orchestration.py:1356,1373-1375,1537-1541` | S-14.3: Fan-in nutzt Konsensverdict nur als Text; bei `NO_CONSENSUS` läuft Robert-Freigabe und erzeugt Finalbeschluss — Regelfall, da Kind-Artefakte nie Marker produzieren | `fan_consensus` nur in `f"... Konsensstatus: ..."`; kein Gate vor `robert_prompt` oder `finalize_approval` | F-10 |
| **B8** | D15 | `agent_profiles.json:62`, `archon/routers/agent_chat.py:203-214`, `core_dispatcher.py:1366` | S-15.1: `negative_scope` in 497 Artefakten produziert, aber in keinem Produktiv-Dispatch konsumiert; Prompt ist identischer 4-Zeilen-Block für alle 71 Profile | `grep -r negative_scope --include=*.py` → nur Generator/Tests; `agent_chat.py:203` nutzt `prof.get("system_prompt")` | F-18 |

**HIGH-Cluster (59 gesamt) — siehe §1 und die 16 Domänenberichte für Nachweise und Fix-Pläne im Pflichtformat**
`[Kritikalität] | [Dateipfad:Zeile] | [Soll-Ist] | [Nachweis] | [Fix-Plan]`.

---

## 5. G-05-Wiederherstellung — Auswirkung auf die Bewertung

Der User hat G-05 am 24.11.2026 erneut bestätigt. Folgende drei Funde wurden daraufhin von „bewertet" auf **„AKZEPTIERT (kein Finding)"** umklassifiziert:

| Fund | Domäne | Ursprünglich | Nach G-05 | Grund |
|---|---|---|---|---|
| Unauthentifizierter lokaler Admin-Default auf `127.0.0.1` | D04 | HIGH | **akzeptiert** | Bewusster lokaler Single-User-Default für pre-1.0; Non-Loopback-Bind erzwingt weiterhin Auth |
| `main.py` God-Object (2853 Zeilen) | D09 | HIGH | **akzeptiert** | Bewusst akzeptierte Architektur für pre-1.0 |
| 11066-Zeilen-Telegram-Adapter-Patch | D09 | HIGH | **akzeptiert** | Bewusst akzeptierte Architektur für pre-1.0 |
| Prozess-lokale Provider-Breaker | D02 | kein Befund | **akzeptiert (bestätigt)** | Funktional korrekt verdrahtet; kein Score-Effekt |

**Nicht wiederhergestellt:** n8n-Stubs deaktiviert (D06, HIGH) — standen nicht in der User-Liste und bleiben regulär bewertet (G-05a). Falls gewünscht, wäre der Score mit dieser zusätzlichen Ausnahme ~5,2/10.

| Kennzahl | Vor G-05 (Zwischenstand) | Nach G-05 (aktuell) | Delta |
|---|---:|---:|---:|
| Funde | 174 | **171** | −3 |
| BLOCKER | 8 | **8** | 0 |
| HIGH | 62 | **59** | −3 |
| MED | 104 | **104** | 0 |
| D04 Score | 7/10 | **8/10** | +1 |
| D09 Score | 6/10 | **7/10** | +1 |
| Gesamt (6 Kriterien) | 4,5/10 | **5,0/10** | +0,5 |
| Domainschnitt | 5,25/10 | **5,4/10** | +0,15 |

> **Warum nur +0,5?** G-05 betrifft 3 von 171 Funden. Der Hauptunterschied zur alten 7/10 liegt nicht in G-05, sondern in der Methodik: D11–D16 (sechs zusätzliche kognitive Domänen) wurden mit der Vier-Glieder-Regel G-03 geprüft und liegen bei 4–5/10. Diese Vertiefung ist fachlich gewollt und bleibt bestehen.

---

## 6. Abschlussbemerkung

Dieser Masterplan bewertet den **Ist-Zustand**, nicht die Absicht. Alle 171 bewerteten Funde sind gegen konkreten Code am HEAD `82851c48` verifiziert (G-06). Die 8 BLOCKER B1–B8 sind unverändert und liegen als Handoff für Antigravity vor; **in dieser Welle wurde kein Produktivcode verändert** — ausschließlich `audit_reports/**`. Die Fix-Blöcke F-01 … F-32 sind konfliktfrei in vier Wellen geordnet; Welle 0 muss vor Welle 1 abgeschlossen sein, usw.

**Nächster Schritt (nicht Teil dieses Auftrags):** Antigravity übernimmt B1–B8 anhand von §4, danach Fix-Wellen F-01 … F-32 mit Verifikation gemäß Welle 4 und abschließendem Re-Audit.
