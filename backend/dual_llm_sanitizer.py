"""
backend/dual_llm_sanitizer.py
Archon OS 2026 - Dual-LLM Guard gegen Prompt Injection (t-d3f2d2)
Stufe 1 Quarantäne-Modell isoliert externe E-Mails, Websites und Chat-Inputs,
neutralisiert bösartige System-Übersteuerungen und übergibt bereinigte Sachdaten
an Stufe 2 Werkzeug-Agenten (Robert / Executive).
Inklusive Trusted-Source-Whitelisting (klickbares [T]-Badge).
"""

import json
import logging
import os
import re
import tempfile
import threading
import unicodedata
from typing import Any, Dict, List, Optional

logger = logging.getLogger("dual_llm_sanitizer")
_TRUST_LOCK = threading.RLock()

# D04-M2/D12-M5 (W2-C): Audit-Schreibfehler nie verschlucken.
_AUDIT_ERROR_COUNTS: Dict[str, int] = {}


def _audit_strict() -> bool:
    raw = str(os.environ.get("ARCHON_AUDIT_STRICT", "1") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off", "none"}


def _record_audit_error(action: str, exc: BaseException) -> None:
    _AUDIT_ERROR_COUNTS[action] = _AUDIT_ERROR_COUNTS.get(action, 0) + 1
    logger.error(
        "[dual_llm_sanitizer] Audit-Event '%s' fehlgeschlagen (count=%d): %s",
        action, _AUDIT_ERROR_COUNTS[action], exc,
    )


class TrustedSources(list):
    """Whitelist mit Verifikationsnachweis (list-kompatibel für bestehende Konsumenten).

    ``verified=True`` bedeutet ausschließlich: die Registry wurde erfolgreich
    gelesen und geparst. Bei jedem Lese-/Parsefehler bleibt die Liste LEER und
    ``trust_verification_error`` ist gesetzt — damit darf keine Quelle als
    ``VERIFIED_SENDER`` ausgegeben werden (Fail-Closed, §0/§2.5).
    """

    def __init__(self, sources: List[str], *, verified: bool, trust_verification_error: Optional[str] = None):
        super().__init__(sources)
        self.verified = verified
        self.trust_verification_error = trust_verification_error


WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRUSTED_SOURCES_FILE = os.path.join(WORKSPACE_DIR, "data", "trusted_sources.json")

# F-024 (S-4.7): Single Source of Truth für Injection-Muster ist
# `local_security_guard.INJECTION_PATTERNS` (25 Muster inkl. `curl https://`,
# `wget`, `rm -rf`, `drop table`, `<<SYS>>`). Der Quarantäner importiert die
# Liste direkt, statt eine eigene, unvollständige 9-Muster-Liste zu pflegen.
from local_security_guard import INJECTION_PATTERNS  # noqa: E402

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

def load_trusted_sources() -> TrustedSources:
    """Lädt die Whitelist verifizierter Absender/Quellen (Fail-Closed).

    D12-M5/D04-M2 (W2-C): früher lieferte jeder Registry-Fehler eine
    hartcodierte Whitelist (``intern@archon.local``, ``system@archon.os``,
    ``micha@archon.os``) — Quellen wurden damit ohne Verifikation als
    ``VERIFIED_SENDER`` markiert. Jetzt gilt: nur bei erfolgreich gelesener
    und geparster Registry werden Einträge zurückgegeben; bei Fehler eine
    LEERE Liste plus ``trust_verification_error``.
    """
    if not os.path.exists(TRUSTED_SOURCES_FILE):
        err = "trust_registry_missing"
        logger.error("[dual_llm_sanitizer] %s: keine verifizierte Trust-Registry vorhanden", err)
        return TrustedSources([], verified=False, trust_verification_error=err)
    try:
        with open(TRUSTED_SOURCES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("trust registry muss eine JSON-Liste sein")
        sources = [
            s.lower().strip() for s in data
            if isinstance(s, str) and s.strip()
        ]
        return TrustedSources(sources, verified=True)
    except Exception as e:
        err = f"trust_registry_unreadable: {e}"
        logger.error("[dual_llm_sanitizer] %s: %s", err, TRUSTED_SOURCES_FILE)
        # Fail-Closed: keine Quelle ist verifiziert.
        return TrustedSources([], verified=False, trust_verification_error=err)


def is_trusted_source(source_id: str) -> bool:
    """Prüft, ob eine Quelle/Absender als vertrauenswürdig (Trusted [T]) markiert ist.

    Bei Registry-Fehler (leere Liste + ``trust_verification_error``) ist keine
    Quelle verifiziert — auch nicht die früher hartcodierten Absender.
    """
    if not source_id:
        return False
    trusted = load_trusted_sources()
    # Explizit gesetzter Registry-Fehler -> keine Vertrauensaussage erlauben.
    # (`verified` defaultet auf True, damit einfache Listen-Mocks kompatibel
    # bleiben; die echte Registry setzt es bei Fehler auf False.)
    if getattr(trusted, "trust_verification_error", None) or getattr(trusted, "verified", True) is False:
        return False
    sid = source_id.lower().strip()
    return sid in trusted or any(sid.endswith(f"@{t}") or sid.endswith(f".{t}") for t in trusted if "@" not in t)

def toggle_trusted_source(source_id: str, operator: str = "operator") -> Dict[str, Any]:
    """Schaltet den Trust-Status um — Audit VOR der Registry-Änderung (W2-C).

    D04-M2/D12-M5: der signierte Audit-Eintrag wird VOR dem Atomar-Schreiben
    der Whitelist erzeugt. Schlägt er fehl, wird die Änderung gar nicht erst
    angewandt (strengste Form des „Toggle zurücknehmen") und bei
    ``ARCHON_AUDIT_STRICT=1`` (Default) mit ``RuntimeError("audit_write_failed")``
    eskaliert. Eine nicht verifizierbare Registry wird ebenfalls hart
    abgelehnt, damit ein Toggle nicht eine fehlerhafte Datei überschreibt.
    """
    sid = source_id.lower().strip()
    with _TRUST_LOCK:
        registry = load_trusted_sources()
        err = getattr(registry, "trust_verification_error", None)
        # Fehlt die Datei, darf ein Admin sie mit diesem Toggle anlegen.
        # Existiert sie, aber ist unlesbar/ungültig -> fail-closed.
        if err and not err.startswith("trust_registry_missing"):
            raise RuntimeError(f"trust_registry_unverified: {err}")
        trusted = list(registry)
        is_now_trusted = False

        if sid in trusted:
            trusted.remove(sid)
            is_now_trusted = False
        else:
            trusted.append(sid)
            is_now_trusted = True

        # Signierten Nachweis VOR der Zustandsänderung schreiben (§2.5).
        # Bei Auditfehler bleibt die Registry unverändert; im Strict-Modus
        # (Default) wird hart abgebrochen.
        try:
            from backend.audit_log import chained_audit_log
            chained_audit_log.record_event(
                category="security",
                action="sender_trust_toggled",
                agent_id=operator,
                payload={
                    "source_id": sid,
                    "is_trusted": is_now_trusted,
                },
            )
        except Exception as e:
            _record_audit_error("sender_trust_toggled", e)
            if _audit_strict():
                raise RuntimeError("audit_write_failed") from e
            # Expliziter Opt-out (ARCHON_AUDIT_STRICT=0): Fehler bleibt
            # gezaehlt/gesehen, der Toggle wird wie zuvor angewandt.

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

        return {
            "source_id": sid,
            "is_trusted": is_now_trusted,
            "total_trusted": len(trusted),
        }

def scan_heuristic_threats(text: str) -> List[str]:
    """Scannt Text (inkl. NFKC-Normalisierung gegen Homoglyphen) auf bekannte Injection-Signaturen."""
    found: List[str] = []
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
    # D12-M5: `VERIFIED_SENDER` ist eine Verifikationsaussage und darf nur bei
    # erfolgreich gelesener Registry entstehen. Bei Registry-Fehler (leere
    # Liste + trust_verification_error) bleibt `trusted` false.
    registry = load_trusted_sources()
    registry_verified = bool(
        getattr(registry, "verified", True)
        and not getattr(registry, "trust_verification_error", None)
    )
    trusted = registry_verified and is_trusted_source(sid)
    normalized_raw = unicodedata.normalize("NFKC", raw_text or "")

    # Audit D04/HIGH: zwingende Dual-LLM-Quarantine. Die bisherige Stufe-1-
    # Heuristik allein hat den zweiten Klassifikator nie aufgerufen.
    from local_security_guard import quarantine_external_text
    q = quarantine_external_text(raw_text or "", source_id=sid or "unknown", source_type=source_type)
    q_blocked = str(q.get("verdict") or "").lower() == "blocked"

    # 1. Heuristische Analyse (auch fuer Trusted Sources gegen Header-Spoofing / Weiterleitungen)
    threats = scan_heuristic_threats(raw_text or "")

    if trusted and not threats and not q_blocked:
        return {
            "is_safe": True,
            "threat_level": "none",
            "is_trusted": True,
            "detected_patterns": [],
            "source_id": sid,
            "source_type": source_type,
            "clean_summary": (raw_text or "").strip(),
            "extracted_facts": {"trust_status": "VERIFIED_SENDER"},
            "llm_verdict": q.get("llm_verdict"),
            "llm_classification_executed": bool(q.get("llm_classification_executed")),
            "message": "Quelle ist als vertrauenswürdig [T] verifiziert (ohne Bedrohungssignaturen), dual-LLM-klassifiziert."
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
    is_safe = len(threats) == 0 and not q_blocked
    if q_blocked:
        threats.append("LLM_CLASSIFIER_BLOCKED")
        threats = sorted(list(set(threats)))
    threat_level = "critical" if q_blocked or any(t in ("INSTRUCTION_OVERRIDE", "JAILBREAK_ATTEMPT", "SYSTEM_PROMPT_TARGETING") for t in threats) else ("high" if threats else "none")

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
        is_safe = len(threats) == 0 and not q_blocked
        threat_level = "critical" if q_blocked or any(t in ("INSTRUCTION_OVERRIDE", "JAILBREAK_ATTEMPT", "SYSTEM_PROMPT_TARGETING") for t in threats) else ("high" if threats else "none")
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
            # §0/§2.5: verschlucktes Audit-Event mindestens sichtbar machen.
            _record_audit_error("prompt_injection_blocked", e)

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
        "llm_verdict": q.get("llm_verdict"),
        "llm_classification_executed": bool(q.get("llm_classification_executed")),
        "warning": None if is_safe else f"Achtung: {len(threats)} verdächtige Manipulations-Muster isoliert ({', '.join(threats)})!"
    }
