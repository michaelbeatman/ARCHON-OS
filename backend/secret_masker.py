"""
backend/secret_masker.py
Secret-Masking & Red-Teaming Output Guard (Pillar 6 / Zero-Trust).
Scannt Textausgaben von Modellen und Agenten auf vertrauliche API-Keys,
Passwörter, JWT-Token oder private Zugangsdaten und maskiert diese vor der Weitergabe.
"""

import re
from typing import Tuple

SECRET_PATTERNS = [
    # OpenAI / OpenRouter / Anthropic Keys
    (r'sk-[a-zA-Z0-9_\-]{20,}', '[GESCHÜTZTER_API_KEY]'),
    (r'sk-ant-[a-zA-Z0-9_\-]{20,}', '[GESCHÜTZTER_ANTHROPIC_KEY]'),
    # Bearer Tokens
    (r'Bearer\s+[a-zA-Z0-9_\-\.\/]{24,}', 'Bearer [GESCHÜTZTES_BEARER_TOKEN]'),
    # JWT Tokens (3 Base64 Blöcke mit Punkten getrennt)
    (r'eyJ[a-zA-Z0-9_\-]{10,}\.eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}', '[GESCHÜTZTES_JWT_TOKEN]'),
    # Private Keys
    (r'-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+PRIVATE KEY-----', '[GESCHÜTZTER_PRIVATE_KEY]'),
    # Passwörter in Verbindungsstrings (z.B. postgres://user:password@host)
    (r'://([^:]+):([^@]+)@', r'://\1:[GESCHÜTZTES_PASSWORT]@'),
    # Telegram Bot Tokens (z.B. 123456789:ABCdefGhI...)
    (r'\b\d{8,10}:[a-zA-Z0-9_-]{35}\b', '[GESCHÜTZTER_TELEGRAM_TOKEN]')
]

def mask_sensitive_text(text: str) -> Tuple[str, int]:
    """
    Scannt den Eingabetext auf vertrauliche Zugangsdaten und ersetzt sie.
    Berücksichtigt den Schalter secret_masking_enabled in settings.json.
    Gibt (bereinigter_text, anzahl_maskierungen) zurück.
    """
    if not text or not isinstance(text, str):
        return text, 0

    try:
        from backend.autonomy_settings import get_module_config
        cfg = get_module_config("fleet_and_hygiene")
        if not cfg.get("secret_masking_enabled", True):
            return text, 0
    except Exception:
        pass

    masked_text = text
    total_replacements = 0

    for pattern, replacement in SECRET_PATTERNS:
        matches = list(re.finditer(pattern, masked_text))
        if matches:
            total_replacements += len(matches)
            masked_text = re.sub(pattern, replacement, masked_text)

    return masked_text, total_replacements
