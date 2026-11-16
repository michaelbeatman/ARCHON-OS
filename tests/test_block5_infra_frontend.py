"""Regression tests for Audit #4 Block 5 (Frontend, i18n, Infra & Privacy Config)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_privacy_router_ollama_base_url_env_override(tmp_path, monkeypatch):
    import backend.privacy_router as pr

    cfg_file = tmp_path / "privacy_routing.json"
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(pr, "PRIVACY_CFG_FILE", str(cfg_file))
    monkeypatch.setattr(pr, "ROOT_SETTINGS_FILE", str(settings_file))
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")

    cfg = pr.get_privacy_config()
    assert cfg["local_llm_url"] == "http://host.docker.internal:11434/v1"
    check = pr.verify_zero_egress_config(cfg)
    assert check["zero_egress_verified"] is True
    assert check["local_egress_zone"] == "LOCAL_ON_PREM"
    assert check["issues"] == []

    # Explicit privacy_routing.json override takes precedence over OLLAMA_BASE_URL
    cfg_file.write_text(
        json.dumps({"local_llm_url": "http://127.0.0.1:11435/v1"}),
        encoding="utf-8",
    )
    cfg2 = pr.get_privacy_config()
    assert cfg2["local_llm_url"] == "http://127.0.0.1:11435/v1"


def test_hermes_webui_no_unrendered_placeholders_and_assets_exist():
    webui = REPO_ROOT / "static" / "hermes-webui"
    for name in ("index.html", "share.html", "sw.js", "manifest.json"):
        txt = (webui / name).read_text(encoding="utf-8")
        assert "__WEBUI_VERSION__" not in txt, f"Unrendered __WEBUI_VERSION__ in {name}"
        assert "__MAX_UPLOAD_BYTES__" not in txt, f"Unrendered __MAX_UPLOAD_BYTES__ in {name}"
        assert "__CSRF_TOKEN_JSON__" not in txt, f"Unrendered __CSRF_TOKEN_JSON__ in {name}"
        assert "favicon-32.png" not in txt
        assert "favicon-192.png" not in txt
        assert "apple-touch-icon.png" not in txt

    sw_txt = (webui / "sw.js").read_text(encoding="utf-8")
    for m in re.finditer(r"['\"](\./[^'\"]+)['\"]", sw_txt):
        rel = m.group(1).split("?")[0].lstrip("./")
        assert (webui / rel).is_file(), f"Missing sw.js asset on disk: {rel}"

    msgs_txt = (webui / "messages.js").read_text(encoding="utf-8")
    assert "static/favicon-192.png" not in msgs_txt
    assert "static/favicon-32.png" not in msgs_txt


def test_modal_a11y_uses_debounced_observer_and_aria_sync():
    txt = (REPO_ROOT / "static" / "js" / "modal_a11y.js").read_text(encoding="utf-8")
    assert "setTimeout(" in txt
    assert "new MutationObserver(scheduleSync)" in txt
    assert 'aria-modal' in txt
    assert 'aria-hidden' in txt


def test_no_duplicate_global_js_overrides_in_frontend():
    idx = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert len(re.findall(r"function fallbackCopyText\s*\(", idx)) == 1
    assert 'if (typeof window.setOperationsTab !== "function")' in idx

    ap = (REPO_ROOT / "static" / "js" / "approval_policies_controller.js").read_text(encoding="utf-8")
    assert "function escapeHtml(" not in ap

    ps = (REPO_ROOT / "static" / "js" / "prompt_studio.js").read_text(encoding="utf-8")
    assert "function resetRolesToDefault(" not in ps
    assert "function loadRolesFromServer(" not in ps
    assert "function loadModelsFromServer(" not in ps
    assert "function loadVaultFiles(" in ps

    wb = (REPO_ROOT / "static" / "js" / "wissensbibliothek.js").read_text(encoding="utf-8")
    assert "function loadVaultFiles(" not in wb

    cc = (REPO_ROOT / "static" / "js" / "corporate_controller.js").read_text(encoding="utf-8")
    assert "window.setBoardroomTab" not in cc
    assert "window.setSettingsTab" not in cc

    agp = (REPO_ROOT / "static" / "js" / "agent_profiles.js").read_text(encoding="utf-8")
    assert "window.openPriceCatalogForAgentTab" not in agp
