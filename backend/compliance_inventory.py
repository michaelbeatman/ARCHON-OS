"""M68 — Compliance-Inventar, DPIA-Register, Retention & Audit-Replay.

Schoen lesbare, versionierte Compliance-Artefakte ohne neue Datenbanktabelle:

* ``build_inventory``          — Tenant-Inventar (Agent -> Datenklasse -> Ziel -> Freigabestufe -> Retention)
                                  aus agent_profiles.json / roles.json / config/org_hierarchy.json /
                                  data_classifier.py / approval_policy_engine.py (nur lesend).
* ``DPIARegister``             — Art.-35-DSGVO-Register als versionierte YAML-Datei mit
                                  Hash-Fingerprint und Change-Trigger bei neuen Modellen/Datenklassen.
* ``RETENTION_MAP``            — Aufbewahrungsfristen je Log-Kategorie (GoBD 10 Jahre vs. Betriebs-Logs).
* ``pseudonymize_*``           — deterministische Feldpseudonymisierung; keine Klartexte in Exporten.
* ``replay_from_ledger``       — Audit-Replay gegen ``backend.event_ledger.replay_events`` /
                                  ``verify_ledger`` (M112) mit sauberem Fallback auf
                                  ``chained_audit_log.list_events``; Reihenfolge- und Lueckenpruefung.
* ``export_policy_*``          — einseitiger Policy-Export (Markdown/PDF, vorhandene Libs).
* ``annotate_artifact``        — Art.-50-KI-Kennzeichnung fuer agentenerstellte Artefakte.

Alle Funktionen sind read-only gegenueber der SSOT; das DPIA-Register ist die einzige
beschriebene Datei und liegt unter ``config/``.
"""

from __future__ import annotations

import datetime
import hashlib
import importlib
import inspect
import json
import logging
import os
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

import yaml

logger = logging.getLogger("archon.compliance_inventory")

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_FILE = os.path.join(WORKSPACE_DIR, "agent_profiles.json")
ROLES_FILE = os.path.join(WORKSPACE_DIR, "roles.json")
ORG_HIERARCHY_FILE = os.path.join(WORKSPACE_DIR, "config", "org_hierarchy.json")
DPIA_REGISTER_FILE = os.path.join(WORKSPACE_DIR, "config", "dpia_register.yaml")

GENESIS_HASH = "0" * 64
PSEUDONYM_PREFIX = "pyn_"
_FINGERPRINT_FIELDS = "archon-m68-dpia-v1"

# ---------------------------------------------------------------------------
# Aufbewahrungsfristen (DSGVO Art. 5 Abs. 1 lit. e, GoBD / § 147 AO, § 257 HGB)
# ---------------------------------------------------------------------------

_BASIS_GOBD = "GoBD / § 147 AO, § 257 HGB — 10 Jahre unveraendert"
_BASIS_BETRIEB = "Betriebs-Log (DSGVO Art. 5 Abs. 1 lit. e, Speicherbegrenzung)"

#: Rueckgabe je Kategorie: ``years`` (0 = keine GoBD-Pflicht), ``days``, ``basis``.
RETENTION_MAP: Dict[str, Dict[str, Any]] = {
    "financial": {"years": 10, "days": 3650, "basis": _BASIS_GOBD},
    "invoice": {"years": 10, "days": 3650, "basis": _BASIS_GOBD},
    "tax": {"years": 10, "days": 3650, "basis": _BASIS_GOBD},
    "bookkeeping": {"years": 10, "days": 3650, "basis": _BASIS_GOBD},
    "treasury": {"years": 10, "days": 3650, "basis": _BASIS_GOBD},
    "payment": {"years": 10, "days": 3650, "basis": _BASIS_GOBD},
    "audit": {"years": 10, "days": 3650, "basis": _BASIS_GOBD},
    "approval": {"years": 10, "days": 3650, "basis": _BASIS_GOBD},
    "llm_dispatch": {"years": 10, "days": 3650, "basis": _BASIS_GOBD},
    "governance": {"years": 10, "days": 3650, "basis": _BASIS_GOBD},
    "compliance": {"years": 10, "days": 3650, "basis": _BASIS_GOBD},
    "system": {"years": 0, "days": 365, "basis": _BASIS_BETRIEB},
    "security": {"years": 0, "days": 365, "basis": _BASIS_BETRIEB},
    "workflow": {"years": 0, "days": 365, "basis": _BASIS_BETRIEB},
    "chat": {"years": 0, "days": 180, "basis": _BASIS_BETRIEB},
    "debug": {"years": 0, "days": 90, "basis": _BASIS_BETRIEB},
    "performance": {"years": 0, "days": 90, "basis": _BASIS_BETRIEB},
    "health": {"years": 0, "days": 30, "basis": _BASIS_BETRIEB},
    "default": {"years": 0, "days": 90, "basis": _BASIS_BETRIEB},
}

GOBD_RETENTION_YEARS = 10

