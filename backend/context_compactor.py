"""
backend/context_compactor.py
Paket 1 (Feature 4) + M99: Dynamisches Context-Compaction, modell-dynamische
Kontextfenster & Hierarchisches Summarizing.
Verdichtet lange Konversations- und Tool-Verläufe konsistent gegen das aktive
Modell-Kontextfenster (z. B. 128k / 200k / 1M, sicherer Fallback 32k) in einen
strukturierten `[HIERARCHICAL_MEMORY_STATE]`-Block, während die jüngsten
`keep_recent_turns` Nachrichten im Original erhalten bleiben.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("archon.context_compactor")

DEFAULT_MAX_CONTEXT_TOKENS = 32000
MIN_CONTEXT_TOKENS = 4096
MAX_CONTEXT_TOKENS = 2_000_000

DEFAULT_TRIGGER_TOKEN_THRESHOLD = 6000
DEFAULT_AUTO_COMPACT_PCT = 85.0
DEFAULT_KEEP_RECENT_TURNS = 4
DEFAULT_TARGET_COMPRESSION_RATIO = 0.30

# Geordnete Prefix-/Familien-Tabelle (spezifischere Eintraege zuerst)
MODEL_CONTEXT_WINDOWS: Tuple[Tuple[str, int], ...] = (
    # 1M+ Kontextfenster
    ("gemini-3", 1_000_000),
    ("gemini-2.5", 1_000_000),
    ("gemini-2.0", 1_000_000),
    ("gemini-1.5", 1_000_000),
    ("gpt-4.1", 1_000_000),
    # 200k Kontextfenster
    ("claude-4", 200_000),
    ("claude-3", 200_000),
    ("claude-sonnet", 200_000),
    ("claude-opus", 200_000),
    ("claude-haiku", 200_000),
    ("gpt-5", 200_000),
    ("o4-", 200_000),
    ("o3-", 200_000),
    ("o1-", 200_000),
    ("glm-5", 200_000),
    # 128k Kontextfenster
    ("gpt-4o", 128_000),
    ("chatgpt-4o", 128_000),
    ("gpt-4-turbo", 128_000),
    ("deepseek-chat", 128_000),
    ("deepseek-reasoner", 128_000),
    ("deepseek-r1", 128_000),
    ("deepseek-v3", 128_000),
    ("llama-4", 128_000),
    ("llama-3.3", 128_000),
    ("llama-3.2", 128_000),
    ("llama-3.1", 128_000),
    ("llama3.3", 128_000),
    ("llama3.2", 128_000),
    ("llama3.1", 128_000),
    ("qwen-3", 128_000),
    ("qwen3", 128_000),
    ("qwen-2.5", 128_000),
    ("qwen2.5", 128_000),
    ("qwq", 128_000),
    ("mistral-large", 128_000),
    ("codestral", 128_000),
    ("mixtral-8x22b", 128_000),
    ("grok-4", 128_000),
    ("grok-3", 128_000),
    ("grok-2", 128_000),
    ("glm-4", 128_000),
    ("kimi", 128_000),
    ("moonshot", 128_000),
)

_EXACT_MODEL_WINDOWS: Dict[str, int] = {
    "o1": 200_000,
    "o3": 200_000,
    "o4": 200_000,
}

_UNTRUSTED_TOOL_DELIMITER = "--- BEGIN UNTRUSTED TOOL OUTPUT ---"


def normalize_model_name(model: Optional[str]) -> str:
    """Normalisiert Modell-IDs (Provider-Praefix und :free/:exacto-Suffix entfernen)."""
    raw = str(model or "").strip().lower()
    if not raw:
        return ""
    if "/" in raw:
        raw = raw.rsplit("/", 1)[-1]
    if ":" in raw:
        raw = raw.split(":", 1)[0]
    return raw.strip()


def _clamp_context_window(tokens: Any) -> Optional[int]:
    if isinstance(tokens, bool):
        return None
    try:
        val = int(tokens)
    except (TypeError, ValueError):
        return None
    if val <= 0:
        return None
    return max(MIN_CONTEXT_TOKENS, min(MAX_CONTEXT_TOKENS, val))


def _lookup_cached_provider_context(model: str) -> Optional[int]:
    """Liest das Kontextfenster rein aus dem In-Memory-Preis-/Modell-Cache (kein Netzwerk)."""
    try:
        from backend.llm_prices import get_price_cache

        cache = get_price_cache()
        if not isinstance(cache, dict) or not cache:
            return None
        raw = model.strip()
        candidates = [raw, raw.lower()]
        if ":" in raw:
            candidates.append(raw.split(":", 1)[0])
        for cand in candidates:
            entry = cache.get(cand)
            if isinstance(entry, dict):
                clamped = _clamp_context_window(
                    entry.get("context_length") or entry.get("max_context_tokens")
                )
                if clamped is not None:
                    return clamped
        norm = normalize_model_name(raw)
        if norm:
            for key, entry in cache.items():
                if normalize_model_name(key) == norm and isinstance(entry, dict):
                    clamped = _clamp_context_window(
                        entry.get("context_length") or entry.get("max_context_tokens")
                    )
                    if clamped is not None:
                        return clamped
    except Exception:
        return None
    return None


def resolve_model_context_window(
    model: Optional[str] = None,
    *,
    provider_metadata: Optional[Dict[str, Any]] = None,
    configured_override: Optional[int] = None,
) -> int:
    """Ermittelt das dynamische Kontextfenster je Modell mit sicherem 32k-Fallback.

    Prioritaet:
    1. Explizite ``provider_metadata`` (``context_length`` / ``max_context_tokens``)
    2. In-Memory-Provider-Cache (``backend.llm_prices.get_price_cache()``)
    3. Eingebaute Modellfamilien-Tabelle (128k / 200k / 1M)
    4. Optionales ``configured_override`` (fuer unbekannte/lokale Modelle)
    5. Sicherer Fallback ``DEFAULT_MAX_CONTEXT_TOKENS`` (32000)
    """
    if isinstance(provider_metadata, dict):
        meta_ctx = _clamp_context_window(
            provider_metadata.get("context_length")
            or provider_metadata.get("max_context_tokens")
            or provider_metadata.get("context_window")
        )
        if meta_ctx is not None:
            return meta_ctx

    model_str = str(model or "").strip()
    if model_str:
        cached = _lookup_cached_provider_context(model_str)
        if cached is not None:
            return cached

        norm = normalize_model_name(model_str)
        if norm in _EXACT_MODEL_WINDOWS:
            return _EXACT_MODEL_WINDOWS[norm]
        for prefix, window in MODEL_CONTEXT_WINDOWS:
            if norm.startswith(prefix):
                return window

    override = _clamp_context_window(configured_override)
    if override is not None:
        return override

    return DEFAULT_MAX_CONTEXT_TOKENS


def validate_context_compactor_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Validiert Compaction-Parameter aus Settings-UI / API streng (fail-closed)."""
    if not isinstance(raw, dict):
        raise ValueError("context_compactor muss ein JSON-Objekt sein.")

    validated: Dict[str, Any] = {}

    if "enabled" in raw:
        val = raw["enabled"]
        if not isinstance(val, bool):
            raise ValueError("context_compactor.enabled muss ein Boolean sein.")
        validated["enabled"] = val

    if "trigger_token_threshold" in raw:
        val = raw["trigger_token_threshold"]
        if isinstance(val, bool) or not isinstance(val, (int, float)) or int(val) != val:
            raise ValueError("context_compactor.trigger_token_threshold muss eine Ganzzahl sein.")
        ival = int(val)
        if ival < 1000 or ival > 1_000_000:
            raise ValueError(
                "context_compactor.trigger_token_threshold muss zwischen 1000 und 1000000 liegen."
            )
        validated["trigger_token_threshold"] = ival

    if "auto_compact_pct" in raw:
        val = raw["auto_compact_pct"]
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise ValueError("context_compactor.auto_compact_pct muss eine Zahl sein.")
        fval = float(val)
        if fval < 10.0 or fval > 99.0:
            raise ValueError(
                "context_compactor.auto_compact_pct muss zwischen 10 und 99 Prozent liegen."
            )
        validated["auto_compact_pct"] = round(fval, 1)

    if "keep_recent_turns" in raw:
        val = raw["keep_recent_turns"]
        if isinstance(val, bool) or not isinstance(val, (int, float)) or int(val) != val:
            raise ValueError("context_compactor.keep_recent_turns muss eine Ganzzahl sein.")
        ival = int(val)
        if ival < 1 or ival > 100:
            raise ValueError(
                "context_compactor.keep_recent_turns muss zwischen 1 und 100 liegen."
            )
        validated["keep_recent_turns"] = ival

    if "target_compression_ratio" in raw:
        val = raw["target_compression_ratio"]
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise ValueError("context_compactor.target_compression_ratio muss eine Zahl sein.")
        fval = float(val)
        if fval < 0.05 or fval > 0.90:
            raise ValueError(
                "context_compactor.target_compression_ratio muss zwischen 0.05 und 0.90 liegen."
            )
        validated["target_compression_ratio"] = round(fval, 2)

    if "auto_compact_min_messages" in raw:
        val = raw["auto_compact_min_messages"]
        if isinstance(val, bool) or not isinstance(val, (int, float)) or int(val) != val:
            raise ValueError("context_compactor.auto_compact_min_messages muss eine Ganzzahl sein.")
        ival = int(val)
        if ival < 2 or ival > 200:
            raise ValueError(
                "context_compactor.auto_compact_min_messages muss zwischen 2 und 200 liegen."
            )
        validated["auto_compact_min_messages"] = ival

    # Unbekannte Schluessel nicht stillschweigend verwerfen, falls zukuenftige Felder durchgereicht werden
    for key, val in raw.items():
        if key not in validated:
            validated[key] = val

    return validated


