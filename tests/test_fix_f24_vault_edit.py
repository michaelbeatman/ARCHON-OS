"""Cluster 2 — F24: ``/api/vault/edit`` schreibt ohne Rollenzaun in Agenten-Home.

Rot gegen HEAD (909421d6): der Handler (``main.py:8712``) hat weder
``require_admin_or_503`` noch eine ``startswith(vault_root)``-Pruefung; der
Aufruf ``safe_path(path, allow_write=True)`` zieht die Default-Wurzeln
(``/opt/data``, ``~/.hermes``, ``/app``) mit, also ist ``/opt/data/.env``
beschreibbar. Die Schwester-Route ``DELETE /api/vault`` prueft beides korrekt
(``main.py:8727-8745``).
"""

from __future__ import annotations

import os

import pytest
from fastapi import HTTPException

from archon_security_support import ADMIN, OPERATOR, import_main, make_request


@pytest.fixture()
def vault_root(monkeypatch, tmp_path):
    main = import_main()
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(main, "OBSIDIAN_VAULT_DIR", str(vault))
    monkeypatch.setattr(main, "_VAULT_FILES_CACHE", {"ts": 0.0, "data": None})
    return main, vault


def _session(monkeypatch, main, user):
    monkeypatch.setattr(main.auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(main.auth_service, "verify_session", lambda tok: dict(user))


def test_vault_edit_blocks_operator(monkeypatch, vault_root):
    main, vault = vault_root
    _session(monkeypatch, main, OPERATOR)
    target = vault / "notiz.md"
    request = make_request("/api/vault/edit", "POST", token="tok_op")

    with pytest.raises(HTTPException) as exc:
        main.api_edit_vault_file_direct(request, {"path": str(target), "content": "x"})

    assert exc.value.status_code == 403
    assert not target.exists()


@pytest.mark.parametrize("target", ["/opt/data/.env", "/opt/data/settings.json",
                                    "~/.hermes/config.yaml"])
def test_vault_edit_rejects_paths_outside_vault(monkeypatch, vault_root, target):
    main, _vault = vault_root
    _session(monkeypatch, main, ADMIN)
    request = make_request("/api/vault/edit", "POST", token="tok_admin")
    resolved = os.path.expanduser(target)

    with pytest.raises(HTTPException) as exc:
        main.api_edit_vault_file_direct(request, {"path": resolved, "content": "pwned"})

    assert exc.value.status_code == 403


def test_vault_edit_rejects_traversal_out_of_vault(monkeypatch, vault_root, tmp_path):
    main, vault = vault_root
    _session(monkeypatch, main, ADMIN)
    escaped = tmp_path / "aussen.md"
    request = make_request("/api/vault/edit", "POST", token="tok_admin")

    with pytest.raises(HTTPException) as exc:
        main.api_edit_vault_file_direct(
            request, {"path": str(vault / ".." / "aussen.md"), "content": "pwned"}
        )

    assert exc.value.status_code == 403
    assert not escaped.exists()


def test_vault_edit_writes_inside_vault(monkeypatch, vault_root):
    main, vault = vault_root
    _session(monkeypatch, main, ADMIN)
    target = vault / "notiz.md"
    request = make_request("/api/vault/edit", "POST", token="tok_admin")

    result = main.api_edit_vault_file_direct(request, {"path": str(target), "content": "# neu"})

    assert result["status"] == "success"
    assert target.read_text(encoding="utf-8") == "# neu"


# --------------------------------------------------------------------------
# Gleiche Klasse: GET /api/vault/file las mit denselben Default-Wurzeln
# --------------------------------------------------------------------------

@pytest.mark.parametrize("target", ["/opt/data/.env", "/app/data/settings.json",
                                    "~/.hermes/config.yaml"])
def test_vault_read_rejects_paths_outside_vault(monkeypatch, vault_root, target):
    main, _vault = vault_root

    with pytest.raises(HTTPException) as exc:
        main.api_read_vault_file_direct(os.path.expanduser(target))

    assert exc.value.status_code == 403


def test_vault_read_serves_inside_vault(monkeypatch, vault_root):
    main, vault = vault_root
    note = vault / "notiz.md"
    note.write_text("# drin", encoding="utf-8")

    result = main.api_read_vault_file_direct(str(note))

    assert result["status"] == "success"
    assert result["content"] == "# drin"
