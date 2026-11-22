"""
Kryptographische Passkey / WebAuthn (FIDO2) Verifizierung fuer HITL-Freigaben (M101).
Pro-User-Konfiguration & Signaturpruefung mittels `cryptography`.
"""

from __future__ import annotations
import logging
_archon_exc_logger = logging.getLogger("passkey_hitl")

import base64
import datetime
import hashlib
import json
import os
import secrets
import threading
import time
from typing import Any, Dict, List, Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

CONFIG_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "config"))
PASSKEY_FILE = os.path.join(CONFIG_DIR, "passkey_hitl.json")

_LOCK = threading.Lock()
_CHALLENGES: Dict[str, Dict[str, Any]] = {}
_CHALLENGE_TTL_SECONDS = 300
_PROOF_TOKENS: Dict[str, Dict[str, Any]] = {}
_PROOF_TTL_SECONDS = 120
_HIGH_RISK_CATEGORIES = {"payments", "destructive_actions", "system"}

DEFAULT_CATEGORIES = {
    "payments": True,
    "project_start": True,
    "budget_overrun": True,
    "destructive_actions": True,
    "system": True,
}


def _b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_decode(val: str) -> bytes:
    s = str(val or "").strip()
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _load_store() -> Dict[str, Any]:
    if not os.path.exists(PASSKEY_FILE):
        return {"users": {}}
    try:
        with open(PASSKEY_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("users"), dict):
            return data
    except Exception as _exc:
        _archon_exc_logger.debug("[passkey_hitl] Ignorierte Ausnahme (Z.57): %s", _exc)
    return {"users": {}}


def _save_store(data: Dict[str, Any]) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = f"{PASSKEY_FILE}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, PASSKEY_FILE)


def _default_user_entry() -> Dict[str, Any]:
    return {
        "enabled": False,
        "scope": "all",
        "categories": dict(DEFAULT_CATEGORIES),
        "credentials": [],
    }


def get_user_passkey_config(user_id: str) -> Dict[str, Any]:
    uid = str(user_id or "admin").strip() or "admin"
    with _LOCK:
        store = _load_store()
        raw = store["users"].get(uid) or _default_user_entry()
        creds = [
            {
                "id": c.get("id"),
                "label": c.get("label") or "Passkey",
                "alg": c.get("alg", -7),
                "created_at": c.get("created_at"),
                "last_used_at": c.get("last_used_at"),
            }
            for c in (raw.get("credentials") or [])
            if isinstance(c, dict) and c.get("id")
        ]
        cats = dict(DEFAULT_CATEGORIES)
        if isinstance(raw.get("categories"), dict):
            for k in cats:
                if k in raw["categories"]:
                    cats[k] = bool(raw["categories"][k])
        return {
            "user_id": uid,
            "enabled": bool(raw.get("enabled", False)),
            "scope": "selected" if raw.get("scope") == "selected" else "all",
            "categories": cats,
            "credentials": creds,
            "has_credentials": len(creds) > 0,
        }


def update_user_passkey_config(
    user_id: str,
    *,
    enabled: Optional[bool] = None,
    scope: Optional[str] = None,
    categories: Optional[Dict[str, bool]] = None,
) -> Dict[str, Any]:
    uid = str(user_id or "admin").strip() or "admin"
    with _LOCK:
        store = _load_store()
        entry = store["users"].setdefault(uid, _default_user_entry())
        if enabled is not None:
            entry["enabled"] = bool(enabled)
        if scope in ("all", "selected"):
            entry["scope"] = scope
        if isinstance(categories, dict):
            cats = entry.setdefault("categories", dict(DEFAULT_CATEGORIES))
            for k in DEFAULT_CATEGORIES:
                if k in categories:
                    cats[k] = bool(categories[k])
        _save_store(store)
    return get_user_passkey_config(uid)


def is_passkey_required(user_id: str, category: str = "all") -> bool:
    cfg = get_user_passkey_config(user_id)
    if not cfg["enabled"] or not cfg["has_credentials"]:
        return False
    if cfg["scope"] == "all":
        return True
    return bool(cfg["categories"].get(category, False))


def _cleanup_challenges() -> None:
    now = time.time()
    expired = [k for k, v in _CHALLENGES.items() if now - v.get("created_ts", 0) > _CHALLENGE_TTL_SECONDS]
    for k in expired:
        _CHALLENGES.pop(k, None)
    expired_proofs = [k for k, v in _PROOF_TOKENS.items() if now - v.get("created_ts", 0) > _PROOF_TTL_SECONDS]
    for k in expired_proofs:
        _PROOF_TOKENS.pop(k, None)


