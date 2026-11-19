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


def run_proof_command(
    proof_command: str,
    cwd: Optional[str] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    """Fuehrt das Proof-Kommando einer Kanban-Card aus (Done erst bei Exit Code 0)."""
    cmd_str = (proof_command or "").strip()
    if not cmd_str:
        return {"passed": True, "exit_code": 0, "stdout": "", "stderr": "", "skipped": True}
    try:
        args = shlex.split(cmd_str, posix=True)
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
) -> Dict[str, Any]:
    """Loest eine blockierte Card per HITL-Entscheidung auf (override_budget | retry | abort)."""
    act = (action or "").strip().lower()
    if act == "override_budget":
        new_budget = int(override_budget) if override_budget and int(override_budget) > 0 else max(current_budget * 2, current_budget + 10000)
        return {"next_status": "ready", "token_budget": new_budget, "block_kind": "approval_granted", "reset_retries": True}
    if act == "retry":
        return {"next_status": "ready", "token_budget": current_budget, "block_kind": "approval_granted", "reset_retries": True}
    if act == "abort":
        return {"next_status": "failed", "token_budget": current_budget, "block_kind": "aborted_by_human", "reset_retries": False}
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
