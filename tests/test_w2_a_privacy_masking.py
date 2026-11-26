"""W2-A (Security) Regressionstests.

Abgedeckte Befunde:
- D04-H3 / D04-M3  privacy_router: Strengthening-Only-Merge, Audit-Fehler hart
- D04-H2 / D04-M5  secret_masker / llm_kernel: Maskierung nicht abschaltbar,
                   Masking-Fehler nie Klartext
- D04-M7           egress_firewall: Config-Fehler → harter Block (kein Allowlist-Fallback)
"""
from __future__ import annotations

import json
from typing import Any

import pytest


def _isolate_privacy_files(
    tmp_path: Any, monkeypatch: Any, privacy: dict[str, Any], settings: dict[str, Any] | None = None
) -> tuple[Any, Any]:
    """Legt temporäre Konfigurationsquellen an und verdrahtet privacy_router darauf."""
    from backend import privacy_router as pr

    priv_file = tmp_path / "privacy_routing.json"
    priv_file.write_text(json.dumps(privacy), encoding="utf-8")
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(
        json.dumps(settings if settings is not None else {}), encoding="utf-8"
    )
    monkeypatch.setattr(pr, "PRIVACY_CFG_FILE", str(priv_file))
    monkeypatch.setattr(pr, "ROOT_SETTINGS_FILE", str(settings_file))
    monkeypatch.delenv("PRIVACY_ZERO_EGRESS", raising=False)
    return priv_file, settings_file


def test_d04_h3_privacy_json_cannot_weaken_settings(tmp_path: Any, monkeypatch: Any) -> None:
    """settings.json zero_egress=true darf nicht durch false in privacy_routing.json aufgehoben werden."""
    _isolate_privacy_files(
        tmp_path,
        monkeypatch,
        privacy={
            "zero_egress_strict": False,
            "sensitive_local_routing": False,
            "hard_block_on_local_offline": False,
            "block_crm_erp_prefetch_on_cloud": False,
            "fallback_to_eu": True,
        },
        settings={"privacy": {"zero_egress": True}},
    )
    from backend import privacy_router as pr

    cfg = pr.get_privacy_config()
    assert cfg["zero_egress_strict"] is True
    assert cfg["sensitive_local_routing"] is True
    assert cfg["hard_block_on_local_offline"] is True
    assert cfg["block_crm_erp_prefetch_on_cloud"] is True
    assert cfg["fallback_to_eu"] is False


def test_d04_h3_false_in_json_cannot_weaken_hard_defaults(tmp_path: Any, monkeypatch: Any) -> None:
    """Ohne weitere Quelle bleiben die harten Defaults trotz false in JSON aktiv."""
    _isolate_privacy_files(
        tmp_path,
        monkeypatch,
        privacy={
            "zero_egress_strict": False,
            "sensitive_local_routing": False,
            "hard_block_on_local_offline": False,
            "block_crm_erp_prefetch_on_cloud": False,
            "fallback_to_eu": False,
        },
    )
    from backend import privacy_router as pr

    cfg = pr.get_privacy_config()
    assert cfg["zero_egress_strict"] is False  # Default darf false bleiben
    assert cfg["sensitive_local_routing"] is True
    assert cfg["hard_block_on_local_offline"] is True
    assert cfg["block_crm_erp_prefetch_on_cloud"] is True
    assert cfg["fallback_to_eu"] is False


def test_d04_h3_late_governance_strict_revokes_eu_fallback(tmp_path: Any, monkeypatch: Any) -> None:
    """Ein später aus governance aktivierter striker Modus entzieht eine JSON-Fallback-Freigabe."""
    _isolate_privacy_files(
        tmp_path,
        monkeypatch,
        privacy={"sensitive_local_routing": True, "fallback_to_eu": True, "mistral_api_key": "dummy"},
        settings={"zero_egress_governance": {"zero_egress_strict": True}},
    )
    from backend import privacy_router as pr

    cfg = pr.get_privacy_config()
    assert cfg["zero_egress_strict"] is True
    assert cfg["sensitive_local_routing"] is True
    assert cfg["fallback_to_eu"] is False


