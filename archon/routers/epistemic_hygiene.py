"""
archon/routers/epistemic_hygiene.py
===================================
M53 — REST-Endpunkt für den Epistemic-Hygiene-Wächter.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from archon.routers._rbac import forbid_viewer_writes, require_admin_or_503
from backend.epistemic_hygiene import scan_vault_epistemic_hygiene

router = APIRouter(
    prefix="/api/v1/vault/epistemic-hygiene",
    tags=["Epistemic Hygiene (M53)"],
    dependencies=[Depends(forbid_viewer_writes)],
)


@router.get("")
def get_epistemic_hygiene():
    return scan_vault_epistemic_hygiene()


@router.post("/scan")
def trigger_epistemic_hygiene_scan(request: Request):
    require_admin_or_503(request)
    return scan_vault_epistemic_hygiene()
