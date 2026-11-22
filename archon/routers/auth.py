"""
Auth & Multi-User Router fuer Archon OS.
Verwaltet /api/auth/* Endpunkte (Status, Toggle, Login/Logout, Benutzerverwaltung, Passwort-Aenderung)
sowie rollenbasierte Autorisierungshelfer (get_current_user_from_request, require_admin).
Extrahiert aus main.py zur Modularisierung.
"""

from __future__ import annotations

import os
import sys
import json
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse

from backend.auth_service import auth_service
from archon.core.config import config
from archon.core.paths import SETTINGS_FILE
from archon.core.runtime import atomic_write_json, logger

router = APIRouter(tags=["auth"])

_DEPS: Dict[str, Any] = {}


def configure(**deps: Any) -> None:
    """Registriert injizierte Helfer aus main.py."""
    _DEPS.update(deps)


def _request_has_service_token(request: Request) -> bool:
    checker = _DEPS.get("_request_has_service_token")
    if checker:
        return checker(request)
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "_request_has_service_token"):
        return main_mod._request_has_service_token(request)
    provided = request.headers.get("x-archon-service-token", "")
    expected = config.archon_service_token
    if not expected or not provided:
        return False
    import hmac
    return hmac.compare_digest(provided, expected)


def _load_json_helper(path: str, default: Any) -> Any:
    fn = _DEPS.get("_load_json")
    if fn:
        return fn(path, default)
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "_load_json"):
        return main_mod._load_json(path, default)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json_helper(path: str, data: Any) -> None:
    fn = _DEPS.get("_save_json")
    if fn:
        return fn(path, data)
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "_save_json"):
        return main_mod._save_json(path, data)
    atomic_write_json(path, data)


def get_current_user_from_request(request: Request) -> dict:
    """Ermittelt die Identitaet aus der Session.

    Kandidaten in dieser Reihenfolge: ``Authorization``-Header,
    ``X-Archon-Session``, ``archon_session``-Cookie.
    """
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "get_current_user_from_request"):
        fn = getattr(main_mod, "get_current_user_from_request")
        if fn is not get_current_user_from_request:
            return fn(request)

    state_obj = getattr(request, "state", None)
    state_user = getattr(state_obj, "user", None) if state_obj is not None else None
    if isinstance(state_user, dict) and state_user.get("role"):
        return state_user

    is_enabled = auth_service.is_auth_enabled()
    if request is None:
        if not is_enabled:
            return auth_service.get_fallback_admin()
        raise HTTPException(status_code=401, detail="Nicht authentifiziert.")

    candidates: List[str] = []
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        candidates.append(auth_header[7:].strip())
    header_session = request.headers.get("x-archon-session", "").strip()
    if header_session:
        candidates.append(header_session)
    cookie_session = (request.cookies.get("archon_session", "") or "").strip()
    if cookie_session:
        candidates.append(cookie_session)

    for candidate in candidates:
        if not candidate:
            continue
        try:
            user = auth_service.verify_session(candidate)
        except Exception:
            user = None
        if user:
            user["auth_enabled"] = is_enabled
            return user

    # Multi-User-Modus: ohne gueltige Session gibt es KEINE Admin-Rechte.
    if is_enabled:
        if _request_has_service_token(request):
            return {
                "id": "usr_service",
                "username": "service",
                "display_name": "Interner Dienst",
                "role": "admin",
                "permissions": ["service"],
                "is_service": True,
                "auth_enabled": True,
            }
        return {
            "id": "usr_anonymous",
            "username": "anonymous",
            "display_name": "Nicht angemeldet",
            "role": "anonymous",
            "permissions": [],
            "is_fallback": False,
            "auth_enabled": True,
        }

    fb = auth_service.get_fallback_admin()
    fb["auth_enabled"] = is_enabled
    return fb


def require_admin(request: Request) -> Dict[str, Any]:
    """Rollenzaun fuer destruktive Admin-Routen."""
    user = get_current_user_from_request(request)
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Nur Administratoren duerfen diese Aktion ausfuehren "
                   f"(erkannte Rolle: {user.get('role') or 'unbekannt'}).",
        )
    return user


def require_operator_or_admin(request: Request) -> Dict[str, Any]:
    """Rollenzaun fuer schreibende Fach-Routen: sperrt 'viewer' und 'anonymous'."""
    user = get_current_user_from_request(request)
    if user.get("role") not in ("admin", "operator"):
        raise HTTPException(
            status_code=403,
            detail="Keine Schreibberechtigung fuer diese Aktion "
                   f"(erkannte Rolle: {user.get('role') or 'unbekannt'}).",
        )
    return user


