# -*- coding: utf-8 -*-
"""
backend/code_mode_capability_broker.py
======================================
M109b - Capability-Broker fuer den isolierten Code-Mode.

Der Broker ist der EINZIGE Pfad, ueber den Sandbox-Code Capabilities aus dem
Registry (``backend/code_mode_discovery.py``) aufrufen darf. Er duplicationt
weder Maskierung (``credential_masking`` / ``secret_masker``), noch Approval
(``approval_policy_engine``), noch Audit (``audit_log``) - er ruft diese
Module ueber ihre veroffentlichten SSOT-Funktionen auf.

Sicherheitsinvarianten:
  * Allowlist + Route-Binding: eine Capability ist nur erreichbar, wenn NAME
    UND (METHOD, PATH) freigegeben sind.
  * Kein Broker-Bypass ueber Argumente (method/path/url/capability/...).
  * write/destructive brauchen eine extern (HITL) freigegebene PreDecision.
  * Jeder Allow-/Block-Entscheid geht in die GoBD-Audit-Kette; ein
    Audit-Schreibfehler ist fail-closed.
  * Jedes Ergebnis wird rekursiv maskiert, bevor es den Broker verlaesst.
"""

from __future__ import annotations

import asyncio
import inspect
import re
import threading
from typing import Any, Dict, FrozenSet, Iterable, Optional, Tuple

from backend.credential_masking import mask_secret
from backend.secret_masker import mask_sensitive_text

__all__ = [
    "SENSITIVE_KEY_PARTS",
    "_is_sensitive_key",
    "mask_broker_response",
    "CapabilityBroker",
    "get_capability_broker",
]


# ---------------------------------------------------------------------------
# Sensitive-Keys & Maskierung
# ---------------------------------------------------------------------------

SENSITIVE_KEY_PARTS: Tuple[str, ...] = (
    "key", "token", "secret", "password", "credential", "authorization", "auth",
)

# Kleine Allowlist fuer harmlose Woerter, die einen sensitiven Substring
# enthalten („monkey“ enthaelt „key“, „author“ enthaelt „auth“).
_BENIGN_KEY_TOKENS: FrozenSet[str] = frozenset({
    "monkey", "keyword", "keyboard", "keycode", "keyframe", "keyhole",
    "keying", "author", "authors", "authoring", "authored", "secretary",
    "secretaries", "tokenize", "tokenizer", "tokenizing",
})

# Argument-Keys, die eine Capability/Route umleiten oder den Broker uebergehen
# koennten. Normalisiert (lower) verglichen.
_BROKER_BYPASS_KEYS: FrozenSet[str] = frozenset({
    "method", "path", "url", "endpoint", "capability", "broker", "target",
    "_capability", "__proto__",
})

_MAX_MASK_DEPTH = 8
_MAX_MASK_NODES = 200


class _AuditFailure(Exception):
    """Intern: Pflicht-Audit konnte nicht geschrieben werden (fail-closed)."""


def _mask_failure() -> RuntimeError:
    """Fail-closed-Fehler OHNE Rueckverweis auf den Rohwert."""
    # `from None` unterdrueckt __cause__/__context__, damit kein Secret ueber
    # eine verkettete Exception in Logs oder Tracebacks gelangt.
    return RuntimeError("broker_masking_failed")


def _is_sensitive_key(key: Any) -> bool:
    """True, wenn ein Dictionary-Key als sensitiv gilt.

    Groß-/Kleinschreibung ist irrelevant.Comparisons laufen ueber
    alphanumerische Tokens: ``api-key``/``apiKey``/``API_KEY`` werden erkannt,
    ``monkey``/``keyword``/``author`` dagegen nicht falsch positiv.
    """
    text = str(key if key is not None else "").strip().lower()
    if not text:
        return False
    tokens = [tok for tok in re.split(r"[^a-z0-9]+", text) if tok]
    if tokens and all(tok in _BENIGN_KEY_TOKENS for tok in tokens):
        return False
    for token in tokens:
        if token in _BENIGN_KEY_TOKENS:
            continue
        if any(part in token for part in SENSITIVE_KEY_PARTS):
            return True
    return False


def _mask_text(text: str) -> str:
    """SSOT-Textmaskierung - bei Fehler hart fail-closed, nie Rohwert zurueck."""
    try:
        return mask_sensitive_text(text)[0]
    except Exception:
        raise _mask_failure() from None


