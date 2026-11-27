# -*- coding: utf-8 -*-
"""
backend/code_mode_discovery.py
==============================
M109a: Deferred Discovery fuer den Code-Mode-Tool-Loop.

Statt alle MCP-Werkzeuge mit ihren vollstaendigen JSON-Schemas in den
Kontext zu laden, werden hier nur kompakte Faehigkeits-Kurzformen
(``to_brief``) durchsucht. Das volle Schema gibt es erst auf ausdruecklichen
``describe_capability``-Aufruf, die Ausfuehrung ausschliesslich ueber den
Lazy-importierten ``CapabilityBroker``.

Grenzen (bewusst hart, gegen Prompt-Injection und Kontext-Explosion):
- 6 Verschachtelungsebenen, 100 Schluessel, 8000 Zeichen pro String,
  64k JSON-Zeichen pro Argumentpaket.
- Kein Import-Side-Effect: Registry und Broker werden erst bei Bedarf
  aufgebaut. Maskierung, Freigaben und Auditierung bleiben beim Broker bzw.
  bei deren zentralen Modulen und werden hier nicht dupliziert.
"""

from __future__ import annotations

import copy
import importlib
import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("archon.code_mode_discovery")

RISK_LEVELS = ("read", "write", "destructive")

_SUMMARY_MAX = 90
_MAX_DEPTH = 6
_MAX_KEYS = 100
_MAX_STRING = 8000
_MAX_PAYLOAD_CHARS = 64 * 1024

_DESTRUCTIVE_TOKENS = ("delete", "destroy", "remove", "purge", "drop", "erase", "revoke")
_WRITE_TOKENS = (
    "create", "update", "send", "trigger", "run", "start", "execute",
    "write", "set", "apply", "modify", "rotate", "approve", "dispatch",
    "schedule", "publish", "import", "archive",
)
_READ_TOKENS = (
    "read", "list", "get", "search", "metrics", "fetch", "query",
    "describe", "inspect", "count", "check", "export", "view",
)

_CATEGORY_TOKENS = (
    ("crm", ("crm", "contact", "company")),
    ("inbox", ("inbox", "mail", "telegram", "message")),
    ("workflow", ("workflow", "node", "template", "dag", "plugin")),
    ("boardroom", ("boardroom", "debate", "council")),
    ("system", ("system", "metric", "health", "config", "audit")),
    ("approval", ("approval", "request", "policy")),
    ("task", ("task", "kanban", "ticket")),
)


@dataclass(frozen=True)
class Capability:
    """Eine durchsuchbare Faehigkeit mit kompaktem Brief und vollem Schema."""

    name: str
    method: str
    path: str
    category: str
    risk_level: str
    summary: str
    parameters: Dict[str, Any] = field(default_factory=dict)

    @property
    def approval_required(self) -> bool:
        """True fuer schreibende und destruktive Faehigkeiten (Fail-Closed)."""
        return str(self.risk_level or "").strip().lower() != "read"

    def to_brief(self) -> Dict[str, str]:
        """Nur die fünf kompakten Felder — ohne JSON-Schema."""
        return {
            "name": self.name,
            "method": self.method,
            "path": self.path,
            "risk_level": self.risk_level,
            "summary": self.summary,
        }


_capabilities: Dict[str, Capability] = {}
_registry_lock = threading.RLock()
_registry_built = False


def register_capability(cap: Capability) -> None:
    """Registriert eine Faehigkeit idempotent unter ihrem Namen."""
    if not isinstance(cap, Capability):
        logger.warning("[CodeModeDiscovery] Faehigkeit mit falschem Typ ignoriert")
        return
    name = str(cap.name or "").strip()
    if not name:
        logger.warning("[CodeModeDiscovery] Faehigkeit ohne Namen ignoriert")
        return
    with _registry_lock:
        _capabilities[name] = cap


def _risk_from_name(name: str) -> str:
    """Heuristische Risikoklasse aus dem Werkzeugnamen (Fail-Closed)."""
    tokens = [t for t in "".join(c if c.isalnum() else " " for c in name.lower()).split() if t]
    for group, level in ((_DESTRUCTIVE_TOKENS, "destructive"), (_WRITE_TOKENS, "write")):
        if any(tok.startswith(word) for tok in tokens for word in group):
            return level
    if any(tok.startswith(word) for tok in tokens for word in _READ_TOKENS):
        return "read"
    # Unbekannte Aktionen sind genehmigungspflichtig, nicht still als lesend.
    return "write"


