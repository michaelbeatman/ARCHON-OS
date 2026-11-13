"""
backend/cost_estimator.py
Pre-Flight Kosten-Schätzer & Budget-Prognose (Pillar 5 / FinOps).
Schätzt vor dem Start einer Aufgabe anhand von Prompt-Länge, Zielmodell und
erwarteten Output-Tokens die voraussichtlichen Kosten in USD ab.
"""

from typing import Dict, Any

MODEL_PRICING = {
    "deepseek/deepseek-chat": {"in_per_m": 0.14, "out_per_m": 0.28},
    "deepseek-chat": {"in_per_m": 0.14, "out_per_m": 0.28},
    "anthropic/claude-3-5-sonnet": {"in_per_m": 3.00, "out_per_m": 15.00},
    "claude-3-5-sonnet": {"in_per_m": 3.00, "out_per_m": 15.00},
    "anthropic/claude-3-haiku": {"in_per_m": 0.25, "out_per_m": 1.25},
    "openai/gpt-4o-mini": {"in_per_m": 0.15, "out_per_m": 0.60},
    "openai/gpt-4o": {"in_per_m": 2.50, "out_per_m": 10.00},
    "free-forever": {"in_per_m": 0.0, "out_per_m": 0.0}
}

def estimate_prompt_cost(
    prompt: str,
    model_name: str = "deepseek/deepseek-chat",
    expected_output_tokens: int = 1000,
    task_budget_usd: float = 0.25
) -> Dict[str, Any]:
    """Berechnet die voraussichtlichen Token und Dollar-Kosten eines Auftrags."""
    input_tokens = max(1, len(prompt) // 4)
    m_key = model_name.lower().strip()

    rates = None
    for k, v in MODEL_PRICING.items():
        if k in m_key:
            rates = v
            break

    if rates is None:
        # Fallback: Kostenfrei nur wenn explizit lokal / free im Modellnamen
        if any(tok in m_key for tok in ("free", "local", "ollama")):
            rates = MODEL_PRICING["free-forever"]
        else:
            # Konservativer Standardtarif fuer unbekannte kommerzielle Modelle (Pillar 5 / FinOps)
            rates = {"in_per_m": 2.50, "out_per_m": 10.00}

    in_cost = (input_tokens / 1_000_000.0) * rates["in_per_m"]
    out_cost = (expected_output_tokens / 1_000_000.0) * rates["out_per_m"]
    total_est = in_cost + out_cost

    fits_budget = total_est <= task_budget_usd

    return {
        "status": "success",
        "model": model_name,
        "input_tokens_est": input_tokens,
        "expected_output_tokens": expected_output_tokens,
        "total_tokens_est": input_tokens + expected_output_tokens,
        "estimated_cost_usd": round(total_est, 5),
        "task_budget_usd": task_budget_usd,
        "fits_budget": fits_budget,
        "warning": None if fits_budget else f"Geschätzte Kosten (${total_est:.4f}) überschreiten das Budget (${task_budget_usd:.2f})!"
    }
