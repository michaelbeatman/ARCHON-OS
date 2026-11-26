# -*- coding: utf-8 -*-
"""
backend/kanban_verifier.py
==========================
Meilenstein 76: Verifizierte Kanban-Cards mit Token-Budget & Proof-Gate
(crew-Pattern mit HITL-Entscheidung bei Budget-Ende oder Proof-Fehler).
"""

from __future__ import annotations

import logging
import os
import shlex
import sqlite3
import subprocess
from typing import Any, Dict, Optional

_logger = logging.getLogger("kanban_verifier")

# D14/H1: Hoheitsakte an eine exakte Aktion/Ressource gebunden (analog
# operations_review.py). Der Proof wird genau einmal verbraucht.
HITL_OVERRIDE_ACTION = "kanban_hitl_override"

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# HARTUNG: Proof-Kommande sind Agenten-gesteuerte Subprozesse. Ohne Policy
# konnten beliebige Binarys (inkl. shell -c) mit den Rechten des Servers
# ausgefuehrt werden. Positiv-Liste + Jail statt Blacklist.
_ALLOWED_PROOF_BINARIES = frozenset({
    "pytest", "python", "python3", "node", "npm", "npx", "ruff", "mypy",
})
_PROOF_SHELL_METACHARS = (";", "&&", "||", "|", "`", "$(", ">", "<", "\n", "\r")


def run_proof_command(
    proof_command: str,
    cwd: Optional[str] = None,
    timeout: int = 30,
    *,
    require_proof: bool = False,
) -> Dict[str, Any]:
    """Fuehrt das Proof-Kommando einer Kanban-Card aus (Done erst bei Exit Code 0).

    D14/H1: ``require_proof=True`` (HITL-Override) macht ein leeres Kommando
    hart zur Ablehnung. Ein "erfolgreicher" Proof mit ``skipped=True`` darf
    niemals eine gesperrte Karte freigeben.
    """
    cmd_str = (proof_command or "").strip()
    if not cmd_str:
        if require_proof:
            return {
                "passed": False, "exit_code": -1, "stdout": "", "stderr": "",
                "skipped": False, "error_code": "EMPTY_PROOF_COMMAND",
                "reason": "Pflicht-Proof-Command fehlt im Task-Kontext (fail-closed).",
            }
        return {"passed": True, "exit_code": 0, "stdout": "", "stderr": "", "skipped": True}

    def _rejected(reason: str) -> Dict[str, Any]:
        return {
            "passed": False, "exit_code": -1, "stdout": "",
            "stderr": f"Proof-Kommando abgelehnt (Policy): {reason}", "skipped": False,
        }

    if any(token in cmd_str for token in _PROOF_SHELL_METACHARS):
        return _rejected("Shell-Metazeichen sind nicht erlaubt.")
    try:
        args = shlex.split(cmd_str, posix=True)
    except ValueError as exc:
        return _rejected(f"Ungueltige Kommando-Syntax: {exc}")
    if not args:
        return _rejected("Leeres Kommando.")
    binary = os.path.splitext(os.path.basename(args[0]))[0].lower()  # Windows: python.exe -> python
    if binary not in _ALLOWED_PROOF_BINARIES:
        return _rejected(f"Binary '{binary}' steht nicht auf der Allowlist.")
    # Pfad-Jail: keine traversal/absoluten Pfade aus dem Agenten-Kommando.
    base = os.path.abspath(cwd or WORKSPACE_DIR)
    for arg in args[1:]:
        if arg.startswith("-"):
            continue
        candidate = arg if os.path.isabs(arg) else os.path.join(base, arg)
        try:
            inside = os.path.commonpath([base, os.path.abspath(candidate)]) == base
        except ValueError:
            inside = False  # anderes Laufwerk (Windows) -> ablehnen
        if not inside:
            return _rejected(f"Pfad ausserhalb des Arbeitsverzeichnisses: {arg}")
    try:
        proc = subprocess.run(
            args,
            cwd=cwd or WORKSPACE_DIR,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "passed": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": (proc.stdout or "")[-2000:],
            "stderr": (proc.stderr or "")[-2000:],
            "skipped": False,
        }
    except subprocess.TimeoutExpired:
        return {"passed": False, "exit_code": -1, "stdout": "", "stderr": f"Timeout nach {timeout}s", "skipped": False}
    except Exception as exc:
        return {"passed": False, "exit_code": -1, "stdout": "", "stderr": str(exc), "skipped": False}


