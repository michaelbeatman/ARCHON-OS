"""M67 — deterministische Antwortprüfung und frische, kompakte Step-Prompts.

Kein Ersatz für OmniRoute oder ``backend/cost_estimator.py``: das Kontextfenster
kommt aus der M99-SSOT (``resolve_model_context_window``), die Kostenprognose
aus dem bestehenden Schätzer. Neu ist ausschließlich die hostseitige Kontrolle:
Erst prüfen, dann übernehmen; für jeden Schritt einen kurzen Prompt aus dem
Host-Zustand statt aus der wachsenden Chat-Historie.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import replace
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from backend.context_compactor import estimate_tokens, resolve_model_context_window
from backend.cost_estimator import estimate_prompt_cost
from backend.host_state_store import (
    MAX_JOB_ID_CHARS,
    MAX_RESULT_KEYS,
    MAX_RESULTS,
    MAX_STATUS_CHARS,
    MAX_STEPS,
    MAX_TEXT_CHARS,
    HostState,
    HostStateConflict,
    HostStateError,
    HostStateStore,
    _tenant_key_part,
)

logger = logging.getLogger("archon.prompt_compressor")

DEFAULT_STEP_TOKEN_BUDGET = 4000
MIN_STEP_TOKEN_BUDGET = 512
MAX_STEP_TOKEN_BUDGET = 8000
MIN_STEP_OUTPUT_TOKENS = 64
MAX_STEP_OUTPUT_TOKENS = 4096
MAX_STR_CHARS = 4000
MAX_LIST_ITEMS = 64
MAX_ERRORS = 12
MAX_NORMALIZED_CHARS = 12000
STEP_MARKER = "[HOST_STATE_STEP]"

_ALLOWED_TYPES = frozenset({"str", "int", "float", "bool", "dict", "list", "literal"})
_RULES = (
    "REGELN: Antworte ausschließlich im vorgegebenen JSON-Schema. "
    "Keine Annahmen aus älterem Chat-Verlauf. Keine Secrets ausgeben."
)


def _clip(value: Any, limit: int) -> str:
    text = str(value or "")
    if len(text) <= max(1, limit):
        return text
    return text[: max(0, limit - 12)] + "[GEKÜRZT]"


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, str):
        return "str"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, Mapping):
        return "dict"
    if isinstance(value, (list, tuple)):
        return "list"
    return type(value).__name__


def _normalize_spec(spec: Any) -> Dict[str, Any]:
    if isinstance(spec, str):
        return {"type": spec}
    if isinstance(spec, Mapping):
        return dict(spec)
    return {"type": "invalid"}


def _limit(spec: Mapping[str, Any], key: str, default: int, cap: int) -> int:
    raw = spec.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(cap, value))


def _optional_bound(value: Any) -> Optional[float]:
    """Schema-Grenzen defensiv lesen — fehlerhafte Schemas lösen keine Exception aus."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _check_value(
    value: Any, spec: Mapping[str, Any], path: str, errors: List[str]
) -> Tuple[bool, Any]:
    """Rein deterministische Prüfung — Meldungen enthalten niemals Werte."""
    typ = str(spec.get("type") or "")
    if typ not in _ALLOWED_TYPES:
        errors.append(f"{path}: unsupported schema type")
        return False, None

    if typ == "str":
        if not isinstance(value, str):
            errors.append(f"{path}: erwartet str, erhalten {_type_name(value)}")
            return False, None
        return True, value[: _limit(spec, "max_len", MAX_STR_CHARS, MAX_STR_CHARS)]

    if typ == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append(f"{path}: erwartet int, erhalten {_type_name(value)}")
            return False, None
        low = _optional_bound(spec.get("min"))
        high = _optional_bound(spec.get("max"))
        if low is not None and value < low:
            errors.append(f"{path}: int unterhalb des Minimums")
            return False, None
        if high is not None and value > high:
            errors.append(f"{path}: int oberhalb des Maximums")
            return False, None
        return True, value

    if typ == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"{path}: erwartet float, erhalten {_type_name(value)}")
            return False, None
        number = float(value)
        if not math.isfinite(number):
            errors.append(f"{path}: float ist nicht endlich")
            return False, None
        return True, number

    if typ == "bool":
        if not isinstance(value, bool):
            errors.append(f"{path}: erwartet bool, erhalten {_type_name(value)}")
            return False, None
        return True, value

    if typ == "literal":
        allowed = spec.get("allowed")
        if not isinstance(allowed, (list, tuple)):
            errors.append(f"{path}: Schema ohne erlaubte Werte")
            return False, None
        for candidate in allowed:
            if type(value) is type(candidate) and value == candidate:
                return True, value
        errors.append(f"{path}: Wert nicht in den erlaubten Werten")
        return False, None

    if typ == "dict":
        if not isinstance(value, Mapping):
            errors.append(f"{path}: erwartet dict, erhalten {_type_name(value)}")
            return False, None
        fields_spec = spec.get("fields") or {}
        if not isinstance(fields_spec, Mapping):
            errors.append(f"{path}: Schema-Felder müssen ein Objekt sein")
            return False, None
        before = len(errors)
        cleaned: Dict[str, Any] = {}
        for key in sorted(str(k) for k in fields_spec.keys()):
            sub_spec = _normalize_spec(fields_spec[key])
            sub_path = f"{path}.{key}"
            if key not in value:
                if bool(sub_spec.get("required", True)):
                    errors.append(f"{sub_path}: Pflichtfeld fehlt")
                continue
            ok, sub_value = _check_value(value[key], sub_spec, sub_path, errors)
            if ok:
                cleaned[key] = sub_value
        return len(errors) == before, cleaned

    # list
    if not isinstance(value, (list, tuple)):
        errors.append(f"{path}: erwartet list, erhalten {_type_name(value)}")
        return False, None
    cap = _limit(spec, "max_items", MAX_LIST_ITEMS, MAX_LIST_ITEMS)
    if len(value) > cap:
        errors.append(f"{path}: zu viele Einträge")
        return False, None
    item_spec = _normalize_spec(spec.get("item_type", "str"))
    before = len(errors)
    cleaned_items: List[Any] = []
    for index, item in enumerate(value[:cap]):
        ok, sub_value = _check_value(item, item_spec, f"{path}[{index}]", errors)
        if ok:
            cleaned_items.append(sub_value)
    return len(errors) == before, cleaned_items


