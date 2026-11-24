# Audit D13 — Trajectory-Governance & Loop-Prevention

**Projekt:** Archon OS v0.5.7.5 · Stand 24.11.2026
**Scope:** Domain 13 (Trajectory-Governance & Loop-Prevention), gesamte Codebasis, Working Tree (62 uncommitted Dateien)
**Bericht:** `audit_reports/2026-11-24_d13_trajectory_limits.md`

---

## 1. Scope & Methodik

Geprüft wurden ausschließlich echte Implementierungen, nicht Doc-/Kommentarbehauptungen. Zentrale Quellen:

- `archon/core/orchestration.py` (1431 Z.), `archon/core/delegation.py` (1351 Z.), `archon/core/mission_control.py` (1042 Z.), `archon/core/task_registry.py`, `archon/core/runtime.py`
- `backend/agent_router.py` (1125 Z.), `backend/concurrency_throttle.py` (217 Z.), `backend/role_budget_engine.py` (`BudgetBank`: 969–1296), `backend/delegation_isolation.py` (`PolicyEngine`: 211–327), `backend/workflow_dag_runner.py` (2105 Z.), `backend/workflow_templates.py`, `backend/execution_receipt_ledger.py`, `backend/event_mesh.py` (`EffectLedger`), `backend/deadlock_supervisor.py`, `backend/operations_api.py`, `backend/kanban_verifier.py`, `backend/autonomy_settings.py`
- `core_dispatcher.py` (2402 Z.), `main.py`, `archon/routers/{chat,boardroom,mission_control,execution,autonomy_settings}.py`, `scripts/`, `tests/`

**Methode:** Vollständiges Lesen der relevanten Pfade; Suche nach `max_hops/max_turns/max_depth/replan_count/cycle/visited/reserve/settle/release/lease/heartbeat/UNKNOWN/reconcile`; Verifikation, wo Limits hart (Exception/Abbruch/Status) vs. nur als Prompt-Hinweis/`continue` wirken; Call-Site-Analyse (wer ruft den Schutz wirklich auf?). Ignoriert: `.venv*`, `node_modules`, `.git`, `__pycache__`, `dist`, `backups`, `archive`, Caches.

**Ergebnisüberblick:** 28 belastbare Befunde (8 Hoch, 13 Mittel, 4 Niedrig, 3 Positivbefunde). Die Schutzmechaniken existieren überwiegend, sind aber an entscheidenden Stellen **nicht über den gesamten Trajectory-Pfad durchgesetzt**.

---

## 2. Befundtabelle

