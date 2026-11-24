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

from archon.routers._rbac import require_admin_or_503
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

import core_dispatcher  # noqa: F401
from backend.cancellation import clear_scope, get_child_token
from archon.core.runtime import (  # noqa: F401
    WORKSPACE_DIR, MEMORY_DIR, DATA_DIR, SETTINGS_FILE, OBSIDIAN_VAULT_DIR, APP_ROOT,
    add_ticker, broadcast_event, ticker_entries, _load_json, _save_json, atomic_write_json,
    logger,
)

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
    chairman_id: Optional[str] = "orchestrator"
    chairman_provider: Optional[str] = "openrouter"
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
    frameworks = as_payload(frameworks)
    core_dispatcher.CATEGORIZED_FRAMEWORKS = frameworks
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
            import pypdf, io
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


def _prepare_boardroom_agents(req: BoardroomRequest):
    roles = _DEPS["load_roles"]()
    roles_map = {r["id"]: r for r in roles}
    try:
        hermes_profiles = _DEPS["api_get_hermes_profiles"]()
        for hp in hermes_profiles:
            pid = hp.get("id")
            if pid:
                roles_map[pid] = {
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

    # Chairman Profil (d14: nur bekannte/registrierte Chairman-Rollen zulassen)
    chairman_id = (req.chairman_id or "orchestrator").strip()
    if req.chairman_id and chairman_id not in roles_map and chairman_id != "orchestrator":
        try:
            from backend.role_budget_engine import EXECUTIVE_ROLE_IDS, LEAD_ROLE_IDS
            allowed_extra = EXECUTIVE_ROLE_IDS | LEAD_ROLE_IDS
        except Exception:
            allowed_extra = set()
        if chairman_id.lower() not in allowed_extra:
            raise HTTPException(
                status_code=400,
                detail=f"Unbekannte oder nicht autorisierte Chairman-Rolle: '{chairman_id}'",
            )
    chairman_prof = roles_map.get(chairman_id, {
        "id": chairman_id,
        "name": "Orchestrator & System-Architekt",
        "role": "Moderator & Chairman",
        "prompt": "Du bist der Moderator und Chairman des AI Boardrooms.",
        "model": "deepseek/deepseek-chat",
        "provider": "openrouter",
        "reasoning_level": "medium"
    })
    
    chairman_chosen_model = (req.chairman_model or "").strip() or chairman_prof.get("model") or "deepseek/deepseek-chat"
    chairman_chosen_provider = (req.chairman_provider or "").strip() or chairman_prof.get("provider") or "openrouter"

    chairman_agent = {
        "id": chairman_prof["id"],
        "name": chairman_prof.get("name", "Chairman"),
        "role": "Moderator & Chairman",
        "prompt": chairman_prof.get("prompt", ""),
        "model": chairman_chosen_model,
        "provider": chairman_chosen_provider,
        "reasoning_level": _resolve_reasoning(chairman_prof),
        "active": True
    }
    
    # Participant Slots
    participant_agents = []
    if req.slots and len(req.slots) > 0:
        for idx, s in enumerate(req.slots):
            p_id = s.profile_id or "senior_coder"
            r_name = s.role_name or f"Experte {idx+1}"
            prof = roles_map.get(p_id, {})
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
                "active": True
            })
    else:
        # Standard-Fallback aus Rollen
        for r in roles[1:4]:
            prof = roles_map.get(r["id"], r)
            participant_agents.append({
                "id": r["id"],
                "name": prof.get("name", r["name"]),
                "role": prof.get("role", r.get("name", "Experte")),
                "prompt": prof.get("prompt", r.get("prompt", "")),
                "model": prof.get("model") or "deepseek/deepseek-chat",
                "provider": prof.get("provider") or "openrouter",
                "reasoning_level": _resolve_reasoning(prof),
                "active": True
            })
            
    all_debate_agents = [chairman_agent] + participant_agents
    return chairman_agent, all_debate_agents