def validate_model_response(response: Any, schema: Mapping[str, Any]) -> Dict[str, Any]:
    """Prüft eine Modellantwort VOR jeder Zustandsübernahme (fail-closed).

    ``schema`` erwartet pro Feld ``{"type": ..., "required": ..., ...}``.
    Rückgabe enthält ausschließlich Fehlercodes/Feldnamen und — nur bei Erfolg —
    die normalisierten Werte. Antwortwerte erscheinen nie in Fehlermeldungen.
    """
    if not isinstance(schema, Mapping) or not schema:
        return {
            "valid": False,
            "errors": ["schema: muss ein nicht-leeres Objekt sein"],
            "normalized": {},
            "ignored_fields": 0,
        }

    if isinstance(response, str):
        try:
            response = json.loads(response)
        except (TypeError, ValueError):
            return {
                "valid": False,
                "errors": ["response: kein gültiges JSON"],
                "normalized": {},
                "ignored_fields": 0,
            }

    if not isinstance(response, Mapping):
        return {
            "valid": False,
            "errors": [f"response: erwartet dict, erhalten {_type_name(response)}"],
            "normalized": {},
            "ignored_fields": 0,
        }

    schema_str = {str(key): value for key, value in schema.items()}
    response_str = {str(key): value for key, value in response.items()}
    errors: List[str] = []
    normalized: Dict[str, Any] = {}

    for key in sorted(schema_str.keys()):
        spec = _normalize_spec(schema_str[key])
        if key not in response_str:
            if bool(spec.get("required", True)):
                errors.append(f"{key}: Pflichtfeld fehlt")
            continue
        ok, cleaned = _check_value(response_str[key], spec, key, errors)
        if ok:
            normalized[key] = cleaned

    ignored = sum(1 for key in response_str if key not in schema_str)
    if ignored:
        errors.append(f"response: {ignored} unbekannte Felder ignoriert")
    try:
        payload_size = len(json.dumps(normalized, sort_keys=True, ensure_ascii=False))
    except (TypeError, ValueError):
        errors.append("response: normalisierte Werte nicht serialisierbar")
        payload_size = 0
    if payload_size > MAX_NORMALIZED_CHARS:
        errors.append("response: normalisierte Nutzlast zu groß")

    errors = errors[:MAX_ERRORS]
    return {
        "valid": not errors,
        "errors": errors,
        "normalized": normalized if not errors else {},
        "ignored_fields": ignored,
    }