def _category_from_name(name: str) -> str:
    """Ordnet den Werkzeugnamen einer groben Domaene zu."""
    lower = name.lower()
    for category, words in _CATEGORY_TOKENS:
        if any(word in lower for word in words):
            return category
    return "general"


def _summary_from_description(description: Any, fallback: str) -> str:
    """Einzeilige, gekuerzte Kurzbeschreibung (max. 90 Zeichen)."""
    text = " ".join(str(description or "").split()) or fallback
    if len(text) > _SUMMARY_MAX:
        return text[: _SUMMARY_MAX - 1] + "…"
    return text


def _ensure_registry() -> None:
    """Baut die Registry beim ersten Bedarf aus den MCP-Definitionen auf."""
    global _registry_built
    if _registry_built:
        return
    with _registry_lock:
        if _registry_built:
            return
        definitions: List[Dict[str, Any]] = []
        try:
            from scripts.archon_mcp_server import ArchonMcpServer

            definitions = list(ArchonMcpServer().get_tool_definitions() or [])
        except Exception as exc:
            # Kein hartes Abbrechen, wenn ein anderes Modul noch fehlt.
            logger.warning("[CodeModeDiscovery] MCP-Definitionen nicht verfuegbar: %s", exc)
        for tool in definitions:
            if not isinstance(tool, dict):
                continue
            name = str(tool.get("name") or "").strip()
            if not name:
                continue
            schema = tool.get("inputSchema")
            if not isinstance(schema, dict):
                schema = {}
            register_capability(Capability(
                name=name,
                method="TOOL",
                path=name,
                category=_category_from_name(name),
                risk_level=_risk_from_name(name),
                summary=_summary_from_description(tool.get("description"), name),
                parameters=copy.deepcopy(schema),
            ))
        _registry_built = True


def build_capability_registry() -> List[Capability]:
    """Liefert die lazy aufgebaute Registry (idempotent, ohne Schema-Dumping)."""
    _ensure_registry()
    with _registry_lock:
        return list(_capabilities.values())


def all_capabilities() -> List[Capability]:
    """Alle bekannten Faehigkeiten — beim ersten Zugriff lazy geladen."""
    return build_capability_registry()


def get_capability(name: str) -> Optional[Capability]:
    """Einzelne Faehigkeit nach exaktem Namen oder ``None``."""
    _ensure_registry()
    with _registry_lock:
        return _capabilities.get(str(name or "").strip())


def search_capabilities(
    query: str,
    category: Optional[str] = None,
    risk_level: Optional[str] = None,
    limit: int = 15,
) -> List[Dict[str, str]]:
    """Substring-Suche ueber Kurzformen; nie die vollen Schemas liefern."""
    try:
        capped = max(1, min(50, int(limit)))
    except (TypeError, ValueError):
        capped = 15
    level = str(risk_level or "").strip().lower() if risk_level else ""
    if level and level not in RISK_LEVELS:
        return []
    cat = str(category or "").strip().lower() if category else ""
    needle = str(query or "").strip().lower()
    hits: List[Dict[str, str]] = []
    _ensure_registry()
    with _registry_lock:
        caps = list(_capabilities.values())
    for cap in sorted(caps, key=lambda c: c.name):
        if level and cap.risk_level != level:
            continue
        if cat and cat not in cap.category.lower():
            continue
        if needle and not any(
            needle in str(value).lower()
            for value in (cap.name, cap.summary, cap.category, cap.path)
        ):
            continue
        hits.append(cap.to_brief())
        if len(hits) >= capped:
            break
    return hits


def describe_capability(name: str) -> Dict[str, Any]:
    """Volle Details inklusive Parameter-Schema — nur auf ausdruecklichen Abruf."""
    cap = get_capability(name)
    if cap is None:
        return {"status": "error", "error": "UNKNOWN_CAPABILITY", "name": str(name or "")}
    return {
        "name": cap.name,
        "method": cap.method,
        "path": cap.path,
        "category": cap.category,
        "risk_level": cap.risk_level,
        "approval_required": cap.approval_required,
        "summary": cap.summary,
        "parameters": copy.deepcopy(cap.parameters),
    }


def _type_ok(value: Any, expected: str) -> bool:
    """Strikte JSON-Typpruefung; ``bool`` gilt nicht als ``integer``."""
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True  # unbekannte Schema-Typen werden nicht erfunden