def resolve_effective_compaction_params(
    cfg: Optional[Dict[str, Any]],
    max_context_tokens: int,
    keep_recent_override: Optional[int] = None,
) -> Dict[str, Any]:
    """Berechnet konsistente Compaction-Schwellen gegen das dynamische Kontextfenster."""
    src = cfg if isinstance(cfg, dict) else {}
    window = _clamp_context_window(max_context_tokens) or DEFAULT_MAX_CONTEXT_TOKENS

    enabled = bool(src.get("enabled", True))
    try:
        auto_compact_pct = float(src.get("auto_compact_pct", DEFAULT_AUTO_COMPACT_PCT))
    except (TypeError, ValueError):
        auto_compact_pct = DEFAULT_AUTO_COMPACT_PCT
    auto_compact_pct = max(10.0, min(99.0, auto_compact_pct))

    try:
        raw_keep = keep_recent_override if keep_recent_override is not None else src.get("keep_recent_turns", DEFAULT_KEEP_RECENT_TURNS)
        keep_recent_turns = max(1, min(100, int(raw_keep)))
    except (TypeError, ValueError):
        keep_recent_turns = DEFAULT_KEEP_RECENT_TURNS

    try:
        trigger_token_threshold = int(src.get("trigger_token_threshold", DEFAULT_TRIGGER_TOKEN_THRESHOLD))
    except (TypeError, ValueError):
        trigger_token_threshold = DEFAULT_TRIGGER_TOKEN_THRESHOLD
    trigger_token_threshold = max(1000, trigger_token_threshold)

    pct_threshold = max(1000, int(round(window * (auto_compact_pct / 100.0))))
    # Deckelt statische Schwellen auf auto_compact_pct des dynamischen Fensters,
    # damit kleinere lokale Modelle (32k) nie ueberlaufen.
    effective_threshold = min(trigger_token_threshold, pct_threshold)

    return {
        "enabled": enabled,
        "max_context_tokens": window,
        "auto_compact_pct": round(auto_compact_pct, 1),
        "pct_threshold": pct_threshold,
        "trigger_token_threshold": trigger_token_threshold,
        "effective_threshold": effective_threshold,
        "keep_recent_turns": keep_recent_turns,
    }