def apply_response_to_state(state: HostState, normalized: Mapping[str, Any]) -> HostState:
    """Übernimmt nur geprüfte, begrenzte Felder — nie freie Chat-Texte."""
    status = str(normalized.get("status") or state.status)[:MAX_STATUS_CHARS]
    steps: List[Dict[str, Any]] = [dict(entry) for entry in state.steps[:MAX_STEPS]]

    step_id = normalized.get("step_id")
    if isinstance(step_id, str) and step_id:
        for index, entry in enumerate(steps):
            if str(entry.get("id") or "") == step_id:
                if "step_status" in normalized:
                    entry["status"] = str(normalized["step_status"])[:MAX_STATUS_CHARS]
                if "summary" in normalized:
                    entry["summary"] = _clip(normalized["summary"], 400)
                steps[index] = entry
                break

    results: List[Dict[str, Any]] = [dict(entry) for entry in state.results[:MAX_RESULTS]]
    result = normalized.get("result")
    if isinstance(result, Mapping):
        entry = {str(key): _clip(val, 800) for key, val in list(result.items())[:MAX_RESULT_KEYS]}
        results = (results + [entry])[-MAX_RESULTS:]

    next_action = str(normalized.get("next_action") or state.next_action)[:MAX_TEXT_CHARS]
    return replace(
        state,
        status=status,
        steps=tuple(steps),
        results=tuple(results),
        next_action=next_action,
    )


def _record_audit(
    action: str,
    *,
    session_id: str,
    tenant_id: str,
    expected_version: int,
    errors: List[str],
    fields: List[str],
    required: bool = True,
) -> Dict[str, Any]:
    """Audit-Hinweis über die bestehende Kette — nie mit Antwortwerten füttern."""
    payload = {
        "session_id": session_id,
        "tenant_id": tenant_id,
        "expected_version": expected_version,
        "errors": errors[:MAX_ERRORS],
        "fields": fields[:MAX_ERRORS],
        "store": "kv_store/agentic_memory.db",
    }
    try:
        from backend.audit_log import chained_audit_log

        event = chained_audit_log.record_event(
            "m67_host_state", action, "host-state-service", payload
        )
        return {
            "status": "recorded",
            "event_id": str((event or {}).get("id") or (event or {}).get("event_id") or ""),
        }
    except Exception as exc:
        logger.error("[M67] Audit-Event %s/%s fehlgeschlagen: %s", "m67_host_state", action, exc)
        try:
            from backend.audit_log import is_audit_strict

            strict = bool(is_audit_strict())
        except Exception:
            strict = True
        if strict and required:
            raise RuntimeError("audit_write_failed") from exc
        return {"status": "failed", "reason": "audit_write_failed"}


def advance_from_response(
    store: HostStateStore,
    *,
    session_id: str,
    tenant_id: Optional[str],
    response: Any,
    schema: Mapping[str, Any],
    expected_version: int,
    apply: Optional[Callable[[HostState, Mapping[str, Any]], HostState]] = None,
) -> Dict[str, Any]:
    """Prüft, auditiert und schreibt NUR bei gültiger Antwort atomar weiter."""
    tid = _tenant_key_part(tenant_id)
    fields = sorted(str(key) for key in schema.keys()) if isinstance(schema, Mapping) else []
    validation = validate_model_response(response, schema)

    if not validation["valid"]:
        audit = _record_audit(
            "model_response_rejected",
            session_id=session_id,
            tenant_id=tid,
            expected_version=expected_version,
            errors=list(validation["errors"]),
            fields=fields,
        )
        return {
            "accepted": False,
            "state": None,
            "errors": list(validation["errors"]),
            "audit": audit,
        }

    mutator = apply or apply_response_to_state
    try:
        next_state = store.advance(
            session_id,
            expected_version,
            lambda current: mutator(current, validation["normalized"]),
            tenant_id=tid,
        )
    except (HostStateConflict, HostStateError) as exc:
        errors = [f"version_conflict: {type(exc).__name__}"]
        audit = _record_audit(
            "model_response_conflict",
            session_id=session_id,
            tenant_id=tid,
            expected_version=expected_version,
            errors=errors,
            fields=fields,
        )
        return {"accepted": False, "state": None, "errors": errors, "audit": audit}

    audit = _record_audit(
        "model_response_accepted",
        session_id=session_id,
        tenant_id=tid,
        expected_version=expected_version,
        errors=[],
        fields=fields,
        required=False,
    )
    return {
        "accepted": True,
        "state": next_state.to_dict(),
        "errors": [],
        "audit": audit,
    }


def format_host_state_marker(state: HostState) -> str:
    """Kompakte, maschinenlesbare Statuszeile für Chat-Anzeige/SSE (M67)."""
    return (
        f"[HOST_STATE_MARKER | v={int(state.version)} "
        f"| job={_clip(state.job_id, MAX_JOB_ID_CHARS).replace('|', '/').replace('[', '(').replace(']', '')} "
        f"| status={_clip(state.status, MAX_STATUS_CHARS).replace('|', '/').replace('[', '(').replace(']', '')} "
        f"| steps={len(state.steps[:MAX_STEPS])} | results={len(state.results[:MAX_RESULTS])}]"
    )


