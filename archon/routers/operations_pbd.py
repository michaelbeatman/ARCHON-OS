from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
"""Sub-Router fuer Meilenstein 26: Autonomous Computer-Use & PbD (Programming by Demonstration).

Ausgelagert aus backend/operations_api.py.
"""

from typing import Any, Dict, Optional
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])


class PBDStartRequest(BaseModel):
    title: str
    target_url: str = ""
    creator_agent: str = "default"


class PBDEventRequest(BaseModel):
    action_type: str  # click, type, navigate, scroll, voice_instruction
    details: Dict[str, Any] = {}
    commentary: str = ""


class PBDStopRequest(BaseModel):
    skill_slug: Optional[str] = None


class TrajectoryRequest(BaseModel):
    start_x: float
    start_y: float
    end_x: float
    end_y: float
    target_width: float = 40.0
    target_height: float = 24.0
    apply_jitter: bool = True
    steps: int = 20


class A11yPruneRequest(BaseModel):
    html: str
    max_depth: int = 5


@router.post("/bot-screen/pbd/start")
def start_pbd_recording(req: PBDStartRequest):
    """Startet eine Vormach- und Aufnahmesitzung (Programming by Demonstration)."""
    from backend.computer_use_pbd import get_pbd_recorder
    recorder = get_pbd_recorder()
    res = recorder.start_recording(
        session_title=req.title,
        target_url=req.target_url,
        creator_agent=req.creator_agent,
    )
    return res


@router.post("/bot-screen/pbd/event")
def record_pbd_event(req: PBDEventRequest):
    """Zeichnet ein Bediener-Ereignis (Klick, Eingabe, Sprachkommentar) auf."""
    from backend.computer_use_pbd import get_pbd_recorder
    recorder = get_pbd_recorder()
    res = recorder.record_event(
        action_type=req.action_type,
        details=req.details,
        commentary=req.commentary,
    )
    return res


@router.get("/bot-screen/pbd/status")
def get_pbd_status():
    """Liefert den aktuellen Aufnahmestatus und bisherige Schritte."""
    from backend.computer_use_pbd import get_pbd_recorder
    recorder = get_pbd_recorder()
    session = recorder.get_current_session()
    return {
        "is_recording": session is not None,
        "session": session,
    }


@router.post("/bot-screen/pbd/stop-and-synthesize")
def stop_pbd_and_synthesize(req: PBDStopRequest):
    """Beendet die Demonstration und synthetisiert einen Skill (SKILL.md + Python-Skript)."""
    from backend.computer_use_pbd import get_pbd_recorder
    recorder = get_pbd_recorder()
    res = recorder.stop_and_synthesize_skill(skill_slug=req.skill_slug)
    return res


@router.post("/bot-screen/trajectory")
def calculate_ghost_cursor_trajectory(req: TrajectoryRequest):
    """Berechnet biomechanische Bézier-Punkte mit Fitts's Law und Bounding-Box Jitter."""
    from backend.computer_use_pbd import get_ghost_cursor
    engine = get_ghost_cursor()

    end_x, end_y = req.end_x, req.end_y
    if req.apply_jitter:
        end_x, end_y = engine.apply_bounding_box_jitter(
            center_x=req.end_x,
            center_y=req.end_y,
            width=req.target_width,
            height=req.target_height,
        )

    points = engine.calculate_bezier_trajectory(
        start=(req.start_x, req.start_y),
        end=(end_x, end_y),
        steps=req.steps,
    )

    return {
        "status": "success",
        "target_point": {"x": end_x, "y": end_y},
        "trajectory": points,
        "jitter_applied": req.apply_jitter,
    }


@router.post("/bot-screen/a11y-prune")
def prune_a11y_tree(req: A11yPruneRequest):
    """Reduziert rohes HTML auf einen kompakten semantischen Accessibility-Tree."""
    from backend.computer_use_pbd import get_observation_pruner
    pruner = get_observation_pruner()
    return pruner.prune_html_to_a11y_tree(raw_html=req.html, max_depth=req.max_depth)
