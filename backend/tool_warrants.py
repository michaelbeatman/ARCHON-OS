# -*- coding: utf-8 -*-
"""
backend/tool_warrants.py
========================
Meilenstein 90: Signierte, ablaufende Tool-Warrants (hermes-tenuo-Pattern).

Erstellt kryptografisch signierte (HMAC-SHA256), zeitlich begrenzte
Berechtigungs-Warrants mit Parameter-Constraints pro Session, Cron-Job
oder delegiertem Subagenten.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import posixpath
import secrets
import time
from typing import Any, Dict, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_KEY_FILE = os.path.join(WORKSPACE_DIR, "data", "warrant_hmac.key")


def _get_warrant_secret(key_file: Optional[str] = None) -> str:
    env_sec = (os.environ.get("ARCHON_WARRANT_SECRET") or "").strip()
    if env_sec:
        return env_sec
    path = key_file or DEFAULT_KEY_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            val = f.read().strip()
            if len(val) >= 32:
                return val
    generated = secrets.token_hex(32)
    with open(path, "w", encoding="utf-8") as f:
        f.write(generated)
    return generated


def _sign_payload(payload: Dict[str, Any], secret: str) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def issue_warrant(
    session_id: str,
    allowed_tools: List[str],
    constraints: Optional[Dict[str, Any]] = None,
    ttl_seconds: int = 900,
    secret: Optional[str] = None,
) -> Dict[str, Any]:
    now = time.time()
    payload = {
        "warrant_id": f"war-{secrets.token_hex(6)}",
        "session_id": session_id,
        "allowed_tools": sorted(set(allowed_tools)),
        "constraints": constraints or {},
        "issued_at": round(now, 3),
        "expires_at": round(now + max(1, int(ttl_seconds)), 3),
    }
    sig = _sign_payload(payload, secret or _get_warrant_secret())
    return {"payload": payload, "signature": sig}


def verify_warrant_for_call(
    warrant: Dict[str, Any],
    session_id: str,
    tool_name: str,
    args: Optional[Dict[str, Any]] = None,
    secret: Optional[str] = None,
    now_ts: Optional[float] = None,
) -> Dict[str, Any]:
    if not isinstance(warrant, dict) or "payload" not in warrant or "signature" not in warrant:
        return {"allowed": False, "reason": "Ungueltiges Warrant-Format."}

    payload = warrant["payload"]
    expected_sig = _sign_payload(payload, secret or _get_warrant_secret())
    if not hmac.compare_digest(str(warrant["signature"]), expected_sig):
        return {"allowed": False, "reason": "Warrant-Signatur ungueltig (Manipulation erkannt)."}

    now = now_ts if now_ts is not None else time.time()
    if float(payload.get("expires_at", 0)) <= now:
        return {"allowed": False, "reason": "Warrant abgelaufen."}

    if payload.get("session_id") != session_id:
        return {"allowed": False, "reason": "Warrant gehoert zu einer anderen Session."}

    allowed_tools = set(payload.get("allowed_tools") or [])
    if "*" not in allowed_tools and tool_name not in allowed_tools:
        return {"allowed": False, "reason": f"Tool '{tool_name}' nicht im Warrant freigegeben."}

    constraints = payload.get("constraints") or {}
    call_args = args or {}
    if "max_amount" in constraints and "amount" in call_args:
        try:
            amt = float(call_args["amount"])
            max_amt = float(constraints["max_amount"])
        except (TypeError, ValueError):
            return {"allowed": False, "reason": "Ungueltiger Betrag im Tool-Aufruf."}
        if not math.isfinite(amt) or not math.isfinite(max_amt) or amt < 0:
            return {"allowed": False, "reason": "Nicht-finiter oder negativer Betrag im Warrant-Aufruf abgelehnt."}
        if amt > max_amt:
            return {"allowed": False, "reason": f"Betrag {amt} ueberschreitet Warrant-Limit {max_amt}."}

    if "allowed_path_prefixes" in constraints and "path" in call_args:
        raw_p = str(call_args["path"]).replace("\\", "/").strip()
        norm_p = posixpath.normpath(raw_p).lstrip("./")
        if norm_p == ".." or norm_p.startswith("../") or "/../" in f"/{norm_p}/":
            return {"allowed": False, "reason": f"Pfad-Traversal '{raw_p}' im Warrant abgelehnt."}
        prefs = [posixpath.normpath(str(p).replace("\\", "/")).lstrip("./") for p in constraints["allowed_path_prefixes"]]
        if not any(norm_p == pr or norm_p.startswith(pr.rstrip("/") + "/") or norm_p.startswith(pr) for pr in prefs if pr):
            return {"allowed": False, "reason": f"Pfad '{norm_p}' ausserhalb der Warrant-Prefixes."}

    return {"allowed": True, "warrant_id": payload.get("warrant_id"), "tool": tool_name}
