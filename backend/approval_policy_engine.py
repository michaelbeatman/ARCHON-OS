"""
==============================================================================
Archon OS 2026 - GoBD/ISO 27001 Compliant Approval Policy Engine (t-5596bd)
==============================================================================
Revisionssicheres Freigabesystem mit:
- Wertschwellen (unter 50 EUR Auto-Freigabe, ab 500 EUR 4-Augen-Prinzip)
- Zeitgesteuerter Fristüberwachung & Eskalation nach 24 h ohne Rückmeldung
- Urlaubsmodus & automatisierter Stellvertretung
- Append-Only SHA-256 Hash-Kette für GoBD- und ISO-27001-Nachweisführung
"""

import base64
import copy
import datetime
import functools
import hashlib
import hmac
import json
import logging
import math
import os
import re
import sqlite3
import threading
import time
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Tuple

logger = logging.getLogger("archon.approval_policy_engine")

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    from backend.db_paths import resolve_db
    DB_FILE = resolve_db("agentic_memory.db")
except Exception:
    DB_FILE = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")
GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

# D14/M4: Domains, deren Antraege grundsaetzlich HITL-pflichtig sind. Bei
# diesen Domains ist ein Antrag ohne zuordenbaren Ersteller wirkungslos und
# wird bei der Freigabe hart abgelehnt (kein Self-Approval durch den Admin).
HITL_REQUIRED_DOMAINS = frozenset({
    "agent_dispatch", "boardroom", "workflow_authoring",
    "context_hygiene", "system", "governance",
})

# D04/HIGH (A4-Handoff): harter Mindestabstand zwischen der Auto-Freigabe- und
# der Vier-Augen-Schwelle. Die blosse Ungleichung `auto_max < four_eyes_min`
# liess Werte wie 499.99 / 500.00 zu und machte die 50-EUR-Regel wirkungslos.
# Die Invariante wird ab jetzt SYMMETRISCH geprueft — egal welche der beiden
# Schwellen geaendert wird.
FINANCE_THRESHOLD_MIN_GAP = 0.01  # ein Cent — kleinste harte, geldbetragsrelevante Distanz
_GAP_EPSILON = 1e-9  # Float-Rundung (500.0 - 499.99 == 0.009999999999990905)

# M95: Harte Sicherheits-Invarianten fuer Urlaubs-/Vertretungsmodus & Eskalation
ALLOWED_DEPUTY_ROLES: FrozenSet[str] = frozenset({"admin", "operator"})
ADMIN_ONLY_DEPUTY_DOMAINS: FrozenSet[str] = frozenset({"system", "governance"})
_FORBIDDEN_AGENT_IDENTITIES: FrozenSet[str] = frozenset({
    "system",
    "agent",
    "default",
    "system_watchdog",
    "hermes",
    "archon",
    "auto",
    "bot",
    "ai",
    "llm",
    "assistant",
    "executive_decision_architect",
    "legal_counsel",
    "tax_holding_advisor",
    "finance_lead",
    "senior_fullstack_engineer",
    "agile_scrum_master",
    "qa_test_engineer",
    "linkedin_social_media_specialist",
})
_FORBIDDEN_AGENT_PREFIXES = (
    "agent:",
    "agent_",
    "bot:",
    "bot_",
    "sys:",
    "system:",
    "system_",
    "ai:",
    "ai_",
    "llm:",
    "auto:",
)


def is_agent_or_system_identity(actor: Optional[str]) -> bool:
    """True, wenn die Identitaet ein Agent, Bot oder System-Default ist (nie als Mensch zulassen)."""
    clean = str(actor or "").strip().lower()
    if not clean:
        return True
    if clean in _FORBIDDEN_AGENT_IDENTITIES:
        return True
    return any(clean.startswith(prefix) for prefix in _FORBIDDEN_AGENT_PREFIXES)


# ---------------------------------------------------------------------------
# M69: Policy-as-Code — versionierte YAML-Regeln mit Hash-Fingerprint.
# Die Datei ist die SSOT; Lesefehler oder Schema-Verletzungen sperren jeden
# Gate (fail-closed). Die Kanonisierung entspricht der von M71
# `build_config_fingerprint`: SHA-256 ueber sortiertes, kompaktes UTF-8-JSON.
# ---------------------------------------------------------------------------
POLICY_FILE = os.path.join(WORKSPACE_DIR, "config", "approval_policy.yaml")
POLICY_SCHEMA_VERSION = 1
_POLICY_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_POLICY_CACHE: Dict[str, Tuple[int, Dict[str, Any]]] = {}


class PolicyValidationError(ValueError):
    """Ungueltige, fehlende oder nicht lesbare Policy (immer fail-closed)."""


class ApprovalTokenError(ValueError):
    """Ungueltiges, abgelaufenes oder bereits verbrauchtes Freigabe-Token."""


def _now_epoch() -> int:
    """Sekunden-Zeitstempel; zentral, damit TTL-Pruefung deterministisch testbar ist."""
    return int(time.time())


def _canonical_policy_bytes(policy: Dict[str, Any]) -> bytes:
    payload = {key: value for key, value in policy.items() if key != "fingerprint"}
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def build_policy_fingerprint(policy: Dict[str, Any]) -> str:
    """SHA-256 ueber die kanonisierte Policy (M71-kompatible Fingerprint-Form)."""
    return hashlib.sha256(_canonical_policy_bytes(policy)).hexdigest()