| # | Dateipfad | Zeile(n) | Kritikalität | Kategorie | Technischer Nachweis | Impact | Empfehlung |
|---|-----------|----------|--------------|-----------|----------------------|--------|------------|
| F01 | `archon/core/mission_control.py` + `archon/core/orchestration.py` | 45–74, 286–297, 381, 531–566 / 359, 751 | **HOCH** | Rekursion / Hop-Limit | `delegation_depth` wird in `_EXTENDED_TASK_KEYS` (45–74) nicht gelistet, daher von `_extract_meta_payload()` (286–297) nicht in `mc_task_meta` geschrieben und beim Reload (531–566) nicht restauriert. Orchestration berechnet `depth = int(task.get("delegation_depth",0) or 0)+1`. | Nach jedem `_commit()`/`load_mc()` (also praktisch bei jedem Task-Wechsel) beginnt die Tiefenschranke neu bei 0. Der dokumentierte `max_depth=3` ist **nur innerhalb eines einzigen In-Memory-Laufs** wirksam → unbegrenzte Rekursion über Task-Recycles/Persistenz. | `delegation_depth` in `_EXTENDED_TASK_KEYS` **und** in den Restore-Opt-Key-Tupel (551–566) aufnehmen; besser: Tiefe in eine eigene Spalte mit `CHECK(depth <= max)` und beim Upsert fortschreiben. |
| F02 | `backend/workflow_dag_runner.py` | 250–261 | **HOCH** | Token-/Kostenbudget | `if total > float(cap) * 1.15: errors.append(...)` — die Summe der Node-Caps darf das Run-Cap um 15 % überschreiten und gilt trotzdem als `valid`. | "Harte Obergrenze pro Ticket" ist um 15 % unterlaufen; bei 5 Nodes à 0.20 EUR und Cap 1.00 EUR (Summe 1.00 ≤ 1.15) wird der Plan freigegeben. | Toleranz auf `0` setzen (oder nur Rundungsepsilon `1e-6`) und bei Überschreitung `valid=False` + `budget_exceeded` Reason. |
| F03 | `backend/workflow_dag_runner.py` | 1932–1947 | **HOCH** | Token-/Kostenbudget | Nach Abschluss aller Nodes wird `_total_cost` aus `workflow_node_states.output_json` summiert und **nur** in `total_cost_usd` geschrieben. Es gibt keinen Abbruch, kein `budget_exhausted`, kein HITL-Gate, wenn `_total_cost > dag_def["max_budget_eur"]`. | Ein Run kann das Budget beliebig überschreiten und endet trotzdem `completed`. Nur `map`/`dynamic_fanout` prüft Kosten vor Abschluss (1705). | Vor jedem Node-Dispatch kumulierten Verbrauch gegen `max_budget_eur` prüfen; beiErreichen `blocked` + `needs_human` mit Teil-Ergebnis; `_connect`-Schreibpfad entsprechend ergänzen. |
| F04 | `backend/workflow_templates.py` + `backend/workflow_dag_runner.py` | 1151–1202 / 250–261 | **HOCH** | Token-/Kostenbudget | `_DAG_NODE_PASSTHROUGH_KEYS` enthält `token_budget`/`cost_limit_usd`, aber **nicht** `max_budget_eur`. `_build_dag_def_from_template()` (1197–1202) setzt auch auf Run-Ebene kein `max_budget_eur`. | Der einzige produktive DAG-Einstieg (Templates → `launch_workflow_run`) erzeugt DAGs, bei denen `validate_dag_def` die Budgetprüfung komplett überspringt (`cap is None`). F03 wird damit in der Praxis fast immer greifen. | `max_budget_eur` in die Passthrough-Liste und in das Run-Dict aufnehmen; Default aus `cost_limit_usd`/`token_budget` ableiten; fehlendes Cap = `valid=False`. |
| F05 | `backend/workflow_dag_runner.py` | 292–317 (+ Call-Site-Suche) | **HOCH** | Replan-Cap | `request_dag_replan()` inkrementiert `_replan_count` **innerhalb `dag_json` eines `run_id`**. eine Suche über alle `.py` findet **keinen einzigen Produktivaufrufer** (nur Definition). Jeder neue `run_id` startet bei 0. | Der "harte `replan_count`-Deckel" ist pro Run, nicht pro Ticket; durch Neuerstellung des Runs (z. B. `run_workflow_dag` mit neuem `run_id`, 30+ Call-Sites) beliebig umgangbar. Die kontrollierte Replan-Route ist Totcode. | Zähler an `root_ticket_id`/`trajectory_id` in einer eigenen Tabelle führen; `request_dag_replan` in den Router/Resume-Pfad verdrahten; neuer `run_id` muss Zähler erben. |
| F06 | `archon/routers/chat.py` + `archon/core/delegation.py` | 1016–1039 / 471–503 | **HOCH** | Rekursion / Fan-out | `_parse_delegation_blocks()` hat **kein `max_fanout`**; Dedup nur via `ziel_agent:auftrag[:40]`. Legacy-CLI-Regex (1022–1029) hängt weitere Payloads ohne Dedup an. Chat iteriert alle Payloads (1030–1032) und ruft `_execute_delegation`. | Eine einzige LLM-Antwort kann N Kanban-Tasks + N Worker + N LLM-Calls erzeugen. Der MC-Pfad hat `max_fanout=5` (orchestration.py:358), der Haupt-Delegationspfad hat **keinen** → asymmetrische, unbegrenzte Fan-out-Kosten. | Zentrales `max_delegations_per_response` (z. B. 5) vor dem Loop; Legacy-Payloads in dieselbe Dedup-Menge; Ablehnung mit `blocked`+Reason statt stiller Kürzung. |
| F07 | `backend/role_budget_engine.py` | 493–516 | **HOCH** | Token-/Kostenbudget | Fehlt `total_token_budget` oder ist 0, wird `tot_tokens = max(60_000, len(subtasks)*45_000+15_000)` und `tot_eur = tot_tokens/100_000*1.25` **neu erfunden**. | Jede neue Sub-Task-Generation mint Budget aus dem Nichts; es gibt keine übergeordnete Ticket-Root-Invariante. Kette A→B→C kann pro Hop frisches Budget erzeugen. | Fehlendes Parent-Budget = `blocked`/`needs_human`, nicht Fallback. Budget muss vom Root-Ticket aus `reserve()` kommen und an Kinder **verteilt** (nie neu erzeugt) werden. |
| F08 | `archon/routers/chat.py` | 711–750 | **HOCH** | Token-/Kostenbudget | Mission-Task setzt `estimated_tokens=45000/95000` und `estimated_cost_eur=0.05/0.18`, aber **kein** `token_budget`/`cost_limit_eur` und ruft `allocate_task_budget_to_subagents()` nicht. | `BudgetBank.check()/reserve()` (role_budget_engine.py:1060–1078, 1119–1135) prüft Task-Limits nur, wenn ein Allocation-Row existiert → für Chat-Missions gibt es **kein hartes Task-Budget**, nur das globale Tagescap. | Bei Task-Erzeugung zwingend `token_budget`/`cost_limit_eur` aus Request (mit globalem Ceiling) setzen und Allocation in derselben Transaktion anlegen. |
| F09 | `backend/role_budget_engine.py` | 977, 1105–1109, 1215–1217 | **MITTEL** | Token-/Kostenbudget | `RESERVATION_TTL_SECONDS = 1800`; `reserve()` markiert alle älteren Reservierungen `expired`; `settle()` gibt bei `status != 'reserved'` `{"status":"not_found"}` zurück **ohne Ledger-Buchung**. | Bei Ketten/LLM-Calls > 30 min verfällt die Reservierung, der Verbrauch wird nie gebucht → Budget-Unterzählung und Überschreitung unbemerkt. `agent_router` timeout=90 s, DAG `timeout_sec` bis 900 s, Tool-Loops bis 8 Calls → 30 min erreichbar. | TTL ≥ maximal erlaubte Trajectory-Dauer oder Heartbeat-Verlängerung der Reservierung; `settle()` bei abgelaufener Reservierung trotzdem Verbrauch buchen + Alarm. |
| F10 | `backend/agent_router.py` | 305–317, 222 | **MITTEL** | Erkennungsmechanik | `loop_detection_enabled = policy.get("loop_detection_enabled", True)`; bei `False` sofortiger Return ohne Prüfung. Config stammt aus `get_module_config("circuit_breaker")`, also UI/settings.json editierbar. | Loop-/Ping-Pong-Schutz ist abschaltbar, kein hartes Invariant. Ein Tiermit-Admin-Rechten kann die einzige zentrale Erkennung deaktivieren. | Minimum-Caps hart im Code: `max_steps` zwischen 5 und 30 clampen, `loop_detection_enabled` nur mit zusätzlichem `ARCHON_ALLOW_LOOP_DETECTION_OFF` + Audit-Event abschaltbar. |
| F11 | `backend/agent_router.py` + `archon/routers/autonomy_settings.py` | 369–383 / 97–105 | **MITTEL** | Erkennungsmechanik | `max_steps = int(policy.get("max_steps_per_task", 15))` ohne Unter-/Obergrenze; der Settings-Sync schreibt `max_steps_per_task` ungeprüft in die Config. | `max_steps_per_task=100000` deaktiviert die Schrittgrenze effektiv; gleichzeitig `max_identical_turns` unbounded → Jaccard-Ping-Pong-Check nie erreichbar. | Pydantic-Validierung `ge=1, le=30` bzw. `ge=2, le=10` an beiden Endpunkten; Value-Clamp auch beim Lesen in `_get_guardian_policy()`. |
| F12 | `backend/agent_router.py` + `archon/routers/chat.py` | 366–383 / 1044–1060 | **MITTEL** | Erkennungsmechanik | `trailing_agent_steps` zählt nur bis zur nächsten `user`-Nachricht. Delegations-Quittungen werden in `chat.py:1048` an `full_assistant_text` gehängt und in `:1060` als `assistant` gespeichert. | Ein neuer User-Turn setzt den Step-Zähler zurück; eine zirkuläre Kette kann durch gelegentliche User-Nachrichten die 15-Schritt-Grenze umgehen. Es gibt keinen ticket-weiten Zähler. | Persistenter `hop_count` pro `trajectory_id` statt Message-History-Heuristik; User-Turn darf den Zähler nicht zurücksetzen. |
| F13 | `archon/core/orchestration.py` | 353–367, 745–759 | **MITTEL** | Escalation | Bei `depth > max_depth` folgt nur `logger.warning` + `ticker(...)` + `continue`; Task-Status/Reason bleiben unverändert. | Limit-Erreichung führt zu still partial result; kein `blocked`/`needs_human`, kein Audit-Grund im Task. Andere Pfade (Budget, DAG, Kanban-Verifier) eskalieren sauber. | Bei Cap-Erreichung `task["status"]="blocked"`, `block_kind="trajectory_depth_exceeded"`, `failure_reason` setzen und `_commit()` + HITL-Ping. |
| F14 | `archon/core/delegation.py` | 223–228, 1251–1266, 1332–1334 | **MITTEL** | Rekursion / Zyklus | `_DELEGATION_CHAIN_BY_SESSION` (max 5000) wird bei Overflow zur Hälfte nach Insertionsreihenfolge geleert: `for _old in list(...)[:_MAX_TRACKED_CHAINS//2]: pop(...)`. | Eine noch laufende Kette kann evicted werden; danach ist `_chain` leer → Zyklus- und Tiefenprüfung für genau diese Session wirkungslos (`A→B→A` möglich). | Aktive Chains nie evictieren; LRU nur für terminale Sessions; Eviction mit `active`-Flag/CAS absichern. |
| F15 | `archon/core/delegation.py` | 1257–1266, 1464–1470 | **MITTEL** | Escalation | Zyklus-/Tiefen-Ablehnung gibt nur einen Text-String zurück (`"❌ DELEGATION ABGELEHNT — Zyklus erkannt..."`); kein Task-Status, kein `block_kind`, kein HITL-Event. | Ablehnung ist für Audit/UI unsichtbar; der delegierende Agent erhält lediglich eine Nachricht und kann erneut versuchen. | Ablehnung als strukturiertes Result `{status:"blocked", reason:"CYCLE_DETECTED", ...}` + Audit-Event; Task/Kanban-Karte entsprechend markieren. |
| F16 | `archon/core/mission_control.py` | 891–973 | **MITTEL** | Rekursion / Zyklus | `mc_link_subtask_sqlite()` schreibt `INSERT OR IGNORE INTO task_links (parent_id, child_id)` und `UPDATE tasks SET project_id=?` **ohne DFS/Visited-Check**. | `parent_project_id`/`parent_task_id`-Zyklen sind im Task-Graphen möglich (z. B. über andere Link-Pfade oder manipulierte Payloads); Fan-in/Synthese kann loop-en. | Vor dem Insert eine recursive CTE/DFS mit Zyklusprüfung; ablehnen mit `blocked`+`reason`, Self-Link bereits bei `mission_control.py:523` nur lokal abgefangen. |
| F17 | `backend/operations_api.py` | 67–89, 163–167 | **MITTEL** | Leases / Liveness | 6-h-Zombie-Reset setzt `status='todo', started_at=NULL` für alle `in_progress`-Tasks ohne `claim_lock`/`worker_pid`/Heartbeat zu prüfen. | Ein legitim langer, aber lebendiger Task (> 6 h) wird auf `todo` zurückgesetzt, während der Worker noch arbeitet. Duplikat-Ausführung wird nur durch den noch gehaltenen `claim_lock` verhindert — Inkonsistenz zwischen Lease und Status. | Zusätzlich `AND (claim_lock IS NULL OR claim_expires < now)` und PID-Liveness via `deadlock_supervisor._pid_alive` prüfen; Reset nur bei totem Worker. |
| F18 | `backend/concurrency_throttle.py` | 115–219 | **MITTEL** | Concurrency-Throttle | `_wait_queue` ist eine unbounds Heap-Liste; Heap-Key `(-priority, seq, ...)` hat **kein Aging**; `queue_timeout_seconds=60` (default). | Bei anhaltendem P3-Zufluss verhungern P1-Permanent (Priority-Inversion); bei vielen Waitern wächst die Queue ohne Obergrenze → Speicherdruck. | `max_queue_size` + QueueFull → `blocked`/`429`; Aging-Faktor auf Priorität anwenden; Metrik `queue_depth` alarmieren. |
| F19 | `backend/workflow_dag_runner.py` | 919–996, 904–913 | **MITTEL** | Token-/Kostenbudget / Loop | Tool-Loop: `max_turns = max(1, min(6, ...))`; pro Turn ein zusätzlicher `dispatch_to_omniroute_or_container` (978), plus初始 Dispatch (904) und optionaler Schema-Repair-Dispatch (1026). `task_id=str(kanban_task_id or node.get("id") or "")` — oft Node-ID ohne Allocation. | Bis zu 8 kostenpflichtige Calls pro Node, ohne Prüfung des kumulierten Node-`token_budget`. Pro-Task-Cap greift nur bei vorhandenem Allocation-Row. | Kumulierte Tokens pro Node gegen `token_budget` prüfen;bei 0 → Tool-Loop beenden + `blocked`; `task_id` immer an echte Kanban-Karte binden. |
| F20 | `core_dispatcher.py` | 2088–2110 | **MITTEL** | Erkennungsmechanik / Escalation | Boardroom-CB-Prüfung nutzt nur `debate_statements[-8:]`, setzt `role="agent"`; `max_steps_per_task=15` kann mit 8 Messages **nie** auslösen. `except Exception: logger.debug(...)` verschluckt CB-Fehler → Fail-Open. | Bei CB-Ausfall oder >15 sedimentierten Schritten ohne Ping-Pong-Muster läuft die Debatte ungebremst weiter. | CB-Fehler fail-closed (Debatte `blocked`), Fenster ≥ `max_steps+1`,atriender Step-Zähler statt Jaccard-Fenster. |
| F21 | `backend/event_mesh.py` + `backend/tool_runtime.py` | 63–70, 167–211, 622–670 / 50–80 | **MITTEL** | Effect Ledger UNKNOWN | `EffectLedger` wird nur im Outbox-Pfad (`event_mesh.py:511, 565–571`) benutzt. `tool_runtime.execute_agent_tool()` (DAG-Tool-Calls, 942–948 im Runner) hat **keinen** Effect-Ledger-Aufruf, auch kein `mark_unknown`. | "UNKNOWN + Reconciliation" gilt nur für HTTP-Outbox-Effekte; unbekannte Agent-Tool-Effekte (Zahlung, Datei, Mail) werden nicht als UNKNOWN markiert und können still als Erfolg verbucht werden. | Auch Tool-Ausführungen über `effect_ledger.reserve/mark_unknown/reconcile` mit Idempotency-Key führen; Code-Modifikation an zentralem `tool_runtime`-Chokepoint. |
| F22 | `backend/event_mesh.py` | 180–200 | **NIEDRIG** | Effect Ledger UNKNOWN | `reconcile()` prüft nur `final_state in (COMMITTED, FAILED)` und `bool(evidence)` — nicht, ob das Evidence den Effekt tatsächlich belegt (z. B. `http_status=200`). | Ein beliebiges nicht-leeres Dict kann einen UNKNOWN-Effekt zu COMMITTED schließen; Reconciliation ist formal, nicht beweiskräftig. | Evidence-Schema validieren (HTTP-Status, Response-Hash, erwartete Version) und nur bei passendem Beweis abschließen. |
| F23 | `archon/routers/boardroom.py` | 56–76 | **NIEDRIG** | Fan-out | `slots: Optional[List[BoardroomSlotItem]]` ohne `max_length`; `rounds` korrekt `ge=1, le=6` (67). | Pro Runde unbegrenzt viele Agenten → N×6 Calls; globale Tagesbudgets greifen, aber kein Ticket-Fan-out-Cap. | `Field(..., max_length=8)` und Gesamt-Call-Cap `len(slots)*rounds <= 48`. |
| F24 | `core_dispatcher.py` | 2394–2417 | **NIEDRIG** | Rekursion / Runden-Cap | `run_boardroom_debate(task, max_rounds, ...)` hat keine interne Validierung; nur der Router (boardroom.py:67) begrenzt auf 6. | Interne Direktcaller (Skripte, Agents) können `max_rounds=10000` übergeben → Endlosschleife kostenpflichtiger Calls. | `max_rounds = max(1, min(6, int(max_rounds)))` direkt in `stream_boardroom_debate()`/ `run_boardroom_debate()`. |
| F25 | `CHANGELOG.md` / `backend/deadlock_supervisor.py` | 31 / 66–97 | **NIEDRIG** | Doc-Drift | CHANGELOG behauptet `Liveness-Check via os.kill(pid, 0)`; Code nutzt bewusst `psutil.pid_exists()` und warnt explizit, dass `os.kill(pid,0)` unter Windows ein Ctrl+C auslöst. | Dokumentation beschreibt eine gefährliche, nicht vorhandene Implementierung; Audits können falsch vertrauen. | CHANGELOG/Handbuch auf `psutil` + Windows-Fallback korrigieren. |
| F26 | `backend/deadlock_supervisor.py` | 264–321 | **POSITIV** | Leases / Heartbeats | Fail-closed Heartbeat (`hb_fresh` nur bei frischem Beacon), CAS-Reset `WHERE claim_expires <= now`, `_pid_alive()` via psutil, nach 3 Resets `failed` + `[DEADLOCK-ESCALATED]` Reason. | Zombie-/Duplikat-Ausführung wirksam unterbunden; saubere Eskalation nach 3 Versuchen. | Mechanik beibehalten; auf `operations_api`-Zombie-Reset (F17) anwenden. |
| F27 | `backend/event_mesh.py` | 63–70, 167–211, 622–670 | **POSITIV** | Effect Ledger UNKNOWN | `mark_unknown(resolved=False)`, `can_retry()` nur `PENDING/FAILED`, `reconcile()` nur aus UNKNOWN mit Evidence; Outbox reconcilierte UNKNOWN **vor** Retry ohne Ledger-Selbständerung (`update_ledger=False`). | Korrekte Semantik für Outbox-Effekte; kein direkter Retry nach UNKNOWN. | Auf Tool-Effekte ausweiten (F21). |
| F28 | `core_dispatcher.py` | 605–653, 684–704, 746–758 | **POSITIV** | BudgetBank reserve/settle | Vor jedem OmniRoute-Dispatch `budget_bank.reserve()` im `asyncio.to_thread`, bei Fehler `status=blocked` (fail-closed); `settle`/`release` nach dem Call und `release` im `finally`; `est_eur` vorab geschätzt. | Kein TOCTOU, keine hängenden Reservierungen, harte Tages-/Task-/Monats-Caps im Reservierungspfad (role_budget_engine.py:1119–1160). | Auf Chat-/Container-Pfade (`agent_router`, `dispatch_to_external_agent`) ausweiten. |