def build_step_prompt(
    host_state: HostState,
    model: Optional[str] = None,
    *,
    token_budget: Optional[int] = None,
    expected_output_tokens: int = 512,
    task_budget_usd: float = 0.25,
) -> Dict[str, Any]:
    """Baut einen frischen Step-Prompt aus dem Host-Zustand, nicht aus Chat-Verlauf.

    Das harte Tokenbudget wird gegen die M99-Fenster-SSOT geklemmt; die Kosten-
    schätzung kommt unverändert aus ``backend.cost_estimator``.
    """
    state = HostState.from_dict(host_state.to_dict())
    window = resolve_model_context_window(model)
    try:
        requested = int(token_budget) if token_budget is not None else DEFAULT_STEP_TOKEN_BUDGET
    except (TypeError, ValueError):
        requested = DEFAULT_STEP_TOKEN_BUDGET
    window_cap = max(MIN_STEP_TOKEN_BUDGET, window // 4)
    budget = max(MIN_STEP_TOKEN_BUDGET, min(MAX_STEP_TOKEN_BUDGET, requested, window_cap))

    try:
        out_tokens = int(expected_output_tokens)
    except (TypeError, ValueError):
        out_tokens = 512
    out_tokens = max(MIN_STEP_OUTPUT_TOKENS, min(MAX_STEP_OUTPUT_TOKENS, out_tokens))
    try:
        budget_usd = max(0.0, float(task_budget_usd))
    except (TypeError, ValueError):
        budget_usd = 0.25

    char_budget = budget * 4
    header = (
        f"{STEP_MARKER} | v={state.version} "
        f"| job={_clip(state.job_id, 80).replace('|', '/')} "
        f"| status={_clip(state.status, 32).replace('|', '/')}"
    )
    lines: List[str] = [header]
    lines.append(f"ZIEL: {_clip(state.goal, max(80, char_budget // 5))}")

    step_lines: List[str] = [f"SCHRITTE ({len(state.steps[:MAX_STEPS])}):"]
    step_char_cap = max(120, char_budget * 2 // 5)
    for entry in state.steps[:MAX_STEPS]:
        step_id = _clip(entry.get("id") or "?", 48)
        step_status = _clip(entry.get("status") or "", 32)
        summary = _clip(entry.get("summary") or entry.get("title") or "", 200)
        line = f"  - {step_id}: {step_status} — {summary}" if step_status else f"  - {step_id}: {summary}"
        step_lines.append(line[:240])
        if sum(len(item) for item in step_lines) > step_char_cap:
            break
    lines.extend(step_lines)

    result_lines: List[str] = [f"ERGEBNISSE ({len(state.results[:MAX_RESULTS])}):"]
    result_char_cap = max(80, char_budget // 5)
    for entry in state.results[:MAX_RESULTS]:
        keys = sorted(str(key) for key in entry.keys())
        item = "; ".join(
            f"{key}={_clip(entry[key], 160)}" for key in keys[:MAX_RESULT_KEYS]
        )
        result_lines.append(f"  - {item}"[:240])
        if sum(len(line) for line in result_lines) > result_char_cap:
            break
    lines.extend(result_lines)

    if state.next_action:
        lines.append(f"NÄCHSTE AKTION: {_clip(state.next_action, max(80, char_budget // 8))}")
    lines.append(_RULES)

    prompt = "\n".join(lines)
    truncated = len(prompt) > char_budget
    if truncated:
        prompt = prompt[:char_budget].rstrip()
    tokens = estimate_tokens(prompt)
    if tokens > budget:  # defensiv; darf bei 4-Zeichen-Regel nicht eintreten
        prompt = prompt[: budget * 4]
        tokens = estimate_tokens(prompt)
        truncated = True

    cost = estimate_prompt_cost(
        prompt,
        model or "deepseek/deepseek-chat",
        expected_output_tokens=out_tokens,
        task_budget_usd=budget_usd,
    )
    return {
        "prompt": prompt,
        "input_tokens": tokens,
        "token_budget": budget,
        "max_context_tokens": window,
        "expected_output_tokens": out_tokens,
        "truncated": truncated,
        "cost_estimate": cost,
        "within_budget": bool(cost.get("fits_budget")),
        "host_state_version": state.version,
        "model": model or "auto",
        "marker": format_host_state_marker(state),
    }


__all__ = (
    "validate_model_response",
    "apply_response_to_state",
    "advance_from_response",
    "build_step_prompt",
    "format_host_state_marker",
    "DEFAULT_STEP_TOKEN_BUDGET",
    "MIN_STEP_TOKEN_BUDGET",
    "MAX_STEP_TOKEN_BUDGET",
)
