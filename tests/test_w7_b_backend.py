"""Welle W7, Partition B — Regressionstests für D01-M6/M7/M8 und D09-M7.

Alle Tests laufen im Produktivpfad: Router-Endpunkt, Synthese-Finalisierung,
Audit-Kryptopfad und die ausgelieferten Doku-/UI-Dateien. Keine Secrets,
keine echten Schlüssel (nur der von conftest gesetzte Test-Key).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# D01-M6 — api_save_services: kein Fake-Success ohne Schreibeffekt
# ---------------------------------------------------------------------------


class _FakeAppMain:
    """Provider-Double mit steuerbarem Writer/Reader und Schreibe-Effekt."""

    def __init__(
        self,
        *,
        writer: bool = True,
        reader: bool = True,
        persists: bool = True,
    ) -> None:
        self.saved: Optional[List[Dict[str, Any]]] = None
        self.persists = persists
        if writer:
            self.save_services = self._save_services
        if reader:
            self.load_services = self._load_services

    def _save_services(self, services: List[Dict[str, Any]]) -> None:
        self.saved = [dict(svc) for svc in services]

    def _load_services(self) -> List[Dict[str, Any]]:
        if self.persists and self.saved is not None:
            return [dict(svc) for svc in self.saved]
        return []


def _call_save_services(
    monkeypatch: pytest.MonkeyPatch,
    app_main: _FakeAppMain,
    entries: List[Dict[str, Any]],
) -> Dict[str, Any]:
    from archon.routers import docker_services as ds

    monkeypatch.setattr(ds, "_require_admin", lambda _request: None)
    monkeypatch.setattr(
        "archon.core.provider_registry.get_provider", lambda _name: app_main
    )
    payload = [ds.ServiceConfigEntry(**entry) for entry in entries]
    result = ds.api_save_services(Mock(), payload)
    assert isinstance(result, dict)
    return result


def test_missing_save_services_is_fail_closed_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider ohne Writer darf keinen Erfolg melden (D01-M6)."""
    app_main = _FakeAppMain(writer=False)

    with pytest.raises(HTTPException) as exc:
        _call_save_services(monkeypatch, app_main, [{"id": "svc-1"}])

    assert exc.value.status_code == 503
    assert "persistence unavailable" in exc.value.detail
    assert app_main.saved is None


def test_missing_load_services_blocks_success_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ohne Reader ist keine Verifikation des Schreibergebnisses möglich."""
    app_main = _FakeAppMain(reader=False)

    with pytest.raises(HTTPException) as exc:
        _call_save_services(monkeypatch, app_main, [{"id": "svc-1"}])

    assert exc.value.status_code == 503
    assert "verification unavailable" in exc.value.detail


def test_write_without_effect_is_not_success_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Writer läuft, Ruecklesen zeigt aber nichts: kein 'success' (D01-M6)."""
    app_main = _FakeAppMain(persists=False)

    with pytest.raises(HTTPException) as exc:
        _call_save_services(
            monkeypatch, app_main, [{"id": "svc-1"}, {"id": "svc-2"}]
        )

    assert exc.value.status_code == 500
    assert "mismatch" in exc.value.detail


def test_saved_services_are_verified_and_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Erfolg nur mit verifiziertem Ruecklesen; Zähler aus dem Effekt."""
    app_main = _FakeAppMain()

    result = _call_save_services(
        monkeypatch,
        app_main,
        [{"id": "svc-1", "active": True}, {"id": "svc-2"}],
    )

    assert result == {"status": "success", "saved": True, "count": 2}
    assert app_main.saved is not None
    assert [svc["id"] for svc in app_main.saved] == ["svc-1", "svc-2"]


# ---------------------------------------------------------------------------
# D01-M7 — Synthese-Finalisierung: kein leerer Ordnername als Fallback
# ---------------------------------------------------------------------------


def _finalize_kwargs(
    data: Dict[str, Any], tmp_path: Path, **overrides: Any
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {
        "dispatcher": Mock(),
        "load_mc": lambda: data,
        "save_mc": Mock(),
        "update_mc": Mock(),
        "ticker": Mock(),
        "paths": {
            "OBSIDIAN_VAULT_DIR": str(tmp_path / "vault"),
            "WORKSPACE_DIR": str(tmp_path / "workspace"),
        },
        "set_status": Mock(),
        "tg_ping": Mock(),
    }
    kwargs.update(overrides)
    return kwargs


@pytest.mark.asyncio
async def test_missing_project_folder_name_aborts_synthesis(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Import-Fehler des Namers muss die Finalisierung blockieren (D01-M7)."""
    from archon.core import orchestration as orch

    monkeypatch.setattr(orch, "PROJEKTE_DIR", str(tmp_path / "projekte"))
    # None in sys.modules lässt den Import zuverlässig scheitern.
    monkeypatch.setitem(sys.modules, "backend.post_task_pipeline", None)

    data: Dict[str, Any] = {
        "tasks": [{"id": "p1", "title": "Projekt", "status": "in_progress"}],
        "metrics": {},
        "audit_logs": [],
    }

    with pytest.raises(RuntimeError, match="project_folder_name unavailable"):
        await orch._finalize_synthesis_after_approval(
            "p1",
            "/fake/draft.md",
            "SYNTHESE",
            "Robert: OK",
            daten=data,
            **_finalize_kwargs(data, tmp_path),
        )

    assert data["tasks"][0].get("synthesis_finalized") is not True
    assert not list((tmp_path / "projekte").rglob("*.md"))


