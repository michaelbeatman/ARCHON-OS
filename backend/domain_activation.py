"""
backend/domain_activation.py
============================
H-2: Laufzeit-Consumer fuer die im Onboarding gewaehlten aktiven Fachdomaenen.

Vorher wurden ``active_domains`` / ``specialist_domains`` nur in settings.json
geschrieben — kein Runtime-Pfad las sie. Damit war die Domain-Aktivierung
Dekoration. Dieses Modul ist der zentrale, fail-open Consumer:

  * Keine ``active_domains`` konfiguriert  -> ALLE Profile aktiv (Default,
    rueckwaerts kompatibel mit bestehenden Installationen und Tests).
  * ``active_domains`` gesetzt             -> nur Profile aus den aktiven
    Kategorien werden im Fleet/Chat/Boardroom angeboten.

Der Filter ist bewusst NUR auf Anzeige-/Auswahl-Ebene (Profil-Liste), nicht
auf dem Dispatcher selbst: ein bereits gestarteter Task darf nicht mitten
in der Ausfuehrung verschwinden.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_settings() -> Dict[str, Any]:
    for path in (
        os.path.join(WORKSPACE_DIR, "agent_workspace", "settings.json"),
        os.path.join(WORKSPACE_DIR, "settings.json"),
        "/app/agent_workspace/settings.json",
        "/app/settings.json",
    ):
        if not os.path.exists(path):
            continue
        try:
            import json
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}


def active_domain_ids() -> List[str]:
    """Liste aktiver Domain-IDs; leer = 'alles aktiv' (Default)."""
    s = _load_settings()
    raw = s.get("active_domains")
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def _domain_key(category: str) -> str:
    """'1. Strategie, Führung & Lebensplanung' -> '1' (stabil ueber EN/DE)."""
    return str(category or "").strip().split(".", 1)[0]


def is_domain_active(profile: Dict[str, Any], active_ids: Optional[Iterable[str]] = None) -> bool:
    ids = list(active_ids) if active_ids is not None else active_domain_ids()
    if not ids:
        return True
    cat = str(profile.get("category") or profile.get("category_en") or "")
    key = _domain_key(cat)
    return key in {str(x).strip().split(".", 1)[0] for x in ids}


def filter_active_profiles(
    profiles: List[Dict[str, Any]], active_ids: Optional[Iterable[str]] = None
) -> List[Dict[str, Any]]:
    """Filtert Profile auf aktive Domains; fail-open wenn nichts konfiguriert."""
    ids = list(active_ids) if active_ids is not None else active_domain_ids()
    if not ids:
        return profiles
    return [p for p in profiles if is_domain_active(p, ids)]
