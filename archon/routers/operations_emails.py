import logging
_archon_exc_logger = logging.getLogger("operations_emails")
from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
"""Sub-Router fuer Email Draft Approval Queue (t-7ca8cd).

Ausgelagert aus backend/operations_api.py.
"""

from typing import Optional
from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from archon.routers._rbac import require_admin_or_503, require_session_actor


class EmailDraftCreateRequest(BaseModel):
    """Validierter Payload für POST /email-drafts (Etappe 7)."""
    # extra="ignore": Clients senden Zusatzfelder (z. B. created_by), die
    # serverseitig aus der Session kommen und nicht vertrauenswürdig sind.
    model_config = ConfigDict(extra="ignore")
    subject: str = Field(default="", max_length=1_000)
    recipient: str = Field(default="", max_length=2_000)
    body_text: str = Field(default="", max_length=100_000)
    agent_id: str = Field(default="default", max_length=128)
    agent_name: str = Field(default="Hermes Orchestrator", max_length=128)
    sender: str = Field(default="system@archon-os.internal", max_length=256)
    source_task_id: Optional[str] = None
    created_by: str = Field(default="admin", max_length=128)


class EmailDraftApproveRequest(BaseModel):
    """Optionaler Payload für POST /email-drafts/{id}/approve (Etappe 7)."""
    model_config = ConfigDict(extra="ignore")
    approver_id: str = Field(default="admin", max_length=128)


class EmailDraftEditRequest(BaseModel):
    """Validierter Payload für PUT /email-drafts/{id} (Etappe 7).

    None bedeutet "nicht angegeben" -> Wert aus dem bestehenden Entwurf.
    """
    model_config = ConfigDict(extra="ignore")
    subject: Optional[str] = Field(default=None, max_length=1_000)
    recipient: Optional[str] = Field(default=None, max_length=2_000)
    body_text: Optional[str] = Field(default=None, max_length=100_000)
    editor_id: Optional[str] = Field(default=None, max_length=128)
    updated_by: Optional[str] = Field(default=None, max_length=128)


class EmailDraftSnoozeRequest(BaseModel):
    """Optionaler Payload für POST /email-drafts/{id}/snooze (Etappe 7)."""
    model_config = ConfigDict(extra="ignore")
    hours: int = Field(default=1, ge=1, le=8_760)  # 1 Stunde .. 1 Jahr
    user_id: str = Field(default="admin", max_length=128)


class EmailDraftRegenerateRequest(BaseModel):
    """Validierter Payload für POST /email-drafts/{id}/regenerate (Etappe 7)."""
    model_config = ConfigDict(extra="ignore")
    feedback: str = Field(default="", max_length=20_000)
    user_id: str = Field(default="admin", max_length=128)


class EmailDraftRejectRequest(BaseModel):
    """Optionaler Payload für POST /email-drafts/{id}/reject (Etappe 7)."""
    model_config = ConfigDict(extra="ignore")
    reason: str = Field(default="Vom Nutzer verworfen", max_length=1_000)
    user_id: str = Field(default="admin", max_length=128)


router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])


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
def api_create_email_draft(req: EmailDraftCreateRequest):
    """Erstellt einen neuen E-Mail-Entwurf (z. B. durch einen Agenten)."""
    subject = req.subject.strip()
    recipient = req.recipient.strip()
    body_text = req.body_text.strip()
    agent_id = req.agent_id.strip()
    agent_name = req.agent_name.strip()
    sender = req.sender.strip()
    source_task_id = req.source_task_id
    created_by = req.created_by.strip()

    if not subject or not recipient or not body_text:
        raise HTTPException(status_code=400, detail={"code": "emails_subject_recipient_text_required", "params": {}})

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
            raise HTTPException(status_code=404, detail={"code": "emails_draft_not_found", "params": {}})
        return {"status": "success", "draft": draft}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/email-drafts/{draft_id}/approve")