---

## 3. Domänen-Urteil

**Note 4 von 5 (1 = best, 5 = kritisch).**

Begründung: Die Domain hat ein ungewöhnlich dichtes Fundament — atomare `BudgetBank`, Leases mit Liveness-Check, DAG-Plan-Validator, Circuit-Breaker, Effect-Ledger mit UNKNOWN, Concurrency-Throttle und Zyklus-Erkennung im Delegationspfad sind real implementiert und teilweise testsseitig abgesichert. Die **Durchsetzung über den gesamten Trajectory** ist jedoch lückenhaft: Der MC-Tiefenzähler geht bei der Persistenz verloren (F01), die Budget-Obergrenze wird zur Laufzeit nicht erzwungen und ist im Template-Pfad gar nicht gesetzt (F02–F04), der Replan-Deckel ist an einen Run statt an ein Ticket gebunden und ohne Produktivaufrufer (F05), der Hauptdelegationspfad hat keinen Fan-out-Cap (F06), und der zentrale Loop-Schutz ist konfigurativ abschaltbar (F10/F11). Doc-Behauptungen treffen therefore nur teilweise zu.

---

## 4. Top-5-Risiken

1. **F01 – Tiefen-Cap ist nach Persistenz wirkungslos.** `delegation_depth` wird nicht in `mc_task_meta` gespeichert/restauriert; die `max_depth=3`-Schranke zählt nach jedem Reload wieder ab 0 → theoretisch unbegrenzte, kostenpflichtige Delegationskaskade.
2. **F03/F04 – Keine harte Kostenobergrenze während eines Runs.** Template-DAGs tragen kein `max_budget_eur`; der Validator prüft nichts, und am Ende werden Kosten nur protokolliert, nicht abgebrochen → Budgetüberschreitung bleibt unbemerkt bis zur Abrechnung.
3. **F05/F07 – Replan- und Task-Budget sind nicht ticketweit.** `_replan_count` sitzt im `run_id`-Dokument und hat keinen Produktivaufrufer; fehlende Parent-Budgets werden neu erfunden → ein Ticket kann durch neue Run-/Task-IDs beliebig viele Runden und Budget minten.
4. **F06 – Unbegrenzter Delegations-Fan-out im Chat-Pfad.** Eine LLM-Antwort kann beliebig viele `delegation`-Blöcke enthalten; es gibt kein `max_fanout`, während der MC-Pfad sehr wohl einen hat → asymmetrische, unbegrenzte Parallelkosten.
5. **F10/F11 – Loop-Schutz ist abschaltbar und konfigurativ entgrenzbar.** `loop_detection_enabled=False` oder `max_steps_per_task=100000` über settings.json deaktiviert die einzige zentrale Ping-Pong-/Runaway-Erkennung, ohne dass ein harter Code-Cap greift.

