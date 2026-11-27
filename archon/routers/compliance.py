"""M68 — /api/compliance/*: read-only Compliance-Endpunkte.

Der Router wird bewusst NICHT in ``main.py`` registriert; der Integrator verdrahtet
ihn mit ``app.include_router(compliance.router)``. Alle Endpunkte haengen am
gemeinsamen Admin-Zaun (``_rbac.require_admin_or_503``, fail-closed) und schreiben
keinerlei SSOT. Der Mandant kommt ausschliesslich aus dem verifizierten Kontext
(kein client-gesteuertes ``tenant_id`` = kein IDOR).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from archon.routers._rbac import require_admin_or_503

router = APIRouter(dependencies=[Depends(require_admin_or_503)])


def _active_tenant() -> str:
    """Mandant aus der SSOT; ohne verfuegbaren Kontext fail-closed auf 'default'."""
    try:
        from backend.tenant_context import tenant_context

        return str(tenant_context.get_active_tenant_id() or "default")
    except Exception:
        return "default"


@router.get("/api/compliance/inventory")
@router.get("/api/v1/compliance/inventory")
def api_compliance_inventory() -> dict[str, Any]:
    """Tenant-Compliance-Inventar (Agent -> Datenklasse -> Ziel -> Freigabe -> Retention)."""
    from backend.compliance_inventory import build_inventory

    tenant_id = _active_tenant()
    items = build_inventory(tenant_id)
    return {"status": "success", "tenant_id": tenant_id, "inventory": items, "count": len(items)}


@router.get("/api/compliance/dpia-register")
@router.get("/api/v1/compliance/dpia-register")
def api_compliance_dpia_register() -> dict[str, Any]:
    """Versioniertes Art.-35-Register inkl. Fingerprint und Change-Triggern (read-only)."""
    from backend.compliance_inventory import DPIARegister

    register = DPIARegister().load()
    return {"status": "success", "register": register}


@router.get("/api/compliance/retention")
@router.get("/api/v1/compliance/retention")
def api_compliance_retention() -> dict[str, Any]:
    """Aufbewahrungsfristen je Log-Kategorie (GoBD 10 Jahre vs. Betriebs-Logs)."""
    from backend.compliance_inventory import (
        GOBD_RETENTION_YEARS,
        RETENTION_MAP,
        retention_for_category,
    )

    return {
        "status": "success",
        "gobd_years": GOBD_RETENTION_YEARS,
        "categories": {key: retention_for_category(key) for key in RETENTION_MAP},
    }


@router.get("/api/compliance/replay")
@router.get("/api/v1/compliance/replay")
def api_compliance_replay(
    limit: int = Query(default=10_000, ge=1, le=50_000),
) -> dict[str, Any]:
    """Audit-Replay mit Reihenfolge-/Luecken-/Kettenschlusspruefung (M112 + Fallback)."""
    from backend.compliance_inventory import replay_from_ledger

    return {"status": "success", "replay": replay_from_ledger(_active_tenant(), limit=limit)}


@router.get("/api/compliance/inventory.pdf")
@router.get("/api/v1/compliance/inventory.pdf")
def api_compliance_inventory_pdf() -> Response:
    """Vollstaendiger Compliance-Inventar-Export als PDF; SHA-256 als Response-Header."""
    from backend.compliance_inventory import export_inventory_pdf

    pdf_bytes, pdf_sha256 = export_inventory_pdf(_active_tenant())
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="Archon_Compliance_Inventar_M68.pdf"',
            "X-Document-SHA256": pdf_sha256,
        },
    )


@router.get("/api/compliance/policy.md")
@router.get("/api/v1/compliance/policy.md")
def api_compliance_policy_markdown() -> Response:
    """Einseitiger Policy-Export als Markdown (Art.-50-gekennzeichnet, PII-frei)."""
    from backend.compliance_inventory import export_policy_markdown

    content = export_policy_markdown(_active_tenant())
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="Archon_Compliance_Policy_M68.md"'},
    )


@router.get("/api/compliance/policy.pdf")
@router.get("/api/v1/compliance/policy.pdf")
def api_compliance_policy_pdf() -> Response:
    """Einseitiger Policy-Export als PDF; SHA-256 als Response-Header."""
    from backend.compliance_inventory import export_policy_pdf

    pdf_bytes, pdf_sha256 = export_policy_pdf(_active_tenant())
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="Archon_Compliance_Policy_M68.pdf"',
            "X-Document-SHA256": pdf_sha256,
        },
    )
