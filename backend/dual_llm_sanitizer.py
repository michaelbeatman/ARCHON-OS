"""
backend/dual_llm_sanitizer.py
Archon OS 2026 - Dual-LLM Guard gegen Prompt Injection (t-d3f2d2)
Stufe 1 Quarantäne-Modell isoliert externe E-Mails, Websites und Chat-Inputs,
neutralisiert bösartige System-Übersteuerungen und übergibt bereinigte Sachdaten
an Stufe 2 Werkzeug-Agenten (Robert / Executive).
Inklusive Trusted-Source-Whitelisting (klickbares [T]-Badge).
"""

import os
import sys
import json
import re
import time
import logging
import tempfile
import threading
import unicodedata
from typing import Dict, Any, List, Optional

logger = logging.getLogger("dual_llm_sanitizer")
_TRUST_LOCK = threading.RLock()

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRUSTED_SOURCES_FILE = os.path.join(WORKSPACE_DIR, "data", "trusted_sources.json")

# F-024 (S-4.7): Single Source of Truth für Injection-Muster ist
# `local_security_guard.INJECTION_PATTERNS` (25 Muster inkl. `curl https://`,
# `wget`, `rm -rf`, `drop table`, `<<SYS>>`). Der Quarantäner importiert die
# Liste direkt, statt eine eigene, unvollständige 9-Muster-Liste zu pflegen.
from local_security_guard import INJECTION_PATTERNS

# Die 9 benannten Signaturen bleiben ausschließlich für die Severity-
# Klassifizierung (threat_level "critical") erhalten. Sie werden mit der
# SSOT-Liste vereint, damit keine Erkennung verloren geht (z. B. Base64-,
# Zero-Width- und Role-Delimiter-Muster stehen so nicht in der SSOT-Liste).
_NAMED_INJECTION_SIGNATURES = [
    (r"(?i)ignore\s+(all\s+|any\s+|previous\s+|above\s+)*(instructions|directions|prompts|rules)", "INSTRUCTION_OVERRIDE"),
    (r"(?i)system\s+prompt\s+(override|leak|reveal|show|bypass)", "SYSTEM_PROMPT_TARGETING"),
    (r"(?i)you\s+are\s+now\s+(in\s+developer\s+mode|dan|unrestricted|god\s+mode|jailbroken)", "JAILBREAK_ATTEMPT"),
    (r"(?i)disregard\s+(prior|previous|initial)\s+(rules|constraints|guidelines)", "CONSTRAINT_DISREGARD"),
    (r"(?i)(reveal|display|output|print|echo)\s+(your|the)\s+(initial|original|secret|hidden)\s+(instructions|system\s+prompt|api\s+key|token)", "SECRET_EXTRACTION"),
    (r"(?i)stop\s+being\s+(an?\s+ai|helpful|restricted)", "BEHAVIOR_RESET"),
    (r"(?i)base64:\s*[A-Za-z0-9+/=]{20,}", "ENCODED_PAYLOAD"),
    (r"[\u200B-\u200D\uFEFF]", "ZERO_WIDTH_CHARACTER_INJECTION"),
    (r"(?im)(?:<\|im_start\|>\s*system|<\|system\|>|^\s*(?:###\s*)?SYSTEM\s*:|\[INST\]|</?system>)", "ROLE_DELIMITER_INJECTION"),
]

# Vom Quarantäner tatsächlich gescannte Muster: 25 SSOT + 9 benannte Signaturen.
INJECTION_SIGNATURES = _NAMED_INJECTION_SIGNATURES + list(INJECTION_PATTERNS)