def api_approve_email_draft(request: Request, draft_id: str, req: EmailDraftApproveRequest = Body(default=EmailDraftApproveRequest())):
    """Aktion 1: Freigeben & Senden via SMTP."""
    require_admin_or_503(request)
    # KRITISCH: niemals den vom Client übergebenen approver_id als Fallback
    # verwenden — sonst lässt sich ein Vier-Augen-Prinzip mit erfundenen
    # Namen fälschen (Audit 23.11.2026).
    approver_id = require_session_actor(request)
    try:
        from backend.email_draft_engine import email_draft_engine
        draft = email_draft_engine.approve_and_send(draft_id, approver_id=approver_id)
        try:
            from backend.workflow_scheduler import dispatch_workflow_event
            dispatch_workflow_event(
                source="approval",
                event_type="email_approved",
                title=f"E-Mail freigegeben: {draft.get('subject') or draft_id}",
                summary=f"Empfaenger: {draft.get('recipient', '')} | Freigegeben durch {approver_id}",
                payload={"draft_id": draft_id, "approver": approver_id},
                correlation_id=f"mail-apr-{draft_id}",
            )
        except Exception as _exc:
            _archon_exc_logger.debug("[operations_emails] Ignorierte Ausnahme (Z.92): %s", _exc)
        # Audit 23.11.2026: die Nachricht darf nur bei echtem SMTP-Erfolg
        # 'versendet' behaupten. Engine liefert delivery_status + ehrliche Message.
        delivery_status = draft.get("delivery_status") or "unknown"
        return {
            "status": "success" if delivery_status == "sent" else "partial",
            "draft": draft,
            "delivery_status": delivery_status,
            "message": draft.get("message") or "Freigabe ohne Versandbestätigung.",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/email-drafts/{draft_id}")
def api_edit_email_draft(draft_id: str, req: EmailDraftEditRequest):
    """Aktion 2: Entwurf im Editor anpassen."""
    from backend.email_draft_engine import email_draft_engine
    existing = email_draft_engine.get_draft(draft_id)
    if not existing:
        raise HTTPException(status_code=404, detail={"code": "emails_draft_not_found_2", "params": {}})

    subject = req.subject.strip() if req.subject is not None else existing.get("subject", "")
    recipient = req.recipient.strip() if req.recipient is not None else existing.get("recipient", "")
    body_text = req.body_text.strip() if req.body_text is not None else existing.get("body_text", "")
    editor_id = (
        req.editor_id if req.editor_id is not None
        else (req.updated_by if req.updated_by is not None else "admin")
    ).strip()

    if not subject or not recipient or not body_text:
        raise HTTPException(status_code=400, detail="Betreff, Empfänger und Text dürfen nicht leer sein.")

    try:
        draft = email_draft_engine.edit_draft(draft_id, subject, recipient, body_text, editor_id=editor_id)
        return {"status": "success", "draft": draft, "message": "Entwurf erfolgreich aktualisiert."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/email-drafts/{draft_id}/snooze")
def api_snooze_email_draft(draft_id: str, req: EmailDraftSnoozeRequest = Body(default=EmailDraftSnoozeRequest())):
    """Aktion 3: Später erinnern (Snooze)."""
    hours = req.hours
    user_id = req.user_id.strip()
    try:
        from backend.email_draft_engine import email_draft_engine
        draft = email_draft_engine.snooze_draft(draft_id, hours=hours, user_id=user_id)
        return {"status": "success", "draft": draft, "message": f"Entwurf für {hours} Stunde(n) zurückgestellt."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/email-drafts/{draft_id}/regenerate")
def api_regenerate_email_draft(draft_id: str, req: EmailDraftRegenerateRequest):
    """Aktion 4: Neu generieren mit Prompt-Feedback."""
    feedback = req.feedback.strip()
    user_id = req.user_id.strip()
    if not feedback:
        raise HTTPException(status_code=400, detail="Feedback für den Agenten ist erforderlich.")

    try:
        from backend.email_draft_engine import email_draft_engine
        draft = email_draft_engine.regenerate_draft(draft_id, feedback_text=feedback, user_id=user_id)
        return {"status": "success", "draft": draft, "message": "Überarbeitungsauftrag an Agenten übergeben."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/email-drafts/{draft_id}/reject")
def api_reject_email_draft(draft_id: str, req: EmailDraftRejectRequest = Body(default=EmailDraftRejectRequest())):
    """Aktion 5: Abbrechen / Verwerfen."""
    reason = req.reason.strip()
    user_id = req.user_id.strip()
    try:
        from backend.email_draft_engine import email_draft_engine
        draft = email_draft_engine.reject_draft(draft_id, reason=reason, user_id=user_id)
        return {"status": "success", "draft": draft, "message": "Entwurf verworfen."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
