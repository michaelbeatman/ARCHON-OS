"""
Orchestrierungskern für Mission Control — extrahiert aus main.py.

Alle externen Abhängigkeiten werden per Dependency Injection übergeben
(Defaults zeigen auf die echten Implementierungen für Backwards-Compat).
"""

# mypy: disable-error-code="assignment,truthy-function,call-arg,union-attr"

from __future__ import annotations

import asyncio
import datetime
import json
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

# Lokale Imports (keine main.py, kein core_dispatcher)
from archon.core.mission_control import (
    _MC_ASYNC_LOCK,
    _write_mc_atomic,
)
from archon.core.mission_control import (
    _load_mission_control_data as _default_load_mc,
)
from archon.core.mission_control import (
    _save_mission_control_data as _default_save_mc,
)
from archon.core.mission_control import (
    update_mission_control_data as _default_update_mc,
)
from archon.core.paths import OBSIDIAN_VAULT, PROJEKTE_DIR
from archon.core.runtime import APP_ROOT, logger
from archon.core.task_registry import spawn as _spawn_tracked
from backend.handoff_desk import mark_truncated

# Type aliases für DI
Dispatcher = Any  # core_dispatcher mit .dispatch_to_omniroute_or_container, .trigger_n8n_execution
LoadMC = Callable[[], Dict[str, Any]]
SaveMC = Callable[[Dict[str, Any]], None]
Ticker = Callable[[str, str], None]
GetProfiles = Callable[[], List[Dict[str, Any]]]
InvalidateProfiles = Callable[[], None]
RollingBackup = Callable[[str, int], None]
SyncObsidian = Callable[[Dict[str, Any]], str]
FolderNamer = Callable[[Dict[str, Any]], str]
TelegramSendDoc = Callable[[str, str, Optional[Dict]], bool]
TelegramSendMsg = Callable[[str, Optional[Dict]], bool]
BuildDossier = Callable[[str, str, str, str, str], str]
CreateDecision = Callable[..., Any]

# Pfad-Konstanten (können via paths-Dict überschrieben werden)
DEFAULT_OBSIDIAN_VAULT_DIR = OBSIDIAN_VAULT
DEFAULT_WORKSPACE_DIR = APP_ROOT


def _task_by_id(data: dict, task_id: str):
    return next((t for t in data.get("tasks", []) if t.get("id") == task_id), None)


def _evidence_marker(evidence: Any) -> str:
    """Liest den Marker aus ConsensusEvidence (Tuple, Dict oder Pydantic-Modell)."""
    if isinstance(evidence, dict):
        return str(evidence.get("marker") or "")
    if isinstance(evidence, (list, tuple)):
        return str(evidence[1]) if len(evidence) >= 2 else ""
    return str(getattr(evidence, "marker", "") or "")


def _evidence_agent(evidence: Any) -> str:
    """Liest die echte Agent-ID aus ConsensusEvidence (Tuple/Dict/Modell)."""
    if isinstance(evidence, dict):
        return str(evidence.get("agent_id") or "")
    if isinstance(evidence, (list, tuple)):
        return str(evidence[0]) if evidence else ""
    return str(getattr(evidence, "agent_id", "") or "")


# --- F033/H-14-1: Produzent der Fan-in-Konsensmarker -------------------------
# Der Marker war bisher toter Code: Kind-Tasks wurden ohne verdict-Felder
# angelegt und `result_summary=reply` war der einzige spätere Schreibzugriff.
# Jetzt werden die Felder aus dem ECHTEN Dispatch-Result übernommen. Es wird
# nie ein Ja-Votum erfunden; fehlt ein strukturiertes Urteil, entsteht ein
# expliziter KEINE_STIMME-Marker (weder Zustimmung noch Widerspruch).

_FAN_NO_VOTE_MARKER = "KEINE_STIMME_STRUKTURIERT"


def _fanout_cap_guard(nominated: list, cap: int, task_id: str, ticker: Callable) -> list:
    """D13/MED: stumme Listen-Slice durch quittierte FANOUT_CAP ersetzen."""
    try:
        from backend.trajectory_budget import DEFAULT_MAX_DELEGATIONS_PER_RESPONSE as _ssot_cap
        cap = max(1, min(int(cap), int(_ssot_cap)))
    except Exception as exc:
        logger.error("[Delegation] Fanout-SSOT nicht lesbar — fail-closed %s: %s", cap, exc)
    if len(nominated) <= cap:
        return nominated
    omitted = len(nominated) - cap
    msg = f"FANOUT_CAP={cap}: {omitted} von {len(nominated)} Nominierungen verworfen"
    ticker("Delegation", f"Task #{task_id}: {msg}")
    logger.error("[Delegation] %s (task=%s)", msg, task_id)
    try:
        from archon.core.mission_control import mc_append_audit_sqlite
        mc_append_audit_sqlite("delegation", msg, str(task_id))
    except Exception as exc:
        logger.error("[Delegation] FANOUT_CAP-Audit fehlgeschlagen (task=%s): %s", task_id, exc)
    return nominated[:cap]


def extract_dispatch_verdict(res: Any, status: str = "") -> Dict[str, Any]:
    """Hoheits-/Guardrail-Felder aus einem Dispatch-Ergebnis (fail-closed)."""
    out: Dict[str, Any] = {
        "consensus_verdict": "", "verdict": "", "decision_status": "",
        "policy_violation": False, "guardrail_violation": False,
        "severity": "", "source_trace_id": "", "verdict_source": "",
    }
    if not isinstance(res, dict):
        return out
    for key in ("consensus_verdict", "consensus_status", "verdict", "decision_status"):
        value = str(res.get(key) or "").strip()
        if value:
            if not out["consensus_verdict"] and key in ("consensus_verdict", "consensus_status"):
                out["consensus_verdict"] = value
                out["verdict_source"] = f"dispatch_result:{key}"
            elif key == "verdict" and not out["verdict"]:
                out["verdict"] = value
            elif key == "decision_status" and not out["decision_status"]:
                out["decision_status"] = value
    gr = res.get("guardrail_result")
    if isinstance(gr, dict):
        out["policy_violation"] = bool(gr.get("policy_violation"))
        out["guardrail_violation"] = bool(gr.get("guardrail_violation"))
        out["severity"] = str(gr.get("severity") or "")
        out["source_trace_id"] = str(gr.get("source_trace_id") or res.get("trace_id") or "")
    for key in ("policy_violation", "guardrail_violation"):
        if bool(res.get(key)):
            out[key] = True
    if not out["severity"]:
        out["severity"] = str(res.get("severity") or "")
    if not out["source_trace_id"]:
        out["source_trace_id"] = str(res.get("trace_id") or "")
    if str(res.get("status") or status or "").strip().lower() == "blocked":
        out["policy_violation"] = True
        out["guardrail_violation"] = True
        out["severity"] = out["severity"] or "high"
        out["verdict_source"] = out["verdict_source"] or "dispatch_status:blocked"
    return out


def fan_verdict_marker(child: Dict[str, Any]) -> str:
    """Übersetzt ein strukturiertes Kind-Urteil in einen echten Konsensmarker."""
    verdict = str(
        child.get("consensus_verdict") or child.get("verdict")
        or child.get("decision_status") or ""
    ).strip().upper()
    if bool(child.get("policy_violation") or child.get("guardrail_violation")):
        return "POLICY_VIOLATION"
    if verdict.startswith("CONSENSUS_REACHED") or verdict in ("ZUSTIMME", "AGREE", "APPROVED", "EINVERSTANDEN"):
        return "KONSENS_ERREICHT"
    if (
        verdict.startswith("NO_CONSENSUS")
        or verdict in ("REJECTED", "ABGELEHNT", "CHANGES_REQUESTED")
        or "WIDERSPRUCH" in verdict or "KEIN KONSENS" in verdict
    ):
        return "KEIN KONSENS"
    # Nie still: ein Kind ohne strukturiertes Urteil ist eine Enthaltung und
    # wird als solche im Statement sichtbar (kein erfundenes Ja/Nein).
    return f"{_FAN_NO_VOTE_MARKER}:{verdict or 'kein Feld im Dispatch-Result'}"


class NominationItem(BaseModel):
    """D11/S-11.1: Schema einer einzelnen Agenten-Nominierung."""

    model_config = ConfigDict(extra="ignore")

    agent_id: str = Field(..., min_length=1)
    role: str = "Spezialist"
    mandate: str = ""
    trace_id: str = ""
    session_id: str = ""
    correlation_id: str = ""


class NominationBatch(BaseModel):
    """D11/S-11.1: Validierte Nominierungsmatrix statt json.loads + .get()."""

    model_config = ConfigDict(extra="ignore")

    project_title: str = ""
    nominated_agents: List[NominationItem] = Field(default_factory=list)


def _parse_nomination_batch(raw_json: str) -> Optional[NominationBatch]:
    """Parst einen Nominierungsblock schema-validiert; fehlerhaft -> None."""
    try:
        data = json.loads(raw_json)
        return NominationBatch.model_validate(data)
    except (ValidationError, TypeError, ValueError) as exc:
        logger.warning("[Orchestration] Nominierungsblock ungueltig: %s", exc)
        return None


def _extract_nominated_json_blocks(reply: str) -> List[str]:
    """Extrahiert JSON-Objekte mit `nominated_agents` sauber via Klammer-Tiefe (auch verschachtelt)."""
    if not reply or "nominated_agents" not in reply:
        return []
    blocks: List[str] = []
    for part in reply.split("```"):
        clean_p = part.strip()
        if clean_p.startswith("json"):
            clean_p = clean_p[4:].strip()
        if "nominated_agents" in clean_p and clean_p.startswith("{") and clean_p.endswith("}"):
            blocks.append(clean_p)
    if blocks:
        return blocks

    # Fallback: verschachtelte JSON-Objekte über Klammerzählung finden
    depth = 0
    in_str = False
    esc = False
    start = -1
    for i, ch in enumerate(reply):
        if esc:
            esc = False
            continue
        if ch == "\\" and in_str:
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                cand = reply[start : i + 1]
                if "nominated_agents" in cand:
                    blocks.append(cand)
                start = -1
    return blocks


def _merge_task_delta(fresh: dict, local_data: dict, task_id: str, local_tasks: list, orig_ids: Optional[set] = None) -> None:
    """Uebertraegt nur die Aenderungen DIESES Tasks in den frisch geladenen Store.

    Der Task wird ueber einen langen await (LLM-Dispatch) hinweg als Snapshot
    gehalten. Ein komplettes `save_mc(data)` am Ende wuerde alles ueberschreiben,
    was in der Zwischenzeit am Store passiert ist — etwa ein Task, den der Nutzer
    im Board verschoben hat (Lost Update, Audit B1). Deshalb wird nur der eigene
    Task ersetzt bzw. eingefuegt und neu angelegte Sub-Tasks ergaenzt.
    """
    fresh_tasks = fresh.setdefault("tasks", [])
    fresh_ids = {t.get("id") for t in fresh_tasks}

    local_task = _task_by_id(local_data, task_id)
    if local_task is not None:
        for i, t in enumerate(fresh_tasks):
            if t.get("id") == task_id:
                fresh_tasks[i] = local_task
                break
        else:
            fresh_tasks.insert(0, local_task)

    # R-18: Es werden NUR Tasks ergaenzt, die WAEHREND dieses Laufs neu
    # entstanden sind (nicht in orig_ids, eigenes Kind). Vorher wurde die
    # komplette alte Snapshot-Liste mitgegeben — Tasks, die der Nutzer
    # waehrend des awaits verworfen hatte, wurden dadurch wiederbelebt.
    if orig_ids is None:
        orig_ids = set()
    for sub in local_tasks or []:
        if sub.get("id") not in fresh_ids \
                and sub.get("id") not in orig_ids \
                and sub.get("parent_task_id") == task_id:
            fresh_tasks.insert(0, sub)


