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

# D04/MED: SSOT für alle Pfad-/Betrags-Aliase. delegation_isolation importiert
# diese Tupel — es gibt keine zweite, kürzere Liste mehr.
PATH_ARG_KEYS = (
    "path", "file_path", "filepath", "file", "target_path", "filename",
    "notebook_path", "source_path", "destination_path", "workspace",
    "uri", "target", "src", "dst", "image_path", "url",
    "input_path", "output_path", "output_dir", "input_dir", "media_path",
    "source_dir", "target_dir", "workdir", "cwd",
)
AMOUNT_ARG_KEYS = ("amount", "value", "total", "price", "betrag")
# Tools, bei denen eine max_amount-Constraint einen Betrag erzwingt. Ein
# reiner Datei-Tool-Call mit Pfad braucht keinen Betrag, ein pay-Call schon.
_AMOUNT_TOOL_MARKERS = (
    "pay", "invoice", "transfer", "purchase", "order", "buy", "refund",
    "withdraw", "charge", "checkout", "transaction", "payment", "spend",
)


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
    # Secret-Datei atomar und mit 600 anlegen (vorher open("w") -> default
    # 644, lokaler Key-Diebstall ermoeglichte Warrant-Faelschung).
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(fd, generated.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
    except FileExistsError:
        with open(path, "r", encoding="utf-8") as f:
            existing = f.read().strip()
        if len(existing) >= 32:
            return existing
        raise RuntimeError(f"Warrant-Key ungueltig: {path}")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return generated


def _sign_payload(payload: Dict[str, Any], secret: str) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


# Serverseitiges Warrant-Registry: der Client soll sein Warrant NICHT self-
# an den Tool-Endpunkt liefern können. Ausgestellte Warrants werden hier
# vorgehalten und vom Chokepoint gegen die Session aufgelöst.
_WARRANT_REGISTRY: Dict[str, list] = {}
_REGISTRY_LOCK = __import__("threading").RLock()


def register_warrant(warrant: Dict[str, Any]) -> None:
    payload = warrant.get("payload") if isinstance(warrant, dict) else None
    if not isinstance(payload, dict):
        return
    sid = str(payload.get("session_id") or "").strip()
    if not sid:
        return
    with _REGISTRY_LOCK:
        _WARRANT_REGISTRY.setdefault(sid, []).append(warrant)
        # Alte/abgelaufene Einträge begrenzen (Memory-Hygiene)
        _WARRANT_REGISTRY[sid] = _WARRANT_REGISTRY[sid][-25:]


def get_warrant_for_session(session_id: str, tool_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Liefert das neueste gültige Warrant für die Session (serverseitig)."""
    sid = str(session_id or "").strip()
    if not sid:
        return None
    with _REGISTRY_LOCK:
        entries = list(reversed(_WARRANT_REGISTRY.get(sid, [])))
    for w in entries:
        payload = w.get("payload") if isinstance(w, dict) else None
        if not isinstance(payload, dict):
            continue
        if float(payload.get("expires_at") or 0) <= time.time():
            continue
        if tool_name:
            allowed = set(payload.get("allowed_tools") or [])
            if "*" not in allowed and str(tool_name) not in allowed:
                continue
        # Registry-Eintraege muessen zusaetzlich kryptografisch verifiziert
        # werden. Vorher genuegten Ablauf + Tool-Name — manipulierte Registry
        # oder gefaelschte Eintraege wurden bedingungslos vertraut.
        try:
            v = verify_warrant_for_call(w, sid, str(tool_name or "*"))
            if not v.get("allowed"):
                continue
        except Exception:
            continue
        return w
    return None


def latest_warrant_payload_for_session(session_id: str) -> Optional[Dict[str, Any]]:
    """D11/W3-C: gueltiges Parent-Warrant lesen (ohne Tool-Filter).

    ``get_warrant_for_session()`` verlangt einen konkreten Tool-Namen und
    wuerde ein Parent-Warrant mit ``allowed_tools``-Whitelist hier ablehnen.
    Diese Variante prueft nur Signatur + Ablauf + Session-Bindung und liefert
    das signierte Payload zur kontrollierten Vererbung an die Kind-Session.
    """
    sid = str(session_id or "").strip()
    if not sid:
        return None
    with _REGISTRY_LOCK:
        entries = list(reversed(_WARRANT_REGISTRY.get(sid, [])))
    for w in entries:
        payload = w.get("payload") if isinstance(w, dict) else None
        if not isinstance(payload, dict):
            continue
        if float(payload.get("expires_at") or 0) <= time.time():
            continue
        try:
            if not hmac.compare_digest(
                str(w.get("signature") or ""), _sign_payload(payload, _get_warrant_secret())
            ):
                continue
        except Exception:
            continue
        return dict(payload)
    return None


def inherit_warrant_for_session(
    source_session_id: str,
    target_session_id: str,
    *,
    allowed_tools: Optional[List[str]] = None,
    constraints: Optional[Dict[str, Any]] = None,
    ttl_seconds: int = 900,
) -> str:
    """D11/W3-C: Warrant des Parents an die Kind-Session vererben.

    Gibt die ``warrant_id`` des neu ausgestellten, an die Kind-Session
    gebundenen Warrants zurueck (wird signiert in der Delegationsuebergabe
    mitgefuehrt). Ohne Parent-Warrant bleibt die ID leer — das Kind erhaelt
    keine stillen Zusatzrechte.
    """
    source = latest_warrant_payload_for_session(source_session_id)
    if not source:
        return ""
    tools = list(allowed_tools or source.get("allowed_tools") or [])
    if not tools:
        return ""
    inherited = issue_warrant(
        str(target_session_id),
        tools,
        dict(constraints or source.get("constraints") or {}),
        ttl_seconds=ttl_seconds,
    )
    register_warrant(inherited)
    return str(inherited["payload"]["warrant_id"])


def issue_warrant(
    session_id: str,
    allowed_tools: List[str],
    constraints: Optional[Dict[str, Any]] = None,
    ttl_seconds: int = 900,
    secret: Optional[str] = None,
) -> Dict[str, Any]:
    # Harte Obergrenze: ein Aufrufer konnte frueher beliebig lange
    # Super-Warrants ausstellen (ttl_seconds ohne Limit).
    ttl_seconds = max(1, min(int(ttl_seconds or 900), 900))
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

    if "max_amount" in constraints:
        # D04/MED: alle Betrags-Aliase (amount/value/total/price/betrag) müssen
        # gegen das signierte Limit geprüft werden. Bei einem betragspflichtigen
        # Tool ist ein fehlender Betrag hart abzulehnen; ein reiner Pfad-Call
        # (z. B. read_file) benötigt keinen Betrag.
        amount_key = next(
            (k for k in AMOUNT_ARG_KEYS if k in call_args and call_args[k] is not None),
            None,
        )
        if amount_key is None:
            has_path_arg = any(
                k in call_args and call_args[k] not in (None, "") for k in PATH_ARG_KEYS
            )
            amount_relevant = (
                any(m in str(tool_name).lower() for m in _AMOUNT_TOOL_MARKERS)
                or not has_path_arg
            )
            if amount_relevant:
                return {
                    "allowed": False,
                    "reason": "Warrant verlangt max_amount, aber kein Betrag im Tool-Call (fail-closed).",
                }
        else:
            try:
                amt = float(call_args[amount_key])
                max_amt = float(constraints["max_amount"])
            except (TypeError, ValueError):
                return {"allowed": False, "reason": "Ungueltiger Betrag im Tool-Aufruf."}
            if not math.isfinite(amt) or not math.isfinite(max_amt) or amt < 0:
                return {"allowed": False, "reason": "Nicht-finiter oder negativer Betrag im Warrant-Aufruf abgelehnt."}
            if amt > max_amt:
                return {"allowed": False, "reason": f"Betrag {amt} ueberschreitet Warrant-Limit {max_amt}."}

    if "allowed_path_prefixes" in constraints:
        # KRITISCH: vorher wurde nur der exakte Key "path" geprueft. Ein Call
        # mit {"file_path": "../warrant_hmac.key"} umging das Constraint und
        # konnte das Warrant-Secret lesen. Alle gaengigen Pfad-Aliase aus der
        # SSOT (PATH_ARG_KEYS) prüfen.
        _PATH_KEYS = PATH_ARG_KEYS
        path_values = [str(call_args[k]) for k in _PATH_KEYS if k in call_args and call_args[k]]
        if any(str(call_args[k]).strip().lower() in ("", "none") for k in _PATH_KEYS if k in call_args):
            return {
                "allowed": False,
                "reason": "Warrant verlangt Pfad-Constraint, aber ein Pfad-Argument ist leer.",
            }
        if not path_values:
            # Pfad-Constraint vorhanden, aber kein Pfad-Argument erkennbar:
            # fail-closed statt still durchzulassen.
            return {"allowed": False, "reason": "Warrant verlangt Pfad-Constraint, aber kein Pfad-Argument im Tool-Call."}
        prefs = [posixpath.normpath(str(p).replace("\\", "/")).lstrip("./") for p in constraints["allowed_path_prefixes"]]

        def _path_in_prefix(p: str, pref: str) -> bool:
            pref = pref.rstrip("/")
            if not pref:
                return False
            try:
                return posixpath.commonpath([p, pref]) == pref
            except ValueError:
                return False

        for raw_p in path_values:
            raw_p = raw_p.replace("\\", "/").strip()
            norm_p = posixpath.normpath(raw_p).lstrip("./")
            if norm_p == ".." or norm_p.startswith("../") or "/../" in f"/{norm_p}/" or raw_p.startswith("/"):
                return {"allowed": False, "reason": f"Pfad-Traversal '{raw_p}' im Warrant abgelehnt."}
            if not any(_path_in_prefix(norm_p, pr) for pr in prefs if pr):
                return {"allowed": False, "reason": f"Pfad '{norm_p}' ausserhalb der Warrant-Prefixes."}

    return {"allowed": True, "warrant_id": payload.get("warrant_id"), "tool": tool_name}
