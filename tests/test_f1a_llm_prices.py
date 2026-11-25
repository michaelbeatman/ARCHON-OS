"""F1a — Characterization-Tests fuer die Preis-SSOT und den Pfad-SSOT.

Deckt insbesondere den von Antigravity gefundenen Bug ab: ``get_llm_prices()``
liefert ``{"status": ..., "prices": {...}}`` mit ``prompt_1m``/``completion_1m``.
Vorher suchte ``llm_kernel.estimate_model_cost_usd`` direkt im Outer-Dict nach
der model_id und nach ``input``/``prompt_per_1m`` -> Live-Preise griffen nie.
"""

import pytest

from backend import llm_kernel


def test_live_prices_are_unpacked_and_use_prompt_1m(monkeypatch):
    def fake_prices():
        return {
            "status": "ok",
            "prices": {
                "openai/gpt-f1a-test": {
                    "name": "F1A Test",
                    "prompt_1m": 2.0,
                    "completion_1m": 8.0,
                }
            },
        }

    monkeypatch.setattr("backend.llm_prices.get_llm_prices", fake_prices)
    cost = llm_kernel.estimate_model_cost_usd(
        "openai/gpt-f1a-test", 1_000_000, 1_000_000
    )
    assert cost == pytest.approx(10.0)


def test_error_status_falls_back_to_static_defaults(monkeypatch):
    monkeypatch.setattr(
        "backend.llm_prices.get_llm_prices",
        lambda: {"status": "error", "prices": {}},
    )
    cost = llm_kernel.estimate_model_cost_usd(
        "some-unknown-model", 1_000_000, 1_000_000
    )
    # Kein Fallback-Tabellen-Treffer -> statische Defaults 0.30 + 1.20.
    assert cost == pytest.approx(1.50)


def test_get_price_cache_reflects_refresh(monkeypatch):
    from backend import llm_prices

    monkeypatch.setattr(llm_prices, "_price_cache", None)
    assert llm_prices.get_price_cache() is None
    sentinel = {"model/x": {"prompt_1m": 1.0, "completion_1m": 2.0}}
    monkeypatch.setattr(llm_prices, "_price_cache", sentinel)
    assert llm_prices.get_price_cache() is sentinel


def test_guardian_limits_path_is_ssot():
    from archon.core import paths
    from archon.routers import autonomy_settings

    assert autonomy_settings.GUARDIAN_LIMITS_FILE == paths.GUARDIAN_LIMITS_FILE
    assert autonomy_settings.guardian_limits_path() == paths.GUARDIAN_LIMITS_FILE