def consume_hitl_proof_token(token: Optional[str], user_id: str, category: str = "all") -> bool:
    """Prueft und verbraucht ein serverseitig ausgestelltes Einmal-Passkey-Proof-Token."""
    raw = str(token or "").strip()
    if not raw:
        return False
    uid = str(user_id or "admin").strip() or "admin"
    with _LOCK:
        _cleanup_challenges()
        entry = _PROOF_TOKENS.pop(raw, None)
    if not entry:
        return False
    if entry.get("user_id") != uid:
        return False
    token_cat = str(entry.get("category") or "all")
    if category != "all" and token_cat not in ("all", category):
        return False
    if category in _HIGH_RISK_CATEGORIES and not entry.get("uv_verified"):
        return False
    return True


def create_registration_options(user_id: str, username: str, rp_id: str) -> Dict[str, Any]:
    uid = str(user_id or "admin").strip() or "admin"
    challenge_bytes = secrets.token_bytes(32)
    challenge_b64 = _b64u_encode(challenge_bytes)
    with _LOCK:
        _cleanup_challenges()
        _CHALLENGES[challenge_b64] = {
            "kind": "register",
            "user_id": uid,
            "rp_id": rp_id,
            "created_ts": time.time(),
        }
        store = _load_store()
        existing = (store["users"].get(uid) or {}).get("credentials") or []
        exclude = [{"type": "public-key", "id": c["id"]} for c in existing if c.get("id")]

    return {
        "challenge": challenge_b64,
        "rp": {"name": "Archon OS", "id": rp_id},
        "user": {
            "id": _b64u_encode(uid.encode("utf-8")),
            "name": username or uid,
            "displayName": username or uid,
        },
        "pubKeyCredParams": [
            {"type": "public-key", "alg": -7},    # ES256
            {"type": "public-key", "alg": -257},  # RS256
        ],
        "timeout": 60000,
        "attestation": "none",
        "excludeCredentials": exclude,
        "authenticatorSelection": {
            "residentKey": "preferred",
            "userVerification": "preferred",
        },
    }


def verify_and_store_registration(
    *,
    user_id: str,
    credential_id: str,
    client_data_b64: str,
    public_key_spki_b64: str,
    alg: int = -7,
    label: str = "Passkey",
    expected_origin: Optional[str] = None,
    authenticator_data_b64: Optional[str] = None,
) -> Dict[str, Any]:
    uid = str(user_id or "admin").strip() or "admin"
    client_raw = _b64u_decode(client_data_b64)
    client_data = json.loads(client_raw.decode("utf-8"))
    if client_data.get("type") != "webauthn.create":
        raise ValueError("Ungueltiger clientData.type fuer Registrierung.")

    challenge_b64 = client_data.get("challenge") or ""
    with _LOCK:
        _cleanup_challenges()
        ch = _CHALLENGES.pop(challenge_b64, None)
    if not ch or ch.get("kind") != "register" or ch.get("user_id") != uid:
        raise ValueError("Registrierungs-Challenge abgelaufen oder ungueltig.")
    if expected_origin and client_data.get("origin") != expected_origin:
        raise ValueError("Origin stimmt nicht ueberein.")

    if authenticator_data_b64:
        auth_data = _b64u_decode(authenticator_data_b64)
        if len(auth_data) < 37:
            raise ValueError("Ungueltige authenticatorData bei Registrierung.")
        rp_id_hash = auth_data[:32]
        expected_rp_hash = hashlib.sha256(ch["rp_id"].encode("utf-8")).digest()
        if rp_id_hash != expected_rp_hash:
            raise ValueError("rpIdHash stimmt bei Registrierung nicht ueberein.")
        if not (auth_data[32] & 0x01):
            raise ValueError("User-Presence-Flag fehlt bei Registrierung.")

    spki_bytes = _b64u_decode(public_key_spki_b64)
    # Validieren, dass es ein gueltiger oeffentlicher Schluessel ist
    serialization.load_der_public_key(spki_bytes)

    now_iso = datetime.datetime.now().isoformat()
    with _LOCK:
        store = _load_store()
        entry = store["users"].setdefault(uid, _default_user_entry())
        creds = [c for c in (entry.get("credentials") or []) if c.get("id") != credential_id]
        creds.append({
            "id": credential_id,
            "label": str(label or "Passkey")[:64],
            "public_key_spki_b64": public_key_spki_b64,
            "alg": int(alg),
            "sign_count": 0,
            "created_at": now_iso,
            "last_used_at": None,
        })
        entry["credentials"] = creds
        _save_store(store)
    return get_user_passkey_config(uid)


def delete_user_credential(user_id: str, credential_id: str) -> Dict[str, Any]:
    uid = str(user_id or "admin").strip() or "admin"
    with _LOCK:
        store = _load_store()
        entry = store["users"].setdefault(uid, _default_user_entry())
        entry["credentials"] = [c for c in (entry.get("credentials") or []) if c.get("id") != credential_id]
        _save_store(store)
    return get_user_passkey_config(uid)


