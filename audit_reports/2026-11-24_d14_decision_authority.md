# Audit D14 — Entscheidungs-Hoheit & Konfliktlösung
**Projekt:** Archon OS v0.5.7.5 · **Stand:** 24.11.2026
**Domäne:** Deterministische Tie-Breaking-Regeln, Autoritäts-Hierarchien, Policy-Validierung von Subagenten-Ergebnissen, Konsensqualität, Critique-Instanz, Vier-Augen-Prinzip, Ressourcenkonflikte, rechtliche Gates

---

## 1. Scope & Methodik

**Geprüfte Produktivquellen:** `archon/core/orchestration.py`, `archon/core/delegation.py`, `archon/routers/{boardroom,decisions,governance,guardian,operations_approvals,operations_org,mesh,autonomy_settings,auth,content_machine}.py`, `backend/{consensus_gate,approval_policy_engine,compliance_engine,delegation_isolation,epistemic_hygiene,dual_llm_sanitizer,role_budget_engine,llm_egress_guard,output_policy_linter,precedent_log,deadlock_supervisor,supervisor_rollover,content_machine,agent_router,email_service}.py`, `core_dispatcher.py`, `config/org_hierarchy.json`, `config/teams.json`, `roles.json`, `scripts/trigger_boardroom_debate.py`, relevante `tests/*`.

**Ignoriert:** `.venv*`, `.ci_venv`, `node_modules`, `.git`, `__pycache__`, `dist`, `site`, `backups`, `archive`, `_archive_legacy`, `*.bak*`, Caches.

**Vorgehen:** Reines Code-Reading. Docs/Kommentare wurden nur als Behauptungen behandelt, nicht als Beleg. Gezielt verfolgt: Aufrufketten ab `resolve_debate_consensus()`, `POST /api/boardroom/run`, `POST /api/decisions/decide`, `POST /approvals/requests/{id}/approve`, `POST /org-hierarchy`, `check_activation_allowed()`; Schreibpfade auf `kanban.db`, `boardroom_history.json`, `approval_requests`, `content_assets`; RBAC-/Session-Actor-Herkunft. Zählungen per `grep`: `config/org_hierarchy.json` = 70 `nodes` (`"id"` Z. 5–1118) + 69 `links` (`"from"` Z. 1136–1408); `roles.json` = 73 `"id"`-Einträge; `core_dispatcher.py` = 55 DE-Frameworks (Z. 1656–1726) + 55 EN (Z. 1728–1794).

**Hinweis zur Shell:** Die PowerShell-Shell war in dieser Session nicht startbar (`failed to spawn pwsh.exe: Zugriff verweigert`). Alle Befunde stammen aus `read`/`grep`/`glob` mit exakten Zeilenangaben; Zählungen sind grep-basiert.

---

## 2. Befundtabelle

