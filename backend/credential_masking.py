"""Zentrale Maskierung fuer Credentials (M98).

Masken sind die einzige erlaubte Darstellung von Secrets in API-Responses und
im Frontend. Werte werden nicht geloggt, nicht in Exceptions aufgenommen und
nicht als Klartext zurueckgegeben. Die bewusste Einmalanzeige des frisch
erzeugten Archon-Tokens (``create_key``/``rotate_key``) ist die einzige
Ausnahme und darf nie in Listen- oder Aggregationsendpunkte gelangen.
"""

from __future__ import annotations

_VISIBLE_EDGE_CHARS = 4
# Erst ab 12 Zeichen bleiben nach der Maskierung mindestens vier Zeichen verborgen.
_MIN_MASKABLE_LENGTH = 12
_FULL_MASK = "••••••••"


def mask_secret(value: object | None, *, separator: str = "…") -> str:
    """Gibt maximal vier Zeichen am Anfang und am Ende eines Secrets frei.

    Kurze Werte werden vollstaendig maskiert. ``None``/leere Werte ergeben einen
    leeren String. ``str()`` des Wertes wird gegen Exceptions abgesichert; der
    Fehlertext wird bewusst verworfen, damit kein Secret in Logs oder
    Exception-Meldungen gelangt.
    """
    if value is None:
        return ""
    try:
        text = str(value)
    except Exception:
        return _FULL_MASK
    if not text:
        return ""
    if len(text) < _MIN_MASKABLE_LENGTH:
        return _FULL_MASK
    sep = separator if separator and len(separator) <= 4 else "…"
    return f"{text[:_VISIBLE_EDGE_CHARS]}{sep}{text[-_VISIBLE_EDGE_CHARS:]}"