@router.post("/api/boardroom/run")
async def api_run_boardroom(req: BoardroomRequest, request: Request = None):
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
        moa_reference_models=req.moa_reference_models,
        moa_aggregator=req.moa_aggregator
    )
    
    # Speichere finales Protokoll im Obsidian Vault
    try:
        vault_dir = OBSIDIAN_VAULT_DIR
        os.makedirs(vault_dir, exist_ok=True)
        ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        vault_file = os.path.join(vault_dir, f"boardroom_debatte_{ts_str}.md")
        
        md_content = f"# AI Boardroom Debatte: {req.task}\n\n"
        md_content += f"**Datum:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        md_content += f"**Methodik-Framework:** {req.framework}\n"
        md_content += f"**Chairman:** {res.get('chairman', {}).get('name', 'Unbekannt')}\n"
        md_content += f"**Max Runden:** {req.rounds}\n\n"
        md_content += f"## Diskussionsprotokoll\n\n{res.get('transcript', '')}\n\n"
        md_content += f"## Finale Synthese\n\n{res.get('synthesis', '')}\n"
        
        def _write_vault_note(path: str, text: str) -> None:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        await asyncio.to_thread(_write_vault_note, vault_file, md_content)
        add_ticker("AI Boardroom", f"Protokoll im Vault gespeichert: boardroom_debatte_{ts_str}.md")

        # Speichere strukturierten Eintrag in boardroom_history
        try:
            _consensus_status = str(res.get("consensus_status") or "").strip().upper()
            _debate_status = str(res.get("status") or "").strip().lower()
            _is_final_decision = (
                _consensus_status != "NO_CONSENSUS"
                and _debate_status not in ("cancelled", "canceled", "error", "aborted")
                and not bool(res.get("cancelled"))
            )
            hist_entry = {
                "id": f"deb_{int(time.time())}_{uuid.uuid4().hex[:6]}",
                "timestamp": datetime.datetime.now().isoformat(),
                "date_display": datetime.datetime.now().strftime("%d.%m.%Y · %H:%M Uhr"),
                "task": req.task,
                "framework": req.framework,
                "chairman": chairman_agent.get("name", "Moderator"),
                "use_moa": req.use_moa,
                "rounds": req.rounds,
                "decision_status": "approved" if _is_final_decision else (_consensus_status.lower() or _debate_status or "no_consensus"),
                "slots_count": max(0, len(all_debate_agents) - 1),
                "slots": [
                    {"name": a.get("name", ""), "role": a.get("role", ""), "model": a.get("model", "")}
                    for a in all_debate_agents[1:]
                ],
                "transcript": res.get("transcript", ""),
                "synthesis": res.get("synthesis", ""),
                "vault_file": f"boardroom_debatte_{ts_str}.md"
            }
            from archon.routers._rbac import get_session_actor
            hist_entry["_actor_id"] = get_session_actor(request, fallback="boardroom-service")
            save_boardroom_history_item(hist_entry)
            res["history_id"] = hist_entry["id"]
            if _is_final_decision:
                try:
                    from backend.workflow_scheduler import dispatch_workflow_event
                    dispatch_workflow_event(
                        source="boardroom",
                        event_type="decision",
                        title=req.task[:140],
                        summary=str(res.get("synthesis", ""))[:600],
                        payload={"framework": req.framework, "history_id": hist_entry["id"]},
                        correlation_id=hist_entry["id"],
                    )
                except Exception as wf_err:
                    print(f"[Boardroom] Workflow-Event notice: {wf_err}")
            else:
                logger.info(
                    "[Boardroom] Debatte %s ohne finalen Konsens (%s) — kein Decision-Workflow-Event ausgeloest.",
                    hist_entry["id"], hist_entry["decision_status"],
                )
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
                moa_reference_models=req.moa_reference_models,
                moa_aggregator=req.moa_aggregator,
                cancel_token=cancel_token,
            ):
                cancel_token.check()
                if await request.is_disconnected():
                    print("[AI Boardroom] Client disconnected. Beende Debatten-Stream vorzeitig.")
                    cancel_token.cancel("client_disconnect")
                    break
                if ev.get("type") == "done":
                    running_transcript = ev.get("transcript", "")
                    synthesis_text = ev.get("synthesis", "")
                    vault_file_name = ""
                    # Save to Obsidian Vault
                    try:
                        vault_dir = OBSIDIAN_VAULT_DIR
                        os.makedirs(vault_dir, exist_ok=True)
                        ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                        vault_file_name = f"boardroom_debatte_{ts_str}.md"
                        vault_file = os.path.join(vault_dir, vault_file_name)

                        md_content = f"# AI Boardroom Debatte: {req.task}\n\n"
                        md_content += f"**Datum:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                        md_content += f"**Methodik-Framework:** {req.framework}\n"
                        md_content += f"**Chairman:** {chairman_agent.get('name', 'Unbekannt')}\n"
                        md_content += f"**Max Runden:** {req.rounds}\n\n"
                        md_content += f"## Diskussionsprotokoll\n\n{running_transcript}\n\n"
                        md_content += f"## Finale Synthese\n\n{synthesis_text}\n"

                        def _write_vault_note_stream(path: str, text: str) -> None:
                            with open(path, "w", encoding="utf-8") as f:
                                f.write(text)
                        await asyncio.to_thread(_write_vault_note_stream, vault_file, md_content)
                        add_ticker("AI Boardroom", f"Protokoll im Vault gespeichert: {vault_file_name}")
                        ev["vault_file"] = vault_file_name
                    except Exception as e:
                        print(f"Error saving obsidian vault note: {e}")

                    # Save structured debate entry to boardroom history
                    try:
                        hist_entry = {
                            "id": f"deb_{int(time.time())}_{uuid.uuid4().hex[:6]}",
                            "timestamp": datetime.datetime.now().isoformat(),
                            "date_display": datetime.datetime.now().strftime("%d.%m.%Y · %H:%M Uhr"),
                            "task": req.task,
                            "framework": req.framework,
                            "chairman": chairman_agent.get("name", "Moderator"),
                            "use_moa": req.use_moa,
                            "rounds": req.rounds,
                            "slots_count": max(0, len(all_debate_agents) - 1),
                            "slots": [
                                {"name": a.get("name", ""), "role": a.get("role", ""), "model": a.get("model", "")}
                                for a in all_debate_agents[1:]
                            ],
                            "transcript": running_transcript,
                            "synthesis": synthesis_text,
                            "vault_file": vault_file_name
                        }
                        from archon.routers._rbac import get_session_actor
                        hist_entry["_actor_id"] = get_session_actor(request, fallback="boardroom-service")
                        save_boardroom_history_item(hist_entry)
                        ev["history_id"] = hist_entry["id"]
                    except Exception as e:
                        print(f"Error saving boardroom history item: {e}")

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
