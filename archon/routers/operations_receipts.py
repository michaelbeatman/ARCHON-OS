import logging
_archon_exc_logger = logging.getLogger("operations_receipts")
from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
"""Sub-Router fuer Beleg-Verarbeitung, OCR und Archivierung (Receipts Engine).

Ausgelagert aus backend/operations_api.py.
"""

import base64
import os
from typing import Any, Dict, Optional
from fastapi import APIRouter, Body, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from archon.routers._rbac import require_admin_or_503
from utils.path_jail import PathJailError, safe_path_within
from archon.core.runtime import APP_ROOT

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])


class ReceiptProcessRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    image_base64: Optional[str] = None
    image_path: Optional[str] = None
    filename: str = "receipt.jpg"
    source: str = "api"
    sender: str = "Operator"
    create_kanban_task: bool = True

    @model_validator(mode="after")
    def _require_image(self) -> "ReceiptProcessRequest":
        if not self.image_base64 and not self.image_path:
            raise ValueError("image_base64 oder image_path erforderlich")
        return self


class ReceiptPatchRequest(BaseModel):
    """Nur die von receipt_ocr_engine.update_receipt erlaubten Felder."""
    model_config = ConfigDict(extra="ignore")
    status: Optional[str] = Field(default=None, pattern=r"^(draft|review|approved|rejected|booked|paid)$")
    category: Optional[str] = None
    merchant: Optional[str] = None
    amount_gross: Optional[float] = Field(default=None, ge=0)
    tax_amount: Optional[float] = Field(default=None, ge=0)
    payment_method: Optional[str] = None


# =========================================================================
# BELEGVERARBEITUNG & VISION OCR (RECEIPTS ENGINE)
# =========================================================================

@router.post("/receipts/process")
def api_receipts_process(request: Request, req: ReceiptProcessRequest):
    """Verarbeitet einen Beleg: Extrahiert Buchhaltungs-Metadaten via Vision OCR und legt Task an."""
    require_admin_or_503(request)
    b64_data = req.image_base64
    image_path = req.image_path
    filename = req.filename
    source = req.source
    sender = req.sender
    create_task = req.create_kanban_task

    img_bytes = None
    if b64_data:
        try:
            if "," in b64_data:
                b64_data = b64_data.split(",", 1)[1]
            img_bytes = base64.b64decode(b64_data)
        except Exception as e:
            raise HTTPException(status_code=400, detail={"code": "receipts_invalid_base64", "params": {"error": str(e)}})
    elif image_path:
        allowed_roots = [os.path.join(APP_ROOT, "data"), os.path.join(APP_ROOT, "inbox")]
        safe_img = None
        for root in allowed_roots:
            try:
                safe_img = safe_path_within(root, image_path)
                break
            except (PathJailError, ValueError):
                continue
        if not safe_img or not os.path.exists(safe_img):
            raise HTTPException(status_code=403, detail="image_path außerhalb der erlaubten Beleg-Verzeichnisse oder nicht gefunden.")
        try:
            with open(safe_img, "rb") as fh:
                img_bytes = fh.read()
            filename = os.path.basename(safe_img)
        except Exception as e:
            raise HTTPException(status_code=400, detail={"code": "receipts_image_read_failed", "params": {"error": str(e)}})
    else:
        raise HTTPException(status_code=400, detail="Entweder 'image_base64' oder ein existierender 'image_path' ist erforderlich.")

    try:
        from backend.receipt_ocr_engine import receipt_ocr_engine
        result = receipt_ocr_engine.process_receipt(
            image_bytes=img_bytes,
            filename=filename,
            source=source,
            sender=sender,
            create_kanban_task=create_task
        )
        return {"status": "success", "receipt": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "receipts_processing_failed", "params": {"error": str(e)}})


@router.get("/receipts")
def api_receipts_list(limit: int = Query(default=50)):
    """Gibt die Liste der archivierten Belege zurück."""
    try:
        from backend.receipt_ocr_engine import receipt_ocr_engine
        receipts = receipt_ocr_engine.list_receipts(limit=limit)
        return {"status": "success", "count": len(receipts), "receipts": receipts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/receipts/{receipt_id}/image")
def api_receipt_image(receipt_id: str):
    """Gibt die Belegdatei als Bild aus."""
    from backend.receipt_ocr_engine import receipt_ocr_engine
    rcpt = receipt_ocr_engine.get_receipt(receipt_id)
    if not rcpt or not rcpt.get("image_path") or not os.path.exists(rcpt["image_path"]):
        # 1x1 transparent SVG fallback
        svg = '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200"><rect width="200" height="200" fill="#1e293b"/><text x="50%" y="50%" fill="#94a3b8" dominant-baseline="middle" text-anchor="middle" font-family="sans-serif" font-size="14">Kein Bild</text></svg>'
        return Response(content=svg, media_type="image/svg+xml")
    return FileResponse(rcpt["image_path"])


@router.patch("/receipts/{receipt_id}")
def api_receipt_patch(request: Request, receipt_id: str, updates: ReceiptPatchRequest):
    """Aktualisiert Belegdaten wie Status (approved/rejected), Kategorie oder Betrag."""
    # Alle Peer-Endpunkte schuetzen schreibende Finanzoperationen mit Admin.
    require_admin_or_503(request)
    # Nur gesetzte Felder weiterreichen — `None` würde sonst NULL in die DB
    # schreiben und bestehende Beträge löschen.
    update_dict = updates.model_dump(exclude_none=True)
    if not update_dict:
        raise HTTPException(status_code=400, detail="Keine zu aktualisierenden Felder.")
    from backend.receipt_ocr_engine import receipt_ocr_engine
    ok = receipt_ocr_engine.update_receipt(receipt_id, update_dict)
    if not ok:
        raise HTTPException(status_code=400, detail="Aktualisierung fehlgeschlagen oder keine gültigen Felder.")
    try:
        from backend.audit_log import chained_audit_log
        chained_audit_log.record_event(
            category="finance",
            action="receipt_updated",
            agent_id="finance_operator",
            payload={"receipt_id": receipt_id, "updates": updates}
        )
    except Exception as _exc:
        _archon_exc_logger.debug("[operations_receipts] Ignorierte Ausnahme (Z.115): %s", _exc)
    return {"status": "success", "receipt_id": receipt_id, "updated": update_dict}


@router.post("/receipts/upload")
async def api_receipts_upload(file: UploadFile = File(...), sender: str = "WebUI", category: Optional[str] = None):
    """Upload von Belegen via Drag & Drop aus der Weboberfläche."""
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Datei ist leer.")
    try:
        from backend.receipt_ocr_engine import receipt_ocr_engine
        result = receipt_ocr_engine.process_receipt(
            image_bytes=contents,
            filename=file.filename or "receipt.jpg",
            source="web_upload",
            sender=sender,
            create_kanban_task=True
        )
        if category and result.get("receipt_id"):
            receipt_ocr_engine.update_receipt(result["receipt_id"], {"category": category})
            result["category"] = category
        return {"status": "success", "receipt": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "receipts_upload_failed", "params": {"error": str(e)}})