def test_d04_h3_env_zero_egress_revokes_eu_fallback(tmp_path: Any, monkeypatch: Any) -> None:
    """PRIVACY_ZERO_EGRESS=1 darf nicht von einer früheren JSON-Fallback-Freigabe unterlaufen werden."""
    _isolate_privacy_files(
        tmp_path,
        monkeypatch,
        privacy={"sensitive_local_routing": True, "fallback_to_eu": True, "mistral_api_key": "dummy"},
    )
    monkeypatch.setenv("PRIVACY_ZERO_EGRESS", "1")
    from backend import privacy_router as pr

    cfg = pr.get_privacy_config()
    assert cfg["zero_egress_strict"] is True
    assert cfg["fallback_to_eu"] is False


def test_d04_h3_fallback_allowed_only_without_strict_mode(tmp_path: Any, monkeypatch: Any) -> None:
    """Ohne strikten Modus darf ein explizit freigegebener EU-Fallback bestehen bleiben."""
    _isolate_privacy_files(
        tmp_path,
        monkeypatch,
        privacy={"sensitive_local_routing": True, "fallback_to_eu": True},
    )
    from backend import privacy_router as pr

    cfg = pr.get_privacy_config()
    assert cfg["zero_egress_strict"] is False
    assert cfg["fallback_to_eu"] is True