def verify_card_completion(
    task_id: str,
    result_text: str,
    proof_command: Optional[str] = None,
    token_used: int = 0,
    token_budget: int = 0,
    retry_count: int = 0,
    max_auto_retries: int = 1,
    cwd: Optional[str] = None,
    *,
    require_proof: bool = False,
) -> Dict[str, Any]:
    """
    Prueft Token-Budget, Ergebnis-Qualitaet und optionales Proof-Kommando.
    Liefert:
      - status: 'done' | 'retry' | 'blocked'
      - requires_hitl: bool
      - block_kind: str | None
      - hitl_options: list[str]
    """
    if token_budget > 0 and token_used > token_budget:
        return {
            "task_id": task_id,
            "verified": False,
            "status": "blocked",
            "requires_hitl": True,
            "block_kind": "budget_exceeded_hitl",
            "hitl_options": ["override_budget", "retry", "abort"],
            "reason": f"Token-Budget ueberschritten ({token_used} > {token_budget}). Menschliche Freigabe erforderlich.",
            "proof": None,
        }

    text = (result_text or "").strip()
    if not text or text.startswith("[FEHLER:"):
        if retry_count < max_auto_retries:
            return {
                "task_id": task_id,
                "verified": False,
                "status": "retry",
                "next_retry_count": retry_count + 1,
                "requires_hitl": False,
                "block_kind": None,
                "hitl_options": [],
                "reason": "Leeres oder fehlerhaftes Ergebnis — automatischer Retry.",
                "proof": None,
            }
        return {
            "task_id": task_id,
            "verified": False,
            "status": "blocked",
            "requires_hitl": True,
            "block_kind": "verifier_failed_hitl",
            "hitl_options": ["retry", "override_budget", "abort"],
            "reason": "Ergebnis-Verifikation nach Retry fehlgeschlagen. HITL-Entscheidung erforderlich.",
            "proof": None,
        }

    proof_res = run_proof_command(proof_command or "", cwd=cwd, require_proof=require_proof)
    if not proof_res["passed"]:
        if retry_count < max_auto_retries:
            return {
                "task_id": task_id,
                "verified": False,
                "status": "retry",
                "next_retry_count": retry_count + 1,
                "requires_hitl": False,
                "block_kind": None,
                "hitl_options": [],
                "reason": f"Proof-Command fehlgeschlagen (Exit {proof_res['exit_code']}) — automatischer Retry.",
                "proof": proof_res,
            }
        return {
            "task_id": task_id,
            "verified": False,
            "status": "blocked",
            "requires_hitl": True,
            "block_kind": "proof_failed_hitl",
            "hitl_options": ["retry", "override_budget", "abort"],
            "reason": f"Proof-Command fehlgeschlagen (Exit {proof_res['exit_code']}). HITL-Entscheidung erforderlich.",
            "proof": proof_res,
        }

    return {
        "task_id": task_id,
        "verified": True,
        "status": "done",
        "requires_hitl": False,
        "block_kind": None,
        "hitl_options": [],
        "reason": "Verifiziert.",
        "proof": proof_res,
    }