def create_hitl_assertion_options(
    user_id: str,
    rp_id: str,
    category: str = "all",
    action_label: str = "",
) -> Dict[str, Any]:
    uid = str(user_id or "admin").strip() or "admin"
    cfg = get_user_passkey_config(uid)
    allow = [{"type": "public-key", "id": c["id"]} for c in cfg["credentials"]]
    if not allow:
        raise ValueError("Kein Passkey fuer diesen Benutzer registriert.")
    challenge_b64 = _b64u_encode(secrets.token_bytes(32))
    with _LOCK:
        _cleanup_challenges()
        _CHALLENGES[challenge_b64] = {
            "kind": "hitl_assert",
            "user_id": uid,
            "rp_id": rp_id,
            "category": category,
            "action_label": action_label,
            "created_ts": time.time(),
        }
    return {
        "challenge": challenge_b64,
        "rpId": rp_id,
        "timeout": 60000,
        "userVerification": "required" if (category in _HIGH_RISK_CATEGORIES or category == "all") else "preferred",
        "allowCredentials": allow,
    }


def verify_hitl_assertion(
    *,
    user_id: str,
    credential_id: str,
    client_data_b64: str,
    authenticator_data_b64: str,
    signature_b64: str,
    expected_origin: Optional[str] = None,
    require_uv: Optional[bool] = None,
) -> Dict[str, Any]:
    uid = str(user_id or "admin").strip() or "admin"
    client_raw = _b64u_decode(client_data_b64)
    client_data = json.loads(client_raw.decode("utf-8"))
    if client_data.get("type") != "webauthn.get":
        raise ValueError("Ungueltiger clientData.type fuer Verifizierung.")

    challenge_b64 = client_data.get("challenge") or ""
    with _LOCK:
        _cleanup_challenges()
        ch = _CHALLENGES.pop(challenge_b64, None)
    if not ch or ch.get("kind") != "hitl_assert" or ch.get("user_id") != uid:
        raise ValueError("Verifizierungs-Challenge abgelaufen oder ungueltig.")
    if expected_origin and client_data.get("origin") != expected_origin:
        raise ValueError("Origin stimmt nicht ueberein.")

    auth_data = _b64u_decode(authenticator_data_b64)
    if len(auth_data) < 37:
        raise ValueError("Ungueltige authenticatorData.")
    rp_id_hash = auth_data[:32]
    expected_rp_hash = hashlib.sha256(ch["rp_id"].encode("utf-8")).digest()
    if rp_id_hash != expected_rp_hash:
        raise ValueError("rpIdHash stimmt nicht ueberein.")
    flags = auth_data[32]
    if not (flags & 0x01):  # User Present (UP)
        raise ValueError("User-Presence-Flag fehlt.")
    cat = ch.get("category") or "all"
    must_uv = (cat in _HIGH_RISK_CATEGORIES or cat == "all") if require_uv is None else bool(require_uv)
    uv_ok = bool(flags & 0x04)  # User Verified (UV: Biometrie/PIN)
    if must_uv and not uv_ok:
        raise ValueError("User-Verification-Flag (Biometrie/PIN) fuer diese Risikokategorie erforderlich.")

    sign_count = int.from_bytes(auth_data[33:37], "big")
    sig_bytes = _b64u_decode(signature_b64)
    signed_payload = auth_data + hashlib.sha256(client_raw).digest()

    with _LOCK:
        store = _load_store()
        entry = store["users"].get(uid) or {}
        cred = next((c for c in (entry.get("credentials") or []) if c.get("id") == credential_id), None)
        if not cred:
            raise ValueError("Unbekannter Passkey.")
        pub = serialization.load_der_public_key(_b64u_decode(cred["public_key_spki_b64"]))

        if isinstance(pub, ec.EllipticCurvePublicKey):
            pub.verify(sig_bytes, signed_payload, ec.ECDSA(hashes.SHA256()))
        elif isinstance(pub, rsa.RSAPublicKey):
            pub.verify(sig_bytes, signed_payload, padding.PKCS1v15(), hashes.SHA256())
        else:
            raise ValueError("Nicht unterstuetzter Public-Key-Typ.")

        if cred.get("sign_count", 0) > 0 and sign_count <= cred["sign_count"]:
            raise ValueError("Moeglicher Replay/Klon-Angriff (signCount).")
        cred["sign_count"] = max(sign_count, cred.get("sign_count", 0))
        cred["last_used_at"] = datetime.datetime.now().isoformat()
        _save_store(store)

        proof_token = secrets.token_urlsafe(32)
        _cleanup_challenges()
        _PROOF_TOKENS[proof_token] = {
            "user_id": uid,
            "credential_id": credential_id,
            "category": cat,
            "uv_verified": uv_ok,
            "created_ts": time.time(),
        }

    return {
        "verified": True,
        "uv_verified": uv_ok,
        "proof_token": proof_token,
        "user_id": uid,
        "credential_id": credential_id,
        "category": cat,
        "action_label": ch.get("action_label") or "",
        "verified_at": datetime.datetime.now().isoformat(),
    }
