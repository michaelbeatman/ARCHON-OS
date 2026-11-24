# Audit D11 — Context Drift & Handoff-Integrität

Datum: 24.11.2026 · Repo: `C:\.Antigravity-projekte\AgenticOS-2026` (Archon OS v0.5.7.5) · Auditierter Stand: Working Tree (62 uncommitted files)

---

## 1. Scope & Methodik

**Domäne:** Alle Übergabepunkte zwischen Orchestrator, Prompt-Builder, LLM, Parser, Result, Synthese und Parent-Agent — über die gesamte productive Codebasis hinweg.

**Geprüfte Dateien (Auszug, alle mit echtem Code-Lesen):**

| Schicht | Dateien |
|---|---|
| Orchestrierung | `archon/core/orchestration.py`, `archon/core/delegation.py`, `archon/core/mission_control.py`, `archon/core/runtime.py`, `core_dispatcher.py` |
| Routing / Registry | `backend/agent_router.py`, `backend/prompt_registry.py`, `backend/handoff_desk.py`, `backend/context_compactor.py`, `backend/consensus_gate.py`, `backend/idempotency_guard.py` |
| DAG / Task-Force | `backend/workflow_dag_runner.py`, `backend/ephemeral_team_spawner.py`, `backend/ephemeral_sandbox.py` |
| Router | `archon/routers/agent_chat.py`, `archon/routers/chat.py`, `archon/routers/boardroom.py`, `archon/routers/execution.py`, `archon/routers/hr.py`, `scripts/trigger_boardroom_debate.py` |
| Daten / Profile | `agent_profiles.json`, `roles.json`, `prompt_studio_catalog.json`, `archon/core/profiles.py`, `archon/services/profiles_service.py`, `.hermes/profiles/*` (indirekt via `profiles.py`) |

**Ignoriert:** `.venv*`, `.ci_venv`, `node_modules`, `.git`, `__pycache__`, `dist`, `site`, `backups`, `archive`, `_archive_legacy`, `*.bak*`, Caches.

**Vorgehen:** Es wurde ausschließlich implementierter Code gelesen (keine Doc-/Kommentar-Vertrauensbasis). Jeder Befund hat einen konkreten Datei-/Zeilenbezug. Docs/Kommentare wurden separat in Abschnitt 5 gegen den Code geprüft.

**Querschnittsbefund vorab:** In der gesamten Handoff-Kette gibt es **kein einziges tyisiertes Pydantic-Modell für Task-, Handoff- oder Result-Payloads**. Pydantic wird nur an HTTP-Request-Grenzen (`BaseModel` in Routern) und für Profilvalidierung (`AgentProfileValidationSchema`) verwendet. Alle Übergaben zwischen Orchestrator → Dispatcher → Subagent → Parser → Synthese → Parent laufen über `dict[str, Any]`, `str`, f-strings und `json.dumps`.

---

## 2. Befundtabelle