def resolve_card_hitl_decision(
    action: str,
    current_budget: int = 0,
    override_budget: Optional[int] = None,
    *,
    actor: str = "",
    created_by: str = "",
    result_text: str = "",
    proof_command: Optional[str] = None,
    primary_model: str = "",
    diff_text: str = "",
    cwd: Optional[str] = None,
    require_full_proof: bool = False,
    verified_cross_model: Optional[Dict[str, Any]] = None,
    verified_passkey: bool = False,
) -> Dict[str, Any]:
    """HITL-Auflösung (User-Entscheidung 24.11.2026).

    * ``override``/``override_budget``: Budget erhöhen + Reverifikation; nur bei
      ``verified=True`` -> ``todo`` (registry-gestützter Spawn).
    * ``retry``: neu dispatchen via ``update_task_status(..., source="hitl")``.
    * ``abort``: ``failed`` + ``aborted_by_human`` + Audit-Event.

    Actor/Ersteller stammen aus der Session bzw. DB — niemals aus dem Body.

    D14/H1: ``require_full_proof=True`` ist der Produktivpfad. Dann zaehlen
    ausschliesslich die aus dem Task-Kontext geladenen Proof-Parameter, ein
    echtes Kommando (Exit 0, ``skipped=False``), ein echter Cross-Modell-Call
    und ein verbrauchter Passkey-Proof. Die positionalen Proof-Argumente
    bleiben nur für direkte Bibliotheksaufrufe (Rueckwaertskompatibilitaet)
    erhalten und werden im Produktivpfad bewusst ignoriert.
    """
    act = (action or "").strip().lower()
    actor = str(actor or "").strip()
    created_by = str(created_by or "").strip()
    # D14: der Ersteller darf generell keine eigene HITL-Sperre aufloesen
    # (auch nicht per `retry`). Nur die zusaetzliche Fail-Closed-Pruefung bei
    # unbekanntem Ersteller gilt fuer Overrides (Budget-Erhoehung).
    if actor and created_by and actor == created_by:
        raise PermissionError("Ersteller darf die eigene HITL-Sperre nicht auflösen (Vier-Augen-Prinzip).")
    if act in ("override", "override_budget") and not created_by:
        raise PermissionError(
            "HITL-Override verweigert: Ersteller nicht verifizierbar (Vier-Augen-Prinzip)."
        )

    old_budget = int(current_budget or 0)
    new_budget = old_budget

    if act in ("override", "override_budget"):
        new_budget = int(override_budget) if override_budget and int(override_budget) > 0 else max(old_budget * 2, old_budget + 10000)
        if new_budget <= old_budget:
            raise ValueError("Override-Budget muss groesser als das aktuelle Budget sein.")
        verified = False
        reason = "Keine Reverifikation durchgefuehrt."
        proof_res: Optional[Dict[str, Any]] = None
        cross_res: Optional[Dict[str, Any]] = None
        if require_full_proof:
            # Produktivpfad: keinerlei Body-Steuerung. `primary_model`/`diff_text`
            # aus dem Request werden hier bewusst NICHT verwendet.
            if not verified_passkey:
                reason = "Passkey-Proof nicht verifiziert."
            elif not isinstance(verified_cross_model, dict):
                reason = "Kein echter Cross-Modell-Verifier-Call vorhanden."
            elif not bool(verified_cross_model.get("passed")):
                reason = "Cross-Modell-Verifier hat abgelehnt."
            elif verified_cross_model.get("model_call") is not True:
                reason = "Cross-Modell-Verifier war nur Precheck (kein Modellaufruf)."
            elif not result_text or not proof_command:
                reason = "Proof-Parameter fehlen im verifizierten Task-Kontext."
            else:
                vres = verify_card_completion(
                    "hitl-override", result_text, proof_command=proof_command,
                    token_used=0, token_budget=new_budget, cwd=cwd,
                    require_proof=True,
                )
                proof_res = vres.get("proof") if isinstance(vres.get("proof"), dict) else None
                verified = bool(vres.get("verified"))
                reason = str(vres.get("reason") or "")
                if verified and (
                    not proof_res
                    or proof_res.get("skipped") is not False
                    or proof_res.get("exit_code") != 0
                ):
                    # D14/H1: leerer/uebersprungener Proof ist kein Proof.
                    verified = False
                    reason = "Proof-Command wurde nicht echt ausgefuehrt (Exit 0, skipped=False erforderlich)."
                if verified:
                    cross_res = verified_cross_model
                    reason = (
                        f"{reason} | Cross-Modell {cross_res.get('verifier_model') or 'unbekannt'} "
                        f"bestanden ({cross_res.get('reason') or ''})"
                    )
        else:
            # Rueckwaertskompatible Bibliotheksfunktion (kein Hoheitspfad).
            if result_text or proof_command:
                vres = verify_card_completion(
                    "hitl-override", result_text, proof_command=proof_command,
                    token_used=0, token_budget=new_budget, cwd=cwd,
                )
                proof_res = vres.get("proof") if isinstance(vres.get("proof"), dict) else None
                verified = bool(vres.get("verified"))
                reason = str(vres.get("reason") or "")
            if (primary_model or diff_text) and verified:
                xres = cross_model_verify_card(
                    "hitl-override", primary_model or "default", diff_text=diff_text
                )
                verified = bool(xres.get("passed"))
                reason = f"{reason} | {xres.get('reason') or ''}"
        # D14/MED: der Env-Fail-Open-Schalter
        # ARCHON_KANBAN_HITL_ALLOW_UNVERIFIED_OVERRIDE wurde entfernt. Ohne
        # erfolgreiche Reverifikation gibt es keinen Override — immer blocked.
        if not verified:
            return {
                "resolution": act,
                "next_status": "blocked",
                "token_budget": new_budget,
                "old_budget": old_budget,
                "block_kind": (
                    "override_proof_missing_hitl" if require_full_proof
                    else "override_reverification_failed_hitl"
                ),
                "verified": False,
                "reset_retries": False,
                "reason": f"Override ohne erfolgreiche Reverifikation abgelehnt: {reason}",
            }
        result = {
            "resolution": act,
            "next_status": "todo",
            "token_budget": new_budget,
            "old_budget": old_budget,
            "block_kind": "approval_granted",
            "verified": True,
            "reset_retries": True,
            "reason": reason,
        }
        if require_full_proof:
            # Nachweis fuer die Audit-Kette des Routers (vor Statuswechsel).
            result.update({
                "proof": proof_res,
                "cross_model": cross_res,
                "passkey_verified": True,
                "primary_model": "",  # nie aus dem Body — Herkunft: Task-Kontext
            })
        return result
    if act == "retry":
        return {
            "resolution": act,
            "next_status": "todo",
            "token_budget": old_budget,
            "old_budget": old_budget,
            "block_kind": "approval_granted",
            "verified": True,
            "reset_retries": True,
            "reason": "Retry: Re-Dispatch ueber update_task_status(source='hitl').",
        }
    if act == "abort":
        return {
            "resolution": act,
            "next_status": "failed",
            "token_budget": old_budget,
            "old_budget": old_budget,
            "block_kind": "aborted_by_human",
            "verified": True,
            "reset_retries": False,
            "reason": "Vom Menschen abgebrochen.",
        }
    raise ValueError(f"Unbekannte HITL-Aktion: {action}")