---

## 5. Geprüfte Doc-Behauptungen

| Behauptung (Quelle) | Bewertung | Begründung mit Beleg |
|---------------------|-----------|----------------------|
| `replan_count`-Cap (README.md:51, ROADMAP_2026.md:706) | ⚠️ | `MAX_REPLAN_COUNT=2` existiert (workflow_dag_runner.py:64, 285–287, 303), aber `request_dag_replan()` hat **keinen Produktivaufrufer** und der Zähler ist pro `run_id`, nicht pro Ticket (F05). |
| Pre-Execution-DAG-Validator (README.md:51) | ✅ | `validate_dag_def()` wird **vor jedem Node** gerufen (workflow_dag_runner.py:1424–1446) und erkennt Zyklen via Kahn (222–240), fehlende Abhängigkeiten (228–230), doppelte IDs (209–210), ungültige Kanten (213–220), Input-Mapping (242–248), Deadline (263–271), RBAC/HITL (273–282). **ABER** Budgetcheck wirkungslos im Template-Pfad (F04). |
| Worker-Leases/Heartbeats + Liveness-Check (README.md:51, CHANGELOG.md:31) | ⚠️ | Kernmechanik solide (deadlock_supervisor.py:126–197, 264–321; DAG `guard.lost` fail-closed 2075–2088). Doc-Drift beim Liveness-Verfahren (`os.kill` behauptet, `psutil` implementiert — F25) und 6-h-Zombie-Reset ohne Lease-Prüfung (F17). |
| Effect Ledger mit `UNKNOWN` + Reconciliation (README.md:51) | ⚠️ | Im Outbox-Pfad korrekt (event_mesh.py:63–211, 622–670), aber **nicht** für Agent-Tool-Effekte verdrahtet (F21); `reconcile()` ohne Beweisvalidierung (F22). |
| Concurrency-Throttle (Doku implizit) | ⚠️ | Priorisierte Slots + Backpressure + Timeout existieren (concurrency_throttle.py:115–219), aber unbounds Queue und kein Aging (F18). |
| BudgetBank `reserve → settle/release` (README.md:52) | ⚠️ | Im `core_dispatcher` korrekt fail-closed verdrahtet (F28); **nicht** im Chat-/AgentRouter-Pfad (F08), TTL-Lücke (F09), Budget-Minting (F07). |
| PolicyEngine (README.md:52) | ✅ | Zentrale Chokepoint-Entscheidung mit Warrant-Zwang, File-Jail, Session-Taint, Audit-Fail-Closed (delegation_isolation.py:211–327; tool_runtime.py:66–70). |
| Idempotenz (README.md:51) | ✅ | `idempotency_guard` im MC-Hot-Path (orchestration.py:266–285), DAG-Nodes (workflow_dag_runner.py:1273–1308), Outbox (event_mesh.py). |
| 6h-Auto-Crash-Recovery | ⚠️ | 6-h-Reset existiert (operations_api.py:67–89), ignoriert aber Lease/Liveness (F17); die 3-Versuch-/Eskalationslogik liegt im Deadlock-Supervisor (deadlock_supervisor.py:296–304). |
| 4-Augen-HITL-Gates | ✅ | DAG-HITL-Gate mit SUSPEND/Checkpoint/Fencing (workflow_dag_runner.py:1576–1599, 1751–1759, `_suspend_run_at_gate` 122–181); Approval-Engine 4-Augen (approval_policy_engine.py:350–394); Synthesis-Fehler → `blocked` (orchestration.py F-040-Pfad). |
| Harte `max_hops`/Rekursionslimits pro Ticket | ❌ | Kein durchgehendes `max_hops`. `max_depth=3` (MC), `_MAX_DELEGATION_DEPTH=5` (Session-Kette), `max_steps=15` (Message-History), `max_turns≤6` (DAG-Node) sind **unterschiedliche, nicht ticketweite** Zähler; MC-Zähler geht bei Persistenz verloren (F01), Ketten-Cache kann evicted werden (F14). |

