"""Router fuer Hermes Core Updates (/api/v1/hermes/update/*)."""
from __future__ import annotations

import logging
from typing import Dict

from fastapi import APIRouter, Body, HTTPException, Request

logger = logging.getLogger("archon.routers.updater")

router = APIRouter(tags=["updater"])


@router.get("/api/v1/hermes/update/check")
def api_hermes_update_check(force: bool = False):
    from backend import hermes_updater

    return hermes_updater.check_hermes_updates(force_refresh=force)


@router.post("/api/v1/hermes/update/apply")
def api_hermes_update_apply(request: Request, payload: Dict = Body(default={})):
    import main as app_main

    curr_user = app_main.get_current_user_from_request(request)
    if curr_user.get("role") != "admin":
        raise HTTPException(
            status_code=403, detail="Nur Administratoren dürfen Hermes Core Updates einleiten."
        )
    from backend import hermes_updater

    channel = payload.get("channel", "latest")
    auto_restart = payload.get("restart", True)
    return hermes_updater.apply_hermes_update(channel=channel, auto_restart=auto_restart)
