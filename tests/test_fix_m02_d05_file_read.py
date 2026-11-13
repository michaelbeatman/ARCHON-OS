"""Cluster 2 — F3/M-02/D-05: beliebiges Datei-Lesen unter ``/app`` und ``/opt/data``.

Rot gegen HEAD (909421d6):

* ``views_core.py:432`` (``/api/views/showroom/file-content``) prueft
  ``startswith("/app")`` — das erlaubt den gesamten Code-Baum inklusive
  ``.env.archon`` und ``data/.archon_service_token``.
* ``views_core.py:497`` (``/showroom/export-desktop``) nimmt als einziger
  Handler der Datei kein ``Request`` entgegen und hat keinen Rollenzaun.
* ``views_core.py:146`` (``/inbox/file``) oeffnet den Pfad roh.
* ``main.py:8589`` (``/api/documents/parse``) parst jeden angegebenen Pfad.

Zugesagt wird: Rollenzaun als erste Anweisung, Jail ausschliesslich auf die
fachlich zustaendige Wurzel (kein ``/app``, kein ``/opt/data``).
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from archon_security_support import ADMIN, OPERATOR, import_main, make_request


@pytest.fixture()
def vault_and_session(monkeypatch, tmp_path):
    """Temp-Vault + Temp-raw_docs; liefert (views_core, vault, raw_docs)."""
    import views_core

    vault = tmp_path / "vault"
    vault.mkdir()
    raw_docs = tmp_path / "raw_docs"
    raw_docs.mkdir()
    monkeypatch.setattr(views_core, "resolve_obsidian_vault_dir", lambda: str(vault))
    return views_core, vault, raw_docs


def _session(monkeypatch, main, user):
    monkeypatch.setattr(main.auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(main.auth_service, "verify_session", lambda tok: dict(user))


# --------------------------------------------------------------------------
# Showroom-Vorschau
# --------------------------------------------------------------------------

def test_showroom_file_content_blocks_operator(monkeypatch, vault_and_session):
    main = import_main()
    _session(monkeypatch, main, OPERATOR)
    views_core, vault, _ = vault_and_session
    (vault / "bericht.md").write_text("# ok", encoding="utf-8")
    request = make_request("/api/views/showroom/file-content", "GET", token="tok_op")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(views_core.get_showroom_file_content(request, path=str(vault / "bericht.md")))

    assert exc.value.status_code == 403


@pytest.mark.parametrize("target", ["/app/.env.archon", "/opt/data/.env", "/etc/passwd"])
def test_showroom_file_content_jails_to_vault(monkeypatch, vault_and_session, target):
    main = import_main()
    _session(monkeypatch, main, ADMIN)
    views_core, _vault, _ = vault_and_session
    request = make_request("/api/views/showroom/file-content", "GET", token="tok_admin")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(views_core.get_showroom_file_content(request, path=target))

    assert exc.value.status_code in (403, 404)


def test_showroom_file_content_reads_inside_vault(monkeypatch, vault_and_session):
    main = import_main()
    _session(monkeypatch, main, ADMIN)
    views_core, vault, _ = vault_and_session
    note = vault / "bericht.md"
    note.write_text("# Hallo", encoding="utf-8")
    request = make_request("/api/views/showroom/file-content", "GET", token="tok_admin")

    result = asyncio.run(views_core.get_showroom_file_content(request, path=str(note)))

    assert "Hallo" in result["content"]


# --------------------------------------------------------------------------
# Showroom-Export auf den Desktop
# --------------------------------------------------------------------------

def test_export_desktop_blocks_operator(monkeypatch, vault_and_session):
    main = import_main()
    _session(monkeypatch, main, OPERATOR)
    views_core, vault, _ = vault_and_session
    payload = views_core.DesktopExportPayload(filepath=str(vault / "bericht.md"))
    request = make_request("/api/views/showroom/export-desktop", "POST", token="tok_op")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(views_core.export_showroom_to_desktop(request, payload))

    assert exc.value.status_code == 403


def test_export_desktop_jails_to_vault(monkeypatch, vault_and_session, tmp_path):
    main = import_main()
    _session(monkeypatch, main, ADMIN)
    views_core, _vault, _ = vault_and_session
    outside = tmp_path / "aussen.md"
    outside.write_text("geheim", encoding="utf-8")
    payload = views_core.DesktopExportPayload(filepath=str(outside))
    request = make_request("/api/views/showroom/export-desktop", "POST", token="tok_admin")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(views_core.export_showroom_to_desktop(request, payload))

    assert exc.value.status_code in (403, 404)


# --------------------------------------------------------------------------
# Inbox-Datei
# --------------------------------------------------------------------------

def test_inbox_file_blocks_operator(monkeypatch, vault_and_session, tmp_path):
    main = import_main()
    _session(monkeypatch, main, OPERATOR)
    views_core, _vault, _ = vault_and_session
    secret = tmp_path / "geheim.txt"
    secret.write_text("x", encoding="utf-8")
    request = make_request("/api/views/inbox/file", "GET", token="tok_op")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(views_core.get_inbox_file_content(request, path=str(secret)))

    assert exc.value.status_code == 403


def test_inbox_file_rejects_path_outside_inbox(monkeypatch, vault_and_session, tmp_path):
    main = import_main()
    _session(monkeypatch, main, ADMIN)
    views_core, _vault, _ = vault_and_session
    email_dir = tmp_path / "inbox" / "emails"
    email_dir.mkdir(parents=True)
    monkeypatch.setattr(views_core, "get_inbox_email_dir", lambda: str(email_dir))
    monkeypatch.setattr(views_core, "get_inbox_telegram_dir", lambda: str(tmp_path / "inbox" / "telegram"))
    secret = tmp_path / "geheim.txt"
    secret.write_text("x", encoding="utf-8")
    request = make_request("/api/views/inbox/file", "GET", token="tok_admin")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(views_core.get_inbox_file_content(request, path=str(secret)))

    assert exc.value.status_code in (403, 404)


# --------------------------------------------------------------------------
# D-05 — /api/documents/parse
# --------------------------------------------------------------------------

def test_document_parse_blocks_operator(monkeypatch):
    main = import_main()
    _session(monkeypatch, main, OPERATOR)
    request = make_request("/api/documents/parse", "POST", token="tok_op")

    with pytest.raises(HTTPException) as exc:
        main.api_parse_document(request, {"filepath": "/etc/passwd"})

    assert exc.value.status_code == 403


@pytest.mark.parametrize("target", ["/app/.env.archon", "/opt/data/.env", "/etc/passwd"])
def test_document_parse_jails_to_raw_docs(monkeypatch, tmp_path, target):
    main = import_main()
    _session(monkeypatch, main, ADMIN)
    import utils.batch_library_importer as importer

    raw_docs = tmp_path / "raw_docs"
    raw_docs.mkdir()
    monkeypatch.setattr(importer, "resolve_raw_docs_dir", lambda: str(raw_docs))
    request = make_request("/api/documents/parse", "POST", token="tok_admin")

    with pytest.raises(HTTPException) as exc:
        main.api_parse_document(request, {"filepath": target})

    assert exc.value.status_code in (403, 404)
