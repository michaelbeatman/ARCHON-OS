"""Einziger Registrierungspunkt der 14 ``/api/operations``-Unter-Router (F4).

``backend/operations_api.py`` traegt weiterhin denselben APIRouter mit
``prefix="/api/operations"``, den ``forbid_viewer_writes``-Dependencies und
allen EIGENEN Endpunkten (Kanban, Esign, ...). Dieses Modul haelt nur die
``include_router``-Aufrufe und re-exportiert genau diesen Router fuer
``main.py:2752`` - es wird kein zweiter Router erzeugt (sonst doppeltes
Prefix bzw. verlorene Routen).

Warum hier: ``backend`` darf ``archon.routers`` nicht importieren
(D09/H-09-2). Die erlaubte Richtung ist ``archon.routers -> backend``.

Die 14 Router werden 1:1 in der historischen Reihenfolge registriert
(Reihenfolge = Pfad-Praezedenz, vgl. main.py:3149-3150):
org -> dag -> prompts -> receipts -> sysops -> dunning -> finetuning ->
approvals -> keys -> emails -> security -> bot_screen -> autonomy -> pbd.
Ein Importfehler bricht den Start weiterhin ueber den try/except in
main.py:2751 plus _ROUTER_LOAD_ERRORS / _assert_router_health() fail-closed ab.
"""

from archon.routers import (
    operations_approvals,
    operations_autonomy,
    operations_bot_screen,
    operations_dag,
    operations_dunning,
    operations_emails,
    operations_finetuning,
    operations_keys,
    operations_org,
    operations_pbd,
    operations_prompts,
    operations_receipts,
    operations_security,
    operations_sysops,
)
from backend.operations_api import router

__all__ = ["router"]

# Reihenfolge 1:1 aus backend/operations_api.py (alt :4116-4507).
# NICHT alphabetisch umsortieren: Pfad-Praezedenz.
router.include_router(operations_org.router)
router.include_router(operations_dag.router)
router.include_router(operations_prompts.router)
router.include_router(operations_receipts.router)
router.include_router(operations_sysops.router)
router.include_router(operations_dunning.router)
router.include_router(operations_finetuning.router)
router.include_router(operations_approvals.router)
router.include_router(operations_keys.router)
router.include_router(operations_emails.router)
router.include_router(operations_security.router)
router.include_router(operations_bot_screen.router)
router.include_router(operations_autonomy.router)
router.include_router(operations_pbd.router)