def test_shipped_privacy_routing_json_has_hard_defaults() -> None:
    """Die ausgelieferte Konfiguration darf sensibles Routing nicht abschalten."""
    from backend import privacy_router as pr

    with open(pr.PRIVACY_CFG_FILE, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["sensitive_local_routing"] is True
    assert data["fallback_to_eu"] is False


def test_d04_m3_audit_error_aborts_before_any_mutation(tmp_path: Any, monkeypatch: Any) -> None:
    """Schlägt der Ketten-Eintrag fehl, dürfen weder JSON noch settings.json verändert werden."""
    priv_file, settings_file = _isolate_privacy_files(
        tmp_path,
        monkeypatch,
        privacy={"local_llm_model": "original"},
        settings={"privacy": {"zero_egress": False}},
    )
    original_priv = json.loads(priv_file.read_text(encoding="utf-8"))
    original_settings = json.loads(settings_file.read_text(encoding="utf-8"))

    from backend import audit_log as al
    from backend import privacy_router as pr

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("audit chain unavailable")

    monkeypatch.setattr(al.chained_audit_log, "record_event", _boom)

    with pytest.raises(RuntimeError, match="fail-closed"):
        pr.save_privacy_config(
            {"zero_egress_strict": True, "local_llm_model": "mutated"}, operator="tester"
        )

    assert json.loads(priv_file.read_text(encoding="utf-8")) == original_priv
    assert json.loads(settings_file.read_text(encoding="utf-8")) == original_settings


def test_d04_m3_successful_save_writes_audit_first(tmp_path: Any, monkeypatch: Any) -> None:
    """Erfolgsfall: Ketten-Eintrag wird geschrieben und Konfiguration persistiert."""
    priv_file, _settings_file = _isolate_privacy_files(
        tmp_path, monkeypatch, privacy={"local_llm_model": "original"}
    )
    from backend import audit_log as al
    from backend import privacy_router as pr

    calls: list[dict[str, Any]] = []

    def _record(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(al.chained_audit_log, "record_event", _record)

    result = pr.save_privacy_config({"local_llm_model": "updated"}, operator="tester")
    assert result["local_llm_model"] == "updated"
    assert json.loads(priv_file.read_text(encoding="utf-8"))["local_llm_model"] == "updated"
    assert len(calls) == 1
    assert calls[0]["action"] == "privacy_routing_updated"
    assert calls[0]["agent_id"] == "tester"


def test_d04_h3_save_cannot_weaken_hardening_flags(tmp_path: Any, monkeypatch: Any) -> None:
    """Auch save_privacy_config() darf gehärtete Werte nicht mit false überschreiben."""
    priv_file, _settings_file = _isolate_privacy_files(
        tmp_path, monkeypatch, privacy={"local_llm_model": "original"}
    )
    from backend import audit_log as al
    from backend import privacy_router as pr

    monkeypatch.setattr(al.chained_audit_log, "record_event", lambda **_kw: None)

    pr.save_privacy_config(
        {
            "sensitive_local_routing": False,
            "hard_block_on_local_offline": False,
            "block_crm_erp_prefetch_on_cloud": False,
            "local_llm_model": "updated",
        }
    )
    saved = json.loads(priv_file.read_text(encoding="utf-8"))
    assert saved["sensitive_local_routing"] is True
    assert saved["hard_block_on_local_offline"] is True
    assert saved["block_crm_erp_prefetch_on_cloud"] is True


def test_d04_h2_masking_ignores_disable_switch(monkeypatch: Any) -> None:
    """secret_masking_enabled=false darf niemals Klartext mit count=0 liefern."""
    from backend import autonomy_settings as aus
    from backend import secret_masker as sm

    monkeypatch.setattr(aus, "get_module_config", lambda _name: {"secret_masking_enabled": False})
    key = "sk-" + ("a" * 32)
    masked, count = sm.mask_sensitive_text(f"api key: {key}")
    assert key not in masked
    assert "GESCHÜTZTER_API_KEY" in masked
    assert count >= 1


def test_d04_h2_masking_error_hard_fails(monkeypatch: Any) -> None:
    """Ein Maskierungsfehler muss hart abbrechen statt den Text unmaskiert zurückzugeben."""
    from backend import secret_masker as sm

    class _BrokenRe:
        @staticmethod
        def finditer(*_args: Any, **_kwargs: Any) -> None:
            raise ValueError("regex engine down")

        @staticmethod
        def sub(*_args: Any, **_kwargs: Any) -> None:
            raise ValueError("regex engine down")

    monkeypatch.setattr(sm, "re", _BrokenRe)
    with pytest.raises(RuntimeError, match="secret_masking_failed"):
        sm.mask_sensitive_text("TEST_KEY_" + ("a" * 32))


def test_d04_m5_finalize_never_returns_cleartext_on_masking_error(monkeypatch: Any) -> None:
    """finalize_llm_output() darf bei Masking-Fehler nicht den unmaskierten Text zurückgeben."""
    from backend import llm_kernel as lk
    from backend import secret_masker as sm

    key = "sk-" + ("c" * 32)

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("masker unavailable")

    monkeypatch.setattr(sm, "mask_sensitive_text", _boom)
    with pytest.raises(RuntimeError, match="llm_output_masking_failed"):
        lk.finalize_llm_output(f"secret {key}", session_id=None, is_local=False)


def test_finalize_llm_output_masks_secrets_normally() -> None:
    """Regression: im Normalfall maskiert die Output-Chain weiterhin zuverlässig."""
    from backend.llm_kernel import finalize_llm_output

    key = "sk-" + ("d" * 32)
    out = finalize_llm_output(f"key={key}")
    assert key not in out


def test_d04_m7_config_error_hard_blocks(monkeypatch: Any) -> None:
    """Config-Fehler → ZeroEgressBlockedError, niemals eine hartcodierte Allowlist."""
    from backend import autonomy_settings as aus
    from backend import egress_firewall as ef
    from backend.llm_egress_guard import ZeroEgressBlockedError

    def _boom(_name: str) -> dict[str, Any]:
        raise ValueError("config store down")

    monkeypatch.setattr(aus, "get_module_config", _boom)

    with pytest.raises(ZeroEgressBlockedError) as exc_info:
        ef._get_cfg()
    assert exc_info.value.error_code == "EGRESS_FIREWALL_CONFIG_UNAVAILABLE"

    with pytest.raises(ZeroEgressBlockedError):
        ef.egress_firewall.check_url("https://api.groq.com/v1")
