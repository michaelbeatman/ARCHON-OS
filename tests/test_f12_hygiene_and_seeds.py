"""F12 (D09): Router-Schemas, Body(default_factory), GoBD-Seed-Gate und Doku-Versions-CI-Gate."""
from __future__ import annotations

import inspect
import json
from pathlib import Path

from archon.routers.autonomy_settings import api_run_eval_regression_suite
from archon.routers.erp import ErpSyncPocketbaseRequest
from archon.routers.gateway import GatewayConfigRequest
from archon.routers.hermes_ops import api_hermes_memory_purge
from archon.routers.updater import api_hermes_update_apply
from scripts.check_doc_version_sync import check_doc_version_sync

ROOT = Path(__file__).resolve().parents[1]


def test_f12_gateway_and_erp_sync_schemas_ignore_unknown_fields():
    gw = GatewayConfigRequest.model_validate(
        {"idle_timeout_minutes": 30, "autostart": {"a": True}, "injected_unknown": "x"}
    )
    gw_dump = gw.model_dump()
    assert gw_dump["idle_timeout_minutes"] == 30
    assert "injected_unknown" not in gw_dump

    erp = ErpSyncPocketbaseRequest.model_validate(
        {"company_id": "default", "pocketbase_url": "http://127.0.0.1:8090", "injected": 123}
    )
    erp_dump = erp.model_dump()
    assert erp_dump["company_id"] == "default"
    assert "injected" not in erp_dump


def test_f12_body_defaults_use_default_factory_without_shared_mutation():
    for fn, param_name in (
        (api_run_eval_regression_suite, "payload"),
        (api_hermes_memory_purge, "purge_options"),
        (api_hermes_update_apply, "payload"),
    ):
        param = inspect.signature(fn).parameters[param_name]
        body_info = param.default
        assert body_info.default_factory is not None, f"{fn.__name__}.{param_name} ohne default_factory"
        first = body_info.default_factory()
        second = body_info.default_factory()
        assert first is not second
        first_dict = first.model_dump() if hasattr(first, "model_dump") else dict(first)
        first_dict["mutated"] = True
        second_dict = second.model_dump() if hasattr(second, "model_dump") else dict(second)
        assert "mutated" not in second_dict


def test_f12_erp_primary_tenant_has_zero_fictive_seeds_outside_demo_mode(tmp_path, monkeypatch):
    import backend.erp_manager as erp_mod

    monkeypatch.delenv("ARCHON_DEMO_MODE", raising=False)
    monkeypatch.setattr(erp_mod, "TENANTS_BASE_DIR", str(tmp_path / "prod_erp"))
    mgr = erp_mod.ERPManager()
    overview = mgr.get_tenant_overview("default")
    count = overview["counts"]["entities"]
    assert count == 0, f"Im Nicht-Demo-Modus duerfen keine fiktiven GoBD-Seeds angelegt werden (count={count})"

    # Gegenprobe: im expliziten ARCHON_DEMO_MODE=true werden Demo-Seeds angelegt
    monkeypatch.setenv("ARCHON_DEMO_MODE", "true")
    monkeypatch.setattr(erp_mod, "TENANTS_BASE_DIR", str(tmp_path / "demo_erp"))
    mgr_demo = erp_mod.ERPManager()
    demo_count = mgr_demo.get_tenant_overview("default")["counts"]["entities"]
    assert demo_count >= 1


def test_f12_doc_version_sync_gate_passes_on_repo_and_fails_on_drift(tmp_path):
    version, mismatches = check_doc_version_sync(ROOT)
    assert version
    assert mismatches == [], mismatches

    # Negativprobe: veraltete Version in README.md muss erkannt werden
    (tmp_path / "config").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "config" / "version.json").write_text(
        json.dumps({"version": "v9.9.9"}), encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("Archon v0.0.1", encoding="utf-8")
    (tmp_path / "README.de.md").write_text("Archon v9.9.9", encoding="utf-8")
    (tmp_path / "docs" / "SYSTEM_HANDBUCH.md").write_text("Archon v9.9.9", encoding="utf-8")
    _, drift = check_doc_version_sync(tmp_path)
    assert any("README.md" in m for m in drift)