# --- M81: Cross-Model-Verifier & Test-Assertion-Waechter (shadow-army-Pattern) ---
_ASSERTION_PATTERNS = ("assert ", "pytest.raises", "expect(", "assertEqual", "assertRaises", "assertTrue", "assertFalse")


def detect_deleted_test_assertions(diff_text: str) -> list[str]:
    """Erkennt geloeschte Test-Assertions in einem Unified-Diff (shadow-army)."""
    removed = []
    added = []
    for line in (diff_text or "").splitlines():
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("-") and any(pat in line for pat in _ASSERTION_PATTERNS):
            removed.append(line[1:].strip())
        elif line.startswith("+") and any(pat in line for pat in _ASSERTION_PATTERNS):
            added.append(line[1:].strip())
    added_set = set(added)
    return [r for r in removed if r not in added_set]


def pick_independent_verifier_model(primary_model: str) -> str:
    """Waehlt fuer den Verifier bewusst eine andere Modell-Familie als das Writer-Modell."""
    m = (primary_model or "").lower()
    if "claude" in m or "anthropic" in m:
        return "deepseek/deepseek-chat"
    if "deepseek" in m:
        return "google/gemini-2.5-pro"
    if "gemini" in m or "google" in m:
        return "anthropic/claude-sonnet-4"
    if "gpt" in m or "openai" in m or "codex" in m:
        return "anthropic/claude-sonnet-4"
    return "deepseek/deepseek-chat"