@router.get("/api/auth/status")
def api_auth_status():
    return {
        "status": "success",
        "auth_enabled": auth_service.is_auth_enabled()
    }


@router.post("/api/auth/toggle")
def api_auth_toggle(request: Request, payload: dict = Body(...)):
    curr = get_current_user_from_request(request)
    if curr.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Nur Administratoren dürfen den Authentifizierungsmodus ändern.")
    enabled = bool(payload.get("enabled", False))
    s = _load_json_helper(SETTINGS_FILE, {})
    if "auth" not in s or not isinstance(s["auth"], dict):
        s["auth"] = {}
    s["auth"]["enabled"] = enabled
    s["auth"]["mode"] = "multi_user" if enabled else "single_user"
    _save_json_helper(SETTINGS_FILE, s)

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    alt_paths = [
        os.path.join(repo_root, "agent_workspace", "settings.json"),
        "/app/agent_workspace/settings.json",
        os.path.join(repo_root, "settings.json"),
        "/app/settings.json",
    ]
    for alt in alt_paths:
        try:
            if os.path.exists(alt) and os.path.abspath(alt) != os.path.abspath(SETTINGS_FILE):
                alt_s = _load_json_helper(alt, {})
                if "auth" not in alt_s or not isinstance(alt_s["auth"], dict):
                    alt_s["auth"] = {}
                alt_s["auth"]["enabled"] = enabled
                alt_s["auth"]["mode"] = s["auth"]["mode"]
                _save_json_helper(alt, alt_s)
        except Exception as exc:
            logger.warning(f"[Auth] Spiegel-Sync fuer {alt} fehlgeschlagen: {exc}")
    return {
        "status": "success",
        "auth_enabled": enabled,
        "mode": s["auth"]["mode"],
        "message": "Multi-User-Modus aktiviert." if enabled else "Einzelplatz-Modus aktiviert (keine Anmeldung erforderlich)."
    }


@router.get("/api/auth/me")
def api_auth_me(request: Request):
    user = get_current_user_from_request(request)
    return {
        "status": "success",
        "user": user,
        "auth_enabled": auth_service.is_auth_enabled()
    }


@router.post("/api/auth/login")
def api_auth_login(request: Request, payload: dict = Body(...)):
    username = payload.get("username", "")
    password = payload.get("password", "")
    client_ip = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")
    try:
        session = auth_service.authenticate(username, password, ip_address=client_ip, user_agent=user_agent)
    except PermissionError as lock_err:
        raise HTTPException(status_code=429, detail=str(lock_err)) from lock_err
    if not session:
        raise HTTPException(status_code=401, detail="Ungültiger Benutzername oder falsches Passwort.")
    res = JSONResponse(content={"status": "success", **session})
    is_https = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() == "https"
    )
    res.set_cookie(
        key="archon_session",
        value=session["token"],
        max_age=86400 * 30,
        httponly=True,
        samesite="lax",
        secure=is_https,
    )
    return res


@router.post("/api/auth/logout")
def api_auth_logout(request: Request):
    token = request.cookies.get("archon_session") or request.headers.get("x-archon-session", "")
    if not token:
        auth_hdr = request.headers.get("authorization", "")
        if auth_hdr.lower().startswith("bearer "):
            token = auth_hdr[7:].strip()
    if token:
        auth_service.logout(token)
    res = JSONResponse(content={"status": "success", "message": "Erfolgreich abgemeldet."})
    res.delete_cookie(key="archon_session")
    return res


@router.get("/api/auth/users")
def api_auth_list_users(request: Request):
    curr = get_current_user_from_request(request)
    if curr.get("role") not in ("admin", "operator"):
        return {"status": "success", "users": [curr]}
    return {"status": "success", "users": auth_service.list_users()}


@router.post("/api/auth/users")
def api_auth_create_user(request: Request, payload: dict = Body(...)):
    curr = get_current_user_from_request(request)
    if curr.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Nur Administratoren dürfen neue Benutzer anlegen.")
    try:
        new_u = auth_service.create_user(
            username=payload.get("username"),
            password=payload.get("password"),
            role=payload.get("role", "operator"),
            display_name=payload.get("display_name", ""),
            email=payload.get("email", "")
        )
        return {"status": "success", "user": new_u}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/api/auth/users/{user_id}")
