"""4-Augen-Qualitaetsreview & Hoheits-Override (D3/5 aus backend/operations_api.py).

Reine Extraktion nach dem S3-Muster (Call-Time-Dependency-Injection):
* Kein Rueckimport auf ``backend.operations_api``.
* Kein Import aus ``archon.routers.*`` (wahrt Layer-Contract D09/H-09-2).
* Alle Monkeypatches auf ``backend.operations_api._get_kanban_connection``,
  ``_load_kanban_meta`` und ``_load_profiles_map`` greifen unveraendert.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import re
import sys
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Set

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from archon.core.provider_registry import get_provider

logger = logging.getLogger("archon_os.operations_api")


class QualityReviewVerdict(BaseModel):
    """Fail-closed-Schema der Reviewer-Antwort (R-16)."""

    model_config = ConfigDict(extra="ignore")

    verdict: str = "changes_requested"
    score: int = 0
    summary: str = ""
    critique_points: List[str] = Field(default_factory=list)
    actionable_next_steps: List[str] = Field(default_factory=list)


class QualityReviewRequest(BaseModel):
    """H-14-2/F022: kein Body-Override mehr fuer das 4-Augen-Qualitaetsreview.

    ``force_verdict`` und ``reviewer_id`` waren direkt aus dem Body faehig, das
    Vier-Augen-Gate zu faelschen (hartcodierter Reviewer ``operator``). Die
    Verifikation laeuft jetzt immer ueber den Reviewer-Agenten; eine manuelle
    Aufhebung von ``changes_requested`` nur ueber
    ``POST /kanban/tasks/{id}/quality-review/override`` mit Session-Actor,
    zweiter Identitaet und HITL-Proof.
    """

    model_config = ConfigDict(extra="ignore")

    comment: Optional[str] = Field(default=None, max_length=4000)


class QualityReviewOverrideRequest(BaseModel):
    """Expliziter 4-Augen-Override eines ``changes_requested``-Reviews."""

    model_config = ConfigDict(extra="ignore")

    reason: str = Field(min_length=10, max_length=4000)
    passkey_proof_token: Optional[str] = None
    approval_id: Optional[str] = None


class ReviewDeps(NamedTuple):
    """Zur Aufrufzeit injizierte Abhaengigkeiten aus backend.operations_api."""

    get_kanban_connection: Callable[..., Any]
    load_kanban_meta: Callable[[], Dict[str, Any]]
    load_profiles_map: Callable[[], Dict[str, Any]]
    current_quality_review: Optional[Callable[[str], Dict[str, Any]]] = None
    task_created_by: Optional[Callable[[str], str]] = None
    task_status: Optional[Callable[[str], str]] = None
    require_four_eyes_override: Optional[Callable[..., Dict[str, Any]]] = None


def _identity_tokens(actor: str) -> Set[str]:
    """Normalisierte Identitaets-Tokens (wie in approval_policy_engine)."""
    s = str(actor or "").strip().lower()
    if not s:
        return set()
    tokens = {s}
    if " (i.v. " in s:
        main_p, sub_p = s.split(" (i.v. ", 1)
        tokens.add(main_p.strip())
        sub_clean = sub_p.rstrip(")").strip()
        if sub_clean:
            tokens.add(sub_clean)
            tokens.add(sub_clean.split(" ")[0])
    else:
        tokens.add(s.split(" ")[0])
    return {t for t in tokens if t}


def current_quality_review(task_id: str, deps: ReviewDeps) -> Dict[str, Any]:
    """Liest das Review aus der Sidecar-SSOT (fail-closed bei Fehlern)."""
    try:
        meta = deps.load_kanban_meta()
        return dict(((meta.get("tasks") or {}).get(task_id) or {}).get("quality_review") or {})
    except Exception as exc:
        logger.error("[4-Augen] Review-Sidecar nicht lesbar (fail-closed): %s", exc)
        raise HTTPException(status_code=503, detail="quality_review_state_unavailable")


def task_created_by(task_id: str, deps: ReviewDeps) -> str:
    conn = deps.get_kanban_connection(maintenance=True)
    try:
        row = conn.execute("SELECT created_by FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return str((row["created_by"] if row else "") or "")
    finally:
        conn.close()


def task_status(task_id: str, deps: ReviewDeps) -> str:
    conn = deps.get_kanban_connection(maintenance=True)
    try:
        row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return str((row["status"] if row else "") or "")
    finally:
        conn.close()


def require_four_eyes_override(
    *,
    task_id: str,
    actor: str,
    review: Dict[str, Any],
    reason: str,
    proof_token: Optional[str],
    action: str,
    created_by: str = "",
    approval_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Prueft die Hoheits-Kette fuer ``done``-Overrides (fail-closed).

    Rueckgabe: signierfaehiger Evidence-Block. Jede Verletzung fuehrt zu 403;
    nicht verfuegbare HITL-Konfiguration zu 503. Der Actor stammt ausschliesslich
    aus ``require_session_actor(request)``.
    """
    who = str(actor or "").strip()
    why = str(reason or "").strip()
    if not who:
        raise HTTPException(status_code=401, detail="Keine verifizierte Session-Identitaet.")
    if len(why) < 10:
        raise HTTPException(
            400,
            detail="Begruendung des 4-Augen-Overrides fehlt oder zu kurz (min. 10 Zeichen).",
        )

    actor_tokens = _identity_tokens(who)
    other_ids = [
        str(review.get("reviewer_id") or ""),
        str(review.get("reviewer") or ""),
        str(created_by or ""),
    ]
    for other in other_ids:
        if other and actor_tokens & _identity_tokens(other):
            raise HTTPException(
                status_code=403,
                detail="Vier-Augen-Prinzip: der Override muss durch eine andere Person erfolgen "
                "als der Reviewer oder der Ersteller des Tasks.",
            )

    from backend.passkey_hitl import consume_hitl_proof_token

    token = str(proof_token or "").strip()
    try:
        ok = consume_hitl_proof_token(
            token, who, "system", action=action, resource=task_id, consume=True
        )
    except Exception as exc:
        logger.error("[4-Augen] HITL-Pruefung fehlgeschlagen (fail-closed): %s", exc)
        raise HTTPException(status_code=503, detail="hitl_proof_check_unavailable")
    if not ok:
        raise HTTPException(
            status_code=403,
            detail="Passkey-Proof erforderlich/ungueltig fuer diesen 4-Augen-Override "
            "(action/resource nicht gebunden).",
        )

    evidence: Dict[str, Any] = {
        "actor": who,
        "reason": why,
        "action": action,
        "resource": task_id,
        "approval_id": str(approval_id or "").strip() or None,
        "first_reviewer_id": str(review.get("reviewer_id") or ""),
        "previous_review_status": str(review.get("status") or ""),
        "hitl_proof_verified": True,
        "verified_at": datetime.datetime.now().isoformat(),
    }
    try:
        from backend.audit_log import _require_audit_event

        _require_audit_event(
            "governance",
            "four_eyes_override_verified",
            who,
            {"task_id": task_id, **evidence},
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return evidence


async def run_quality_review(
    task_id: str,
    actor: str,
    deps: ReviewDeps,
) -> Dict[str, Any]:
    """Fuehrt das 4-Augen-Qualitaetsreview ueber den Reviewer-Agenten aus."""

    def _fetch_task_sync() -> Dict[str, Any]:
        conn = deps.get_kanban_connection(maintenance=True)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, title, body, assignee, status, result FROM tasks WHERE id = ?",
                (task_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Task nicht gefunden.")
            return dict(row)
        finally:
            conn.close()

    t_dict = await asyncio.to_thread(_fetch_task_sync)
    title = t_dict.get("title") or "Aufgabe"
    body = t_dict.get("body") or title
    from backend.agent_aliases import resolve_agent_id

    raw_assignee = (t_dict.get("assignee") or "").strip()
    if not raw_assignee:
        raw_assignee = "default"

        def _auto_assign_sync() -> None:
            try:
                c_asgn = deps.get_kanban_connection(maintenance=True)
                try:
                    now_asgn_iso = datetime.datetime.now().isoformat()
                    c_asgn.execute("UPDATE tasks SET assignee = ? WHERE id = ?", (raw_assignee, task_id))
                    c_asgn.execute(
                        "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'auto_assigned_orchestrator', ?, ?)",
                        (
                            task_id,
                            json.dumps(
                                {
                                    "assignee": raw_assignee,
                                    "reason": "Kein Profil gesetzt — automatische Zuweisung an Orchestrator",
                                }
                            ),
                            now_asgn_iso,
                        ),
                    )
                    c_asgn.commit()
                finally:
                    c_asgn.close()
            except Exception as exc:
                print(
                    f"[OperationsAPI] WARNUNG (MEDIUM) trigger_quality_review: Exception im Fehler-/Fallback-Pfad: {exc}",
                    file=sys.stderr,
                )

        await asyncio.to_thread(_auto_assign_sync)
    assignee = resolve_agent_id(raw_assignee)
    result = t_dict.get("result") or ""
    now_iso = datetime.datetime.now().isoformat()

    if not result:
        raise HTTPException(
            status_code=400,
            detail="Aufgabe hat noch kein Arbeitsergebnis zur Prüfung hinterlegt.",
        )

    profiles = await asyncio.to_thread(deps.load_profiles_map)
    if assignee in ("katharina", "katharina-voelk", "katharina_voelk"):
        reviewer_id = "robert"
    else:
        reviewer_id = "katharina"

    prof = profiles.get(reviewer_id, {})
    reviewer_name = prof.get("name") or ("Katharina Völk" if reviewer_id == "katharina" else "Robert")
    reviewer_role = prof.get("category") or prof.get("role") or "Qualitäts- & Compliance-Auditor"

    audit_prompt = f"""Du bist unabhängiger Qualitätsprüfer im 4-Augen-Review-Gate von Archon OS.
Prüfe das vorgelegte Teilergebnis für die folgende Projektaufgabe unbestechlich und sachlich:

TITEL: {title}
BRIEFING / AUFGABENSTELLUNG:
{body}

BEARBEITER: {assignee}
ERGEBNIS ZUR BEWERTUNG:
{result}

PRÜF-KRITERIEN:
1. Vollständigkeit: Wurde der Auftrag vollumfänglich und ohne Auslassungen beantwortet?
2. Substanz & Evidenz: Gibt es Platzhalter, vage Floskeln oder unplausible Annahmen?
3. Handlungsfähigkeit: Enthält das Ergebnis klare, anwendbare nächste Schritte oder konkrete Resultate?

Liefere deine Bewertung AUSSCHLIESSLICH als valides JSON in exakt folgendem Schema (ohne Begleittext, ohne Markdown):
{{
    "verdict": "approved",
    "score": 88,
    "summary": "1-2 prägnante Sätze zur Qualität",
    "critique_points": ["Punkt 1", "Punkt 2"],
    "actionable_next_steps": ["Schritt 1", "Schritt 2"]
}}
(Wähle "changes_requested" als verdict, falls wesentliche Aspekte fehlen oder unvollständig sind, andernfalls "approved".)
"""
    try:
        import core_dispatcher

        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id=reviewer_id,
            agent_name=reviewer_name,
            prompt=audit_prompt,
            role=reviewer_role,
            system_prompt="Du bist ein strikter QM-Auditor. Gib ausschließlich reines JSON ohne Markdown-Ticks aus.",
            model="deepseek/deepseek-chat",
            task_id=task_id,
        )
        content = res.get("content", "").strip()
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            parsed = QualityReviewVerdict.model_validate(json.loads(json_match.group(0)))
        else:
            parsed = QualityReviewVerdict(
                verdict="changes_requested",
                score=0,
                summary="Reviewer-Antwort enthielt kein auswertbares JSON — Review gilt als nicht bestanden, Nachfassung erforderlich.",
                critique_points=["Reviewer-Lauf lieferte keine strukturierte Bewertung."],
                actionable_next_steps=["Review erneut anstoßen."],
            )
    except Exception as e:
        parsed = QualityReviewVerdict(
            verdict="changes_requested",
            score=0,
            summary=f"Reviewer-Prüfung konnte nicht abgeschlossen werden ({e}).",
            critique_points=["Reviewer-Lauf fehlgeschlagen."],
            actionable_next_steps=["Review erneut anstoßen."],
        )

    verdict: str = parsed.verdict
    if verdict not in ("approved", "changes_requested"):
        verdict = "changes_requested"

    review_data: Dict[str, Any] = {
        "status": verdict,
        "reviewer": reviewer_name,
        "reviewer_id": reviewer_id,
        "requested_by": actor,
        "score": parsed.score,
        "summary": parsed.summary,
        "critique_points": parsed.critique_points,
        "actionable_next_steps": parsed.actionable_next_steps,
        "reviewed_at": now_iso,
        "source": "reviewer_agent",
    }

    from backend.kanban_sidecar import update_kanban_meta

    def _apply_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
        meta.setdefault("tasks", {})
        meta["tasks"].setdefault(task_id, {})
        meta["tasks"][task_id]["quality_review"] = review_data
        return meta

    await asyncio.to_thread(update_kanban_meta, _apply_meta)

    def _record_review_sync() -> None:
        c = deps.get_kanban_connection(maintenance=True)
        try:
            c.execute(
                "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                (task_id, f"quality_review_{verdict}", json.dumps(review_data), now_iso),
            )
            if verdict == "approved" and t_dict.get("status") == "review":
                c.execute("UPDATE tasks SET status = 'done', completed_at = ? WHERE id = ?", (now_iso, task_id))
            elif verdict == "changes_requested":
                c.execute("UPDATE tasks SET status = 'review' WHERE id = ?", (task_id,))
            c.commit()
        finally:
            c.close()

    await asyncio.to_thread(_record_review_sync)

    try:
        from backend.audit_log import _require_audit_event

        _require_audit_event(
            "governance",
            "quality_review_completed",
            actor,
            {
                "task_id": task_id,
                "verdict": verdict,
                "reviewer_id": reviewer_id,
                "requested_by": actor,
                "score": parsed.score,
            },
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    try:
        main = get_provider("app_main")
        if hasattr(main, "broadcast_event"):
            main.broadcast_event(
                "kanban_updated",
                {"action": "quality_review", "task_id": task_id, "review": review_data},
            )
            main.broadcast_event(
                "ticker_update",
                {
                    "agent": review_data.get("reviewer", "Reviewer"),
                    "message": f"4-Augen-Review ({verdict.upper()}): {str(review_data.get('summary', ''))[:40]}",
                    "time": datetime.datetime.now().strftime("%H:%M:%S"),
                },
            )
    except Exception as exc:
        print(
            f"[OperationsAPI] Fallback trigger_quality_review: Exception im Fehler-/Fallback-Pfad: {exc}",
            file=sys.stderr,
        )

    return {
        "status": "success",
        "task_id": task_id,
        "quality_review": review_data,
    }


async def run_quality_review_override(
    task_id: str,
    actor: str,
    req: QualityReviewOverrideRequest,
    deps: ReviewDeps,
) -> Dict[str, Any]:
    """H-14-2/F022: einziger erlaubter Weg, ``changes_requested`` aufzuheben."""
    get_review = deps.current_quality_review or (lambda tid: current_quality_review(tid, deps))
    get_created_by = deps.task_created_by or (lambda tid: task_created_by(tid, deps))
    get_status = deps.task_status or (lambda tid: task_status(tid, deps))
    check_four_eyes = deps.require_four_eyes_override or require_four_eyes_override

    review = await asyncio.to_thread(get_review, task_id)
    if not review:
        raise HTTPException(status_code=409, detail="Kein Quality-Review vorhanden — Override nicht zulaessig.")

    created_by = await asyncio.to_thread(get_created_by, task_id)
    old_status = await asyncio.to_thread(get_status, task_id)
    evidence = check_four_eyes(
        task_id=task_id,
        actor=actor,
        review=review,
        reason=req.reason,
        proof_token=req.passkey_proof_token,
        action="quality_review_override",
        created_by=created_by,
        approval_id=req.approval_id,
    )
    now_iso = datetime.datetime.now().isoformat()
    override_review: Dict[str, Any] = {
        "status": "approved",
        "reviewer": actor,
        "reviewer_id": actor,
        "requested_by": review.get("requested_by") or review.get("reviewer_id") or "",
        "score": 100,
        "summary": str(req.reason or "").strip(),
        "critique_points": [],
        "actionable_next_steps": [],
        "reviewed_at": now_iso,
        "source": "four_eyes_override",
        "four_eyes_evidence": evidence,
        "overrides": {
            "previous_status": review.get("status"),
            "previous_reviewer_id": review.get("reviewer_id"),
        },
    }
    from backend.kanban_sidecar import update_kanban_meta

    def _apply_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
        meta.setdefault("tasks", {}).setdefault(task_id, {})["quality_review"] = override_review
        return meta

    await asyncio.to_thread(update_kanban_meta, _apply_meta)

    def _record_sync() -> None:
        c = deps.get_kanban_connection(maintenance=True)
        try:
            c.execute(
                "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                (task_id, "quality_review_override", json.dumps(override_review, ensure_ascii=False), now_iso),
            )
            c.execute(
                "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    task_id,
                    "status_changed",
                    json.dumps(
                        {
                            "from": old_status,
                            "to": "done",
                            "actor": actor,
                            "force": True,
                            "reason": req.reason,
                            "four_eyes_evidence": evidence,
                            "previous_review": review,
                        },
                        ensure_ascii=False,
                    ),
                    now_iso,
                ),
            )
            if old_status == "review":
                c.execute(
                    "UPDATE tasks SET status = 'done', completed_at = ? WHERE id = ? AND status = 'review'",
                    (now_iso, task_id),
                )
            c.commit()
        finally:
            c.close()

    await asyncio.to_thread(_record_sync)
    return {"status": "success", "task_id": task_id, "quality_review": override_review}