def _validate_value(
    value: Any,
    schema: Dict[str, Any],
    path: str,
    state: Dict[str, int],
) -> Optional[str]:
    """Rekursive Validierung des JSON-Schema-Subsets; liefert Fehlercode oder None."""
    depth = state["depth"]
    if depth > _MAX_DEPTH:
        return "NESTING_TOO_DEEP"

    expected = schema.get("type")
    if isinstance(expected, dict):
        return "INVALID_SCHEMA"
    if expected is not None and not _type_ok(value, str(expected)):
        return "INVALID_TYPE"

    if isinstance(value, str) and len(value) > _MAX_STRING:
        return "STRING_TOO_LONG"

    enum = schema.get("enum")
    if isinstance(enum, list) and not any(value == item for item in enum):
        return "INVALID_ENUM"

    if isinstance(value, dict):
        state["keys"] += len(value)
        if state["keys"] > _MAX_KEYS:
            return "TOO_MANY_KEYS"
        properties = schema.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    return "UNKNOWN_PROPERTY"
        for key, child in value.items():
            child_schema = properties.get(key)
            if isinstance(child_schema, dict):
                state["depth"] = depth + 1
                error = _validate_value(child, child_schema, f"{path}.{key}", state)
                state["depth"] = depth
                if error:
                    return error
    elif isinstance(value, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for index, child in enumerate(value):
                state["depth"] = depth + 1
                error = _validate_value(child, items, f"{path}[{index}]", state)
                state["depth"] = depth
                if error:
                    return error
    return None


def validate_arguments(
    name_or_cap: Union[str, Capability],
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Strikte Validierung inkl. Defaults; liefert nie eine Exception nach aussen.

    Fehlercodes: ``UNKNOWN_CAPABILITY``, ``INVALID_ARGUMENTS``,
    ``PAYLOAD_TOO_LARGE``, ``NESTING_TOO_DEEP``, ``TOO_MANY_KEYS``,
    ``STRING_TOO_LONG``, ``MISSING_REQUIRED``, ``UNKNOWN_PROPERTY``,
    ``INVALID_TYPE``, ``INVALID_ENUM``, ``INVALID_SCHEMA``.
    """
    failure: Dict[str, Any] = {"ok": False, "arguments": {}, "error": None}
    try:
        cap = name_or_cap if isinstance(name_or_cap, Capability) else get_capability(name_or_cap)
        if cap is None:
            return {**failure, "error": "UNKNOWN_CAPABILITY"}
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return {**failure, "error": "INVALID_ARGUMENTS"}

        def _size(payload: Dict[str, Any]) -> int:
            try:
                return len(json.dumps(payload, ensure_ascii=False, default=str))
            except Exception:
                return _MAX_PAYLOAD_CHARS + 1

        if _size(arguments) > _MAX_PAYLOAD_CHARS:
            return {**failure, "error": "PAYLOAD_TOO_LARGE"}

        clean = dict(arguments)
        schema = cap.parameters if isinstance(cap.parameters, dict) else {}
        properties = schema.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        for key, spec in properties.items():
            if key not in clean and isinstance(spec, dict) and "default" in spec:
                clean[key] = copy.deepcopy(spec["default"])

        state = {"depth": 1, "keys": 0}
        error = _validate_value(clean, {"type": "object", **schema}, "arguments", state)
        if error:
            return {**failure, "error": error}

        required = schema.get("required")
        if isinstance(required, list):
            for key in required:
                if str(key) not in clean:
                    return {**failure, "error": "MISSING_REQUIRED"}

        if _size(clean) > _MAX_PAYLOAD_CHARS:
            return {**failure, "error": "PAYLOAD_TOO_LARGE"}
        return {"ok": True, "arguments": clean, "error": None}
    except Exception as exc:
        logger.warning("[CodeModeDiscovery] Validierung abgebrochen: %s", exc)
        return {**failure, "error": "INVALID_SCHEMA"}


def _resolve_broker(
    broker: Optional[Any],
    agent_id: str,
    session_id: str,
) -> tuple[Optional[Any], Optional[str]]:
    """Lazy-Import des Brokers; nie beim Modulimport."""
    if broker is not None:
        return broker, None
    try:
        module = importlib.import_module("backend.code_mode_capability_broker")
    except Exception as exc:
        logger.warning("[CodeModeDiscovery] CapabilityBroker nicht verfuegbar: %s", exc)
        return None, "BROKER_UNAVAILABLE"
    factory = getattr(module, "get_capability_broker", None)
    if callable(factory):
        try:
            return factory(), None
        except Exception as exc:
            logger.warning("[CodeModeDiscovery] Broker-Factory fehlgeschlagen: %s", exc)
            return None, "BROKER_INIT_FAILED"
    broker_cls = getattr(module, "CapabilityBroker", None)
    if not callable(broker_cls):
        return None, "BROKER_UNAVAILABLE"
    try:
        return broker_cls(), None
    except TypeError:
        try:
            return broker_cls(agent_id=agent_id, session_id=session_id), None
        except Exception as exc:
            logger.warning("[CodeModeDiscovery] Broker-Init fehlgeschlagen: %s", exc)
            return None, "BROKER_INIT_FAILED"
    except Exception as exc:
        logger.warning("[CodeModeDiscovery] Broker-Init fehlgeschlagen: %s", exc)
        return None, "BROKER_INIT_FAILED"


def _validation_error(check: Dict[str, Any]) -> Dict[str, Any]:
    """Einheitlicher Fehlervertrag fuer sync und async Aufrufe."""
    return {
        "status": "error",
        "error_code": "SCHEMA_VALIDATION_FAILED",
        "error": str(check.get("error") or "INVALID_ARGUMENTS"),
    }


def call_capability(
    name: str,
    arguments: Optional[Dict[str, Any]] = None,
    *,
    broker: Optional[Any] = None,
    agent_id: str = "",
    session_id: str = "default_session",
    approval_id: Optional[str] = None,
    requester: str = "",
) -> Dict[str, Any]:
    """Validiert strikt und ruft ``broker.invoke_sync`` (nie bei Validierungsfehler)."""
    check = validate_arguments(name, arguments or {})
    if not check.get("ok"):
        return _validation_error(check)
    resolved, error = _resolve_broker(broker, agent_id, session_id)
    if error:
        return {"status": "error", "error_code": error, "error": str(name or "")}
    if resolved is None:
        return {"status": "error", "error_code": "BROKER_UNAVAILABLE", "error": str(name or "")}
    try:
        result = resolved.invoke_sync(
            name,
            check["arguments"],
            agent_id=str(agent_id or ""),
            session_id=str(session_id or "default_session"),
            approval_id=approval_id,
            requester=str(requester or ""),
        )
        if not isinstance(result, dict):
            return {"status": "error", "error_code": "BROKER_INVALID_RESULT", "error": str(name or "")}
        return result
    except Exception as exc:
        logger.warning("[CodeModeDiscovery] Broker-Aufruf fehlgeschlagen: %s", exc)
        return {"status": "error", "error_code": "BROKER_ERROR", "error": str(exc)[:300]}


async def acall_capability(
    name: str,
    arguments: Optional[Dict[str, Any]] = None,
    *,
    broker: Optional[Any] = None,
    agent_id: str = "",
    session_id: str = "default_session",
    approval_id: Optional[str] = None,
    requester: str = "",
) -> Dict[str, Any]:
    """Async Variante zu ``call_capability`` ueber ``broker.invoke``."""
    check = validate_arguments(name, arguments or {})
    if not check.get("ok"):
        return _validation_error(check)
    resolved, error = _resolve_broker(broker, agent_id, session_id)
    if error:
        return {"status": "error", "error_code": error, "error": str(name or "")}
    if resolved is None:
        return {"status": "error", "error_code": "BROKER_UNAVAILABLE", "error": str(name or "")}
    try:
        result = await resolved.invoke(
            name,
            check["arguments"],
            agent_id=str(agent_id or ""),
            session_id=str(session_id or "default_session"),
            approval_id=approval_id,
            requester=str(requester or ""),
        )
        if not isinstance(result, dict):
            return {"status": "error", "error_code": "BROKER_INVALID_RESULT", "error": str(name or "")}
        return result
    except Exception as exc:
        logger.warning("[CodeModeDiscovery] Broker-Aufruf (async) fehlgeschlagen: %s", exc)
        return {"status": "error", "error_code": "BROKER_ERROR", "error": str(exc)[:300]}


# Drei sehr kompakte Meta-Tools: genau genug fuer den Deferred-Discovery-Loop.
CODE_MODE_META_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "search_capabilities",
        "description": "Sucht registrierte Archon-Faehigkeiten als kompakte Kurzformen mit Name, Methode, Pfad, Risikoklasse und Einzeilenbeschreibung. Die Suche ist eine case-insensitive Substring-Suche ueber Name, Beschreibung, Kategorie und Pfad. Volle Parameter-Schemas werden absichtlich nicht geliefert; dafuer ist describe_capability zuständig. Die Treffer enthalten ausschliesslich die Felder name, method, path, risk_level und summary und sind nach Namen sortiert. Die Ergebnisliste ist auf 15 Eintraege voreingestellt und hart auf 50 begrenzt.",
        "inputSchema": {
            "type": "object",
            "description": "Kompakte Suche ohne Schema-Dumping; die Filter werden kombiniert und liefern hoechstens limit Treffer.",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Suchbegriff als Substring; ein leerer Begriff liefert alle Faehigkeiten.",
                },
                "category": {
                    "type": "string",
                    "description": "Optionaler Substring-Filter auf die Domaenen-Kategorie.",
                },
                "risk_level": {
                    "type": "string",
                    "enum": ["read", "write", "destructive"],
                    "description": "Optionaler Risiko-Filter; ungueltige Werte liefern keine Treffer.",
                },
                "limit": {
                    "type": "integer",
                    "default": 15,
                    "minimum": 1,
                    "maximum": 50,
                    "description": "Maximale Anzahl Treffer, auf den Bereich 1 bis 50 begrenzt.",
                },
            },
        },
    },
    {
        "name": "describe_capability",
        "description": "Liefert die vollen Details einer einzelnen Faehigkeit einschliesslich des vollstaendigen JSON-Parameter-Schemas und der Freigabepflicht. Nur bei konkretem Bedarf aufrufen, da die Antwort den Kontext stark belegt. Bei unbekanntem Namen wird ein strukturierter Fehler mit dem Code UNKNOWN_CAPABILITY zurueckgegeben. Die Antwort enthaelt name, method, path, category, risk_level, approval_required, summary und parameters.",
        "inputSchema": {
            "type": "object",
            "description": "Einzelabruf mit vollem Parameter-Schema und Freigabestatus.",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Exakter Faehigkeitsname, wie ihn search_capabilities zurueckgibt.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "call_capability",
        "description": "Fuehrt eine Faehigkeit nach strikter Schema-Validierung ueber den zentralen CapabilityBroker aus. Argumente werden gegen das Schema der Faehigkeit geprueft; Defaults werden ergaenzt, unbekannte Felder nur bei additionalProperties=false abgelehnt. Schreibende und destruktive Faehigkeiten benoetigen eine Freigabe. Validierungsfehler verhindern den Broker-Aufruf vollstaendig. Die Argumente unterliegen harten Grenzen: maximale Tiefe 6, 100 Schluessel, 8000 Zeichen pro String und 64k JSON-Zeichen gesamt; Booleans zaelen nicht als ganze Zahlen. Fehler werden als status=error mit error_code zurueckgegeben. approval_id und requester werden unveraendert an den Broker durchgereicht; dort liegen Freigabe-, Maskierungs- und Audit-Logik.",
        "inputSchema": {
            "type": "object",
            "description": "Strikt validierter Broker-Aufruf mit Freigabe- und Audit-Kette.",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name der aufzurufenden Faehigkeit.",
                },
                "arguments": {
                    "type": "object",
                    "description": "Argumentobjekt gemaess dem Schema von describe_capability.",
                },
                "agent_id": {
                    "type": "string",
                    "description": "Agenten-ID fuer Policy-Pruefung und Audit-Kette.",
                },
                "session_id": {
                    "type": "string",
                    "default": "default_session",
                    "description": "Session-ID fuer Policy und Taint-Guard.",
                },
                "approval_id": {
                    "type": "string",
                    "description": "Freigabe-ID bei genehmigungspflichtigen Aufrufen.",
                },
                "requester": {
                    "type": "string",
                    "description": "Menschlicher Ausloeser der Freigabe.",
                },
            },
            "required": ["name"],
        },
    },
]


__all__ = [
    "RISK_LEVELS",
    "Capability",
    "register_capability",
    "get_capability",
    "all_capabilities",
    "build_capability_registry",
    "search_capabilities",
    "describe_capability",
    "validate_arguments",
    "call_capability",
    "acall_capability",
    "CODE_MODE_META_TOOLS",
]
