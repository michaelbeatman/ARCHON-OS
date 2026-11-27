"""M70/M74 — einheitliches „Braucht mich“-Panel (read-only Bündelung).

Dieses Modul bündelt OFFENE Freigaben und Rückfragen aus vier Quellen:

* Missions-Gates (Mission-Control-Tasks in Approval/Review/Blocked),
* Policy-Gates (M69 ``evaluate_policy_gate`` + Freigabeanfragen),
* MCP-HITL-Gates (Freigabeanfragen mit ``mcp:``-Referenz),
* Agentenrückfragen (noch nicht quittierte, an Menschen adressierte Handoffs) und
* unsichere Abbrüche (fehlgeschlagene Cancels / fail-closed eskalierte Anfragen).

Harte Invarianten:

* NIEMALS Auto-Approval — dieses Modul hat keinen Schreibpfad und verändert
  keinen Freigabestatus. ``auto_approval`` ist konstant ``False``.
* NIEMALS Agent-Fallback — Agenten-/Systemidentitäten werden nie als
  Entscheider, Stellvertreter oder Eskalationsziel akzeptiert (M95-Logik).
* Bekannte Interface-Verträge werden per Dependency Injection hereingenommen.
  Fehlt ein noch nicht gemergtes Modul (M68/M69), greift ein deterministischer,
  fail-closed Fallback — nie ein stilles „Alles ok“.

Alle externen Daten werden als ``Mapping`` behandelt und in Pydantic-Modelle
überführt; Secrets aus Payloads werden vor der Weitergabe entfernt.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import inspect
import json
import logging
import re
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("archon.needs_me_panel")

NEEDS_ME_SSE_EVENT = "needs_me_updated"

GATE_KINDS: tuple[str, ...] = (
    "mission",
    "policy",
    "mcp_hitl",
    "agent_question",
    "unsafe_abort",
)

# Domains mit grundsätzlich hohem Risiko: hier sind Belege + Prüfsummen vor
# jeder menschlichen Freigabe zwingend (M68-Interface).
HIGH_RISK_DOMAINS: frozenset[str] = frozenset(
    {
        "system",
        "governance",
        "boardroom",
        "workflow_authoring",
        "agent_dispatch",
        "context_hygiene",
        "finance",
    }
)

DEFAULT_TIMEOUT_HOURS = 24
OPEN_APPROVAL_STATUSES: frozenset[str] = frozenset(
    {"pending", "escalated", "escalated_blocked", "waiting", "awaiting_review", "in_review"}
)
OPEN_MISSION_STATUSES: frozenset[str] = frozenset(
    {"approval", "waiting_approval", "review", "gate", "blocked"}
)

# Einheitliche Pflichtfelder: jede Quelle muss diese Felder liefern, sonst wird
# das Element als unvollständig markiert (fail-closed, nie still ergänzt).
UNIFIED_REQUIRED_FIELDS: tuple[str, ...] = (
    "id",
    "kind",
    "title",
    "source",
    "reference_id",
    "status",
    "domain",
    "tenant_id",
    "requested_by",
    "assigned_to",
    "created_at",
    "timeout_at",
    "risk",
)
DECISION_FIELDS: dict[str, tuple[str, ...]] = {
    "mission": ("entscheidung", "begruendung"),
    "policy": ("begruendung",),
    "mcp_hitl": ("begruendung",),
    "agent_question": ("antwort",),
    "unsafe_abort": ("entscheidung", "begruendung"),
}

_SECRET_MARKERS = ("token", "password", "secret", "credential", "api_key", "apikey", "authorization")
_SAFE_PAYLOAD_KEYS = (
    "tool",
    "domain",
    "reference_id",
    "title",
    "amount",
    "currency",
    "requester_id",
    "_requester_id",
    "first_approver",
    "requires_four_eyes",
    "question",
    "agent_question",
    "abort_reason",
    "_unsafe_abort",
    "tenant_id",
)


# ---------------------------------------------------------------------------
# Typen
# ---------------------------------------------------------------------------


class EvidenceRef(BaseModel):
    """Beleg + Prüfsumme; niemals Rohdaten eines Payloads."""

    model_config = ConfigDict(extra="forbid")

    kind: str = "beleg"
    reference: str
    checksum: str = ""
    captured_at: str = ""


class EscalationInfo(BaseModel):
    """Ergebnis der M95-Vertretungslogik (read-only)."""

    model_config = ConfigDict(extra="forbid")

    owner: str = ""
    resolved: bool = False
    target: str | None = None
    status: str = "not_required"
    reason: str = ""


class NeedsMeItem(BaseModel):
    """Ein einheitliches Element des „Braucht mich“-Panels."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["mission", "policy", "mcp_hitl", "agent_question", "unsafe_abort"]
    title: str
    domain: str
    tenant_id: str
    source: str
    reference_id: str
    status: str
    requested_by: str
    assigned_to: str
    created_at: str
    timeout_at: str
    overdue: bool = False
    risk: Literal["low", "medium", "high"] = "medium"
    required_fields: tuple[str, ...] = UNIFIED_REQUIRED_FIELDS
    missing_fields: tuple[str, ...] = ()
    decision_fields: tuple[str, ...] = ()
    evidence_required: bool = False
    evidence: tuple[EvidenceRef, ...] = ()
    evidence_complete: bool = True
    escalation: EscalationInfo = Field(default_factory=EscalationInfo)
    requires_four_eyes: bool = False
    needs_you: bool = False
    may_decide: bool = False
    blocking_reasons: tuple[str, ...] = ()
    # Invariante: dieses Panel hat keinen Freigabepfad.
    auto_approval: Literal[False] = False


