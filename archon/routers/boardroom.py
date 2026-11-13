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
from pydantic import BaseModel

import core_dispatcher  # noqa: F401
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
    rounds: int = 2
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


def save_boardroom_history_item(item: dict):
    hist = load_boardroom_history()
    hist.insert(0, item)
    if len(hist) > 100:
        hist = hist[:100]
    _save_json(BOARDROOM_HISTORY_FILE, hist)
    return hist


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
def api_delete_boardroom_history_item(item_id: str):
    hist = load_boardroom_history()
    hist = [h for h in hist if h.get("id") != item_id]
    _save_json(BOARDROOM_HISTORY_FILE, hist)
    return {"status": "success"}


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
def api_save_boardroom_frameworks(request: Request, frameworks: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    core_dispatcher.CATEGORIZED_FRAMEWORKS = frameworks
    _save_json(FRAMEWORKS_FILE, frameworks)
    return {"status": "success"}


@router.post("/api/boardroom/frameworks/reset")
def api_reset_boardroom_frameworks(request: Request):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    if os.path.exists(FRAMEWORKS_FILE):
        try:
            os.remove(FRAMEWORKS_FILE)
        except Exception:
            pass
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
    except Exception:
        pass
    
    override_reasoning = (req.reasoning_level or "profile").strip().lower()

    def _resolve_reasoning(prof_dict: dict) -> str:
        if override_reasoning and override_reasoning != "profile":
            return override_reasoning
        return prof_dict.get("reasoning_level") or "medium"

    # Chairman Profil
    chairman_id = req.chairman_id or "orchestrator"
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
async def api_run_boardroom(req: BoardroomRequest):
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
                "transcript": res.get("transcript", ""),
                "synthesis": res.get("synthesis", ""),
                "vault_file": f"boardroom_debatte_{ts_str}.md"
            }
            save_boardroom_history_item(hist_entry)
            res["history_id"] = hist_entry["id"]
        except Exception as e:
            print(f"Error saving boardroom history item in run: {e}")
    except Exception as e:
        print(f"Error saving obsidian vault note: {e}")
        
    return res


@router.post("/api/boardroom/stream")
async def api_stream_boardroom(req: BoardroomRequest, request: Request):
    chairman_agent, all_debate_agents = _prepare_boardroom_agents(req)
    add_ticker("AI Boardroom", f"Live-Debatte gestartet: '{req.task[:40]}...' ({req.framework}) mit {len(all_debate_agents)} Teilnehmern")

    async def sse_generator():
        running_transcript = ""
        synthesis_text = ""
        async for ev in core_dispatcher.stream_boardroom_debate(
            task=req.task,
            max_rounds=req.rounds,
            chairman_id=chairman_agent["id"],
            active_agents=all_debate_agents,
            framework=req.framework,
            use_moa=req.use_moa,
            moa_reference_models=req.moa_reference_models,
            moa_aggregator=req.moa_aggregator
        ):
            if await request.is_disconnected():
                print("[AI Boardroom] Client disconnected. Beende Debatten-Stream vorzeitig.")
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
                    save_boardroom_history_item(hist_entry)
                    ev["history_id"] = hist_entry["id"]
                except Exception as e:
                    print(f"Error saving boardroom history item: {e}")

            payload = json.dumps(ev, ensure_ascii=False)
            yield f"data: {payload}\n\n"

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
