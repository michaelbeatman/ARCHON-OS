"""M70/M74 — Auto-Review-Runde vor Hochrisiko-Freigaben.

``run_auto_review`` ist ein PRE-GATE: Validierungs-Agenten prüfen einen Request,
Belege/Prüfsummen werden über das M68-Interface eingesammelt und am Request
angehängt. Danach erreicht der Request das unveränderte Menschen-Gate.

Harte Invarianten:

* Es gibt KEINEN Auto-Approval-Pfad. Status, Freigabeflags und Entscheidungen
  werden nicht gesetzt; ``no_auto_approval`` ist konstant ``True``.
* Validierungs-Agenten sind PRÜFER, keine Entscheider — auch ein injizierter
  Agent kann hier keine Freigabe erteilen.
* Fehlt M68 (noch nicht gemergt), wird fail-closed gemeldet (Belegpflicht
  unerfüllt); es wird kein Beleg erfunden.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.needs_me_panel import (
    EvidenceRef,
    collect_evidence_refs,
    evaluate_policy_gate,
    sanitize_payload,
    subject_checksum,
)

logger = logging.getLogger("archon.auto_review")


class AutoReviewRequest(BaseModel):
    """Ein Freigabe-Request, der vor das Menschen-Gate gelegt wird."""

    model_config = ConfigDict(extra="ignore")

    request_id: str = Field(min_length=1, max_length=160)
    reference_id: str = ""
    domain: str = "finance"
    title: str = ""
    amount: float = 0.0
    requester_id: str = ""
    tenant_id: str = "default"
    status: str = "pending"
    requires_four_eyes: bool = False
    risk: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class ReviewCheck(BaseModel):
    """Ergebnis eines Validierungs-Agenten (nie eine Freigabeentscheidung)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    detail: str
    evidence: tuple[EvidenceRef, ...] = ()


class AutoReviewResult(BaseModel):
    """Ergebnis der Auto-Review-Runde inkl. angereichertem Request."""

    model_config = ConfigDict(extra="forbid")

    request: dict[str, Any]
    checks: list[ReviewCheck] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    checksum: str = ""
    evidence_required: bool = False
    evidence_complete: bool = False
    complete: bool = False
    ready_for_human_gate: bool = False
    gate_status: Literal["prepared", "blocked"] = "blocked"
    blocking_reasons: list[str] = Field(default_factory=list)
    no_auto_approval: Literal[True] = True
    reviewed_at: str = ""


Validator = Callable[[Mapping[str, Any]], ReviewCheck]
AttachCallback = Callable[[Mapping[str, Any]], Any]


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _coerce_request(request: Any) -> AutoReviewRequest:
    """Akzeptiert Dict, Pydantic-Modell oder floats-fähige Mappings."""
    if isinstance(request, AutoReviewRequest):
        return request
    if isinstance(request, Mapping):
        return AutoReviewRequest.model_validate(dict(request))
    dump = getattr(request, "model_dump", None)
    if callable(dump):
        return AutoReviewRequest.model_validate(dump())
    raise TypeError("run_auto_review erwartet einen Request (Mapping oder Pydantic-Modell).")


def _risk_of(req: AutoReviewRequest, policy: Mapping[str, Any]) -> str:
    candidate = str(req.risk or policy.get("risk") or policy.get("risk_level") or "").lower()
    if candidate in ("high", "critical", "hoch"):
        return "high"
    if candidate in ("low", "niedrig"):
        return "low"
    return "medium"


def _default_validators() -> list[Validator]:
    """Deterministische Offline-Validatoren (kein LLM, keine Entscheidung)."""

    def belegpflicht(context: Mapping[str, Any]) -> ReviewCheck:
        required = bool(context.get("evidence_required"))
        refs = tuple(context.get("evidence") or ())
        echte = tuple(ref for ref in refs if isinstance(ref, EvidenceRef) and ref.kind != "subject_digest")
        if required and (not echte or not all(ref.checksum for ref in echte)):
            return ReviewCheck(
                name="belegpflicht",
                passed=False,
                detail="Belegpflicht nicht erfüllt: M68-Beleg mit Prüfsumme fehlt.",
                evidence=echte,
            )
        return ReviewCheck(name="belegpflicht", passed=True, detail="Beleglage geprüft.", evidence=echte)

    def pruefsumme(context: Mapping[str, Any]) -> ReviewCheck:
        checksum = str(context.get("checksum") or "")
        passed = checksum.startswith("sha256:") and len(checksum) == len("sha256:") + 64
        return ReviewCheck(
            name="pruefsumme",
            passed=passed,
            detail="Deterministische Prüfsumme bereitgestellt." if passed else "Prüfsumme fehlt.",
        )

    def mensch_gate(context: Mapping[str, Any]) -> ReviewCheck:
        request = dict(context.get("request") or {})
        status = str(request.get("status") or "").lower()
        blocked = status in ("approved", "rejected", "auto_approved")
        return ReviewCheck(
            name="mensch_gate",
            passed=not blocked,
            detail=(
                "Menschen-Gate bleibt unverändert; kein Auto-Approval."
                if not blocked
                else "Request weist bereits eine Entscheidung auf — Review abgebrochen."
            ),
        )

    def vier_augen(context: Mapping[str, Any]) -> ReviewCheck:
        request = dict(context.get("request") or {})
        requester = str(request.get("requester_id") or "")
        payload_raw = request.get("payload")
        payload: Mapping[str, Any] = payload_raw if isinstance(payload_raw, Mapping) else {}
        candidate = str(payload.get("approver_id") or payload.get("approved_by") or "")
        conflict = bool(candidate and requester and candidate.strip().lower() == requester.strip().lower())
        return ReviewCheck(
            name="vier_augen",
            passed=not conflict,
            detail=(
                "Keine Self-Approval-Spur im Payload."
                if not conflict
                else "Vier-Augen-Konflikt: Antragsteller als Genehmiger im Payload."
            ),
        )

    def payload_hygiene(context: Mapping[str, Any]) -> ReviewCheck:
        return ReviewCheck(
            name="payload_hygiene",
            passed=True,
            detail="Payload auf erlaubte Felder reduziert; keine Secrets im Review-Ergebnis.",
        )

    return [belegpflicht, pruefsumme, mensch_gate, vier_augen, payload_hygiene]