---

## 6. Empfehlung für ein hartes Trajectory-Budget

### 6.1 Schema (single source of truth, SQLite `trajectory_budgets`)

```json
{
  "trajectory_id": "tr_<uuid>",              // unveränderlich, über alle Run-/Task-/Session-IDs hinweg
  "root_ticket_id": "task-...",
  "tenant_id": "default",
  "caps": {
    "max_hops": 16,                           // Agentenwechsel + Tool-Calls + Retries + Replans
    "max_agent_switches": 8,
    "max_tool_calls": 24,
    "max_replans": 2,
    "max_tokens": 250000,
    "max_cost_eur": 5.00,
    "max_wall_clock_seconds": 3600
  },
  "usage": {
    "hops": 0,
    "agent_switches": 0,
    "tool_calls": 0,
    "replans": 0,
    "tokens": 0,
    "cost_eur": 0.0,
    "visited_agents": ["default"],           // visited-set für Zyklus-Erkennung
    "started_at": "2026-11-24T...Z"
  },
  "state": "running | blocked | completed | failed",
  "lease": { "token": "...", "expires_at": 0, "heartbeat_at": 0 },
  "escalation": {
    "status": "needs_human",
    "reason": "TRAJECTORY_BUDGET_EXHAUSTED",
    "partial_result_ref": "obsidian://.../<ticket>.md"
  }
}
```