| # | Dateipfad | Zeile(n) | Kritikalität | Kategorie | Technischer Nachweis | Impact | Empfehlung |
|---|---|---|---|---|---|---|---|
| 1 | `archon/routers/boardroom.py`; `core_dispatcher.py` | 308–331, 352–368; 2352–2385 | **KRITISCH** | Autoritäts-Hierarchie | `chairman_id`, `chairman_provider`, `chairman_model` und `slots` kommen unverändert aus dem Request-Body; `roles_map.get(chairman_id, ...)` akzeptiert **jeden** vorhandenen Profile-ID als Chairman. Es gibt keinen Tier-/Supervisor-Check. Der Chairman erzeugt die „Finale Entscheidung & konkreter Aktionsplan" (Z. 2357–2361, 2376). | Ein Tier-3-Spezialist kann per Body als Chairman gesetzt werden und die Synthese eines Senior-Gremiums überschreiben. Die finale Hoheit liegt bei einem LLM, nicht bei HITL. Damit ist „HITL-Vorrang gegenüber Agenten" im Boardroom-Hauptpfad nicht erzwungen. | Chairman-Auswahl serverseitig auf Tier-1/APEX-Ids begrenzen (org_hierarchy + `apex_ids`), Slot-Rollen gegen `roles.json` validieren; für riskante Frameworks verpflichtenden Owner-Decision-Task nachschalten. |
| 2 | `core_dispatcher.py`; `backend/consensus_gate.py` | 2231–2247, 2351–2376; 106–118 | **KRITISCH** | Konsens-Qualität / Tie-Breaking | `resolve_debate_consensus()` wird **nur** für `if round_num < max_rounds` als vorzeitiger Abbruch verwendet (Z. 2233–2247). Der `verdict` fließt nicht in den Synthese-Prompt (Z. 2352–2361) und nicht in die Ergebnisvalidierung ein. `NO_CONSENSUS` erzeugt trotzdem eine „Final Actionable Decision". | Das deterministische Gate ist dekorativ: widersprüchliche Agentenmeinungen werden nicht aufgelöst, sondern vom Chairman-LLM überstimmt. Gleiche Inputs können je nach Modell/Stimmung verschiedene Entscheidungen liefern → nicht reproduzierbar. | Synthese nur freigeben, wenn `verdict == CONSENSUS_REACHED`; anderenfalls dissolve/Abstimmung/HITL-Eskalation. Konsensobjekt in Prompt und Ergebnis zwingend mitführen. |
| 3 | `archon/routers/decisions.py`; `backend/content_machine.py` | 238–254, 671–674, 692–746; 1238–1283 | **KRITISCH** | Vier-Augen-Prinzip | `register_decision()` speichert keinen Ersteller-Actor (`dec` Z. 238–248; `von` nur als Telegram-Caption Z. 286 und Log Z. 826). `api_decide_decision()` prüft nur `decision`, `task_id` und `_require_admin` (Z. 665–677) und CAS-Status `offen` (Z. 699–701). Kein `approver_id != creator_id`. `approve_asset()` setzt `reviewer = actor`, ohne Vergleich mit `author` (Z. 1268–1274). | Der Ersteller kann seine eigene Entscheidung/synthese als Admin freigeben. Das beworbene Vier-Augen-Prinzip ist UI-/Prozess-Text, keine technische Sperre. | `created_by`/`requester_uid` im Decision-Block persistieren; `approver == creator` → 403 (Ausnahme nur mit dokumentiertem Notfall-Override + Audit). Analog für Content-Assets. |
| 4 | `archon/routers/decisions.py`; `archon/routers/auth.py` | 404–426, 665–705; 203–212, 228–237 | **KRITISCH** | HITL-Vorrang / Service-Token | `_DECISION_HITL_TYPEN = {"permission_gate","mission_freigabe"}` (Z. 404) — `synthesis_freigabe`, `delegation_review`, `workflow_hitl_gate` benötigen **keinen** Passkey-Proof. `_decision_session_actor_uid()` (Z. 407–426) lehnt anders als `require_session_actor()` (`_rbac.py:78–79`) **keine** Service-Tokens ab; `get_current_user_from_request()` gibt Service-Tokens `role="admin"` (auth.py Z. 203–212). | Ein interner Service-Token (und damit ein Agent-Kontext mit Service-Credential) kann Freigaben ohne menschlichen Proof erteilen. HITL ist für die Mehrzahl der Entscheidungstypen umgehbar. | `_decision_session_actor_uid()` auf `is_service` prüfen und 403; HITL-Typen auf alle `_DECISION_TYPEN` ausweiten, mindestens auf `synthesis_freigabe` und `workflow_hitl_gate`. |
| 5 | `backend/approval_policy_engine.py`; `archon/routers/operations_approvals.py` | 238–290, 342–365; 58–76 | **KRITISCH** | Policy-Selbstlockerung | `update_policy()` verlangt nur Admin + Session-Actor (Router Z. 61–64). Die einzige Invariante ist `auto_max < four_eyes_min` (Z. 262–275); Werte bis 1.000.000 sind erlaubt (Z. 260). Ein einzelner Admin kann `four_eyes_min=1_000_000`, `auto_max=999999` setzen. | Vier-Augen-Schwelle faktisch deaktiviert, ohne zweite Person, ohne Passkey, ohne HITL. `evaluate_and_enqueue()` auto-approvt dann alle Beträge < 1 Mio. (Z. 349–365). | Policy-Änderungen selbst dem Vier-Augen-/Passkey-Prozess unterwerfen; Untergrenzen/Obergrenzen gegen `settings.json` hart pinned; Änderungen mit `requires_four_eyes`-Invariante gegen Altwerte validieren. |
| 6 | `backend/consensus_gate.py`; `archon/routers/boardroom.py` | 61–118; 413–430 | **HOCH** | Konsens-Qualität / Beweissicherung | `resolve_debate_consensus()` kennt keine Felder für Autorität, Confidence, Evidenzqualität, Specialization-Weight oder Dissens-Klasse; `evidence` ist nur `(agent_id, marker)` (Z. 94/98/117). `hist_entry` speichert `transcript` + `synthesis`, aber **nicht** `res["events"]` (Z. 413–430), obwohl `consensus_reached` dort `yes_votes`, `required_votes`, `verdict`, `evidence` trägt (`core_dispatcher.py:2237–2246`). | Die Begründung der Konfliktentscheidung geht nach dem Request verloren. Kein Minority-Report, keine Nachvollziehbarkeit für GoBD/Audit. | Konsens- und Votes-Objekt in `hist_entry` und in die HMAC-Kette schreiben; strukturierte `confidence`/`evidence_refs`/`dissent` in Statements verlangen. |
| 7 | `core_dispatcher.py`; `archon/core/orchestration.py` | 2114–2123, 2191–2200, 2233–2235; 1249–1253 | **HOCH** | Tie-Breaking / Doc-Divergenz | Die Agent-Prompts fordern „klare Fachperspektive" / „Argumente hinterfragen", aber **nie** einen der Marker `KONSENS_ERREICHT` / `KEIN KONSENS` (Vergleich `consensus_gate.py:52–58`). Im Fan-in werden `work_package_N`-Statements aus Freitext-Berichten gebaut (Z. 1249–1252). | Reale Debatten liefern `total_votes=0`, `required_votes=2`, `verdict="NO_CONSENSUS"`; die „deterministische Auswertung" ist strukturell wirkungslos (siehe auch D02-Befund 6). | Marker aus strukturierten Feldern (`verdict`, `confidence`) berechnen statt aus Freitext; Produzenten verpflichtend markieren lassen. |
| 8 | `archon/core/orchestration.py`; `backend/consensus_gate.py` | 1296–1325, 1319, 1345; 169–201, 225–236 | **HOCH** | Critique-Prompt / Bias | Der Reviewer ist ein LLM desselben Dispatchers; Default-Modell `deepseek/deepseek-v4-flash-0731` (Z. 1319) — identisch mit Roberts Default (Z. 1345). Reviewer-Fehler wird nur geloggt (Z. 1324–1325) und die Synthese läuft weiter. `review_task_output()` nutzt `deepseek/deepseek-chat` (Z. 151) und ist selbst keine unabhängige Instanz. Kein Provider-/Modell-Trennzang zwischen Debattierenden, Critic und Chairman. | Self-Critique im selben Modell-/Prompt-Umfeld → systematischer Bias; Kritik ist rein beratend (nur in Roberts Prompt eingehängt, Z. 1336–1338) und kann bei Ausfall einfach verschwinden. | Critic auf anderem Provider/Modell erzwingen (z. B. `moa_reference_models`-Parser), Kritik als hartes Gate (fehlt → `blocked`), Reviewer-Output revisionssicher speichern. |
| 9 | `archon/routers/mesh.py`; `backend/autonomy_settings.py` | 285–323; 62–68 | **HOCH** | Gate-Verdrahtung | `review_task_output()` und `run_tri_agent_council()` werden repo-weit **nur** von den API-Endpunkten `POST /api/tasks/review-consensus` und `POST /api/consensus/council-vote` aufgerufen. Der konfigurierte `mode: "tri_agent_council"` (Z. 65) wird von keinem Produktivpfad gelesen. | Das „Mehr-Augen-Prinzip" ist ein Opt-in-Tool, kein Automatismus bei Delegations- oder Synthese-Ergebnissen. Ein Subagent-Ergebnis wird nie automatisch durch den Rat geprüft. | Gate in `delegation.py`/`orchestration.py` vor Ergebnisübernahme verdrahten; `mode` auswerten oder entfernen. |
| 10 | `archon/core/orchestration.py`; `backend/consensus_gate.py` | 1273–1281; 88–98, 111–118 | **HOCH** | Dissens / Minority-Report | Negative Marker werden nur als erste 10 Einträge in „Widersprueche & offene Punkte" gelistet (Z. 1275–1276). Ohne Marker folgt der Text „Keine expliziten Widerspruchs-Marker … implizite Luecken bleiben im Review" (Z. 1278–1281) — ohne dass dieses Review technisch stattfindet. | Dissens wird nur bei expliziter Marker-Kennzeichnung sichtbar; implizite Widersprüche zwischen zwei Subagent-Berichten bleiben im „Integrierten Ergebnis" (Z. 1271–1272) unkommentiert nebeneinander stehen. Minority-Report existiert nicht. | Alle Statements mit `stance`, `confidence`, `evidence_refs` strukturieren; Dissens immer vollständig (kein `[:10]`) und als eigenes Decisions-Feld persistieren. |
| 11 | `archon/core/delegation.py`; `archon/routers/boardroom.py` | 166–217, 1268–1272; 308–331 | **HOCH** | Autoritäts-Hierarchie | `_check_delegation_permission()` wertet `tier`/`team_id` aus `org_hierarchy.json` **nur** für Delegationen aus (APEX → alle; Tier 2 → eigenes Team; Tier 3 → keine). `org_hierarchy.json` `links` werden ausschließlich für Eskalationsanzeige (`resolve_supervisor`, Z. 1272) genutzt. Boardroom/Decisions prüfen weder Tier noch Supervisor. | Die Hierarchie steuert „wer darf beauftragen", aber nicht „wer darf entscheiden". Eine Senior-Freigabe ist für keine Entscheidungsebene technisch erforderlich. | Entscheidungsautorität aus demselben Tier-Modell ableiten (`min_tier` pro Decision-Typ) und in `api_decide_decision()` / Boardroom-Chairman erzwingen. |
| 12 | `archon/routers/operations_org.py`; `archon/core/delegation.py` | 703–741; 166–185 | **HOCH** | Autoritäts-Hierarchie / Mutierbarkeit | `save_org_hierarchy()` übernimmt `req.nodes` samt `tier`/`team_id` ungeprüft in `config/org_hierarchy.json` (Z. 711–719) und schreibt parallel `model`/`provider` in `agent_profiles.json` (Z. 727–738).Keine Validierung auf `tier ∈ {1,2,3}`, keine HMAC-/Audit-Schreibung. `_load_org_hierarchy_map()` konsumiert genau diese Felder (delegation.py Z. 176–181). | Ein Admin kann per UI-Payload einen Tier-3-Agenten zum Tier-1 machen und damit delegationsrechtlich escalieren — ohne zweite Person und ohne Revisionsspur. | Tier/team-ID gegen `config/teams.json` validieren; Änderungen an Autoritätsfeldern nur mit Vier-Augen + chained audit; Cache-Invalidierung explizit auslösen. |
| 13 | `archon/core/orchestration.py` | 100–131, 195–209 | **HOCH** | Ressourcenkonflikt / Lost Update | `_merge_task_delta()` ersetzt den gesamten Task im frisch geladenen Store durch den über einen langen `await` gehaltenen Snapshot: `fresh_tasks[i] = local_task` (Z. 116). `update_mission_control_data()` sichert zwar `BEGIN IMMEDIATE` (`mission_control.py:1112`), aber der Mutator selbst kennt keine Version. | Editiert ein Nutzer oder zweiter Agent während des LLM-Dispatches denselben Kanban-Card, wird dessen Änderung still überschrieben (Last-Write-Wins mit veraltetem Snapshot). | Fields-Delta statt Whole-Object-Replace; `expected_updated_at`/`revision` als CAS-Bedingung im Mutator; Konflikt → 409/Eskalation. (`content_machine.py:1268–1278` zeigt das richtige Muster.) |
| 14 | `archon/core/orchestration.py` | 250–285 | **HOCH** | Ressourcenkonflikt / Duplikat | Lease-CAS ist korrekt (`deadlock_supervisor.py:147–156`), aber: (a) `ARCHON_LEASE_FAIL_OPEN` erlaubt Dispatch ohne Claim (Z. 254–260); (b) Ausfall des `idempotency_guard` wird nur geloggt (Z. 284–285), nicht blockiert. | Zwei Worker können denselben Task ausführen und widersprüchliche Ergebnisse in dasselbe Dokument/denselben Card schreiben. | Idempotency-Fehler fail-closed behandeln; Fail-Open-Flag nur in Tests zulassen und im Produktions-Modus hart ablehnen. |
| 15 | `core_dispatcher.py` | 1587–1638 vs. 1006–1024 | **HOCH** | Policy-Verstoß / Zero-Egress | `dispatch_to_external_agent()` kehrt für `agent_id in {"hermes","odysseus","openclaw","openclaw-docker"}` vor dem OmniRoute-Pfad zurück (Z. 1606–1638). Der Compliance-/EU-AI-Act-Gate in `dispatch_to_omniroute_or_container()` (Z. 1006–1024) wird damit übersprungen. | Subagent-Ergebnisse aus Container-Dispatches durchlaufen weder `check_activation_allowed()` noch Budget-/DataClassifier-Gate an dieser Stelle. | Gate in `dispatch_to_external_agent()` vor **allen** Container-Branches ausführen oder Container-Dispatches ausschließlich über den geprüften Pfad routen. |
| 16 | `backend/compliance_engine.py` | 277–282, 292–375 | **HOCH** | Rechtliches Gate / GoBD | `check_activation_allowed()` prüft Inventar, PROHIBITED/NON_COMPLIANT, SOUL-SHA und HITL/Literacy — aber **nicht** die GoBD-Kettenintegrität. Die Prüfung existiert nur in `evaluate_guardrails()` (Z. 277–282), die für das PDF-Snapshot (`compliance_engine.py:455`) und den GET-Endpunkt (`governance.py:160–166`) genutzt wird. | Eine gebrochene GoBD-Hashkette blockiert weder Dispatch noch Freigabe. „GoBD-Status" ist Bericht, nicht Gate. | Kettenintegrität in `check_activation_allowed()` und in `api_decide_decision()` als hartes Gate ergänzen (fail-closed bei `valid=False`). |
| 17 | `backend/delegation_isolation.py`; `backend/output_policy_linter.py`; `backend/agent_router.py` | 211–327; 39–80; 694–700 | **HOCH** | Policy-Verstoß / Output-Validierung | `PolicyEngine.decide()` ist eine **Tool-Call**-Entscheidungsstelle (Parameter `tool_name`, `args`, `warrant`), keine Validierung von Subagenten-Ergebnissen. `OutputPolicyLinter` cleaned destruktive Strings per Regex und gibt `passed=False`, aber der Aufrufer übernimmt nur `cleaned_text` (agent_router Z. 697–698); bei Exception nur `logger.warning` (Z. 699–700). | Es gibt keine Policy-Prüfung von Ergebnissen auf Zero-Egress, Datenschutz, Freigabepflicht oder GoBD-Status. Verstöße werden höchstens kosmetisch bereinigt, nicht hart abgelehnt. | Ergebnis-Gate mit `data_classification`, `approval_required`, `audit_status` und `egress_zone` als Pflichtfelder; `passed=False` → `blocked`, nicht `cleaned_text`. |
| 18 | `archon/routers/decisions.py`; `backend/approval_policy_engine.py` | 699–701, 737–745; 425–426, 496–497 | **HOCH** | Appeal / Reconsider | Der CAS-Marker setzt `in_bearbeitung`, danach ist der Decision-Block terminal; spätere Aufrufe erhalten `already_decided` (Z. 737–745). `approve_request()`/`reject_request()` lehnen jede Änderung an `approved`/`rejected` ab (Z. 425–426, 496–497). Kein `reopen`, `appeal`, `reconsider` oder Widerruf von Entscheidungen (nur Präzedenzfälle sind revoked: `kanban.py:246–254`). | Widersprüchliche neue Evidenz kann eine getroffene Entscheidung nicht mehr korrigieren; das System kennt nur „neue Entscheidung anlegen", nicht „angefochtene Entscheidung überprüfen". | `appeal`-Status + zweite Freigabe mit Begründung und Link zur Ursprungsentscheidung; CAS um `appealed` erweitern; Audit-Kette verknüpfen. |
| 19 | `backend/compliance_engine.py` | 309–312, 368–375 | **HOCH** | EU-AI-Act Art. 50 | `disclosure_required` wird für unbekannte Agenten (`True`, Z. 312) und für HIGH_RISK/LIMITED_RISK/SPECIFIC_TRANSPARENCY (Z. 374) berechnet, aber repo-weit **nirgends** konsumiert (nur 2 Treffer im gesamten Code). | Die Pflicht zur Offenlegung gegenüber betroffenen Personen wird nicht technisch umgesetzt; ein High-Risk-Agent antwortet ohne KI-Kennzeichnung. | `disclosure_required` in Antwort-Header/UI-Badge/Protokoll zwingend umsetzen und bei `True` ohne Kennzeichnung blockieren. |
| 20 | `backend/consensus_gate.py` | 267–271, 306–314 | **MITTEL** | Konsens-Qualität / Modell-Trennung | Alle drei Juroren nutzen denselben `model`-Parameter (Z. 259–263, 288–295); Rollen unterscheiden sich nur im Prompt. Fehlende `score` werden mit `7` erfunden (`sum(v.get("score", 7) ...)`, Z. 309), `required_votes` ist bei `two_thirds` einfach 2 (Z. 311). | `avg_score` ist kein belastbares Confidence-Maß; drei „unabhängige" Stimmen stammen vom selben Modell/Provider (Common-Mode-Failure). | Juroren auf verschiedene Provider/Modelle verteilen; fehlende Scores als `0` und `reviewed=False` behandeln; Specialization-Weight aus `roles.json` ergänzen. |
| 21 | `backend/consensus_gate.py` | 52–58, 82–99 | **MITTEL** | Tie-Breaking / Robustheit | Marker-Erkennung ist `substring` auf `text.upper()`: `AGREE` ist Teil von `DISAGREE` (Negation gewinnt zwar, Z. 91–98), aber „kein Widerspruch" wird wegen `WIDERSPRUCH` als **Negativstimme** gezählt. `total_votes` zählt Statements, nicht eindeutige `agent_id`s — ein Agent kann mehrfach voten. | Fehlklassifikation von Stimmen und Vote-Spam möglich; die „deterministische" Regel ist anfällig für Formulierungen statt Evidenz. | Ganzwort-/Token-Marker mit Regex-Grenzen; Radix auf eindeutige `agent_id`s (letztes oder stärkstes Statement) und structuriertes `vote`-Feld. |
| 22 | `core_dispatcher.py`; `archon/routers/boardroom.py` | 2421–2425; 379–444 | **MITTEL** | Fehler-als-Entscheidung | `run_boardroom_debate()` liefert bei `error` `{"status":"error","content":...}` (Z. 2425). Der Router prüft `status` nicht, schreibt Vault-Note + `hist_entry` und dispatched `event_type="decision"` mit leerem Summary (Z. 390–444). | Eine fehlgeschlagene Debatte wird als Entscheidung archiviert und in die Decision-Engine/Workflows eingespeist. | Vor dem Speichern `res.get("status") == "success"` prüfen; Fehler als `cancelled`/`failed` mit `reason` persistieren. |
| 23 | `backend/epistemic_hygiene.py`; `archon/routers/epistemic_hygiene.py` | 43–129; 12–29 | **MITTEL** | Konfliktauflösung / Diagnose | `scan_vault_epistemic_hygiene()` erkennt widersprüchliche Zahlen (`conflicts`, Z. 102–116) und berechnet einen `hygiene_score` (Z. 128), ist aber nur über GET-Endpunkte erreichbar. | Konflikte zwischen Dokumenten werden angezeigt, aber nie als Gate oder Tie-Break in eine Entscheidung einbezogen. | Konflikte als `blocking` markieren, mit `decision_id` verknüpfen und vor Freigaben prüfen. |
| 24 | `backend/precedent_log.py`; `backend/operations_api.py` | 102–145, 148–...; 1149–1162 | **MITTEL** | Tie-Breaking / Präzedenz | `find_matching_precedents()` sortiert nach `(-keyword_overlap, -created_at)` — bei Gleichstand gewinnt der **neueste** Eintrag, nicht der höchstrangige (Z. 138). Das Ergebnis wird nur als Prompt-Block in den Task eingehängt (operations_api Z. 1152–1162). | Präzedenz ist Empfehlung, nicht bindend; ein jüngerer Präzedenzfall eines Junior-Agenten verdrängt ältere Senior-Rulings ohne Autoritätsprüfung. | Präzedenz mit `authority_tier` und `approver` versehen; Sortierung `(tier, overlap, created_at)`; Bindung an Entscheidungs-Gate statt Prompt. |
| 25 | `roles.json` | 1–4128 (73 `"id"`-Einträge) | **MITTEL** | Autoritätsmodell / Doc-Divergenz | Repo-weite Suche nach `"authority"`, `"authority_level"`, `"permissions"`, `"can_approve"`, `"veto"`, `"tier"`, `"decision_rights"` in `roles.json`: **0 Treffer**. Autorität steht ausschließlich in Freitext-Prompts (z. B. Z. 9 „finale Entscheidungen", Z. 60 „principal owner"). | Die behaupteten „70 Rollen mit Autoritätsmodell" sind ein Prompt-Text, keine maschinenlesbare Politik. Kein Gate kann daraus Ableitungen treffen. | Strukturiertes `authority`-Objekt pro Rolle (`tier`, `approves`, `veto`, `delegates_to`, `budget_cap`) ergänzen und von `decisions.py`/`boardroom.py` konsumieren. |
| 26 | `config/org_hierarchy.json` | 5–1133, 1134–1410 | **MITTEL** | Doc-Divergenz | Gezählt: 70 Knoten (`"id"` Z. 5–1118) und 69 Kanten (`"from"` Z. 1136–1408), nur 6 explizite `supervisor_id` (Z. 26, 187, 284, 413, 623, 1041). | Die doc-seitige Angabe „64 Knoten/63 Berichtslinien" stimmt nicht mit dem Working Tree überein; Tier-basierte Rechte und Eskalationskette basieren auf unterschiedlichen Feldern (`tier` vs. `links`). | Zahl in Doku korrigieren oder Datei auf 64/63 synchronisieren; `links` als einzige SSOT für Supervisor-Beziehungen definieren. |

