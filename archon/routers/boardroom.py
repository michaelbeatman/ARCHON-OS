from fastapi import Depends as _ArchonDepends

from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes

"""Router /api/boardroom — ausgelagerte Routen (Modularisierung main.py -> archon/routers)."""

import asyncio
import datetime
import json
import os
import re
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, cast

import httpx
import yaml
from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

import core_dispatcher  # noqa: F401
from archon.core.runtime import (  # noqa: F401
    APP_ROOT,
    DATA_DIR,
    MEMORY_DIR,
    OBSIDIAN_VAULT_DIR,
    SETTINGS_FILE,
    WORKSPACE_DIR,
    _load_json,
    _save_json,
    add_ticker,
    atomic_write_json,
    broadcast_event,
    logger,
    ticker_entries,
)
from archon.routers._rbac import require_admin_or_503
from backend.cancellation import clear_scope, get_child_token

# --------------------------------------------------
# Dependency-Injektion statt Kopie
# --------------------------------------------------
# load_boardroom_frameworks, load_roles, api_get_hermes_profiles
# werden aus main.py per configure() injiziert
_DEPS: Dict[str, Any] = {}

def configure(**deps: Any) -> None:
    """Registriert die aus main.py injizierten Abhängigkeiten (einmalig beim Import)."""
    _DEPS.update(deps)
    _missing = {"load_boardroom_frameworks", "load_roles", "api_get_hermes_profiles"} - set(_DEPS)
    if _missing:
        logger.warning(f"[Router] boardroom: fehlende Dependencies {sorted(_missing)}")

from copy import deepcopy as _deepcopy

from archon.routers._validated_body import PassthroughBody, as_payload

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])


BOARDROOM_HISTORY_FILE = os.path.join(WORKSPACE_DIR, "boardroom_history.json")

FRAMEWORKS_FILE = os.path.join(WORKSPACE_DIR, "frameworks.json")


class BoardroomSlotItem(BaseModel):
    role_name: str
    profile_id: str
    model_id: Optional[str] = None
    provider: Optional[str] = None


class BoardroomRequest(BaseModel):
    task: str
    # Audit 23.11.2026: ohne Obergrenze waren unbegrenzt kostenpflichtige
    # LLM-Runden moeglich (pro Runde N Agenten + optionales MoA).
    rounds: int = Field(default=2, ge=1, le=6)
    # D02/D14: Default muss in der tier-geprueften EXECUTIVE|LEAD-Menge liegen.
    # "orchestrator" ist in keiner Profilquelle registriert und darf nicht
    # lngueltig ein erfundenes Profil erzeugen.
    chairman_id: Optional[str] = "executive_decision_architect"
    # Deprecated: Body-Overrides sind NICHT autorisiert und werden ignoriert.
    chairman_provider: Optional[str] = None
    chairman_model: Optional[str] = None
    framework: str = "Steffi Kieffer Boardroom"
    slots: Optional[List[BoardroomSlotItem]] = None
    reasoning_level: Optional[str] = "profile"
    use_moa: bool = False
    moa_reference_models: Optional[List[dict]] = None
    moa_aggregator: Optional[dict] = None

def load_boardroom_history():
    hist = _load_json(BOARDROOM_HISTORY_FILE, None)
    # R-14: keinerlei erfundene Starter-Debatten mehr. Der GET erzeugt weder
    # Fiktion noch hat er einen Schreib-Seiteneffekt. Ein noch vorhandenes,
    # altes Sample-Artefakt wird beim ersten echten Speichern ueberschrieben.
    if hist is None:
        return []
    if not isinstance(hist, list):
        return []
    return hist


def _audit_boardroom(action: str, actor_id: str, payload: Dict[str, Any]) -> None:
    """K5: jede Historie-Änderung zusätzlich in die HMAC-Kette schreiben."""
    try:
        from backend.audit_log import chained_audit_log
        chained_audit_log.record_event("boardroom", action, actor_id or "system", payload)
    except Exception as exc:
        # Audit-Ausfall darf die Debatte nicht beschädigen, muss aber auffallen.
        logger.error("[Boardroom] Audit-Spiegelung fehlgeschlagen (%s): %s", action, exc)


