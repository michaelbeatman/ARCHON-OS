"""
backend/structured_output_enforcer.py
Paket 3 (Feature 11): Structured Outputs & JSON-Schema-Garantie (Grammar Enforcement & Auto-Repair).
Extrahiert, repariert und validiert JSON-Antworten von Sprachmodellen deterministisch gegen ein vorgegebenes
Pflichtfeld-/Typ-Schema, damit nachgelagerte Pipelines niemals an fehlerhaftem JSON scheitern.
"""

import re
import json
from typing import Dict, Any, Optional


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("structured_outputs")
    except Exception:
        return {
            "enabled": True,
            "auto_repair_json": True,
            "strict_schema_validation": True,
            "max_repair_attempts": 2
        }


TYPE_DEFAULTS = {
    "string": "",
    "str": "",
    "integer": 0,
    "int": 0,
    "number": 0.0,
    "float": 0.0,
    "boolean": False,
    "bool": False,
    "array": [],
    "list": [],
    "object": {},
    "dict": {}
}


class StructuredOutputEnforcer:
    def _repair_raw_json(self, raw_text: str) -> str:
        text = (raw_text or "").strip()
        # 1. Entferne Markdown-Codeblöcke ```json ... ```
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
        if fence_match:
            text = fence_match.group(1).strip()

        # 2. Schneide führenden/nachfolgenden Fließtext ab (suche äußerste { ... } oder [ ... ])
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            text = text[first_brace:last_brace + 1]

        # 3. Entferne Trailing Commas vor } oder ]
        text = re.sub(r",\s*([}\]])", r"\1", text)

        # 4. Falls ungeschlossene Klammern am Ende fehlen, ergänze sie
        open_curly = text.count("{") - text.count("}")
        if open_curly > 0:
            text += "}" * open_curly

        return text

    def validate_and_enforce(
        self,
        raw_output: str,
        schema: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        cfg = _get_cfg()
        enabled = bool(cfg.get("enabled", True))
        auto_repair = bool(cfg.get("auto_repair_json", True))
        strict_schema = bool(cfg.get("strict_schema_validation", True))

        if not enabled:
            return {
                "valid": True,
                "bypassed": True,
                "repaired": False,
                "raw_output": raw_output
            }

        repaired_used = False
        parsed_obj = None
        parse_error = None

        try:
            parsed_obj = json.loads(raw_output)
        except Exception as e1:
            parse_error = str(e1)
            if auto_repair:
                candidate = self._repair_raw_json(raw_output)
                try:
                    parsed_obj = json.loads(candidate)
                    repaired_used = True
                    parse_error = None
                except Exception as e2:
                    parse_error = str(e2)

        if parsed_obj is None or not isinstance(parsed_obj, dict):
            return {
                "valid": False,
                "repaired": repaired_used,
                "error": f"JSON-Parsing fehlgeschlagen: {parse_error}",
                "data": {}
            }

        missing_filled = []
        type_coercions = []

        if schema and strict_schema:
            for field_name, expected_type in schema.items():
                exp_low = str(expected_type).lower()
                if field_name not in parsed_obj or parsed_obj[field_name] is None:
                    parsed_obj[field_name] = TYPE_DEFAULTS.get(exp_low, "")
                    missing_filled.append(field_name)
                else:
                    val = parsed_obj[field_name]
                    try:
                        if exp_low in ("int", "integer") and not isinstance(val, int):
                            parsed_obj[field_name] = int(float(val))
                            type_coercions.append(field_name)
                        elif exp_low in ("float", "number") and not isinstance(val, (int, float)):
                            parsed_obj[field_name] = float(val)
                            type_coercions.append(field_name)
                        elif exp_low in ("str", "string") and not isinstance(val, str):
                            parsed_obj[field_name] = str(val)
                            type_coercions.append(field_name)
                    except Exception:
                        parsed_obj[field_name] = TYPE_DEFAULTS.get(exp_low, "")
                        type_coercions.append(field_name)

        return {
            "valid": True,
            "repaired": repaired_used,
            "missing_fields_filled": missing_filled,
            "type_coercions": type_coercions,
            "data": parsed_obj
        }


structured_output_enforcer = StructuredOutputEnforcer()