**Summe: 26 Befunde — KRITISCH 5 · HOCH 14 · MITTEL 7**

---

## 3. Domänen-Urteil

**Note 2 (von 5)** — mit Tendenz zu 3.

Die Domäne hat bemerkenswert solide **Einzelbausteine**: `resolve_debate_consensus()` ist eine echte, offline-deterministische, fail-closed Funktion mit Negations-Vorrang; der Budget-Gate ist atomar reserviert und fail-closed (`core_dispatcher.py:605–653`); Zero-Egress und EU-AI-Act-Aktivierung sind harte Pre-Flight-Gates; der CAS-Decision-Pfad verhindert doppelte Freigaben; die Vier-Augen-Prüfung in `approval_policy_engine.approve_request()` vergleicht tatsächlich zwei Identitäten (Z. 444–463); Leases sind per SQL-CAS abgesichert.

Trotzdem ist die **Hoheitskette** nicht geschlossen. Drei systematische Brüche dominieren:

1. **Deterministik ohne Wirkung:** Der Konsens-Rechner steuert nur den Abbruch, nicht die Entscheidung. Der Chairman-LLM erzeugt die finale Entscheidung unabhängig vom `verdict`; die Marker werden in keinem Agent-Prompt gefordert. Das Ergebnis ist nicht reproduzierbar und nicht begründet persistiert.
2. **Autorität ist Text, nicht Code:** `roles.json` besitzt kein Autoritätsfeld, `org_hierarchy.json` wird nur für Delegationen ausgewertet, der Boardroom-Chairman ist clientseitig wählbar. Vier-Augen wird im Approval-Engine korrekt geprüft, in der zentralen Decision-API und bei Content-Freigaben jedoch nicht gegen den Ersteller. HITL-Passkey gilt nur für zwei Decision-Typen; Service-Tokens bleiben im Decision-Pfad zugelassen.
3. **Policy-Gates schützen den Dispatch, nicht das Ergebnis:** Tool-Calls, Budget und Egress sind fail-closed abgesichert; Subagent-Outputs, GoBD-Kettenstatus und Art.-50-Kennzeichnung sind es nicht. Kritik und Präzedenz sind beratend; ein fehlgeschlagener Review oder eine gebrochene Kette blockiert nichts.