def _boardroom_utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def save_boardroom_history_item(item: dict, actor_id: str = "system"):
    """K5: Historie ist revisionssicher gespiegelt, nicht mehr nur eine JSON-Datei.

    - Actor und Korrelations-ID kommen aus der verifizierten Session (siehe
      Call-Sites), nie aus dem JSON-Body.
    - UTC-Zeitstempel mit Offset (GoBD).
    - verdrängte Einträge (>100) werden vor dem Verwerfen in die Kette
      übernommen — keine stille Spurenlöschung mehr.
    """
    entry = dict(item)
    # Abwärtskompatibel: Actor kann im Dict liegen, damit bestehende
    # 1-Argument-Mocks/Call-Sites weiter funktionieren (kein neues Keyword).
    actor_id = str(entry.pop("_actor_id", "") or actor_id or "system")
    entry["actor_id"] = actor_id
    entry.setdefault("correlation_id", entry.get("id"))
    entry["timestamp"] = _boardroom_utc_now()
    hist = load_boardroom_history()
    hist.insert(0, entry)
    if len(hist) > 100:
        for old in hist[100:]:
            _audit_boardroom("decision_evicted", actor_id, {
                "id": old.get("id"), "timestamp": old.get("timestamp")})
        hist = hist[:100]
    # atomar statt "komplett neu schreiben" (D3): kein halber JSON-Stand.
    atomic_write_json(BOARDROOM_HISTORY_FILE, hist)
    _audit_boardroom("decision_saved", actor_id, {
        "id": entry.get("id"),
        "correlation_id": entry.get("correlation_id"),
        "task": str(entry.get("task", ""))[:500],
        "framework": entry.get("framework"),
        "timestamp": entry.get("timestamp"),
        "decision_status": entry.get("decision_status"),
        "consensus_verdict": entry.get("consensus_verdict"),
        "cancel_reason": entry.get("cancel_reason") or "",
        "cancel_scope": entry.get("cancel_scope") or "",
    })
    return hist


@router.post("/api/boardroom/cancel")
async def api_cancel_boardroom(request: Request):
    """Globaler Kill-Switch: bricht alle laufenden Boardroom-Debatten ab und
    setzt den Root-Scope zurueck, damit kuenftige Debatten nicht dauerhaft
    blockiert bleiben (d07)."""
    from archon.routers._rbac import require_admin_or_503
    require_admin_or_503(request)
    from backend.cancellation import cancel_and_reset_scope
    ok = cancel_and_reset_scope("boardroom", reason="global_kill_switch")
    return {"status": "success" if ok else "not_running", "cancelled": bool(ok)}


@router.get("/api/boardroom/history")
def api_get_boardroom_history():
    return load_boardroom_history()


@router.get("/api/boardroom/history/{item_id}")
def api_get_boardroom_history_item(item_id: str):
    hist = load_boardroom_history()
    for item in hist:
        if item.get("id") == item_id:
            return item
    raise HTTPException(status_code=404, detail="Debatte nicht gefunden")


@router.delete("/api/boardroom/history/{item_id}")
def api_delete_boardroom_history_item(request: Request, item_id: str):
    require_admin_or_503(request)
    from archon.routers._rbac import get_session_actor
    actor = get_session_actor(request, fallback="admin")
    hist = load_boardroom_history()
    found = False
    for h in hist:
        if h.get("id") != item_id:
            continue
        found = True
        # K5 / Zielkonflikt Z3: DSGVO-Recht auf Vergessen erfüllen, ohne die
        # GoBD-Kette zu beschädigen. Tombstone statt physischem Löschen.
        h["redacted"] = True
        h["redacted_at"] = _boardroom_utc_now()
        h["redacted_by"] = actor
        for key in ("task", "transcript", "synthesis", "slots", "vault_file"):
            h.pop(key, None)
    if not found:
        raise HTTPException(status_code=404, detail="Debatte nicht gefunden")
    atomic_write_json(BOARDROOM_HISTORY_FILE, hist)
    _audit_boardroom("decision_redacted", actor, {"id": item_id})
    return {"status": "success", "redacted": True}


def _resolve_boardroom_lang(lang: Optional[str] = None, request: Request = cast(Request, None)) -> str:
    if isinstance(lang, str) and lang.strip():
        return "en" if lang.strip().lower().startswith("en") else "de"
    if request is not None:
        st_lang = getattr(getattr(request, "state", None), "lang", None)
        if isinstance(st_lang, str) and st_lang.strip():
            return "en" if st_lang.strip().lower().startswith("en") else "de"
        acc = (request.headers.get("accept-language") or "").strip().lower()
        if acc:
            first_tag = acc.split(",")[0].split(";")[0].strip()
            if first_tag.startswith("en"):
                return "en"
            if first_tag.startswith("de"):
                return "de"
    env_lang = (os.environ.get("ARCHON_LANGUAGE") or "").strip().lower()
    return "en" if env_lang.startswith("en") else "de"


@router.get("/api/boardroom/frameworks")
def api_get_boardroom_frameworks(lang: Optional[str] = None, request: Request = cast(Request, None)):
    resolved_lang = _resolve_boardroom_lang(lang=lang, request=request)
    if resolved_lang == "en":
        return core_dispatcher.CATEGORIZED_FRAMEWORKS_EN
    if "load_boardroom_frameworks" in _DEPS:
        return _DEPS["load_boardroom_frameworks"]()
    return core_dispatcher.CATEGORIZED_FRAMEWORKS


