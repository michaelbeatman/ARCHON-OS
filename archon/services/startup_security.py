"""Startup-Sicherheits- und Audit-Integritaets-Gates (M2 aus main.py).

Reine Extraktion ohne Rueckimport auf ``main``:
* ``_AUDIT_COMPROMISED`` und ``AUDIT_COMPROMISED`` sind dasselbe Dict-Objekt
  und werden in ``main.py`` per X-as-X Re-Export identisch bereitgestellt.
* Die 5 ``_STARTUP_HOOKS.insert(0, ...)``-Registrierungen und ``_FAIL_FAST_HOOKS``
  bleiben physisch in ``main.py``.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
import threading
import time
from typing import Any, Callable, Dict, NamedTuple, Optional

logger = logging.getLogger("archon_os")

_AUDIT_COMPROMISED: Dict[str, Any] = {
    "compromised": False,
    "reason": "",
    "chains": [],
    "ts": 0.0,
}
AUDIT_COMPROMISED = _AUDIT_COMPROMISED
_AUDIT_COMPROMISED_LOCK = threading.Lock()

_LOCAL_BINDS = {"127.0.0.1", "localhost", "::1", "[::1]"}


class StartupSecurityDeps(NamedTuple):
    """Call-Time-Hooks aus main.py, damit monkeypatch.setattr(main, ...) greift."""

    verify_all_audit_chains: Callable[[], Dict[str, Dict[str, Any]]]
    audit_integrity_enforced: Callable[[], bool]
    mark_audit_compromised: Callable[[str, Dict[str, Any]], None]
    must_force_auth: Callable[[], bool]
    nonloopback_bind_detected: Callable[[], bool]


_DEPS_PROVIDER: Optional[Callable[[], StartupSecurityDeps]] = None


def register_startup_security_deps_provider(
    provider: Callable[[], StartupSecurityDeps],
) -> None:
    """Registriert den Call-Time-Resolver fuer main.py (S3-Muster)."""
    global _DEPS_PROVIDER
    _DEPS_PROVIDER = provider


def _deps() -> Optional[StartupSecurityDeps]:
    return _DEPS_PROVIDER() if _DEPS_PROVIDER is not None else None


def _mark_audit_compromised(label: str, result: Dict[str, Any]) -> None:
    """Loggt den Befund immer auf ERROR; setzt das 503-Flag im Produktivpfad."""
    if not isinstance(result, dict) or result.get("valid") is not False:
        return
    reason = str(
        result.get("reason") or result.get("message") or "Integritätsprüfung fehlgeschlagen"
    )
    corrupted = str(result.get("corrupted_id") or "")
    if corrupted:
        reason = f"{reason} (corrupted_id={corrupted})"
    logger.error("[Audit][Integritaet] %s INVALID: %s", label, result)
    d = _deps()
    enforced_fn = d.audit_integrity_enforced if d is not None else _audit_integrity_enforced
    if not enforced_fn():
        return
    with _AUDIT_COMPROMISED_LOCK:
        _AUDIT_COMPROMISED["compromised"] = True
        _AUDIT_COMPROMISED["reason"] = f"{label}: {reason}"
        chains = list(_AUDIT_COMPROMISED.get("chains") or [])
        if label not in chains:
            chains.append(label)
        _AUDIT_COMPROMISED["chains"] = chains
        _AUDIT_COMPROMISED["ts"] = time.time()


def _nonloopback_bind_detected() -> bool:
    """Erkennt einen Nicht-Loopback-Bind aus ENV *und* Prozess-Kommandozeile."""
    for var in ("ARCHON_BIND_IP", "UVICORN_HOST", "HOST"):
        val = str(os.environ.get(var) or "").strip().strip("[]")
        if val and val not in _LOCAL_BINDS:
            return True
    argv = list(sys.argv or [])
    for idx, arg in enumerate(argv):
        val = ""
        if arg == "--host" and idx + 1 < len(argv):
            val = str(argv[idx + 1] or "").strip()
        elif arg.startswith("--host="):
            val = arg.split("=", 1)[1].strip()
        val = val.strip("[]")
        if val and val not in _LOCAL_BINDS:
            return True
    return False


def _must_force_auth() -> bool:
    """Erweitert auth_service._must_force_auth() um den echten uvicorn-Bind."""
    try:
        from backend.auth_service import auth_service

        if auth_service._must_force_auth():
            return True
    except Exception as exc:
        logger.error(f"[Auth] _must_force_auth nicht lesbar (fail-closed): {exc}")
        return True
    d = _deps()
    nonloopback_fn = d.nonloopback_bind_detected if d is not None else _nonloopback_bind_detected
    return nonloopback_fn()


def _assert_auth_on_nonloopback_bind() -> None:
    """Nicht-Loopback-Bind ohne Auth ist Fail-Open -> Start hart abbrechen."""
    d = _deps()
    force_fn = d.must_force_auth if d is not None else _must_force_auth
    if not force_fn():
        return
    try:
        from backend.auth_service import AuthService

        auth_enabled = AuthService._read_auth_enabled()
    except Exception as exc:
        logger.error(f"[Auth] Auth-Konfiguration bei Nicht-Loopback-Bind nicht pruefbar: {exc}")
        raise RuntimeError(
            "[Auth] Auth-Konfiguration nicht pruefbar — Start abgebrochen (fail-closed)."
        ) from exc
    if not auth_enabled:
        raise RuntimeError(
            "[Auth] Nicht-Loopback-Bind (z. B. 0.0.0.0) oder Produktion erkannt, aber "
            "auth.enabled ist in settings.json nicht explizit aktiviert — "
            "Start abgebrochen (fail-closed). Auth aktivieren oder an 127.0.0.1 binden."
        )


def _assert_api_key_pepper() -> None:
    """D04/H-04-2: Produktion ohne ARCHON_API_KEY_PEPPER darf nicht starten."""
    env_name = str(
        os.environ.get("ENVIRONMENT") or os.environ.get("ARCHON_ENV") or ""
    ).strip().lower()
    if env_name not in ("production", "prod", "live"):
        return
    pepper = str(os.environ.get("ARCHON_API_KEY_PEPPER") or "").strip()
    if not pepper:
        raise RuntimeError(
            "[Security] ARCHON_API_KEY_PEPPER fehlt in Produktion — "
            "Start abgebrochen (fail-closed). Bitte sicheres Secret setzen und "
            "alle bestehenden API-Keys rotieren."
        )
    if len(pepper) < 16 or pepper.lower() in ("changeme", "secret", "password", "pepper"):
        raise RuntimeError(
            "[Security] ARCHON_API_KEY_PEPPER ist zu kurz oder ein Platzhalter — "
            "Start abgebrochen (fail-closed)."
        )


def _assert_audit_hmac() -> None:
    """GoBD/ISO27001: ohne HMAC-Key ist die Audit-Kette ab Block 1 faelschbar."""
    key = str(os.environ.get("ARCHON_AUDIT_HMAC_KEY") or "").strip()
    if key:
        return
    env_name = str(
        os.environ.get("ENVIRONMENT") or os.environ.get("ARCHON_ENV") or ""
    ).strip().lower()
    prod = env_name in ("production", "prod", "live")
    try:
        from backend.auth_service import auth_service

        prod = prod or bool(auth_service.is_auth_enabled()) or bool(auth_service._must_force_auth())
    except Exception:
        prod = True
    has_hmac_blocks = False
    try:
        from backend.db_paths import resolve_db

        with sqlite3.connect(f"file:{resolve_db('agentic_memory.db')}?mode=ro", uri=True, timeout=3) as conn:
            has_hmac_blocks = (
                conn.execute(
                    "SELECT 1 FROM audit_log WHERE current_hash LIKE 'hmac-sha256:%' LIMIT 1"
                ).fetchone()
                is not None
            )
    except Exception as exc:
        logger.warning("[Audit] HMAC-Block-Pruefung nicht moeglich: %s", exc)
        has_hmac_blocks = False
    if prod or has_hmac_blocks:
        raise RuntimeError(
            "[Audit] ARCHON_AUDIT_HMAC_KEY fehlt — Revisionskette ist manipulierbar (GoBD/ISO27001). "
            "Key aus ENV setzen (z.B. secrets.token_hex(32))."
        )
    logger.warning(
        "[Audit] ARCHON_AUDIT_HMAC_KEY nicht gesetzt — Audit-Kette ist NICHT manipulationssicher (Development)."
    )


def _verify_all_audit_chains() -> Dict[str, Dict[str, Any]]:
    """Zentrale + alle sechs Nebenketten verifizieren (sync, fuer Hook + Loop)."""
    from backend.api_key_manager import api_key_manager as _api_key_chain
    from backend.approval_policy_engine import approval_engine as _approval_chain
    from backend.audit_log import chained_audit_log as _audit_chain
    from backend.email_draft_engine import verify_email_draft_chain
    from backend.execution_receipt_ledger import execution_receipt_ledger
    from backend.gdpr_compliance_engine import verify_gdpr_audit_chain
    from backend.treasury_engine import verify_treasury_chain

    verifiers = (
        ("Zentrale Audit-Kette", _audit_chain.verify_integrity),
        ("Approval-Kette", _approval_chain.verify_audit_integrity),
        ("API-Key-Kette", _api_key_chain.verify_integrity),
        ("Receipt-Kette", execution_receipt_ledger.verify_chain_integrity),
        ("Treasury-Kette", verify_treasury_chain),
        ("Email-Draft-Kette", verify_email_draft_chain),
        ("DSGVO-Audit-Kette", verify_gdpr_audit_chain),
    )
    results: Dict[str, Dict[str, Any]] = {}
    for label, verify_fn in verifiers:
        try:
            res = verify_fn()
            if isinstance(res, dict):
                if "valid" not in res and "chain_valid" in res:
                    res = dict(res)
                    res["valid"] = res["chain_valid"]
                results[label] = res
            else:
                results[label] = {"valid": False, "reason": "Kein Verify-Result."}
        except Exception as exc:
            logger.error("[Integritaet] %s nicht pruefbar (fail-closed): %s", label, exc)
            results[label] = {
                "valid": False,
                "corrupted_id": label,
                "reason": f"Verifikation nicht ausfuehrbar: {type(exc).__name__}: {exc}",
            }
    return results


def _audit_integrity_enforced() -> bool:
    """§2.5: Fail-Fast nur im produktiven Pfad ('Produktion startet nicht')."""
    env_name = str(
        os.environ.get("ENVIRONMENT") or os.environ.get("ARCHON_ENV") or ""
    ).strip().lower()
    if env_name in ("production", "prod", "live"):
        return True
    if str(os.environ.get("ARCHON_AUDIT_INTEGRITY_FAIL_FAST", "") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return True
    try:
        d = _deps()
        force_fn = d.must_force_auth if d is not None else _must_force_auth
        return bool(force_fn())
    except Exception:
        return True


def _assert_audit_integrity() -> None:
    """B-05 (D05/BLOCKER): Fail-Fast bei Manipulation der Audit-Ketten."""
    d = _deps()
    enforced_fn = d.audit_integrity_enforced if d is not None else _audit_integrity_enforced
    verify_fn = d.verify_all_audit_chains if d is not None else _verify_all_audit_chains
    mark_fn = d.mark_audit_compromised if d is not None else _mark_audit_compromised
    if not enforced_fn():
        return
    results = verify_fn()
    broken = {
        label: res
        for label, res in results.items()
        if isinstance(res, dict) and res.get("valid") is False
    }
    if not broken:
        return
    for label, res in broken.items():
        mark_fn(label, res)
    detail = "; ".join(
        f"{label}: {res.get('reason') or res.get('message') or 'unbekannt'}"
        for label, res in broken.items()
    )
    raise RuntimeError(
        f"[Audit] Kettenintegritaet verletzt — Start abgebrochen (fail-closed): {detail}"
    )
