from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
"""Sub-Router fuer Autonomie-Systeme (Features 6, 8, 10, 13).

Ausgelagert aus backend/operations_api.py.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from archon.routers._rbac import require_admin_or_503

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])


class ToolEvolutionRequest(BaseModel):
    tool_name: str
    description: str
    sample_usage_prompt: str = ""
    creator_agent: str = "default"
    max_retries: int = 3
    implementation_code: Optional[str] = None
    verification_test_code: Optional[str] = None


class MCTSSimulationRequest(BaseModel):
    task_goal: str
    candidate_actions: List[Dict[str, Any]]
    simulations_per_candidate: int = 10
    agent_id: str = "default"


class PrefetchRequest(BaseModel):
    user_prompt: str
    agent_id: str = "default"


class JITPersonaTaskRequest(BaseModel):
    task_description: str
    creator_agent: str = "default"
    auto_purge_on_complete: bool = True
    context: Dict[str, Any] = {}


@router.get("/autonomy/evolved-tools")
def list_evolved_tools():
    """Gibt alle autonom synthetisierten Voyager-Werkzeuge zurück."""
    from backend.self_evolving_tooling import get_self_evolving_tool_engine
    engine = get_self_evolving_tool_engine()
    return {"status": "success", "tools": engine.list_evolved_tools()}


@router.post("/autonomy/evolve-tool")
def trigger_tool_evolution(request: Request, req: ToolEvolutionRequest):
    """Voyager-Zyklus für FERTIGEN Code: Sandbox-Test, Reparaturversuche, Registrierung."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    from backend.self_evolving_tooling import get_self_evolving_tool_engine
    implementation_code = (req.implementation_code or "").strip()
    verification_test_code = (req.verification_test_code or "").strip()
    if not implementation_code:
        raise HTTPException(
            status_code=400,
            detail=(
                "Keine Synthese möglich: die Selbst-Evolutions-Engine erzeugt keinen "
                "Code aus einer Beschreibung. 'implementation_code' (und sinnvollerweise "
                "'verification_test_code') müssen mitgeschickt werden — die Engine testet "
                "und repariert fertigen Code in der Sandbox."
            ),
        )
    engine = get_self_evolving_tool_engine()
    return engine.synthesize_and_evolve_tool(
        creator_agent=req.creator_agent,
        tool_name=req.tool_name,
        description=req.description,
        implementation_code=implementation_code,
        verification_test_code=verification_test_code,
        max_repair_iterations=req.max_retries,
    )


@router.post("/autonomy/mcts-simulate")
def simulate_mcts_trajectories(req: MCTSSimulationRequest):
    """Simuliert Handlungsstränge mittels Monte Carlo Tree Search vor deren Ausführung."""
    from backend.mcts_engine import get_mcts_engine
    engine = get_mcts_engine()
    res = engine.evaluate_action_paths(
        task_goal=req.task_goal,
        candidate_actions=req.candidate_actions,
        simulations_per_candidate=req.simulations_per_candidate,
        agent_id=req.agent_id,
    )
    return res


@router.post("/autonomy/prefetch")
def trigger_speculative_prefetch(req: PrefetchRequest):
    """Erkennt spekulativ Entitäten (CRM, ERP, Learnings) und legt sie in den schnellen RAM-Cache."""
    from backend.speculative_prefetcher import get_speculative_prefetcher
    prefetcher = get_speculative_prefetcher()
    res = prefetcher.prefetch_for_prompt(
        user_prompt=req.user_prompt,
        agent_id=req.agent_id,
    )
    return res


@router.post("/autonomy/jit-persona/execute")
def execute_jit_persona_task(request: Request, req: JITPersonaTaskRequest):
    """Erzeugt ad-hoc eine flüchtige Spezialisten-Persona und führt die Aufgabe isoliert aus."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    from backend.jit_persona_engine import get_jit_persona_engine
    engine = get_jit_persona_engine()
    res = engine.execute_ephemeral_task(
        task_description=req.task_description,
        creator_agent=req.creator_agent,
        auto_purge_on_complete=req.auto_purge_on_complete,
        context=req.context,
    )
    return res


@router.get("/autonomy/jit-persona/ephemeral")
def list_ephemeral_personas():
    """Gibt alle aktuell aktiven flüchtigen Spezialisten-Personas zurück."""
    from backend.jit_persona_engine import get_jit_persona_engine
    engine = get_jit_persona_engine()
    return {"status": "success", "ephemeral_personas": engine.list_active_ephemeral_personas()}