| # | Dateipfad | Zeile(n) | Kritikalität | Kategorie | Technischer Nachweis | Impact | Empfehlung |
|---|---|---|---|---|---|---|---|
| 1 | `core_dispatcher.py` | 916–927, 1572, 1581–1585 | 🔴 KRITISCH | Canary/Version Traceability | `effective_prompt_info = eff` wird gesetzt, aber in **keinem** der ~20 `return {"status":..., "content":...}`-Dicts (z. B. 1572, 1581) übergeben. `grep effective_prompt_info` → nur 2 Treffer (Zuweisung + Init). | Aktive Prompt-Version und `is_canary` sind im Ergebnis unsichtbar. Canary-Ergebnisse sind nachträglich **nicht** der Version zuordenbar; Rollback-Entscheidungen entbehren der Evidenz. | `PromptVersionRef` (siehe Abschnitt 6) in **jeden** Dispatch-Return aufnehmen und bis in `task.result_summary`-Metadaten / Handoff-Envelope durchreichen. |
| 2 | `archon/core/mission_control.py` | 45–74, 381–399, 531–565 | 🔴 KRITISCH | Serialisierungsgrenze / Schema-Drift | `_EXTENDED_TASK_KEYS` ist eine statische Whitelist. `_extract_meta_payload()` speichert nur diese Keys; `_load_sqlite_state_from_conn()` rekonstruiert nur diese + explizite Liste 551–565. `orchestration.py:654–655` schreibt `failure_reason`, `delegation.py:385–411` schreibt `delegation_depth`, `role`, `mandate` — **alle nicht in der Whitelist**. | Strukturierte Failure-Flags und Delegationskontext verschwinden beim SQLite-Roundtrip. Fan-in sieht `blocked` ohne `failure_reason`; Rekursionsschranke verliert ihre Tiefeninformation nach Reload. | Whitelist durch versioniertes Task-Schema (Pydantic) ersetzen; unbekannte Keys mit `extra="allow"` in `mc_task_meta` bewahren statt zu verwerfen. |
| 3 | `backend/agent_router.py` | 231–302, 403–413 | 🔴 KRITISCH | Truncation / Safety-Verlust | `_compress_conversation_window`: pro älterer Nachricht nur `lines[0][:160]` (256); bei >18 Zeilen `summary_lines[:3] + ["- [...]"] + summary_lines[-12:]` (263); 2. Branch (403–413) trimmt ohne jeden Marker. System-Prompt ( messages[0] ) bleibt, aber Safety-/Negativabgrenzungen in älteren User-/Assistant-Turns gehen verloren. | Stille Post: Rollen-Constraints, Quellen, HITL-Hinweise und Negativabgrenzungen aus früheren Turns fehlen im Prompt, ohne dass das Modell oder nachgelagerte Logik erfährt, was fehlt. | Strukturierte Summary mit `dropped_turns`-Liste + explizitem Marker (wie in `handoff_desk.summarize_for_handoff`) und Pflicht-Retention aller `system`/`safety`-Nachrichten. |
| 4 | `backend/workflow_dag_runner.py` | 998–1014 | 🔴 KRITISCH | Schema-Validierung (Schein) | `output_schema`-Prüfung ist nur `json.loads()` + `required`-Key-Check. Fallback `req_keys = list(schema.keys())` (1010) behandelt z. B. `"type"`/`"properties"` als Pflichtfelder. Keine Typprüfung, kein `jsonschema`, kein `$ref`. | Ein DAG-Node kann "validiert" sein, obwohl Felder vom falschen Typ sind; umgekehrt werden valide Outputs wegen Schema-Metakeys abgelehnt. Repair-/Eskalations-LLMs (1018–1073) werden unnötig mit Kosten beauftragt. | `jsonschema.Draft202012Validator` (oder Pydantic `TypeAdapter`) mit `model_validate()`; `required` aus `schema["required"]`, nie aus Schema-Keys. |
| 5 | `archon/core/profiles.py` | 550–551, 358–371 | 🔴 KRITISCH | Cross-Language DE/EN | `prompt_en = ydata.get("prompt_en") or fallback.get("prompt_en") or fallback.get("system_prompt_en") or prompt`. Fehlt die EN-Variante, wird der **deutsche** SOUL-Text als `system_prompt_en` übernommen. `_project_profiles_for_lang(..., "en")` setzt ihn dann aktiv (370). | Eine EN-Anfrage erhält deutsche Rollen-, Safety- und Negativinstruktionen. Sprachwechsel ändert das Verhalten, ohne dass es jemandem auffällt — genau die im Briefing geforderte DE/EN-Paritätsverletzung. | Fail-closed: fehlende `prompt_en` → Fehler/Warnung + DE-Flag im Profil, kein stiller Fallback; Parität als CI-Check über alle Profile. |
| 6 | `core_dispatcher.py` | 2295–2304, 2320–2321 | 🔴 KRITISCH | Informationsverlust-Kette | MoA-Referenzfehler werden als `content: f"Fehler bei {m_name}: {e}"` (2297) zurückgegeben und anschließend ungefiltert in `agg_prompt += f"=== MODELL... ===\n{r['content']}"` (2321) eingespeist. | Der Aggregator erhält exception-Texte als angebliche Fachanalyse. Ein fehlgeschlagenes Referenzmodell verschlechtert die Synthese, ohne dass ein Failure-Flag ankommt (`status` wird im Prompt nicht mitgegeben). | Nur `status=="ok"`-Results in den Aggregator-Prompt aufnehmen; Fehler als strukturierte `failed_references`-Liste mitführen. |
| 7 | `backend/agent_router.py` | 674–701 | 🟠 HOCH | Result-Mutation ohne Metadaten | `_finalize_output_guard()` überschreibt `text` durch PII-Rehydration (682–684), Secret-Masking (689) und Output-Linter (696–698). Rückgabe ist ein reiner `str`. | Nachgelagerte Parser/Synthese können nicht wissen, ob/inwieweit der Output verändert wurde (z. B. `[EMAIL_N]`-Rehydration). Nachvollziehbarkeit fehlt. | `GuardedOutput{text, transformations: list[str], redaction_count}` statt `str`. |
| 8 | `backend/agent_router.py` | 834–849 | 🟠 HOCH | Typisierte Result-Grenze | `raw_text = data["choices"][0]["message"]["content"]` (834) → `return raw_text` (849). `usage`, `finish_reason`, `model` werden verworfen. Receipt nutzt `len(...)//4` und `cost_usd=0.0` (842–845). | Kein Confidence-/Finish-Reason-Signal für den Parent-Agenten; Telemetrie ist erfunden (Tokens geschätzt, Kosten 0). | `LLMResponse` mit `content, model, finish_reason, usage_real, cost` aus `data["usage"]`. |
| 9 | `archon/core/orchestration.py` | 1243, 1286–1294 | 🟠 HOCH | Freitext-Marker-Protokoll | `_MARKER = "SYNTHESE-BEREIT"` wird in den f-string `synthesis_reply` (1286) eingebaut und anschließend per `splitlines()[-1].strip().upper() == _MARKER` wieder entfernt (1292–1294). | Protokollzustand lebt in der letzten Textzeile. Abweichende Formatierung (Leerzeile, Fettung, Übersetzung) ⇒ Marker bleibt im Dokument oder fehlt; keine strukturierte "`synthesis_ready`" Information. | Explizites Feld `synthesis_state: Literal["ready","draft"]` im Result-Objekt; Marker nur noch als Kosmetik. |
| 10 | `archon/core/orchestration.py` | 1361–1372 | 🟠 HOCH | Regex-/String-Parsing LLM-Output | Freigabe wird ausschließlich über `_erste_zeile = robert_reply.splitlines()[0].strip().upper()` und `== "FREIGABE"` / `"ABLEHNUNG"` entschieden. Alles andere (inkl. "KEINE FREIGABE", Leerantwort) ⇒ `freigegeben = False` (1372). | Fail-closed ist gut, aber eine gegen uppercase abweichende oder mit Emoji/Anrede beginnende Antwort wird als Ablehnung interpretiert und erzeugt eine Kanban-Entscheidung. Kein `parse_confidence`, kein Raw-Output im Entscheidungs-Record. | Structured Output (JSON-Schema `approval_decision`) + `decision_source`/`raw_answer` im Audit-Eintrag. |
| 11 | `archon/core/orchestration.py` | 1218–1253 | 🟠 HOCH | Identitätsverlust im Fan-in | `fan_statements = [{"agent_id": f"work_package_{idx+1}", "content": str(rep)[:4000]}]` (1249–1252) — echte `sub_agent`/Rolle aus `reports` (1220–1232) wird durch Platzhalter ersetzt; `content` still auf 4000 Zeichen gekürzt. `resolve_debate_consensus` (1253) arbeitet damit auf anonymisierten, unvollständigen Statements. | Konsens-Evidence nennt `work_package_1` statt des Agenten; Quellen/Confidence/Failure-Flags der Teilergebnisse sind weg. Widersprüche außerhalb der ersten 4000 Zeichen unsichtbar. | `FanInStatement(agent_id, role, task_id, content, sources, confidence, failure_flags)`; completo Text als `content_full_ref`. |
| 12 | `archon/core/orchestration.py` | 955 | 🟡 MITTEL | Stille Truncation | `parent_task["result_summary"] = (synthese_text[:500] + "...") if len(...) > 500 else ...` | Finale Synthese wird im Parent-Task auf 500 Zeichen gekürzt; der vollständige Text liegt nur in der Obsidian-Datei, deren Pfad separat geführt wird. Kein `truncated`-Flag. | `result_summary` + `result_excerpt_ref` + `result_truncated: bool`. |
| 13 | `archon/core/delegation.py` | 471–503 | 🟠 HOCH | Regex-Parsing LLM-Output | `_parse_delegation_blocks()` nutzt `re.finditer(r"```(?:delegation|json)?\s*\n(.*?)```", ...)` (477) und als Fallback `r'\{[^{}]*"ziel_agent"...\}'` (491) — verschachteltes JSON kann damit nicht geparst werden; `invalid_blocks` enthalten nur `raw[:200]` + Fehlertext. | Ein gültiger Delegationsblock mit verschachtelten Objekten wird still verworfen; der Fehler landet als Freitext in der Chat-Session (siehe #16) und ist für nachgelagerte Logik unsichtbar. | JSON-Mode des LLM erzwingen + `json.loads` auf `output_text`; Fallback nur mit balanced-brace scanner, Fehler als `parse_error`-Event. |
| 14 | `archon/core/delegation.py` | 1335, 1371–1376 | 🟠 HOCH | Unstrukturierte Freitext-Übergabe | `msg_text = f"{isolation_header}\nMessage from 🤖 {d_name} (@{delegator_id}): {auftrag}"` (1335) und `tasks.body = f"Delegation von @{delegator_id} an @{ziel}:\n{isolation_header}\n{auftrag}"` (1376). `MEMORY_SCOPE: ... \| ACL: ... \| TTL_SECONDS: ...` (1322–1325) ist Text in einem Prompt-Header. | Isolation/Memory-ACL/TLL werden als Text an den Worker übergeben; der Worker muss sie erneut parsen. Rollen-Kontext und Delegationskette sind nicht maschinell trennbar. | `DelegationPayload` mit `execution_scope`, `memory_scope`, `acl`, `chain`, `acceptance_criteria` als Feldern; Navier Text daraus generieren. |
| 15 | `archon/core/delegation.py` | 1066–1089 | 🟠 HOCH | Erfundene Confidence + Truncation | `_confidence = 1.0 if done else (0.6 if review else 0.0)` (1066) — rein statusbasiert, nicht evidenzbasiert. `deliverables["result"] = str(result)[:4000]` (1078) ohne Kürzungsmarker. | A2A-Envelope wirkt typisiert, trägt aber eine erfundene Zahl; 4000 Zeichen Ergebnis werden ohne Marker abgeschnitten (im Gegensatz zu `handoff_desk.summarize_for_handoff`). | Confidence vom ausführenden Agenten liefern oder als `null` markieren; `summarize_for_handoff()` und `full_result_ref` verwenden. |
| 16 | `archon/routers/chat.py` | 1016–1048 | 🟠 HOCH | Fehler in Freitext verpackt | `invalid_blocks` → `f"⚠️ DELEGATION-FEHLER — Ungültiger Delegations-Block ({bad['error']})..."` (1036–1039); Quittungen ebenfalls Strings (1032–1034). Alles wird per `"\n".join(...)` zu `receipt_text` (1045) und in `full_assistant_text` (1048) sowie per SSE-Delta (1046) in die Session geschrieben. | Parsefehler/Internfehler sind für nachgelagerte Auswertung (Status, DLQ, Retry) unsichtbar; sie sehen aus wie Assistententext. | `delegation_events: list[DelegationEvent]` im SSE-`done`-Payload + `status`-Feld; Quittungstext nur als Darstellungsschicht. |
| 17 | `backend/workflow_dag_runner.py` | 156–163 | 🟠 HOCH | Serialisierung `default=str` | HITL-Checkpoint: `json.loads(json.dumps({... "node_statuses": statuses, "outputs": outputs}, default=str))` (156–161); bei Exception Fallback auf nur `workflow_id/gate_node_id` (163). | Nicht-serialisierbare Werte werden still zu Strings; bei IOException verliert der Checkpoint **alle** Node-States und Outputs. Resume nach HITL arbeitet auf unvollständigem Stand. | Pydantic-Checkpoint-Modell + `model_dump(mode="json")`; Fehler → Phase `SUSPEND_FAILED`, nie stiller Fallback. |
| 18 | `backend/workflow_dag_runner.py` | 485–510 | 🟠 HOCH | Datenfluss-Modus Verlust | `_shape_upstream_output`: `none` → nur `status`; `artifact_only` → nur status/artifacts/path; `summary` → `txt[:1200]` ohne Marker (504); `raw_out.get("status", "success")` (489/494/503) erfindet Erfolg, wenn das Feld fehlt. | Abhängige Nodes verlieren Quellen, Confidence und Failure-Flags. Ein Output ohne `status` wird als Erfolg weitergegeben. | Verluststreet mit `data_mode`, `omitted_fields`, `truncated` und `status_source` im Shape; fehlender Status ⇒ `unknown`, nicht `success`. |
| 19 | `backend/workflow_dag_runner.py` | 883–891, 974–976 | 🟠 HOCH | Stille Truncation im Prompt-Builder | `str(txt)[:4000]` pro Upstream-Output (890); Tool-Ergebnis `json.dumps(_tres)[:3500]` (975) kann mitten in einem JSON-Token abbrechen. | Das nächste LLM erhält ungültiges JSON bzw. unvollständigen Kontext, ohne Markierung. Reparatur-Prompts (1018+) greifen dann auf Basis eines schon beschädigten Textes. | `summarize_for_handoff()`-Marker + vollständiger Wert in `upstream_refs`; Tool-Result als parsed dict statt gekürzter JSON-Zeichenkette. |
| 20 | `backend/workflow_dag_runner.py` | 603–608 | 🟠 HOCH | HITL-Entscheidungsgrundlage gekürzt | `upstream_preview = json.dumps(upstream, ensure_ascii=False)[:1500]` (603) und als Freitext in `create_decision(...)` (607). | Der Mensch genehmigt auf Basis der ersten 1500 Zeichen — ohne Marker, ohne Verweis auf den vollständigen Output. HITL-Kaskade ist informativ blind. | `decision_context_ref` + `upstream_snapshot` als strukturiertes Feld; Preview mit `truncated`-Flag. |
| 21 | `backend/consensus_gate.py` | 52–99 | 🟠 HOCH | Marker-basierte Auswertung | `neg = next(m for m in _NEGATIVE_DEBATE_MARKERS if m in text)` (88), `pos = ...` (89) — reine Substringsuche im Uppercase-Text. `evidence.append((agent_id, neg))` (94/98) sind ungetippte Tupel. | Ein Satz wie „Ich widerspreche der Behauptung ‚KEIN CONSENSUS'" wird als Negativstimme gezählt. Rollen/Quellen/Confidence der Statements sind bereits vorher verloren (siehe #11). | Explizites Vote-Feld im Statement (`vote: Literal["yes","no","abstain"]`); Marker-Auswertung nur als Fallback mit `parse_confidence`. |
| 22 | `backend/consensus_gate.py` | 211–214, 309, 340 | 🟠 HOCH | Erfundene Felder / verlorene Entscheidung | `critique = parsed.get("critique", "Keine gravierenden Mängel gefunden.")` (214) erfindet Inhalt; `sum(v.get("score", 7) ...)` (309) erfindet Score 7; `json.dumps(votes)` (340) ohne `default=str`, Exception wird nur geloggt (343–344). | Fehlende Felder werden als positive Evidenz interpretiert; bei Serialisierungsfehler ist die Konsensentscheidung spurlos weg. | Fehlende Pflichtfelder ⇒ `review_incomplete`; Scores als `Optional[float]`; Decision-Record vor Serialisierung validieren. |
| 23 | `core_dispatcher.py` | 2137–2145, 2387–2391, 2406–2423 | 🟠 HOCH | Status-/Provenance-Verlust im Event-Stream | `agent_response` übernimmt nur `res.get("content", "Keine Antwort.")` (2144) — `status`/`error_code` des Dispatchers fallen weg. `done`-Event (2387) und `run_boardroom_debate`-Result (2406–2415, 2421–2423) enthalten nur `transcript`/`synthesis`. | Ein blockierter/failed Dispatch erscheint als normale Agentenaussage; Konsens-Ergebnis (`yes_votes`, `verdict`, `evidence` aus 2236–2246) wird am Ende verworfen. | `BoardroomResult` mit `events`, `consensus`, `provenance`, `failed_dispatches`; `agent_response` mit `dispatch_status`. |
| 24 | `archon/routers/boardroom.py` | 217–221, 63–76, 441 | 🟠 HOCH | Unvalidierte Payloads / Truncation | Frameworks via `PassthroughBody`/`as_payload()` direkt in globale `core_dispatcher.CATEGORIZED_FRAMEWORKS` (219–221) — kein Schema. `moa_reference_models: Optional[List[dict]]`, `moa_aggregator: Optional[dict]` (75–76) roh. `summary=str(res.get("synthesis",""))[:600]` (441) ohne Marker. | Ein manipuliertes Framework-JSON kann Prompt-Injection in alle Boardroom-Prompts einschleusen (`build_final_system_prompt(framework, ...)` in `core_dispatcher.py:2124`); Synthese im Workflow-Event gekürzt. | `FrameworkList = list[Framework]` (Pydantic), `MoARefModel`-Modell; Preview-Flag für die 600 Zeichen. |
| 25 | `scripts/trigger_boardroom_debate.py` | 70–78, 89, 125 | 🟠 HOCH | Cross-Language / unvalidierte Antwort | `auto_detect_framework()` prüft nur deutsche Keywords (`"sicherheit"`, `"risiko"`, `"kreativ"`, `"sprint"` …). Ein englischsprachiges Task ("security risk", "brainstorm") fällt auf `"Steffi Kieffer Boardroom"` zurück. HTTP-Response wird roh `json.loads` (125) ohne Schema. | Sprachwechsel ändert die Methodik (falsches Framework) — ein klassischer Context-Drift. Fehlerhafte Antwortstrukturen fallen erst beim Aufrufer auf. | Bilinguale Keyword-Maps oder sprachunabhängige Framework-ID; Response gegen `BoardroomResult` validieren. |
| 26 | `archon/routers/agent_chat.py` | 43–45, 175–181, 194, 198–199, 224–230 | 🟠 HOCH | Mehrfache Handoff-Drift | List-Prompt wird zu `"role: content"`-Fließtext (45); unbekanntes Profil wird **erfunden** inkl. system_prompt + `gpt-4o-mini` (175–181); Anhang `[:6000]` (194); `history[-8:]` mit unvalidierter Rolle (198–199) — `h.get("role", "user")` erlaubt `"system"`; Response nur `reply: str` (227). | Rolle/Identität des Agenten ist bei Fehlern erfunden; Client kann system-rollen einschleusen; Status/Error-Code/Prompt-Version gehen verloren. | Pflichtprofil (fail-closed), `Literal["user","assistant"]` für History, `AgentChatResponse` mit `status/error_code/model/prompt_version`. |
| 27 | `backend/context_compactor.py` | 32–65, 112–128 | 🟠 HOCH | Kompression mit Faktenverlust | `_extract_hard_facts()` liest nur `content.splitlines()[0][:160]` pro Nachricht (50) und begrenzt auf 6 Ziele / 8 Entscheidungen / 25 Pfade (51–64); daraus wird der `HIERARCHICAL_MEMORY_STATE`-Block (113–126). | Safety-Regeln, Negativabgrenzungen und Quellen ab Zeile 2 jeder Nachricht sind weg. Der komprimierte Block wird als `system`-Message (123–128) höher priorisiert als der Originaltext. | Alle Zeilen mit Relevanzklassifikation verarbeiten; `dropped_facts` + `source_message_ids` im Block; Safety-Turns nie komprimieren. |
| 28 | `backend/ephemeral_team_spawner.py` / `backend/workflow_dag_runner.py` | spawner 131–147 / runner 1418 | 🟡 MITTEL | Key-Drift zwischen Schichten | Spawner baut `dag_def = {"workflow_id": team_id, "nodes": ..., "edges": []}` (147); Runner liest `wf_id = str(dag_def.get("id") or "workflow")` (1418). | Die `workflow_id` der Task-Force wird im Run nicht übernommen; `res["workflow_run_id"]` (spawner 199) und Runs sind nicht mehr verlässlich korrelierbar. | Ein gemeinsames `DAGDefinition`-Modell mit `workflow_id` (alias `id`) auf beiden Seiten. |
| 29 | `backend/prompt_registry.py` | 70–89, 343–351 | 🟡 MITTEL | Stiller Fallback / SSOT-Drfit | `get_effective_prompt()` liefert bei leerem Registry-Fall `{"prompt": "", "version_num": 0, ...}` (344–351) — consumer in `core_dispatcher.py:920` prüft `if eff and eff.get("prompt")`, d. h. leerer Prompt wird still ignoriert. `_sync_profiles_json()` schreibt nur `prompt`/`model` (80–82), nicht `system_prompt`/`prompt_en`. | Keine Version, kein Fehler — die Registry wird faktisch umgangen. Profil-Felder divergieren zwischen Registry und `agent_profiles.json`. | Fallback gegen `agent_profiles.json` mit `source="profile"` und `version_num=None` markieren; alle promptrelevanten Felder synchronisieren. |
| 30 | `archon/core/mission_control.py` | 577–579, 601–606 | 🟡 MITTEL | Audit-/KV-Drift | Nur `SELECT ... FROM task_events WHERE kind='mc_audit' ORDER BY id DESC LIMIT 25` (577–579) → `audit_logs`. `mc_kv`-Keys (601–606) werden ohne Namens- oder Typvalidierung als Top-Level-State injiziert. | Handoff-/Audit-Historie wird beim Laden auf 25 Einträge gekürzt (still); ein `mc_kv`-Key namens `tasks` oder `status` kann den State-Shape überschreiben. | Audit pagieren/exportieren; `mc_kv` auf erlaubte Keys + JSON-Schema pro Key begrenzen. |
| 31 | `backend/workflow_dag_runner.py` | 1475, 1761–1763, 1950–1961 | 🟡 MITTEL | Trace-ID nicht im Handoff | `trace_id = await _otel_start(...)` (1475) wird für Spans (1762) und `_otel_end` (1960) genutzt, ist aber **nicht** im `result`-Dict (1950–1956) und nicht in den Node-Outputs (1186–1207) enthalten. | OTel-Span und Ergebnis sind nicht korrelierbar; „Observability" endet an der Übergabegrenze. | `trace_id` in `WorkflowRunResult`, `NodeOutput` und `DelegationEnvelope` aufnehmen. |
| 32 | `archon/routers/hr.py` | 197–212 | 🟡 MITTEL | SOUL-Mode Heuristik | Mode wird per Inhaltsvergleich und schließlich per `min(candidates_dist, key=...)` über **Textlängen** geraten (210–212). | `compact`/`pro`/`full` kann falsch detektiert werden; damit ist unklar, welche Safety-/Rollenversion gerade aktiv ist. | Mode als Felder in `profile.yaml`/SSOT pflegen, nicht aus Dateilänge inferieren. |

**Kurz positiv (Referenz für die Empfehlung):** `backend/handoff_desk.py:49–69` (`summarize_for_handoff`) markiert Kürzungen explizit mit `„[gekürzt: N Zeichen; vollständiges Ergebnis in deliverables_json]"` und bewahrt den vollen Text in SQLite (133, 166). `core_dispatcher.py:2061–2073` (`_prompt_transcript`) und `archon/routers/boardroom.py:266–270` (`is_truncated`) zeigen ebenfalls, wie korrekte Marker aussehen — diese Muster sind lediglich **nicht** flächendeckend angewendet.

---

## 3. Domänen-Urteil

**Note 2 (von 5) — „Mangelhaft bis ausreichend, mit kritischen Einzelstellen".**

Begründung: Die Architektur enthält mit `handoff_desk`, `prompt_registry`, `consensus_gate`, `workflow_dag_runner` und `mission_control` durchaus die **baulichen Voraussetzungen** für integritätserhaltende Übergaben (Hash, A2A-Envelope, Idempotenz, Canary, HITL-Checkpoints, explizite Kürzungsmarker an einigen Stellen). Im produktiven Hot Path werden diese Mechanismen jedoch systematisch umgangen: Payloads sind rohe Dictionaries und f-strings, Fehler-/Blocked-Status werden in Text verpackt, Kürzungen erfolgen überwiegend still, und die wenigen vorhandenen Typen (Pydantic an HTTP-Grenzen) enden an der ersten inneren Übergabe. Drei Befunde (Prompt-Version, Task-Meta-Whitelist, EN/DE-Fallback) sind einzeln kritisch, weil sie die Nachvollziehbarkeit bzw. die Safety-Instruktionen direkt betreffen.

---

## 4. Top-5-Risiken

1. **Prompt-Version & Canary verschwinden im Ergebnis** (`core_dispatcher.py:916–927`) — Canary-Rollouts sind nicht auditierbar; ein fehlerhaftes Prompt kann nicht identifiziert und zurückgerollt werden.
2. **Strukturierte Failure-Flags fallen am SQLite-Rand weg** (`mission_control.py:45–74` vs. `orchestration.py:654–655`) — `failure_reason` und `delegation_depth` überleben den Roundtrip nicht; Eskalation und Rekursionsschutz arbeiten mit unvollständigem Zustand.
3. **EN-Anfragen können deutsche SOUL-/Safety-Instruktionen erhalten** (`profiles.py:550–551`) — sprachbedingter Verlust bzw. Ersatz von Rollen- und Negativabgrenzungen.
4. **Kontext-Kompression verliert ganze Turns ohne Marker** (`agent_router.py:231–302`, `context_compactor.py:32–65`) — „Stille Post" über mehrere Hierarchieebenen, safety-relevante Aussagen ab Zeile 2 gehen verloren.
5. **Schein-Validierung im DAG** (`workflow_dag_runner.py:998–1014`) und **Marker-Freigabe** (`orchestration.py:1361–1372`) — HITL- und Schema-Gates geben Sicherheit vor, die der Code nicht leistet.

---

## 5. Geprüfte Doc-Behauptungen

| Behauptung (Quelle) | Bewertung | Code-Evidenz |
|---|---|---|
| „70 Spezialisten mit 3-Stufen-SOUL.md (Compact/Pro/Full)" | ⚠️ | `agent_profiles.json` und `roles.json` enthalten **je 73** `"id"`-Einträge (nicht 70). Die 3 Stufen werden tatsächlich gelesen (`archon/routers/hr.py:184–195`), aber der aktive Modus wird per Längenheuristik geraten (`hr.py:210–212`). |
| „832 Prompt-Templates mit 100 % Variablen-Parität" | ⚠️ | `prompt_studio_catalog.json` enthält DE/EN-Paare (`archon_prompt_template` / `archon_prompt_template_en`, z. B. Zeilen 123/127). Ein **Code-Nachweis für 100 % Parität** findet sich in keiner der geprüften Produktionsdateien; die Katalog-Datei hat kein `variables`-Feld, Parität müsste aus den `{{...}}`-Tokens beider Texte berechnet werden. Keine validierende Instanz gefunden. |
| „55 Boardroom-Frameworks" | ⚠️ | `archon/routers/boardroom.py:206–213` liefert `CATEGORIZED_FRAMEWORKS` bzw. `_EN`; eine hart codierte Anzahl 55 existiert im geprüften Code nicht. `scripts/trigger_boardroom_debate.py:16–41` kennt nur 4 Default-Frameworks. Frameworks werden unvalidiert überschrieben (`boardroom.py:217–221`). |
| „Fan-in-Synthese über `resolve_debate_consensus()`" | ✅ | `archon/core/orchestration.py:1253` und `core_dispatcher.py:2235` rufen die Funktion tatsächlich auf. **ABER:** Eingangsdaten sind anonymisiert/gekürzt (Befund #11) — Implementierung vorhanden, Integrität nicht. |
| „HITL-Freigabekaskade" | ⚠️ | Vorhanden (`workflow_dag_runner.py:122–181` suspend/checkpoint, `orchestration.py:1327–1372` Robert-Gate), aber Freigabe per First-Line-String (#10), HITL-Preview gekürzt (#20), Schema nicht validiert (#4). |
| „Observability / OTel" | ⚠️ | `workflow_dag_runner.py:37–59, 1475, 1761–1960` instrumentiert Traces — die `trace_id` wird jedoch nicht ins Ergebnis/Handoff übernommen (#31). |
| „Idempotenz + Outbox" | ✅ | `idempotency_guard.check_or_register` in `orchestration.py:266–285`, `workflow_dag_runner.py:1273–1308`; DLQ in `delegation.py:690–713, 1221–1254` und `workflow_dag_runner.py:1221–1254`. |
| „Prompt-Registry mit Canary-Rollout" (inkl. „aktive Prompt-Version im Handoff nachvollziehbar") | ❌ | Registry und Canary-Routing existieren (`prompt_registry.py:292–324`, `core_dispatcher.py:915–931`), aber `effective_prompt_info` wird nie ins Result übergeben (#1). Der nachvollziehbare Teil der Behauptung ist **falsch**. |
| „`agent_profiles.json` / `roles.json` / `.hermes/profiles/` synchron" | ⚠️ | Beide Root-Dateien haben 73 Einträge; `archon/core/profiles.py:451–457, 623–635` baut die Profile aus SOUL/profile.yaml und schreibt `agent_profiles.json` zurück. Es gibt jedoch **keine bidirektionale Validierung** und der EN-Fallback erzeugt inhaltliche Drift (#5). |

---

## 6. Konkrete Schema-Empfehlung für den Handoff

Zentrales, versioniertes Envelope-Modell. Jede Übergabe (Orchestrator → Dispatcher → Agent → Parser → Synthese → Parent) sollte genau dieses Modell oder eine seiner Untertypen tragen. Bestehende Strings werden zu `content_full_ref`/`content_excerpt`.

```python
from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator


class ProvenanceRef(BaseModel):
    """Woher stammt das Ergebnis? Nie wieder `work_package_1` (#11)."""
    task_id: str
    handoff_id: str | None = None
    agent_id: str                      # echte ID, nicht Platzhalter
    role: str
    parent_task_id: str | None = None
    correlation_id: str                # task:/run: Präfix wie in handoff_desk
    trace_id: str | None = None        # OTel-Korrelation (#31)
    turn: int | None = None


class PromptVersionRef(BaseModel):
    """Canary-Version ist Pflicht im Handoff (#1, #29)."""
    agent_id: str
    version_num: int = Field(gt=0)
    is_canary: bool = False
    canary_percentage: int = Field(default=0, ge=0, le=100)
    prompt_sha256: str | None = None
    source: Literal["registry", "profile"] = "registry"


class TruncationInfo(BaseModel):
    """Kürzung ist immer explizit und rückführbar (#3, #8, #12, #19, #20)."""
    truncated: bool = False
    original_chars: int = 0
    kept_chars: int = 0
    marker: str | None = None
    full_ref: str                      # SQLite/Obsidian-Referenz, nie nur Freitext


class Confidence(BaseModel):
    """Confidence ist entweder belegt oder None — nie erfunden (#15, #22)."""
    value: float | None = Field(default=None, ge=0.0, le=1.0)
    source: Literal["agent", "eval_gate", "consensus", "none"] = "none"
    rationale: str | None = None


class FailureFlags(BaseModel):
    """Status ist strukturiert, nicht in `content` verpackt (#7, #16, #23)."""
    status: Literal["success", "blocked", "failed", "review", "cancelled", "timeout"]
    error_code: str | None = None
    failure_reason: str | None = None   # überlebt SQLite (#2)
    blocked_by_hitl: bool = False
    failed_dispatches: list[str] = Field(default_factory=list)
    parse_errors: list[str] = Field(default_factory=list)


class DelegationEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")  # kein stilles Feld-Wegfallen (#28)

    schema_version: Literal[1] = 1
    handoff_id: str
    message_id: str
    reply_to: str | None = None
    created_at: datetime

    provenance: ProvenanceRef
    prompt_version: PromptVersionRef | None = None   # Pflicht für LLM-Results

    # Typisierte Übergabe statt isolation_header-Freitext (#14)
    execution_scope: dict[str, Any] = Field(default_factory=dict)
    memory_scope: str = "project"
    memory_acl: list[str] = Field(default_factory=list)
    delegation_chain: list[str] = Field(default_factory=list)
    delegation_depth: int = Field(default=0, ge=0, le=5)
    acceptance_criteria: list[str] = Field(default_factory=list)

    result: FailureFlags
    confidence: Confidence = Field(default_factory=Confidence)
    content_full_ref: str | None = None
    content_excerpt: str | None = None
    truncation: TruncationInfo = Field(default_factory=TruncationInfo)

    sources: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    consensus: dict[str, Any] | None = None   # yes_votes/verdict/evidence (#23)
    hitl: dict[str, Any] | None = None

    payload_hash: str | None = None           # bestehendes handoff_desk-Prinzip

    @model_validator(mode="after")
    def result_needs_content_or_ref(self) -> "DelegationEnvelope":
        if self.result.status == "success" and not (self.content_excerpt or self.content_full_ref):
            raise ValueError("success ohne content_excerpt/content_full_ref")
        return self
```

**Integrationsregeln (minimalinvasiv):**

1. `core_dispatcher.dispatch_to_omniroute_or_container()` gibt `LLMDispatchResult{content, ..., prompt_version, trace_id, failure_flags}` zurück statt `dict` (#1, #8).
2. `handoff_desk.create_handoff()` nimmt `DelegationEnvelope` statt `deliverables: Dict` (#15); `summarize_for_handoff()` liefert `TruncationInfo`.
3. `mission_control._EXTENDED_TASK_KEYS` wird durch `TaskState.model_dump()` ersetzt; `extra="allow"` bewahrt unbekannte Felder in `mc_task_meta` (#2).
4. `workflow_dag_runner._shape_upstream_output()` arbeitet auf `DelegationEnvelope`, nicht auf rohen Dicts; `data_mode` wird im Envelope dokumentiert (#18).
5. `consensus_gate.resolve_debate_consensus()` akzeptiert `list[FanInStatement]` mit echtem `agent_id`, `vote`, `sources`, `confidence` (#11, #21).
6. Freigabe/Robert-Gate liefert `ApprovalDecision{decision, raw_answer, parse_confidence}` statt First-Line-String (#10).

---

*Ende des Berichts — alle Befunde basieren auf gelesenem Working-Tree-Code; keine Annahmen über nicht geprüfte Dateien.*