**Invarianten:** `hops ≤ max_hops`, `replans ≤ max_replans`, `tokens ≤ max_tokens`, `cost_eur ≤ max_cost_eur`, `ziel ∉ visited_agents` (außer dokumentierte Apex-Ausnahme), `state=blocked ⇒ needs_human + reason + partial_result`.

### 6.2 Durchsetzungsreihenfolge

1. **Root-Caps beim Intake** (`archon/routers/chat.py`, `mission_control.py`, `boardroom.py`, `workflow_templates.py`): Request-Felder mit Pydantic `ge/le` gegen globale Obergrenzen validieren. Fehlendes Budget = `blocked`, kein Fallback-Minting (fix F06/F07/F08/F23/F24).
2. **Zentralen `TrajectoryBudgetBank`** (neben `BudgetBank` in `role_budget_engine.py`, `BEGIN IMMEDIATE`, CAS): `reserve_hop(trajectory_id, kind, agent_id)` **vor** jedem Agentenwechsel, Tool-Call, Retry und Replan — atomar mit `budget_bank.reserve()` (fix F02/F03/F05/F09/F19).
3. **`trajectory_id` überall durchreichen**: chat → `_execute_delegation` → Kanban → `core_dispatcher` → DAG-Runner → `tool_runtime` → Boardroom. Kein Zählen mehr über `session_id`/`task_id`/Message-History (fix F01/F12/F14/F20).
4. **Zyklus-/Self-Delegation hart im Chokepoint**: `ziel in visited_agents` oder `depth > max_depth` → `status=blocked`, `block_kind=cycle_detected|depth_exceeded`, Audit-Event, kein Dispatch (fix F13/F15/F16).
5. **`settle` nach jedem Hop** mit echten Tokens/Kosten; bei `cap-1` → keine weiteren Dispatches, stattdessen `needs_human` mit Teil-Ergebnis (nie Crash, nie Endlosschleife). `release` im `finally` für alle Pfade inkl. `dispatch_to_external_agent`.
6. **Counters vererben, nie zurücksetzen**: Neuer `run_id`, Task-Recycle, Deadlock-Reset, Replan und Retry übernehmen `hops/replans/tokens` des `trajectory_id` (fix F05/F17).
7. **Observability & Fail-Closed**: OTel-Span + Audit-Record pro Hop, Alarm bei 80 % Caps; Ausfall der Budgetbank/Validator → `blocked`, nie Fail-Open (analog core_dispatcher.py:644–653).

**Reihenfolge der Umsetzung (empfohlen):** 1+2 (Intake & Bank) → 3 (ID-Propagation) → 4 (Zyklus-Check) → 5 (Settle/Eskalation) → 6 (Vererbung) → 7 (Telemetrie). Erst mit Schritt 3 sind F01/F05/F14 wirklich behoben.

---

*Ende des Berichts. Alle Zeilenangaben beziehen sich auf den auditierten Working Tree vom 24.11.2026.*