def cross_model_verify_card(
    task_id: str,
    primary_model: str,
    diff_text: str = "",
) -> Dict[str, Any]:
    """D14/M5: Precheck-Haelfte der SSOT — KEIN Modellaufruf.

    Der echte Dispatch liegt ausschliesslich in
    ``backend.operations_execution._cross_model_verify_task_result()``, das
    diese Funktion als Precheck aufruft. ``model_call=False`` macht die
    Abwesenheit eines LLM-Calls explizit, damit kein Hoheitspfad den Precheck
    mit einer echten Verifikation verwechseln kann.
    """
    deleted_assertions = detect_deleted_test_assertions(diff_text)
    verifier_model = pick_independent_verifier_model(primary_model)
    if deleted_assertions:
        return {
            "task_id": task_id,
            "passed": False,
            "requires_hitl": True,
            "block_kind": "deleted_test_assertions_hitl",
            "verifier_model": verifier_model,
            "deleted_assertions": deleted_assertions,
            "model_call": False,
            "reason": f"{len(deleted_assertions)} geloeschte Test-Assertion(s) erkannt.",
        }
    return {
        "task_id": task_id,
        "passed": True,
        "requires_hitl": False,
        "block_kind": None,
        "verifier_model": verifier_model,
        "deleted_assertions": [],
        "model_call": False,
        "reason": "Cross-Model-Precheck bestanden (kein Modellaufruf — SSOT: _cross_model_verify_task_result).",
    }