Positiv zu erwähnen: Fail-Closed-Verhalten bei `review_task_output()` bei deaktiviertem Gate/`priority<threshold`/Exception (`consensus_gate.py:137–167, 226–236`), die Negations-Präferenz (M-1), die `BEGIN IMMEDIATE`-Serialisierung in `update_mission_control_data()`, die CAS-Prüfung in `content_machine.py:1268–1278` und die `_identity_tokens()`-Heuristik im Approval-Engine. Die kritischen Punkte 1–5 sollten vor einem Release behoben werden; sie betreffen direkt die Frage, wer über ein widersprüchliches Subagenten-Ergebnis entscheidet.

---

## 4. Top-5-Risiken

1. **Junior überschreibt Senior (Befund 1+11+12):** Der Chairman ist per Request-Body frei wählbar; `org_hierarchy.json` steuert nur Delegation, nicht Entscheidung, und ist per UI ohne Validierung mutierbar.
2. **Konsens ist symbolisch (Befund 2+6+7):** `NO_CONSENSUS` erzeugt trotzdem eine „Final Actionable Decision"; die Marker werden nie angefordert; Votes/Begründung landen nicht in der Historie.
3. **Vier-Augen ohne Ersteller-Vergleich (Befund 3+5):** Zentrale Decision-API und Content-Freigabe prüfen nur Admin-Rolle; Policy-Schwellen kann ein einzelner Admin auf 1 Mio. anheben.
4. **HITL-Bypass durch Service-Token (Befund 4+19):** Passkey nur für 2 Typen, `_decision_session_actor_uid()` akzeptiert `is_service`; Art.-50-Disclosure-Flag wird nirgends umgesetzt.
5. **Ergebnisse statt Calls ungeprüft (Befund 15+16+17+22):** Container-Dispatches umgehen den Compliance-Gate, GoBD-Bruch blockiert nichts, Output-Linter fail-open, fehlgeschlagene Debatten werden als Entscheidung archiviert.