def format_compaction_marker(
    *,
    original_tokens: int,
    compacted_tokens: int,
    saved_pct: float,
    compacted_messages: int,
    kept_recent: int,
    max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
    model: Optional[str] = None,
) -> str:
    """Erzeugt eine maschinenlesbare Marker-Zeile fuer den Chatverlauf (M99)."""
    saved_tokens = max(0, int(original_tokens) - int(compacted_tokens))
    model_tag = str(model or "").replace("|", "/").replace("]", "").strip() or "auto"
    return (
        f"[COMPACTION_MARKER | before={int(original_tokens)} | after={int(compacted_tokens)} "
        f"| saved={saved_tokens} | saved_pct={round(float(saved_pct), 1)} "
        f"| compacted_messages={int(compacted_messages)} | kept_recent={int(kept_recent)} "
        f"| model={model_tag} | max_context_tokens={int(max_context_tokens)}]"
    )


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("context_compactor")
    except Exception:
        return {
            "enabled": True,
            "trigger_token_threshold": DEFAULT_TRIGGER_TOKEN_THRESHOLD,
            "auto_compact_pct": DEFAULT_AUTO_COMPACT_PCT,
            "keep_recent_turns": DEFAULT_KEEP_RECENT_TURNS,
            "target_compression_ratio": DEFAULT_TARGET_COMPRESSION_RATIO,
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
        role = str(msg.get("role", "user")).lower()
        content = str(msg.get("content", "")).strip()
        if not content:
            continue

        # M93-Verzahnung: Unvertrauenswuerdige Tool-Outputs (Firewall-Delimiter)
        # nicht als verbindliche Ziele oder Entscheidungen in den Memory-State uebernehmen.
        if role == "tool" or _UNTRUSTED_TOOL_DELIMITER in content:
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
        "errors_and_fixes": errors_and_fixes,
    }


