"""Router /api/boardroom — ausgelagerte Routen (Modularisierung main.py -> archon/routers)."""

import asyncio
import datetime
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

import httpx
import yaml
from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Request, UploadFile
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

router = APIRouter()


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
    if hist is None:
        # Initial starter entries so the overview looks alive immediately
        hist = [
            {
                "id": "deb_sample_001",
                "timestamp": "2026-10-26T21:30:00",
                "date_display": "26.10.2026 · 21:30 Uhr",
                "task": "Sollten wir unsere Microservices-Architektur konsolidieren und kostenfreie OmniRoute-Modelle als zentrales Gateway nutzen?",
                "framework": "Steffi Kieffer Boardroom",
                "chairman": "Michael Keller (Orchestrator)",
                "rounds": 2,
                "slots_count": 3,
                "slots": [
                    {"name": "Skeptiker & Risikoprüfer", "role": "Haftungs- & Risikoanalyse", "model": "deepseek/deepseek-r1"},
                    {"name": "Innovator & Stratege", "role": "Strategische Entscheidungen", "model": "anthropic/claude-3.7-sonnet"},
                    {"name": "Pragmatiker & Implementierer", "role": "Enterprise Solutions", "model": "deepseek/deepseek-chat"}
                ],
                "transcript": "Michael Keller (Moderator): Debatte eröffnet. Fragestellung: Konsolidierung der Microservices und Nutzung von OmniRoute als zentrales Gateway.\n\nSkeptiker (Haftungs- & Risikoanalyse): Aus Ausfallsicherheits- und SLA-Sicht birgt ein zentrales Gateway ein Single-Point-of-Failure-Risiko, sofern kein lokales Fallback auf Ollama oder direkte API-Keys hinterlegt ist.\n\nInnovator (Strategie): Wirtschaftlich sparen wir dadurch erhebliche Infrastrukturkosten. Die Konsolidierung vereinfacht das Routing und Token-Accounting drastisch.\n\nPragmatiker (Enterprise Solutions): Technisch machbar mittels NGINX-Reverse-Proxy und FastAPI-Failover. Empfehlung: Hybrides Modell mit 2 Fallback-Providern.",
                "synthesis": "KONSENS & ENTSCHEIDUNGSEMPFEHLUNG:\n1. Konsolidierung wird befürwortet unter der Bedingung eines automatischen Fallback-Routings.\n2. OmniRoute fungiert als primäres Gateway; bei Latenz > 5000ms wird nahtlos auf direkte API-Keys bzw. lokale Modelle (Ollama) umgeschaltet.\n3. Implementierung eines 30-Tage-Pilotbetriebs mit Token-Monitoring.",
                "vault_file": "boardroom_debatte_sample_001.md"
            },
            {
                "id": "deb_sample_002",
                "timestamp": "2026-10-25T17:15:00",
                "date_display": "25.10.2026 · 17:15 Uhr",
                "task": "Einführung eines autonomen Nacht-Watchdogs für CI/CD-Pipelines und Sicherheits-Patches",
                "framework": "CLEAR-Model",
                "chairman": "Michael Keller (Orchestrator)",
                "rounds": 2,
                "slots_count": 3,
                "slots": [
                    {"name": "Code Security Lead", "role": "Zero-Trust & Pentest", "model": "openai/gpt-4o"},
                    {"name": "Senior DevOps Engineer", "role": "Docker & Infrastructure", "model": "deepseek/deepseek-chat"},
                    {"name": "Quality Assurance", "role": "E2E Playwright Suite", "model": "google/gemini-2.5-flash"}
                ],
                "transcript": "Michael Keller: Diskussion zur Einführung eines autonomen Nacht-Watchdogs für automatische CI/CD-Patches.\n\nSecurity Lead: Autonome Patches dürfen nur in isolierten Staging-Branches committet werden. Production-Deploys erfordern HITL-Freigabe (Human-in-the-Loop).\n\nDevOps: Wir können nächtliche Cron-Jobs aufsetzen, die automatische PRs erstellen und Test-Suites laufen lassen.\n\nQA: Vollständige Test-Suite muss grün sein, bevor ein PR für den Reviewer markiert wird.",
                "synthesis": "KONSENS & FAZIT:\n- Autonomer Nacht-Watchdog wird aktiviert, agiert jedoch im Staging-Modus.\n- Keine automatischen Merges in den Main-Branch ohne 2FA-Freigabe des Administrators.\n- Slack/Telegram-Benachrichtigung bei erfolgreichem Testlauf.",
                "vault_file": "boardroom_debatte_sample_002.md"
            }
        ]
        _save_json(BOARDROOM_HISTORY_FILE, hist)
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


@router.get("/api/boardroom/frameworks")
def api_get_boardroom_frameworks():
    return _DEPS["load_boardroom_frameworks"]()


@router.post("/api/boardroom/frameworks")
def api_save_boardroom_frameworks(frameworks: Dict = Body(...)):
    core_dispatcher.CATEGORIZED_FRAMEWORKS = frameworks
    _save_json(FRAMEWORKS_FILE, frameworks)
    return {"status": "success"}


@router.post("/api/boardroom/frameworks/reset")
def api_reset_boardroom_frameworks():
    if os.path.exists(FRAMEWORKS_FILE):
        try:
            os.remove(FRAMEWORKS_FILE)
        except Exception:
            pass
    core_dispatcher.CATEGORIZED_FRAMEWORKS = _deepcopy(core_dispatcher.DEFAULT_CATEGORIZED_FRAMEWORKS)
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
        
        with open(vault_file, "w", encoding="utf-8") as f:
            f.write(md_content)
        add_ticker("AI Boardroom", f"Protokoll im Vault gespeichert: boardroom_debatte_{ts_str}.md")

        # Speichere strukturierten Eintrag in boardroom_history
        try:
            hist_entry = {
                "id": f"deb_{int(time.time())}",
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
                    
                    with open(vault_file, "w", encoding="utf-8") as f:
                        f.write(md_content)
                    add_ticker("AI Boardroom", f"Protokoll im Vault gespeichert: {vault_file_name}")
                    ev["vault_file"] = vault_file_name
                except Exception as e:
                    print(f"Error saving obsidian vault note: {e}")

                # Save structured debate entry to boardroom history
                try:
                    hist_entry = {
                        "id": f"deb_{int(time.time())}",
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