class NeedsMeBundle(BaseModel):
    """Aggregat aller offenen Gates für einen Actor/Tenant."""

    model_config = ConfigDict(extra="forbid")

    actor: str
    tenant: str
    actor_is_human: bool
    generated_at: str
    items: list[NeedsMeItem] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    total: int = 0
    requires_action: int = 0
    timeout_policy_hours: int = DEFAULT_TIMEOUT_HOURS
    invariants: dict[str, bool] = Field(
        default_factory=lambda: {"no_auto_approval": True, "no_agent_fallback": True}
    )


# ---------------------------------------------------------------------------
# Kleine, deterministische Hilfsfunktionen
# ---------------------------------------------------------------------------


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat()


def _parse_dt(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _text(value: Any, limit: int = 300) -> str:
    """Steuerzeichen entfernen und Länge begrenzen (kein Log-/UI-Overflow)."""
    raw = re.sub(r"[\x00-\x1f\x7f]", " ", str(value if value is not None else ""))
    return " ".join(raw.split())[:limit]


def _is_agent_identity(value: Any) -> bool:
    """M95-Identitätsprüfung mit lokalem Fallback (Modul noch nicht gemergt?)."""
    try:
        from backend.approval_policy_engine import is_agent_or_system_identity

        return bool(is_agent_or_system_identity(str(value or "")))
    except Exception as exc:  # pragma: no cover - nur bei fehlender M95-Abhängigkeit
        logger.debug("[NeedsMe] M95-Identitaetspruefung nicht verfuegbar: %s", exc)
    clean = str(value or "").strip().lower()
    if not clean:
        return True
    forbidden = {
        "system",
        "agent",
        "default",
        "system_watchdog",
        "hermes",
        "archon",
        "auto",
        "bot",
        "ai",
        "llm",
        "assistant",
    }
    prefixes = ("agent:", "agent_", "bot:", "bot_", "sys:", "system:", "ai:", "auto:")
    return clean in forbidden or clean.startswith(prefixes)


def _identity_tokens(value: Any) -> set[str]:
    """Identitäts-Tokens inkl. Stellvertretungs-Suffix („alice (i.V. Bob)“)."""
    raw = str(value or "").strip().lower()
    if not raw:
        return set()
    tokens = {raw}
    if " (i.v. " in raw:
        principal, deputy = raw.split(" (i.v. ", 1)
        tokens.add(principal.strip())
        tokens.add(deputy.rstrip(")").strip())
    else:
        tokens.add(raw.split(" ")[0])
    return {token for token in tokens if token}


def _same_identity(left: Any, right: Any) -> bool:
    a, b = _identity_tokens(left), _identity_tokens(right)
    return bool(a and b and a & b)


def _sanitize_tenant(value: Any) -> str:
    try:
        from backend.tenant_context import sanitize_tenant_id

        return str(sanitize_tenant_id(str(value or "")) or "")
    except Exception:  # pragma: no cover - Fallback ohne Tenant-Modul
        return re.sub(r"[^a-zA-Z0-9_-]", "_", str(value or "").strip())[:64]


def _tenant_matches(item_tenant: str, requested_tenant: str) -> bool:
    if not item_tenant:
        return True  # systemweite Gates sind für jeden Tenant sichtbar
    return _sanitize_tenant(item_tenant) == _sanitize_tenant(requested_tenant)


def _safe_payload(raw: Any) -> dict[str, Any]:
    """Nur explizit erlaubte, unkritische Schlüssel weiterreichen."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return {}
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key, value in raw.items():
        name = str(key)
        lowered = name.lower()
        if any(marker in lowered for marker in _SECRET_MARKERS):
            continue
        if name in _SAFE_PAYLOAD_KEYS:
            result[name] = value
    return result


def _checksum(subject: Mapping[str, Any]) -> str:
    """Deterministische Prüfsumme über kanonisierte, bereinigte Subject-Daten."""
    canonical = json.dumps(
        {k: str(subject.get(k, ""))[:200] for k in sorted(subject)},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def sanitize_payload(raw: Any) -> dict[str, Any]:
    """Öffentlicher Wrapper: nur unkritische Payload-Schlüssel weitergeben."""
    return _safe_payload(raw)


def subject_checksum(subject: Mapping[str, Any]) -> str:
    """Öffentlicher Wrapper für die deterministische Subject-Prüfsumme."""
    return _checksum(subject)


def is_agent_identity(value: Any) -> bool:
    """Öffentlicher Wrapper: Agent-/Systemidentität nie als Mensch behandeln."""
    return _is_agent_identity(value)


def same_identity(left: Any, right: Any) -> bool:
    """Öffentlicher Wrapper für die Identitätsprüfung inkl. Vertretungssuffix."""
    return _same_identity(left, right)


def normalize_escalation(
    raw: Mapping[str, Any], *, owner: str, requester_id: str, first_approver: str
) -> EscalationInfo:
    """Öffentlicher Wrapper: M95-Eskalationsergebnis validieren."""
    return _normalize_escalation(
        raw, owner=owner, requester_id=requester_id, first_approver=first_approver
    )


def _coerce_evidence(raw: Any) -> list[EvidenceRef]:
    """M68-Ergebnisse in die einheitliche Belegform bringen (ohne Secrets)."""
    if isinstance(raw, Mapping) and "evidence" in raw:
        raw = raw.get("evidence")
    elif isinstance(raw, Mapping) and "belege" in raw:
        raw = raw.get("belege")
    if isinstance(raw, Mapping):
        raw = list(raw.values())
    if not isinstance(raw, (list, tuple)):
        return []
    refs: list[EvidenceRef] = []
    for entry in raw:
        if isinstance(entry, EvidenceRef):
            refs.append(entry)
            continue
        if not isinstance(entry, Mapping):
            continue
        candidate: dict[str, Any] = {}
        for key, value in entry.items():
            name = str(key).lower()
            if any(marker in name for marker in _SECRET_MARKERS):
                continue
            if name in ("type", "kind", "beleg_typ"):
                candidate["kind"] = _text(value, 80) or "beleg"
            elif name in ("reference", "reference_id", "path", "file", "name", "beleg_id"):
                candidate["reference"] = _text(value, 200)
            elif name in ("checksum", "sha256", "hash", "digest", "pruefsumme"):
                candidate["checksum"] = _text(value, 200)
            elif name in ("captured_at", "timestamp", "created_at"):
                candidate["captured_at"] = _text(value, 60)
        reference = str(candidate.get("reference") or "")
        checksum = str(candidate.get("checksum") or "")
        if not reference and not checksum:
            continue
        refs.append(
            EvidenceRef(
                kind=str(candidate.get("kind") or "beleg"),
                reference=reference or checksum[:32],
                checksum=checksum,
                captured_at=str(candidate.get("captured_at") or ""),
            )
        )
    return refs


def _call_adapter(fn: Callable[..., Any], subject: Mapping[str, Any]) -> Any:
    """Argumente an das tatsächliche Interface anpassen (DI-Verträge M68/M69)."""
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return fn(subject)
    kwargs: dict[str, Any] = {}
    for name, param in signature.parameters.items():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        if name in subject:
            kwargs[name] = subject[name]
    if kwargs:
        try:
            return fn(**kwargs)
        except TypeError:
            # Interface mit abweichender Signatur: Subject als Ganzes übergeben.
            return fn(subject)
    return fn(subject)


M68_CANDIDATES: tuple[str, ...] = (
    "collect_evidence",
    "collect_compliance_evidence",
    "gather_evidence",
    "build_evidence_bundle",
)


def collect_evidence_refs(
    subject: Mapping[str, Any], *, provider: Callable[..., Any] | None = None
) -> list[EvidenceRef]:
    """Belege/Prüfsummen über M68 sammeln; Fallback ohne Modul: leer (fail-closed).

    Der Fallback erfindet KEINE Belege. Erzeugt wird höchstens eine lokale
    Prüfsumme über das (bereinigte) Subject, damit der Pre-Gate bewertbar bleibt.
    """
    chosen = provider
    if chosen is None:
        try:
            import backend.compliance_inventory as inventory

            for name in M68_CANDIDATES:
                candidate = getattr(inventory, name, None)
                if callable(candidate):
                    chosen = candidate
                    break
        except Exception as exc:  # M68 noch nicht gemergt
            logger.debug("[NeedsMe] M68-Belegmodul nicht verfuegbar: %s", exc)
    raw: Any = None
    if chosen is not None:
        try:
            raw = _call_adapter(chosen, subject)
        except Exception as exc:
            logger.warning("[NeedsMe] M68-Belegabruf fehlgeschlagen: %s", exc)
            raw = None
    refs = _coerce_evidence(raw)
    if not refs:
        # Keine fremden Belege vorhanden: nur die lokale Subject-Prüfsumme
        # anhängen. Sie ist kein Beleg, daher bleibt checksum-tragend, aber
        # `kind="subject_digest"` — ein Mensch muss den echten Beleg liefern.
        refs.append(
            EvidenceRef(
                kind="subject_digest",
                reference=_text(subject.get("reference_id") or subject.get("request_id") or "subject", 120),
                checksum=_checksum(subject),
            )
        )
    return refs


M69_CANDIDATES: tuple[str, ...] = ("evaluate_policy_gate",)


def evaluate_policy_gate(
    subject: Mapping[str, Any], *, evaluator: Callable[..., Any] | None = None
) -> dict[str, Any]:
    """M69-Policy-Gate auswerten; nur freigegebene Felder übernehmen.

    Eine Antwort wie ``{"approve": True}`` wird bewusst IOGNORIERT: ein
    Policy-Gate darf niemals die menschliche Freigabe ersetzen.
    """
    chosen = evaluator
    if chosen is None:
        try:
            import backend.policy_gates as gates

            for name in M69_CANDIDATES:
                candidate = getattr(gates, name, None)
                if callable(candidate):
                    chosen = candidate
                    break
        except Exception as exc:  # M69 noch nicht gemergt
            logger.debug("[NeedsMe] M69-Policy-Gate nicht verfuegbar: %s", exc)
    raw: Any = {}
    if chosen is not None:
        try:
            result = _call_adapter(chosen, subject)
            if isinstance(result, Mapping):
                raw = dict(result)
        except Exception as exc:
            logger.warning("[NeedsMe] M69-Policy-Gate nicht auswertbar: %s", exc)
    allowed = (
        "risk",
        "risk_level",
        "required_fields",
        "evidence_required",
        "timeout_hours",
        "requires_four_eyes",
        "policy_key",
        "gate",
    )
    return {key: raw[key] for key in allowed if key in raw}


# ---------------------------------------------------------------------------
# Standard-Provider (read-only SQLite; keine Statusänderungen)
# ---------------------------------------------------------------------------


def _db_path(filename: str) -> str:
    try:
        from backend.db_paths import resolve_db

        return str(resolve_db(filename))
    except Exception:  # pragma: no cover
        return str(Path(__file__).resolve().parent.parent / "data" / filename)


def _read_only_rows(path: str, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    """Reine Lese-Abfrage; existiert die DB nicht, ist das Ergebnis leer."""
    if not Path(path).exists():
        return []
    try:
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        try:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.warning("[NeedsMe] Read-only-Abfrage fehlgeschlagen (%s): %s", Path(path).name, exc)
        return []


def default_approval_provider(tenant: str = "default") -> list[dict[str, Any]]:
    """Offene Freigabeanfragen aus der Approval-Engine (nur SELECT)."""
    placeholders = ",".join("?" for _ in OPEN_APPROVAL_STATUSES)
    rows = _read_only_rows(
        _db_path("agentic_memory.db"),
        f"SELECT * FROM approval_requests WHERE lower(COALESCE(status,'')) IN ({placeholders}) "
        "ORDER BY created_at DESC LIMIT 100",
        tuple(sorted(OPEN_APPROVAL_STATUSES)),
    )
    return [row for row in rows if _tenant_matches(_text(row.get("tenant_id"), 64), tenant)]


def default_mission_provider(tenant: str = "default") -> list[dict[str, Any]]:
    """Offene Missions-Gates direkt aus kanban.db (kein Auto-Migrate)."""
    rows = _read_only_rows(
        _db_path("kanban.db"),
        "SELECT t.id, t.title, t.status, t.assignee, t.created_by, t.created_at, t.project_id, "
        "m.meta_json FROM tasks t LEFT JOIN mc_task_meta m ON m.task_id = t.id "
        "WHERE lower(COALESCE(t.status,'')) NOT IN ('archived','done','completed','cancelled') "
        "ORDER BY t.created_at DESC LIMIT 100",
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        meta: dict[str, Any] = {}
        try:
            loaded = json.loads(str(row.get("meta_json") or "{}"))
            if isinstance(loaded, dict):
                meta = loaded
        except (TypeError, ValueError):
            meta = {}
        status = _text(row.get("status"), 40).lower()
        if status not in OPEN_MISSION_STATUSES and not bool(meta.get("hitl_required")):
            continue
        merged = dict(row)
        merged.update(meta)
        if _tenant_matches(_text(merged.get("tenant_id") or merged.get("tenant"), 64), tenant):
            result.append(merged)
    return result


def default_question_provider(tenant: str = "default") -> list[dict[str, Any]]:
    """Noch nicht quittierte, an Menschen adressierte Agentenrückfragen."""
    rows = _read_only_rows(
        _db_path("agentic_memory.db"),
        "SELECT id, task_id, from_agent, to_agent, acceptance_criteria, status, created_at "
        "FROM agent_handoffs WHERE lower(COALESCE(status,'')) = 'pending_acceptance' "
        "ORDER BY created_at DESC LIMIT 100",
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        recipient = _text(row.get("to_agent"), 120)
        # Agent-zu-Agent-Übergaben sind KEINE Rückfragen an einen Menschen.
        if not recipient or _is_agent_identity(recipient):
            continue
        if _tenant_matches(_text(row.get("tenant_id"), 64), tenant):
            result.append(row)
    return result


def default_abort_provider(tenant: str = "default") -> list[dict[str, Any]]:
    """Fehlgeschlagene Abbrüche als unsichere Abbrüche bündeln."""
    try:
        from backend.cancellation import failed_cancellations

        raw = failed_cancellations()
    except Exception as exc:
        logger.debug("[NeedsMe] Cancel-Status nicht verfuegbar: %s", exc)
        return []
    result: list[dict[str, Any]] = []
    if isinstance(raw, Mapping):
        for scope, reasons in raw.items():
            if not isinstance(reasons, (list, tuple)):
                reasons = [reasons]
            for index, reason in enumerate(reasons):
                result.append(
                    {
                        "id": f"abort:{scope}:{index}",
                        "scope": scope,
                        "reason": reason,
                        "tenant_id": "",
                    }
                )
    return result


def default_escalation_resolver(
    owner: str,
    *,
    domain: str = "finance",
    requester_id: str | None = None,
    first_approver: str | None = None,
) -> dict[str, Any]:
    """M95-Vertretungslogik; ohne aktiven Urlaubsmodus neutral (kein Block)."""
    try:
        from backend.approval_policy_engine import approval_engine

        delegation = approval_engine.get_delegation(str(owner or "admin"))
        if not bool(delegation.get("is_active")):
            return {
                "resolved": False,
                "status": "not_required",
                "deputy": None,
                "reason": "Kein aktiver Urlaubsmodus; keine Stellvertretung erforderlich.",
            }
        return dict(
            approval_engine.resolve_human_escalation_target(
                str(owner or "admin"),
                domain=domain,
                requester_id=requester_id or None,
                first_approver=first_approver or None,
            )
        )
    except Exception as exc:
        # Fehler bei der Vertretungsprüfung NIE als „freigegeben“ werten.
        return {
            "resolved": False,
            "status": "escalated_blocked",
            "deputy": None,
            "reason": f"Vertretungsprüfung nicht verfügbar (fail-closed): {exc}",
        }


# ---------------------------------------------------------------------------
# Normalisierung
# ---------------------------------------------------------------------------

EscalationResolver = Callable[..., Mapping[str, Any]]
EvidenceProvider = Callable[..., Any]
PolicyEvaluator = Callable[..., Any]
RowProvider = Callable[[str], Sequence[Mapping[str, Any]]]


def _normalize_escalation(
    raw: Mapping[str, Any], *, owner: str, requester_id: str, first_approver: str
) -> EscalationInfo:
    status = _text(raw.get("status"), 60) or "not_required"
    deputy_raw = raw.get("deputy")
    if isinstance(deputy_raw, Mapping):
        target = _text(deputy_raw.get("username") or deputy_raw.get("id"), 120)
    else:
        target = _text(deputy_raw, 120)
    reason = _text(raw.get("reason"), 400)
    resolved = bool(raw.get("resolved")) and bool(target)
    blocked = status == "escalated_blocked"
    # Agent-Fallback auch bei injiziertem Resolver hart blockieren.
    if target and _is_agent_identity(target):
        target, resolved, blocked = "", False, True
        reason = "Agenten-/Systemidentität als Stellvertreter abgelehnt (M95)."
    if resolved and requester_id and _same_identity(target, requester_id):
        target, resolved, blocked = "", False, True
        reason = "Vier-Augen-Konflikt: Stellvertreter ist Antragsteller (M95)."
    if resolved and first_approver and _same_identity(target, first_approver):
        target, resolved, blocked = "", False, True
        reason = "Vier-Augen-Konflikt: Stellvertreter hat bereits freigegeben (M95)."
    return EscalationInfo(
        owner=_text(owner, 120),
        resolved=resolved,
        target=target or None,
        status="escalated_blocked" if blocked else status,
        reason=reason,
    )


def _build_item(
    *,
    kind: str,
    raw: Mapping[str, Any],
    actor: str,
    tenant: str,
    now: dt.datetime,
    timeout_hours: int,
    evidence_provider: EvidenceProvider | None,
    policy_evaluator: PolicyEvaluator | None,
    escalation_resolver: EscalationResolver,
) -> NeedsMeItem | None:
    """Eine Quelle in das einheitliche Item-Format überführen."""
    reference_id = _text(raw.get("reference_id") or raw.get("id"), 160)
    domain = _text(raw.get("domain") or raw.get("project_id"), 80) or "system"
    source = _text(raw.get("source"), 80) or kind
    payload = _safe_payload(raw.get("payload") or raw.get("payload_json") or {})
    requested_by = _text(
        raw.get("requester_id")
        or payload.get("_requester_id")
        or raw.get("created_by")
        or raw.get("from_agent")
        or raw.get("scope"),
        120,
    )
    assigned_to = _text(
        raw.get("escalated_to")
        or raw.get("assigned_approver")
        or raw.get("assignee")
        or raw.get("to_agent"),
        120,
    )
    if not assigned_to and kind == "unsafe_abort":
        assigned_to = "admin"
    status = _text(raw.get("status") or "open", 60)
    created = _parse_dt(raw.get("created_at")) or now
    expires = (
        _parse_dt(raw.get("expires_at"))
        or _parse_dt(raw.get("timeout_at"))
        or (created + dt.timedelta(hours=timeout_hours))
    )
    title = _text(raw.get("title") or raw.get("question") or reference_id, 200)
    if not title:
        return None

    subject: dict[str, Any] = {
        "request_id": reference_id,
        "reference_id": _text(raw.get("reference_id"), 160),
        "domain": domain,
        "tenant_id": _text(raw.get("tenant_id"), 64) or tenant,
        "payload": payload,
        "kind": kind,
    }
    policy = evaluate_policy_gate(subject, evaluator=policy_evaluator)
    risk_raw = _text(policy.get("risk") or policy.get("risk_level"), 20).lower()
    amount = payload.get("amount", 0.0)
    try:
        high_amount = float(amount) >= 500.0
    except (TypeError, ValueError):
        high_amount = False
    four_eyes = bool(raw.get("requires_four_eyes") or policy.get("requires_four_eyes") or high_amount)
    risk: Literal["low", "medium", "high"]
    if risk_raw in ("high", "critical", "hoch") or domain.lower() in HIGH_RISK_DOMAINS or four_eyes:
        risk = "high"
    elif risk_raw in ("low", "niedrig"):
        risk = "low"
    else:
        risk = "medium"
    evidence_required = bool(
        risk == "high" or kind in ("mcp_hitl", "unsafe_abort") or policy.get("evidence_required", False)
    )
    evidence = tuple(collect_evidence_refs(subject, provider=evidence_provider))
    # Nur echte M68-Belegrefs erfüllen die Belegpflicht. Die lokale
    # Subject-Prüfsumme ist ein Diagnosewert, kein Beleg (kein Agent-Fallback).
    belege = tuple(ref for ref in evidence if ref.kind != "subject_digest")
    evidence_complete = (not evidence_required) or (
        bool(belege) and all(bool(ref.checksum) for ref in belege)
    )

    escalation_raw = escalation_resolver(
        assigned_to or "admin",
        domain=domain,
        requester_id=requested_by or None,
        first_approver=_text(payload.get("first_approver"), 120) or None,
    )
    escalation = _normalize_escalation(
        escalation_raw if isinstance(escalation_raw, Mapping) else {},
        owner=assigned_to or "admin",
        requester_id=requested_by,
        first_approver=_text(payload.get("first_approver"), 120),
    )

    tenant_id = _text(raw.get("tenant_id") or raw.get("tenant"), 64)
    values: dict[str, Any] = {
        "id": _text(raw.get("id"), 160) or f"{kind}:{reference_id}",
        "kind": kind,
        "title": title,
        "source": source,
        "reference_id": reference_id,
        "status": status,
        "domain": domain,
        "tenant_id": tenant_id,
        "requested_by": requested_by,
        "assigned_to": assigned_to,
        "created_at": _iso(created),
        "timeout_at": _iso(expires),
        "risk": risk,
    }
    missing = tuple(name for name in UNIFIED_REQUIRED_FIELDS if not str(values.get(name, "")).strip())
    if "tenant_id" in missing:
        # Ohne Tenant-Angabe ist das Gate systemweit; kein Pflichtfeld-Verstoß.
        missing = tuple(name for name in missing if name != "tenant_id")

    actor_is_human = not _is_agent_identity(actor)
    target = escalation.target or assigned_to
    needs_you = actor_is_human and (
        kind == "unsafe_abort"
        or not assigned_to
        or _same_identity(actor, assigned_to)
        or _same_identity(actor, target)
    )
    blocking: list[str] = []
    if not actor_is_human:
        blocking.append("Agenten-/Systemidentität darf keine Freigabe erteilen.")
    if requested_by and _same_identity(actor, requested_by):
        blocking.append("Vier-Augen-Prinzip: Antragsteller darf nicht freigeben.")
    if four_eyes and _same_identity(actor, payload.get("first_approver")):
        blocking.append("Vier-Augen-Prinzip: Erstfreigabe bereits durch diese Person.")
    if escalation.status == "escalated_blocked":
        blocking.append(escalation.reason or "Vertretung fail-closed blockiert.")
    if evidence_required and not evidence_complete:
        blocking.append("Belegpflicht nicht erfüllt: Beleg mit Prüfsumme fehlt.")
    if missing:
        blocking.append("Pflichtfelder unvollständig: " + ", ".join(missing))

    may_decide = needs_you and not blocking
    return NeedsMeItem(
        id=str(values["id"]),
        kind=kind,  # type: ignore[arg-type]  # kind kommt aus fester Quellliste
        title=title,
        domain=domain,
        tenant_id=tenant_id,
        source=source,
        reference_id=reference_id,
        status=status,
        requested_by=requested_by,
        assigned_to=assigned_to,
        created_at=_iso(created),
        timeout_at=_iso(expires),
        overdue=now > expires,
        risk=risk,
        missing_fields=missing,
        decision_fields=DECISION_FIELDS.get(kind, ()),
        evidence_required=evidence_required,
        evidence=evidence,
        evidence_complete=evidence_complete,
        escalation=escalation,
        requires_four_eyes=four_eyes,
        needs_you=needs_you,
        may_decide=may_decide,
        blocking_reasons=tuple(blocking),
    )


def sse_payload(bundle: NeedsMeBundle) -> dict[str, Any]:
    """SSE-Nutzlast NUR mit Zählern/Status — keine Titel, Payloads oder Secrets."""
    return {
        "type": NEEDS_ME_SSE_EVENT,
        "total": bundle.total,
        "requires_action": bundle.requires_action,
        "counts": dict(bundle.counts),
        "generated_at": bundle.generated_at,
    }


# ---------------------------------------------------------------------------
# Öffentlicher Einstiegspunkt
# ---------------------------------------------------------------------------


def collect_needs_me(
    actor: str,
    tenant: str = "default",
    *,
    approval_provider: RowProvider | None = None,
    mission_provider: RowProvider | None = None,
    question_provider: RowProvider | None = None,
    abort_provider: Callable[[str], Sequence[Mapping[str, Any]]] | None = None,
    evidence_provider: EvidenceProvider | None = None,
    policy_evaluator: PolicyEvaluator | None = None,
    escalation_resolver: EscalationResolver | None = None,
    timeout_hours: int = DEFAULT_TIMEOUT_HOURS,
    now: dt.datetime | None = None,
) -> NeedsMeBundle:
    """Bündelt alle offenen Gates read-only; es wird NIE freigegeben.

    Die Provider sind injizierbar, damit der Integrator fremde Module (M68/M69)
    nach dem Merge verdrahten kann. Ohne Injektion werden die vorhandenen
    Datenquellen über reine SELECT-Abfragen gelesen.
    """
    current = now or _utcnow()
    if current.tzinfo is None:
        current = current.replace(tzinfo=dt.timezone.utc)
    clean_actor = _text(actor, 120)
    clean_tenant = _text(tenant, 64) or "default"
    resolve = escalation_resolver or default_escalation_resolver
    approvals = (approval_provider or default_approval_provider)(clean_tenant)
    missions = (mission_provider or default_mission_provider)(clean_tenant)
    questions = (question_provider or default_question_provider)(clean_tenant)
    aborts = (abort_provider or default_abort_provider)(clean_tenant)

    sources: list[tuple[str, Sequence[Mapping[str, Any]]]] = []
    for row in approvals:
        if not isinstance(row, Mapping):
            continue
        reference = _text(row.get("reference_id"), 160)
        kind = "mcp_hitl" if reference.lower().startswith("mcp:") else "policy"
        sources.append((kind, [row]))
    sources.append(("mission", [r for r in missions if isinstance(r, Mapping)]))
    sources.append(("agent_question", [r for r in questions if isinstance(r, Mapping)]))
    sources.append(("unsafe_abort", [r for r in aborts if isinstance(r, Mapping)]))

    items: list[NeedsMeItem] = []
    seen: set[str] = set()
    for kind, rows in sources:
        for row in rows:
            # Tenant-Grenze gilt für JEDEN Provider (auch injizierte Fakes).
            if not _tenant_matches(_text(row.get("tenant_id") or row.get("tenant"), 64), clean_tenant):
                continue
            item = _build_item(
                kind=kind,
                raw=row,
                actor=clean_actor,
                tenant=clean_tenant,
                now=current,
                timeout_hours=timeout_hours,
                evidence_provider=evidence_provider,
                policy_evaluator=policy_evaluator,
                escalation_resolver=resolve,
            )
            if item is None or item.id in seen:
                continue
            seen.add(item.id)
            items.append(item)

    items.sort(key=lambda i: (not i.overdue, i.timeout_at, i.id))
    counts = {kind: sum(1 for item in items if item.kind == kind) for kind in GATE_KINDS}
    return NeedsMeBundle(
        actor=clean_actor,
        tenant=clean_tenant,
        actor_is_human=not _is_agent_identity(clean_actor),
        generated_at=_iso(current),
        items=items,
        counts=counts,
        total=len(items),
        requires_action=sum(1 for item in items if item.needs_you),
        timeout_policy_hours=timeout_hours,
    )
