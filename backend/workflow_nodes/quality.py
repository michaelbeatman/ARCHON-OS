"""Cluster 8 — Self-Critique / Anti-AI-Slop-Revisionsschleife des DAG-Executors.

Reine Extraktion aus ``default_agent_node_executor`` (frueher ~:1389-1461).
KEINE Logikaenderung: der ``output_schema``-Schutz (validiertes JSON darf NICHT
durch Prosa-Revision ueberschrieben werden), ``max_rev``/``min_q``-Clamps,
``evaluate_asset_quality``-Payloads, Revisions-Prompt und die ``while``-Schleife
sind 1:1 uebernommen.

Dependency-Injection (S3): ``dispatch_with_budget`` zur Aufrufzeit uebergeben;
``backend.content_machine.evaluate_asset_quality`` bleibt Lazy-Import, damit
bestehende Patches greifen.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, NamedTuple, Optional, Tuple

# Gleicher Logger-Name wie vor der Extraktion (kein stiller Kanal-Wechsel).
logger = logging.getLogger("archon.workflow_dag")

__all__ = ["QualityOutcome", "run_quality_revisions"]


class QualityOutcome(NamedTuple):
    """Alle von Cluster 8 veraenderten Locals der Facade."""

    content: str
    res: Dict[str, Any]
    is_error: bool
    quality_report: Optional[Dict[str, Any]]
    revisions_used: int


async def run_quality_revisions(
    *,
    node: Dict[str, Any],
    res: Dict[str, Any],
    content: str,
    is_error: bool,
    output_schema: Any,
    parsed_output: Any,
    channel_hint: str,
    is_content_node: bool,
    model: str,
    agent_id: str,
    agent_name: str,
    eff_system_prompt: str,
    role: str,
    reasoning_level: str,
    kanban_task_id: Optional[str],
    full_prompt: str,
    dispatch_with_budget: Callable[..., Awaitable[Tuple[Any, bool]]],
) -> QualityOutcome:
    """Quality-Check + bis zu ``max_revisions`` Anti-Slop-Revisionen."""
    quality_report: Optional[Dict[str, Any]] = None
    revisions_used = 0
    if not is_error and content and is_content_node:
        try:
            from backend.content_machine import evaluate_asset_quality

            if isinstance(output_schema, dict) and isinstance(parsed_output, dict):
                q_hook = str(parsed_output.get("hook") or parsed_output.get("title") or "")
                q_body = str(parsed_output.get("body") or parsed_output.get("content") or parsed_output.get("summary") or content)
                q_cta = str(parsed_output.get("cta") or "")
                quality_report = evaluate_asset_quality({
                    "channel": channel_hint or "linkedin",
                    "hook": q_hook,
                    "body": q_body,
                    "cta": q_cta,
                })
            else:
                max_rev = max(0, min(2, int(node.get("max_revisions") if node.get("max_revisions") is not None else 1)))  # type: ignore[arg-type]
                min_q = int(node.get("min_quality_score") or 75)
                lines_c = [ln.strip() for ln in content.splitlines() if ln.strip()]
                quality_report = evaluate_asset_quality({
                    "channel": channel_hint or "linkedin",
                    "hook": lines_c[0] if lines_c else "",
                    "body": content,
                    "cta": lines_c[-1] if len(lines_c) > 1 else "",
                })
                while (revisions_used < max_rev and not is_error
                       and (not quality_report.get("passed") or int(quality_report.get("score", 0)) < min_q)):
                    revisions_used += 1
                    rev_issues = "; ".join(quality_report.get("issues") or [])
                    rev_sugg = "; ".join(quality_report.get("suggestions") or [])
                    rev_prompt = (
                        f"{full_prompt}\n\n"
                        f"[SELBST-KRITIK / ANTI-AI-SLOP-PRUEFUNG (Revision {revisions_used}/{max_rev})]\n"
                        f"Dein bisheriger Entwurf erreichte nur Quality-Score {quality_report.get('score')}/100.\n"
                        f"Befunde: {rev_issues}\n"
                        f"Konkrete Korrektur-Aufgaben: {rev_sugg}\n\n"
                        f"BISHERIGER ENTWURF:\n{content[:4500]}\n\n"
                        "Ueberarbeite den Text direkt, konkret, faktenbasiert (mit Zahlen-Anker & klarem CTA) und komplett ohne KI-Floskeln."
                    )
                    rev_res, rev_blocked = await dispatch_with_budget(
                        node, res, model,
                        agent_id=agent_id,
                        agent_name=agent_name,
                        prompt=rev_prompt,
                        role=role,
                        system_prompt=eff_system_prompt,
                        model=model,
                        reasoning_level=reasoning_level,
                        task_id=str(kanban_task_id or node.get("id") or ""),
                        _phase="anti_slop_revision",
                    )
                    if rev_blocked:
                        is_error = True
                        res["error"] = str(rev_res.get("error") or "NODE_TOKEN_BUDGET_EXCEEDED")
                        break
                    rev_content = str(rev_res.get("content") or "").strip()
                    if rev_content and str(rev_res.get("status") or "success").lower() not in ("error", "failed", "blocked"):
                        content = rev_content
                        res["input_tokens"] = int(res.get("input_tokens") or 0) + int(rev_res.get("input_tokens") or 0)
                        res["output_tokens"] = int(res.get("output_tokens") or 0) + int(rev_res.get("output_tokens") or 0)
                        lines_c = [ln.strip() for ln in content.splitlines() if ln.strip()]
                        quality_report = evaluate_asset_quality({
                            "channel": channel_hint or "linkedin",
                            "hook": lines_c[0] if lines_c else "",
                            "body": content,
                            "cta": lines_c[-1] if len(lines_c) > 1 else "",
                        })
                    else:
                        break
        except Exception as qexc:
            logger.debug("[WorkflowDAG] Anti-Slop-Quality-Check uebersprungen: %s", qexc)

    return QualityOutcome(
        content=content,
        res=res,
        is_error=is_error,
        quality_report=quality_report,
        revisions_used=revisions_used,
    )