def run_auto_review(
    request: Any,
    *,
    validators: Sequence[Validator] | None = None,
    evidence_provider: Callable[..., Any] | None = None,
    policy_evaluator: Callable[..., Any] | None = None,
    attach: AttachCallback | None = None,
    now: dt.datetime | None = None,
) -> AutoReviewResult:
    """Sammelt Belege, führt Prüfer aus und hängt das Ergebnis an den Request.

    ``attach`` ist der Verdrahtungspunkt für den Integrator (z. B. Persistenz im
    Pending-Store). Ohne ``attach`` wird NUR eine kopierte Request-Dictionary
    zurückgegeben — der Originalstatus bleibt unberührt.
    """
    req = _coerce_request(request)
    timestamp = now or _utcnow()
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=dt.timezone.utc)

    safe_payload = sanitize_payload(req.payload)
    subject: dict[str, Any] = {
        "request_id": req.request_id,
        "reference_id": req.reference_id or req.request_id,
        "domain": req.domain,
        "tenant_id": req.tenant_id,
        "title": req.title,
        "payload": safe_payload,
    }
    policy = evaluate_policy_gate(subject, evaluator=policy_evaluator)
    risk = _risk_of(req, policy)
    evidence_required = bool(
        risk == "high" or req.requires_four_eyes or policy.get("evidence_required", False)
    )
    evidence = tuple(collect_evidence_refs(subject, provider=evidence_provider))
    checksum = subject_checksum(subject)
    echte = tuple(ref for ref in evidence if ref.kind != "subject_digest")
    evidence_complete = (not evidence_required) or (
        bool(echte) and all(bool(ref.checksum) for ref in echte)
    )

    context: dict[str, Any] = {
        "request": req.model_dump(),
        "evidence": evidence,
        "checksum": checksum,
        "evidence_required": evidence_required,
        "evidence_complete": evidence_complete,
        "risk": risk,
        "policy": policy,
    }
    checks: list[ReviewCheck] = []
    for validator in (validators if validators is not None else _default_validators()):
        try:
            check = validator(context)
            if not isinstance(check, ReviewCheck):
                raise TypeError("Validator lieferte keinen ReviewCheck.")
        except Exception as exc:
            # Fehler im Prüfer = fail-closed, niemals „bestanden“.
            logger.warning("[AutoReview] Validator fehlgeschlagen: %s", exc)
            check = ReviewCheck(name="validator_error", passed=False, detail=str(exc)[:300])
        checks.append(check)

    blocking = [f"{check.name}: {check.detail}" for check in checks if not check.passed]
    complete = not blocking
    enriched: dict[str, Any] = req.model_dump()
    enriched["payload"] = safe_payload
    enriched["human_gate_required"] = True
    enriched["status"] = req.status  # explizit KEIN Statuswechsel
    enriched["auto_review"] = {
        "checksum": checksum,
        "evidence_required": evidence_required,
        "evidence_complete": evidence_complete,
        "evidence": [ref.model_dump() for ref in evidence],
        "checks": [check.model_dump(mode="json") for check in checks],
        "complete": complete,
        "no_auto_approval": True,
        "reviewed_at": timestamp.isoformat(),
    }

    if attach is not None:
        try:
            attach(enriched)
        except Exception as exc:
            logger.warning("[AutoReview] Anhang am Request fehlgeschlagen: %s", exc)
            blocking.append(f"attach: {str(exc)[:300]}")
            complete = False
            enriched["auto_review"]["complete"] = False
            enriched["auto_review"]["attach_failed"] = True

    ready = complete and evidence_complete
    return AutoReviewResult(
        request=enriched,
        checks=checks,
        evidence=list(evidence),
        checksum=checksum,
        evidence_required=evidence_required,
        evidence_complete=evidence_complete,
        complete=complete,
        ready_for_human_gate=ready,
        gate_status="prepared" if ready else "blocked",
        blocking_reasons=blocking,
        reviewed_at=timestamp.isoformat(),
    )