def api_auth_update_user(user_id: str, request: Request, payload: dict = Body(...)):
    curr = get_current_user_from_request(request)
    if curr.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Nur Administratoren dürfen Benutzerrollen anpassen.")
    try:
        updated = auth_service.update_user(
            user_id=user_id,
            role=payload.get("role"),
            display_name=payload.get("display_name"),
            email=payload.get("email"),
            is_active=payload.get("is_active")
        )
        return {"status": "success", "user": updated}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/auth/change-password")
def api_auth_change_password(request: Request, payload: dict = Body(...)):
    """Passwort ändern: eigener Account (mit aktuellem Passwort) oder als Admin für andere."""
    curr = get_current_user_from_request(request)
    if not curr or curr.get("id") in (None, "", "usr_anonymous"):
        raise HTTPException(status_code=401, detail="Nicht angemeldet.")

    target_id = str(payload.get("user_id") or curr.get("id")).strip()
    new_pw = str(payload.get("new_password") or "")
    if len(new_pw) < 8:
        raise HTTPException(status_code=400, detail="Das neue Passwort muss mindestens 8 Zeichen haben.")

    is_self = (target_id == curr.get("id"))
    if is_self:
        current_pw = str(payload.get("current_password") or "")
        if not auth_service.verify_password(curr.get("username", ""), current_pw):
            raise HTTPException(status_code=400, detail="Das aktuelle Passwort ist falsch.")
    elif curr.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Nur Administratoren dürfen fremde Passwörter ändern.")

    try:
        ok = auth_service.change_password(target_id, new_pw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden.")

    return {
        "status": "success",
        "message": "Passwort geändert.",
        "relogin_required": is_self,
    }


@router.delete("/api/auth/users/{user_id}")
def api_auth_delete_user(user_id: str, request: Request):
    curr = get_current_user_from_request(request)
    if curr.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Nur Administratoren dürfen Benutzer löschen.")
    try:
        auth_service.delete_user(user_id)
        return {"status": "success", "message": "Benutzer gelöscht."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _resolve_target_passkey_user(request: Request, explicit_user_id: Optional[str] = None) -> tuple[str, str]:
    curr = get_current_user_from_request(request)
    if auth_service.is_auth_enabled() and curr.get("role") == "anonymous":
        raise HTTPException(status_code=401, detail="Authentifizierung für Passkey-Verwaltung erforderlich.")
    curr_id = str(curr.get("id") or curr.get("username") or "admin")
    curr_name = str(curr.get("username") or curr_id)
    target_id = str(explicit_user_id or curr_id).strip() or curr_id
    if target_id != curr_id and curr.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Nur Administratoren dürfen Passkeys anderer Benutzer verwalten.")
    return target_id, curr_name


def _request_rp_id_and_origin(request: Request) -> tuple[str, Optional[str]]:
    raw_host = (request.headers.get("host") or "localhost").strip() or "localhost"
    rp_id = raw_host.split(":")[0].strip() or "localhost"
    scheme = request.url.scheme or "http"
    server_origin = f"{scheme}://{raw_host}"
    hdr_origin = request.headers.get("origin")
    if hdr_origin and hdr_origin != server_origin:
        # Nur explizit vertrauenswuerdige Origin oder Server-Origin akzeptieren
        return rp_id, server_origin
    return rp_id, (hdr_origin or server_origin)


@router.get("/api/auth/passkey/config")
def api_get_passkey_config(request: Request, user_id: Optional[str] = None):
    from backend.passkey_hitl import get_user_passkey_config
    target_id, _ = _resolve_target_passkey_user(request, user_id)
    return {"status": "success", **get_user_passkey_config(target_id)}


@router.post("/api/auth/passkey/config")
def api_update_passkey_config(request: Request, payload: dict = Body(...)):
    from backend.passkey_hitl import consume_hitl_proof_token, is_passkey_required, update_user_passkey_config
    target_id, _ = _resolve_target_passkey_user(request, payload.get("user_id"))
    if payload.get("enabled") is False and is_passkey_required(target_id, "system"):
        proof = str(payload.get("passkey_proof_token") or request.headers.get("x-passkey-proof") or "").strip()
        if not proof or not consume_hitl_proof_token(proof, target_id, "system"):
            raise HTTPException(status_code=403, detail="Passkey-Verifizierung erforderlich, um Passkey-HITL zu deaktivieren.")
    cfg = update_user_passkey_config(
        target_id,
        enabled=payload.get("enabled"),
        scope=payload.get("scope"),
        categories=payload.get("categories"),
    )
    return {"status": "success", **cfg}


@router.post("/api/auth/passkey/register/options")
def api_passkey_register_options(request: Request, payload: dict = Body(default={})):
    from backend.passkey_hitl import create_registration_options
    target_id, curr_name = _resolve_target_passkey_user(request, payload.get("user_id"))
    rp_id, _ = _request_rp_id_and_origin(request)
    username = str(payload.get("username") or curr_name or target_id)
    opts = create_registration_options(target_id, username, rp_id)
    return {"status": "success", "options": opts}


@router.post("/api/auth/passkey/register/verify")
def api_passkey_register_verify(request: Request, payload: dict = Body(...)):
    from backend.passkey_hitl import (
        consume_hitl_proof_token,
        get_user_passkey_config,
        is_passkey_required,
        verify_and_store_registration,
    )
    target_id, _ = _resolve_target_passkey_user(request, payload.get("user_id"))
    existing_cfg = get_user_passkey_config(target_id)
    if (existing_cfg.get("credentials") or []) and is_passkey_required(target_id, "system"):
        proof = str(payload.get("passkey_proof_token") or request.headers.get("x-passkey-proof") or "").strip()
        if not proof or not consume_hitl_proof_token(proof, target_id, "system"):
            raise HTTPException(
                status_code=403,
                detail="Passkey-Verifizierung erforderlich, um einen weiteren Passkey zu registrieren.",
            )
    _, origin = _request_rp_id_and_origin(request)
    try:
        cfg = verify_and_store_registration(
            user_id=target_id,
            credential_id=str(payload.get("id") or ""),
            client_data_b64=str(payload.get("clientDataJSON") or ""),
            public_key_spki_b64=str(payload.get("publicKeySpki") or ""),
            alg=int(payload.get("alg", -7)),
            label=str(payload.get("label") or "Passkey"),
            expected_origin=origin,
            authenticator_data_b64=str(payload.get("authenticatorData") or "") or None,
        )
        return {"status": "success", **cfg}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/api/auth/passkey/credentials/{cred_id}")
def api_passkey_delete_credential(cred_id: str, request: Request, user_id: Optional[str] = None):
    from backend.passkey_hitl import consume_hitl_proof_token, delete_user_credential, is_passkey_required
    target_id, _ = _resolve_target_passkey_user(request, user_id)
    if is_passkey_required(target_id, "system"):
        proof = str(request.headers.get("x-passkey-proof") or request.query_params.get("passkey_proof_token") or "").strip()
        if not proof or not consume_hitl_proof_token(proof, target_id, "system"):
            raise HTTPException(status_code=403, detail="Passkey-Verifizierung erforderlich, um Passkey-Zugangsdaten zu loeschen.")
    cfg = delete_user_credential(target_id, cred_id)
    return {"status": "success", **cfg}


@router.post("/api/auth/passkey/hitl/options")
def api_passkey_hitl_options(request: Request, payload: dict = Body(default={})):
    from backend.passkey_hitl import create_hitl_assertion_options, is_passkey_required
    target_id, _ = _resolve_target_passkey_user(request, payload.get("user_id"))
    category = str(payload.get("category") or "all")
    if not is_passkey_required(target_id, category) and not payload.get("force"):
        return {"status": "success", "required": False}
    rp_id, _ = _request_rp_id_and_origin(request)
    try:
        opts = create_hitl_assertion_options(
            target_id,
            rp_id,
            category=category,
            action_label=str(payload.get("action_label") or ""),
        )
        return {"status": "success", "required": True, "options": opts}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/auth/passkey/hitl/verify")
def api_passkey_hitl_verify(request: Request, payload: dict = Body(...)):
    from backend.passkey_hitl import verify_hitl_assertion
    target_id, _ = _resolve_target_passkey_user(request, payload.get("user_id"))
    _, origin = _request_rp_id_and_origin(request)
    try:
        proof = verify_hitl_assertion(
            user_id=target_id,
            credential_id=str(payload.get("id") or ""),
            client_data_b64=str(payload.get("clientDataJSON") or ""),
            authenticator_data_b64=str(payload.get("authenticatorData") or ""),
            signature_b64=str(payload.get("signature") or ""),
            expected_origin=origin,
        )
        return {"status": "success", "proof": proof}
    except Exception as exc:
        raise HTTPException(status_code=403, detail=str(exc))