@router.post("/api/boardroom/frameworks")
def api_save_boardroom_frameworks(request: Request, frameworks: PassthroughBody = Body(...)):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    frameworks = as_payload(frameworks)  # type: ignore[assignment]
    core_dispatcher.CATEGORIZED_FRAMEWORKS = frameworks  # type: ignore[assignment]
    _save_json(FRAMEWORKS_FILE, frameworks)
    return {"status": "success"}


@router.post("/api/boardroom/frameworks/reset")
def api_reset_boardroom_frameworks(request: Request):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    if os.path.exists(FRAMEWORKS_FILE):
        try:
            os.remove(FRAMEWORKS_FILE)
        except Exception as exc:
            logger.warning(f"Framework-Datei {FRAMEWORKS_FILE} konnte nicht geloescht werden: {exc}")
    core_dispatcher.CATEGORIZED_FRAMEWORKS = _deepcopy(core_dispatcher.DEFAULT_CATEGORIZED_FRAMEWORKS)
    core_dispatcher.CATEGORIZED_FRAMEWORKS_EN = _deepcopy(core_dispatcher.DEFAULT_CATEGORIZED_FRAMEWORKS_EN)
    _save_json(FRAMEWORKS_FILE, core_dispatcher.CATEGORIZED_FRAMEWORKS)
    return {"status": "success"}


@router.post("/api/boardroom/parse-attachment")
async def api_boardroom_parse_attachment(file: UploadFile = File(...)):
    filename = file.filename or "attachment"
    content = await file.read()
    extracted_text = ""
    lower_name = filename.lower()
    
    if lower_name.endswith(".pdf"):
        try:
            import io

            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(content))
            pages_text = []
            for i, page in enumerate(reader.pages[:25]):
                t = page.extract_text() or ""
                if t.strip():
                    pages_text.append(f"--- Seite {i+1} ---\n{t.strip()}")
            extracted_text = "\n\n".join(pages_text)
            if not extracted_text.strip():
                extracted_text = f"[Hinweis: Keine extrahierbare Textebene in PDF '{filename}' gefunden (z.B. gescanntes Dokument ohne OCR).]"
        except Exception as e:
            extracted_text = f"[Fehler beim Lesen der PDF-Datei '{filename}': {str(e)}]"
    else:
        try:
            extracted_text = content.decode("utf-8", errors="replace")
        except Exception as e:
            extracted_text = f"[Konnte Datei '{filename}' nicht als Text dekodieren: {str(e)}]"
            
    max_chars = 30000
    is_truncated = len(extracted_text) > max_chars
    final_text = extracted_text[:max_chars]
    if is_truncated:
        final_text += f"\n\n[... Inhalt nach {max_chars} Zeichen für Prompt-Budget gekürzt ...]"
        
    return {
        "filename": filename,
        "size": len(content),
        "text": final_text,
        "is_truncated": is_truncated
    }


# D14/MED (Re-Audit): eine textuelle Prompt-Directive allein verhindert nicht,
# dass ein nicht konformes Modell bei NO_CONSENSUS doch eine finale Entscheidung
# in Vault/History schreibt. Die folgenden Helfer pruefen das deterministisch.
_FINAL_DECISION_MARKERS = (
    "final actionable decision",
    "final decision",
    "finale entscheidung",
    "entscheidung getroffen",
    "### 3. final",
)


def _has_final_consensus(result: Dict[str, Any]) -> bool:
    """Nur ein explizites CONSENSUS_REACHED berechtigt zur finalen Synthese."""
    verdict = str(
        result.get("consensus_verdict") or result.get("consensus_status") or ""
    ).strip().upper()
    return verdict.startswith("CONSENSUS_REACHED")


def _conflict_analysis_synthesis(text: Any) -> str:
    """Entfernt Final-Decision-Abschnitte aus NO_CONSENSUS-Artefakten."""
    raw = str(text or "")
    kept: List[str] = []
    dropping = False
    for line in raw.splitlines():
        lowered = line.lower()
        if any(marker in lowered for marker in _FINAL_DECISION_MARKERS):
            dropping = True
            continue
        if dropping:
            # Eine neue Ueberschrift beendet den zu entfernenden Abschnitt.
            if re.match(r"^#{1,6}\s", line.strip()):
                dropping = False
            else:
                continue
        kept.append(line)
    cleaned = "\n".join(kept).strip()
    if not cleaned:
        return (
            "Keine finale Entscheidung — kein Konsens erreicht. "
            "Siehe Diskussionsprotokoll und HITL-Eskalation."
        )
    return cleaned


def _verified_tier(agent_id: str) -> str:
    """Tier aus der Rollen-SSOT, nie aus einem frei waehlbaren Body-Wert."""
    try:
        from backend.role_budget_engine import get_default_role_budget
        return str(get_default_role_budget(agent_id).get("tier") or "")
    except Exception as exc:
        logger.warning("[Boardroom] Tier-SSOT nicht verfuegbar (%s) — kein Tier-Gewicht.", exc)
        return ""