def policy_source_digest(path: Optional[str] = None) -> str:
    """SHA-256 der Policy-Datei in der M71-Kanonisierung (UTF-8/LF/Zeilenfassung).

    M71 kann damit ``config/approval_policy.yaml`` als weitere Quelle in
    ``build_config_fingerprint`` aufnehmen, ohne dieses Modul zu editieren.
    """
    source = str(path or POLICY_FILE)
    try:
        with open(source, "rb") as handle:
            text = handle.read().decode("utf-8")
    except Exception as exc:
        raise PolicyValidationError(f"Policy-Datei nicht lesbar: {source}") from exc
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    canonical = "\n".join(lines) + ("\n" if lines else "")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _require_number(value: Any, label: str, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PolicyValidationError(f"{label} muss eine Zahl sein.")
    numeric = float(value)
    if not math.isfinite(numeric) or not (minimum <= numeric <= maximum):
        raise PolicyValidationError(
            f"{label} liegt ausserhalb der erlaubten Spanne ({minimum}..{maximum})."
        )
    return numeric


def _require_int(value: Any, label: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PolicyValidationError(f"{label} muss eine ganze Zahl sein.")
    if not (minimum <= value <= maximum):
        raise PolicyValidationError(
            f"{label} liegt ausserhalb der erlaubten Spanne ({minimum}..{maximum})."
        )
    return value


def _require_dict(value: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise PolicyValidationError(f"{label} muss ein Mapping sein.")
    return value


def _require_str_list(value: Any, label: str) -> List[str]:
    if not isinstance(value, list) or not value:
        raise PolicyValidationError(f"{label} muss eine nicht-leere Liste sein.")
    items: List[str] = []
    for entry in value:
        text = str(entry or "").strip().lower()
        if not text:
            raise PolicyValidationError(f"{label} enthaelt einen leeren Eintrag.")
        items.append(text)
    return items


def _validate_policy(raw: Any) -> Dict[str, Any]:
    """Normalisiert und validiert die Policy strikt; nie still Default-Werte ergaenzen."""
    data = _require_dict(raw, "Policy")
    schema = _require_int(
        data.get("schema_version"), "schema_version", minimum=1, maximum=POLICY_SCHEMA_VERSION
    )
    version = str(data.get("policy_version") or "").strip()
    if not _POLICY_VERSION_RE.match(version):
        raise PolicyValidationError("policy_version muss der Form X.Y.Z sein.")

    levels = _require_dict(data.get("approval_levels"), "approval_levels")
    auto = _require_dict(levels.get("auto"), "approval_levels.auto")
    four = _require_dict(levels.get("four_eyes"), "approval_levels.four_eyes")
    admin = _require_dict(levels.get("admin"), "approval_levels.admin")
    auto_max = _require_number(
        auto.get("max_amount_eur"), "auto.max_amount_eur", minimum=0.0, maximum=1_000_000.0
    )
    four_min = _require_number(
        four.get("min_amount_eur"), "four_eyes.min_amount_eur",
        minimum=0.0, maximum=1_000_000.0,
    )
    admin_min = _require_number(
        admin.get("min_amount_eur"), "admin.min_amount_eur",
        minimum=0.0, maximum=1_000_000.0,
    )
    # Gleiche harte Invariante wie in der DB-Seite: mindestens ein Cent Abstand.
    if four_min - auto_max + _GAP_EPSILON < FINANCE_THRESHOLD_MIN_GAP:
        raise PolicyValidationError(
            "Invariante verletzt: four_eyes.min_amount_eur muss mindestens "
            f"{FINANCE_THRESHOLD_MIN_GAP:.2f} EUR ueber auto.max_amount_eur liegen."
        )
    if admin_min < four_min:
        raise PolicyValidationError(
            "Invariante verletzt: admin.min_amount_eur darf nicht unter "
            "four_eyes.min_amount_eur liegen."
        )
    min_distinct = _require_int(
        four.get("min_distinct_approvers"), "four_eyes.min_distinct_approvers",
        minimum=2, maximum=10,
    )

    domino = _require_dict(data.get("domino_limits"), "domino_limits")
    max_depth = _require_int(
        domino.get("max_chain_depth"), "domino_limits.max_chain_depth", minimum=1, maximum=32
    )
    max_actions = _require_int(
        domino.get("max_actions_per_chain"), "domino_limits.max_actions_per_chain",
        minimum=1, maximum=1000,
    )
    domains = _require_str_list(domino.get("allowed_domains"), "domino_limits.allowed_domains")

    vendor = _require_dict(data.get("vendor_limits"), "vendor_limits")
    window = _require_int(
        vendor.get("window_hours"), "vendor_limits.window_hours", minimum=24, maximum=24
    )
    default_spend = _require_number(
        vendor.get("max_spend_usd"), "vendor_limits.max_spend_usd",
        minimum=0.01, maximum=1_000_000.0,
    )
    default_calls = _require_int(
        vendor.get("max_calls"), "vendor_limits.max_calls", minimum=1, maximum=100_000
    )
    vendors_raw = _require_dict(vendor.get("vendors"), "vendor_limits.vendors")
    vendors: Dict[str, Dict[str, Any]] = {}
    for name, cfg in vendors_raw.items():
        key = str(name or "").strip().lower()
        if not key:
            raise PolicyValidationError("vendor_limits.vendors enthaelt einen leeren Namen.")
        entry = _require_dict(cfg, f"vendor_limits.vendors.{key}")
        vendors[key] = {
            "window_hours": _require_int(
                entry.get("window_hours", window),
                f"vendor_limits.vendors.{key}.window_hours", minimum=24, maximum=24,
            ),
            "max_spend_usd": _require_number(
                entry.get("max_spend_usd", default_spend),
                f"vendor_limits.vendors.{key}.max_spend_usd",
                minimum=0.01, maximum=1_000_000.0,
            ),
            "max_calls": _require_int(
                entry.get("max_calls", default_calls),
                f"vendor_limits.vendors.{key}.max_calls", minimum=1, maximum=100_000,
            ),
        }

    roles = _require_dict(data.get("roles"), "roles")
    approver_roles = _require_str_list(roles.get("approver_roles"), "roles.approver_roles")
    # M95 darf durch YAML niemals aufgeweicht werden: keine Viewer, keine Agenten.
    if not set(approver_roles).issubset(ALLOWED_DEPUTY_ROLES):
        raise PolicyValidationError(
            "roles.approver_roles enthaelt Rollen, die M95 verletzen "
            "(erlaubt: admin, operator)."
        )
    admin_only = _require_str_list(roles.get("admin_only_domains"), "roles.admin_only_domains")
    if not set(admin_only).issubset(set(domains)):
        raise PolicyValidationError(
            "roles.admin_only_domains enthaelt Domains ausserhalb von "
            "domino_limits.allowed_domains."
        )
    forbidden = _require_str_list(
        roles.get("forbidden_deputy_roles"), "roles.forbidden_deputy_roles"
    )
    if "viewer" not in forbidden:
        raise PolicyValidationError(
            "roles.forbidden_deputy_roles muss 'viewer' enthalten (M95)."
        )

    token = _require_dict(data.get("token"), "token")
    ttl = _require_int(token.get("ttl_seconds"), "token.ttl_seconds", minimum=30, maximum=900)
    max_uses = _require_int(token.get("max_uses"), "token.max_uses", minimum=1, maximum=1)

    return {
        "schema_version": schema,
        "policy_version": version,
        "effective_from": str(data.get("effective_from") or "").strip(),
        "approval_levels": {
            "auto": {"max_amount_eur": auto_max},
            "four_eyes": {
                "min_amount_eur": four_min,
                "min_distinct_approvers": min_distinct,
            },
            "admin": {"min_amount_eur": admin_min},
        },
        "domino_limits": {
            "max_chain_depth": max_depth,
            "max_actions_per_chain": max_actions,
            "allowed_domains": domains,
        },
        "vendor_limits": {
            "window_hours": window,
            "max_spend_usd": default_spend,
            "max_calls": default_calls,
            "vendors": vendors,
        },
        "roles": {
            "approver_roles": approver_roles,
            "admin_only_domains": admin_only,
            "forbidden_deputy_roles": forbidden,
        },
        "token": {"ttl_seconds": ttl, "max_uses": max_uses},
    }


def load_approval_policy(
    path: Optional[str] = None, *, use_cache: bool = True
) -> Dict[str, Any]:
    """Laedt und validiert die Policy; Bei jedem Fehler fail-closed."""
    policy_path = str(path or POLICY_FILE)
    try:
        stat = os.stat(policy_path)
        cached = _POLICY_CACHE.get(policy_path)
        if use_cache and cached is not None and cached[0] == stat.st_mtime_ns:
            return copy.deepcopy(cached[1])
        import yaml

        with open(policy_path, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
        policy = _validate_policy(raw)
        policy["fingerprint"] = build_policy_fingerprint(policy)
        _POLICY_CACHE[policy_path] = (stat.st_mtime_ns, copy.deepcopy(policy))
        return policy
    except PolicyValidationError:
        raise
    except Exception as exc:
        raise PolicyValidationError(
            f"Policy '{policy_path}' nicht ladbar (fail-closed): {exc}"
        ) from exc


def _record_central_audit(category: str, action: str, actor: str, details: Dict[str, Any]) -> None:
    """Protokolliert M95-Urlaubs- und Eskalationsereignisse zusaetzlich in backend/audit_log.py."""
    try:
        from backend.audit_log import chained_audit_log

        chained_audit_log.record_event(category, action, actor, details)
    except Exception as exc:
        logger.warning("[ApprovalPolicyEngine] Zentrales Audit-Event (%s/%s) nicht geschrieben: %s", category, action, exc)


# ---------------------------------------------------------------------------
# M69: Kurzlebige, HMAC-signierte Freigabe-Tokens mit Einmalverbrauch.
# Das Token ist ein kompaktes Binaerformat (<= 46 Zeichen inkl. Signatur),
# damit es samt `hitl:`-Praefix in eine Telegram-callback_data passt.
# Der Klartext wird NIE geloggt; Logs/Responses enthalten nur ID/Fingerprint.
# ---------------------------------------------------------------------------
_TOKEN_MAGIC = b"M69"
_TOKEN_VERSION = 1
_TOKEN_BODY_LEN = 3 + 1 + 4 + 5 + 1 + 4 + 4  #magic, Version, exp, jti, Aktion, req-, Policy-FP
_TOKEN_SIG_LEN = 12
_TOKEN_KEY_CONTEXT = b"archon-m69-approval-token-v1"
_TOKEN_ACTION_CODES: Dict[str, int] = {"approve": 1, "deny": 2}
_TOKEN_ACTIONS_BY_CODE: Dict[int, str] = {1: "approve", 2: "deny"}


def _token_key() -> bytes:
    """HMAC-Schluessel mit Domain-Separation; ohne Key fail-closed."""
    secret = str(os.environ.get("ARCHON_AUDIT_HMAC_KEY") or "")
    if len(secret) < 16:
        raise ApprovalTokenError(
            "ARCHON_AUDIT_HMAC_KEY fehlt oder ist zu kurz — Freigabe-Tokens gesperrt."
        )
    return hmac.new(secret.encode("utf-8"), _TOKEN_KEY_CONTEXT, hashlib.sha256).digest()


def _policy_db_path(db_path: Optional[str] = None) -> str:
    if db_path:
        return str(db_path)
    engine = globals().get("approval_engine")
    return str(getattr(engine, "db_path", DB_FILE))


def _init_token_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS m69_approval_tokens (
                jti TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                action TEXT NOT NULL,
                policy_fingerprint TEXT NOT NULL,
                actor TEXT DEFAULT '',
                issued_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                expires_at_epoch INTEGER NOT NULL,
                used_at TEXT
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_m69_tokens_request "
            "ON m69_approval_tokens(request_id)"
        )
    return conn


def issue_approval_token(
    request_id: str,
    action: str,
    *,
    actor: str = "",
    ttl_seconds: Optional[int] = None,
    policy: Optional[Dict[str, Any]] = None,
    policy_path: Optional[str] = None,
    db_path: Optional[str] = None,
    now_epoch: Optional[int] = None,
) -> Dict[str, Any]:
    """Stellt ein Einmal-Token fuer eine EXISTIERENDE Freigabeanfrage aus."""
    pol = policy or load_approval_policy(policy_path)
    ttl = int(ttl_seconds) if ttl_seconds is not None else int(pol["token"]["ttl_seconds"])
    if not (30 <= ttl <= 900):
        raise ApprovalTokenError("Token-TTL liegt ausserhalb der Spanne (30..900 s).")
    act = str(action or "").strip().lower()
    if act not in _TOKEN_ACTION_CODES:
        raise ApprovalTokenError(f"Ungueltige Token-Aktion '{act}'.")
    rid = str(request_id or "").strip()
    if not rid:
        raise ApprovalTokenError("request_id darf nicht leer sein.")
    engine = approval_engine if db_path is None else ApprovalPolicyEngine(db_path=db_path)
    if engine.get_request(rid) is None:
        raise ApprovalTokenError("Freigabeanfrage nicht gefunden — kein Token ausgestellt.")

    issued = _now_epoch() if now_epoch is None else int(now_epoch)
    expires = issued + ttl
    jti_raw = os.urandom(5)
    fingerprint = str(pol.get("fingerprint") or build_policy_fingerprint(pol))
    body = (
        _TOKEN_MAGIC
        + bytes([_TOKEN_VERSION])
        + expires.to_bytes(4, "big")
        + jti_raw
        + bytes([_TOKEN_ACTION_CODES[act]])
        + hashlib.sha256(rid.encode("utf-8")).digest()[:4]
        + hashlib.sha256(fingerprint.encode("utf-8")).digest()[:4]
    )
    signature = hmac.new(_token_key(), body, hashlib.sha256).digest()[:_TOKEN_SIG_LEN]
    token = base64.urlsafe_b64encode(body + signature).rstrip(b"=").decode("ascii")
    conn = _init_token_db(_policy_db_path(db_path))
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO m69_approval_tokens
                (jti, request_id, action, policy_fingerprint, actor,
                 issued_at, expires_at, expires_at_epoch, used_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    jti_raw.hex(), rid, act, fingerprint, str(actor or "").strip(),
                    datetime.datetime.fromtimestamp(issued, datetime.timezone.utc).isoformat(),
                    datetime.datetime.fromtimestamp(expires, datetime.timezone.utc).isoformat(),
                    expires,
                ),
            )
    finally:
        conn.close()
    return {
        "token": token,
        "token_id": jti_raw.hex(),
        "fingerprint": hashlib.sha256(token.encode("ascii")).hexdigest()[:16],
        "request_id": rid,
        "action": act,
        "actor": str(actor or "").strip(),
        "issued_at": datetime.datetime.fromtimestamp(issued, datetime.timezone.utc).isoformat(),
        "expires_at": datetime.datetime.fromtimestamp(expires, datetime.timezone.utc).isoformat(),
        "ttl_seconds": ttl,
        "callback_data": f"hitl:{act}:{token}",
    }


def verify_approval_token(
    token: str,
    *,
    expected_action: Optional[str] = None,
    expected_request_id: Optional[str] = None,
    consume: bool = False,
    policy: Optional[Dict[str, Any]] = None,
    policy_path: Optional[str] = None,
    db_path: Optional[str] = None,
    now_epoch: Optional[int] = None,
) -> Dict[str, Any]:
    """Prueft Signatur, TTL, Policy-Bindung und Einmalverbrauch — nie ein Allow-Fallback."""
    result: Dict[str, Any] = {
        "valid": False, "reason": "", "request_id": "", "action": "", "actor": "",
        "token_id": "", "fingerprint": "", "expires_at": "", "consumed": False,
    }

    def _reject(reason: str) -> Dict[str, Any]:
        result["reason"] = reason
        return result

    try:
        raw_token = str(token or "").strip()
        if not raw_token or len(raw_token) > 128:
            return _reject("invalid_token")
        try:
            blob = base64.urlsafe_b64decode(raw_token + "=" * (-len(raw_token) % 4))
        except Exception:
            return _reject("invalid_encoding")
        if len(blob) != _TOKEN_BODY_LEN + _TOKEN_SIG_LEN:
            return _reject("invalid_length")
        body, signature = blob[:_TOKEN_BODY_LEN], blob[_TOKEN_BODY_LEN:]
        expected_sig = hmac.new(_token_key(), body, hashlib.sha256).digest()[:_TOKEN_SIG_LEN]
        if not hmac.compare_digest(signature, expected_sig):
            return _reject("invalid_signature")
        if body[:3] != _TOKEN_MAGIC or body[3] != _TOKEN_VERSION:
            return _reject("unsupported_version")

        expires = int.from_bytes(body[4:8], "big")
        jti_hex = body[8:13].hex()
        action = _TOKEN_ACTIONS_BY_CODE.get(body[13], "")
        request_fp, policy_fp = body[14:18], body[18:22]
        if not action:
            return _reject("invalid_action")
        result["token_id"] = jti_hex
        result["fingerprint"] = hashlib.sha256(raw_token.encode("ascii")).hexdigest()[:16]
        now = _now_epoch() if now_epoch is None else int(now_epoch)
        if expires <= now:
            return _reject("expired")

        pol = policy or load_approval_policy(policy_path)
        fingerprint = str(pol.get("fingerprint") or build_policy_fingerprint(pol))
        if not hmac.compare_digest(
            policy_fp, hashlib.sha256(fingerprint.encode("utf-8")).digest()[:4]
        ):
            return _reject("policy_fingerprint_mismatch")
        if expected_action and expected_action != action:
            return _reject("action_mismatch")

        conn = _init_token_db(_policy_db_path(db_path))
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT * FROM m69_approval_tokens WHERE jti = ?", (jti_hex,)
                ).fetchone()
                if row is None:
                    return _reject("unknown_token")
                if row["used_at"] is not None:
                    return _reject("already_used")
                req_id = str(row["request_id"] or "")
                if not hmac.compare_digest(
                    request_fp, hashlib.sha256(req_id.encode("utf-8")).digest()[:4]
                ):
                    return _reject("request_mismatch")
                if expected_request_id and expected_request_id != req_id:
                    return _reject("request_mismatch")
                if str(row["action"]) != action or int(row["expires_at_epoch"]) != expires:
                    return _reject("token_record_mismatch")
                if consume:
                    cur = conn.execute(
                        "UPDATE m69_approval_tokens SET used_at = ? "
                        "WHERE jti = ? AND used_at IS NULL AND expires_at_epoch > ?",
                        (
                            datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            jti_hex,
                            now,
                        ),
                    )
                    if cur.rowcount != 1:
                        return _reject("already_used_or_expired")
                    result["consumed"] = True
                result.update({
                    "valid": True,
                    "reason": "ok",
                    "request_id": req_id,
                    "action": action,
                    "actor": str(row["actor"] or ""),
                    "expires_at": datetime.datetime.fromtimestamp(
                        expires, datetime.timezone.utc
                    ).isoformat(),
                })
                return result
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("[M69] Token-Pruefung fehlgeschlagen (fail-closed): %s", exc)
        return _reject("verification_error")


def parse_policy_callback(callback_data: str) -> Optional[Dict[str, str]]:
    """Zerlegt eine Telegram-callback_data in Aktion und signiertes Token."""
    parts = str(callback_data or "").strip().split(":", 2)
    if len(parts) != 3 or parts[0] not in ("hitl", "app"):
        return None
    action = parts[1].strip().lower()
    if action not in ("approve", "reject", "deny"):
        return None
    token = parts[2].strip()
    if not token:
        return None
    return {"action": "reject" if action == "deny" else action, "token": token}


def _policy_gate_result() -> Dict[str, Any]:
    """Stabiler Rueckgabe-Vertrag fuer M70/M74 (niemals das Roh-Token enthalten)."""
    return {
        "allowed": False,
        "decision": "deny",
        "reason": "",
        "reason_code": "",
        "policy_version": "",
        "policy_fingerprint": "",
        "required_level": "",
        "domain": "",
        "action": "",
        "amount_eur": 0.0,
        "vendor": "",
        "domino": {
            "chain_depth": 0, "max_chain_depth": 0,
            "actions_in_chain": 0, "max_actions_per_chain": 0, "within_limits": False,
        },
        "vendor_limit": None,
        "m95": {
            "human_approver_required": False, "approver": "", "deputy": None,
            "deputy_valid": None, "role_required": "",
        },
        "token": {
            "present": False, "valid": False, "token_id": "", "fingerprint": "",
            "expires_at": "", "consumed": False, "reason": "",
        },
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def _fail_closed_gate(
    func: Callable[..., Dict[str, Any]],
) -> Callable[..., Dict[str, Any]]:
    """Jeder unerwartete Fehler wird zur Ablehnung, nie zu einem Allow."""

    @functools.wraps(func)
    def _wrapped(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            logger.error("[M69] Policy-Gate nicht auswertbar (fail-closed): %s", exc)
            gate = _policy_gate_result()
            gate["decision"] = "deny"
            gate["reason_code"] = "policy_evaluation_error"
            gate["reason"] = "Policy-Gate nicht auswertbar (fail-closed)."
            return gate

    return _wrapped


@_fail_closed_gate
def evaluate_policy_gate(
    *,
    domain: str,
    action: str = "dispatch",
    amount_eur: float = 0.0,
    vendor: str = "",
    estimated_cost_usd: float = 0.0,
    actor: str = "",
    approver: str = "",
    request_id: str = "",
    approval_token: str = "",
    chain_depth: int = 0,
    actions_in_chain: int = 0,
    policy_path: Optional[str] = None,
    db_path: Optional[str] = None,
    now_epoch: Optional[int] = None,
) -> Dict[str, Any]:
    """Zentraler Policy-Gate fuer M70/M74.

    Vertrag: siehe ``_policy_gate_result()``. ``decision`` ist ``allow``,
    ``require_approval`` oder ``deny``; ``allowed`` ist NUR bei ``allow`` True.
    Ein Token wird ausschliesslich nach allen uebrigen Pruefungen und vor der
    Rueckgabe atomar verbraucht. Das Roh-Token erscheint nie im Ergebnis.
    """
    gate = _policy_gate_result()

    def _finish(decision: str, code: str, reason: str) -> Dict[str, Any]:
        gate["decision"] = decision
        gate["reason_code"] = code
        gate["reason"] = reason
        gate["allowed"] = decision == "allow"
        return gate

    clean_domain = str(domain or "").strip().lower()
    clean_action = str(action or "").strip().lower()
    gate["domain"] = clean_domain
    gate["action"] = clean_action
    try:
        amount = float(amount_eur)
        cost = float(estimated_cost_usd)
        depth = int(chain_depth)
        actions = int(actions_in_chain)
    except (TypeError, ValueError):
        return _finish("deny", "invalid_numeric_input", "Numerische Gate-Parameter ungueltig.")
    if not all(math.isfinite(x) for x in (amount, cost)) or amount < 0 or cost < 0:
        return _finish("deny", "invalid_numeric_input", "Betraege muessen endlich und >= 0 sein.")
    gate["amount_eur"] = amount
    gate["vendor"] = str(vendor or "").strip().lower()

    try:
        policy = load_approval_policy(policy_path)
    except PolicyValidationError as exc:
        return _finish("deny", "policy_invalid", f"Policy ungültig (fail-closed): {exc}")
    gate["policy_version"] = str(policy["policy_version"])
    gate["policy_fingerprint"] = str(policy["fingerprint"])

    levels = policy["approval_levels"]
    # Validierung der Pflichtfelder (fail-closed) ohne ungenutzte Beleg-variable.
    float(levels["auto"]["max_amount_eur"])
    four_min = float(levels["four_eyes"]["min_amount_eur"])
    admin_min = float(levels["admin"]["min_amount_eur"])
    if clean_domain not in policy["domino_limits"]["allowed_domains"]:
        return _finish("deny", "domain_not_allowed", f"Domain '{clean_domain}' ist nicht freigegeben.")
    required = (
        "admin" if amount >= admin_min
        else "four_eyes" if amount >= four_min
        else "auto"
    )
    gate["required_level"] = required

    domino = policy["domino_limits"]
    gate["domino"] = {
        "chain_depth": depth,
        "max_chain_depth": int(domino["max_chain_depth"]),
        "actions_in_chain": actions,
        "max_actions_per_chain": int(domino["max_actions_per_chain"]),
        "within_limits": (
            0 <= depth <= int(domino["max_chain_depth"])
            and 0 <= actions <= int(domino["max_actions_per_chain"])
        ),
    }
    if not gate["domino"]["within_limits"]:
        return _finish("deny", "domino_limit_exceeded", "Domino-/Kettenlimit ueberschritten.")

    human_required = required in ("four_eyes", "admin") or clean_domain in HITL_REQUIRED_DOMAINS
    m95 = gate["m95"]
    m95["human_approver_required"] = human_required
    m95["approver"] = str(approver or "").strip()
    eff_approver = m95["approver"] or str(actor or "").strip()
    if human_required:
        if is_agent_or_system_identity(eff_approver):
            return _finish(
                "deny", "m95_human_approver_required",
                "Freigabe erfordert einen verifizierten menschlichen Genehmiger (M95).",
            )
        roles_cfg = policy["roles"]
        required_roles = (
            frozenset({"admin"})
            if clean_domain in roles_cfg["admin_only_domains"]
            else frozenset(roles_cfg["approver_roles"])
        )
        m95["role_required"] = ",".join(sorted(required_roles))
        engine = approval_engine if db_path is None else ApprovalPolicyEngine(db_path=db_path)
        delegation = engine.get_delegation(eff_approver or "admin")
        if delegation.get("is_active"):
            esc = engine.resolve_human_escalation_target(
                eff_approver or "admin",
                domain=clean_domain,
                requester_id=request_id or None,
                strict_rbac=True,
            )
            if not esc["resolved"] or not esc["deputy"]:
                return _finish(
                    "deny", "m95_deputy_invalid",
                    f"M95-Stellvertretung ungueltig (fail-closed): {esc['reason']}",
                )
            m95["deputy"] = str(esc["deputy"]["username"])
            m95["deputy_valid"] = True
            eff_approver = m95["deputy"]
        m95["approver"] = eff_approver
        with engine._get_conn() as conn:
            user = engine._lookup_human_user(conn, eff_approver)
        if user is not None:
            if not user["is_active"] or user["role"] not in required_roles:
                return _finish(
                    "deny", "m95_insufficient_role",
                    f"Rolle '{user['role']}' darf Domain '{clean_domain}' nicht freigeben.",
                )

    token_info = gate["token"]
    token_info["present"] = bool(approval_token)
    expected_action = (
        "approve" if clean_action == "approve"
        else "deny" if clean_action in ("deny", "reject")
        else None
    )
    if approval_token:
        pre = verify_approval_token(
            approval_token,
            expected_action=expected_action,
            expected_request_id=request_id or None,
            consume=False,
            policy=policy,
            db_path=db_path,
            now_epoch=now_epoch,
        )
        token_info.update({
            "valid": bool(pre["valid"]), "token_id": str(pre["token_id"]),
            "fingerprint": str(pre["fingerprint"]), "expires_at": str(pre["expires_at"]),
            "reason": str(pre["reason"]),
        })
        if not pre["valid"]:
            return _finish(
                "deny", "approval_token_invalid",
                f"Freigabe-Token abgelehnt ({pre['reason']}).",
            )
        if request_id and request_id != pre["request_id"]:
            return _finish(
                "deny", "approval_token_request_mismatch",
                "Freigabe-Token gehoert zu einer anderen Anfrage.",
            )
        if pre["actor"] and m95["approver"] and not (
            _actor_identity_tokens(str(pre["actor"]))
            & _actor_identity_tokens(m95["approver"])
        ):
            return _finish(
                "deny", "approval_token_actor_mismatch",
                "Freigabe-Token ist an eine andere Person gebunden.",
            )

    if gate["vendor"]:
        from backend import cost_estimator as _cost_estimator

        vendor_check = _cost_estimator.check_vendor_limit(
            gate["vendor"],
            planned_cost_usd=cost,
            policy=policy,
            db_path=db_path,
            now_epoch=now_epoch,
        )
        gate["vendor_limit"] = vendor_check
        if not vendor_check["allowed"]:
            return _finish(
                "deny", "vendor_limit_exceeded",
                f"24h-Vendor-Limit fuer '{gate['vendor']}' ueberschritten.",
            )

    if human_required and not approval_token:
        return _finish(
            "require_approval", "approval_token_required",
            "Freigabe erforderlich: kein gueltiges Freigabe-Token uebergeben.",
        )

    if approval_token:
        final = verify_approval_token(
            approval_token,
            expected_action=expected_action,
            expected_request_id=request_id or None,
            consume=True,
            policy=policy,
            db_path=db_path,
            now_epoch=now_epoch,
        )
        token_info["consumed"] = bool(final["consumed"])
        if not final["valid"]:
            token_info["valid"] = False
            token_info["reason"] = str(final["reason"])
            return _finish(
                "deny", "approval_token_consumption_failed",
                f"Token konnte nicht einmalig verbraucht werden ({final['reason']}).",
            )

    return _finish("allow", "ok", "Policy-Gate freigegeben.")


def _actor_identity_tokens(actor: str) -> set:
    """Identitaets-Tokens eines Actors (inkl. Stellvertretungs-Suffix).

    D04/D14: gemeinsam genutzt von der Ersteller-Sperre und der
    Vier-Augen-Pruefung, damit "alice" und "alice (i.V. Bob)" als dieselbe
    physische Person erkannt werden.
    """
    s = (actor or "").strip().lower()
    if not s:
        return set()
    tokens = {s}
    if " (i.v. " in s:
        main_p, sub_p = s.split(" (i.v. ", 1)
        tokens.add(main_p.strip())
        sub_clean = sub_p.rstrip(")").strip()
        if sub_clean:
            tokens.add(sub_clean)
            tokens.add(sub_clean.split(" ")[0])
    else:
        tokens.add(s.split(" ")[0])
    return {t for t in tokens if t}


class ApprovalPolicyEngine:
    _chain_lock = threading.RLock()

    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self._chain_lock = threading.RLock()
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self):
        # Import VOR dem Oeffnen der Schreib-Transaktion, damit ChainedAuditLog._init_db()
        # beim Kaltstart auf einer frischen DB keinen Re-Entrancy-Lock ('database is locked') ausloest.
        from backend.audit_log import _chain_hash

        seeded_head = ""
        seeded_count = 0
        with self._get_conn() as conn:
            # 1. Policies table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS approval_policies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL,
                    policy_key TEXT NOT NULL UNIQUE,
                    policy_value TEXT NOT NULL,
                    label TEXT,
                    description TEXT,
                    updated_at TEXT NOT NULL,
                    updated_by TEXT NOT NULL
                );
            """)

            # 2. Append-Only GoBD Cryptographic Audit Chain
            conn.execute("""
                CREATE TABLE IF NOT EXISTS approval_policy_audit_chain (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prev_hash TEXT NOT NULL,
                    current_hash TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    domain TEXT,
                    policy_key TEXT,
                    old_value TEXT,
                    new_value TEXT,
                    signature_valid INTEGER DEFAULT 1
                );
            """)

            # D05/MED (F013): frueher sperrte der Trigger nur id/prev_hash/
            # current_hash — timestamp, action, new_value und signature_valid
            # waren per SQL-UPDATE aenderbar. Die Erkennung in
            # verify_audit_integrity() war bloss Detektion, keine Verhinderung.
            # Jetzt blockt BEFORE UPDATE ON (ohne OF-Klausel) JEDE Spalte.
            # Bestands-DBs muessen den alten Trigger droppen, damit die neue
            # Definition wirksam wird (CREATE IF NOT EXISTS greift sonst nicht).
            conn.execute("DROP TRIGGER IF EXISTS approval_chain_no_hash_update")
            conn.execute("""
                CREATE TRIGGER approval_chain_no_hash_update
                BEFORE UPDATE ON approval_policy_audit_chain
                BEGIN
                    SELECT RAISE(ABORT, 'approval_policy_audit_chain is append-only');
                END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS approval_chain_no_delete
                BEFORE DELETE ON approval_policy_audit_chain
                BEGIN
                    SELECT RAISE(ABORT, 'approval_policy_audit_chain is append-only');
                END
            """)

            # 3. Approval Requests Queue
            conn.execute("""
                CREATE TABLE IF NOT EXISTS approval_requests (
                    id TEXT PRIMARY KEY,
                    domain TEXT NOT NULL,
                    reference_id TEXT,
                    title TEXT NOT NULL,
                    amount REAL DEFAULT 0.0,
                    currency TEXT DEFAULT 'EUR',
                    status TEXT DEFAULT 'pending',
                    requires_four_eyes INTEGER DEFAULT 0,
                    first_approver TEXT,
                    first_approved_at TEXT,
                    second_approver TEXT,
                    second_approved_at TEXT,
                    rejected_by TEXT,
                    rejected_reason TEXT,
                    escalated_at TEXT,
                    expires_at TEXT,
                    created_at TEXT NOT NULL,
                    payload_json TEXT
                );
            """)
            # D04/MED: Der Antragsteller wird als eigene Spalte persistiert,
            # damit die Ersteller-Sperre engine-seitig (nicht nur im Router)
            # greift. Idempotenter SQLite-ALTER wie in session_taint_guard.py.
            _columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(approval_requests)").fetchall()
            }
            if "requester_id" not in _columns:
                conn.execute("ALTER TABLE approval_requests ADD COLUMN requester_id TEXT")
            if "assigned_approver" not in _columns:
                conn.execute("ALTER TABLE approval_requests ADD COLUMN assigned_approver TEXT")
            if "escalated_to" not in _columns:
                conn.execute("ALTER TABLE approval_requests ADD COLUMN escalated_to TEXT")
            if "escalation_reason" not in _columns:
                conn.execute("ALTER TABLE approval_requests ADD COLUMN escalation_reason TEXT")

            # d14/HIGH: Aenderung der 4-Augen-Schwelle benötigt einen zweiten,
            # unabhaengigen Genehmiger. Einzel-Admin erzeugt nur einen Vorschlag.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS approval_policy_change_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    policy_key TEXT NOT NULL,
                    proposed_value TEXT NOT NULL,
                    old_value TEXT NOT NULL,
                    proposed_by TEXT NOT NULL,
                    approved_by TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                );
            """)

            # 4. Vacation & Delegation Settings
            conn.execute("""
                CREATE TABLE IF NOT EXISTS delegation_settings (
                    user_id TEXT PRIMARY KEY,
                    is_active INTEGER DEFAULT 0,
                    substitute_id TEXT NOT NULL,
                    substitute_name TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

            # Seed default policies if empty
            cur = conn.cursor()
            existing = cur.execute("SELECT COUNT(*) FROM approval_policies").fetchone()[0]
            if existing == 0:
                now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                default_policies = [
                    # Finance Domain
                    ("finance", "finance_auto_approval_max", "50.00", "Auto-Freigabe bis (EUR)", "Belege und Ausgaben unter diesem Betrag werden direkt ohne manuelle Freigabe akzeptiert.", "system"),
                    ("finance", "finance_four_eyes_min", "500.00", "4-Augen-Prüfung ab (EUR)", "Ab diesem Betrag sind zwei unabhängige Freigaben (z.B. Initiator + Controller) zwingend erforderlich.", "system"),
                    ("finance", "finance_timeout_hours", "24", "Eskalationsfrist (Stunden)", "Wartezeit bis zur automatischen Benachrichtigung & Eskalation an Admin.", "system"),
                    
                    # Communication / Email Domain
                    ("email", "email_require_approval", "true", "Freigabepflicht für E-Mail-Entwürfe", "Erfordert 1-Klick-Freigabe für alle extern versendeten KI-Entwürfe.", "system"),
                    ("email", "email_timeout_hours", "12", "E-Mail-Eskalationsfrist (Stunden)", "Frist für Antwortentwürfe in der Inbox vor Erinnerung.", "system"),
                    ("email", "email_whitelist_domains", "internal,archon-os.internal", "Whitelist für Auto-Versand", "Domainliste mit freiem internen Nachrichtenaustausch.", "system"),

                    # System / IT Domain
                    ("system", "system_require_approval_keys", "true", "Freigabe für API-Keys & Scopes", "Schlüssel mit Schreibrechten bedürfen einer Bestätigung.", "system"),
                    ("system", "system_emergency_bypass", "false", "Notfall-Bypass aktiv", "Überbrückung bei Totalausfall externer Validatoren.", "system"),
                    ("system", "system_timeout_hours", "6", "IT-Eskalationsfrist (Stunden)", "Dringende Systemänderungen nach dieser Zeit eskalieren.", "system")
                ]
                
                prev_h = GENESIS_HASH
                # E (Audit): Block-ID an den Schreibpfad geben, damit der
                # gleiche HMAC-Epochen-Key wie in verify_audit_integrity()
                # (r["id"]) verwendet wird.
                next_audit_id = int(cur.execute(
                    "SELECT COALESCE(MAX(id), 0) + 1 FROM approval_policy_audit_chain"
                ).fetchone()[0])
                for domain, key, val, label, desc, user in default_policies:
                    cur.execute("""
                        INSERT INTO approval_policies (domain, policy_key, policy_value, label, description, updated_at, updated_by)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (domain, key, val, label, desc, now, user))

                    # Chained audit log (HMAC-SHA256 wenn ARCHON_AUDIT_HMAC_KEY gesetzt, sonst SHA-256)
                    payload = f"{prev_h}|{now}|{user}|INIT|{domain}|{key}|{val}"
                    curr_h = _chain_hash(payload, next_audit_id)
                    cur.execute("""
                        INSERT INTO approval_policy_audit_chain 
                        (id, prev_hash, current_hash, timestamp, user_id, action, domain, policy_key, old_value, new_value)
                        VALUES (?, ?, ?, ?, ?, 'INIT', ?, ?, '', ?)
                    """, (next_audit_id, prev_h, curr_h, now, user, domain, key, val))
                    prev_h = curr_h
                    next_audit_id += 1

                # Seed default delegation
                cur.execute("""
                    INSERT OR IGNORE INTO delegation_settings (user_id, is_active, substitute_id, substitute_name, updated_at)
                    VALUES ('admin', 0, 'katharina', 'Katharina Völk (QM & Compliance)', ?)
                """, (now,))
                seeded_head = prev_h
                seeded_count = len(default_policies)

            conn.commit()

        # Kaltstart-Fix: Bei erstmaligem Seeding der zentralen DB den initialen Head-Anker
        # sofort verankern, damit ENVIRONMENT=production beim allerersten Start nicht fail-closed abbricht.
        if seeded_head and seeded_count > 0:
            try:
                from backend import audit_log as _audit_mod

                if os.path.abspath(self.db_path) == os.path.abspath(_audit_mod.DB_PATH):
                    _audit_mod.record_chain_anchor(
                        "approval_policy_audit_chain",
                        seeded_head,
                        seeded_count,
                        db_path=self.db_path,
                    )
            except Exception as exc:
                logger.warning("[ApprovalPolicyEngine] Initialer Head-Anker konnte nicht geschrieben werden: %s", exc)

    # --------------------------------------------------------------------------
    # Audit Chain Helper
    # --------------------------------------------------------------------------
    def _log_audit_change(self, user_id: str, action: str, domain: str, key: str, old_val: str, new_val: str, conn: Optional[sqlite3.Connection] = None) -> str:
        from backend.audit_log import _chain_hash
        with self._chain_lock:
            should_close = False
            if conn is None:
                conn = self._get_conn()
                conn.execute("BEGIN IMMEDIATE")
                should_close = True

            cur = conn.cursor()
            last_entry = cur.execute("SELECT current_hash FROM approval_policy_audit_chain ORDER BY id DESC LIMIT 1").fetchone()
            prev_h = last_entry["current_hash"] if last_entry else GENESIS_HASH
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()

            payload = f"{prev_h}|{now}|{user_id}|{action}|{domain}|{key}|{old_val}->{new_val}"
            # E (Audit): gleiche Block-ID wie in verify_audit_integrity().
            next_id = int(cur.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 FROM approval_policy_audit_chain"
            ).fetchone()[0])
            curr_h = _chain_hash(payload, next_id)

            cur.execute("""
                INSERT INTO approval_policy_audit_chain 
                (id, prev_hash, current_hash, timestamp, user_id, action, domain, policy_key, old_value, new_value)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (next_id, prev_h, curr_h, now, user_id, action, domain, key, old_val, new_val))
            conn.commit()

            if should_close:
                conn.close()
            return curr_h

            return curr_h

    # --------------------------------------------------------------------------
    # Policies API
    # --------------------------------------------------------------------------
    def get_policies(self, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            if domain:
                rows = cur.execute("SELECT * FROM approval_policies WHERE domain = ? ORDER BY id ASC", (domain,)).fetchall()
            else:
                rows = cur.execute("SELECT * FROM approval_policies ORDER BY domain ASC, id ASC").fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def _parse_finance_threshold(value: Any, policy_key: str) -> float:
        """Numerische Schwelle mit spanne — bei Parse-Fehler fail-closed."""
        try:
            numeric = float(str(value).strip())
        except (TypeError, ValueError):
            raise ValueError(f"Policy '{policy_key}' muss ein numerischer Betrag sein.")
        if not (0.0 <= numeric <= 1_000_000.0):
            raise ValueError(
                f"Policy '{policy_key}' liegt ausserhalb der erlaubten Spanne (0..1_000_000)."
            )
        return numeric

    def _assert_finance_threshold_invariant(
        self, cur: sqlite3.Cursor, policy_key: str, candidate_value: Any
    ) -> None:
        """D04/HIGH: `auto_max < four_eyes_min` mit Mindestabstand, SYMMETRISCH.

        Frueher wurde die Invariante nur beim Aendern von
        `finance_auto_approval_max` gegen `finance_four_eyes_min` geprueft.
        Ein einzelner Admin konnte daher `finance_four_eyes_min` unter die
        Auto-Freigabeschwelle senken und damit alle Betraege automatisch
        freigeben. Jetzt wird bei jeder Aenderung einer der beiden Schwellen
        das jeweilige Gegenstück aus der DB gelesen und die Invariante mit
        hartem Mindestabstand geprueft (fail-closed bei fehlender/Nicht-Zahl).
        """
        keys = ("finance_auto_approval_max", "finance_four_eyes_min")
        if policy_key not in keys:
            return
        values = {
            key: (
                self._parse_finance_threshold(candidate_value, policy_key)
                if key == policy_key
                else None
            )
            for key in keys
        }
        for key in keys:
            if values[key] is None:
                row = cur.execute(
                    "SELECT policy_value FROM approval_policies WHERE policy_key = ?", (key,)
                ).fetchone()
                if not row:
                    raise ValueError(
                        f"Policy '{key}' fehlt — Schwellen-Invariante nicht pruefbar (fail-closed)."
                    )
                values[key] = self._parse_finance_threshold(row["policy_value"], key)
        gap = values["finance_four_eyes_min"] - values["finance_auto_approval_max"]  # type: ignore[operator, operator, operator]
        if gap + _GAP_EPSILON < FINANCE_THRESHOLD_MIN_GAP:
            raise ValueError(
                "Invariante verletzt: finance_auto_approval_max muss mindestens "
                f"{FINANCE_THRESHOLD_MIN_GAP:.2f} EUR unter finance_four_eyes_min liegen "
                f"(auto_max={values['finance_auto_approval_max']:.2f}, "
                f"four_eyes_min={values['finance_four_eyes_min']:.2f})."
            )

    def update_policy(self, policy_key: str, new_value: str, user_id: str) -> Dict[str, Any]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            row = cur.execute("SELECT * FROM approval_policies WHERE policy_key = ?", (policy_key,)).fetchone()
            if not row:
                raise ValueError(f"Policy-Key {policy_key} nicht gefunden.")

            old_val = row["policy_value"]
            domain = row["domain"]
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()

            # P1/D04/HIGH: Vorher konnte ein Admin finance_auto_approval_max auf
            # 1_000_000 setzen und damit alle Finanzanfragen ohne Vier-Augen-Prinzip
            # automatisch freigeben. Typ, Bereich und die SYMMETRISCHE Invariante
            # (auch bei Aenderung von finance_four_eyes_min) werden jetzt zentral
            # fuer ALLE Aufrufer geprueft.
            self._assert_finance_threshold_invariant(cur, policy_key, new_value)

            # d14/MED: finance_four_eyes_min ist die Hoheits-Schwelle selbst,
            # finance_auto_approval_max die korrespondierende Freigabeschwelle.
            # Ein einzelner Admin darf KEINE von beiden direkt aendern — er
            # erzeugt einen Vorschlag, der von einer zweiten, unabhaengigen
            # Person freigegeben werden muss (4-Augen). Vorher konnte ein
            # Admin die Auto-Freigabe von 50 auf knapp 500 EUR anheben.
            if policy_key in ("finance_four_eyes_min", "finance_auto_approval_max"):
                import uuid
                proposal_id = f"policy-change-{uuid.uuid4().hex}"
                cur.execute("""
                    INSERT INTO approval_policy_change_proposals
                    (proposal_id, policy_key, proposed_value, old_value, proposed_by,
                     approved_by, status, created_at, resolved_at)
                    VALUES (?, ?, ?, ?, ?, NULL, 'pending', ?, NULL)
                """, (proposal_id, policy_key, str(new_value), str(old_val), user_id, now))
                audit_hash = self._log_audit_change(
                    user_id, "PROPOSE_POLICY_CHANGE", domain, policy_key,
                    old_val, new_value, conn=conn,
                )
                conn.commit()
                return {
                    "policy_key": policy_key,
                    "old_value": old_val,
                    "new_value": new_value,
                    "status": "pending_four_eyes",
                    "proposal_id": proposal_id,
                    "message": (
                        f"Aenderung der Finanz-Schwelle '{policy_key}' erfordert eine zweite, "
                        "unabhaengige Freigabe (approve_policy_change_proposal)."
                    ),
                    "audit_hash": audit_hash,
                    "updated_at": now,
                }

            cur.execute("""
                UPDATE approval_policies
                SET policy_value = ?, updated_at = ?, updated_by = ?
                WHERE policy_key = ?
            """, (new_value, now, user_id, policy_key))

            audit_hash = self._log_audit_change(user_id, "UPDATE_POLICY", domain, policy_key, old_val, new_value, conn=conn)
            conn.commit()

            return {
                "policy_key": policy_key,
                "old_value": old_val,
                "new_value": new_value,
                "audit_hash": audit_hash,
                "updated_at": now
            }

    def approve_policy_change_proposal(
        self, proposal_id: str, approver_id: str
    ) -> Dict[str, Any]:
        """Vierte-Augen-Freigabe fuer eine Policy-Aenderung (d14/HIGH).

        Der zweite Genehmiger muss eine andere physische Person sein als der
        Antragsteller; sonst bleibt der Vorschlag pending.
        """
        with self._get_conn() as conn:
            cur = conn.cursor()
            p = cur.execute(
                "SELECT * FROM approval_policy_change_proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
            if not p:
                raise ValueError(f"Policy-Aenderungsvorschlag {proposal_id} nicht gefunden.")
            if p["status"] != "pending":
                raise ValueError(f"Vorschlag {proposal_id} ist bereits {p['status']}.")

            def _identity_tokens(actor: str) -> set:
                s = (actor or "").strip().lower()
                tokens = {s}
                if s:
                    tokens.add(s.split(" ")[0])
                return {t for t in tokens if t}

            proposer = str(p["proposed_by"] or "")
            if approver_id == proposer or bool(
                _identity_tokens(approver_id) & _identity_tokens(proposer)
            ):
                raise ValueError(
                    "Vier-Augen-Prinzip: die zweite Freigabe muss durch eine "
                    "andere Person erfolgen als den Antragsteller."
                )

            key = p["policy_key"]
            if key not in ("finance_four_eyes_min", "finance_auto_approval_max"):
                raise ValueError(f"Vorschlag fuer {key} ist nicht 4-Augen-pflichtig.")
            # D04/HIGH: gleiche symmetrische Invariante wie im Einzel-Admin-Pfad.
            # Vorher wurde auch hier nur `auto_max` gegen `four_eyes_min` geprueft;
            # ein Vorschlag, der `four_eyes_min` unter `auto_max` senkte, ging durch.
            self._assert_finance_threshold_invariant(cur, key, p["proposed_value"])

            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            cur.execute("""
                UPDATE approval_policies SET policy_value = ?, updated_at = ?, updated_by = ?
                WHERE policy_key = ?
            """, (p["proposed_value"], now, approver_id, key))
            cur.execute("""
                UPDATE approval_policy_change_proposals
                SET status = 'approved', approved_by = ?, resolved_at = ?
                WHERE proposal_id = ?
            """, (approver_id, now, proposal_id))
            audit_hash = self._log_audit_change(
                approver_id, "APPROVE_POLICY_CHANGE", "finance", key,
                p["old_value"], p["proposed_value"], conn=conn,
            )
            conn.commit()
            return {
                "policy_key": key,
                "new_value": p["proposed_value"],
                "proposal_id": proposal_id,
                "status": "approved",
                "approved_by": approver_id,
                "audit_hash": audit_hash,
            }

    # --------------------------------------------------------------------------
    # Delegation / Urlaubsmodus (M95 — RBAC-gesichert, nie Agent-Fallback)
    # --------------------------------------------------------------------------
    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _required_deputy_roles(domain: str = "finance") -> FrozenSet[str]:
        if str(domain or "").strip().lower() in ADMIN_ONLY_DEPUTY_DOMAINS:
            return frozenset({"admin"})
        return ALLOWED_DEPUTY_ROLES

    def _lookup_human_user(
        self, conn: sqlite3.Connection, identifier: str
    ) -> Optional[Dict[str, Any]]:
        clean = str(identifier or "").strip()
        if not clean or not self._table_exists(conn, "users"):
            return None
        user_cols = {
            str(r["name"]) for r in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        tg_chat_expr = (
            "COALESCE(telegram_chat_id, '') AS telegram_chat_id"
            if "telegram_chat_id" in user_cols
            else "'' AS telegram_chat_id"
        )
        row = conn.execute(
            f"SELECT id, username, display_name, role, is_active, {tg_chat_expr} "
            "FROM users WHERE id = ? OR lower(username) = ? LIMIT 1",
            (clean, clean.lower()),
        ).fetchone()
        if not row:
            return None
        return {
            "id": str(row["id"]),
            "username": str(row["username"]),
            "display_name": str(row["display_name"] or row["username"]),
            "role": str(row["role"] or "viewer").lower().strip(),
            "is_active": bool(row["is_active"]),
            "telegram_chat_id": str(row["telegram_chat_id"] or "").strip(),
        }

    def validate_human_deputy(
        self,
        substitute_id: str,
        *,
        delegating_user_id: Optional[str] = None,
        domain: str = "finance",
        conn: Optional[sqlite3.Connection] = None,
        strict_rbac: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Prueft, dass der Stellvertreter ein aktiver Mensch mit ausreichender RBAC-Rolle ist.

        Harte M95-Invariante: Niemals Agent, System-Default, Viewer, inaktiver User
        oder Selbst-Delegation.
        """
        sub = str(substitute_id or "").strip()
        if is_agent_or_system_identity(sub):
            raise ValueError(
                f"Ungueltiger Stellvertreter '{sub}': Agenten oder System-Defaults duerfen "
                "niemals als HITL-/4-Augen-Stellvertreter eingesetzt werden."
            )

        owner = str(delegating_user_id or "").strip()
        if owner and bool(_actor_identity_tokens(owner) & _actor_identity_tokens(sub)):
            raise ValueError(
                "Selbst-Delegation ist unzulaessig: Stellvertreter muss eine andere Person sein."
            )

        def _check(c: sqlite3.Connection) -> Dict[str, Any]:
            has_users = self._table_exists(c, "users")
            enforce = has_users if strict_rbac is None else bool(strict_rbac)
            required_roles = self._required_deputy_roles(domain)
            if not enforce:
                return {
                    "id": sub,
                    "username": sub,
                    "display_name": sub,
                    "role": "operator",
                    "is_active": True,
                    "telegram_chat_id": "",
                }

            user = self._lookup_human_user(c, sub)
            if not user:
                raise ValueError(
                    f"Stellvertreter '{sub}' ist kein registrierter menschlicher Benutzer (fail-closed)."
                )
            if not user["is_active"]:
                raise ValueError(
                    f"Stellvertreter '{user['username']}' ist deaktiviert und nicht freigabeberechtigt."
                )
            if user["role"] not in required_roles:
                raise ValueError(
                    f"Stellvertreter '{user['username']}' hat Rolle '{user['role']}' "
                    f"(erforderlich: {', '.join(sorted(required_roles))}; Viewer ausgeschlossen)."
                )
            if owner:
                owner_user = self._lookup_human_user(c, owner)
                if owner_user and owner_user["id"] == user["id"]:
                    raise ValueError(
                        "Selbst-Delegation ist unzulaessig: Stellvertreter ist identisch mit dem Abwesenden."
                    )
            # Keine Delegationsschleife: wenn Stellvertreter selbst im Urlaubsmodus ist -> fail-closed
            if self._table_exists(c, "delegation_settings"):
                sub_deleg = c.execute(
                    "SELECT is_active FROM delegation_settings WHERE lower(user_id) IN (?, ?) AND is_active = 1",
                    (user["id"].lower(), user["username"].lower()),
                ).fetchone()
                if sub_deleg:
                    raise ValueError(
                        f"Stellvertreter '{user['username']}' befindet sich selbst im Urlaubsmodus (fail-closed)."
                    )
            return user

        if conn is not None:
            return _check(conn)
        with self._get_conn() as own_conn:
            return _check(own_conn)

    def resolve_human_escalation_target(
        self,
        owner_user_id: str,
        *,
        domain: str = "finance",
        requester_id: Optional[str] = None,
        first_approver: Optional[str] = None,
        conn: Optional[sqlite3.Connection] = None,
        strict_rbac: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Ermittelt den gueltigen menschlichen Stellvertreter oder blockiert fail-closed."""
        def _resolve(c: sqlite3.Connection) -> Dict[str, Any]:
            if not self._table_exists(c, "delegation_settings"):
                return {
                    "resolved": False,
                    "status": "escalated_blocked",
                    "deputy": None,
                    "reason": "Keine delegation_settings vorhanden (fail-closed).",
                }
            row = c.execute(
                "SELECT * FROM delegation_settings WHERE lower(user_id) = ? LIMIT 1",
                (str(owner_user_id or "admin").strip().lower(),),
            ).fetchone()
            if not row or not str(row["substitute_id"] or "").strip():
                return {
                    "resolved": False,
                    "status": "escalated_blocked",
                    "deputy": None,
                    "reason": f"Kein menschlicher Stellvertreter fuer '{owner_user_id}' hinterlegt (fail-closed).",
                }
            sub_id = str(row["substitute_id"]).strip()
            try:
                deputy = self.validate_human_deputy(
                    sub_id,
                    delegating_user_id=owner_user_id,
                    domain=domain,
                    conn=c,
                    strict_rbac=strict_rbac,
                )
            except ValueError as exc:
                return {
                    "resolved": False,
                    "status": "escalated_blocked",
                    "deputy": None,
                    "reason": str(exc),
                }

            deputy_tokens = _actor_identity_tokens(deputy["username"]) | _actor_identity_tokens(deputy["id"])
            if requester_id and bool(deputy_tokens & _actor_identity_tokens(requester_id)):
                return {
                    "resolved": False,
                    "status": "escalated_blocked",
                    "deputy": None,
                    "reason": "Vier-Augen-Konflikt: Stellvertreter ist identisch mit Antragsteller (fail-closed).",
                }
            if first_approver and bool(deputy_tokens & _actor_identity_tokens(first_approver)):
                return {
                    "resolved": False,
                    "status": "escalated_blocked",
                    "deputy": None,
                    "reason": "Vier-Augen-Konflikt: Stellvertreter hat bereits Erstfreigabe erteilt (fail-closed).",
                }

            return {
                "resolved": True,
                "status": "escalated",
                "deputy": deputy,
                "reason": f"Eskaliert an menschlichen Stellvertreter '{deputy['username']}' ({deputy['role']}).",
            }

        if conn is not None:
            return _resolve(conn)
        with self._get_conn() as own_conn:
            return _resolve(own_conn)

    def get_delegation(self, user_id: str = "admin") -> Dict[str, Any]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            row = cur.execute("SELECT * FROM delegation_settings WHERE user_id = ?", (user_id,)).fetchone()
            if row:
                return dict(row)
            return {
                "user_id": user_id,
                "is_active": 0,
                "substitute_id": "",
                "substitute_name": "",
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }

    def set_delegation(
        self,
        user_id: str,
        is_active: bool,
        substitute_id: str,
        substitute_name: str = "",
        *,
        domain: str = "finance",
        strict_rbac: Optional[bool] = None,
    ) -> Dict[str, Any]:
        clean_user = str(user_id or "").strip()
        if not clean_user:
            raise ValueError("user_id darf nicht leer sein.")
        clean_sub_id = str(substitute_id or "").strip()
        clean_sub_name = str(substitute_name or "").strip()

        with self._get_conn() as conn:
            verified_deputy: Optional[Dict[str, Any]] = None
            if is_active:
                verified_deputy = self.validate_human_deputy(
                    clean_sub_id,
                    delegating_user_id=clean_user,
                    domain=domain,
                    conn=conn,
                    strict_rbac=strict_rbac,
                )
                if not clean_sub_name:
                    clean_sub_name = str(verified_deputy.get("display_name") or clean_sub_id)
            elif clean_sub_id and is_agent_or_system_identity(clean_sub_id):
                raise ValueError(
                    f"Ungueltiger Stellvertreter '{clean_sub_id}': Agenten oder System-Defaults sind unzulaessig."
                )

            cur = conn.cursor()
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            prev_row = cur.execute(
                "SELECT is_active, substitute_id, substitute_name FROM delegation_settings WHERE user_id = ?",
                (clean_user,),
            ).fetchone()
            old_state = (
                f"{'active' if prev_row['is_active'] else 'inactive'}:{prev_row['substitute_id']}"
                if prev_row
                else "inactive"
            )
            cur.execute("""
                INSERT INTO delegation_settings (user_id, is_active, substitute_id, substitute_name, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    is_active = excluded.is_active,
                    substitute_id = excluded.substitute_id,
                    substitute_name = excluded.substitute_name,
                    updated_at = excluded.updated_at
            """, (clean_user, 1 if is_active else 0, clean_sub_id, clean_sub_name, now))

            action = "ENABLE_DELEGATION" if is_active else "DISABLE_DELEGATION"
            audit_hash = self._log_audit_change(
                clean_user,
                action,
                "system",
                "delegation_settings",
                old_state,
                f"{'active' if is_active else 'inactive'}:{clean_sub_id}:{clean_sub_name}",
                conn=conn,
            )
            conn.commit()

        _record_central_audit(
            "approval_delegation",
            "VACATION_MODE_ENABLED" if is_active else "VACATION_MODE_DISABLED",
            clean_user,
            {
                "user_id": clean_user,
                "is_active": bool(is_active),
                "substitute_id": clean_sub_id,
                "substitute_name": clean_sub_name,
                "substitute_role": (verified_deputy or {}).get("role", ""),
                "audit_hash": audit_hash,
            },
        )
        return {
            "user_id": clean_user,
            "is_active": 1 if is_active else 0,
            "substitute_id": clean_sub_id,
            "substitute_name": clean_sub_name,
            "substitute_role": (verified_deputy or {}).get("role", ""),
            "audit_hash": audit_hash,
        }

    # --------------------------------------------------------------------------
    # Request Evaluation & Queue
    # --------------------------------------------------------------------------
    def evaluate_and_enqueue(self, domain: str, title: str, amount: float = 0.0,
                             reference_id: Optional[str] = None, payload: Optional[dict] = None,
                             requester_id: Optional[str] = None,
                             force_four_eyes: bool = False,
                             requester_required: bool = False,
                             assigned_approver: Optional[str] = None) -> Dict[str, Any]:
        # D04/MED: requester_id ist jetzt Teil des Engine-Vertrags. Er wird
        # zusaetzlich signiert im payload_json abgelegt (defense in depth),
        # damit auch Router/Caller ohne Spaltenzugriff den Ersteller pruefen.
        stored_payload = dict(payload or {})
        requester = str(requester_id or "").strip()
        if requester:
            stored_payload.setdefault("_requester_id", requester)
        # D14/M4: HITL-pflichtige Antraege markieren die Erstellerpflicht
        # explizit im signierten Payload. `approve_request()` leert damit nicht
        # still laufen, falls die requester_id-Spalte aus einem Legacy-Pfad
        # leer bleibt.
        requires_requester = bool(
            requester
            or requester_required
            or force_four_eyes
            or str(domain or "").strip().lower() in HITL_REQUIRED_DOMAINS
        )
        if requires_requester:
            stored_payload.setdefault("_requester_required", True)
        policies = {p["policy_key"]: p["policy_value"] for p in self.get_policies(domain)}
        now = datetime.datetime.now(datetime.timezone.utc)
        now_iso = now.isoformat()

        req_id = f"REQ-{now.strftime('%Y%m%d')}-{os.urandom(3).hex().upper()}"
        auto_max = float(policies.get("finance_auto_approval_max", "50.00"))
        four_eyes_min = float(policies.get("finance_four_eyes_min", "500.00"))
        timeout_hours = int(policies.get("finance_timeout_hours", "24"))

        owner_approver = str(assigned_approver or "admin").strip() or "admin"
        deleg = self.get_delegation(owner_approver)
        delegation_active = bool(deleg.get("is_active"))
        active_substitute: Optional[str] = None
        escalated_to: Optional[str] = None
        escalation_reason: Optional[str] = None

        # Check conditions
        # F022/H-14-3: Hoheitsaenderungen (z.B. AI-Act-Downgrades) sind immer
        # 4-Augen-pflichtig — unabhaengig von einem Geldbetrag.
        requires_four_eyes = 1 if (force_four_eyes or amount >= four_eyes_min) else 0
        expires_at = (now + datetime.timedelta(hours=timeout_hours)).isoformat()

        # D04/HIGH: Auto-Freigabe NUR wenn die Invariante auch tatsaechlich
        # greift. Ein Betrag, der die Vier-Augen-Schwelle erreicht/ueberschreitet,
        # darf niemals automatisch freigegeben werden.
        if amount <= auto_max and not requires_four_eyes and domain == "finance":
            status = "auto_approved"
            first_approver = "System-Rule (Auto-Approval <= 50 EUR)"
            first_approved_at = now_iso
        else:
            status = "pending"
            first_approver = None
            first_approved_at = None

        # M95: Bei aktivem Urlaubsmodus menschlichen Stellvertreter pruefen (nie Agent, fail-closed)
        if status == "pending" and delegation_active:
            esc = self.resolve_human_escalation_target(
                owner_approver,
                domain=domain,
                requester_id=requester or None,
            )
            if esc["resolved"] and esc["deputy"]:
                escalated_to = str(esc["deputy"]["username"])
                active_substitute = str(deleg.get("substitute_name") or esc["deputy"]["display_name"])
                escalation_reason = str(esc["reason"])
            else:
                status = "escalated_blocked"
                escalated_to = None
                active_substitute = None
                escalation_reason = str(esc["reason"])

        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO approval_requests (
                    id, domain, reference_id, title, amount, currency, status,
                    requires_four_eyes, first_approver, first_approved_at,
                    expires_at, created_at, payload_json, requester_id,
                    assigned_approver, escalated_to, escalation_reason
                ) VALUES (?, ?, ?, ?, ?, 'EUR', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                req_id, domain, reference_id, title, amount, status,
                requires_four_eyes, first_approver, first_approved_at,
                expires_at, now_iso, json.dumps(stored_payload, ensure_ascii=False),
                requester or None, owner_approver, escalated_to, escalation_reason,
            ))
            conn.commit()

        # Audit log creation
        self._log_audit_change("system", "ENQUEUE_REQUEST", domain, req_id, "NONE", status)
        if delegation_active and status in ("pending", "escalated_blocked"):
            esc_action = "DEPUTY_ESCALATION" if escalated_to else "ESCALATION_BLOCKED_FAIL_CLOSED"
            self._log_audit_change(
                owner_approver,
                esc_action,
                domain,
                req_id,
                "pending",
                f"{escalated_to or 'BLOCKED'}:{escalation_reason or ''}",
            )
            _record_central_audit(
                "approval_escalation",
                esc_action,
                owner_approver,
                {
                    "request_id": req_id,
                    "domain": domain,
                    "status": status,
                    "assigned_approver": owner_approver,
                    "escalated_to": escalated_to,
                    "reason": escalation_reason or "",
                },
            )

        return {
            "request_id": req_id,
            "domain": domain,
            "title": title,
            "amount": amount,
            "status": status,
            "requires_four_eyes": bool(requires_four_eyes),
            "assigned_approver": owner_approver,
            "delegation_active": delegation_active,
            "delegated_to": active_substitute,
            "escalated_to": escalated_to,
            "escalation_reason": escalation_reason,
            "expires_at": expires_at,
        }

    def get_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Eine Freigabeanfrage exakt nach ID (kein Listen-Scan, kein stilles Fallback)."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM approval_requests WHERE id = ?", (request_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_requests(self, status: Optional[str] = None, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        self.check_and_escalate_timeouts()
        with self._get_conn() as conn:
            cur = conn.cursor()
            query = "SELECT * FROM approval_requests WHERE 1=1"
            params = []
            if status:
                query += " AND status = ?"
                params.append(status)
            if domain:
                query += " AND domain = ?"
                params.append(domain)
            query += " ORDER BY created_at DESC LIMIT 100"
            rows = cur.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def approve_request(self, request_id: str, approver_id: str) -> Dict[str, Any]:
        # D04/MED + M95: kein Default-Approver, kein Agent, kein Viewer.
        if is_agent_or_system_identity(approver_id):
            raise ValueError(
                f"Freigabe verweigert: '{approver_id}' ist eine Agenten-/System-Identitaet "
                "(HITL-/4-Augen-Freigaben erfordern einen berechtigten Menschen)."
            )
        with self._chain_lock:
            with self._get_conn() as conn:
                conn.execute("BEGIN IMMEDIATE")
                cur = conn.cursor()
                req = cur.execute("SELECT * FROM approval_requests WHERE id = ?", (request_id,)).fetchone()
                if not req:
                    raise ValueError("Freigabeanfrage nicht gefunden.")

                if req["status"] in ("approved", "rejected"):
                    raise ValueError(f"Anfrage kann nicht genehmigt werden (aktueller Status: {req['status']}).")

                # M95: RBAC-Rollenpruefung wenn users-Tabelle existiert (Viewer / Inaktive blockieren)
                approver_user = self._lookup_human_user(conn, approver_id)
                if approver_user is not None:
                    if not approver_user["is_active"]:
                        raise ValueError(f"Freigabe verweigert: Benutzer '{approver_user['username']}' ist deaktiviert.")
                    allowed_roles = self._required_deputy_roles(str(req["domain"] or "finance"))
                    if approver_user["role"] not in allowed_roles:
                        raise ValueError(
                            f"Freigabe verweigert: Rolle '{approver_user['role']}' darf Domain "
                            f"'{req['domain']}' nicht freigeben (erforderlich: {', '.join(sorted(allowed_roles))})."
                        )

                # D04/MED: Ersteller-Sperre zentral im Engine — nicht nur im
                # Router. Jeder Aufrufer (u. a. MCP-Pfad) ist damit gebunden.
                # Quelle: eigene Spalte -> signiertes Payload -> created_by.
                pl = req["payload_json"]
                if isinstance(pl, str):
                    try:
                        pl = json.loads(pl)
                    except (TypeError, ValueError):
                        pl = {}
                if not isinstance(pl, dict):
                    pl = {}
                requester = str(req["requester_id"] or "").strip()
                if not requester:
                    requester = str(pl.get("_requester_id") or pl.get("requester_id") or "").strip()
                if not requester and "created_by" in req.keys():
                    requester = str(req["created_by"] or "").strip()
                # D14/M4: bei HITL-pflichtigen Antraegen darf ein leerer
                # Ersteller nicht still durchgewinkt werden — sonst ist die
                # Ersteller-Sperre wirkungslos und eine identifizierte Person
                # kann sich selbst freigeben.
                if not requester and bool(pl.get("_requester_required")):
                    raise ValueError(
                        "Vier-Augen-Prinzip: Ersteller der Freigabeanfrage nicht verifizierbar "
                        "— Freigabe verweigert (fail-closed)."
                    )
                if requester and bool(
                    _actor_identity_tokens(approver_id) & _actor_identity_tokens(requester)
                ):
                    raise ValueError(
                        "Vier-Augen-Prinzip: der Ersteller darf die eigene Freigabeanfrage nicht genehmigen."
                    )

                now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                deleg_row = cur.execute("SELECT * FROM delegation_settings WHERE user_id = ?", (approver_id,)).fetchone()
                is_deleg_active = bool(deleg_row["is_active"]) if deleg_row else False
                sub_name = deleg_row["substitute_name"] if deleg_row else "Katharina Völk (QM)"
                actual_approver = f"{approver_id} (i.V. {sub_name})" if is_deleg_active else approver_id

                if req["requires_four_eyes"]:
                    if not req["first_approver"]:
                        # 1st approval step
                        cur.execute("""
                            UPDATE approval_requests
                            SET first_approver = ?, first_approved_at = ?, status = 'first_approved'
                            WHERE id = ?
                        """, (actual_approver, now, request_id))
                        new_status = "first_approved"
                    else:
                        # 2nd approval step: Prüfen, dass zweite Genehmigung von einer anderen physischen Person stammt
                        def _identity_tokens(actor_str: str) -> set:
                            s = (actor_str or "").strip().lower()
                            tokens = set()
                            if " (i.v. " in s:
                                main_p, sub_p = s.split(" (i.v. ", 1)
                                tokens.add(main_p.strip())
                                sub_clean = sub_p.rstrip(")").strip()
                                if sub_clean:
                                    tokens.add(sub_clean)
                                    tokens.add(sub_clean.split(" ")[0])
                            elif s:
                                tokens.add(s)
                                tokens.add(s.split(" ")[0])
                            return {t for t in tokens if t}

                        first_ids = _identity_tokens(req["first_approver"])
                        second_ids = _identity_tokens(actual_approver)
                        if req["first_approver"] == actual_approver or bool(first_ids & second_ids):
                            raise ValueError("Vier-Augen-Prinzip: Zweitgenehmigung muss durch eine andere Person erfolgen.")
                        cur.execute("""
                            UPDATE approval_requests
                            SET second_approver = ?, second_approved_at = ?, status = 'approved'
                            WHERE id = ?
                        """, (actual_approver, now, request_id))
                        new_status = "approved"
                else:
                    cur.execute("""
                        UPDATE approval_requests
                        SET first_approver = ?, first_approved_at = ?, status = 'approved'
                        WHERE id = ?
                    """, (actual_approver, now, request_id))
                    new_status = "approved"

                audit_hash = self._log_audit_change(actual_approver, "APPROVE_REQUEST", req["domain"], request_id, req["status"], new_status, conn=conn)
                conn.commit()

            return {
                "request_id": request_id,
                "status": new_status,
                "approver": actual_approver,
                "timestamp": now,
                "audit_hash": audit_hash
            }

    def reject_request(self, request_id: str, rejected_by: str, reason: str) -> Dict[str, Any]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            req = cur.execute("SELECT * FROM approval_requests WHERE id = ?", (request_id,)).fetchone()
            if not req:
                raise ValueError("Freigabeanfrage nicht gefunden.")

            if req["status"] in ("approved", "rejected"):
                raise ValueError(f"Anfrage kann nicht abgelehnt werden (aktueller Status: {req['status']}).")

            now = datetime.datetime.now(datetime.timezone.utc).isoformat()  # noqa: F841
            cur.execute("""
                UPDATE approval_requests
                SET status = 'rejected', rejected_by = ?, rejected_reason = ?
                WHERE id = ?
            """, (rejected_by, reason, request_id))

            audit_hash = self._log_audit_change(rejected_by, "REJECT_REQUEST", req["domain"], request_id, req["status"], f"REJECTED: {reason}", conn=conn)
            conn.commit()

            return {
                "request_id": request_id,
                "status": "rejected",
                "rejected_by": rejected_by,
                "reason": reason,
                "audit_hash": audit_hash
            }

    def check_and_escalate_timeouts(self) -> int:
        """Finds requests that exceeded their expiry time and escalates them fail-closed (M95).

        Harte Invariante: Timeout fuehrt niemals zu Auto-Approval oder Agent-Delegation.
        Eskalation erfolgt ausschliesslich an einen verifizierten menschlichen RBAC-Stellvertreter;
        fehlt dieser, wird die Anfrage fail-closed auf ``escalated_blocked`` gesetzt.
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        central_events: List[Dict[str, Any]] = []
        with self._get_conn() as conn:
            cur = conn.cursor()
            req_cols = {
                str(c["name"]) for c in cur.execute("PRAGMA table_info(approval_requests)").fetchall()
            }
            has_m95_cols = {"assigned_approver", "escalated_to", "escalation_reason"}.issubset(req_cols)
            has_users = self._table_exists(conn, "users")
            has_deleg = self._table_exists(conn, "delegation_settings")

            select_cols = ["id", "title", "amount", "domain", "status"]
            for opt_col in ("requester_id", "first_approver", "assigned_approver"):
                if opt_col in req_cols:
                    select_cols.append(opt_col)
            rows = cur.execute(
                f"SELECT {', '.join(select_cols)} FROM approval_requests "
                "WHERE status IN ('pending', 'first_approved') AND expires_at < ?",
                (now,),
            ).fetchall()

            escalated_count = 0
            for r in rows:
                old_status = str(r["status"] or "pending")
                if has_users and has_deleg:
                    owner = (
                        str(r["assigned_approver"] or "").strip()
                        if "assigned_approver" in req_cols
                        else ""
                    ) or "admin"
                    requester = str(r["requester_id"] or "").strip() if "requester_id" in req_cols else None
                    first_app = str(r["first_approver"] or "").strip() if "first_approver" in req_cols else None
                    esc = self.resolve_human_escalation_target(
                        owner,
                        domain=str(r["domain"] or "finance"),
                        requester_id=requester or None,
                        first_approver=first_app or None,
                        conn=conn,
                        strict_rbac=True,
                    )
                    new_status = str(esc["status"])  # 'escalated' | 'escalated_blocked'
                    target_human = str(esc["deputy"]["username"]) if esc["resolved"] and esc["deputy"] else None
                    esc_reason = str(esc["reason"])
                    audit_action = "ESCALATE_TO_DEPUTY" if target_human else "ESCALATE_BLOCKED_FAIL_CLOSED"
                    audit_new = f"{new_status}:{target_human or 'NO_HUMAN_DEPUTY'}"
                else:
                    # Kompatibilitaet fuer isolierte Legacy-Schema-Tests ohne users-Tabelle
                    new_status = "escalated"
                    target_human = None
                    esc_reason = "Timeout eskaliert"
                    audit_action = "ESCALATE_REQUEST"
                    audit_new = "escalated"

                if has_m95_cols:
                    cur.execute(
                        """
                        UPDATE approval_requests
                        SET status = ?, escalated_at = ?, escalated_to = ?, escalation_reason = ?
                        WHERE id = ?
                        """,
                        (new_status, now, target_human, esc_reason, r["id"]),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE approval_requests
                        SET status = ?, escalated_at = ?
                        WHERE id = ?
                        """,
                        (new_status, now, r["id"]),
                    )
                # N-08: Die Audit-Schreibung muss auf DERSELBEN Verbindung laufen.
                self._log_audit_change(
                    "system_watchdog",
                    audit_action,
                    str(r["domain"]),
                    str(r["id"]),
                    old_status,
                    audit_new,
                    conn=conn,
                )
                central_events.append({
                    "action": audit_action,
                    "request_id": str(r["id"]),
                    "domain": str(r["domain"]),
                    "old_status": old_status,
                    "new_status": new_status,
                    "escalated_to": target_human,
                    "reason": esc_reason,
                })
                escalated_count += 1

            if escalated_count > 0:
                conn.commit()

        for ev in central_events:
            _record_central_audit("approval_escalation", ev["action"], "system_watchdog", ev)

        return escalated_count

    def get_audit_chain(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Returns the cryptographically chained audit log for verification."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            rows = cur.execute("""
                SELECT * FROM approval_policy_audit_chain ORDER BY id DESC LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]

    def verify_audit_integrity(self) -> Dict[str, Any]:
        """d05 F-03: Kette + signierter Head-Anker + Trigger."""
        from backend.audit_log import finalize_secondary_chain_verification
        return finalize_secondary_chain_verification(
            "approval_policy_audit_chain", self._verify_audit_integrity_raw(), db_path=self.db_path
        )

    def _verify_audit_integrity_raw(self) -> Dict[str, Any]:
        """Validates all SHA-256 / HMAC-SHA256 hashes in sequence from genesis."""
        from backend.audit_log import HMAC_PREFIX, _hmac_epochs, _verify_hash
        with self._get_conn() as conn:
            cur = conn.cursor()
            rows = cur.execute("SELECT * FROM approval_policy_audit_chain ORDER BY id ASC").fetchall()
            
            if not rows:
                return {"valid": True, "count": 0, "hmac_active": bool(_hmac_epochs()), "hmac_blocks": 0, "message": "Audit-Kette ist leer."}

            prev_hash = GENESIS_HASH
            hmac_blocks = 0
            for r in rows:
                if r["prev_hash"] != prev_hash:
                    return {
                        "valid": False,
                        "broken_at_id": r["id"],
                        "message": f"Kettenbruch bei Eintrag ID {r['id']}: prev_hash stimmt nicht überein."
                    }
                if str(r["current_hash"] or "").startswith(HMAC_PREFIX):
                    hmac_blocks += 1
                # R-30: Validiere auch den berechneten Hash ueber dem tatsaechlichen Inhalt der Zeile
                if r["action"] == "INIT":
                    payload = f"{r['prev_hash']}|{r['timestamp']}|{r['user_id']}|INIT|{r['domain']}|{r['policy_key']}|{r['new_value']}"
                else:
                    payload = f"{r['prev_hash']}|{r['timestamp']}|{r['user_id']}|{r['action']}|{r['domain']}|{r['policy_key']}|{r['old_value']}->{r['new_value']}"
                # H4 (Audit 23.11.2026): Block-ID uebergeben, sonst werden
                # nach einer HMAC-Epochen-Rotation alle alten Bloecke mit dem
                # NEUEN Key geprueft -> falscher Manipulationsalarm.
                if not _verify_hash(payload, str(r["current_hash"] or ""), r["id"]):
                    return {
                        "valid": False,
                        "broken_at_id": r["id"],
                        "message": f"Payload-Manipulation bei Eintrag ID {r['id']}: Berechneter Hash stimmt nicht mit aktuellem Zeileninhalt überein."
                    }
                prev_hash = r["current_hash"]

            key_active = bool(_hmac_epochs())
            if key_active:
                try:
                    legacy_max = int(os.environ.get("ARCHON_AUDIT_LEGACY_MAX_BLOCK", "0") or 0)
                except ValueError:
                    legacy_max = 0
                # d05 F-01: Voller HMAC-Downgrade (auch wenn hmac_blocks == 0) muss erkannt werden.
                downgraded_ids = [
                    int(r["id"]) for r in rows
                    if not str(r["current_hash"] or "").startswith(HMAC_PREFIX)
                    and int(r["id"]) > legacy_max
                ]
                if downgraded_ids:
                    return {
                        "valid": False,
                        "count": len(rows),
                        "hmac_active": True,
                        "hmac_blocks": hmac_blocks,
                        "downgraded_ids": downgraded_ids[:10],
                        "message": (
                            "HMAC-Key ist aktiv, aber Approval-Policy-Audit-Block(e) ohne HMAC-Signatur "
                            "vorhanden (moeglicher Downgrade auf nacktes SHA-256)."
                        ),
                    }
            if hmac_blocks and not key_active:
                return {
                    "valid": False,
                    "count": len(rows),
                    "hmac_active": False,
                    "hmac_blocks": hmac_blocks,
                    "message": "HMAC-Signaturpruefung fehlgeschlagen: ARCHON_AUDIT_HMAC_KEY fehlt."
                }

            return {
                "valid": True,
                "count": len(rows),
                "hmac_active": key_active,
                "hmac_blocks": hmac_blocks,
                "latest_hash": prev_hash,
                "message": f"Kryptografische Integrität bestätigt ({len(rows)} Einträge manipulationssicher verkettet)."
            }

approval_engine = ApprovalPolicyEngine()