def mask_broker_response(payload: Any) -> Any:
    """Rekursiv maskieren (max. Tiefe 8 / 200 Knoten).

    * sensitive Keys -> ``credential_masking.mask_secret(value)``
    * String-Blaetter -> ``secret_masker.mask_sensitive_text(text)[0]``
    * bei Ueberschreitung oder Maskierungsfehler -> RuntimeError (fail-closed)

    Es werden bewusst keine Werte in Logs oder Exception-Texte aufgenommen.
    """
    counter = {"nodes": 0}

    def _walk(value: Any, depth: int) -> Any:
        counter["nodes"] += 1
        if counter["nodes"] > _MAX_MASK_NODES or depth > _MAX_MASK_DEPTH:
            raise _mask_failure()

        if isinstance(value, dict):
            result: Dict[Any, Any] = {}
            for key, item in value.items():
                # Auch Keys koenvn ein ENV-Secret-Literal enthalten.
                safe_key = _mask_text(key) if isinstance(key, str) else key
                if _is_sensitive_key(key):
                    try:
                        result[safe_key] = mask_secret(item)
                    except Exception:
                        raise _mask_failure() from None
                else:
                    result[safe_key] = _walk(item, depth + 1)
            return result

        if isinstance(value, (list, tuple)):
            items = [_walk(item, depth + 1) for item in value]
            return tuple(items) if isinstance(value, tuple) else items

        if isinstance(value, set):
            return {_walk(item, depth + 1) for item in value}

        if isinstance(value, str):
            return _mask_text(value)

        if isinstance(value, (bytes, bytearray)):
            try:
                return mask_secret(bytes(value))
            except Exception:
                raise _mask_failure() from None

        return value

    return _walk(payload, 0)


# ---------------------------------------------------------------------------
# Discovery / SSOT-Lazy-Imports
# ---------------------------------------------------------------------------

def _discovery_module() -> Any:
    from backend import code_mode_discovery  # noqa: WPS433 (lazy by design)

    return code_mode_discovery


def _default_audit_sink() -> Any:
    from backend.audit_log import _require_audit_event  # noqa: WPS433

    return _require_audit_event


def _default_executor() -> Any:
    from backend.tool_runtime import execute_agent_tool  # noqa: WPS433

    return execute_agent_tool


def _route_of(cap: Any) -> Tuple[str, str]:
    return (
        str(getattr(cap, "method", "") or "").strip().upper(),
        str(getattr(cap, "path", "") or "").strip(),
    )


def _identity_tokens(actor: Any) -> set:
    """Minimale Identitaets-Tokens zur Self-Approval-Erkennung (defense in depth)."""
    clean = str(actor or "").strip().lower()
    if not clean:
        return set()
    return {tok for tok in (clean, clean.split(" ")[0]) if tok}


def _standard_response(
    status: str,
    *,
    result: Any = None,
    error: Optional[str] = None,
    error_code: Optional[str] = None,
    request_id: Optional[str] = None,
    masked: bool = False,
) -> Dict[str, Any]:
    return {
        "status": status,
        "result": result,
        "error": error,
        "error_code": error_code,
        "request_id": request_id,
        "masked": bool(masked),
    }


# ---------------------------------------------------------------------------
# Broker
# ---------------------------------------------------------------------------

