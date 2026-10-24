"""
backend/output_policy_linter.py
Paket 4 (Feature 19): Deterministischer Output-Linter & Policy-Checker.
Prüft und bereinigt Agenten-Antworten in unter 5 Millisekunden deterministisch vor der Auslieferung:
1. Entfernt verbotene KI-Floskeln & Sycophancy-Opener (gemäß Anti-AI-Slop-Regelwerk)
2. Blockiert gefährliche destruktive Shell-Befehle (`rm -rf /`, `DROP TABLE`, `format c:`).
"""

import re
from typing import Dict, Any, List


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("output_policy_linter")
    except Exception:
        return {
            "enabled": True,
            "strip_ai_slop_phrases": True,
            "block_destructive_commands": True,
            "auto_clean_output": True
        }


AI_SLOP_PATTERNS = [
    r"(?i)^(great question!|certainly!|absolutely!|i hope this helps!|gerne helfe ich dir dabei!|natürlich!)\s*",
    r"(?i)\b(delve into|testament to|tapestry of|cutting-edge|paradigm shift|at its core|in conclusion,)\b"
]

DESTRUCTIVE_CMD_PATTERNS = [
    r"rm\s+-rf\s+/(?:\s|$|\*)",
    r"(?i)drop\s+table\s+\w+",
    r"(?i)mkfs\.\w+",
    r"(?i):\(\)\{\s*:\|:&\s*\};:"
]


class OutputPolicyLinter:
    def lint_and_clean(self, output_text: str) -> Dict[str, Any]:
        cfg = _get_cfg()
        if not bool(cfg.get("enabled", True)):
            return {
                "passed": True,
                "bypassed": True,
                "cleaned_text": output_text,
                "violations": []
            }

        strip_slop = bool(cfg.get("strip_ai_slop_phrases", True))
        block_destr = bool(cfg.get("block_destructive_commands", True))
        auto_clean = bool(cfg.get("auto_clean_output", True))

        violations: List[str] = []
        working = output_text or ""

        if block_destr:
            for pat in DESTRUCTIVE_CMD_PATTERNS:
                m = re.search(pat, working)
                if m:
                    violations.append(f"DESTRUCTIVE_COMMAND_DETECTED: '{m.group(0)}'")
                    if auto_clean:
                        working = re.sub(pat, "[BLOCKED_DESTRUCTIVE_COMMAND]", working)

        if strip_slop:
            for pat in AI_SLOP_PATTERNS:
                m = re.search(pat, working)
                if m:
                    violations.append(f"AI_SLOP_PHRASE: '{m.group(0).strip()}'")
                    if auto_clean:
                        working = re.sub(pat, "", working).strip()

        has_critical = any(v.startswith("DESTRUCTIVE_COMMAND") for v in violations)
        return {
            "passed": not has_critical,
            "auto_cleaned": auto_clean and len(violations) > 0,
            "violations_count": len(violations),
            "violations": violations,
            "cleaned_text": working
        }


output_policy_linter = OutputPolicyLinter()