def _prepare_boardroom_agents(req: BoardroomRequest):
    roles = _DEPS["load_roles"]()
    # D14: case-normalisierte Map — Vergleich und Lookup nutzen exakt denselben
    # Key, damit "Lead" und "lead" nicht auseinanderfallen.
    roles_map = {str(r["id"]).strip().lower(): r for r in roles}
    try:
        hermes_profiles = _DEPS["api_get_hermes_profiles"]()
        for hp in hermes_profiles:
            pid = hp.get("id")
            if pid:
                roles_map[str(pid).strip().lower()] = {
                    "id": pid,
                    "name": hp.get("name", pid),
                    "role": hp.get("role", "Expert"),
                    "prompt": hp.get("system_prompt") or hp.get("prompt") or "",
                    "model": hp.get("model") or "deepseek/deepseek-chat",
                    "provider": hp.get("provider") or "openrouter",
                    "reasoning_level": hp.get("reasoning_level") or "medium"
                }
    except Exception as exc:
        logger.debug(f"Hot-Profile konnten nicht geladen werden, nutze Defaults: {exc}")
    
    override_reasoning = (req.reasoning_level or "profile").strip().lower()

    def _resolve_reasoning(prof_dict: dict) -> str:
        if override_reasoning and override_reasoning != "profile":
            return override_reasoning
        return prof_dict.get("reasoning_level") or "medium"

    # Chairman-Hoheit (D02/HIGH + D14/HIGH): NUR tier-gepruefte IDs,
    # unabhaengig davon, ob die ID in roles_map liegt. Ein Specialist darf
    # niemals Synthese-Hoheit erhalten — auch nicht als registriertes Profil.
    # Rueckwaertskompatibilitaet: der historische Default "orchestrator" war
    # in keiner Profilquelle registriert. Er wird auf die registrierte
    # EXECUTIVE-Rolle abgebildet und danach normal tier-geprueft — kein
    # erfundenes Fallback-Profil mehr.
    _CHAIRMAN_ALIASES = {"orchestrator": "executive_decision_architect"}
    requested_chairman = (req.chairman_id or "executive_decision_architect").strip().lower()
    chairman_id = _CHAIRMAN_ALIASES.get(requested_chairman, requested_chairman)
    try:
        from backend.role_budget_engine import EXECUTIVE_ROLE_IDS, LEAD_ROLE_IDS
        allowed_chairmen = {str(x).strip().lower() for x in (EXECUTIVE_ROLE_IDS | LEAD_ROLE_IDS)}
    except Exception as exc:
        logger.error("[Boardroom] Tier-SSOT nicht verfuegbar — Chairman abgelehnt: %s", exc)
        allowed_chairmen = set()
    if chairman_id not in allowed_chairmen:
        raise HTTPException(
            status_code=400,
            detail=f"Chairman-Rolle '{chairman_id}' ist nicht in EXECUTIVE|LEAD autorisiert.",
        )
    chairman_prof = roles_map.get(chairman_id)
    if not chairman_prof:
        raise HTTPException(
            status_code=400,
            detail=f"Chairman-Rolle '{chairman_id}' ist nicht als Profil registriert.",
        )

    # D02/D14: Provider/Model ausschliesslich aus dem tier-geprueften Profil —
    # Body-Overrides (req.chairman_model/-provider) werden bewusst ignoriert.
    chairman_chosen_model = str(chairman_prof.get("model") or "deepseek/deepseek-chat")
    chairman_chosen_provider = str(chairman_prof.get("provider") or "openrouter")

    chairman_agent = {
        "id": chairman_id,
        "name": chairman_prof.get("name", "Chairman"),
        "role": "Moderator & Chairman",
        "prompt": chairman_prof.get("prompt", ""),
        "model": chairman_chosen_model,
        "provider": chairman_chosen_provider,
        "reasoning_level": _resolve_reasoning(chairman_prof),
        "tier": _verified_tier(chairman_id),
        "active": True
    }
    
    # Participant Slots
    participant_agents = []
    if req.slots and len(req.slots) > 0:
        for idx, s in enumerate(req.slots):
            p_id = str(s.profile_id or "senior_coder").strip().lower()
            r_name = s.role_name or f"Experte {idx+1}"
            # D14/MED: unbekanntes Slot-Profil darf kein leeres Profil und damit
            # keine frei waehlbare Executive-ID mit Tier-Gewicht 3 erzeugen.
            prof = roles_map.get(p_id)
            if not prof:
                raise HTTPException(
                    status_code=400,
                    detail=f"Slot-Profil '{p_id}' ist nicht als registriertes Profil bekannt.",
                )
            chosen_model = (s.model_id or "").strip() or prof.get("model") or "deepseek/deepseek-chat"
            chosen_provider = (s.provider or "").strip() or prof.get("provider") or "openrouter"
            participant_agents.append({
                "id": p_id,
                "name": prof.get("name", p_id),
                "role": r_name,
                "prompt": prof.get("prompt", ""),
                "model": chosen_model,
                "provider": chosen_provider,
                "reasoning_level": _resolve_reasoning(prof),
                # Tier stammt aus der geprueften Rollen-SSOT, nicht aus dem Body.
                "tier": _verified_tier(p_id),
                "active": True
            })
    else:
        # Standard-Fallback aus Rollen
        for r in roles[1:4]:
            prof = roles_map.get(str(r["id"]).strip().lower(), r)
            participant_agents.append({
                "id": r["id"],
                "name": prof.get("name", r["name"]),
                "role": prof.get("role", r.get("name", "Experte")),
                "prompt": prof.get("prompt", r.get("prompt", "")),
                "model": prof.get("model") or "deepseek/deepseek-chat",
                "provider": prof.get("provider") or "openrouter",
                "reasoning_level": _resolve_reasoning(prof),
                "tier": _verified_tier(str(r["id"]).strip().lower()),
                "active": True
            })
            
    all_debate_agents = [chairman_agent] + participant_agents
    return chairman_agent, all_debate_agents


