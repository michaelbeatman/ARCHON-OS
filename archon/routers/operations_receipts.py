from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
"""Sub-Router fuer Beleg-Verarbeitung, OCR und Archivierung (Receipts Engine).

Ausgelagert aus backend/operations_api.py.
"""

import base64
import os
from typing import Any, Dict, Optional
from fastapi import APIRouter, Body, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])


# =========================================================================
# BELEGVERARBEITUNG & VISION OCR (RECEIPTS ENGINE)
# =========================================================================

@router.post("/receipts/process")
def api_receipts_process(req: Dict[str, Any] = Body(...)):
    """Verarbeitet einen Beleg: Extrahiert Buchhaltungs-Metadaten via Vision OCR und legt Task an."""
    b64_data = req.get("image_base64")
    image_path = req.get("image_path")
    filename = req.get("filename", "receipt.jpg")
    source = req.get("source", "api")
    sender = req.get("sender", "Operator")
    create_task = bool(req.get("create_kanban_task", True))

    img_bytes = None
    if b64_data:
        try:
            if "," in b64_data:
                b64_data = b64_data.split(",", 1)[1]
            img_bytes = base64.b64decode(b64_data)
        except Exception as e:
            raise HTTPException(status_code=400, detail={"code": "receipts_invalid_base64", "params": {"error": str(e)}})
    elif image_path and os.path.exists(image_path):
        try:
            with open(image_path, "rb") as fh:
                img_bytes = fh.read()
            filename = os.path.basename(image_path)
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
def api_receipt_patch(receipt_id: str, updates: Dict[str, Any] = Body(...)):
    """Aktualisiert Belegdaten wie Status (approved/rejected), Kategorie oder Betrag."""
    from backend.receipt_ocr_engine import receipt_ocr_engine
    ok = receipt_ocr_engine.update_receipt(receipt_id, updates)
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
    except Exception:
        pass
    return {"status": "success", "receipt_id": receipt_id, "updated": updates}


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