---

## 5. Geprüfte Doc-Behauptungen

| Behauptung | Status | Begründung / Nachweis |
|---|---|---|
| 55 Boardroom-Frameworks mit Critique-Prompt und Synthese | ⚠️ | 55 DE (`core_dispatcher.py:1656–1726`) + 55 EN (`:1728–1794`) vorhanden; Synthese-Prompt existiert (`:2352–2361`). Aber: **kein** frameworkspezifischer Critique-Prompt, `UNIVERSAL_METHODOLOGY_HEADER` (`:1825–1847`) enthält keine Kritik-Instanz; nur CLEAR/Six-Hats/Steelmanning erwähnen Selbstkritik im Text. Unabhängiger Reviewer existiert nur im separaten Fan-in-Pfad (Befund 8). |
| `resolve_debate_consensus()` statt `aggregation_lisa`/Marker | ⚠️ | Funktion ist echt verdrahtet (`core_dispatcher.py:2234`, `orchestration.py:1240`) und deterministisch (`consensus_gate.py:61–118`). Aber `aggregation_lisa` lebt als Id weiter (`orchestration.py:987, 1121, 1169, 1440`), der `_MARKER="SYNTHESE-BEREIT"`-Vertrag ist aktiv (`:1243, 1286, 1290–1294`) und die Marker werden von keinem Produktions-Prompt erzeugt (Befund 7). |
| HITL-Freigabekaskade / Vier-Augen-Prinzip | ❌ | Approval-Engine prüft Vier-Augen korrekt (`approval_policy_engine.py:444–463`), aber Decision-API (`decisions.py:665–746`), Content-Freigabe (`content_machine.py:1238–1283`) und Policy-Änderungen (Befund 5) nicht. Passkey nur für 2 Typen; Service-Token akzeptiert (Befund 4). |
| PolicyEngine + BudgetBank | ✅ | `PolicyEngine` (`delegation_isolation.py:211–327`, verdrahtet via `tool_runtime.py:66`), `BudgetBank` (`role_budget_engine.py:969`) mit atomarem `reserve/settle/release` im Dispatcher (`core_dispatcher.py:628–700`). **Einschränkung:** PolicyEngine prüft Tool-Calls, nicht Subagent-Ergebnisse (Befund 17). |
| EU-AI-Act Art. 4 / Art. 50 | ⚠️ | Art. 4: Literacy-Register + HITL-/SOUL-Hash-Gate deterministisch (`compliance_engine.py:292–367`) und im Dispatch fail-closed verdrahtet (`core_dispatcher.py:1006–1024`, `agent_router.py:632–649`). Art. 50: `disclosure_required` berechnet, aber nirgends konsumiert (Befund 19). |
| GoBD | ⚠️ | SHA-256/HMAC-Kette mit Append-Only-Triggern existiert (`approval_policy_engine.py:63–95`, `audit_log.py`), Timestamp UTC in `boardroom.py:100–135`. Aber Kettenintegrität ist kein Entscheidungs-Gate (Befund 16); Boardroom-Historie verliert Vote-Metadaten (Befund 6); `date_display` bleibt lokale Zeit (`:416`). |
| DSGVO / Zero-Egress | ✅ (mit Lücke) | `evaluate_and_gate_llm_dispatch()` harter Block mit Audit-Beweis (`llm_egress_guard.py:119–193`); DataClassifier-Eskalation (`agent_router.py:651–664`); Tombstone-Logik statt physischem Löschen (`boardroom.py:174–185`). Lücke: Container-Spezialdispatch umgeht das Gate (Befund 15). |
| `org_hierarchy.json` mit 64 Knoten / 63 Berichtslinien | ❌ | Gezählt 70 Knoten / 69 Links (Befund 26); nur 6 `supervisor_id`. Zusätzlich werden `tier` (Rechte) und `links` (Eskalation) getrennt gepflegt. |
| 70 Rollen mit Autoritätsmodell | ❌ | 73 `"id"`-Einträge in `roles.json`, aber **keine** strukturierten Autoritätsfelder; Hoheit nur in Prompt-Freitext (Befund 25). |
| Deterministische Konfliktauflösung bei widersprüchlichen Agenten | ❌ | `resolve_debate_consensus()` ist deterministisch, aber ohne Autorität/Confidence/Evidenz; Ergebnis bindet nicht; Chairman entscheidet per LLM-Text; Präzedenz nur als Prompt, Kritik nur beratend (Befunde 2, 6, 8, 20, 24). |

