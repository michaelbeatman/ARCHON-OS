"""Sub-Router fuer Email Draft Approval Queue (t-7ca8cd).

Ausgelagert aus backend/operations_api.py.
"""

from typing import Any, Dict, Optional
from fastapi import APIRouter, Body, HTTPException

router = APIRouter()


@router.get("/email-drafts")
def api_list_email_drafts(status: Optional[str] = None):
    """Gibt alle E-Mail-Entwürfe der Freigabe-Queue zurück."""
    try:
        from backend.email_draft_engine import email_draft_engine
        drafts = email_draft_engine.list_drafts(status=status)
        counts = email_draft_engine.get_status_counts()
        return {"status": "success", "drafts": drafts, "counts": counts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/email-drafts")
def api_create_email_draft(req: Dict[str, Any] = Body(...)):
    """Erstellt einen neuen E-Mail-Entwurf (z. B. durch einen Agenten)."""
    subject = req.get("subject", "").strip()
    recipient = req.get("recipient", "").strip()
    body_text = req.get("body_text", "").strip()
    agent_id = req.get("agent_id", "default").strip()
    agent_name = req.get("agent_name", "Hermes Orchestrator").strip()
    sender = req.get("sender", "system@archon-os.internal").strip()
    source_task_id = req.get("source_task_id")
    created_by = req.get("created_by", "admin").strip()

    if not subject or not recipient or not body_text:
        raise HTTPException(status_code=400, detail="Betreff, Empfänger und Text sind erforderlich.")

    try:
        from backend.email_draft_engine import email_draft_engine
        draft = email_draft_engine.create_draft(
            subject=subject,
            recipient=recipient,
            body_text=body_text,
            agent_id=agent_id,
            agent_name=agent_name,
            sender=sender,
            source_task_id=source_task_id,
            created_by=created_by,
        )
        return {"status": "success", "draft": draft}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/email-drafts/{draft_id}")
def api_get_email_draft(draft_id: str):
    """Ruft Details zu einem E-Mail-Entwurf ab."""
    try:
        from backend.email_draft_engine import email_draft_engine
        draft = email_draft_engine.get_draft(draft_id)
        if not draft:
            raise HTTPException(status_code=404, detail="Entwurf nicht gefunden.")
        return {"status": "success", "draft": draft}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/email-drafts/{draft_id}/approve")
def api_approve_email_draft(draft_id: str, req: Dict[str, Any] = Body(default={})):
    """Aktion 1: Freigeben & Senden via SMTP."""
    approver_id = req.get("approver_id", "admin").strip()
    try:
        from backend.email_draft_engine import email_draft_engine
        draft = email_draft_engine.approve_and_send(draft_id, approver_id=approver_id)
        return {"status": "success", "draft": draft, "message": "E-Mail freigegeben und versendet."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/email-drafts/{draft_id}")
def api_edit_email_draft(draft_id: str, req: Dict[str, Any] = Body(...)):
    """Aktion 2: Entwurf im Editor anpassen."""
    from backend.email_draft_engine import email_draft_engine
    existing = email_draft_engine.get_draft(draft_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Entwurf nicht gefunden.")

    subject = req.get("subject", existing.get("subject", "")).strip()
    recipient = req.get("recipient", existing.get("recipient", "")).strip()
    body_text = req.get("body_text", existing.get("body_text", "")).strip()
    editor_id = req.get("editor_id", req.get("updated_by", "admin")).strip()

    if not subject or not recipient or not body_text:
        raise HTTPException(status_code=400, detail="Betreff, Empfänger und Text dürfen nicht leer sein.")

    try:
        draft = email_draft_engine.edit_draft(draft_id, subject, recipient, body_text, editor_id=editor_id)
        return {"status": "success", "draft": draft, "message": "Entwurf erfolgreich aktualisiert."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/email-drafts/{draft_id}/snooze")
def api_snooze_email_draft(draft_id: str, req: Dict[str, Any] = Body(default={})):
    """Aktion 3: Später erinnern (Snooze)."""
    hours = int(req.get("hours", 1))
    user_id = req.get("user_id", "admin").strip()
    try:
        from backend.email_draft_engine import email_draft_engine
        draft = email_draft_engine.snooze_draft(draft_id, hours=hours, user_id=user_id)
        return {"status": "success", "draft": draft, "message": f"Entwurf für {hours} Stunde(n) zurückgestellt."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/email-drafts/{draft_id}/regenerate")
def api_regenerate_email_draft(draft_id: str, req: Dict[str, Any] = Body(...)):
    """Aktion 4: Neu generieren mit Prompt-Feedback."""
    feedback = req.get("feedback", "").strip()
    user_id = req.get("user_id", "admin").strip()
    if not feedback:
        raise HTTPException(status_code=400, detail="Feedback für den Agenten ist erforderlich.")

    try:
        from backend.email_draft_engine import email_draft_engine
        draft = email_draft_engine.regenerate_draft(draft_id, feedback_text=feedback, user_id=user_id)
        return {"status": "success", "draft": draft, "message": "Überarbeitungsauftrag an Agenten übergeben."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/email-drafts/{draft_id}/reject")
def api_reject_email_draft(draft_id: str, req: Dict[str, Any] = Body(default={})):
    """Aktion 5: Abbrechen / Verwerfen."""
    reason = req.get("reason", "Vom Nutzer verworfen").strip()
    user_id = req.get("user_id", "admin").strip()
    try:
        from backend.email_draft_engine import email_draft_engine
        draft = email_draft_engine.reject_draft(draft_id, reason=reason, user_id=user_id)
        return {"status": "success", "draft": draft, "message": "Entwurf verworfen."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
