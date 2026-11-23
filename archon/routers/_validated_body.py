"""Gemeinsame Pydantic-Basis fuer die restlichen Body-Endpunkte.

Audit 23.11.2026 / API_VALIDATION_ROADMAP: einheitliche, minimal-intrusive
Migration. `extra="ignore"` entspricht der Kompatibilitaetsregel der Roadmap;
Endpunkte, die den kompletten Payload weiterreichen, leiten daraus eine Klasse
mit `extra="allow"` ab.

`as_payload()` ist tolerant gegenueber internen/direkten Aufrufern, die weiter
Dicts uebergeben (Tests, Helfer) — die HTTP-Validierung bleibt aktiv.
"""
from typing import Any, Dict

from pydantic import BaseModel, ConfigDict


class TypedBody(BaseModel):
    model_config = ConfigDict(extra="ignore")


class PassthroughBody(BaseModel):
    """Fuer Handler, die den kompletten Payload an Services weitergeben."""
    model_config = ConfigDict(extra="allow")


def as_payload(value, exclude_none: bool = False) -> Dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=exclude_none)
    return dict(value)