---

## 6. Entwurf einer deterministischen Konfliktauflösungsregel

**Ziel:** Gleiche Inputs → gleiche Entscheidung, mit nachvollziehbarer Begründung, ohne LLM als letzte Instanz.

```text
Eingabe: Statements S = [(agent_id, role_id, tier, confidence∈[0,1],
                          evidence_refs[], stance∈{PRO,CON,ABSTAIN},
                          policy_flags[], created_at)]
         Policy P = {min_tier, min_confidence, required_evidence,
                     weighted_vote_threshold, veto_roles, mandatory_hitl}

Schritt 0 – Normalisierung (deterministisch, offline)
  - Ein agent_id zählt genau einmal: bei mehreren Statements gilt das
    neueste mit gültigem stance; ABSTAIN zählt nicht als Stimme.
  - Ungültige/markenlose Statements -> ABSTAIN, nie PRO (fail-closed).

Schritt 1 – Policy-Gate (Vorrang vor jeder Abstimmung)
  - Wenn policy_flags ∩ {EGRESS_VIOLATION, BUDGET_EXCEEDED,
      DSGVO_BLOCK, GOBD_CHAIN_INVALID, APPROVAL_REQUIRED,
      ACT_PROHIBITED, SOUL_SHA_MISMATCH} != ∅ -> verdict = BLOCKED.
  - Kein Appeal innerhalb desselben Laufs; BLOCKED -> HITL-Task.

Schritt 2 – Autoritäts-Gewichtung (kein „letzter gewinnt")
  w_i = tier_weight(tier_i)                 # 1=4.0, 2=2.0, 3=1.0
        × specialization(role_i, domain)   # 0.5..1.5, aus roles.json
        × clamp(confidence_i, 0, 1)
        × min(1, len(evidence_refs_i)/required_evidence)

Schritt 3 – Veto / HITL-Vorrang
  - Wenn ein Veto-Rolle (z. B. compliance_gdpr_auditor,
    finance_lead) CON stimmt: Sperre bis menschliche Freigabe.
  - Menschliche Freigabe hat immer Vorrang; Approval nach Schritt 1
    darf nie durch Agentenmehrheit überschrieben werden.

Schritt 4 – Entscheidungsregel (Reihenfolge strikt)
  1. BLOCKED (Schritt 1) oder Veto (Schritt 3) -> NO_GO
  2. gewichtete PRO-Summe  / Summe aller gewichteten Stimmen >= 2/3
     UND PRO-Anzahl >= 2 UND keine ungewichtungstarken CON (>2.0)
     -> GO
  3. sonst -> ESCALATE_HITL  (nie automatisch GO)

Schritt 5 – Dissens & Beweissicherung
  - minority_report = alle CON-Statements mit Grund + evidence_refs
    (unverkürzt), getrennt vom Entscheidungstext.
  - Persistiere: verdict, score, votes[], weights[], policy_flags[],
    minority_report, rule_version, input_hash, actor_id, UTC-Zeitstempel
    in HMAC-Kette. Kein `verdict` ohne `input_hash`.

Schritt 6 – Reproduzierbarkeit
  - Sortierung der Statements vor der Auswertung nach
    (tier DESC, created_at ASC, agent_id ASC) — Dict-Reihenfolge
    darf das Ergebnis nie beeinflussen.
  - LLM-Ausgaben (Synthese, Critic) sind NUR Begründungshilfe und
    dürfen `verdict` nicht ändern; fehlt die Kritik -> NO_GO.
```

**Implementierungs-Hinweis:** `resolve_debate_consensus()` (`backend/consensus_gate.py:61–118`) kann als Schritt-0-/Schritt-4-Kern weiterverwendet werden, benötigt aber die oben genannten strukturierten Felder statt Freitext-Markern. Die Regel muss in `core_dispatcher.py` vor Z. 2249 (Synthese) und in `orchestration.py` vor Z. 1327 (Robert-Freigabe) liegen, nicht nur als API-Endpunkt (`mesh.py:285–323`).

---

*Ende des Berichts — Domäne 14 (Entscheidungs-Hoheit & Konfliktlösung).*