def _escalate_boardroom_no_consensus(
    *,
    task_id: str,
    task: str,
    consensus_status: str,
    res: Dict[str, Any],
    actor_id: str,
) -> Optional[Dict[str, Any]]:
    """D02/D14: NO_CONSENSUS ist ein HITL-Fall, KEINE finale Entscheidung.

    Der bevorzugte Typ ``boardroom_no_consensus`` wird zuerst versucht. Ist er
    in ``_DECISION_TYPEN`` (archon/core/constants.py — fremdes Territorium)
    noch nicht registriert, fallbacken wir auf den registrierten HITL-Gate-Typ
    und behalten den Grund explizit im Payload. Es entsteht auf jeden Fall ein
    sichtbarer Eskalations-Task — kein stilles return {}.
    """
    extra = {
        "reason_code": "boardroom_no_consensus",
        "consensus_status": consensus_status,
        "consensus_verdict": str(res.get("consensus_verdict") or consensus_status),
        "veto_by": res.get("veto_by"),
        "critique": str(res.get("critique") or "")[:1500],
        "synthesis": str(res.get("synthesis") or "")[:1500],
    }
    kurzfassung = (
        f"Boardroom ohne Konsens ({consensus_status}). "
        f"Keine finale Entscheidung — manuelles Review erforderlich."
    )
    try:
        from archon.routers.decisions import create_decision
        dec = create_decision(
            "boardroom_no_consensus",
            titel=f"[HITL] Boardroom-No-Consensus: {task[:110]}",
            kurzfassung=kurzfassung,
            ref_id=str(task_id or ""),
            extra=extra,
            created_by=actor_id or "boardroom-service",
        )
        if not dec:
            dec = create_decision(
                "workflow_hitl_gate",
                titel=f"[HITL] Boardroom-No-Consensus: {task[:110]}",
                kurzfassung=kurzfassung,
                ref_id=str(task_id or ""),
                extra=extra,
                created_by=actor_id or "boardroom-service",
            )
        if dec:
            _audit_boardroom("no_consensus_escalated", actor_id, {
                "consensus_status": consensus_status,
                "decision_id": dec.get("id"),
                "reason_code": "boardroom_no_consensus",
            })
        else:
            logger.error("[Boardroom] HITL-Eskalation fehlgeschlagen (kein Decision-Task angelegt).")
        return dec
    except Exception as exc:
        logger.error("[Boardroom] HITL-Eskalation fehlgeschlagen: %s", exc)
        return None


