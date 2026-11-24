# -*- coding: utf-8 -*-
"""
backend/kanban_verifier.py
==========================
Meilenstein 76: Verifizierte Kanban-Cards mit Token-Budget & Proof-Gate
(crew-Pattern mit HITL-Entscheidung bei Budget-Ende oder Proof-Fehler).
"""

from __future__ import annotations

import os
import shlex
import subprocess
from typing import Any, Dict, Optional

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
) -> Dict[str, Any]:
    """Fuehrt das Proof-Kommando einer Kanban-Card aus (Done erst bei Exit Code 0)."""
    cmd_str = (proof_command or "").strip()
    if not cmd_str:
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

    proof_res = run_proof_command(proof_command or "", cwd=cwd)
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
) -> Dict[str, Any]:
    """HITL-Auflösung (User-Entscheidung 24.11.2026).

    * ``override``/``override_budget``: Budget erhöhen + Reverifikation; nur bei
      ``verified=True`` -> ``todo`` (registry-gestützter Spawn).
    * ``retry``: neu dispatchen via ``update_task_status(..., source="hitl")``.
    * ``abort``: ``failed`` + ``aborted_by_human`` + Audit-Event.

    Actor/Ersteller stammen aus der Session bzw. DB — niemals aus dem Body.
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
        if result_text or proof_command:
            vres = verify_card_completion(
                "hitl-override", result_text, proof_command=proof_command,
                token_used=0, token_budget=new_budget, cwd=cwd,
            )
            verified = bool(vres.get("verified"))
            reason = str(vres.get("reason") or "")
        if primary_model or diff_text:
            xres = cross_model_verify_card("hitl-override", primary_model or "default", diff_text=diff_text)
            verified = verified and bool(xres.get("passed"))
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
                "block_kind": "override_reverification_failed_hitl",
                "verified": False,
                "reset_retries": False,
                "reason": f"Override ohne erfolgreiche Reverifikation abgelehnt: {reason}",
            }
        return {
            "resolution": act,
            "next_status": "todo",
            "token_budget": new_budget,
            "old_budget": old_budget,
            "block_kind": "approval_granted",
            "verified": verified,
            "reset_retries": True,
            "reason": reason,
        }
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
    """Prueft geloeschte Assertions und bestimmt das unabhaengige Verifier-Modell."""
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
            "reason": f"{len(deleted_assertions)} geloeschte Test-Assertion(s) erkannt.",
        }
    return {
        "task_id": task_id,
        "passed": True,
        "requires_hitl": False,
        "block_kind": None,
        "verifier_model": verifier_model,
        "deleted_assertions": [],
        "reason": "Cross-Model-Precheck bestanden.",
    }
