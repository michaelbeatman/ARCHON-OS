"""
backend/secret_masker.py
Secret-Masking & Red-Teaming Output Guard (Pillar 6 / Zero-Trust).
Scannt Textausgaben von Modellen und Agenten auf vertrauliche API-Keys,
Passwörter, JWT-Token oder private Zugangsdaten und maskiert diese vor der Weitergabe.
"""
import logging

_archon_exc_logger = logging.getLogger("secret_masker")

import os  # noqa: E402
import re  # noqa: E402
from typing import Tuple  # noqa: E402

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SECRET_PATTERNS = [
    # Anthropic Keys vor generischem sk- prüfen, damit das spezifischere Label greift
    (r'sk-ant-[a-zA-Z0-9_\-]{20,}', '[GESCHÜTZTER_ANTHROPIC_KEY]'),
    # OpenAI / OpenRouter Keys
    (r'sk-[a-zA-Z0-9_\-]{20,}', '[GESCHÜTZTER_API_KEY]'),
    # Bearer Tokens
    (r'Bearer\s+[a-zA-Z0-9_\-\.\/]{24,}', 'Bearer [GESCHÜTZTES_BEARER_TOKEN]'),
    # JWT Tokens (3 Base64 Blöcke mit Punkten getrennt)
    (r'eyJ[a-zA-Z0-9_\-]{10,}\.eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}', '[GESCHÜTZTES_JWT_TOKEN]'),
    # Private Keys
    (r'-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+PRIVATE KEY-----', '[GESCHÜTZTER_PRIVATE_KEY]'),
    # Passwörter in Verbindungsstrings (z.B. postgres://user:password@host, kein Whitespace/Zeilenumbruch-Span)
    (r'://([^\s:/@]+):([^\s/@]+)@', r'://\1:[GESCHÜTZTES_PASSWORT]@'),
    # Telegram Bot Tokens (z.B. 123456789:ABCdefGhI...)
    (r'\b\d{8,10}:[a-zA-Z0-9_-]{35}\b', '[GESCHÜTZTER_TELEGRAM_TOKEN]'),
    # Weitere gaengige Provider-Formate (GitHub, Google, AWS, Slack)
    (r'\bgh[pousr]_[A-Za-z0-9]{20,}\b', '[GESCHÜTZTER_GITHUB_TOKEN]'),
    (r'\bAIza[0-9A-Za-z_\-]{35}\b', '[GESCHÜTZTER_GOOGLE_API_KEY]'),
    (r'\bAKIA[0-9A-Z]{16}\b', '[GESCHÜTZTER_AWS_KEY]'),
    (r'\bxox[baprs]-[A-Za-z0-9-]{10,}\b', '[GESCHÜTZTER_SLACK_TOKEN]'),
    # Eigene Archon-Formate (vorher unmaskiert in Logs/LLM-Kontext)
    (r'\barchon_live_[0-9a-f]{48}\b', '[GESCHÜTZTER_ARCHON_API_KEY]'),
    (r'\btok_[0-9a-f]{32}_[0-9a-f]{12}\b', '[GESCHÜTZTER_ARCHON_SESSION_TOKEN]'),
]


def _env_secret_literals() -> list:
    """Exakte Literale aller ENV-Secrets (ohne die Werte zu loggen).

    Regex-Muster erfassen nicht ARCHON_SERVICE_TOKEN, N8N_* oder
    ANYTHINGLLM_API_KEY. Diese Werte werden direkt aus der Umgebung
    geholt und als Literal ersetzt.
    """
    literals = []
    for name, value in os.environ.items():
        upper = name.upper()
        if not any(k in upper for k in ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH")):
            continue
        if not isinstance(value, str) or len(value.strip()) < 8:
            continue
        if value.strip().lower() in ("true", "false", "none", "default", "your_anythingllm_api_key_here"):
            continue
        literals.append(value.strip())
    # Datei-basierte Secrets (nicht in ENV) ebenfalls als Literale erfassen
    for path in (
        os.path.join(WORKSPACE_DIR, "data", ".archon_service_token"),
        os.path.join(WORKSPACE_DIR, "data", "warrant_hmac.key"),
        os.path.join(WORKSPACE_DIR, ".archon_initial_admin_password"),
    ):
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    val = fh.read().strip()
                if len(val) >= 8:
                    literals.append(val)
        except Exception:
            pass
    return literals

def mask_sensitive_text(text: str) -> Tuple[str, int]:
    """
    Scannt den Eingabetext auf vertrauliche Zugangsdaten und ersetzt sie.

    D04-H2: Maskierung ist **nicht abschaltbar**. Ein `secret_masking_enabled=false`
    in settings.json wird bewusst ignoriert: Es gibt keinen Pfad, der Klartext
    mit `count=0` als „Erfolg" zurückgibt. `count=0` bedeutet ausschließlich,
    dass der geprüfte Text tatsächlich keine Secrets enthielt.

    D04-H2: Bei einem Maskierungsfehler wird hart abgebrochen (fail-closed),
    statt den ungeprüften Text an den Aufrufer durchzureichen.

    Gibt (bereinigter_text, anzahl_maskierungen) zurück.
    """
    if not text or not isinstance(text, str):
        return text, 0

    try:
        masked_text = text
        total_replacements = 0

        for pattern, replacement in SECRET_PATTERNS:
            matches = list(re.finditer(pattern, masked_text))
            if matches:
                total_replacements += len(matches)
                masked_text = re.sub(pattern, replacement, masked_text)

        for literal in _env_secret_literals():
            if literal in masked_text:
                total_replacements += masked_text.count(literal)
                masked_text = masked_text.replace(literal, "[GESCHÜTZTER_UMGEBUNG_SECRET]")
    except Exception as exc:
        _archon_exc_logger.error("[secret_masker] Maskierung fehlgeschlagen (fail-closed): %s", exc)
        raise RuntimeError(f"secret_masking_failed: {exc}") from exc

    return masked_text, total_replacements
