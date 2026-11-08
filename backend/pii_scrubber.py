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
IBAN_REGEX = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?\d{4}){3,5}(?:\s?\d{1,2})?\b")
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
        vault: Dict[str, str] = {}
        working = text or ""

        def _replace_matches(pattern: re.Pattern, prefix: str, current_text: str) -> str:
            counter = 1
            for match in list(pattern.finditer(current_text)):
                raw_val = match.group(0)
                placeholder = f"[{prefix}_{counter}]"
                vault[placeholder] = raw_val
                current_text = current_text.replace(raw_val, placeholder, 1)
                counter += 1
            return current_text

        if bool(cfg.get("scrub_ibans", True)):
            working = _replace_matches(IBAN_REGEX, "IBAN", working)
        if bool(cfg.get("scrub_emails", True)):
            working = _replace_matches(EMAIL_REGEX, "EMAIL", working)
        if bool(cfg.get("scrub_phones", True)):
            working = _replace_matches(PHONE_REGEX, "PHONE", working)

        with self._lock:
            while len(self._sessions) >= self.max_sessions:
                self._sessions.popitem(last=False)
            self._sessions[sid] = vault
        return {
            "enabled": True,
            "session_id": sid,
            "scrubbed_text": working,
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