class ContextCompactor:
    def compact_messages(
        self,
        messages: List[Dict[str, Any]],
        force: bool = False,
        keep_recent_override: Optional[int] = None,
        *,
        model: Optional[str] = None,
        max_context_tokens: Optional[int] = None,
        provider_metadata: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        cfg = _get_cfg()
        resolved_window = (
            _clamp_context_window(max_context_tokens)
            or resolve_model_context_window(model, provider_metadata=provider_metadata)
        )
        params = resolve_effective_compaction_params(
            cfg,
            resolved_window,
            keep_recent_override=keep_recent_override,
        )

        # F011/B-11: Produzent im echten Compaction-Pfad. Jede einzelne Nachricht
        # wird idempotent in die verlustfreie Historie der konsolidierten
        # memory.db aufgenommen (auch wenn keine Komprimierung stattfindet).
        try:
            from backend.lossless_session_dag import (
                derive_session_id,
                derive_tenant_id,
                record_turns,
            )
            _lcm_sid = f"session:{session_id}" if session_id else derive_session_id(messages)
            _lcm_tid = derive_tenant_id(messages)
            record_turns(_lcm_sid, messages, tenant_id=_lcm_tid)
        except Exception as _lcm_exc:
            logger.error(
                "[ContextCompactor] Lossless-Turn-Persistenz fehlgeschlagen: %s", _lcm_exc
            )
            _lcm_sid, _lcm_tid = "compactor-unknown", "default"

        enabled = bool(params["enabled"])
        threshold = int(params["effective_threshold"])
        keep_recent = int(params["keep_recent_turns"])

        original_tokens = _estimate_tokens(messages)
        if not enabled and not force:
            return {
                "compacted": False,
                "bypassed": True,
                "reason": "Context Compactor in settings.json deaktiviert.",
                "original_tokens": original_tokens,
                "compacted_tokens": original_tokens,
                "saved_tokens": 0,
                "saved_pct": 0.0,
                "model": model,
                "max_context_tokens": resolved_window,
                "effective_threshold": threshold,
                "auto_compact_pct": params["auto_compact_pct"],
                "keep_recent_turns": keep_recent,
                "lossless_session_id": _lcm_sid,
                "messages": messages,
            }

        if not force and (original_tokens < threshold or len(messages) <= keep_recent + 1):
            return {
                "compacted": False,
                "reason": f"Token-Anzahl ({original_tokens}) unter Schwellenwert ({threshold}).",
                "original_tokens": original_tokens,
                "compacted_tokens": original_tokens,
                "saved_tokens": 0,
                "saved_pct": 0.0,
                "model": model,
                "max_context_tokens": resolved_window,
                "effective_threshold": threshold,
                "auto_compact_pct": params["auto_compact_pct"],
                "keep_recent_turns": keep_recent,
                "lossless_session_id": _lcm_sid,
                "messages": messages,
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
            f"- Wichtige Ergebnisse/Entscheidungen: {'; '.join(facts['decisions'])}",
        ]
        if facts["errors_and_fixes"]:
            summary_lines.append(f"- Diagnostizierte Fehler/Fixes: {'; '.join(facts['errors_and_fixes'])}")

        compacted_block = {
            "role": "system",
            "content": "\n".join(summary_lines),
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
        saved_tokens = max(0, original_tokens - compacted_tokens)
        saved_pct = round(max(0.0, (1.0 - (compacted_tokens / max(1, original_tokens))) * 100), 1)
        marker = format_compaction_marker(
            original_tokens=original_tokens,
            compacted_tokens=compacted_tokens,
            saved_pct=saved_pct,
            compacted_messages=len(older_turns),
            kept_recent=len(recent_turns),
            max_context_tokens=resolved_window,
            model=model,
        )

        return {
            "compacted": True,
            "original_turns": len(messages),
            "compacted_turns": len(new_messages),
            "original_tokens": original_tokens,
            "compacted_tokens": compacted_tokens,
            "saved_tokens": saved_tokens,
            "saved_pct": saved_pct,
            "model": model,
            "max_context_tokens": resolved_window,
            "effective_threshold": threshold,
            "auto_compact_pct": params["auto_compact_pct"],
            "keep_recent_turns": keep_recent,
            "compaction_marker": marker,
            "extracted_facts": facts,
            # F011: nachweisbarer Effekt (§0) statt unsichtbarem DB-Schreibvorgang
            "lossless_session_id": _lcm_sid,
            "lossless_summary_id": _lcm_summary_id,
            "messages": new_messages,
        }


context_compactor = ContextCompactor()