class CapabilityBroker:
    """Chokepoint zwischen Sandbox-Code und den registrierten Capabilities."""

    def __init__(
        self,
        allowlist: Iterable[str],
        *,
        allowed_routes: Optional[Iterable[Tuple[str, str]]] = None,
        engine: Any = None,
        audit_sink: Any = None,
        executor: Any = None,
    ) -> None:
        self.allowlist: FrozenSet[str] = frozenset(
            str(item).strip() for item in (allowlist or ()) if str(item).strip()
        )
        self._engine = engine
        self._audit_sink = audit_sink
        self._executor = executor
        self.allowed_routes: FrozenSet[Tuple[str, str]] = (
            frozenset(
                (str(method).strip().upper(), str(path).strip())
                for method, path in allowed_routes
            )
            if allowed_routes is not None
            else self._routes_from_registry()
        )

    # -- Lazy SSOT-Zugriffe --------------------------------------------------
    def _routes_from_registry(self) -> FrozenSet[Tuple[str, str]]:
        """Default-Routen: (method, path) aller allowlisteten Capabilities."""
        try:
            caps = _discovery_module().all_capabilities()
            return frozenset(_route_of(cap) for cap in caps if str(getattr(cap, "name", "")) in self.allowlist)
        except Exception:
            # Registry nicht verfuegbar -> fail-closed (keine Route erlaubt).
            return frozenset()

    def _get_engine(self) -> Any:
        if self._engine is None:
            # SSOT: Existing module singleton (approval_policy_engine.py).
            # Never instantiate a second engine here - it owns the audit chain
            # lock and the approval-request state.
            from backend.approval_policy_engine import approval_engine  # noqa: WPS433

            self._engine = approval_engine
        return self._engine

    def _get_audit_sink(self) -> Any:
        if self._audit_sink is None:
            self._audit_sink = _default_audit_sink()
        return self._audit_sink

    def _get_executor(self) -> Any:
        if self._executor is None:
            self._executor = _default_executor()
        return self._executor

    def _audit(self, action: str, payload: Dict[str, Any]) -> None:
        """Pflicht-Audit; Schreibfehler werden nie still verschluckt."""
        try:
            self._get_audit_sink()(
                category="code_mode",
                action=action,
                agent_id=str(payload.get("agent_id") or "system"),
                payload=payload,
            )
        except Exception:
            raise _AuditFailure() from None

    # -- Oeffentliche API ----------------------------------------------------
    async def invoke(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
        *,
        agent_id: str = "",
        session_id: str = "default_session",
        approval_id: Optional[str] = None,
        requester: str = "",
        caller_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Capability pruefen, ggf. PreDecision einholen und sicher ausfuehren."""
        try:
            return await self._invoke_impl(
                name,
                arguments,
                agent_id=agent_id,
                session_id=session_id,
                approval_id=approval_id,
                requester=requester,
                caller_context=caller_context,
            )
        except _AuditFailure:
            # Kein zweiter Audit-Versuch gegen eine defekte Senke.
            return _standard_response(
                "error", error_code="AUDIT_WRITE_FAILED", error="Audit write failed"
            )
        except Exception:
            # Fail-closed: keine Rohwerte, kein Exception-Detail nach aussen.
            try:
                self._audit(
                    "broker_error",
                    {"name": str(name or ""), "agent_id": str(agent_id or "system")},
                )
            except Exception:
                pass
            return _standard_response(
                "error", error_code="BROKER_ERROR", error="Broker execution failed"
            )

    def invoke_sync(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
        *,
        agent_id: str = "",
        session_id: str = "default_session",
        approval_id: Optional[str] = None,
        requester: str = "",
        caller_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Synchrone Fassade zu ``invoke`` (Windows-kompatibel)."""
        kwargs: Dict[str, Any] = {
            "agent_id": agent_id,
            "session_id": session_id,
            "approval_id": approval_id,
            "requester": requester,
            "caller_context": caller_context,
        }

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # Kein aktiver Loop: normaler Pfad.
            try:
                return asyncio.run(self.invoke(name, arguments, **kwargs))
            except Exception:
                return _standard_response(
                    "error", error_code="BROKER_ERROR", error="Broker execution failed"
                )

        # Aktiver Loop im aufrufenden Thread: eigene Loop in einem Thread,
        # sonst wäre asyncio.run() unzulaessig (Windows-sicher).
        box: Dict[str, Any] = {}

        def _runner() -> None:
            try:
                box["response"] = asyncio.run(self.invoke(name, arguments, **kwargs))
            except Exception as exc:
                box["error"] = exc

        worker = threading.Thread(target=_runner, daemon=True, name="code-mode-broker")
        worker.start()
        worker.join()
        if "response" in box:
            return box["response"]
        return _standard_response(
            "error", error_code="BROKER_ERROR", error="Broker execution failed"
        )

    # -- Interner Ablauf -----------------------------------------------------
    async def _invoke_impl(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]],
        *,
        agent_id: str,
        session_id: str,
        approval_id: Optional[str],
        requester: str,
        caller_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        clean_name = str(name or "").strip()
        clean_agent = str(agent_id or "").strip()
        safe_name = clean_name[:200]

        def _blocked(code: str, action: str, request_id: Optional[str] = None) -> Dict[str, Any]:
            self._audit(action, {
                "name": safe_name,
                "agent_id": clean_agent,
                "error_code": code,
                "request_id": request_id,
            })
            return _standard_response(
                "blocked", error_code=code, error=code, request_id=request_id
            )

        # 1) Capability aufloesen + Allowlist + Route-Binding
        try:
            cap = _discovery_module().get_capability(clean_name)
        except Exception:
            cap = None
        if (
            cap is None
            or clean_name not in self.allowlist
            or _route_of(cap) not in self.allowed_routes
        ):
            return _blocked("CAPABILITY_NOT_ALLOWLISTED", "capability_blocked")

        # 2) Argumente gegen Broker-Bypass absichern + Schema validieren
        if self._contains_bypass_key(arguments):
            return _blocked("BROKER_ARGUMENT_REJECTION", "capability_blocked")

        try:
            verdict = _discovery_module().validate_arguments(cap, arguments or {})
        except Exception:
            verdict = None
        if not isinstance(verdict, dict) or not verdict.get("ok"):
            return _blocked("SCHEMA_VALIDATION_FAILED", "capability_blocked")
        safe_arguments = verdict.get("arguments")
        if safe_arguments is None:
            safe_arguments = arguments or {}
        if not isinstance(safe_arguments, dict):
            return _blocked("SCHEMA_VALIDATION_FAILED", "capability_blocked")

        # 3) PreDecision-Gate (nur write/destructive)
        gate = await self.pre_decision_gate(
            cap,
            safe_arguments,
            approval_id,
            agent_id=clean_agent,
            requester=requester,
        )
        if not gate.get("allowed"):
            return _standard_response(
                "blocked",
                error_code=str(gate.get("error_code") or "PREDECISION_DENIED"),
                error=str(gate.get("error_code") or "PREDECISION_DENIED"),
                request_id=gate.get("request_id"),
            )

        # 4) Ausfuehrung ueber den zentralen ToolRuntime-Chokepoint
        exec_fn = self._get_executor()
        kwargs: Dict[str, Any] = {
            "tool_name": clean_name,
            "args": safe_arguments,
            "agent_id": clean_agent,
            "session_id": str(session_id or "default_session"),
            "approval_id": approval_id,
            "requested_by": str(requester or clean_agent),
        }
        if isinstance(caller_context, dict) and caller_context:
            try:
                params = inspect.signature(exec_fn).parameters
                accepts = any(
                    p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
                ) or "caller_context" in params
            except (TypeError, ValueError):
                accepts = False
            if accepts:
                kwargs["caller_context"] = caller_context

        raw = exec_fn(**kwargs)
        if inspect.isawaitable(raw):
            raw = await raw

        # Ergebnis IMMER maskieren, bevor es den Broker verlaesst.
        masked_result = mask_broker_response(raw)

        status = "success"
        error: Optional[str] = None
        error_code: Optional[str] = None
        if isinstance(masked_result, dict):
            candidate = str(masked_result.get("status") or "").strip().lower()
            if candidate in ("blocked", "error"):
                status = candidate
                error_code = str(masked_result.get("error_code") or "TOOL_EXECUTION_FAILED")
                error = str(masked_result.get("error") or error_code)

        # 5) Pflicht-Audit mit Nursery-Payload (keine Argumente, keine Secrets)
        self._audit("capability_allowed", {
            "name": clean_name,
            "method": str(getattr(cap, "method", "") or ""),
            "path": str(getattr(cap, "path", "") or ""),
            "risk_level": str(getattr(cap, "risk_level", "") or ""),
            "agent_id": clean_agent,
            "status": status,
        })

        return _standard_response(
            status,
            result=masked_result,
            error=error,
            error_code=error_code,
            request_id=str(approval_id) if approval_id else None,
            masked=True,
        )

    @staticmethod
    def _contains_bypass_key(value: Any, depth: int = 0) -> bool:
        """Rekursive Suche nach Route-/Broker-Bypass-Keys (depth/node hart begrenzt)."""
        if depth > _MAX_MASK_DEPTH:
            return True
        if isinstance(value, dict):
            if len(value) > _MAX_MASK_NODES:
                return True
            for key, item in value.items():
                normalized = str(key if key is not None else "").strip().lower()
                if normalized in _BROKER_BYPASS_KEYS:
                    return True
                if CapabilityBroker._contains_bypass_key(item, depth + 1):
                    return True
            return False
        if isinstance(value, (list, tuple, set)):
            if len(value) > _MAX_MASK_NODES:
                return True
            return any(CapabilityBroker._contains_bypass_key(item, depth + 1) for item in value)
        return False

    async def pre_decision_gate(
        self,
        cap: Any,
        arguments: Dict[str, Any],
        approval_id: Optional[str],
        *,
        agent_id: str = "",
        requester: str = "",
    ) -> Dict[str, Any]:
        """HITL-Gate fuer ``write``/``destructive``; ``read`` laeuft sofort durch."""
        name = str(getattr(cap, "name", "") or "")
        risk = str(getattr(cap, "risk_level", "read") or "read").strip().lower()
        if risk == "read":
            # Kein Extra-Audit noetig: Allow/Block wird ohnehin protokolliert.
            return {"allowed": True, "predecision": False}
        if risk not in ("write", "destructive"):
            # Fail-closed: unbekannte/ungueltige Risikolevel werden wie
            # `destructive` behandelt und nie still als lesend durchgewinkt.
            risk = "destructive"

        engine = self._get_engine()
        if not approval_id:
            outcome = engine.evaluate_and_enqueue(
                domain="code_mode",
                title=f"Code-Mode {risk}: {name}",
                reference_id=name,
                requester_id=str(requester or agent_id),
                payload={"capability": name, "risk_level": risk},
            )
            request_id = outcome.get("request_id") if isinstance(outcome, dict) else None
            self._audit("predecision_denied", {
                "name": name,
                "agent_id": str(agent_id or "system"),
                "error_code": "PREDECISION_REQUIRED",
                "request_id": request_id,
            })
            return {
                "allowed": False,
                "predecision": True,
                "status": "blocked",
                "error_code": "PREDECISION_REQUIRED",
                "request_id": request_id,
            }

        clean_id = str(approval_id).strip()
        request = engine.get_request(clean_id) if clean_id else None
        allowed = (
            isinstance(request, dict)
            and str(request.get("status") or "") == "approved"
            and str(request.get("domain") or "") == "code_mode"
            and str(request.get("reference_id") or "") == name
            and not self._is_self_approval(request, requester, agent_id)
        )
        if not allowed:
            self._audit("predecision_denied", {
                "name": name,
                "agent_id": str(agent_id or "system"),
                "error_code": "PREDECISION_DENIED",
                "request_id": clean_id,
            })
            return {
                "allowed": False,
                "predecision": True,
                "status": "blocked",
                "error_code": "PREDECISION_DENIED",
                "request_id": clean_id,
            }
        return {
            "allowed": True,
            "predecision": True,
            "status": "approved",
            "request_id": clean_id,
        }

    @staticmethod
    def _is_self_approval(
        request: Dict[str, Any], requester: str, agent_id: str
    ) -> bool:
        """Kein Self-Approval: der gespeicherte Genehmiger darf nicht der Antragsteller sein.

        Der ausfuehrende Agent ist regular IDENTISCH mit dem Antragsteller - er
        darf also nicht als „Genehmiger“ gewertet werden. Verglichen werden
        ausschliesslich die im Freigabeantrag dokumentierten Approver.
        """
        stored = str(request.get("requester_id") or "").strip()
        payload = request.get("payload_json")
        if isinstance(payload, str):
            try:
                import json

                payload = json.loads(payload)
            except Exception:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if not stored:
            stored = str(payload.get("_requester_id") or payload.get("requester_id") or "").strip()
        if not stored:
            stored = str(requester or agent_id or "").strip()
        if not stored:
            # Ohne verifizierbaren Antragsteller keine Freigabe akzeptieren.
            return bool(payload.get("_requester_required"))
        stored_tokens = _identity_tokens(stored)
        approvers = (
            request.get("first_approver"),
            request.get("second_approver"),
            request.get("approved_by"),
        )
        for approver in approvers:
            if stored_tokens & _identity_tokens(approver):
                return True
        return False


# ---------------------------------------------------------------------------
# Prozessweiter Default-Broker (Factory fuer code_mode_discovery.call_capability)
# ---------------------------------------------------------------------------

_default_broker: Optional["CapabilityBroker"] = None
_default_broker_lock = threading.Lock()


def get_capability_broker() -> "CapabilityBroker":
    """Prozessweiter Default-Broker mit der vollen registrierten Allowlist.

    Die Registry wird erst beim ersten Aufruf lazy aufgebaut; der Modulimport
    selbst hat keinen Side-Effect. threaded Singleton, damit Diskrepanzen
    zwischen Allowlist und Route-Binding ausgeschlossen sind.
    """
    global _default_broker
    if _default_broker is None:
        with _default_broker_lock:
            if _default_broker is None:
                names = [
                    str(getattr(cap, "name", "") or "").strip()
                    for cap in _discovery_module().all_capabilities()
                ]
                _default_broker = CapabilityBroker(
                    [name for name in names if name]
                )
    return _default_broker