@pytest.mark.asyncio
async def test_failing_folder_namer_writes_no_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ein werfender Namer darf nicht still zu einem leeren Pfad werden."""
    from archon.core import orchestration as orch

    monkeypatch.setattr(orch, "PROJEKTE_DIR", str(tmp_path / "projekte"))

    def _boom(_ctx: Dict[str, Any]) -> str:
        raise RuntimeError("namer down")

    data: Dict[str, Any] = {
        "tasks": [{"id": "p1", "title": "Projekt", "status": "in_progress"}],
        "metrics": {},
        "audit_logs": [],
    }

    await orch._finalize_synthesis_after_approval(
        "p1",
        "/fake/draft.md",
        "SYNTHESE",
        "Robert: OK",
        daten=data,
        **_finalize_kwargs(data, tmp_path, folder_namer=_boom),
    )

    assert data["tasks"][0].get("status") != "completed"
    assert data["tasks"][0].get("synthesis_finalized") is not True
    assert not list((tmp_path / "projekte").rglob("*.md"))


def test_no_empty_folder_fallback_in_production_path() -> None:
    """Statisch: kein `def folder_namer(x): return ""` und kein `return ""` mehr."""
    src = (REPO_ROOT / "archon" / "core" / "orchestration.py").read_text(
        encoding="utf-8"
    )
    assert "def folder_namer(x):" not in src
    assert 'return ""' not in src
    assert src.count("project_folder_name unavailable") >= 2


# ---------------------------------------------------------------------------
# D01-M8 — Audit-Flags aus verify_integrity(), kein neuer Schalter
# ---------------------------------------------------------------------------


def test_dispatch_audit_flag_uses_real_verified_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Echter llm_dispatch-Block + verify_integrity() statt Konstante."""
    from backend import audit_log as al
    from backend import autonomy_settings as aus

    status = al._dispatch_audit_integrity()
    assert status["valid"] is True
    assert status["hmac_active"] is True
    assert str(status["probe_hash"]).startswith(al.HMAC_PREFIX)

    assert al._dispatch_audit_enforced() is True
    assert aus.is_sha256_dispatch_audit_enforced() is True


def test_dispatch_audit_flag_follows_failed_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Manipulations-/Key-Verlust muss das Flag auf False ziehen (D01-M8)."""
    from backend import audit_log as al
    from backend import autonomy_settings as aus

    monkeypatch.setattr(
        al,
        "_dispatch_audit_integrity",
        lambda: {
            "valid": False,
            "hmac_active": True,
            "reason": "manipulated_chain",
        },
    )

    assert al._dispatch_audit_enforced() is False
    assert aus.is_sha256_dispatch_audit_enforced() is False


def test_dispatch_audit_flag_false_without_hmac_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ohne HMAC-Key ist der Nachweis nicht führbar — fail-closed."""
    from backend import audit_log as al

    monkeypatch.delenv("ARCHON_AUDIT_HMAC_KEY", raising=False)
    monkeypatch.delenv("ARCHON_AUDIT_HMAC_EPOCHS", raising=False)

    assert al._dispatch_audit_enforced() is False


def test_settings_cannot_reintroduce_a_switch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ein `false` in settings.json bleibt wirkungslos; Flag kommt aus der Kette."""
    from backend import audit_log as al
    from backend import autonomy_settings as aus

    monkeypatch.setattr(aus, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setattr(
        al,
        "_dispatch_audit_integrity",
        lambda: {
            "valid": True,
            "hmac_active": True,
            "probe_hash": al.HMAC_PREFIX + "a" * 64,
        },
    )

    saved = aus.save_autonomy_settings(
        {"zero_egress_governance": {"sha256_dispatch_audit_enforced": False}}
    )
    assert saved["zero_egress_governance"]["sha256_dispatch_audit_enforced"] is True

    loaded = aus.load_all_settings()
    assert loaded["zero_egress_governance"]["sha256_dispatch_audit_enforced"] is True


# ---------------------------------------------------------------------------
# D09-M7 — Produktmodell-Korrektur: kein /content-studio als Produktfläche
# ---------------------------------------------------------------------------

_D09_M7_DOCS = (
    "CHANGELOG.md",
    "docs/SYSTEM_HANDBUCH.md",
    "docs/system/ROADMAP_2026.md",
    "docs/system/MULTI_AGENT_CONTENT_ROADMAP_2026_GUIDE.md",
)


def test_docs_no_longer_advertise_content_studio() -> None:
    """Die vier ausgelieferten Doku-Stellen beschreiben keine Produktfläche mehr."""
    for rel in _D09_M7_DOCS:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "/content-studio" not in text, rel
        assert "Produktmodell-Korrektur" in text or "Product-model correction" in text, rel


def test_legacy_alias_is_explicitly_commented() -> None:
    """Nur der kommentierte Redirect für alte Deeplinks bleibt erhalten."""
    html = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    alias_lines = [
        line for line in html.splitlines() if 'tabId === "content-studio"' in line
    ]
    assert len(alias_lines) == 1
    assert "LEGACY-ALIAS" in alias_lines[0]
    assert 'setTab("operations", "workflows");' in html


def test_ci_gate_guards_content_studio_with_whitelist() -> None:
    """CI muss Doku-Reste finden, den kommentierten Alias aber zulassen."""
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    assert "D09-M7" in ci
    assert "grep -rnF '/content-studio'" in ci
    assert "LEGACY-ALIAS" in ci
    assert "WHITELIST" in ci
