"""M70/M74 — Tests für „Braucht mich“, Auto-Review, Vertretung, SSE und RBAC.

Alle Providers werden injiziert: die Tests berühren keine echte Datenbank und
keinen Freigabestatus. Die Invarianten (kein Auto-Approval, kein Agent-Fallback)
werden direkt gegen die Ergebnisse geprüft.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pytest
from fastapi import HTTPException

from archon.routers import needs_me as needs_me_router
from backend.auto_review import AutoReviewRequest, ReviewCheck, run_auto_review
from backend.needs_me_panel import (
    GATE_KINDS,
    NEEDS_ME_SSE_EVENT,
    UNIFIED_REQUIRED_FIELDS,
    collect_needs_me,
)

NOW = dt.datetime(2026, 11, 27, 12, 0, tzinfo=dt.timezone.utc)
PAST = (NOW - dt.timedelta(hours=3)).isoformat()
FUTURE = (NOW + dt.timedelta(hours=2)).isoformat()


def beleg(subject: Any) -> list[dict[str, str]]:
    """M68-Fake: gültiger Beleg mit Prüfsumme."""
    return [
        {
            "kind": "invoice",
            "reference": f"beleg:{subject.get('request_id', 'unknown')}",
            "checksum": "sha256:" + "a" * 64,
            "captured_at": NOW.isoformat(),
        }
    ]


def policy(subject: Any) -> dict[str, Any]:
    """M69-Fake: nur Gate-Metadaten, KEINE Freigabeentscheidung."""
    return {"risk": "high", "requires_four_eyes": True, "evidence_required": True}


def deputy(owner: str, **_: Any) -> dict[str, Any]:
    """M95-Fake: gültiger menschlicher Stellvertreter."""
    return {
        "resolved": True,
        "status": "escalated",
        "deputy": {"username": "carol", "id": "usr_carol", "role": "operator"},
        "reason": "Eskaliert an menschlichen Stellvertreter carol.",
    }


def blocked_deputy(owner: str, **_: Any) -> dict[str, Any]:
    """M95-Fake: fail-closed gesperrte Vertretung."""
    return {
        "resolved": False,
        "status": "escalated_blocked",
        "deputy": None,
        "reason": "Kein menschlicher Stellvertreter (fail-closed).",
    }


def agent_deputy(owner: str, **_: Any) -> dict[str, Any]:
    """Böswilliger Fake: Agent als Stellvertreter muss blockiert werden."""
    return {
        "resolved": True,
        "status": "escalated",
        "deputy": {"username": "agent:finance_lead"},
        "reason": "Agent-Fallback-Versuch.",
    }


def policy_row(requester: str = "bob", owner: str = "alice") -> dict[str, Any]:
    return {
        "id": "REQ-1",
        "reference_id": "REQ-1",
        "title": "Lieferantenzahlung 800 EUR",
        "status": "pending",
        "domain": "finance",
        "requester_id": requester,
        "assigned_approver": owner,
        "requires_four_eyes": True,
        "created_at": PAST,
        "expires_at": FUTURE,
        "payload": {"amount": 800.0, "api_key": "nie-im-response"},
    }


def mcp_row() -> dict[str, Any]:
    return {
        "id": "REQ-2",
        "reference_id": "mcp:key-1",
        "title": "MCP Tool-Aufruf: ask_specialist",
        "status": "pending",
        "domain": "agent_dispatch",
        "requester_id": "bob",
        "assigned_approver": "alice",
        "created_at": PAST,
        "expires_at": FUTURE,
        "payload": {"tool": "archon__ask_specialist", "password": "nie-im-response"},
    }


def mission_row() -> dict[str, Any]:
    return {
        "id": "mc-1",
        "title": "Mission freigeben",
        "status": "approval",
        "domain": "system",
        "assignee": "alice",
        "created_by": "bob",
        "created_at": PAST,
        "hitl_required": True,
        "source": "mission_control",
    }


def question_row() -> dict[str, Any]:
    return {
        "id": "handoff-1",
        "task_id": "task-1",
        "from_agent": "agent:researcher",
        "to_agent": "alice",
        "acceptance_criteria": "Rueckfrage beantworten",
        "status": "pending_acceptance",
        "created_at": PAST,
        "source": "agent_handoffs",
    }


def abort_row() -> dict[str, Any]:
    return {
        "id": "abort:workflow-1:0",
        "scope": "workflow-1",
        "reason": "Abbruch nicht bestätigt",
        "source": "cancellation",
    }


def bundled(actor: str = "alice", **overrides: Any) -> Any:
    """Bündel mit allen fünf Quellen, M68/M69/M95 injiziert."""
    kwargs: dict[str, Any] = {
        "approval_provider": lambda tenant: [policy_row(), mcp_row()],
        "mission_provider": lambda tenant: [mission_row()],
        "question_provider": lambda tenant: [question_row()],
        "abort_provider": lambda tenant: [abort_row()],
        "evidence_provider": beleg,
        "policy_evaluator": policy,
        "escalation_resolver": deputy,
        "now": NOW,
    }
    kwargs.update(overrides)
    return collect_needs_me(actor, "default", **kwargs)


# ---------------------------------------------------------------------------
# 1. Bündelung über alle Gate-Typen + einheitliche Pflichtfelder
# ---------------------------------------------------------------------------


def test_buendelt_alle_gate_typen_mit_einheitlichen_pflichtfeldern() -> None:
    bundle = bundled()

    assert {item.kind for item in bundle.items} == set(GATE_KINDS)
    assert bundle.total == 5
    assert bundle.counts["policy"] == 1
    assert bundle.counts["mcp_hitl"] == 1
    assert bundle.counts["mission"] == 1
    assert bundle.counts["agent_question"] == 1
    assert bundle.counts["unsafe_abort"] == 1
    for item in bundle.items:
        assert set(UNIFIED_REQUIRED_FIELDS).issubset(set(item.required_fields))
        assert item.missing_fields == ()
        assert item.decision_fields
        assert item.auto_approval is False
    assert bundle.invariants == {"no_auto_approval": True, "no_agent_fallback": True}


def test_policy_evaluator_darf_nicht_freigeben() -> None:
    bundle = bundled(
        policy_evaluator=lambda subject: {"approve": True, "approved": True, "status": "approved"}
    )
    assert all(item.status != "approved" for item in bundle.items)
    assert all(item.auto_approval is False for item in bundle.items)
    dumped = bundle.model_dump()
    assert "approve" not in dumped
    assert "approved" not in dumped


def test_tenant_filter_trennt_gates() -> None:
    fremd = dict(policy_row(), tenant_id="andere-firma")
    bundle = bundled(approval_provider=lambda tenant: [fremd])
    assert bundle.total == 3  # Mission/Rückfrage/Abbruch sind systemweit


# ---------------------------------------------------------------------------
# 2. Vier-Augen + M95-Vertretung
# ---------------------------------------------------------------------------


def test_vier_augen_sperrt_antragsteller_und_deputy_wird_beruecksichtigt() -> None:
    als_antragsteller = bundled(
        actor="bob", approval_provider=lambda tenant: [policy_row(requester="bob")]
    )
    policy_item = next(i for i in als_antragsteller.items if i.kind == "policy")
    assert policy_item.may_decide is False
    assert any("Vier-Augen" in reason for reason in policy_item.blocking_reasons)

    als_deputy = bundled(
        actor="carol", approval_provider=lambda tenant: [policy_row(requester="bob")]
    )
    policy_item = next(i for i in als_deputy.items if i.kind == "policy")
    assert policy_item.needs_you is True
    assert policy_item.may_decide is True
    assert policy_item.escalation.target == "carol"


def test_gesperrte_vertretung_blockt_fail_closed() -> None:
    bundle = bundled(actor="carol", escalation_resolver=blocked_deputy)
    policy_item = next(i for i in bundle.items if i.kind == "policy")
    assert policy_item.escalation.status == "escalated_blocked"
    assert policy_item.may_decide is False


# ---------------------------------------------------------------------------
# 3. Eskalations-Timeouts
# ---------------------------------------------------------------------------


def test_timeout_wird_berechnet_und_als_overdue_markiert() -> None:
    bundle = bundled(timeout_hours=1)
    policy_item = next(i for i in bundle.items if i.kind == "policy")
    # explizites expires_at in der Zukunft -> nicht überfällig
    assert policy_item.overdue is False

    ohne_frist = dict(policy_row())
    ohne_frist.pop("expires_at")
    bundle = bundled(
        timeout_hours=1,
        approval_provider=lambda tenant: [ohne_frist],
    )
    policy_item = next(i for i in bundle.items if i.kind == "policy")
    assert policy_item.overdue is True
    assert policy_item.timeout_at == (NOW - dt.timedelta(hours=2)).isoformat()


# ---------------------------------------------------------------------------
# 4. Belegpflicht / Auto-Review
# ---------------------------------------------------------------------------


def test_auto_review_sammelt_belege_und_haengt_sie_an_den_request() -> None:
    req = AutoReviewRequest(
        request_id="REQ-1",
        domain="finance",
        risk="high",
        requester_id="bob",
        payload={"tool": "demo", "api_key": "nie-im-response"},
    )
    result = run_auto_review(req, evidence_provider=beleg, now=NOW)

    assert result.ready_for_human_gate is True
    assert result.gate_status == "prepared"
    assert result.checksum.startswith("sha256:")
    assert result.evidence_complete is True
    assert result.request["status"] == "pending"
    assert result.request["human_gate_required"] is True
    assert result.request["auto_review"]["evidence"]
    assert result.no_auto_approval is True
    serialized = json.dumps(result.model_dump())
    assert "nie-im-response" not in serialized


def test_auto_review_ohne_beleg_blockt_high_risk() -> None:
    req = AutoReviewRequest(request_id="REQ-2", domain="finance", risk="high")
    result = run_auto_review(req, evidence_provider=lambda subject: [], now=NOW)

    assert result.evidence_required is True
    assert result.evidence_complete is False
    assert result.ready_for_human_gate is False
    assert result.gate_status == "blocked"
    assert any("Beleg" in reason for reason in result.blocking_reasons)


def test_attach_fehler_faehrt_zum_fail_closed() -> None:
    def kaputt(request: Any) -> None:
        raise RuntimeError("Store nicht erreichbar")

    result = run_auto_review(
        AutoReviewRequest(request_id="REQ-3", risk="high"),
        evidence_provider=beleg,
        attach=kaputt,
        now=NOW,
    )
    assert result.ready_for_human_gate is False
    assert result.request["auto_review"]["attach_failed"] is True


# ---------------------------------------------------------------------------
# 5. Kein Agent-Fallback
# ---------------------------------------------------------------------------


def test_agent_actor_und_agent_deputy_werden_nie_entscheider() -> None:
    bundle = bundled(actor="agent:default", escalation_resolver=agent_deputy)
    assert bundle.actor_is_human is False
    assert bundle.requires_action == 0
    assert all(item.needs_you is False and item.may_decide is False for item in bundle.items)
    policy_item = next(i for i in bundle.items if i.kind == "policy")
    assert policy_item.escalation.status == "escalated_blocked"
    assert policy_item.escalation.target is None


def test_validatoren_sind_pruefer_keine_genehmiger() -> None:
    result = run_auto_review(
        AutoReviewRequest(request_id="REQ-4", risk="high"),
        validators=[lambda context: ReviewCheck(name="fake", passed=True, detail="ok")],
        evidence_provider=beleg,
        now=NOW,
    )
    assert result.complete is True
    assert result.request["status"] == "pending"
    assert "approved_by" not in result.request
    assert result.no_auto_approval is True


# ---------------------------------------------------------------------------
# 6. SSE-Payload
# ---------------------------------------------------------------------------


def test_refresh_sendet_nur_zaehler_im_sse_event(monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = bundled()
    events: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setitem(needs_me_router._DEPS, "collect", lambda actor, tenant: bundle)
    monkeypatch.setitem(
        needs_me_router._DEPS,
        "get_current_user",
        lambda request: {"username": "alice", "role": "admin"},
    )
    monkeypatch.setitem(
        needs_me_router._DEPS,
        "emit_event",
        lambda event_type, data: events.append((event_type, dict(data))),
    )

    response = needs_me_router.api_refresh_needs_me(object(), "default")  # type: ignore[arg-type]

    assert response["status"] == "success"
    assert events[0][0] == NEEDS_ME_SSE_EVENT
    assert set(events[0][1]) == {"type", "total", "requires_action", "counts", "generated_at"}
    assert events[0][1]["total"] == 5
    assert "title" not in events[0][1]
    assert "payload" not in events[0][1]


# ---------------------------------------------------------------------------
# 7. RBAC 403/200
# ---------------------------------------------------------------------------


def test_rbac_viewer_service_und_agent_werden_abgewiesen(monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = bundled()
    monkeypatch.setitem(needs_me_router._DEPS, "collect", lambda actor, tenant: bundle)
    for user in (
        {"username": "vic", "role": "viewer"},
        {"username": "service", "role": "admin", "is_service": True},
        {"username": "agent:default", "role": "admin"},
    ):
        monkeypatch.setitem(needs_me_router._DEPS, "get_current_user", lambda request, u=user: u)
        with pytest.raises(HTTPException) as exc:
            needs_me_router.api_get_needs_me(object(), "default")  # type: ignore[arg-type]
        assert exc.value.status_code == 403


@pytest.mark.parametrize("role", ["admin", "operator"])
def test_rbac_admin_und_operator_erhalten_buendel_200(
    monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    bundle = bundled()
    monkeypatch.setitem(needs_me_router._DEPS, "collect", lambda actor, tenant: bundle)
    monkeypatch.setitem(
        needs_me_router._DEPS,
        "get_current_user",
        lambda request, r=role: {"username": "alice", "role": r},
    )

    response = needs_me_router.api_get_needs_me(object(), "default")  # type: ignore[arg-type]

    assert response["status"] == "success"
    assert response["bundle"]["total"] == 5
    assert response["bundle"]["invariants"]["no_auto_approval"] is True
