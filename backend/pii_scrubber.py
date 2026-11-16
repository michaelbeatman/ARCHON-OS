"""
backend/pii_scrubber.py
Paket 4 (Feature 16): Bidirektionaler PII-Scrubber & Re-Hydration (DSGVO-Anonymisierung).
Ersetzt personenbezogene Daten (E-Mail-Adressen, Telefonnummern, IBANs) vor dem Versand an externe
Cloud-LLMs durch deterministische Platzhalter (`[EMAIL_1]`, `[PHONE_1]`, `[IBAN_1]`) und setzt
die Originalwerte nach Erhalt der LLM-Antwort lokal wieder ein (Re-Hydration).
"""

import re
import uuid
import threading
from collections import OrderedDict
from typing import Dict, Any, Tuple


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("pii_scrubber")
    except Exception:
        return {
            "enabled": True,
            "scrub_emails": True,
            "scrub_phones": True,
            "scrub_ibans": True,
            "auto_rehydrate_response": True
        }


EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
IBAN_REGEX = re.compile(r"\b[A-Z]{2}\d{2}(?:[\s\-]?[A-Z0-9]{4}){2,7}(?:[\s\-]?[A-Z0-9]{1,4})?\b")
PHONE_REGEX = re.compile(r"(?:\+\d{1,3}[\s\-]?|0\d{2,4}[\s\-/]?)\d{3,4}[\s\-]?\d{3,5}\b")


class BidirectionalPIIScrubber:
    def __init__(self, max_sessions: int = 500):
        self.max_sessions = max_sessions
        self._sessions: OrderedDict[str, Dict[str, str]] = OrderedDict()
        self._lock = threading.Lock()

    def clear_sessions(self) -> None:
        with self._lock:
            self._sessions.clear()

    def evict_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def scrub_text(self, text: str, session_id: str = "") -> Dict[str, Any]:
        cfg = _get_cfg()
        if not bool(cfg.get("enabled", True)):
            return {
                "enabled": False,
                "session_id": session_id or "bypassed",
                "scrubbed_text": text,
                "redactions_count": 0,
                "vault_map": {}
            }

        sid = session_id or f"pii-{uuid.uuid4().hex[:10]}"
        with self._lock:
            existing_vault = dict(self._sessions.get(sid) or {})
        vault: Dict[str, str] = existing_vault
        reverse_vault: Dict[str, str] = {v: k for k, v in vault.items()}
        working = text or ""

        def _replace_matches(pattern: re.Pattern, prefix: str, current_text: str) -> str:
            # Existierende wörtliche [PREFIX_N]-Tags im Input überspringen, damit kein Echo-Missbrauch entsteht
            existing_nums = {
                int(m.group(1))
                for m in re.finditer(rf"\[{prefix}_(\d+)\]", current_text)
            }
            for k in vault:
                km = re.fullmatch(rf"\[{prefix}_(\d+)\]", k)
                if km:
                    existing_nums.add(int(km.group(1)))
            counter = (max(existing_nums) + 1) if existing_nums else 1

            def _sub(match: re.Match) -> str:
                nonlocal counter
                raw_val = match.group(0)
                if raw_val in reverse_vault:
                    return reverse_vault[raw_val]
                while f"[{prefix}_{counter}]" in vault or counter in existing_nums:
                    counter += 1
                placeholder = f"[{prefix}_{counter}]"
                vault[placeholder] = raw_val
                reverse_vault[raw_val] = placeholder
                counter += 1
                return placeholder

            return pattern.sub(_sub, current_text)

        if bool(cfg.get("scrub_ibans", True)):
            working = _replace_matches(IBAN_REGEX, "IBAN", working)
        if bool(cfg.get("scrub_emails", True)):
            working = _replace_matches(EMAIL_REGEX, "EMAIL", working)
        if bool(cfg.get("scrub_phones", True)):
            working = _replace_matches(PHONE_REGEX, "PHONE", working)

        with self._lock:
            if sid not in self._sessions:
                while len(self._sessions) >= self.max_sessions:
                    self._sessions.popitem(last=False)
            self._sessions[sid] = vault
        return {
            "enabled": True,
            "session_id": sid,
            "scrubbed_text": working,
            "text": working,
            "redactions_count": len(vault),
            "placeholders": list(vault.keys())
        }

    def rehydrate_text(self, response_text: str, session_id: str, custom_vault: Dict[str, str] = None) -> Dict[str, Any]:
        cfg = _get_cfg()
        if not bool(cfg.get("enabled", True)) or not bool(cfg.get("auto_rehydrate_response", True)):
            return {"rehydrated": False, "text": response_text}

        with self._lock:
            vault = custom_vault if custom_vault is not None else dict(self._sessions.get(session_id, {}))
        restored = response_text or ""
        restored_count = 0
        for placeholder, real_val in vault.items():
            if placeholder in restored:
                restored = restored.replace(placeholder, real_val)
                restored_count += 1

        return {
            "rehydrated": True,
            "session_id": session_id,
            "restored_placeholders_count": restored_count,
            "text": restored
        }


pii_scrubber = BidirectionalPIIScrubber()