def load_trusted_sources() -> List[str]:
    """Lädt die Whitelist verifizierter Absender/Quellen."""
    if os.path.exists(TRUSTED_SOURCES_FILE):
        try:
            with open(TRUSTED_SOURCES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [s.lower().strip() for s in data if s]
        except Exception as e:
            logger.warning(f"Fehler beim Lesen von trusted_sources.json: {e}")
    return ["intern@archon.local", "system@archon.os", "micha@archon.os"]

def is_trusted_source(source_id: str) -> bool:
    """Prüft, ob eine Quelle/Absender als vertrauenswürdig (Trusted [T]) markiert ist."""
    if not source_id:
        return False
    trusted = load_trusted_sources()
    sid = source_id.lower().strip()
    return sid in trusted or any(sid.endswith(f"@{t}") or sid.endswith(f".{t}") for t in trusted if "@" not in t)

def toggle_trusted_source(source_id: str, operator: str = "operator") -> Dict[str, Any]:
    """Schaltet den Trust-Status für einen Absender um und loggt im GoBD Audit-Log."""
    sid = source_id.lower().strip()
    with _TRUST_LOCK:
        trusted = load_trusted_sources()
        is_now_trusted = False

        if sid in trusted:
            trusted.remove(sid)
            is_now_trusted = False
        else:
            trusted.append(sid)
            is_now_trusted = True

        target_dir = os.path.dirname(TRUSTED_SOURCES_FILE)
        os.makedirs(target_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".trusted_", suffix=".json.tmp", dir=target_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(trusted, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, TRUSTED_SOURCES_FILE)
        except Exception:
            try:
                os.unlink(tmp_path)
            except Exception as _exc:
                logger.debug("[dual_llm_sanitizer] Ignorierte Ausnahme (Z.86): %s", _exc)
            raise

    try:
        from backend.audit_log import chained_audit_log
        chained_audit_log.record_event(
            category="security",
            action="sender_trust_toggled",
            agent_id=operator,
            payload={
                "source_id": sid,
                "is_trusted": is_now_trusted
            }
        )
    except Exception as e:
        logger.warning(f"Audit-Log Fehler bei toggle_trusted_source: {e}")

    return {
        "source_id": sid,
        "is_trusted": is_now_trusted,
        "total_trusted": len(trusted)
    }

def scan_heuristic_threats(text: str) -> List[str]:
    """Scannt Text (inkl. NFKC-Normalisierung gegen Homoglyphen) auf bekannte Injection-Signaturen."""
    found = []
    if not text:
        return found
    norm = unicodedata.normalize("NFKC", text)
    for target in (text, norm):
        for pattern, name in INJECTION_SIGNATURES:
            if re.search(pattern, target) and name not in found:
                found.append(name)
    return found


def sanitize_external_input(raw_text: str, source_id: str = "unknown", source_type: str = "email") -> Dict[str, Any]:
    """
    Stufe 1 Quarantäne-Filterung:
    1. Trusted-Source-Status prüfen (kein blinder Quarantäne-Bypass bei erkannten Injection-Mustern!).
    2. NFKC-Normalisierung + heuristische Signaturprüfung auf Prompt Injection & Delimiter-Spoofing.
    3. Strukturierte Extraktion von reinem Sachinhalt ohne ausführende Instruktionen.
    4. Bei Bedrohung: Blockierung & Eintragung ins revisionssichere GoBD Audit-Log.
    """
    sid = source_id.strip()
    trusted = is_trusted_source(sid)
    normalized_raw = unicodedata.normalize("NFKC", raw_text or "")

    # 1. Heuristische Analyse (auch fuer Trusted Sources gegen Header-Spoofing / Weiterleitungen)
    threats = scan_heuristic_threats(raw_text or "")

    if trusted and not threats:
        return {
            "is_safe": True,
            "threat_level": "none",
            "is_trusted": True,
            "detected_patterns": [],
            "source_id": sid,
            "source_type": source_type,
            "clean_summary": (raw_text or "").strip(),
            "extracted_facts": {"trust_status": "VERIFIED_SENDER"},
            "message": "Quelle ist als vertrauenswürdig [T] verifiziert (ohne Bedrohungssignaturen)."
        }

    # 2. Quarantäne-Bereinigung: Aggressives Entfernen von Instruktionsmustern
    clean_lines = []
    stripped_instructions = []

    for line in normalized_raw.splitlines():
        line_threats = scan_heuristic_threats(line)
        if line_threats:
            stripped_instructions.append(line.strip())
            threats.extend(line_threats)
            continue
        clean_lines.append(line)

    threats = sorted(list(set(threats)))
    is_safe = len(threats) == 0
    threat_level = "critical" if any(t in ("INSTRUCTION_OVERRIDE", "JAILBREAK_ATTEMPT", "SYSTEM_PROMPT_TARGETING") for t in threats) else ("high" if threats else "none")

    clean_summary = "\n".join(clean_lines).strip()
    # Mehrzeilige Injection-Spans (z. B. "ignore all\nprevious instructions") auch gesamt neutralisieren
    if clean_summary:
        for pattern, p_name in INJECTION_SIGNATURES:
            if re.search(pattern, clean_summary):
                if p_name not in threats:
                    threats.append(p_name)
                stripped_instructions.append(f"[MULTILINE:{p_name}]")
                clean_summary = re.sub(pattern, "[INHALT WEGEN SICHERHEITSRISIKEN GEFILTERT]", clean_summary).strip()
        threats = sorted(list(set(threats)))
        is_safe = len(threats) == 0
        threat_level = "critical" if any(t in ("INSTRUCTION_OVERRIDE", "JAILBREAK_ATTEMPT", "SYSTEM_PROMPT_TARGETING") for t in threats) else ("high" if threats else "none")
    if not clean_summary and stripped_instructions:
        clean_summary = "[INHALT WEGEN SICHERHEITSRISIKEN GEFILTERT]"

    # 4. Wenn Bedrohung erkannt: Im Audit-Log protokollieren
    if not is_safe:
        logger.error(f"[DualLLMSanitizer] PROMPT INJECTION BLOCKIERT von {sid} ({threat_level}): {threats}")
        try:
            from backend.audit_log import chained_audit_log
            chained_audit_log.record_event(
                category="security",
                action="prompt_injection_blocked",
                agent_id="dual_llm_sanitizer",
                payload={
                    "source_id": sid,
                    "source_type": source_type,
                    "threat_level": threat_level,
                    "detected_patterns": threats,
                    "neutralized_snippets": stripped_instructions[:3]
                }
            )
        except Exception as e:
            logger.warning(f"Audit-Log Fehler bei Injection-Alert: {e}")

    return {
        "is_safe": is_safe,
        "threat_level": threat_level,
        "is_trusted": False,
        "detected_patterns": threats,
        "source_id": sid,
        "source_type": source_type,
        "clean_summary": clean_summary,
        "neutralized_instructions": stripped_instructions,
        "extracted_facts": {
            "source": sid,
            "char_count": len(raw_text),
            "threats_count": len(threats)
        },
        "warning": None if is_safe else f"Achtung: {len(threats)} verdächtige Manipulations-Muster isoliert ({', '.join(threats)})!"
    }