def load_hitl_proof_context(
    task_id: str,
    *,
    kanban_db: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """D14/H1: Proof-Parameter ausschliesslich aus dem Task-Kontext lesen.

    Quellen sind der signierte Kanban-Sidecar (``config/kanban_meta.json``,
    ``tasks[task_id]``) und die Kanban-Tabelle. Ein Request-Body wird hier
    bewusst nicht uebergeben — damit ist eine Body-Faelschung strukturell
    ausgeschlossen, nicht nur per Router-Pruefung.
    """
    tmeta: Dict[str, Any] = {}
    try:
        if meta is None:
            from backend.kanban_sidecar import load_kanban_meta

            meta = load_kanban_meta()
        tmeta = ((meta or {}).get("tasks") or {}).get(task_id) or {}
    except Exception as exc:
        _logger.warning("[HITL] Kanban-Meta nicht lesbar (fail-closed): %s", exc)

    row: Dict[str, Any] = {}
    if kanban_db and os.path.exists(kanban_db):
        try:
            from backend.db_paths import get_db_connection

            conn = get_db_connection(kanban_db, timeout=5.0)
            try:
                # get_db_connection() liefert Rows ohne row_factory.
                conn.row_factory = sqlite3.Row
                col_info = conn.execute("PRAGMA table_info(tasks)").fetchall()
                keys = [str(c[1]) for c in col_info]
                if keys:
                    fetched = conn.execute(
                        "SELECT * FROM tasks WHERE id = ?", (task_id,)
                    ).fetchone()
                    if fetched is not None:
                        row = {k: fetched[k] for k in keys}
            finally:
                conn.close()
        except (sqlite3.Error, OSError) as exc:
            _logger.warning("[HITL] Task-Kontext nicht lesbar (fail-closed): %s", exc)

    def _first(*names: str) -> Any:
        for source in (tmeta, row):
            for name in names:
                val = source.get(name)
                if val is not None and str(val).strip() != "":
                    return val
        return ""

    try:
        token_used = int(_first("token_used", "tokens_used") or 0)
    except (TypeError, ValueError):
        token_used = 0

    return {
        "task_id": task_id,
        # Nur serverseitig persistierte Werte. `primary_model` stammt aus der
        # Rollen-SSOT des Dispatches, NIEMALS aus dem HITL-Request-Body.
        "proof_command": str(_first("proof_command") or "").strip(),
        "result_text": str(_first("result_text", "result") or ""),
        "primary_model": str(_first("primary_model", "model", "model_override") or "").strip(),
        "diff_text": str(_first("diff_text") or ""),
        "system_prompt": str(_first("system_prompt") or ""),
        "token_used": token_used,
        "context_found": bool(tmeta or row),
    }


async def resolve_card_hitl_decision_verified(
    action: str,
    task_id: str,
    *,
    actor: str,
    created_by: str,
    current_budget: int = 0,
    override_budget: Optional[int] = None,
    proof_token: str = "",
    kanban_db: Optional[str] = None,
    cwd: Optional[str] = None,
) -> Dict[str, Any]:
    """D14/H1+M5: einziger produktiver HITL-Override-Pfad (fail-closed).

    Re Reihenfolge: Vier-Augen -> Passkey-Proof -> Task-Kontext -> echter
    Proof (Exit 0, ``skipped=False``) -> echter Cross-Modell-Call ->
    Entscheidung. Der Router auditiert das Ergebnis und aendert den Status
    erst nach erfolgreichem Audit.
    """
    act = str(action or "").strip().lower()
    who = str(actor or "").strip()
    creator = str(created_by or "").strip()
    if act not in ("override", "override_budget"):
        return resolve_card_hitl_decision(
            act, current_budget=current_budget, override_budget=override_budget,
            actor=who, created_by=creator,
        )
    if who and creator and who == creator:
        raise PermissionError(
            "Ersteller darf die eigene HITL-Sperre nicht auflösen (Vier-Augen-Prinzip)."
        )
    if not creator:
        raise PermissionError(
            "HITL-Override verweigert: Ersteller nicht verifizierbar (Vier-Augen-Prinzip)."
        )
    if not who:
        raise PermissionError("HITL-Override verweigert: kein verifizierter Session-Actor.")

    old_budget = int(current_budget or 0)
    new_budget = (
        int(override_budget)
        if override_budget and int(override_budget) > 0
        else max(old_budget * 2, old_budget + 10000)
    )
    if new_budget <= old_budget:
        raise ValueError("Override-Budget muss groesser als das aktuelle Budget sein.")

    def _blocked(kind: str, reason: str) -> Dict[str, Any]:
        return {
            "resolution": act,
            "next_status": "blocked",
            "token_budget": new_budget,
            "old_budget": old_budget,
            "block_kind": kind,
            "verified": False,
            "reset_retries": False,
            "reason": reason,
        }

    # 1) Passkey-Proof: an Aktion + Ressource gebunden, genau einmal verbraucht.
    try:
        from backend.passkey_hitl import consume_hitl_proof_token

        proof_ok = consume_hitl_proof_token(
            proof_token, who, category="system",
            action=HITL_OVERRIDE_ACTION, resource=task_id, consume=True,
        )
    except Exception as exc:
        _logger.error("[HITL] Passkey-Pruefung fehlgeschlagen (fail-closed): %s", exc)
        return _blocked("hitl_proof_unavailable", f"Passkey-Proof nicht pruefbar: {exc}")
    if not proof_ok:
        return _blocked(
            "hitl_proof_required_hitl",
            "Passkey-Proof erforderlich/ungueltig fuer kanban_hitl_override und diese Karte.",
        )

    # 2) Kein Body-Freitext: Proof-Parameter aus dem Task-Kontext.
    ctx = load_hitl_proof_context(task_id, kanban_db=kanban_db)

    # 3) Echter Cross-Modell-Call (SSOT in operations_execution, inkl. Precheck).
    try:
        from backend.operations_execution import _cross_model_verify_task_result

        cross = await _cross_model_verify_task_result(
            task_id=task_id,
            result_text=ctx["result_text"],
            primary_model=ctx["primary_model"],
            diff_text=ctx["diff_text"],
            system_prompt=ctx["system_prompt"],
        )
    except Exception as exc:
        _logger.error("[HITL] Cross-Modell-Verifier nicht verfuegbar (fail-closed): %s", exc)
        return _blocked(
            "cross_model_verification_unavailable_hitl",
            f"Cross-Modell-Verifikation nicht abschliessbar: {exc}",
        )

    decision = resolve_card_hitl_decision(
        act,
        current_budget=current_budget,
        override_budget=override_budget,
        actor=who,
        created_by=creator,
        result_text=ctx["result_text"],
        proof_command=ctx["proof_command"] or None,
        # primary_model/diff_text werden NICHT aus dem Body uebernommen; die
        # Herkunft ist der geladene Task-Kontext (im decision auditierbar).
        require_full_proof=True,
        verified_cross_model=cross,
        verified_passkey=True,
        cwd=cwd,
    )
    decision["proof_context"] = {
        "task_id": task_id,
        "context_found": bool(ctx.get("context_found")),
        "proof_command_present": bool(ctx.get("proof_command")),
        "result_text_present": bool(ctx.get("result_text")),
        "primary_model_source": "task_context",
    }
    return decision