#: Felder, die in Exporten grundsaetzlich pseudonymisiert werden (kein Klartext).
PII_FIELDS = frozenset(
    {
        "email", "e_mail", "email_address", "phone", "telefon", "mobile",
        "name", "person_name", "full_name", "first_name", "last_name",
        "iban", "bank_account", "address", "street", "ip", "ip_address",
        "customer_id", "contact", "birthdate", "date_of_birth",
    }
)

ART50_LABEL = (
    "KI-generiert / KI-unterstuetzt durch einen Archon OS Agenten "
    "— Kennzeichnung nach Art. 50 VO (EU) 2024/1689"
)


def retention_for_category(category: str) -> Dict[str, Any]:
    """Aufbewahrungsregel je Log-Kategorie; unbekannte Kategorien fallen auf 90 Tage zurueck."""
    key = str(category or "").strip().lower()
    entry = RETENTION_MAP.get(key, RETENTION_MAP["default"])
    return {
        "category": key or "default",
        "years": int(entry["years"]),
        "days": int(entry["days"]),
        "basis": str(entry["basis"]),
        "gobd_relevant": int(entry["years"]) == GOBD_RETENTION_YEARS,
    }


def retention_label(category: str) -> str:
    """Kurzform fuer Inventar- und Policy-Exporte."""
    rule = retention_for_category(category)
    return f"{rule['years']} Jahre" if rule["years"] else f"{rule['days']} Tage"


# ---------------------------------------------------------------------------
# Deterministische Feldpseudonymisierung
# ---------------------------------------------------------------------------

# Ohne ENV-Salt bewusst prozesslokal: zwei Deployments duerfen nicht dieselben
# Pseudonyme erzeugen (sonst ueberdeployment-weit korrelierbar). Ein Restart
# aendert den Salt — dafuer ist in Produktion ARCHON_DPIA_PSEUDONYM_SALT Pflicht.
_DEV_SALT = hashlib.sha256(os.urandom(16)).hexdigest()[:16]
_PROD_ENV = frozenset({"production", "prod", "live"})


def _pseudonym_salt() -> str:
    """PEPPER aus der ENV; Produktion ohne Salt fail-closed, Dev prozesslokal."""
    salt = os.environ.get("ARCHON_DPIA_PSEUDONYM_SALT", "").strip()
    if salt:
        return salt
    env_name = str(
        os.environ.get("ENVIRONMENT") or os.environ.get("ARCHON_ENV") or ""
    ).strip().lower()
    if env_name in _PROD_ENV:
        raise RuntimeError(
            "ARCHON_DPIA_PSEUDONYM_SALT fehlt in Produktion — "
            "Pseudonymisierung fail-closed (kein deployweiter Default-Salt)."
        )
    return f"archon-m68-dev-{_DEV_SALT}"


def pseudonymize_field(value: Any, field: str = "", salt: Optional[str] = None) -> str:
    """Deterministischer Pseudonym-Token; Klartexte verlassen diese Funktion nicht.

    Nur als PII markierte Felder werden ersetzt. Der Token ist ueber Laeufe hinweg
    stabil (gleicher Wert + gleiches Feld -> gleicher Token), aber nicht umkehrbar.
    """
    text = "" if value is None else str(value)
    if not text:
        return ""
    if str(field or "").strip().lower() not in PII_FIELDS:
        return text
    pepper = _pseudonym_salt() if salt is None else str(salt)
    digest = hashlib.sha256(f"{pepper}|{field}|{text}".encode("utf-8")).hexdigest()
    return f"{PSEUDONYM_PREFIX}{digest[:16]}"


def pseudonymize_payload(payload: Any, *, salt: Optional[str] = None, _depth: int = 0) -> Any:
    """Rekursive Pseudonymisierung aller PII-Felder eines Dict/List-Payloads."""
    if _depth > 6:
        return "[truncated]"
    if isinstance(payload, dict):
        out: Dict[str, Any] = {}
        for key, value in payload.items():
            k = str(key)
            if k.lower() in PII_FIELDS and isinstance(value, (str, int, float)):
                out[k] = pseudonymize_field(value, k, salt=salt)
            else:
                out[k] = pseudonymize_payload(value, salt=salt, _depth=_depth + 1)
        return out
    if isinstance(payload, (list, tuple)):
        return [pseudonymize_payload(item, salt=salt, _depth=_depth + 1) for item in payload]
    return payload


# ---------------------------------------------------------------------------
# M68: Inventar aus vorhandener SSOT
# ---------------------------------------------------------------------------