async def _execute_mission_control_task(
    task_id: str,
    *,
    dispatcher: Dispatcher = None,
    load_mc: LoadMC = _default_load_mc,
    save_mc: SaveMC = _default_save_mc,
    update_mc: Optional[Callable] = None,
    ticker: Ticker = None,
    get_profiles: GetProfiles = None,
    sync_obsidian: SyncObsidian = None,
    trigger_sandy: Callable = None,
    fan_in: Callable = None,
) -> None:
    """Führt eine genehmigte Mission-Control-Aufgabe autonom über core_dispatcher aus."""
    # Lazy imports für Defaults (vermeiden Zyklen bei Modul-Load)
    if dispatcher is None:
        import core_dispatcher as dispatcher
    if ticker is None:
        from archon.core.runtime import add_ticker as ticker
    if get_profiles is None:
        from archon.core.profiles import api_get_hermes_profiles as get_profiles
    if sync_obsidian is None:
        # Bewusst KEIN Fallback: die einzige korrekte Implementierung lebt in
        # main.py. Die frueher hier benutzte Kopie in archon.core.runtime war
        # nicht verhaltensgleich (eigene _slugify(), andere Dateinamen) und
        # haette still andere Ablagepfade erzeugt. Lieber ein bemerkter Fehler
        # als eine stille Abweichung.
        raise RuntimeError(
            "_execute_mission_control_task: Parameter 'sync_obsidian' fehlt. "
            "main.py injiziert _sync_task_to_obsidian; Aufrufer muessen die "
            "Abhaengigkeit explizit uebergeben."
        )
    if trigger_sandy is None:
        trigger_sandy = _trigger_sandy_staffing_nomination
    if fan_in is None:
        fan_in = _fan_in_maybe_start_synthesis
    # D02-H2 (HIGH): Cancel-Token VOR dem ersten await registieren. Der
    # aeussere CancelledError-Handler am Ende dieser Funktion persistiert
    # 'cancelled' in ALLEN Phasen — auch in der Lease-/Idempotency-Phase, die
    # frueher ausserhalb des try/finally lag und Geistertasks produzierte.
    from backend.cancellation import get_token as _get_cancel_token
    cancel_token = _get_cancel_token(f"dispatch:{task_id}")
    # Damit cancel_scope() den laufenden LLM-Call wirklich abbricht (nicht nur
    # ein Flag setzt), wird dieser Task an den Scope gebunden.
    _current_task = asyncio.current_task()
    if _current_task is not None:
        cancel_token.register_task(_current_task)

    # Zustand, den der aeussere Cancel-Handler zum Persistieren braucht.
    data: dict = {}
    tasks: list = []
    orig_task_ids: set = set()
    task: dict = None
    parent_ok = False
    parent_pid = None
    lease_token = None
    idem_key = None
    heartbeat_task = None
    deadlock_supervisor = None

    def _commit_sync() -> None:
        """Schreibt die Aenderungen dieses Tasks (wird via asyncio.to_thread gerufen).

        Mit update_mc: gezieltes Merge in den frisch geladenen Store, damit
        parallele Aenderungen an anderen Tasks nicht ueberschrieben werden.
        Ohne update_mc: RuntimeError (wie in Commit a4267fa2 an anderer Stelle).
        """
        if update_mc is not None:
            update_mc(lambda fresh: _merge_task_delta(fresh, data, task_id, tasks, orig_task_ids))
        else:
            raise RuntimeError(
                "_execute_mission_control_task: Parameter 'update_mc' fehlt. "
                "main.py injiziert update_mission_control_data; Aufrufer muessen die "
                "Abhaengigkeit explizit uebergeben."
            )

    async def _commit_async() -> None:
        await asyncio.to_thread(_commit_sync)

    try:
        # F30 (HIGH H-C): synchrones SQLite-/Store-Laden aus dem async Hot-Path in to_thread
        data = await asyncio.to_thread(load_mc)
        tasks = data.get("tasks", [])
        # R-18: Schnappschuss der Task-IDs VOR dem LLM-await — nur waerend des Laufs
        # neu erzeugte Tasks duerfen im Merge wieder eingefuegt werden.
        orig_task_ids = {t.get("id") for t in tasks}
        task = next((t for t in tasks if t.get("id") == task_id), None)  # type: ignore[arg-type]
        # D02-H2: Check direkt NACH dem Lade-await. Der Task ist jetzt bekannt,
        # damit auch ein vorab abgebrochener Scope 'cancelled' persistiert.
        cancel_token.check()
        if not task:
            return

        agent_id = task.get("agent_id", "founder")
        agent_name = task.get("agent_name") or agent_id or "Founder"
        task_title = task.get("title", "Aufgabe")
        prompt_text = task.get("capture_input") or task_title

        profiles = get_profiles() if get_profiles else []
        prof = next((p for p in profiles if p.get("id") == agent_id or p.get("person_name") == agent_name), None)
        if not prof:
            # KRITISCH (Audit 23.11.2026): niemals unter der Identität eines
            # beliebigen fremden Profils laufen (falscher Prompt, falsches Budget,
            # falsche EU-AI-Act-Klasse). Nur der explizite Root-Orchestrator ist
            # ein zulässiger Fallback.
            prof = next((p for p in profiles if p.get("id") in ("default", "orchestrator")), None)

        from archon.core.profiles import append_negative_scope

        system_prompt = (prof.get("system_prompt") if prof else None) or (prof.get("prompt") if prof else None) or (
            f"Du bist {agent_name} in Archon OS. Bearbeite die Aufgabe präzise, lösungsorientiert und strukturiert."
        )
        system_prompt = append_negative_scope(system_prompt, prof)
        model = (prof.get("model") if prof else None) or task.get("model") or "deepseek/deepseek-v4-flash-0731"

        ticker(agent_name, f"Startet Bearbeitung von Task #{task_id}: '{task_title[:35]}...'")

        # P0-6: Lease + Idempotency waren implementiert, aber nie im Hot Path
        # verdrahtet — parallele Worker konnten denselben Task doppelt ausfuehren.
        lease_token = None
        idem_key = None
        heartbeat_task = None
        deadlock_supervisor = None
        try:
            from backend.deadlock_supervisor import deadlock_supervisor as _supervisor
            deadlock_supervisor = _supervisor
            lease = await asyncio.to_thread(_supervisor.acquire_lease, str(task_id), ttl_seconds=300)
            cancel_token.check()
            if lease.get("acquired"):
                lease_token = lease.get("lease_token")
            elif lease.get("task_exists", True):
                # Nur ein real existierender, bereits geclaimter Task ist ein
                # Duplikat. Fehlt die Zeile (isolierter Store/Test), laufen wir
                # ohne Lease weiter statt den Task faelschlich zu ueberspringen.
                ticker(agent_name, f"Task #{task_id} laeuft bereits in einem anderen Worker — uebersprungen.")
                return
        except Exception as lease_exc:
            # KRITISCH (Audit 23.11.2026 / W3-Rest): ein nicht auswertbarer
            # Lease-Claim darf nie „kein anderer Worker" bedeuten — sonst
            # laufen Tasks doppelt. Der frühere Opt-out
            # ARCHON_LEASE_FAIL_OPEN wurde bewusst entfernt (siehe D07-H2).
            task["status"] = "blocked"
            task["result_summary"] = f"Lease-Claim nicht verfügbar: {lease_exc}"
            ticker(agent_name, f"Task #{task_id} blockiert — Lease-Claim nicht verfügbar.")
            await _commit_async()
            cancel_token.check()
            return

        # Der Guard schuetzt nur echte, per Lease geclaimte Tasks. Ohne Lease
        # (isolierter Store / Tests) gibt es keinen verlaesslichen Lauf-Kontext —
        # ein task_id-basierter Key wuerde dort wiederholte Laeufe faelschlich
        # als Duplikat blockieren.
        if lease_token:
            try:
                from backend.idempotency_guard import idempotency_guard

                def _idem_claim_sync():
                    return idempotency_guard.check_or_register(
                        "mission_control_task",
                        {"task_id": str(task_id),
                         "prompt": mark_truncated(prompt_text, 2000, artifact=f"tasks.capture_input/{task_id}")},
                        explicit_key=f"mct-{task_id}",
                    )

                idem = await asyncio.to_thread(_idem_claim_sync)
                cancel_token.check()
                if idem.get("blocked"):
                    cached = idem.get("cached_result") or {}
                    task["status"] = "completed"
                    task["result_summary"] = cached.get(
                        "result_summary", "Bereits ausgefuehrt (Idempotency-Cache)."
                    )
                    ticker(agent_name, f"Task #{task_id} war bereits ausgefuehrt — Duplicate geblockt.")
                    await _commit_async()
                    cancel_token.check()
                    return
                idem_key = idem.get("idempotency_key")
            except Exception as idem_exc:
                logger.warning(f"[MissionControl] Idempotency-Guard nicht verfuegbar ({idem_exc}).")

        if lease_token:
            async def _lease_heartbeat():
                while True:
                    await asyncio.sleep(60.0)
                    try:
                        if deadlock_supervisor is not None:
                            ok = await asyncio.to_thread(
                                deadlock_supervisor.heartbeat, str(task_id), lease_token, ttl_seconds=300
                            )
                            if ok is False:
                                cancel_token.cancel("lease_lost")
                                return
                    except Exception as hb_exc:
                        # Heartbeat-Verlust darf nicht unbemerkt zum Ablauf der
                        # Lease führen, während der Task weiterläuft (Audit).
                        logger.error("[MissionControl] Lease-Heartbeat %s fehlgeschlagen: %s", task_id, hb_exc)
                        cancel_token.cancel("lease_heartbeat_failed")
                        return

            heartbeat_task = asyncio.create_task(_lease_heartbeat())

        try:
            task["active_tool"] = "Tool: web_search & archon_core"
            await _commit_async()
            cancel_token.check()

            # Echter LLM-Dispatch — vorher Cancel-Token pruefen.
            cancel_token.check()
            res = await dispatcher.dispatch_to_omniroute_or_container(
                agent_id=prof.get("id", agent_id) if prof else agent_id,
                agent_name=agent_name,
                prompt=f"Führe bitte folgende Projektaufgabe in Archon OS durch:\n\n{prompt_text}\n\nLiefere eine klare, fundierte Ausarbeitung sowie die wichtigsten Handlungsschritte.",
                role=prof.get("name", "Spezialist") if prof else "Spezialist",
                system_prompt=system_prompt,
                model=model,
                # Audit v3 2.1.3: task_id mitgeben — sonst wird das Task-Budget nie abgebucht
                task_id=str(task_id or ""),
            )
            cancel_token.check()

            reply = res.get("content", "").strip()
            if res.get("status") in ("error", "blocked") or not reply or reply.startswith(("Fehler:", "Fehler ", "[Fehler")):
                # Dispatcher meldet Fehler -> Task als failed markieren
                task["status"] = "failed"
                task["result_summary"] = "Dispatcher-Fehler: " + (
                    mark_truncated(reply, 200, artifact=f"dispatcher/{task_id}") if reply else "leere Antwort"
                )
                ticker(agent_name or "Mission Control", f"Task #{task_id} fehlgeschlagen: {reply[:100]}")
                return

            # Aktualisiere Task
            task["status"] = "completed"
            task["result_summary"] = reply
            # F033/H-14-1: echte strukturierte Hoheits-/Guardrail-Felder aus dem
            # Dispatch-Result am Kind persistieren (nicht nur result_summary=reply).
            task.update(extract_dispatch_verdict(res))
            task["completed_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            from archon.core.runtime import run_io_bound
            obs_path = await run_io_bound(sync_obsidian, task)
            cancel_token.check()
            task["artifact_path"] = obs_path

            ticker("Obsidian", f"Dokumentation {os.path.basename(obs_path)} für Task #{task_id} abgelegt")
            ticker("Mission Control", f"Task #{task_id} erfolgreich abgeschlossen")

            # --- AUTO-STAFFING / DISPATCH-KETTE (MUSTER B) ---
            # Prüfe, ob die Antwort eine Nominierungsmatrix (nominated_agents) enthält
            try:
                candidate_blocks = _extract_nominated_json_blocks(reply)
                for jm in candidate_blocks:
                    parsed_dispatch = _parse_nomination_batch(jm)
                    if parsed_dispatch is None:
                        continue
                    nominated = parsed_dispatch.nominated_agents
                    if len(nominated) > 0:
                        # KRITISCH (Audit 23.11.2026): Delegations-Rekursion und
                        # Fan-out hart begrenzen — sonst kann ein LLM, das sich
                        # selbst nominiert, unbegrenzt kostenpflichtige Calls
                        # auslösen.
                        max_depth = 3
                        max_fanout = 5
                        depth = int(task.get("delegation_depth", 0) or 0) + 1
                        if depth > max_depth:
                            logger.warning(
                                "[Delegation] Tiefe %s > %s bei Task %s — weitere Nominierung abgelehnt.",
                                depth, max_depth, task_id,
                            )
                            ticker("Delegation", f"Task #{task_id}: maximale Delegationstiefe erreicht — keine weiteren Sub-Tasks.")
                            continue
                        nominated = _fanout_cap_guard(nominated, max_fanout, str(task_id), ticker)
                        proj_title = parsed_dispatch.project_title or task_title
                        batch_subtasks = []
                        for idx, nom in enumerate(nominated):
                            sub_agent_id = nom.agent_id.strip()
                            sub_role = nom.role or "Spezialist"
                            sub_mandate = nom.mandate.strip()
                            if not sub_agent_id or sub_agent_id.startswith("<"):
                                continue

                            # Passenden Namen und Profil suchen
                            sub_prof = next((p for p in profiles if p.get("id") == sub_agent_id), None)
                            sub_name = sub_prof.get("person_name", sub_agent_id) if sub_prof else sub_role
                            sub_task_id = f"task-{int(time.time() * 1000)}-{idx}"
                            sub_task_title = f"AP{idx+1}: {sub_role} - {proj_title}"

                            sub_task = {
                                "id": sub_task_id,
                                "delegation_depth": depth,
                                "parent_task_id": task_id,
                                "title": sub_task_title,
                                "capture_input": f"MANDAT VON STAFFING-DIRECTORIN ({agent_name}):\n\n{sub_mandate}\n\nProjekt-Kontext: {proj_title}",
                                "mandate": sub_mandate,
                                "role": sub_role,
                                "plan": [
                                    f"Empfangen von Mandat durch {agent_name}",
                                    f"Fachliche Ausarbeitung durch {sub_name} ({sub_agent_id})",
                                    "Dokumentation und Ablage in Obsidian"
                                ],
                                "agent_id": sub_agent_id,
                                "agent_name": sub_name,
                                "trace_id": nom.trace_id or str(task.get("trace_id") or ""),
                                "session_id": nom.session_id or str(task.get("session_id") or ""),
                                "correlation_id": nom.correlation_id or f"task:{task_id}",
                                "model": (sub_prof.get("model") if sub_prof else None) or "auto/best-free",
                                "estimated_tokens": 60000,
                                "estimated_cost_eur": 0.08,
                                "subagents_count": 0,  # F-007: noch keine eigenen Subtasks

                                "status": "approval",
                                "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                                "result_summary": "",
                                "artifact_path": "",
                                # F033: deklarierte Felder von Anfang an — der
                                # Produzent füllt sie bei Abschluss aus dem echten
                                # Dispatch-Result (siehe `_run_task`).
                                "consensus_verdict": "",
                                "verdict": "",
                                "decision_status": "",
                                "policy_violation": False,
                                "guardrail_violation": False,
                                "verdict_source": "",
                                "source_trace_id": str(task.get("trace_id") or ""),
                                "parent_project_id": task.get("parent_project_id") or task_id,
                                "target_action": task.get("target_action", "none"),
                                "phase": "execution"
                            }
                            batch_subtasks.append(sub_task)

                        # Komplexitätsgewichteter Budget-Split (Paperclip Governance)
                        try:
                            from backend.role_budget_engine import allocate_task_budget_to_subagents
                            # D13: kein Budget-Minting aus der Subtask-Anzahl.
                            # Fehlt das Elternbudget, muss die Engine fail-closed
                            # `NO_PARENT_BUDGET` liefern.
                            parent_tok_budget = int(task.get("token_budget") or 0)
                            parent_eur_budget = float(task.get("cost_limit_eur") or 0.0)
                            allocate_task_budget_to_subagents(
                                parent_task_id=task_id,
                                total_token_budget=parent_tok_budget,
                                subtasks=batch_subtasks,
                                total_cost_limit_eur=parent_eur_budget,
                            )
                        except Exception as _bg_err:
                            logger.debug(f"[Auto-Staffing] Budget-Split Fallback: {_bg_err}")

                        for sub_task in batch_subtasks:
                            sub_task_id = sub_task["id"]
                            sub_agent_id = sub_task["agent_id"]
                            sub_name = sub_task["agent_name"]
                            data.setdefault("tasks", []).insert(0, sub_task)
                            task.setdefault("subtask_ids", []).append(sub_task_id)
                            task["phase"] = "staffing"
                            ticker("Approval Gate", f"Neuer Sub-Task #{sub_task_id} ({sub_name}) wartet auf Freigabe!")
                            logger.info(f"[Auto-Staffing] Sub-Task #{sub_task_id} für {sub_name} im Approval Gate angelegt.")
                            # --- AUTO-HIRE HOOK ---
                            try:
                                _paperclip_hire_profile_by_id(sub_agent_id, profiles, current_task_id=sub_task_id)
                            except Exception as _hire_err:
                                logger.warning(f"[AutoHire/MusterB] {_hire_err}")

                        # D01/MED: nach dem Fan-out die Prognose durch die echte
                        # Subtask-Anzahl ersetzen. Der Task wird in `_commit()` (finally)
                        # atomar in den Task-Store gemergt.
                        if task.get("subtask_ids"):
                            task["subagents_count"] = len(task["subtask_ids"])
                            task["subagents_count_source"] = "actual"
                            task["subagents_count_estimated"] = False
            except Exception as parse_err:
                logger.warning(f"[Auto-Staffing] Fehler beim Parsen der Nominierungsmatrix: {parse_err}")

            # Cascade-Loop Schritt A: Hat Robert strategisch vorgelegt ohne direkte Nominierung? -> Sandy beauftragen
            # D02/MED: 'micha' ist aus der SSOT entfernt — nie wieder als Sonderfall.
            if agent_id in ("executive_decision_architect", "robert", "default") and not task.get("parent_project_id"):
                if not task.get("subtask_ids"):
                    _spawn_tracked(trigger_sandy(task, profiles), name="sandy_staffing")

            # Cascade-Loop Schritt B: Ist ein Sub-Task fertig und alle Geschwister-Tasks abgeschlossen? -> Synthese starten
            parent_pid = task.get("parent_project_id") or task.get("parent_task_id")
            parent_ok = bool(parent_pid and parent_pid != task_id)

        except asyncio.CancelledError:
            # CancelledError erbt BaseException — vorher blieb der Task in
            # 'approval'/'in_progress' und wurde vom Deadlock-Supervisor reaktiviert.
            logger.info("[MissionControl] Task %s durch Cancel abgebrochen.", task_id)
            parent_ok = False
            task["status"] = "cancelled"
            task["result_summary"] = "Aufgabe durch Operator abgebrochen"
            ticker("Mission Control", f"Task #{task_id} abgebrochen")
            raise
        except Exception as ex:
            logger.error(f"[Execution Error] _execute_mission_control_task {task_id}: {ex}")
            parent_ok = False
            task["status"] = "failed"
            task["result_summary"] = f"Fehler bei Aufgabenausführung: {ex}"
            ticker(agent_name or "Mission Control", f"Task #{task_id} fehlgeschlagen: {ex}")
        finally:
            # P0-6: Heartbeat stoppen, Lease freigeben, Idempotency-Key abschliessen.
            if heartbeat_task is not None:
                heartbeat_task.cancel()
            if lease_token and deadlock_supervisor is not None:
                try:
                    def _lease_release_sync():
                        return deadlock_supervisor.release_lease(str(task_id), lease_token)

                    await asyncio.shield(asyncio.to_thread(_lease_release_sync))
                except asyncio.CancelledError:
                    logger.warning("[MissionControl] Cancel während Lease-Release; Cleanup läuft weiter.")
                except Exception as rel_exc:
                    logger.warning(f"[MissionControl] Lease-Release fehlgeschlagen: {rel_exc}")
            if idem_key:
                try:
                    from backend.idempotency_guard import idempotency_guard

                    def _idem_finish_sync():
                        if task.get("status") == "completed":
                            idempotency_guard.record_execution_result(
                                idem_key,
                                {
                                    "status": "completed",
                                    "result_summary": mark_truncated(
                                        task.get("result_summary", ""), 300,
                                        artifact=f"tasks.result/{task_id}",
                                    ),
                                },
                            )
                        else:
                            # Fehlgeschlagener Lauf darf den Key nicht als "erledigt"
                            # markerieren — sonst wird der naechste Retry geblockt.
                            idempotency_guard.invalidate_key(idem_key)

                    await asyncio.shield(asyncio.to_thread(_idem_finish_sync))
                except asyncio.CancelledError:
                    logger.warning("[MissionControl] Cancel während Idempotency-Abschluss; Cleanup läuft weiter.")
                except Exception as idem_fin_exc:
                    logger.warning(f"[MissionControl] Idempotency-Abschluss fehlgeschlagen: {idem_fin_exc}")
            try:
                await asyncio.shield(_commit_async())
            except asyncio.CancelledError:
                logger.warning("[MissionControl] Cancel während Status-Commit; Commit läuft weiter.")
            # Audit v3 2.1.3: fan_in erst NACH dem Commit starten — sonst liest die Synthese
            # den alten Geschwister-Status aus der letzten Persistierung.
            if parent_ok:
                _spawn_tracked(fan_in(parent_pid), name=f"fan_in:{parent_pid}")
    except asyncio.CancelledError:
        # D02-H2: CancelledError erbt BaseException — ohne diesen aeusseren
        # Zweig blieb der Task in 'approval'/'in_progress' und wurde vom
        # Deadlock-Supervisor als kostenpflichtiger Geistertask reaktiviert.
        logger.info("[MissionControl] Task %s durch Cancel abgebrochen (aeussere Phase).", task_id)
        parent_ok = False
        if heartbeat_task is not None:
            heartbeat_task.cancel()
        if task is not None:
            task["status"] = "cancelled"
            task["result_summary"] = "Aufgabe durch Operator abgebrochen"
            ticker("Mission Control", f"Task #{task_id} abgebrochen")
            try:
                await asyncio.shield(_commit_async())
            except asyncio.CancelledError:
                logger.warning(
                    "[MissionControl] Cancel waehrend Cancel-Commit; Status 'cancelled' bleibt im Store gesetzt."
                )
        raise


def _paperclip_hire_profile_by_id(
    profile_id: str,
    profiles: list,
    current_task_id: str = "",
    *,
    set_status: Callable = None,
    ticker: Ticker = None,
) -> bool:
    """Aktiviert einen Agenten in agent_profiles.json: status='active', current_task_id=..."""
    if set_status is None:
        set_status = _set_agent_profile_status
    if ticker is None:
        from archon.core.runtime import add_ticker as ticker

    try:
        ok = set_status(profile_id, "active", current_task_id)
        if not ok:
            # R-19: kein Ticker/Erfolgslog, wenn das Status-Update den Agenten
            # nicht wirklich aktiviert hat (SSOT weg, Profil fehlt, Schreibfehler).
            logger.warning(f"[AutoHire] Status-Update für '{profile_id}' wirkungslos — Agent bleibt inaktiv.")
            return False
        prof = next((p for p in profiles if p.get("id") == profile_id), None)
        person_name = (prof.get("person_name") or prof.get("name") or profile_id) if prof else profile_id
        ticker("AutoHire", f"'{person_name}' aktiviert & Status -> active")
        logger.info(f"[AutoHire] '{profile_id}' erfolgreich aktiviert.")
        return True
    except Exception as e:
        logger.warning(f"[AutoHire] Status-Update für '{profile_id}' fehlgeschlagen: {e}")
        return False


def _set_agent_profile_status(
    profile_id: str,
    status: str,
    task_id: str = "",
    *,
    rolling_backup: RollingBackup = None,
    invalidate_profiles: InvalidateProfiles = None,
) -> bool:
    """Setzt status (und optional current_task_id) in agent_profiles.json (mit Rolling Backup)."""
    if rolling_backup is None:
        # R-19: create_rolling_backup lebt in archon.core.profiles, NICHT in
        # archon.core.runtime — der falsche Default-Import flog in den
        # blanket-except und der Auto-Hire meldete still "aktiviert", obwohl
        # nichts geschrieben wurde.
        from archon.core.profiles import create_rolling_backup as rolling_backup
    if invalidate_profiles is None:
        from archon.core.profiles import invalidate_hermes_profiles_cache as invalidate_profiles

    try:
        # R-19: SSOT ist agent_profiles.json im REPO-ROOT (runtime.APP_ROOT).
        # Vorher stand hier os.path.dirname(__file__) = archon/core — die
        # Schattenkopie archon/core/agent_profiles.json wurde in git versioniert,
        # die Wurzeldatei blieb unberuehrt.
        ssot = os.path.join(APP_ROOT, "agent_profiles.json")
        if not os.path.exists(ssot):
            logger.warning(f"[ProfileStatus] SSOT fehlt: {ssot} — Status-Update nicht moeglich.")
            return False
        with open(ssot, "r", encoding="utf-8") as f:
            all_profiles = json.load(f)
        changed = False
        for p in all_profiles:
            if p.get("id") == profile_id:
                p["status"] = status
                if task_id:
                    p["current_task_id"] = task_id
                elif "current_task_id" in p and status == "standby":
                    del p["current_task_id"]
                changed = True
                break
        if changed:
            rolling_backup(ssot, max_backups=3)
            with open(ssot, "w", encoding="utf-8") as f:
                json.dump(all_profiles, f, indent=2, ensure_ascii=False)
            # SSOT-Sync: auch profile.yaml im Hermes-Profilordner aktualisieren (falls vorhanden)
            try:
                import yaml

                from archon.core.profiles import get_hermes_profiles_base_dirs
                for bdir in get_hermes_profiles_base_dirs():
                    ypath = os.path.join(bdir, profile_id, "profile.yaml")
                    if os.path.isfile(ypath):
                        with open(ypath, "r", encoding="utf-8") as yf:
                            ydata = yaml.safe_load(yf) or {}
                        if isinstance(ydata, dict):
                            ydata["status"] = status
                            if task_id:
                                ydata["current_task_id"] = task_id
                            elif "current_task_id" in ydata and status == "standby":
                                del ydata["current_task_id"]
                            with open(ypath, "w", encoding="utf-8") as yf:
                                yaml.safe_dump(ydata, yf, allow_unicode=True, sort_keys=False)
            except Exception as yaml_exc:
                logger.debug(f"[ProfileStatus] profile.yaml Sync uebersprungen: {yaml_exc}")
            invalidate_profiles()
            logger.info(f"[ProfileStatus] '{profile_id}' → status='{status}'" + (f", task={task_id}" if task_id else ""))
            return True
        logger.warning(f"[ProfileStatus] Profil '{profile_id}' nicht in {ssot} gefunden.")
        return False
    except Exception as e:
        logger.warning(f"[ProfileStatus] Fehler beim Status-Update für '{profile_id}': {e}")
        return False


def _merge_sandy_delta(fresh: dict, local_data: dict, parent_id: str, created_sub_ids: list, local_tasks: list) -> None:
    """Überträgt nur die Sandy-Änderungen (neue Subtasks + Parent-Update) in den frisch geladenen Store."""
    fresh_tasks = fresh.setdefault("tasks", [])
    fresh_ids = {t.get("id") for t in fresh_tasks}

    # 1. Neue Subtasks hinzufügen (nur die, die es im fresh noch nicht gibt)
    for sub in local_tasks:
        if sub.get("id") not in fresh_ids:
            fresh_tasks.insert(0, sub)

    # 2. Parent-Task aktualisieren (subtask_ids, phase)
    for i, t in enumerate(fresh_tasks):
        if t.get("id") == parent_id:
            local_parent = next((pt for pt in local_data.get("tasks", []) if pt.get("id") == parent_id), None)
            if local_parent:
                fresh_tasks[i]["subtask_ids"] = local_parent.get("subtask_ids", fresh_tasks[i].get("subtask_ids", []))
                fresh_tasks[i]["phase"] = local_parent.get("phase", fresh_tasks[i].get("phase"))
            break


def _merge_synthesis_draft_delta(
    fresh: dict, parent_id: str, draft_path: str, fan_in: Optional[Dict[str, Any]] = None
) -> None:
    """Aktualisiert synthesis_draft_path und die Fan-in-Herkunft im Parent-Task."""
    for t in fresh.get("tasks", []):
        if t.get("id") == parent_id:
            t["synthesis_draft_path"] = draft_path
            if fan_in is not None:
                t["fan_in_child_ids"] = fan_in.get("child_ids", [])
                t["fan_in_statements"] = fan_in.get("statements", [])
            break


def _merge_synthesis_audit_delta(fresh: dict, parent_id: str, time_str: str, robert_reply: str, deci: dict | None, draft_name: str) -> None:
    """Fügt nur den audit_log Eintrag für die Synthese-Entscheidung hinzu (atomar via update_mc)."""
    fresh.setdefault("audit_logs", []).insert(0, {
        "time": time_str, "source": "Synthese-Loop",
        "msg": (f"Lisa-Entwurf für #{parent_id} braucht Freigabe "
                f"(Robert: {mark_truncated(robert_reply, 60, artifact=draft_name) or 'ohne Antwort'}) — "
                f"Kanban-Entscheidung {deci.get('task_id') if deci else 'NICHT angelegt'}")})


def _merge_finalize_synthesis_delta(fresh: dict, parent_pid: str, final_obs_path: str, local_parent: dict, audit_entry: dict) -> None:
    """Merged Parent-Task-Updates (status, phase, artifact_path, result_summary, synthesis_finalized, completed_at) + audit_logs."""
    for t in fresh.get("tasks", []):
        if t.get("id") == parent_pid:
            # Parent-Task-Felder übernehmen
            t["status"] = local_parent.get("status", t.get("status"))
            t["phase"] = local_parent.get("phase", t.get("phase"))
            t["artifact_path"] = local_parent.get("artifact_path", t.get("artifact_path"))
            t["result_summary"] = local_parent.get("result_summary", t.get("result_summary"))
            t["synthesis_finalized"] = local_parent.get("synthesis_finalized", t.get("synthesis_finalized"))
            t["completed_at"] = local_parent.get("completed_at", t.get("completed_at"))
            # F-040: Fehlergrund muss im persistierten Task sichtbar bleiben.
            if "failure_reason" in local_parent:
                t["failure_reason"] = local_parent["failure_reason"]
            break
    # audit_logs Eintrag hinzufügen
    fresh.setdefault("audit_logs", []).insert(0, audit_entry)


async def _trigger_sandy_staffing_nomination(
    parent_task: dict,
    profiles: list,
    *,
    dispatcher: Dispatcher = None,
    load_mc: LoadMC = _default_load_mc,
    save_mc: SaveMC = _default_save_mc,
    update_mc: Optional[Callable] = None,
    ticker: Ticker = None,
    get_profiles: GetProfiles = None,
    paperclip_hire: Callable = None,
) -> None:
    """Lässt Sandy Hooks (labor_law_hr_governance) anhand des Strategieentwurfs die Fachagenten nominieren."""
    if dispatcher is None:
        import core_dispatcher as dispatcher
    if ticker is None:
        from archon.core.runtime import add_ticker as ticker
    if get_profiles is None:
        from archon.core.profiles import api_get_hermes_profiles as get_profiles
    if paperclip_hire is None:
        paperclip_hire = _paperclip_hire_profile_by_id

    parent_id = parent_task.get("id")
    parent_title = parent_task.get("title", "Projekt")
    strategy_content = parent_task.get("result_summary") or parent_task.get("capture_input", "")

    sandy_prof = next((p for p in profiles if p.get("id") == "labor_law_hr_governance" or "sandy" in p.get("person_name", "").lower()), None)
    sandy_model = (sandy_prof.get("model") if sandy_prof else None) or "anthropic/claude-3.7-sonnet"
    sandy_sys = (sandy_prof.get("system_prompt") if sandy_prof else None) or "Du bist Sandy Hooks, Staffing-Directorin von Archon OS."

    roster_lines = [
        f"- {p.get('id')}: {p.get('person_name') or p.get('name') or p.get('id')} ({p.get('role') or p.get('category') or 'Spezialist'})"
        for p in (profiles or [])
        if p.get("id") and p.get("id") not in ("default", "telegram_bot")
    ][:60]
    roster_text = "\n".join(roster_lines) if roster_lines else "- research_scout\n- senior_fullstack_engineer\n- storyteller_ghostwriter"

    prompt = f"""Als HR- & Staffing-Directorin nominiere bitte für folgende Strategie 2 bis 3 spezialisierte Fachagenten zur operativen Umsetzung:

PROJEKT: {parent_title}
STRATEGIE:
{strategy_content}

VERFUEGBARE AGENTEN-IDS IM KADER (waehle AUSSCHLIESSLICH exakt aus dieser Liste):
{roster_text}

Gib deine Antwort AUSSCHLIESSLICH als valides JSON im folgenden Format zurück:
```json
{{
  "project_title": "{parent_title}",
  "nominated_agents": [
    {{
      "agent_id": "<exakte_id_aus_obiger_liste>",
      "role": "<rollenbezeichnung>",
      "mandate": "<konkreter operativer Auftrag für diesen Agenten>"
    }}
  ]
}}
```"""

    ticker("Sandy Hooks", f"Nominiert Umsetzungsteam für #{parent_id}: '{parent_title[:30]}...'")
    try:
        res = await dispatcher.dispatch_to_omniroute_or_container(
            agent_id="labor_law_hr_governance",
            agent_name="Sandy Hooks (Staffing-Directorin)",
            prompt=prompt,
            role="Staffing-Directorin",
            system_prompt=sandy_sys,
            model=sandy_model,
        )
        reply = res.get("content", "").strip()
        # Lokalen Snapshot laden, Änderungen vorbereiten
        data = load_mc()
        candidate_blocks = _extract_nominated_json_blocks(reply)

        created_sub_ids = []
        created_subtasks = []
        for jm in candidate_blocks:
            parsed = _parse_nomination_batch(jm)
            if parsed is None:
                continue
            nominated = parsed.nominated_agents
            if len(nominated) > 0:
                # H7 (Audit 23.11.2026): dieser Sandy-Staffing-Pfad hatte —
                # anders als der Parallelpfad (Zeile 357+) — KEINE Tiefen- oder
                # Fanout-Begrenzung und schrieb kein delegation_depth, sodass
                # die Rekursionsschranke bei jedem Lauf neu bei 0 begann.
                max_depth = 3
                max_fanout = 5
                depth = int(parent_task.get("delegation_depth", 0) or 0) + 1
                if depth > max_depth:
                    logger.warning(
                        "[Delegation] Sandy-Pfad: Tiefe %s > %s bei Task %s — Nominierung abgelehnt.",
                        depth, max_depth, parent_id,
                    )
                    ticker("Delegation", f"Task #{parent_id}: maximale Delegationstiefe erreicht.")
                    continue
                nominated = _fanout_cap_guard(nominated, max_fanout, str(parent_id), ticker)
                for idx, nom in enumerate(nominated):
                    sub_agent_id = nom.agent_id.strip()
                    sub_role = nom.role or "Spezialist"
                    sub_mandate = nom.mandate.strip()
                    if not sub_agent_id or sub_agent_id.startswith("<"):
                        continue
                    sub_prof = next((p for p in profiles if p.get("id") == sub_agent_id), None)
                    sub_name = sub_prof.get("person_name", sub_agent_id) if sub_prof else sub_role
                    sub_task_id = f"task-{int(time.time() * 1000)}-{idx}"
                    sub_task_title = f"AP{idx+1}: {sub_role} - {parent_title}"

                    sub_task = {
                        "id": sub_task_id,
                        "title": sub_task_title,
                        "capture_input": f"MANDAT VON STAFFING-DIRECTORIN (Sandy Hooks):\n\n{sub_mandate}\n\nProjekt-Kontext: {parent_title}",
                        "plan": [
                            "Empfangen von Mandat durch Sandy Hooks",
                            f"Fachliche Ausarbeitung durch {sub_name} ({sub_agent_id})",
                            "Dokumentation und Ablage in Obsidian"
                        ],
                        "agent_id": sub_agent_id,
                        "agent_name": sub_name,
                        "trace_id": nom.trace_id or str(parent_task.get("trace_id") or ""),
                        "session_id": nom.session_id or str(parent_task.get("session_id") or ""),
                        "correlation_id": nom.correlation_id or f"task:{parent_id}",
                        "model": (sub_prof.get("model") if sub_prof else None) or "auto/best-free",
                        "estimated_tokens": 60000,
                        "estimated_cost_eur": 0.08,
                        "subagents_count": 0,  # F-007: noch keine eigenen Subtasks

                        "delegation_depth": depth,
                        "status": "approval",
                        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "result_summary": "",
                        "artifact_path": "",
                        # F033: dieselben deklarierten Felder wie im Hauptpfad.
                        "consensus_verdict": "",
                        "verdict": "",
                        "decision_status": "",
                        "policy_violation": False,
                        "guardrail_violation": False,
                        "verdict_source": "",
                        "source_trace_id": str(parent_task.get("trace_id") or ""),
                        "parent_project_id": parent_id,
                        "parent_task_id": parent_id,
                        "target_action": parent_task.get("target_action", "none"),
                        "phase": "execution"
                    }
                    data.setdefault("tasks", []).insert(0, sub_task)
                    created_sub_ids.append(sub_task_id)
                    created_subtasks.append(sub_task)
                    ticker("Approval Gate", f"Neuer Sub-Task #{sub_task_id} ({sub_name}) wartet auf Freigabe!")

                    # --- AUTO-HIRE HOOK: Agent in Paperclip registrieren & Status auf 'active' ---
                    try:
                        paperclip_hire(sub_agent_id, profiles, current_task_id=sub_task_id)
                    except Exception as hire_err:
                        logger.warning(f"[AutoHire] Hire fehlgeschlagen für '{sub_agent_id}': {hire_err}")

        if created_subtasks:
            try:
                from backend.role_budget_engine import allocate_task_budget_to_subagents
                # D13: kein Budget-Minting — fehlendes Elternbudget blockiert.
                p_tok = int(parent_task.get("token_budget") or 0)
                p_eur = float(parent_task.get("cost_limit_eur") or 0.0)
                allocate_task_budget_to_subagents(
                    parent_task_id=str(parent_id or ""),
                    total_token_budget=p_tok,
                    subtasks=created_subtasks,
                    total_cost_limit_eur=p_eur,
                )
            except Exception as _bg_exc:
                logger.debug(f"[Sandy-Staffing] Budget-Split Fallback: {_bg_exc}")

        # Parent-Task im lokalen Snapshot updaten (subtask_ids, phase)
        local_parent = next((t for t in data.get("tasks", []) if t.get("id") == parent_id), None)
        if local_parent and created_sub_ids:
            local_parent.setdefault("subtask_ids", []).extend(created_sub_ids)
            local_parent["phase"] = "staffing"

        # Atomares Commit: nur unser Delta (neue Subtasks + Parent-Update) in den frischen Store mergen
        def _commit():
            if update_mc is not None:
                update_mc(lambda fresh: _merge_sandy_delta(fresh, data, parent_id, created_sub_ids, created_subtasks))  # type: ignore[arg-type]
            else:
                raise RuntimeError(
                    "_trigger_sandy_staffing_nomination: Parameter 'update_mc' fehlt. "
                    "main.py injiziert update_mission_control_data; Aufrufer muessen die "
                    "Abhaengigkeit explizit uebergeben."
                )
        _commit()
    except Exception as e:
        logger.warning(f"[Cascade-Loop] Fehler bei Sandy-Staffing: {e}")


async def _finalize_synthesis_after_approval(
    parent_pid: str,
    draft_path: str,
    synthese_text: str,
    approver_note: str,
    daten: dict = None,
    *,
    dispatcher: Dispatcher = None,
    load_mc: LoadMC = _default_load_mc,
    save_mc: SaveMC = _default_save_mc,
    update_mc: Optional[Callable] = None,
    ticker: Ticker = None,
    paths: Dict[str, str] = None,
    folder_namer: FolderNamer = None,
    set_status: Callable = None,
    tg_ping: Callable = None,
) -> None:
    """Schliesst die Synthese NACH Robert-Freigabe ab: finaler Bericht in 01_PROJEKTE, Parent-Task completed, Audit/Ticker, Demobilisierung, n8n."""
    if dispatcher is None:
        import core_dispatcher as dispatcher
    if ticker is None:
        from archon.core.runtime import add_ticker as ticker
    if paths is None:
        paths = {"OBSIDIAN_VAULT_DIR": DEFAULT_OBSIDIAN_VAULT_DIR, "WORKSPACE_DIR": DEFAULT_WORKSPACE_DIR}
    if folder_namer is None:
        try:
            from backend.post_task_pipeline import project_folder_name as folder_namer
        except Exception as exc:
            # D01-M7: kein stiller Empty-Path-Fallback. Ohne den echten
            # Ordner-Namer landet der Bericht ausserhalb 01_PROJEKTE bzw. in
            # einem leeren Pfad. Fail-closed statt "" als Ordnername.
            raise RuntimeError(
                "project_folder_name unavailable — synthesis aborted"
            ) from exc
    if set_status is None:
        set_status = _set_agent_profile_status
    if tg_ping is None:
        tg_ping = _tg_ping_synthesis
    if update_mc is None:
        raise RuntimeError(
            "_finalize_synthesis_after_approval: Parameter 'update_mc' fehlt. "
            "main.py injiziert update_mission_control_data; Aufrufer muessen die "
            "Abhaengigkeit explizit uebergeben."
        )

    try:
        data = daten if daten is not None else load_mc()
        parent_task = next((t for t in data.get("tasks", []) if t.get("id") == parent_pid), None)
        if not parent_task:
            logger.warning(f"[Synthese] Parent '{parent_pid}' beim Finalisieren nicht gefunden")
            return
        if parent_task.get("synthesis_finalized"):
            return
        parent_title = parent_task.get("title", "Gesamtprojekt")
        safe_pid = re.sub(r'[^a-zA-Z0-9_\-]+', '-', parent_pid).strip('-') or "projekt"
        final_body = (f"# Finale Beschlussvorlage: {parent_title}\n\n"
                      f"{synthese_text}\n\n---\n"
                      f"**Freigabe:** {approver_note}\n")
        final_name = f"{safe_pid}_final_beschlussvorlage.md"
        target_dirs = [
            PROJEKTE_DIR,
            os.path.join(paths["OBSIDIAN_VAULT_DIR"], "01_PROJEKTE"),
            os.path.join(paths["WORKSPACE_DIR"], "obsidian_vault", "01_PROJEKTE"),
        ]
        # 12.10.2026 (Ordnerflut-Fix): finaler Bericht in den EINEN Projekt-Ordner.
        try:
            _fan_ordner = folder_namer({"parent_project_id": parent_pid, "parent_project_title": parent_title})
        except Exception as exc:
            # D01-M7: Ausfall des Namers darf nicht als leerer Zielordner
            # durchgewinkt werden. Kein Artefakt, kein "completed".
            raise RuntimeError(
                "Projektordner nicht bestimmbar — Synthese abgebrochen (D01-M7)"
            ) from exc
        final_obs_path = (os.path.join(PROJEKTE_DIR, _fan_ordner, "03_Endprodukte", final_name)
                          if _fan_ordner else os.path.join(PROJEKTE_DIR, final_name))
        # D03-M1: derselbe atomare, verifizierte Writer wie im Entwurfspfad
        # (_run_synthesis_cascade, Z. ~1762-1769): commonpath-Jail, Temp im
        # selben Verzeichnis, fsync, os.replace, size>0 und SHA-256 gegen den
        # erwarteten Inhalt. Teilfehler werden gesammelt und fuehren zum Block.
        import hashlib

        final_sha256 = hashlib.sha256(final_body.encode("utf-8")).hexdigest()
        written = False
        final_write_errors: List[str] = []
        for d in target_dirs:
            d_ziel = ""
            tmp_p = ""
            try:
                d_ziel = os.path.join(d, _fan_ordner, "03_Endprodukte") if _fan_ordner else d
                p = os.path.join(d_ziel, final_name)
                if os.path.commonpath([os.path.abspath(p), os.path.abspath(d_ziel)]) != os.path.abspath(d_ziel):
                    raise ValueError(f"Ziel ausserhalb des erlaubten Verzeichnisses: {p}")
                os.makedirs(d_ziel, exist_ok=True)
                tmp_p = os.path.join(d_ziel, f".{final_name}.tmp_{os.getpid()}_{int(time.time() * 1000)}")
                # newline="" verhindert auf Windows die CRLF-Uebersetzung, sonst
                # weicht die Datei (und ihr SHA-256) vom erwarteten Inhalt ab.
                with open(tmp_p, "w", encoding="utf-8", newline="") as f:
                    f.write(final_body)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_p, p)
                tmp_p = ""
                if not (os.path.isfile(p) and os.path.getsize(p) > 0):
                    raise IOError(f"Atomare Verifikation fehlgeschlagen (leer/fehlt): {p}")
                with open(p, "rb") as fh:
                    if hashlib.sha256(fh.read()).hexdigest() != final_sha256:
                        raise IOError(f"SHA-256-Verifikation fehlgeschlagen: {p}")
                written = True
                final_obs_path = p
            except Exception as we:
                final_write_errors.append(f"{d}: {we}")
                logger.error(
                    "[Synthese] Atomares Schreiben des Finalberichts nach %s fehlgeschlagen: %s",
                    d, we,
                )
            finally:
                if tmp_p:
                    try:
                        os.unlink(tmp_p)
                    except OSError:
                        pass

        # D03-M1: JEDER Ziel-Fehler blockiert, auch bei mindestens einem Erfolg.
        if not written or final_write_errors:
            # F-040: fehlgeschlagene Verifikation darf NIE `completed`+"finalisiert"
            # ergeben. Stattdessen terminal blockieren und eskalieren.
            reason = (
                "Synthese-Artefakt konnte nicht atomar in allen Zielverzeichnissen abgelegt werden"
                + (f": {'; '.join(final_write_errors)}" if final_write_errors else "")
            )
            logger.error(f"[Synthese] {reason} (parent={parent_pid})")
            parent_task["status"] = "blocked"
            parent_task["phase"] = "blocked"
            parent_task["artifact_path"] = ""
            parent_task["failure_reason"] = reason
            parent_task["synthesis_finalized"] = False
            if update_mc is not None:
                update_mc(lambda fresh: _merge_finalize_synthesis_delta(
                    fresh, parent_pid, "", parent_task,
                    {"time": datetime.datetime.now().strftime("%H:%M:%S"),
                     "source": "Synthese-Loop",
                     "msg": f"FEHLER: {reason} (#{parent_pid})"},
                ))
            if ticker is not None:
                ticker("Synthese-Loop", f"⛔ {reason} — Eskalation erforderlich")
            try:
                if tg_ping is not None:
                    tg_ping(f"⛔ Synthese #{parent_pid} blockiert: {reason}")
            except Exception:
                pass
            return

        # Parent-Task lokal updaten
        parent_task["status"] = "completed"
        parent_task["phase"] = "completed"
        parent_task["artifact_path"] = final_obs_path
        parent_task["result_summary"] = mark_truncated(
            synthese_text, 500, artifact=final_obs_path or f"tasks.result/{parent_pid}"
        )
        parent_task["synthesis_finalized"] = True
        parent_task["completed_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        now_t = datetime.datetime.now().strftime("%H:%M:%S")

        # Audit-Log-Eintrag lokal vorbereiten
        audit_entry = {
            "time": now_t, "source": "Synthese-Loop",
            "msg": f"Finale Beschlussvorlage fuer #{parent_pid} freigegeben und abgelegt ({mark_truncated(approver_note, 60, artifact=final_obs_path)})"
        }

        # Atomares Commit: Parent-Task-Felder + audit_logs mergen
        def _commit():
            if update_mc is not None:
                update_mc(lambda fresh: _merge_finalize_synthesis_delta(
                    fresh, parent_pid, final_obs_path, parent_task, audit_entry))
            else:
                raise RuntimeError(
                    "_finalize_synthesis_after_approval: Parameter 'update_mc' fehlt. "
                    "main.py injiziert update_mission_control_data; Aufrufer muessen die "
                    "Abhaengigkeit explizit uebergeben."
                )
        _commit()

        ticker("Synthese-Loop", f"Freigabe: finale Beschlussvorlage fuer '{parent_title[:35]}...' bereit")

        # Demobilisierung der Fachagenten (Stammagenten bleiben aktiv)
        try:
            sibs = [t for t in data.get("tasks", [])
                    if (t.get("parent_project_id") == parent_pid or t.get("parent_task_id") == parent_pid)]
            demob_ids = list({s.get("agent_id") for s in sibs if s.get("agent_id")})
            for agent_id_dem in demob_ids:
                if agent_id_dem in ("executive_decision_architect", "robert", "labor_law_hr_governance", "sandy", "aggregation_lisa"):
                    continue
                set_status(agent_id_dem, "standby")
            if demob_ids:
                ticker("Demobilisierung", f"{len(demob_ids)} Fachagent(en) nach Projektabschluss auf Standby gesetzt")
        except Exception as demob_err:
            logger.warning(f"[Demobilisierung] Fehler: {demob_err}")

        # n8n-Bridge (bestehender Einbaupunkt)
        target_action = parent_task.get("target_action") or "none"
        try:
            n8n_res = await dispatcher.trigger_n8n_execution(
                parent_project_id=parent_pid,
                title=parent_title,
                final_report_path=final_obs_path,
                content=synthese_text,
                target_action=target_action,
            )
            logger.info(f"[Synthese-Loop] n8n Webhook Ergebnis: {n8n_res}")
            ticker("n8n Bridge", f"Action '{target_action}' an n8n uebergeben ({n8n_res.get('status')})")
        except Exception as n8n_err:
            logger.warning(f"[Synthese-Loop] n8n Trigger fehlgeschlagen: {n8n_err}")
    except Exception as fin_err:
        logger.warning(f"[Synthese] Finalisierung fehlgeschlagen: {fin_err}")


def fan_in_start_decision(fresh: Dict[str, Any], parent_pid: str) -> Dict[str, Any]:
    """Reine Fan-in-Entscheidung (testbar ohne SQLite/Locks).

    H-02-2/F031: `cancelled` ist terminal und wird wie ein fehlgeschlagenes
    Geschwister behandelt: Parent `blocked` + `failure_reason` + HITL-Kette,
    aber KEINE Synthese (kein Coroutine-Replay, keine erfundenen Resultate).
    """
    decision: Dict[str, Any] = {}
    tasks = fresh.get("tasks", []) or []
    siblings = [t for t in tasks
                if (t.get("parent_project_id") == parent_pid or t.get("parent_task_id") == parent_pid)
                and t.get("id") != parent_pid]
    parent = next((t for t in tasks if t.get("id") == parent_pid), None)
    if not siblings or not parent:
        decision["skip"] = True
        return decision
    if parent.get("synthesis_started"):
        decision["skip"] = True
        return decision
    terminal_states = {"completed", "done", "review", "failed", "blocked", "error", "cancelled"}
    if not all(s.get("status") in terminal_states for s in siblings):
        decision["skip"] = True
        return decision
    failed = [s for s in siblings if s.get("status") not in ("completed", "done", "review")]
    if failed:
        failed_ids = ", ".join(str(s.get("id") or "?") for s in failed)
        cancelled_ids = ", ".join(
            str(s.get("id") or "?") for s in failed if str(s.get("status")) == "cancelled"
        )
        parent["status"] = "blocked"
        parent["phase"] = "blocked"
        reason = (
            f"Teilaufgabe abgebrochen: {cancelled_ids}. HITL-Eskalation erforderlich."
            if cancelled_ids else f"Teilaufgaben fehlgeschlagen/blockiert: {failed_ids}"
        )
        parent["failure_reason"] = reason
        parent["fan_in_escalation"] = "hitl_required" if cancelled_ids else "failed_siblings"
        decision["blocked"] = failed_ids
        decision["cancelled"] = cancelled_ids
        logger.warning(
            "[Fan-in] Parent '%s' blockiert — abgebrochene/fehlgeschlagene Kinder: %s",
            parent_pid, failed_ids,
        )
        return decision
    parent["synthesis_started"] = True
    parent["synthesis_started_at"] = datetime.datetime.now().isoformat()
    decision["start"] = len(siblings)
    return decision


async def _fan_in_maybe_start_synthesis(
    parent_pid: str,
    *,
    load_mc: LoadMC = _default_load_mc,
    write_mc_atomic: Callable = _write_mc_atomic,
    update_mc: Optional[Callable] = _default_update_mc,
    mc_async_lock: asyncio.Lock = _MC_ASYNC_LOCK,
    run_cascade: Callable = None,
) -> None:
    """FAN-IN (12.10.2026): Alle Geschwister des Delegationsprojekts completed? -> Synthese-Loop starten."""
    if not parent_pid:
        return
    if run_cascade is None:
        run_cascade = _run_synthesis_cascade
    try:
        # KRITISCH: früher wurde ein Snapshot über das await gehalten und mit
        # _write_mc_atomic(overwrite=True) zurückgeschrieben. Parallel fertig
        # gewordene Geschwister wurden auf alte Stände zurückgesetzt und die
        # 25 letzten Audit-Sigs erneut eingefügt. Jetzt läuft Prüfung + Flag
        # in EINEM update_mc-Mutator (BEGIN IMMEDIATE, previous_ids, audit_sigs).
        decision: Dict[str, Any] = {}

        def _mutate(fresh: Dict[str, Any]) -> None:
            decision.update(fan_in_start_decision(fresh, parent_pid))

        async with mc_async_lock:
            if update_mc is not None:
                await asyncio.to_thread(update_mc, _mutate)
            else:  # Rückwärtskompatibilität für alte Aufrufer
                data = await asyncio.to_thread(load_mc)
                _mutate(data)
                # Kein Schreiben, wenn die Prüfung übersprungen wurde (keine
                # Geschwister, bereits gestartet, Parent fehlt) — sonst werden
                # unnötig Snapshots/Audit-Sigs erzeugt.
                if not decision.get("skip"):
                    await asyncio.to_thread(write_mc_atomic, data)

        if decision.get("blocked"):
            logger.warning(
                "[Fan-in] Parent '%s' eskaliert/blockiert wegen fehlgeschlagener Geschwister: %s",
                parent_pid, decision["blocked"],
            )
            return
        if decision.get("start"):
            logger.info(
                "[Fan-in] Alle %s Geschwister von '%s' fertig -> Synthese starten",
                decision["start"], parent_pid,
            )
            _spawn_tracked(run_cascade(parent_pid), name=f"synthesis:{parent_pid}")
    except Exception as e:
        logger.warning(f"[Fan-in] Synthese-Check fehlgeschlagen: {e}")


def _tg_ping_synthesis(
    parent_title: str,
    parent_project_id: str,
    synthese_text: str,
    draft_path: str,
    app_id: str = None,
    dossier_dir: str = None,
    *,
    send_doc: TelegramSendDoc = None,
    send_msg: TelegramSendMsg = None,
    build_dossier: BuildDossier = None,
) -> None:
    """2a: Synthese-Bericht als Telegram-Ping MIT Dossier-Anhang."""
    if send_doc is None:
        from telegram_notify import send_telegram_document as send_doc
    if send_msg is None:
        from telegram_notify import send_telegram_message as send_msg
    if build_dossier is None:
        try:
            from dossier_builder import build_dossier_from_report as build_dossier
        except Exception:
            build_dossier = None

    try:
        dpath = None
        if dossier_dir and build_dossier:
            try:
                dpath = build_dossier(
                    f"Synthese: {parent_title}", synthese_text, dossier_dir,
                    f"{re.sub(r'[^a-zA-Z0-9_-]+', '-', str(parent_project_id))[:40]}_synthese",
                    ref_id=parent_project_id, quelle="deterministic_fan_in")
            except Exception as _e:
                logger.warning(f"[Synthese] Dossier-Aufbau fehlgeschlagen: {_e}")
        _kurz = mark_truncated(
            re.sub(r"\s+", " ", (synthese_text or "")).strip(), 300,
            artifact=dpath or f"tasks.result/{parent_project_id}",
        )
        caption = ("🔐 ENTSCHEIDUNG NÖTIG — Synthese\n"
                   f"Projekt: {parent_title}\n\n{_kurz}"
                   + ("\n\nDer vollständige Entwurf liegt als Anhang bei." if dpath else ""))
        markup = None
        if app_id:
            markup = {"inline_keyboard": [[
                {"text": "✅ Freigeben", "callback_data": f"app:approve:{app_id}"},
                {"text": "❌ Ablehnen", "callback_data": f"app:reject:{app_id}"},
            ]]}
        if dpath and send_doc(dpath, caption=caption, reply_markup=markup):
            return
        if dpath:
            logger.warning("[Synthese] Dossier-Ping fehlgeschlagen — Text-Ping stattdessen.")
        from telegram_notify import tg_escape as _tg_esc
        safe_caption = (
            "🔐 <b>ENTSCHEIDUNG NÖTIG — Synthese</b>\n"
            f"<b>Projekt:</b> {_tg_esc(parent_title)}\n\n{_tg_esc(_kurz)}"
            + ("\n\nDer vollständige Entwurf liegt als Anhang bei." if dpath else "")
            + (f"\n\n📄 Entwurf: <code>{_tg_esc(draft_path)}</code>" if draft_path else "")
        )
        send_msg(safe_caption, reply_markup=markup)
    except Exception as e:
        logger.warning(f"[Synthese] Telegram-Ping fehlgeschlagen: {e}")


async def _run_synthesis_cascade(
    parent_project_id: str,
    *,
    dispatcher: Dispatcher = None,
    load_mc: LoadMC = _default_load_mc,
    save_mc: SaveMC = _default_save_mc,
    update_mc: Optional[Callable] = None,
    ticker: Ticker = None,
    get_profiles: GetProfiles = None,
    paths: Dict[str, str] = None,
    folder_namer: FolderNamer = None,
    build_dossier: BuildDossier = None,
    create_decision: CreateDecision = None,
    finalize_approval: Callable = None,
    tg_ping: Callable = None,
) -> None:
    """
    FAN-IN SYNTHESE (12.10.2026, User-Entscheidung A+B; H-15-4/F023):
    1. Sammelt alle Teilergebnisse der Fachagenten fuer parent_project_id.
    2. `deterministic_fan_in` fuegt sie regelbasiert zusammen (KEIN LLM-Dispatch
       und keine ausfuehrende Rolle 'aggregation_lisa' mehr).
    3. `red_team_challenger` prueft den Entwurf (fail-closed, kein stilles
       Ueberspringen); ROBERT (executive_decision_architect) gibt frei.
    4a. FREIGABE  -> finaler Bericht in 01_PROJEKTE + n8n-Bridge.
    4b. ABLEHNUNG -> Entwurf bleibt als Approval-Task im Board liegen.
    """
    if dispatcher is None:
        import core_dispatcher as dispatcher
    if ticker is None:
        from archon.core.runtime import add_ticker as ticker
    if get_profiles is None:
        from archon.core.profiles import api_get_hermes_profiles as get_profiles
    if paths is None:
        paths = {"OBSIDIAN_VAULT_DIR": DEFAULT_OBSIDIAN_VAULT_DIR, "WORKSPACE_DIR": DEFAULT_WORKSPACE_DIR}
    if folder_namer is None:
        try:
            from backend.post_task_pipeline import project_folder_name as folder_namer
        except Exception as exc:
            # D01-M7: kein stiller Empty-Path-Fallback. Ohne den echten
            # Ordner-Namer landet der Bericht ausserhalb 01_PROJEKTE bzw. in
            # einem leeren Pfad. Fail-closed statt "" als Ordnername.
            raise RuntimeError(
                "project_folder_name unavailable — synthesis aborted"
            ) from exc
    if build_dossier is None:
        try:
            from dossier_builder import build_dossier_from_report as build_dossier
        except Exception:
            build_dossier = None
    if create_decision is None:
        try:
            # A1: Fallback ueber die bestehende zyklusfreie Factory-Injektion
            # (archon.core.permissions, registriert in main.py:2010) statt
            # archon.core -> archon.routers. Parameter-Injektion bleibt vorrangig.
            from archon.core.permissions import get_decision_factory
            create_decision = get_decision_factory()
        except Exception:
            create_decision = None
    if finalize_approval is None:
        finalize_approval = _finalize_synthesis_after_approval
    if tg_ping is None:
        tg_ping = _tg_ping_synthesis

    logger.info(f"[Cascade-Loop] Starte Synthese fuer Parent-Projekt {parent_project_id}")
    # Initialen Snapshot laden (nur für Parent-Titel und Geschwister)
    data = load_mc()
    tasks = data.get("tasks", [])
    parent_task = next((t for t in tasks if t.get("id") == parent_project_id), None)
    if not parent_task:
        logger.warning(f"[Cascade-Loop] Parent-Task {parent_project_id} nicht gefunden!")
        return

    siblings = [
        t for t in tasks
        if (t.get("parent_project_id") == parent_project_id or t.get("parent_task_id") == parent_project_id)
        and t.get("id") != parent_project_id
    ]

    # Berichte auslesen (Artifact bevorzugt, sonst result_summary) - synchron, kein await
    # D11/S-11.3+S-11.4: jede Kuerzung ist markiert, jede Aussage traegt die
    # echte Kind-Identitaet sowie trace_id/session_id/correlation_id.
    reports = []
    fan_statements: List[Dict[str, Any]] = []
    from backend.consensus_gate import _infer_tier as _fan_tier
    for s in siblings:
        sub_title = s.get("title", "Teilaufgabe")
        sub_agent = s.get("agent_name") or s.get("agent_id") or "Fachagent"
        art_path = s.get("artifact_path", "")
        content = ""
        if art_path and os.path.exists(art_path):
            try:
                with open(art_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as read_exc:
                logger.warning(f"[Orchestration] Artefakt {art_path} konnte nicht gelesen werden: {read_exc}")
        if not content:
            content = str(s.get("result_summary") or "")
        original_length = len(content)
        child_id = str(s.get("id") or "")
        child_agent = str(s.get("agent_id") or s.get("assignee") or s.get("agent_name") or "unknown")
        artifact_ref = art_path or f"tasks.result/{child_id}"
        display_content = mark_truncated(content, 4000, artifact=artifact_ref)
        reports.append(f"### Arbeitspaket von {sub_agent} ({sub_title})\n\n{display_content}\n")
        # F033/H-14-1: ECHTER PRODUZENT der Konsens-Marker. Die Felder kommen
        # aus dem Dispatch-Result des Kindes (siehe `_run_task`), nicht aus
        # Freitext. `_marker_line` ist nie dauerhaft „": ein Kind ohne
        # strukturiertes Urteil wird als explizite Enthaltung markiert.
        _marker_line = fan_verdict_marker(s)
        _child_policy = bool(s.get("policy_violation") or s.get("guardrail_violation"))
        _child_guardrail = bool(s.get("guardrail_violation"))
        fan_statements.append({
            "agent_id": child_agent,
            "content": display_content + f"\n{_marker_line}",
            "tier": _fan_tier(child_agent),
            "policy_violation": _child_policy,
            "guardrail_violation": _child_guardrail,
            "severity": str(s.get("severity") or "") or ("high" if _child_policy else None),
            "verdict_source": str(s.get("verdict_source") or ""),
            "source_trace_id": str(s.get("source_trace_id") or s.get("trace_id") or ""),
            "trace_id": str(s.get("trace_id") or parent_task.get("trace_id") or ""),
            "session_id": str(s.get("session_id") or parent_task.get("session_id") or ""),
            "correlation_id": str(s.get("correlation_id") or (f"task:{child_id}" if child_id else "")),
            "task_id": child_id,
            "artifact_path": artifact_ref,
            "truncated": original_length > 4000,
            "original_length": original_length,
        })
    combined_reports = "\n---\n\n".join(reports)
    parent_title = parent_task.get("title", "Gesamtprojekt")

    # --- SCHRITT 1: DETERMINISTISCHE FAN-IN-SYNTHESE (kein LLM-Prompt) ---
    # Die alte "aggregation_lisa" war ein LLM-Prompt inkl. Marker-Repair-Retry.
    # Jetzt: votes-/evidence-basierte Auswertung + deterministische Struktur.
    # Kein neues LLM, keine erfundenen Fakten, Widersprüche bleiben sichtbar.
    from backend.consensus_gate import resolve_debate_consensus, validate_debate_statements

    profiles = get_profiles() if get_profiles else []
    _MARKER = "SYNTHESE-BEREIT"
    ticker(
        "Fan-In",
        f"Fuegt {len(reports)} Teilergebnisse deterministisch zu '{parent_title[:30]}...' zusammen",
    )

    # Pydantic-Validierung (DebateStatement, extra=forbid) vor der Konsensauswertung.
    fan_consensus = resolve_debate_consensus(validate_debate_statements(fan_statements))
    # B7: ALLE NO_CONSENSUS*-Verdikte (inkl. NO_CONSENSUS_BY_AUTHORITY und
    # NO_CONSENSUS_POLICY_VIOLATION) sperren die Finalisierung. Der Verdict
    # wird einmal zentral abgeleitet, nicht mehrfach und abweichend gelesen.
    _fan_verdict = str((fan_consensus or {}).get("verdict") or "").strip().upper()
    _fan_final_ok = _fan_verdict.startswith("CONSENSUS_REACHED")
    _fan_policy_veto = _fan_verdict == "NO_CONSENSUS_POLICY_VIOLATION"
    _negative_markers = {
        "KEIN KONSENS", "KEIN CONSENSUS", "NICHT ERREICHT", "NO CONSENSUS",
        "WIDERSPRUCH", "DISAGREE", "DEBATTE_FORTSETZEN",
    }
    _negative_evidence = [
        e for e in (fan_consensus.get("evidence") or [])
        if _evidence_marker(e).upper() in _negative_markers
    ]
    # D11/S-11.4: Herkunft der Kind-Ergebnisse am Parent wiederauffindbar.
    parent_task["fan_in_child_ids"] = [s["agent_id"] for s in fan_statements]
    parent_task["fan_in_statements"] = fan_statements

    _parts = [
        f"# Synthese: {parent_title}",
        "## Executive-Kurzfassung",
        f"{len(reports)} Arbeitspakete wurden deterministisch integriert; keine neuen Fakten "
        f"erfunden. Konsensstatus: {fan_consensus.get('verdict')} "
        f"({fan_consensus.get('yes_votes')}/{fan_consensus.get('total_votes')} explizite "
        f"Zustimmungen, erforderlich: {fan_consensus.get('required_votes')}).",
        "## Integriertes Ergebnis",
        combined_reports or "(keine Teilergebnisse vorhanden)",
        "## Widersprueche & offene Punkte",
    ]
    if _negative_evidence:
        _parts.extend(
            f"- {_evidence_agent(e)}: {_evidence_marker(e)}" for e in _negative_evidence[:10]
        )
    else:
        _parts.append(
            "- Keine expliziten Widerspruchs-Marker in den Teilergebnissen; "
            "implizite Luecken bleiben im Review zu pruefen."
        )
    _parts.extend([
        "## Naechste Schritte",
        (
            "Freigabe durch ROBERT (executive_decision_architect) einholen; bei Ablehnung "
            "Entwurf als Approval-Task im Board belassen."
            if _fan_final_ok else
            "Kein Konsens / Policy-Veto: KEINE Freigabe und keine finale Entscheidung. "
            "Konflikte und Guardrail-Befunde gehen an HITL zur Klaerung."
        ),
        _MARKER,
    ])
    synthesis_reply = "\n\n".join(_parts)

    # MARKER-KONTRAKT: letzte Zeile ist Protokoll, kein Inhalt — wird vor
    # Draft/Dossier/Robert entfernt (wie zuvor).
    _syn_lines = synthesis_reply.splitlines()
    if _syn_lines and _syn_lines[-1].strip().upper() == _MARKER:
        synthesis_reply = "\n".join(_syn_lines[:-1]).strip()

    # --- SCHRITT 1.5: KRITISCHER REVIEWER prüft die Fan-in-Synthese vor Roberts Entscheidung ---
    # H-15-5/F023: `gpts_critical_reviewer` existiert nicht unter den 71 Profilen.
    # SSOT ist `red_team_challenger`. Fehlt das Profil, darf die Kette NICHT
    # still zu Robert weiterlaufen (fail-closed: Eskalation statt Freigabe).
    _REVIEWER_ID = "red_team_challenger"
    reviewer_prof = next((p for p in profiles if p.get("id") == _REVIEWER_ID), None)
    if reviewer_prof is None:
        # Migrationspfad fuer alte Aufrufer, die noch den nie existierenden
        # Handle `gpts_critical_reviewer` uebergeben. Produktiv liefert
        # get_profiles() die echten 71 Profile — dort greift die SSOT-Kennung.
        _legacy = next((p for p in profiles if p.get("id") == "gpts_critical_reviewer"), None)
        if _legacy:
            logger.warning(
                "[Cascade-Loop] Legacy-Reviewer-Profil 'gpts_critical_reviewer' erkannt — "
                "verwende echte Rolle '%s' mit dem uebergebenen Profil.", _REVIEWER_ID
            )
            reviewer_prof = {**_legacy, "id": _REVIEWER_ID}
    reviewer_critique = ""
    reviewer_failed_closed = False
    if not reviewer_prof:
        logger.error(
            "[Cascade-Loop] Pflicht-Reviewer '%s' fehlt in der Rollen-SSOT — "
            "fail-closed: kein Finalisierungs-Gate, Eskalation an HITL.", _REVIEWER_ID
        )
        reviewer_failed_closed = True
        ticker("Reviewer", f"Pflicht-Reviewer {_REVIEWER_ID} nicht verfuegbar — HITL-Eskalation")
    else:
        rev_prompt = f"""Fuehre eine schonungslose Qualitaetspruefung der vorliegenden Synthese durch.
PROJEKT: {parent_title}
URSPRUENGLICHE ANFORDERUNG: {parent_task.get('capture_input', parent_title)}

SYNTHESE-ENTWURF (deterministische Fan-in-Synthese):
{synthesis_reply}

AUFGABE:
1. Pruefe auf unbelegte Behauptungen, Logikbrueche und gravierende Luecken.
2. Formuliere max. 3 praegnante Kernkritikpunkte (oder bestaetige 'Keine kritischen Maengel festgestellt').
3. Schliesse mit einem klaren Urteil: EMPFEHLUNG FREIGABE oder EMPFEHLUNG NACHBESSERUNG."""
        ticker("Reviewer", f"Qualitaetspruefung fuer '{parent_title[:30]}...'")
        try:
            rev_res = await dispatcher.dispatch_to_omniroute_or_container(
                agent_id=_REVIEWER_ID,
                agent_name=(reviewer_prof.get("name") or reviewer_prof.get("person_name") or "Red Team Challenger"),
                prompt=rev_prompt,
                role="Critical Reviewer & QA",
                system_prompt=((reviewer_prof or {}).get("system_prompt") or "Du bist der kritische Chef-Reviewer von Archon OS. Pruefe Entwuerfe schonungslos auf Fakten, Logik und Qualitaet."),
                model=((reviewer_prof or {}).get("model") or "deepseek/deepseek-v4-flash-0731"),
            )
            reviewer_critique = (rev_res.get("content", "") or "").strip()
            if reviewer_critique:
                logger.info(f"[Cascade-Loop] Reviewer-Kritik erstellt ({len(reviewer_critique)} Zeichen)")
            else:
                reviewer_failed_closed = True
                logger.error("[Cascade-Loop] Reviewer lieferte keine Kritik — fail-closed.")
        except Exception as rev_err:
            reviewer_failed_closed = True
            logger.error(f"[Cascade-Loop] Reviewer-Pruefung fehlgeschlagen (fail-closed): {rev_err}")

    # --- SCHRITT 2: ROBERT gibt frei ---
    robert_prompt = f"""Die deterministische Fan-in-Synthese hat die Teilergebnisse folgenden Projekts zusammengefuegt:

PROJEKT: {parent_title}
ANFORDERUNG: {parent_task.get('capture_input', parent_title)}

DETERMINISTISCHE FAN-IN-SYNTHESE:
{synthesis_reply}

""" + (f"""UNABHAENGIGE QUALITAETSPRUEFUNG (Kritischer Reviewer):
{reviewer_critique}

""" if reviewer_critique else "") + """Pruefe Vollstaendigkeit und Plausibilitaet. Antworte MIT GENAU EINEM DER ZWEI
WOERTER ALS ALLERERSTER ZEILE: FREIGABE oder ABLEHNUNG - danach hoechstens
ein Satz Begruendung. Keine weiteren Absaetze, keine Begruessung."""
    r_prof = next((p for p in profiles if p.get("id") in ("executive_decision_architect", "robert")), None)
    r_system = ((r_prof or {}).get("system_prompt") or (r_prof or {}).get("prompt")
                or "Du bist Robert, Executive Decision Architect und leitender Chefstratege von Archon OS. Antworte mit FREIGABE oder ABLEHNUNG als erste Zeile.")
    r_model = (r_prof or {}).get("model") or "deepseek/deepseek-v4-flash-0731"
    robert_reply = ""
    if _fan_policy_veto or reviewer_failed_closed:
        # B7/HIGH + H-15-5: Policy-Veto oder fehlgeschlagener Pflicht-Reviewer
        # ist eine HARTE Ablehnung. Kein Freigabe-Prompt, keine Finalisierung —
        # nur HITL mit Belegen.
        ticker("Robert", "Policy-Veto/Reviewer-Fehler im Fan-in — Freigabe gesperrt, HITL erforderlich")
        logger.warning(
            "[Cascade-Loop] Fan-in gesperrt (verdict=%s, reviewer_failed_closed=%s): "
            "Robert-Freigabe wird nicht angefragt.", _fan_verdict, reviewer_failed_closed,
        )
    else:
        ticker("Robert", f"Prueft Fan-in-Synthese fuer '{parent_title[:30]}...'")
        try:
            rres = await dispatcher.dispatch_to_omniroute_or_container(
                agent_id="executive_decision_architect",
                agent_name="Robert (Chefstratege)",
                prompt=robert_prompt,
                role="Executive Decision Architect",
                system_prompt=r_system,
                model=r_model,
            )
            robert_reply = (rres.get("content", "") or "").strip()
        except Exception as r_err:
            logger.warning(f"[Cascade-Loop] Freigabe-Dispatch an Robert fehlgeschlagen: {r_err}")

    # ROBUSTE FREIGABE-ERKENNUNG (Struktur-Thema 4/1, User-Entscheidung): NUR die
    # exakte erste Zeile zaehlt. Alles andere (Floskeln, "KEINE FREIGABE", leer)
    # geht an den Owner via Kanban-Entscheidung (4b-Pfad) - nie still, nie geraten.
    _erste_zeile = ((robert_reply or "").splitlines() or [""])[0].strip().upper()
    if _erste_zeile == "FREIGABE":
        freigegeben = True
    elif _erste_zeile == "ABLEHNUNG":
        freigegeben = False
    else:
        logger.warning(f"[Cascade-Loop] Roberts Antwort unklar (erste Zeile: '{_erste_zeile[:60]}') - Owner entscheidet")
        ticker("Robert", "Antwort unklar - Freigabe liegt beim Owner im Kanban")
        freigegeben = False

    # Entwurf ablegen (Basis der Robert-Freigabe)
    safe_pid = re.sub(r'[^a-zA-Z0-9_\-]+', '-', parent_project_id).strip('-') or "projekt"
    draft_name = f"{safe_pid}_synthese_lisa_entwurf.md"
    target_dirs = [
        PROJEKTE_DIR,
        os.path.join(paths["OBSIDIAN_VAULT_DIR"], "01_PROJEKTE"),
        os.path.join(paths["WORKSPACE_DIR"], "obsidian_vault", "01_PROJEKTE"),
    ]
    # 12.10.2026 (Ordnerflut-Fix): Entwurf + finaler Bericht gehoeren in den
    # EINEN Projekt-Ordner des Eltern-Projekts, nicht als lose Dateien daneben.
    try:
        _fan_ordner = folder_namer({"parent_project_id": parent_project_id, "parent_project_title": parent_title})
    except Exception as exc:
        # D01-M7: kein stiller Fallback auf einen leeren Zielordner.
        raise RuntimeError(
            "Projektordner nicht bestimmbar — Synthese abgebrochen (D01-M7)"
        ) from exc
    # 2a: Ablageordner fuer das Synthese-Dossier im Projektordner
    _tg_doss_dir = None
    try:
        if _fan_ordner:
            _tg_doss_dir = os.path.join(paths["OBSIDIAN_VAULT_DIR"], "01_PROJEKTE",
                                        _fan_ordner, "01_Zwischenberichte")
    except Exception:
        _tg_doss_dir = None
    draft_path = (os.path.join(PROJEKTE_DIR, _fan_ordner, "03_Endprodukte", draft_name)
                  if _fan_ordner else os.path.join(PROJEKTE_DIR, draft_name))
    critique_section = (
        f"\n\n---\n\n## Unabhängige Qualitätsprüfung (Kritischer Reviewer)\n\n{reviewer_critique}\n"
        if reviewer_critique else ""
    )
    import hashlib
    draft_content = f"# Synthese-Entwurf: {parent_title}\n\n{synthesis_reply}{critique_section}"
    draft_sha256 = hashlib.sha256(draft_content.encode("utf-8")).hexdigest()
    written_draft_paths: List[str] = []
    draft_write_errors: List[str] = []
    for d in target_dirs:
        try:
            d_ziel = os.path.join(d, _fan_ordner, "03_Endprodukte") if _fan_ordner else d
            os.makedirs(d_ziel, exist_ok=True)
            p = os.path.join(d_ziel, draft_name)
            if os.path.commonpath([os.path.abspath(p), os.path.abspath(d_ziel)]) != os.path.abspath(d_ziel):
                raise ValueError(f"Ziel ausserhalb des erlaubten Verzeichnisses: {p}")
            tmp_p = os.path.join(d_ziel, f".{draft_name}.tmp_{os.getpid()}_{int(time.time() * 1000)}")
            with open(tmp_p, "w", encoding="utf-8") as f:
                f.write(draft_content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_p, p)
            if not (os.path.isfile(p) and os.path.getsize(p) > 0):
                raise IOError(f"Atomare Verifikation fehlgeschlagen (leer/fehlt): {p}")
            written_draft_paths.append(p)
            draft_path = p
        except Exception as write_exc:
            draft_write_errors.append(f"{d}: {write_exc}")
            logger.error("[Synthesis] Atomares Schreiben des Entwurfs nach %s fehlgeschlagen: %s", d, write_exc)
    if not written_draft_paths:
        raise RuntimeError(
            f"blocked: synthesis_draft_write_failed ({'; '.join(draft_write_errors) or 'no target_dirs'})"
        )
    # Hash-Manifest atomar neben dem zuletzt geschriebenen Entwurf ablegen (F13)
    try:
        m_path = draft_path + ".sync_manifest.json"
        m_tmp = m_path + f".tmp_{os.getpid()}"
        manifest = {
            "task_id": parent_project_id,
            "authoritative": draft_path,
            "content_sha256": draft_sha256,
            "replicas": written_draft_paths[:-1],
            "status": "partial" if draft_write_errors else "ok",
            "errors": draft_write_errors,
        }
        with open(m_tmp, "w", encoding="utf-8") as mf:
            json.dump(manifest, mf, indent=2, ensure_ascii=False)
            mf.flush()
            os.fsync(mf.fileno())
        os.replace(m_tmp, m_path)
    except Exception as m_exc:
        logger.warning("[Synthesis] Hash-Manifest konnte nicht geschrieben werden: %s", m_exc)

    # --- ATOMARER COMMIT: synthesis_draft_path in Parent-Task schreiben ---
    # Wir nutzen update_mc für atomares Merge (nur Parent-Task Update, keine Tasks-Listen-Änderung)
    def _commit_draft():
        if update_mc is not None:
            update_mc(lambda fresh: _merge_synthesis_draft_delta(
                fresh, parent_project_id, draft_path,
                {"child_ids": parent_task.get("fan_in_child_ids", []),
                 "statements": parent_task.get("fan_in_statements", [])},
            ))
        else:
            raise RuntimeError(
                "_run_synthesis_cascade: Parameter 'update_mc' fehlt. "
                "main.py injiziert update_mission_control_data; Aufrufer muessen die "
                "Abhaengigkeit explizit uebergeben."
            )
    _commit_draft()

    # B7: harter Gate — kein NO_CONSENSUS*-Verdict (inkl. Policy-Veto) darf
    # unabhängig von Roberts Antwort eine finale Beschlussvorlage erzeugen.
    if freigegeben and _fan_final_ok and not reviewer_failed_closed:
        await finalize_approval(
            parent_project_id, draft_path, synthesis_reply,
            "Robert: " + mark_truncated(robert_reply, 200, artifact=draft_path),
        )
        # 2a: Owner informieren - kein Handlungsbedarf, aber Bericht mitliefern.
        tg_ping(parent_title, parent_project_id, synthesis_reply, draft_path, app_id=None, dossier_dir=_tg_doss_dir)
        return

    # 4b: Ablehnung/unklar -> echte Entscheidung im KANBAN (2c). kanban.db ist
    # die Wahrheit; der frühere parallele Mission-Control-Task (mcapp-*) entfällt.
    _deci_dossier = None
    if _tg_doss_dir and build_dossier:
        try:
            _deci_dossier = build_dossier(
                f"Synthese: {parent_title}", synthesis_reply, _tg_doss_dir,
                f"{safe_pid}_synthese", ref_id=parent_project_id,
                quelle="deterministic_fan_in")
        except Exception as _de:
            logger.warning(f"[Synthese] Dossier für die Entscheidung fehlgeschlagen: {_de}")
    _deci = None
    if create_decision:
        try:
            _deci = await asyncio.to_thread(
                create_decision,
                "synthesis_freigabe",
                f"Freigabe: Synthese '{parent_title[:55]}'",
                synthesis_reply,          # kurzfassung
                parent_project_id,        # ref_id
                _deci_dossier,            # dossier
                f"Entwurf der deterministischen Fan-in-Synthese: {draft_path}",   # body
                {"parent_project_id": parent_project_id, "draft_path": draft_path,
                 "projekt": parent_title, "von": "deterministic_fan_in",
                 "teilberichte": f"{len(reports)}/{len(reports)}",
                 # B7: HITL braucht die Konfliktbelege, sonst ist die Eskalation
                 # nicht nachvollziehbar (D14: original_verdict/veto_by/evidence).
                 **({} if _fan_final_ok else {
                     "original_verdict": _fan_verdict,
                     "veto_by": (fan_consensus or {}).get("veto_by"),
                     "policy_violation": _fan_policy_veto,
                     "evidence": [
                         {"agent_id": str(getattr(e, "agent_id", "")),
                          "marker": str(getattr(e, "marker", ""))}
                         for e in ((fan_consensus or {}).get("evidence") or [])
                     ],
                 })},                                                                # extra
                (f"01_PROJEKTE/{_fan_ordner}" if _fan_ordner else None),             # obsidian
            )
        except Exception as _de:
            logger.warning(f"[Synthese] Entscheidung anlegen fehlgeschlagen: {_de}")
    now_t = datetime.datetime.now().strftime("%H:%M:%S")

    # --- ATOMARER COMMIT: audit_logs Eintrag hinzufügen ---
    def _commit_audit():
        if update_mc is not None:
            update_mc(lambda fresh: _merge_synthesis_audit_delta(fresh, parent_project_id, now_t, robert_reply, _deci, draft_name))
        else:
            raise RuntimeError(
                "_run_synthesis_cascade: Parameter 'update_mc' fehlt. "
                "main.py injiziert update_mission_control_data; Aufrufer muessen die "
                "Abhaengigkeit explizit uebergeben."
            )
    _commit_audit()

    ticker("Synthese-Loop", f"Entscheidung im Kanban angelegt: {draft_name}")
    if not _deci:
        logger.warning(f"[Synthese] Entscheidung für #{parent_project_id} konnte NICHT "
                       f"angelegt werden — Freigabe ist per Telegram/Kanban nicht möglich.")


def recover_stale_synthesis(
    load_mc: LoadMC,
    update_mc: Callable[[Callable[[Dict[str, Any]], None]], None],
    *,
    ttl_seconds: int = 900,
    restart: Optional[Callable[[str], Any]] = None,
) -> List[str]:
    """Setzt verwaiste ``synthesis_started``-Flags zurueck und startet neu.

    ``synthesis_started`` wurde vor dem Start der Cascade persistiert. Wurde
    der Task GC'd, das Modul neu geladen oder der Prozess beendet, blieb das
    Flag dauerhaft true und der Fan-In kehrte immer wieder frueh zurueck —
    das Projekt blieb stumm in "alle Ergebnisse da, keine Synthese".
    """
    data = load_mc() or {}
    stale: List[str] = []
    now = datetime.datetime.now()

    # H-02-2/F031: vor dem Deploy produzierte `cancelled`-Kinder haben den
    # Fan-in damals blockiert (Status fehlte in `terminal_states`), also wurde
    # `synthesis_started` NIE gesetzt — die klassische Recovery sah nichts.
    # Hier werden solche Projekte nachträglich erkannt und hart eskaliert.
    def _resolve_cancelled_children(fresh: Dict[str, Any]) -> None:
        tasks = fresh.get("tasks", []) or []
        for parent in tasks:
            if parent.get("synthesis_finalized") or parent.get("synthesis_started"):
                continue
            if str(parent.get("status") or "") in ("done", "completed", "blocked", "cancelled"):
                continue
            children = [
                t for t in tasks
                if t.get("id") != parent.get("id")
                and (t.get("parent_project_id") == parent.get("id")
                     or t.get("parent_task_id") == parent.get("id"))
            ]
            cancelled_ids = [
                str(c.get("id") or "?") for c in children
                if str(c.get("status") or "") == "cancelled"
            ]
            if not cancelled_ids:
                continue
            parent["status"] = "blocked"
            parent["phase"] = "blocked"
            parent["failure_reason"] = (
                f"Teilaufgabe abgebrochen: {', '.join(cancelled_ids)}. "
                "HITL-Eskalation erforderlich (Fan-in zuvor blockiert)."
            )
            parent["fan_in_escalation"] = "hitl_required"
            stale.append(str(parent.get("id") or parent.get("project_id") or "?"))
            logger.error(
                "[Fan-in] Recovery: Parent '%s' wegen abgebrochener Kinder blockiert: %s",
                parent.get("id"), cancelled_ids,
            )

    update_mc(_resolve_cancelled_children)
    data = load_mc() or {}  # frischer Snapshot nach der Mutierung

    for task in data.get("tasks", []) or []:
        if not task.get("synthesis_started") or task.get("synthesis_finalized"):
            continue
        raw = task.get("synthesis_started_at") or task.get("updated_at") or ""
        try:
            started = datetime.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if started.tzinfo is not None:
                started = started.replace(tzinfo=None)
        except (TypeError, ValueError):
            # Kein Zeitstempel (Legacy-Datensatz) -> als stale behandeln
            stale.append(str(task.get("id") or task.get("project_id") or "?"))
            continue
        if (now - started).total_seconds() > ttl_seconds:
            stale.append(str(task.get("id") or task.get("project_id") or "?"))

    if not stale:
        return []

    max_retries = 3
    restartable: List[str] = []

    def _reset(fresh: Dict[str, Any]) -> None:
        for t in fresh.get("tasks", []) or []:
            key = str(t.get("id") or t.get("project_id") or "?")
            if key in stale and t.get("synthesis_started") and not t.get("synthesis_finalized"):
                retries = int(t.get("synthesis_retry_count") or 0) + 1
                t["synthesis_retry_count"] = retries
                t["synthesis_started"] = False
                if retries >= max_retries:
                    # Nach 3 Fehlversuchen nicht endlos neu starten (LLM-Kosten,
                    # Audit-Spam) — eskalieren und HITL entscheiden lassen.
                    t["status"] = "blocked"
                    t["phase"] = "blocked"
                    t["failure_reason"] = f"Synthese nach {retries} Versuchen fehlgeschlagen — manuelle Pruefung erforderlich."
                    logger.error("[Fan-in] Synthese '%s' nach %s Versuchen blockiert.", key, retries)
                else:
                    restartable.append(key)

    update_mc(_reset)
    logger.warning("[Fan-in] %s verwaiste Synthese-Flag(s) zurueckgesetzt: %s", len(stale), stale)
    # KRITISCH: frueher wurde nur das Flag geloescht, aber keine neue
    # Synthese gestartet — das Projekt blieb genau im Zustand haengen, den
    # die Recovery verhindern sollte. Fan-in nach dem Reset erneut triggern.
    if restart is not None:
        for pid in restartable:
            try:
                restart(pid)
            except Exception as exc:
                logger.warning("[Fan-in] Restart von '%s' fehlgeschlagen: %s", pid, exc)
    return stale


__all__ = [
    "recover_stale_synthesis",
    "_execute_mission_control_task",
    "_paperclip_hire_profile_by_id",
    "_set_agent_profile_status",
    "_trigger_sandy_staffing_nomination",
    "_finalize_synthesis_after_approval",
    "_fan_in_maybe_start_synthesis",
    "_tg_ping_synthesis",
    "_run_synthesis_cascade",
]
