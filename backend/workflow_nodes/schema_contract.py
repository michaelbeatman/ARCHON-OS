"""Cluster 7 — JSON/Schema-Validierung, Repair-Retry, Frontier-Eskalation.

Reine Extraktion aus ``default_agent_node_executor`` (frueher ~:1348-1438).
KEINE Logikaenderung: ``_validate_contract``, Repair-Prompt, Eskalations-Prompt,
Token-Akkumulation und Fehlertexte sind 1:1 uebernommen.

WICHTIG (versteckte Kopplung, Fund bei B5): der Kosten-Tail der Facade liest
``_repair_in``/``_repair_out``/``_esc_in``/``_esc_out``/``_repair_model_used``
ueber ``locals().get(...)`` (workflow_dag_runner.py:1539-1548). Diese Namen
muessen nach der Extraktion WIEDER in ``locals()`` der Facade stehen, sonst
waere die Semantik stillschweigend veraendert — auch wenn der D12-except-Zweig
das Endergebnis aktuell auf ``cost_usd=None`` festnagelt. Deshalb traegt
``SchemaOutcome`` alle fuenf Werte; die Facade weist sie explizit zu.

Dependency-Injection (S3): ``dispatch_with_budget`` zur Aufrufzeit uebergeben.
"""

from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable, Dict, NamedTuple, Optional, Tuple

__all__ = ["SchemaOutcome", "validate_contract", "validate_and_repair"]


class SchemaOutcome(NamedTuple):
    """Alle von Cluster 7 veraenderten Locals der Facade."""

    content: str
    res: Dict[str, Any]
    is_error: bool
    parsed_output: Optional[Any]
    repair_in: int
    repair_out: int
    esc_in: int
    esc_out: int
    repair_model_used: str


def validate_contract(raw_txt: str, schema: Dict[str, Any]) -> Tuple[bool, Any, str]:
    """Validiert ``raw_txt`` gegen ``schema`` (1:1 aus der ehemaligen Nested-Funktion)."""
    _clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_txt.strip(), flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        _obj = json.loads(_clean)
    except Exception as _jerr:
        return False, None, f"Kein gueltiges JSON: {_jerr}"
    if not isinstance(_obj, dict):
        return False, None, "JSON-Root muss ein Objekt sein."
    req_keys = schema.get("required") if isinstance(schema.get("required"), list) else list(schema.keys())
    missing = [k for k in req_keys if k not in _obj]  # type: ignore[union-attr]
    if missing:
        return False, _obj, f"Fehlende Pflichtfelder: {', '.join(str(m) for m in missing)}"
    return True, _obj, ""


async def validate_and_repair(
    *,
    node: Dict[str, Any],
    res: Dict[str, Any],
    content: str,
    is_error: bool,
    model: str,
    escalation_model: str,
    agent_id: str,
    agent_name: str,
    eff_system_prompt: str,
    role: str,
    reasoning_level: str,
    kanban_task_id: Optional[str],
    full_prompt: str,
    dispatch_with_budget: Callable[..., Awaitable[Tuple[Any, bool]]],
) -> SchemaOutcome:
    """Schema-Validierung inkl. genau 1 Repair-Retry und Frontier-Eskalation."""
    parsed_output: Optional[Any] = None
    output_schema = node.get("output_schema")
    repair_in = 0
    repair_out = 0
    esc_in = 0
    esc_out = 0
    repair_model_used = ""

    if not is_error and content and isinstance(output_schema, dict):
        ok_schema, parsed_obj, schema_err = validate_contract(content, output_schema)
        if not ok_schema:
            repair_prompt = (
                f"{full_prompt}\n\n[SCHEMA-VALIDIERUNG FEHLGESCHLAGEN]\n"
                f"Fehler: {schema_err}\n"
                f"Erwartetes Schema: {json.dumps(output_schema, ensure_ascii=False)}\n"
                f"Deine bisherige Ausgabe:\n{content[:3000]}\n\n"
                "Gib ausschliesslich ein valides JSON-Objekt zurueck, das alle Pflichtfelder erfuellt."
            )
            repair_model_used = escalation_model or model
            rep_res, rep_blocked = await dispatch_with_budget(
                node, res, model,
                agent_id=agent_id,
                agent_name=agent_name,
                prompt=repair_prompt,
                role=role,
                system_prompt=eff_system_prompt,
                model=repair_model_used,
                reasoning_level=reasoning_level,
                task_id=str(kanban_task_id or node.get("id") or ""),
                _phase="schema_repair",
            )
            if rep_blocked:
                is_error = True
                res["error"] = str(rep_res.get("error") or "NODE_TOKEN_BUDGET_EXCEEDED")
            repair_in = int(rep_res.get("input_tokens") or 0)
            repair_out = int(rep_res.get("output_tokens") or 0)
            res["input_tokens"] = int(res.get("input_tokens") or 0) + repair_in
            res["output_tokens"] = int(res.get("output_tokens") or 0) + repair_out
            rep_content = str(rep_res.get("content") or "").strip()
            if rep_content:
                content = rep_content
                ok_schema, parsed_obj, schema_err = validate_contract(content, output_schema)
        # Punkt 3.2.6: Frontier-Eskalation, wenn der Repair-Retry am billigen Modell scheitert
        if not ok_schema and not is_error and escalation_model and escalation_model != model:
            esc_prompt = (
                f"{full_prompt}\n\n"
                f"[SCHEMA-VALIDIERUNG FEHLGESCHLAGEN — FRONTIER-ESKALATION]\n"
                f"Fehler: {schema_err}\n"
                f"Erwartetes Schema: {json.dumps(output_schema, ensure_ascii=False)}\n"
                f"Vorheriger Versuch:\n{content[:3000]}\n\n"
                "Liefere ausschliesslich das korrekte JSON-Objekt."
            )
            esc_res, esc_blocked = await dispatch_with_budget(
                node, res, model,
                agent_id=agent_id,
                agent_name=agent_name,
                prompt=esc_prompt,
                role=role,
                system_prompt=eff_system_prompt,
                model=escalation_model,
                reasoning_level="high",
                task_id=str(kanban_task_id or node.get("id") or ""),
                _phase="frontier_escalation",
            )
            if esc_blocked:
                is_error = True
                res["error"] = str(esc_res.get("error") or "NODE_TOKEN_BUDGET_EXCEEDED")
            esc_in = int(esc_res.get("input_tokens") or 0)
            esc_out = int(esc_res.get("output_tokens") or 0)
            res["input_tokens"] = int(res.get("input_tokens") or 0) + esc_in
            res["output_tokens"] = int(res.get("output_tokens") or 0) + esc_out
            esc_content = str(esc_res.get("content") or "").strip()
            if esc_content:
                content = esc_content
                ok_schema, parsed_obj, schema_err = validate_contract(content, output_schema)
        if ok_schema:
            parsed_output = parsed_obj
        else:
            is_error = True
            res["error"] = f"Output-Schema-Verletzung: {schema_err}"

    return SchemaOutcome(
        content=content,
        res=res,
        is_error=is_error,
        parsed_output=parsed_output,
        repair_in=repair_in,
        repair_out=repair_out,
        esc_in=esc_in,
        esc_out=esc_out,
        repair_model_used=repair_model_used,
    )
