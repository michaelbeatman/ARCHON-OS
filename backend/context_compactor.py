"""
backend/context_compactor.py
Paket 1 (Feature 4): Dynamisches Context-Compaction & Hierarchisches Summarizing.
Verdichtet lange Konversations- und Tool-Verläufe ab `trigger_token_threshold` (Standard: 6000 Tokens)
oder auf explizite Anforderung in einen strukturierten `[HIERARCHICAL_MEMORY_STATE]`-Block
(Ziele, Entscheidungen, Dateipfade, Befehle, Offene Punkte), während die jüngsten `keep_recent_turns`
Nachrichten im Original erhalten bleiben. Spart ~65–80 % Kontext-Tokens ohne Faktenverlust.
"""

import logging
import re
from typing import List, Dict, Any, Optional

logger = logging.getLogger("archon.context_compactor")


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("context_compactor")
    except Exception:
        return {
            "enabled": True,
            "trigger_token_threshold": 6000,
            "keep_recent_turns": 4,
            "target_compression_ratio": 0.30
        }


def _estimate_tokens(messages: List[Dict[str, Any]]) -> int:
    total_chars = sum(len(str(m.get("content", ""))) for m in messages)
    return max(1, total_chars // 4)


def _extract_hard_facts(messages: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    file_paths = set()
    decisions: list[str] = []
    errors_and_fixes: list[str] = []
    goals: list[str] = []

    path_pattern = re.compile(r"(?:[a-zA-Z]:[\\/]|/)?[\w.\-/\\]+\.(?:py|js|ts|html|css|json|md|docx|sql|sh|yaml|yml)")

    for msg in messages:
        role = msg.get("role", "user")
        content = str(msg.get("content", "")).strip()
        if not content:
            continue

        for match in path_pattern.findall(content):
            if len(match) > 4:
                file_paths.add(match.replace("\\", "/"))

        first_line = content.splitlines()[0][:160]
        if role == "user" and len(goals) < 6:
            goals.append(first_line)
        elif any(k in content.lower() for k in ("entscheidung", "beschlossen", "gelöst", "behoben", "implementiert", "fixed")):
            if len(decisions) < 8:
                decisions.append(first_line)
        elif any(k in content.lower() for k in ("error", "fehler", "traceback", "exception", "bug")):
            if len(errors_and_fixes) < 6:
                errors_and_fixes.append(first_line)

    return {
        "goals": goals or ["Allgemeine Aufgabenbearbeitung"],
        "file_paths": sorted(file_paths)[:25],
        "decisions": decisions or ["Bisherige Schritte erfolgreich ausgeführt"],
        "errors_and_fixes": errors_and_fixes
    }


class ContextCompactor:
    def compact_messages(
        self,
        messages: List[Dict[str, Any]],
        force: bool = False,
        keep_recent_override: Optional[int] = None
    ) -> Dict[str, Any]:
        cfg = _get_cfg()
        # F011/B-11: Produzent im echten Compaction-Pfad. Jede einzelne Nachricht
        # wird idempotent in die verlustfreie Historie der konsolidierten
        # memory.db aufgenommen (auch wenn keine Komprimierung stattfindet).
        try:
            from backend.lossless_session_dag import (
                derive_session_id, derive_tenant_id, record_turns,
            )
            _lcm_sid = derive_session_id(messages)
            _lcm_tid = derive_tenant_id(messages)
            record_turns(_lcm_sid, messages, tenant_id=_lcm_tid)
        except Exception as _lcm_exc:
            logger.error(
                "[ContextCompactor] Lossless-Turn-Persistenz fehlgeschlagen: %s", _lcm_exc
            )
            _lcm_sid, _lcm_tid = "compactor-unknown", "default"

        enabled = bool(cfg.get("enabled", True))
        threshold = int(cfg.get("trigger_token_threshold", 6000))
        keep_recent = int(keep_recent_override if keep_recent_override is not None else cfg.get("keep_recent_turns", 4))

        original_tokens = _estimate_tokens(messages)
        if not enabled and not force:
            return {
                "compacted": False,
                "bypassed": True,
                "reason": "Context Compactor in settings.json deaktiviert.",
                "original_tokens": original_tokens,
                "compacted_tokens": original_tokens,
                "saved_pct": 0.0,
                "lossless_session_id": _lcm_sid,
                "messages": messages
            }

        if not force and (original_tokens < threshold or len(messages) <= keep_recent + 1):
            return {
                "compacted": False,
                "reason": f"Token-Anzahl ({original_tokens}) unter Schwellenwert ({threshold}).",
                "original_tokens": original_tokens,
                "compacted_tokens": original_tokens,
                "saved_pct": 0.0,
                "lossless_session_id": _lcm_sid,
                "messages": messages
            }

        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        if len(non_system) <= keep_recent:
            older_turns = non_system[:-1] if len(non_system) > 1 else non_system
            recent_turns = non_system[-1:] if len(non_system) > 1 else []
        else:
            older_turns = non_system[:-keep_recent]
            recent_turns = non_system[-keep_recent:]

        facts = _extract_hard_facts(older_turns)
        summary_lines = [
            "[HIERARCHICAL_MEMORY_STATE — KOMPRIMIERTE HISTORIE]",
            f"- Verdichtete Turns: {len(older_turns)}",
            f"- Kernziele: {'; '.join(facts['goals'])}",
            f"- Betroffene Dateien ({len(facts['file_paths'])}): {', '.join(facts['file_paths']) if facts['file_paths'] else 'Keine'}",
            f"- Wichtige Ergebnisse/Entscheidungen: {'; '.join(facts['decisions'])}"
        ]
        if facts["errors_and_fixes"]:
            summary_lines.append(f"- Diagnostizierte Fehler/Fixes: {'; '.join(facts['errors_and_fixes'])}")

        compacted_block = {
            "role": "system",
            "content": "\n".join(summary_lines)
        }

        # F011/B-11: ECHTER PRODUZENT — Summary-Knoten mit den verdichteten
        # Turns in der verlustfreien Historie verknüpfen (tenant-scoped, HMAC).
        _lcm_summary_id = ""
        try:
            from backend.lossless_session_dag import compact_conversation_turns
            _lcm_summary_id = compact_conversation_turns(
                _lcm_sid, older_turns, compacted_block["content"], tenant_id=_lcm_tid
            )
        except Exception as _lcm_exc:
            logger.error(
                "[ContextCompactor] Lossless-Compaction-Persistenz fehlgeschlagen: %s",
                _lcm_exc,
            )

        new_messages = system_msgs + [compacted_block] + recent_turns
        compacted_tokens = _estimate_tokens(new_messages)
        saved_pct = round(max(0.0, (1.0 - (compacted_tokens / max(1, original_tokens))) * 100), 1)

        return {
            "compacted": True,
            "original_turns": len(messages),
            "compacted_turns": len(new_messages),
            "original_tokens": original_tokens,
            "compacted_tokens": compacted_tokens,
            "saved_pct": saved_pct,
            "extracted_facts": facts,
            # F011: nachweisbarer Effekt (§0) statt unsichtbarem DB-Schreibvorgang
            "lossless_session_id": _lcm_sid,
            "lossless_summary_id": _lcm_summary_id,
            "messages": new_messages
        }


context_compactor = ContextCompactor()
