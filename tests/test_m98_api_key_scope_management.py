"""M98: Vereinheitlichte API-Key- und Provider-Key-Verwaltung.

Die Tests rufen die Router-Funktionen direkt auf (kein App-Lifespan, keine
Produktions-DB). RBAC-Zaun und api_provider werden gezielt monkeypatcht.
"""

import json
from typing import Any, Callable, Dict

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from archon.routers import llm_providers, operations_keys
from backend import api_key_manager as akm
from backend.audit_log import chained_audit_log
from backend.credential_masking import mask_secret

_SECRETS: Dict[str, str] = {
    "OPENROUTER_API_KEY": "sk-" + "or-abcdefghijklmnopqrst",
    "GEMINI_API_KEY": "AIza-google-secret-1234567890",
    "OMNIROUTE_API_KEY": "omni-gateway-secret-abcdefgh",
    "GROQ_API_KEY": "gsk-groq-secret-1234567890",
    "OPENAI_API_KEY": "sk-" + "openai-secret-1234567890",
}


def _request(method: str, path: str) -> Request:
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "app": None,
    })


@pytest.fixture
def allow_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ersetzt die injizierte Admin-Pruefung durch einen Erlaubnispfad."""
    from archon.routers import _rbac

    monkeypatch.setattr(_rbac, "_checker", lambda _r: None)
    monkeypatch.setattr(
        operations_keys, "require_session_actor", lambda _r: "test-actor"
    )
    monkeypatch.setattr(
        llm_providers, "require_session_actor", lambda _r: "test-actor"
    )


@pytest.fixture
def deny_viewer(monkeypatch: pytest.MonkeyPatch) -> None:
    from archon.routers import _rbac

    def _deny(_r: Any) -> None:
        raise HTTPException(
            status_code=403, detail="Nur Administratoren duerfen schreibend zugreifen."
        )

    monkeypatch.setattr(_rbac, "_checker", _deny)


@pytest.fixture
def isolated_manager(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> akm.ApiKeyManager:
    """Eigene SQLite-DB, keine globalen Audit-Schreibvorgaenge."""
    monkeypatch.setenv("ARCHON_API_KEY_PEPPER", "m98-test-pepper-not-for-production")
    monkeypatch.setattr(
        akm.ApiKeyManager,
        "_emit_global_audit",
        staticmethod(lambda *_a, **_k: {"audit_status": "ok"}),
    )
    manager = akm.ApiKeyManager(str(tmp_path / "m98_api_keys.db"))
    monkeypatch.setattr(akm, "api_key_manager", manager)
    return manager


def test_mask_secret_keeps_at_most_four_edge_chars() -> None:
    secret = "sk-" + "or-abcdefghijklmnopqrstuvwxyz"
    masked = mask_secret(secret)
    assert masked == "sk-o…wxyz"
    assert secret not in masked
    assert secret not in json.dumps({"key_masked": masked})
    assert secret not in str({"key_masked": masked})

    for short in ("a", "abcd", "abcdefgh", "abcdefghij"):
        result = mask_secret(short)
        assert result == "••••••••"
        assert short not in result
    assert mask_secret("") == ""
    assert mask_secret(None) == ""


def test_mask_secret_does_not_leak_via_str_exception() -> None:
    class Exploding:
        def __str__(self) -> str:
            raise RuntimeError("geheimer-wert-darf-nicht-erscheinen")

    result = mask_secret(Exploding())
    assert result == "••••••••"
    assert "geheimer-wert" not in result


@pytest.mark.parametrize(
    "call",
    [
        lambda: operations_keys.api_list_key_scopes(
            _request("GET", "/api/operations/keys/scopes")
        ),
        lambda: llm_providers.api_list_provider_keys(
            _request("GET", "/api/provider-keys")
        ),
    ],
)
def test_viewer_is_denied_on_new_read_endpoints(
    call: Callable[[], Any], deny_viewer: None
) -> None:
    with pytest.raises(HTTPException) as exc:
        call()
    assert exc.value.status_code == 403


def test_anonymous_is_denied_when_admin_guard_is_not_wired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from archon.routers import _rbac

    monkeypatch.setattr(_rbac, "_checker", None)
    with pytest.raises(HTTPException) as exc:
        operations_keys.api_list_key_scopes(
            _request("GET", "/api/operations/keys/scopes")
        )
    assert exc.value.status_code == 503


def test_scope_catalog_contains_exactly_four_scopes(
    allow_admin: None, isolated_manager: akm.ApiKeyManager
) -> None:
    result = operations_keys.api_list_key_scopes(
        _request("GET", "/api/operations/keys/scopes")
    )
    scopes = result["scopes"]
    assert [entry["scope"] for entry in scopes] == [
        "read_only", "kanban_rw", "agent_execute", "admin_full",
    ]
    assert scopes == sorted(scopes, key=lambda e: list(akm.VALID_SCOPES).index(e["scope"]))
    assert all(entry["description"] for entry in scopes)


def _patch_provider_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    import api_provider

    monkeypatch.setattr(
        api_provider,
        "load_provider_catalog",
        lambda: {
            "openrouter": {"env": ["OPENROUTER_API_KEY"]},
            "google": {"env": ["GEMINI_API_KEY", "GOOGLE_API_KEY"]},
            "omniroute": {"env": ["OMNIROUTE_API_KEY"]},
            "groq": {"env": ["GROQ_API_KEY"]},
            "openai": {"env": ["OPENAI_API_KEY"]},
        },
    )
    monkeypatch.setattr(api_provider, "collect_keys", lambda: dict(_SECRETS))
    monkeypatch.setattr(
        api_provider,
        "read_active_config",
        lambda: {
            "provider": "omniroute",
            "model": "auto/best-coding",
            "base_url": "http://omniroute:20128/v1",
        },
    )


def test_provider_overview_returns_masks_only(
    allow_admin: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_provider_catalog(monkeypatch)
    result = llm_providers.api_list_provider_keys(
        _request("GET", "/api/provider-keys")
    )
    entries = result["provider_keys"]
    assert {entry["provider"] for entry in entries} == {
        "openrouter", "google", "omniroute", "groq", "openai",
    }
    payload = json.dumps(result, ensure_ascii=False)
    for secret in _SECRETS.values():
        assert secret not in payload
    for entry in entries:
        assert entry["has_key"] is True
        assert entry["key_masked"] and entry["key_masked"] != secret
        assert "key_value" not in entry
        assert "key_hash" not in entry
    omni = next(e for e in entries if e["provider"] == "omniroute")
    assert omni["base_url"] == "http://omniroute:20128/v1"
    # key_env ist der Env-NAME, nie der Wert.
    assert _SECRETS["OMNIROUTE_API_KEY"] not in json.dumps(omni)


def test_rotation_preserves_metadata_is_one_time_and_audited(
    allow_admin: None, isolated_manager: akm.ApiKeyManager
) -> None:
    created = isolated_manager.create_key(
        name="n8n Automation",
        scopes=["read_only", "kanban_rw"],
        rate_limit_rpm=7,
        rate_limit_rpd=99,
        created_by="test-actor",
    )
    key_id = created["key_id"]
    old_token = created["raw_token"]

    result = operations_keys.api_rotate_key(
        _request("POST", f"/api/operations/keys/{key_id}/rotate"), key_id
    )
    rotated = result["result"]
    assert rotated["key_id"] == key_id
    assert rotated["name"] == "n8n Automation"
    assert rotated["scopes"] == ["read_only", "kanban_rw"]
    assert rotated["rate_limit_rpm"] == 7
    assert rotated["rate_limit_rpd"] == 99
    assert rotated["raw_token"] != old_token
    assert rotated["key_masked"] == mask_secret(rotated["raw_token"])

    assert not isolated_manager.validate_and_consume(old_token, "read_only")[0]
    assert isolated_manager.validate_and_consume(rotated["raw_token"], "read_only")[0]

    listing = json.dumps(isolated_manager.list_keys())
    assert rotated["raw_token"] not in listing
    trail = isolated_manager.get_audit_trail()
    assert any(e["action"] == "KEY_ROTATED" for e in trail)
    audit_json = json.dumps(trail)
    assert rotated["raw_token"] not in audit_json
    assert old_token not in audit_json


def test_revoke_changes_only_status_and_audits(
    allow_admin: None, isolated_manager: akm.ApiKeyManager
) -> None:
    created = isolated_manager.create_key(
        name="Telegram Bot", scopes=["agent_execute"], created_by="test-actor"
    )
    key_id = created["key_id"]
    result = operations_keys.api_revoke_key(
        _request("POST", f"/api/operations/keys/{key_id}/revoke"), key_id
    )
    assert result["status"] == "success"
    item = next(k for k in isolated_manager.list_keys() if k["key_id"] == key_id)
    assert item["is_active"] is False
    assert item["name"] == "Telegram Bot"
    assert item["scopes"] == ["agent_execute"]
    assert any(e["action"] == "KEY_REVOKED" for e in isolated_manager.get_audit_trail())


def test_rotation_audit_failure_maps_to_503(
    allow_admin: None,
    isolated_manager: akm.ApiKeyManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail(*_args: Any, **_kwargs: Any) -> Any:
        raise akm.AuditWriteFailedError("api_key_rotate")

    monkeypatch.setattr(isolated_manager, "rotate_key", _fail)
    with pytest.raises(HTTPException) as exc:
        operations_keys.api_rotate_key(
            _request("POST", "/api/operations/keys/key_unknown/rotate"), "key_unknown"
        )
    assert exc.value.status_code == 503


def test_provider_set_and_revoke_use_allowlist_and_invalidate_cache(
    allow_admin: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    import api_provider

    secret = _SECRETS["OPENROUTER_API_KEY"]
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setattr(api_provider, "ENV_PATH", str(tmp_path / ".env"))
    _patch_provider_catalog(monkeypatch)

    writes: list[tuple[str, str, str]] = []
    invalidations: list[int] = []

    def _set_env(path: str, key: str, value: str) -> bool:
        writes.append((path, key, value))
        return True

    monkeypatch.setattr(api_provider, "set_env_value", _set_env)
    monkeypatch.setattr(
        api_provider, "invalidate_key_cache", lambda: invalidations.append(1)
    )
    monkeypatch.setattr(
        api_provider, "deploy_keys", lambda dry_run=False: {"status": "ok"}
    )

    set_result = llm_providers.api_set_provider_key(
        _request("POST", "/api/provider-keys/openrouter"),
        "openrouter",
        llm_providers.ProviderKeySetRequest(key_value=secret),
    )
    assert set_result["key_masked"] == mask_secret(secret)
    assert secret not in json.dumps(set_result)
    assert any(key == "OPENROUTER_API_KEY" and value == secret for _, key, value in writes)
    assert invalidations

    before = len(invalidations)
    revoke_result = llm_providers.api_revoke_provider_key(
        _request("DELETE", "/api/provider-keys/openrouter"), "openrouter"
    )
    assert revoke_result["has_key"] is False
    assert any(key == "OPENROUTER_API_KEY" and value == "" for _, key, value in writes)
    assert len(invalidations) > before


def test_omniroute_scope_control_persists_scope_model_and_url(
    allow_admin: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    import api_provider

    monkeypatch.setenv("OMNIROUTE_SCOPE", "")
    monkeypatch.setattr(api_provider, "ENV_PATH", str(tmp_path / ".env"))
    writes: list[tuple[str, str, str]] = []

    def _set_env(path: str, key: str, value: str) -> bool:
        writes.append((path, key, value))
        return True

    monkeypatch.setattr(api_provider, "set_env_value", _set_env)
    monkeypatch.setattr(
        api_provider,
        "set_provider_model",
        lambda provider, model: {"provider": provider, "model": model, "ok": True},
    )
    monkeypatch.setattr(
        api_provider, "_set_model_block", lambda *args: True
    )

    result = llm_providers.api_set_omniroute_scope(
        _request("POST", "/api/provider-keys/omniroute/scope"),
        llm_providers.OmniRouteScopeRequest(
            scope="best_coding", model=None, base_url="http://omniroute:20128/v1"
        ),
    )
    assert result["scope"] == "best_coding"
    assert result["model"] == "auto/best-coding"
    assert result["base_url"] == "http://omniroute:20128/v1"
    assert any(key == "OMNIROUTE_SCOPE" for _, key, _ in writes)

    with pytest.raises(HTTPException) as exc:
        llm_providers.api_set_omniroute_scope(
            _request("POST", "/api/provider-keys/omniroute/scope"),
            llm_providers.OmniRouteScopeRequest(
                scope="best_coding", model=None, base_url="http://user:pass@evil.example/v1"
            ),
        )
    assert exc.value.status_code == 400


def test_chained_audit_log_import_stays_available() -> None:
    """Die zentrale Kette bleibt unangetastet (nur Import-/API-Pruefung)."""
    assert callable(chained_audit_log.record_event)


def test_core_dispatcher_omniroute_key_hot_rotation_without_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core_dispatcher

    monkeypatch.setenv("OMNIROUTE_API_KEY", "omni_initial_123456")
    res_init = core_dispatcher.refresh_cached_provider_keys()
    assert res_init["omniroute_key_present"] is True
    assert core_dispatcher._get_omniroute_api_key() == "omni_initial_123456"

    # Rotation im laufenden Prozess (ohne Neustart)
    monkeypatch.setenv("OMNIROUTE_API_KEY", "omni_rotated_999999")
    core_dispatcher.refresh_cached_provider_keys()
    assert core_dispatcher.OMNIROUTE_API_KEY == "omni_rotated_999999"
    assert core_dispatcher._get_omniroute_api_key() == "omni_rotated_999999"

    # Revoke im laufenden Prozess (kein veralteter Cache-Key bleibt haengen)
    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    monkeypatch.setattr("api_provider.collect_keys", lambda: {})
    res_rev = core_dispatcher.refresh_cached_provider_keys()
    assert res_rev["omniroute_key_present"] is False
    assert core_dispatcher.OMNIROUTE_API_KEY == ""
    assert core_dispatcher._get_omniroute_api_key() == ""