def _load_json(path: str, fallback: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        logger.warning("[M68] SSOT %s nicht lesbar: %s", os.path.basename(path), type(exc).__name__)
        return fallback


def _as_records(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [item for item in data.values() if isinstance(item, dict)]
    return []


def _classification_for(agent: Mapping[str, Any]) -> str:
    """Datenklasse aus Kategorie/Beschreibung ueber die vorhandene Taxonomie ableiten."""
    from backend.data_classifier import CLASSIFICATION_METADATA, ClassificationLevel, DataClassifier

    category = str(agent.get("category") or agent.get("category_en") or "")
    description = str(agent.get("description") or "")
    aid = str(agent.get("id") or "").lower()
    context = f"{category} {aid}".lower()
    # 'hr' nur als eigenes Wort zaehlen — sonst trifft es in 'Führung' zu.
    sensitive = any(
        (" hr " in f" {context} ") if token == "hr" else (token in context)
        for token in ("recht", "steuer", "compliance", "finanz", "hr", "personal", "medizin", "klinisch")
    )
    if "strictly" in aid or "secret" in aid or "passwort" in description.lower():
        return ClassificationLevel.STRICTLY_CONFIDENTIAL.value
    try:
        level = DataClassifier.classify(f"{category} {description}", filename=str(agent.get("id") or ""))
        value = str(level.get("level") or "")
        if value in {item.value for item in CLASSIFICATION_METADATA}:
            # Sensible Fachdomaenen duerfen nie unter INTERNAL landen.
            if sensitive and value in ("PUBLIC", "INTERNAL"):
                return ClassificationLevel.CONFIDENTIAL.value
            return value
    except Exception as exc:
        logger.debug("[M68] Klassifizierung %s nicht verfuegbar: %s", aid, type(exc).__name__)
    return ClassificationLevel.CONFIDENTIAL.value if sensitive else ClassificationLevel.INTERNAL.value


def _log_category_for(agent: Mapping[str, Any], datenklasse: str) -> str:
    category = str(agent.get("category") or "").lower()
    aid = str(agent.get("id") or "").lower()
    if any(k in category for k in ("finanz", "steuer", "recht", "compliance")):
        return "financial" if "finanz" in category or "steuer" in category else "governance"
    if datenklasse == "STRICTLY_CONFIDENTIAL":
        return "audit"
    if any(k in aid for k in ("outreach", "social", "copywriter", "marketing")):
        return "chat"
    return "system"


def _freigabestufe_for(
    agent: Mapping[str, Any], node: Mapping[str, Any], datenklasse: str
) -> str:
    """Freigabestufe aus Rollen-SSOT, Org-Hierarchie und Policy-Domain (M69, nur lesend)."""
    hitl_domains: Iterable[str] = ()
    try:
        from backend.approval_policy_engine import HITL_REQUIRED_DOMAINS

        hitl_domains = HITL_REQUIRED_DOMAINS
    except Exception as exc:
        logger.debug("[M68] Policy-Domains nicht lesbar: %s", type(exc).__name__)

    domain = str(agent.get("domain") or node.get("team_id") or "").strip().lower()
    is_authority = bool(node.get("is_approval_authority")) or bool(agent.get("is_approval_authority"))
    if datenklasse == "STRICTLY_CONFIDENTIAL" or is_authority or domain in set(hitl_domains):
        return "HITL_4_AUGEN"
    if datenklasse == "CONFIDENTIAL":
        return "HITL"
    return "AUTO_SUPERVISED"


def build_inventory(
    tenant_id: str = "default",
    *,
    profiles_file: str = PROFILES_FILE,
    roles_file: str = ROLES_FILE,
    org_file: str = ORG_HIERARCHY_FILE,
) -> List[Dict[str, Any]]:
    """Baut das Tenant-Compliance-Inventar aus bestehenden SSOT-Dateien (keine neue Tabelle).

    Jeder Eintrag enthaelt ``agent``, ``datenklasse``, ``ziel`` (lokal/cloud),
    ``freigabestufe`` und ``retention`` sowie herkunftsbezogene Zusatzfelder.
    """
    profiles = _as_records(_load_json(profiles_file, []))
    roles = _as_records(_load_json(roles_file, []))
    org = _load_json(org_file, {})
    org_nodes = org.get("nodes", []) if isinstance(org, dict) else []
    nodes = {str(n.get("id")): n for n in _as_records(org_nodes) if n.get("id")}

    # Rollen-SSOT ergaenzt Profile, ersetzt sie aber nicht (ID ist Schluessel).
    known_ids = {str(p.get("id") or "") for p in profiles}
    for role in roles:
        rid = str(role.get("id") or "")
        if rid and rid not in known_ids:
            profiles.append(role)
            known_ids.add(rid)

    from backend.data_classifier import CLASSIFICATION_METADATA, ClassificationLevel

    try:
        from backend.privacy_router import get_privacy_config

        zero_egress_strict = bool(get_privacy_config().get("zero_egress_strict"))
    except Exception as exc:
        logger.debug("[M68] Privacy-Config nicht lesbar: %s", type(exc).__name__)
        zero_egress_strict = False

    inventory: List[Dict[str, Any]] = []
    for agent in profiles:
        aid = str(agent.get("id") or agent.get("name") or "").strip()
        if not aid:
            continue
        datenklasse = _classification_for(agent)
        meta = CLASSIFICATION_METADATA.get(ClassificationLevel(datenklasse), {})
        node = nodes.get(aid, {})
        sensitive = datenklasse in (
            ClassificationLevel.CONFIDENTIAL.value,
            ClassificationLevel.STRICTLY_CONFIDENTIAL.value,
        )
        ziel = "lokal" if (zero_egress_strict or sensitive or not meta.get("cloud_llm_allowed", True)) else "cloud"
        log_kategorie = _log_category_for(agent, datenklasse)
        inventory.append(
            {
                "tenant_id": str(tenant_id or "default"),
                "agent": aid,
                "agent_name": str(agent.get("name") or aid),
                "datenklasse": datenklasse,
                "ziel": ziel,
                "freigabestufe": _freigabestufe_for(agent, node, datenklasse),
                "retention": retention_label(log_kategorie),
                "log_kategorie": log_kategorie,
                "modell": str(agent.get("model") or node.get("model") or "unbekannt"),
                "pii_scrubbing_required": bool(meta.get("pii_scrubbing_required", False)),
                "quelle": "agent_profiles.json/roles.json/org_hierarchy.json",
            }
        )
    return inventory


# ---------------------------------------------------------------------------
# DPIA-Register (Art. 35 DSGVO), versionierte YAML mit Hash-Fingerprint
# ---------------------------------------------------------------------------

def compute_fingerprint(models: Iterable[str], datenklassen: Iterable[str]) -> str:
    """Stabiler SHA-256 ueber die sortierten Mengen der beobachteten Modelle/Datenklassen."""
    payload = {
        "feld": _FINGERPRINT_FIELDS,
        "modelle": sorted({str(m).strip() for m in models if str(m).strip()}),
        "datenklassen": sorted({str(d).strip() for d in datenklassen if str(d).strip()}),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


class DPIARegister:
    """Versioniertes Art.-35-Register; schreibt ausschliesslich die YAML-Datei unter config/."""

    def __init__(self, register_path: str = DPIA_REGISTER_FILE) -> None:
        self.register_path = register_path

    def load(self) -> Dict[str, Any]:
        """Liest das Register; bei Fehlern fail-closed mit leerer Basis (nie still ueberschreiben)."""
        if not os.path.isfile(self.register_path):
            return {
                "schema": "archon-m68-dpia/v1",
                "version": 0,
                "fingerprint": compute_fingerprint([], []),
                "updated_at": "",
                "entries": [],
                "history": [],
            }
        try:
            with open(self.register_path, "r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
        except Exception as exc:
            logger.error("[M68] DPIA-Register nicht lesbar: %s", type(exc).__name__)
            raise RuntimeError("DPIA-Register nicht lesbar (fail-closed).") from exc
        if not isinstance(data, dict):
            raise RuntimeError("DPIA-Register hat ungueltiges Format (fail-closed).")
        data.setdefault("schema", "archon-m68-dpia/v1")
        data.setdefault("version", 0)
        data.setdefault("fingerprint", "")
        data.setdefault("updated_at", "")
        data.setdefault("entries", [])
        data.setdefault("history", [])
        return data

    def detect_changes(
        self, models: Iterable[str], datenklassen: Iterable[str]
    ) -> List[Dict[str, str]]:
        """Meldet neue Modelle und neue Datenklassen als Change-Trigger (Art. 35 Abs. 11)."""
        current = self.load()
        known_models = {
            str(item.get("wert") or "")
            for item in current.get("entries", [])
            if isinstance(item, dict) and item.get("typ") == "new_model"
        }
        known_classes = {
            str(item.get("wert") or "")
            for item in current.get("entries", [])
            if isinstance(item, dict) and item.get("typ") == "new_datenklasse"
        }
        triggers: List[Dict[str, str]] = []
        for model in sorted({str(m).strip() for m in models if str(m).strip()} - known_models):
            triggers.append({"typ": "new_model", "wert": model})
        for klass in sorted({str(d).strip() for d in datenklassen if str(d).strip()} - known_classes):
            # Art. 35 DSGVO: nur hoehere Risikoklassen brauchen eine DPIA.
            if klass.upper() not in ("CONFIDENTIAL", "STRICTLY_CONFIDENTIAL"):
                continue
            triggers.append({"typ": "new_datenklasse", "wert": klass})
        return triggers

    def ensure_entries(
        self,
        models: Iterable[str],
        datenklassen: Iterable[str],
        *,
        actor: str = "system",
        reason: str = "Automatische SSOT-Synchronisation (M68)",
    ) -> Dict[str, Any]:
        """Legt bei Aenderung versionierte DPIA-Faelle an; ohne Aenderung bleibt die Datei unberuehrt."""
        triggers = self.detect_changes(models, datenklassen)
        current = self.load()
        fingerprint = compute_fingerprint(models, datenklassen)
        if not triggers:
            # Entfernte Modelle/Klassen erzeugen keinen Neu-Trigger, duerfen aber
            # nicht zu einem veralteten Fingerprint fuehren (Art. 35 Abs. 11).
            if fingerprint == str(current.get("fingerprint") or ""):
                return {"changed": False, "triggers": [], "register": current}
            triggers = [{"typ": "fingerprint_drift", "wert": fingerprint[:16]}]

        version = int(current.get("version") or 0) + 1
        now = _utc_now()
        entries = list(current.get("entries", []))
        for idx, trigger in enumerate(triggers, start=1):
            entries.append(
                {
                    "id": f"DPIA-{version:03d}-{idx:02d}",
                    "typ": trigger["typ"],
                    "wert": trigger["wert"],
                    "artikel": "Art. 35 DSGVO (Datenschutz-Folgenabschaetzung)",
                    "status": "PENDING_ASSESSMENT",
                    "triggered_at": now,
                    "actor": str(actor or "system"),
                    "reason": str(reason or "")[:500],
                }
            )
        history = list(current.get("history", []))
        history.append(
            {
                "version": version,
                "timestamp": now,
                "fingerprint_before": str(current.get("fingerprint") or ""),
                "fingerprint_after": fingerprint,
                "trigger_count": len(triggers),
            }
        )
        updated: Dict[str, Any] = {
            "schema": "archon-m68-dpia/v1",
            "version": version,
            "fingerprint": fingerprint,
            "updated_at": now,
            "entries": entries,
            "history": history,
        }
        parent = os.path.dirname(os.path.abspath(self.register_path))
        os.makedirs(parent, exist_ok=True)
        tmp_path = f"{self.register_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(updated, handle, allow_unicode=True, sort_keys=False)
        os.replace(tmp_path, self.register_path)
        return {"changed": True, "triggers": triggers, "register": updated}


def sync_dpia_register(
    tenant_id: str = "default",
    *,
    register_path: str = DPIA_REGISTER_FILE,
    profiles_file: str = PROFILES_FILE,
    roles_file: str = ROLES_FILE,
    org_file: str = ORG_HIERARCHY_FILE,
) -> Dict[str, Any]:
    """Synchronisiert das Inventar mit dem DPIA-Register und liefert die Change-Trigger."""
    inventory = build_inventory(
        tenant_id, profiles_file=profiles_file, roles_file=roles_file, org_file=org_file
    )
    register = DPIARegister(register_path)
    return register.ensure_entries(
        [str(item.get("modell") or "") for item in inventory],
        [str(item.get("datenklasse") or "") for item in inventory],
        actor="system",
    )


# ---------------------------------------------------------------------------
# Audit-Replay (M112-Interface + Fallback) mit Reihenfolge-/Lueckenpruefung
# ---------------------------------------------------------------------------

def _normalize_event(entry: Mapping[str, Any]) -> Dict[str, Any]:
    payload = entry.get("payload_parsed")
    if not isinstance(payload, dict):
        try:
            parsed = json.loads(str(entry.get("payload_json") or "{}"))
            payload = parsed if isinstance(parsed, dict) else {}
        except Exception:
            payload = {}
    raw_id = entry.get("id", 0)
    try:
        event_id = int(raw_id)
    except (TypeError, ValueError):
        event_id = 0
    return {
        "id": event_id,
        "timestamp": str(entry.get("timestamp") or ""),
        "category": str(entry.get("category") or ""),
        "action": str(entry.get("action") or entry.get("event_type") or ""),
        "agent_id": str(entry.get("agent_id") or ""),
        "company_id": str(entry.get("company_id") or ""),
        "prev_hash": str(entry.get("prev_hash") or ""),
        "current_hash": str(entry.get("current_hash") or entry.get("hash") or ""),
        "payload": dict(payload),
    }


def _load_events(tenant_id: str, ledger_path: Optional[str], limit: int) -> List[Dict[str, Any]]:
    """Liest die Registry-Kette ueber die bestehende ChainedAuditLog-API (keine neue Tabelle)."""
    from backend.audit_log import ChainedAuditLog, chained_audit_log

    ledger = ChainedAuditLog(db_path=ledger_path, start_anchor=False) if ledger_path else chained_audit_log
    collected: List[Dict[str, Any]] = []
    page_size = max(1, min(limit, 5000))
    while len(collected) < limit:
        response = ledger.list_events(
            limit=min(page_size, limit - len(collected)),
            offset=len(collected),
            company_id=str(tenant_id or "default"),
        )
        entries = list(response.get("entries") or [])
        if not entries:
            break
        collected.extend(entries)
        total = int(response.get("total") or len(collected))
        if len(collected) >= min(total, limit):
            break
    # list_events liefert DESC (ORDER BY id DESC) — Replay braucht aufsteigende Reihenfolge.
    return [_normalize_event(item) for item in reversed(collected)]


def _call_with_events(fn: Callable[..., Any], events: Sequence[Mapping[str, Any]]) -> Any:
    """M112-Signatur tolerant adaptieren: positional oder benannt (events/entries/records)."""
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return fn(events)
    positional = [
        name
        for name, param in signature.parameters.items()
        if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if positional:
        return fn(events)
    for name in ("events", "entries", "records", "ledger_events"):
        if name in signature.parameters:
            return fn(**{name: events})
    if not signature.parameters:
        return fn()
    return fn(events)


def _invoke_m112(events: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Optionales M112-Replay; Import-/Aufruffehler werden zum sauberen Fallback."""
    try:
        module = importlib.import_module("backend.event_ledger")
    except Exception as exc:
        logger.debug("[M68] backend.event_ledger nicht verfuegbar: %s", type(exc).__name__)
        return None
    replay_fn = getattr(module, "replay_events", None)
    verify_fn = getattr(module, "verify_ledger", None)
    if not callable(replay_fn):
        return None
    try:
        replay_result = _call_with_events(replay_fn, events)
        verify_result = _call_with_events(verify_fn, events) if callable(verify_fn) else None
    except Exception as exc:
        logger.warning("[M68] M112-Replay fehlgeschlagen, lokale Pruefung greift: %s", type(exc).__name__)
        return {"replay_error": type(exc).__name__}
    return {"replay": replay_result, "verify": verify_result}


def _check_sequence(events: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Prueft aufsteigende, lueckenlose IDs, monotone Zeitstempel und Hashketten-Kontinuitaet."""
    gaps: List[Dict[str, int]] = []
    order_errors: List[Dict[str, Any]] = []
    chain_errors: List[Dict[str, Any]] = []
    expected_id: Optional[int] = None
    previous_ts = ""
    expected_prev = GENESIS_HASH
    hashes_present = all(
        bool(str(event.get("prev_hash") or "")) and bool(str(event.get("current_hash") or ""))
        for event in events
    )
    for position, event in enumerate(events):
        event_id = int(event.get("id") or 0)
        if expected_id is not None and event_id != expected_id:
            gaps.append({"position": position, "expected": expected_id, "actual": event_id})
        expected_id = event_id + 1
        timestamp = str(event.get("timestamp") or "")
        if previous_ts and timestamp and timestamp < previous_ts:
            order_errors.append({"position": position, "previous": previous_ts, "actual": timestamp})
        previous_ts = timestamp or previous_ts
        if hashes_present:
            if str(event.get("prev_hash") or "") != expected_prev:
                chain_errors.append({"id": event_id, "expected_prev": expected_prev})
            expected_prev = str(event.get("current_hash") or "")
    return {
        "order_ok": not order_errors,
        "gaps": gaps,
        "order_errors": order_errors,
        "chain_ok": not chain_errors,
        "chain_checked": hashes_present,
        "chain_errors": chain_errors,
    }


def replay_from_ledger(
    tenant_id: str = "default",
    *,
    events: Optional[Sequence[Mapping[str, Any]]] = None,
    ledger_path: Optional[str] = None,
    limit: int = 10_000,
) -> Dict[str, Any]:
    """Getesteter Audit-Replay inkl. Reihenfolge-, Luecken- und Kettenschlusspruefung.

    Nutzt ``backend.event_ledger.replay_events`` / ``verify_ledger`` (M112), sofern das
    Modul verfuegbar ist, und faellt andernfalls auf die Lese-API der Registry-Kette
    (``chained_audit_log.list_events``) zurueck. Antworten enthalten pseudonymisierte
    Payloads und keine Secrets.
    """
    safe_limit = max(1, min(int(limit), 50_000))
    if events is None:
        raw_events = _load_events(str(tenant_id or "default"), ledger_path, safe_limit)
    else:
        raw_events = [_normalize_event(dict(item)) for item in events]

    sequence = _check_sequence(raw_events)
    m112 = _invoke_m112(raw_events)
    backend_name = "event_ledger" if m112 and "replay" in m112 else "audit_log_fallback"
    errors: List[str] = []
    if sequence["gaps"]:
        errors.append("ledger_gap")
    if not sequence["order_ok"]:
        errors.append("order_violation")
    if sequence["chain_checked"] and not sequence["chain_ok"]:
        errors.append("chain_break")
    if m112 and "replay_error" in m112:
        errors.append("m112_replay_error")

    safe_events = []
    for event in raw_events:
        enriched = dict(event)
        enriched["payload"] = pseudonymize_payload(event.get("payload") or {})
        safe_events.append(enriched)

    return {
        "status": "error" if errors else "ok",
        "errors": errors,
        "replay_backend": backend_name,
        "tenant_id": str(tenant_id or "default"),
        "count": len(raw_events),
        "first_id": int(raw_events[0]["id"]) if raw_events else 0,
        "last_id": int(raw_events[-1]["id"]) if raw_events else 0,
        "order_ok": bool(sequence["order_ok"]),
        "gaps": sequence["gaps"],
        "order_errors": sequence["order_errors"],
        "chain_ok": bool(sequence["chain_ok"]),
        "chain_checked": bool(sequence["chain_checked"]),
        "chain_errors": sequence["chain_errors"],
        "m112": pseudonymize_payload(m112) if m112 is not None else None,
        "events": safe_events,
    }


# ---------------------------------------------------------------------------
# Einseitiger Policy-Export & Art.-50-Kennzeichnung
# ---------------------------------------------------------------------------

def art50_label() -> str:
    """Pflicht-Kennzeichnung fuer agentenerstellte Artefakte (Art. 50 EU AI Act)."""
    return ART50_LABEL


def annotate_artifact(
    artifact: Mapping[str, Any], agent_id: str, *, created_at: Optional[str] = None
) -> Dict[str, Any]:
    """Kennzeichnet ein agentenerstelltes Artefakt unveraenderbar mit Art. 50."""
    tagged = dict(artifact)
    tagged["art50_disclosure"] = {
        "label": ART50_LABEL,
        "machine_generated": True,
        "agent_id": str(agent_id or "unknown"),
        "disclosed_at": str(created_at or _utc_now()),
        "legal_basis": "Art. 50 VO (EU) 2024/1689",
    }
    return tagged


def _policy_context(
    tenant_id: str,
    inventory: Optional[Sequence[Mapping[str, Any]]],
    dpia: Optional[Mapping[str, Any]],
    replay: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    items = list(inventory if inventory is not None else build_inventory(tenant_id))
    register = dict(dpia if dpia is not None else DPIARegister().load())
    proof = dict(replay if replay is not None else replay_from_ledger(tenant_id))
    classes = sorted({str(item.get("datenklasse") or "") for item in items if item.get("datenklasse")})
    local = sum(1 for item in items if item.get("ziel") == "lokal")
    gobd_rules = [rule for rule in RETENTION_MAP.values() if rule["years"] == GOBD_RETENTION_YEARS]
    return {
        "tenant_id": str(tenant_id or "default"),
        "generated_at": _utc_now(),
        "agent_count": len(items),
        "datenklassen": ", ".join(classes) or "-",
        "lokal_count": local,
        "cloud_count": len(items) - local,
        "dpia_version": int(register.get("version") or 0),
        "dpia_fingerprint": str(register.get("fingerprint") or ""),
        "dpia_pending": sum(
            1 for entry in register.get("entries", []) if str(entry.get("status")) == "PENDING_ASSESSMENT"
        ),
        "replay_status": str(proof.get("status") or "unknown"),
        "replay_count": int(proof.get("count") or 0),
        "gobd_categories": len(gobd_rules),
        "art50_label": ART50_LABEL,
    }


def export_policy_markdown(
    tenant_id: str = "default",
    *,
    inventory: Optional[Sequence[Mapping[str, Any]]] = None,
    dpia: Optional[Mapping[str, Any]] = None,
    replay: Optional[Mapping[str, Any]] = None,
) -> str:
    """Einseitiger Policy-Export als Markdown (PII-frei, Art.-50-gekennzeichnet)."""
    ctx = _policy_context(tenant_id, inventory, dpia, replay)
    lines = [
        "# Archon OS — Compliance-Policy (M68)",
        "",
        f"**Art.-50-Kennzeichnung:** {ctx['art50_label']}",
        "",
        f"Mandant: {ctx['tenant_id']} | Stand: {ctx['generated_at']} | Agenten: {ctx['agent_count']}",
        "",
        "## Inventar & Datenklassen",
        f"- Datenklassen: {ctx['datenklassen']}",
        f"- Ziel routing: {ctx['lokal_count']} lokal / {ctx['cloud_count']} Cloud",
        "- Freigabestufen: AUTO_SUPERVISED / HITL / HITL_4_AUGEN (SSOT: Rollen + Org-Hierarchie)",
        "",
        "## DPIA & Aufbewahrung",
        f"- Art.-35-Register: Version {ctx['dpia_version']}, offene Faelle {ctx['dpia_pending']}",
        f"- Register-Fingerprint (SHA-256): {ctx['dpia_fingerprint']}",
        f"- GoBD-Kategorien: {ctx['gobd_categories']} mit 10 Jahren; Betriebs-Logs 30–365 Tage",
        "- PII-Felder werden deterministisch pseudonymisiert (pyn_*); keine Klartexte im Export",
        "",
        "## Revisionsnachweis",
        f"- Audit-Replay: {ctx['replay_status']} ueber {ctx['replay_count']} Ereignisse",
        "- Pruefung: Reihenfolge, Luecken, Hashkette (M112 mit Registry-Fallback)",
        "",
        "Diese Policy wurde maschinell aus der laufenden SSOT erzeugt und ist nicht manuell zu aendern.",
    ]
    return "\n".join(lines) + "\n"


def export_inventory_pdf(
    tenant_id: str = "default",
    *,
    inventory: Optional[Sequence[Mapping[str, Any]]] = None,
) -> tuple[bytes, str]:
    """Vollstaendiger Tenant-Inventar-PDF-Export ueber den vorhandenen PDF-Generator."""
    from backend.compliance_pdf import CONTENT_W, _PDFDocumentBuilder

    items = list(inventory if inventory is not None else build_inventory(tenant_id))
    pdf = _PDFDocumentBuilder(
        doc_title="Archon OS Compliance-Inventar (M68)",
        tenant_label=f"Mandant {tenant_id}",
        document_id=f"M68-INVENTAR-{len(items):03d}",
    )
    pdf.add_title_banner(
        main_title="Tenant-Compliance-Inventar",
        subtitle="Agent -> Datenklasse -> Ziel -> Freigabestufe -> Retention",
        meta_lines=[f"Stand: {_utc_now()} | Eintraege: {len(items)}"],
    )
    rows = [
        [
            str(item.get("agent") or ""),
            str(item.get("datenklasse") or ""),
            str(item.get("ziel") or ""),
            str(item.get("freigabestufe") or ""),
            str(item.get("retention") or ""),
        ]
        for item in items
    ]
    pdf.add_table(
        headers=["Agent", "Datenklasse", "Ziel", "Freigabestufe", "Retention"],
        rows=rows,
        col_widths=[150.0, 105.0, 50.0, 105.0, CONTENT_W - 410.0],
        font_size=7.4,
    )
    pdf.add_paragraph(
        f"Art. 50 VO (EU) 2024/1689: {ART50_LABEL}. "
        "PII-Felder sind in Exporten pseudonymisiert (pyn_*).",
        size=8.0,
    )
    pdf_bytes = pdf.finalize_bytes()
    return pdf_bytes, hashlib.sha256(pdf_bytes).hexdigest()


def export_policy_pdf(
    tenant_id: str = "default",
    *,
    inventory: Optional[Sequence[Mapping[str, Any]]] = None,
    dpia: Optional[Mapping[str, Any]] = None,
    replay: Optional[Mapping[str, Any]] = None,
) -> tuple[bytes, str]:
    """Einseitiges Policy-PDF ueber den vorhandenen Pure-Python-Generator (keine neue Dependency)."""
    from backend.compliance_pdf import _PDFDocumentBuilder

    ctx = _policy_context(tenant_id, inventory, dpia, replay)
    pdf = _PDFDocumentBuilder(
        doc_title="Archon OS Compliance-Policy (M68)",
        tenant_label=f"Mandant {ctx['tenant_id']}",
        document_id=f"M68-POLICY-{ctx['dpia_version']:03d}",
    )
    pdf.add_title_banner(
        main_title="Compliance-Policy — Inventar, DPIA, Retention, Replay",
        subtitle="Einseitiger Prueferauszug aus der laufenden SSOT (M68)",
        meta_lines=[
            f"Stand: {ctx['generated_at']} | Agenten: {ctx['agent_count']} | Replay: {ctx['replay_status']}",
        ],
    )
    pdf.add_kv_grid(
        [
            ("Datenklassen", ctx["datenklassen"]),
            ("Ziel-Routing", f"{ctx['lokal_count']} lokal / {ctx['cloud_count']} Cloud"),
            ("Freigabestufen", "AUTO_SUPERVISED / HITL / HITL_4_AUGEN"),
            ("DPIA-Register", f"Version {ctx['dpia_version']}, {ctx['dpia_pending']} offene Faelle"),
            ("Register-Fingerprint", ctx["dpia_fingerprint"]),
            ("Aufbewahrung", f"{ctx['gobd_categories']} GoBD-Kategorien à 10 Jahre, Betrieb 30–365 Tage"),
            ("Audit-Replay", f"{ctx['replay_status']} / {ctx['replay_count']} Ereignisse"),
        ]
    )
    pdf.add_paragraph(
        f"Art. 50 VO (EU) 2024/1689: {ctx['art50_label']}. "
        "PII-Felder werden deterministisch pseudonymisiert (pyn_*); Exporte enthalten keine Klartexte.",
        size=8.0,
    )
    pdf_bytes = pdf.finalize_bytes()
    return pdf_bytes, hashlib.sha256(pdf_bytes).hexdigest()


# ---------------------------------------------------------------------------
# Expliziter Beleg-Adapter fuer M70/M74 (statt dynamischer Namenssuche)
# ---------------------------------------------------------------------------


def collect_evidence(subject: Mapping[str, Any]) -> List[Dict[str, str]]:
    """M68 -> NeedsMe/Auto-Review: Compliance-Policy-Export als Pruefsummen-Beleg.

    Der Beleg ist PII-frei und zeigt auf die versionierte Policy-SSOT; die
    Pruefsumme wird ueber den exportierten Text gebildet. Ersetzt nicht die
    menschliche Freigabe und erzeugt kein Agent-Fallback.
    """
    tenant = str(subject.get("tenant_id") or "default").strip() or "default"
    text = export_policy_markdown(tenant)
    return [
        {
            "kind": "compliance_policy",
            "reference": "config/approval_policy.yaml",
            "checksum": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
    ]
