"""
Standard-Rollen-Definitionen für Archon OS.

D15/F-20: Der fruehere, parallele Katalog mit 28 hartcodierten `DEFAULT_ROLES`
existiert nicht mehr. Er stand im Widerspruch zur 71-Profil-SSOT
(`agent_profiles.json`): zwei IDs kollidierten bei unterschiedlichem Namen und
vollstaendig anderem Prompt, die restlichen Rollen waren fachliche Duplikate
und trugen keine `negative_scope`.

Die Projektion wird jetzt zur Laufzeit aus der SSOT erzeugt. `DEFAULT_ROLES`
bleibt als Kompatibilitaetsname fuer bestehende Importe, enthaelt aber keine
eigenstaendige Taxonomie mehr — aendern wird ausschliesslich
`agent_profiles.json` (via `scripts/sync_profile_ssot.py`).
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from archon.core.runtime import APP_ROOT

DEFAULT_ROLES_FIELDS = (
    "id", "name", "person_name", "callsign", "category", "description",
    "prompt", "system_prompt", "negative_scope", "skills", "status", "tools",
    "avatar", "avatar_url", "model", "provider", "reasoning_level", "is_favorite",
)


def load_default_roles() -> List[Dict[str, Any]]:
    """Liefert die Rollen-Projektion aus der SSOT — nie einen eigenen Katalog.

    Fehlt die SSOT, wird bewusst eine leere Liste geliefert: ein erfundenes
    Fallback-Profil mit erfundenem Prompt waere ein Silent Failure (S-1.7).
    """
    path = os.path.join(APP_ROOT, "agent_profiles.json")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    rows: List[Dict[str, Any]] = []
    for profile in data:
        if not isinstance(profile, dict) or not profile.get("id"):
            continue
        row = {field: profile.get(field) for field in DEFAULT_ROLES_FIELDS if field in profile}
        row.setdefault("prompt", row.get("system_prompt") or "")
        rows.append(row)
    return rows


# Kompatibilitaetsalias: kein statischer 28-Rollen-Katalog mehr, sondern eine
# Laufzeitprojektion der kanonischen 71 Profile.
DEFAULT_ROLES: List[Dict[str, Any]] = load_default_roles()

__all__ = ["DEFAULT_ROLES", "DEFAULT_ROLES_FIELDS", "load_default_roles"]