def _persist_boardroom_result_sync(
    hist_entry: Dict[str, Any],
    *,
    actor_id: str,
    task: str,
    framework: str,
    dispatch_workflow: bool,
    workflow_summary: str = "",
    consensus_status: str = "NO_CONSENSUS",
    escalate: bool = False,
    res: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """D08/H-08-5: komplette Persistenzkette im Worker-Thread.

    ``save_boardroom_history_item`` liest die Historie, schreibt sie atomar
    (mkstemp + json.dump + flush + fsync + os.replace + Verzeichnis-fsync) und
    spiegelt den Eintrag in die HMAC-Auditkette. ``dispatch_workflow_event``
    oeffnet SQLite und enqueued Telemetrie. Beides lief vorher direkt im
    ``async`` Endpoint bzw. SSE-Generator und blockierte genau den SSE-Bus,
    ueber den diese Debatte gestreamt wurde.
    """
    save_boardroom_history_item(hist_entry, actor_id=actor_id)
    result: Dict[str, Any] = {"history_id": str(hist_entry.get("id") or "")}

    if dispatch_workflow:
        try:
            from backend.workflow_scheduler import dispatch_workflow_event
            dispatch_workflow_event(
                source="boardroom",
                event_type="decision",
                title=str(task or "")[:140],
                summary=str(workflow_summary or "")[:600],
                payload={"framework": framework, "history_id": result["history_id"]},
                correlation_id=result["history_id"],
            )
            result["workflow_event"] = True
        except Exception as wf_err:
            logger.error("[Boardroom] Workflow-Event fehlgeschlagen: %s", wf_err)
            result["workflow_event"] = False

    if escalate:
        _esc = _escalate_boardroom_no_consensus(
            task_id=result["history_id"],
            task=str(task or ""),
            consensus_status=str(consensus_status or "NO_CONSENSUS"),
            res=dict(res or {}),
            actor_id=str(actor_id or "boardroom-service"),
        )
        result["escalation_id"] = str(_esc.get("id")) if isinstance(_esc, dict) else None
    return result


@router.post("/api/boardroom/run")
async def api_run_boardroom(req: BoardroomRequest, request: Request = None):  # type: ignore[assignment]
    if request is not None:
        require_admin_or_503(request)
    chairman_agent, all_debate_agents = _prepare_boardroom_agents(req)
    
    add_ticker("AI Boardroom", f"Debatte gestartet: '{req.task[:40]}...' ({req.framework}) mit {len(all_debate_agents)} Teilnehmern")
    
    res = await core_dispatcher.run_boardroom_debate(
        task=req.task,
        max_rounds=req.rounds,
        chairman_id=chairman_agent["id"],
        active_agents=all_debate_agents,
        framework=req.framework,
        use_moa=req.use_moa,
        moa_reference_models=req.moa_reference_models,  # type: ignore[arg-type]
        moa_aggregator=req.moa_aggregator  # type: ignore[arg-type]
    )

    # D14/MED: Konsens deterministisch aus dem Verdict ableiten und die
    # Synthese vor jeder Archivierung bereinigen. Eine Prompt-Directive allein
    # haelt ein nicht konformes Modell nicht von einer Final Decision ab.
    _consensus_status = str(
        res.get("consensus_verdict") or res.get("consensus_status") or ""
    ).strip().upper()
    _has_consensus = _has_final_consensus(res)
    if not _has_consensus:
        res["synthesis"] = _conflict_analysis_synthesis(res.get("synthesis", ""))

    # Speichere finales Protokoll im Obsidian Vault
    try:
        vault_dir = OBSIDIAN_VAULT_DIR
        ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        vault_file = os.path.join(vault_dir, f"boardroom_debatte_{ts_str}.md")
        
        md_content = f"# AI Boardroom Debatte: {req.task}\n\n"
        md_content += f"**Datum:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        md_content += f"**Methodik-Framework:** {req.framework}\n"
        md_content += f"**Chairman:** {res.get('chairman', {}).get('name', 'Unbekannt')}\n"
        md_content += f"**Max Runden:** {req.rounds}\n\n"
        md_content += f"## Diskussionsprotokoll\n\n{res.get('transcript', '')}\n\n"
        _vault_heading = "## Finale Synthese" if _has_consensus else "## Konfliktanalyse / keine Entscheidung"
        md_content += f"{_vault_heading}\n\n{res.get('synthesis', '')}\n"
        
        def _write_vault_note(path: str, text: str) -> None:
            # D08/H-08-5: Verzeichnis-Anlegen + open/fsync im selben Worker.
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        await asyncio.to_thread(_write_vault_note, vault_file, md_content)
        add_ticker("AI Boardroom", f"Protokoll im Vault gespeichert: boardroom_debatte_{ts_str}.md")

        # Speichere strukturierten Eintrag in boardroom_history
        try:
            _debate_status = str(res.get("status") or "").strip().lower()
            # D02/D14/BLOCKER: _consensus_status/_has_consensus wurden oben aus
            # dem Verdict berechnet. NO_CONSENSUS (inkl. Policy-Veto) darf nie
            # approved werden — auch nicht durch einen leeren Status.
            _is_final_decision = (
                _has_consensus
                and _debate_status not in ("cancelled", "canceled", "error", "aborted", "no_consensus")
                and not bool(res.get("cancelled"))
            )
            if _debate_status in ("cancelled", "canceled", "aborted"):
                # D02/HIGH: ein Abbruch ist ein eigener Terminalstatus und kein
                # „kein Konsens" — sonst ist er im Archiv nicht erkennbar.
                _decision_status = "cancelled"
            elif not _has_consensus:
                _decision_status = "no_consensus"
            elif _is_final_decision:
                _decision_status = "approved"
            else:
                _decision_status = _debate_status or "no_consensus"
            hist_entry = {
                "id": f"deb_{int(time.time())}_{uuid.uuid4().hex[:6]}",
                "timestamp": datetime.datetime.now().isoformat(),
                "date_display": datetime.datetime.now().strftime("%d.%m.%Y · %H:%M Uhr"),
                "task": req.task,
                "framework": req.framework,
                "chairman": chairman_agent.get("name", "Moderator"),
                "use_moa": req.use_moa,
                "rounds": req.rounds,
                "consensus_status": _consensus_status or "NO_CONSENSUS",
                "consensus_verdict": str(res.get("consensus_verdict") or _consensus_status or "NO_CONSENSUS"),
                "decision_status": _decision_status,
                "slots_count": max(0, len(all_debate_agents) - 1),
                "slots": [
                    {"name": a.get("name", ""), "role": a.get("role", ""), "model": a.get("model", "")}
                    for a in all_debate_agents[1:]
                ],
                "transcript": res.get("transcript", ""),
                "synthesis": res.get("synthesis", ""),
                "vault_file": f"boardroom_debatte_{ts_str}.md",
                # D02/HIGH: ein Abbruch bleibt als solcher erkennbar — die
                # Begruendung gehoert in History UND Audit-Kette, nicht nur
                # in ein Metadatenfeld des Dispatch-Ergebnisses.
                "cancel_reason": str(res.get("cancel_reason") or ""),
                "cancel_scope": str(res.get("cancel_scope") or "") if _debate_status == "cancelled" else "",
            }
            from archon.routers._rbac import get_session_actor
            hist_entry["_actor_id"] = get_session_actor(request, fallback="boardroom-service")
            # D08/H-08-5: Historie + HMAC-Audit + Workflow-Event + HITL-
            # Eskalation gebuendelt in einem Worker-Thread (ein SSE-Bus bleibt
            # responsiv, waehrend die JSON-Datei gefsynt wird).
            _persisted = await asyncio.to_thread(
                _persist_boardroom_result_sync, hist_entry,
                actor_id=str(hist_entry["_actor_id"]),
                task=req.task, framework=req.framework,
                dispatch_workflow=bool(_is_final_decision),
                workflow_summary=str(res.get("synthesis", "")),
                consensus_status=_consensus_status or "NO_CONSENSUS",
                escalate=not _is_final_decision,
                res=res,
            )
            res["history_id"] = _persisted["history_id"]
            if not _is_final_decision:
                res["no_consensus_escalation_id"] = _persisted.get("escalation_id")
        except Exception as e:
            print(f"Error saving boardroom history item in run: {e}")
    except Exception as e:
        print(f"Error saving obsidian vault note: {e}")
        
    return res


@router.post("/api/boardroom/stream")
async def api_stream_boardroom(req: BoardroomRequest, request: Request):
    require_admin_or_503(request)
    chairman_agent, all_debate_agents = _prepare_boardroom_agents(req)
    add_ticker("AI Boardroom", f"Live-Debatte gestartet: '{req.task[:40]}...' ({req.framework}) mit {len(all_debate_agents)} Teilnehmern")

    # Cancel-Token: Kind von 'boardroom' (Global-Kill-Switch) und pro Debatte
    # eindeutig. Ein Disconnect bricht die laufende Debatte im Dispatch ab,
    # nicht nur den SSE-Consumer.
    cancel_token = get_child_token("boardroom", f"boardroom:{uuid.uuid4().hex[:12]}")

    async def sse_generator():
        running_transcript = ""
        synthesis_text = ""
        # KRITISCH (Audit 23.11.2026): clear_scope() muss auch bei
        # Client-Disconnect / Exception laufen, sonst bleibt der Token in der
        # Registry und der Killswitch wirkt auf verwaiste Scopes.
        try:
            async for ev in core_dispatcher.stream_boardroom_debate(
                task=req.task,
                max_rounds=req.rounds,
                chairman_id=chairman_agent["id"],
                active_agents=all_debate_agents,
                framework=req.framework,
                use_moa=req.use_moa,
                moa_reference_models=req.moa_reference_models,  # type: ignore[arg-type]
                moa_aggregator=req.moa_aggregator,  # type: ignore[arg-type]
                cancel_token=cancel_token,
            ):
                cancel_token.check()
                if await request.is_disconnected():
                    print("[AI Boardroom] Client disconnected. Beende Debatten-Stream vorzeitig.")
                    cancel_token.cancel("client_disconnect")
                    break
                if ev.get("type") == "done":
                    running_transcript = ev.get("transcript", "")
                    _stream_verdict = str(
                        ev.get("consensus_verdict") or ev.get("consensus_status") or "NO_CONSENSUS"
                    ).upper()
                    synthesis_text = ev.get("synthesis", "")
                    # D14/MED: auch im Stream ist ein leerer/fehlgeschlagener
                    # Synthese-Text KEINE finale Entscheidung. Erst das
                    # konsistente Bündel aus Verdict + is_final_decision +
                    # nicht-leerem Text + nicht abgebrochenem Token darf
                    # decision_status="approved" und die Vault-Überschrift
                    # "Finale Synthese" erzeugen.
                    _stream_final = (
                        _stream_verdict.startswith("CONSENSUS_REACHED")
                        and bool(ev.get("is_final_decision"))
                        and bool(str(synthesis_text or "").strip())
                        and not cancel_token.cancelled
                        and not bool(ev.get("cancelled"))
                    )
                    if not _stream_final:
                        synthesis_text = _conflict_analysis_synthesis(synthesis_text)
                        ev["synthesis"] = synthesis_text
                    vault_file_name = ""
                    # Save to Obsidian Vault
                    try:
                        vault_dir = OBSIDIAN_VAULT_DIR
                        ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                        vault_file_name = f"boardroom_debatte_{ts_str}.md"
                        vault_file = os.path.join(vault_dir, vault_file_name)

                        md_content = f"# AI Boardroom Debatte: {req.task}\n\n"
                        md_content += f"**Datum:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                        md_content += f"**Methodik-Framework:** {req.framework}\n"
                        md_content += f"**Chairman:** {chairman_agent.get('name', 'Unbekannt')}\n"
                        md_content += f"**Max Runden:** {req.rounds}\n\n"
                        md_content += f"## Diskussionsprotokoll\n\n{running_transcript}\n\n"
                        _vault_heading = (
                            "## Finale Synthese" if _stream_final else "## Konfliktanalyse / keine Entscheidung"
                        )
                        md_content += f"{_vault_heading}\n\n{synthesis_text}\n"

                        def _write_vault_note_stream(path: str, text: str) -> None:
                            # D08/H-08-5: makedirs + open im selben Worker-Thread.
                            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                            with open(path, "w", encoding="utf-8") as f:
                                f.write(text)
                        await asyncio.to_thread(_write_vault_note_stream, vault_file, md_content)
                        add_ticker("AI Boardroom", f"Protokoll im Vault gespeichert: {vault_file_name}")
                        ev["vault_file"] = vault_file_name
                    except Exception as e:
                        print(f"Error saving obsidian vault note: {e}")

                    # Save structured debate entry to boardroom history
                    try:
                        # _stream_verdict/_stream_final bereits beim done-Event
                        # berechnet (siehe oben) — keine zweite, abweichende Lesart.
                        hist_entry = {
                            "id": f"deb_{int(time.time())}_{uuid.uuid4().hex[:6]}",
                            "timestamp": datetime.datetime.now().isoformat(),
                            "date_display": datetime.datetime.now().strftime("%d.%m.%Y · %H:%M Uhr"),
                            "task": req.task,
                            "framework": req.framework,
                            "chairman": chairman_agent.get("name", "Moderator"),
                            "use_moa": req.use_moa,
                            "rounds": req.rounds,
                            "consensus_status": _stream_verdict,
                            "consensus_verdict": _stream_verdict,
                            "decision_status": (
                                "approved" if _stream_final else
                                ("incomplete" if _stream_verdict.startswith("CONSENSUS_REACHED") else "no_consensus")
                            ),
                            "slots_count": max(0, len(all_debate_agents) - 1),
                            "slots": [
                                {"name": a.get("name", ""), "role": a.get("role", ""), "model": a.get("model", "")}
                                for a in all_debate_agents[1:]
                            ],
                            "transcript": running_transcript,
                            "synthesis": synthesis_text,
                            "vault_file": vault_file_name,
                            "cancel_reason": str(cancel_token.reason or "") if cancel_token.cancelled else "",
                            "cancel_scope": cancel_token.scope if cancel_token.cancelled else "",
                        }
                        from archon.routers._rbac import get_session_actor
                        hist_entry["_actor_id"] = get_session_actor(request, fallback="boardroom-service")
                        # D08/H-08-5: gleicher gebuendelter Worker wie im
                        # non-streaming Endpoint — der SSE-Heartbeat darf nicht
                        # auf den fsync der Historie-Datei warten.
                        _persisted = await asyncio.to_thread(
                            _persist_boardroom_result_sync, hist_entry,
                            actor_id=str(hist_entry["_actor_id"]),
                            task=req.task, framework=req.framework,
                            dispatch_workflow=False,
                            consensus_status=_stream_verdict,
                            escalate=not _stream_final,
                            res={"consensus_verdict": _stream_verdict,
                                 "veto_by": ev.get("veto_by"),
                                 "critique": ev.get("critique", ""),
                                 "synthesis": synthesis_text},
                        )
                        ev["history_id"] = _persisted["history_id"]
                        if not _stream_final:
                            ev["no_consensus_escalation_id"] = _persisted.get("escalation_id")
                    except Exception as e:
                        logger.error("[Boardroom] History-Eintrag fehlgeschlagen: %s", e)

                payload = json.dumps(ev, ensure_ascii=False)
                yield f"data: {payload}\n\n"
        finally:
            cancel_token.cancel("stream_finished")
            clear_scope(cancel_token.scope)

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
