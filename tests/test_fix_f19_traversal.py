"""Cluster 2 — F19/R-03/M-03/Z-01: ungefilterter ``filename``/``title`` -> Traversal.

Rot gegen HEAD (909421d6):

* ``utils/notebook_engine.py:181`` schreibt ``os.path.join(raw_dir, filename)``
  ohne ``basename`` und ohne Jail — ``../../../x`` schreibt ausserhalb.
* ``core_skills_engine.py:137`` baut den Dateinamen aus dem Titel und ersetzt
  nur Leerzeichen und ``/``; ``..`` bleibt stehen.
* ``archon/routers/skills.py:486`` (``obsidian/write``) und der Notebook-Upload
  (``main.py:2456``) haben keinen Rollenzaun.

Zugesagt wird: Angreifer-Bytes landen nie ausserhalb der erlaubten Wurzel, und
beide Handler sperren Nicht-Admins, bevor Fachcode laeuft.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from fastapi import HTTPException

from archon_security_support import ADMIN, OPERATOR, import_main, make_request


# --------------------------------------------------------------------------
# F19/M-03 — Notebook-Upload
# --------------------------------------------------------------------------

@pytest.fixture()
def notebook_env(monkeypatch, tmp_path):
    """Temp-Wurzel fuer Rohdokumente und Vault; Notebook-Store gestubbt."""
    import utils.notebook_engine as engine

    raw_dir = tmp_path / "raw_docs"
    raw_dir.mkdir()
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    (vault_dir / "02_Wissensbibliothek").mkdir()

    monkeypatch.setattr(engine, "resolve_raw_docs_dir", lambda: str(raw_dir))
    monkeypatch.setattr(engine, "resolve_vault_path", lambda: str(vault_dir))
    monkeypatch.setattr(engine, "load_notebooks_data", lambda: {"nb1": {"sources": []}})
    monkeypatch.setattr(engine, "save_notebooks_data", lambda data: None)
    return engine, raw_dir


@pytest.mark.parametrize("filename", [
    "../../../evil.txt",
    "..\\..\\evil.txt",
    "/etc/evil.txt",
    "....//....//evil.txt",
])
def test_notebook_upload_never_writes_outside_raw_dir(notebook_env, tmp_path, filename):
    engine, raw_dir = notebook_env
    escaped = os.path.realpath(os.path.join(str(raw_dir), filename))

    try:
        engine.add_source_file("nb1", b"payload", filename)
    except (ValueError, PermissionError):
        pass  # Ablehnung ist ebenfalls ein gueltiges Ergebnis

    leaked = os.path.exists(escaped) and not escaped.startswith(str(raw_dir.resolve()) + os.sep)
    if leaked:
        os.remove(escaped)
    assert not leaked, f"Datei ausserhalb von raw_docs geschrieben: {escaped}"


def test_notebook_upload_accepts_plain_filename(notebook_env):
    engine, raw_dir = notebook_env

    result = engine.add_source_file("nb1", b"Inhalt", "bericht.txt")

    assert result["status"] == "success"
    assert os.path.isfile(os.path.join(str(raw_dir), "bericht.txt"))


def test_notebook_upload_route_blocks_operator(monkeypatch):
    main = import_main()
    monkeypatch.setattr(main.auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(main.auth_service, "verify_session", lambda tok: dict(OPERATOR))
    request = make_request("/api/v1/notebooks/nb1/sources/upload", "POST", token="tok_op")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.api_upload_notebook_source("nb1", request))

    assert exc.value.status_code == 403


# --------------------------------------------------------------------------
# Z-01 — Obsidian-Write
# --------------------------------------------------------------------------

def test_obsidian_note_title_cannot_escape_vault(tmp_path):
    """Der Titel darf keinen Pfadanteil in den Dateinamen tragen.

    ``/`` wird im Altstand ersetzt, ``\\`` aber nicht — auf Windows ist das ein
    Separator. Der Fix normalisiert beide und nimmt nur den Basisnamen.
    """
    from core_skills_engine import ObsidianVaultSkill

    vault = tmp_path / "vault"
    vault.mkdir()
    skill = ObsidianVaultSkill(vault_dir=str(vault))
    escaped = os.path.realpath(os.path.join(str(vault), "../../evil.md"))

    try:
        result = skill.write_obsidian_note("..\\..\\evil", "payload")
    except (ValueError, PermissionError):
        result = {}

    leaked = os.path.exists(escaped)
    if leaked:
        os.remove(escaped)
    assert not leaked, f"Notiz ausserhalb des Vaults geschrieben: {escaped}"
    if result:
        assert result["filename"] == "evil.md", (
            f"Pfadanteil im Dateinamen geblieben: {result['filename']!r}"
        )


def test_obsidian_note_still_writes_inside_vault(tmp_path):
    from core_skills_engine import ObsidianVaultSkill

    vault = tmp_path / "vault"
    vault.mkdir()
    skill = ObsidianVaultSkill(vault_dir=str(vault))

    result = skill.write_obsidian_note("Gute Notiz", "Inhalt")

    assert result["status"] == "success"
    written = os.path.realpath(result["filepath"])
    assert written.startswith(str(vault.resolve()) + os.sep)
    assert os.path.isfile(written)


class _FakeSkillsEngine:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    class _Obsidian:
        def __init__(self, outer):
            self._outer = outer

        def write_obsidian_note(self, title, content, tags=None):
            self._outer.calls.append((title, content, tags))
            return {"status": "success"}

    @property
    def obsidian(self):
        return self._Obsidian(self)


def test_obsidian_write_handler_blocks_operator(monkeypatch):
    main = import_main()
    monkeypatch.setattr(main.auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(main.auth_service, "verify_session", lambda tok: dict(OPERATOR))
    from archon.routers import skills

    fake_engine = _FakeSkillsEngine()
    monkeypatch.setitem(skills._DEPS, "skills_engine", fake_engine)
    request = make_request("/api/v1/skills/obsidian/write", "POST", token="tok_op")

    with pytest.raises(HTTPException) as exc:
        skills.api_skills_obsidian_write(request, title="t", content="c", tags=None)

    assert exc.value.status_code == 403
    assert fake_engine.calls == []


def test_obsidian_write_handler_forwards_for_admin(monkeypatch):
    main = import_main()
    monkeypatch.setattr(main.auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(main.auth_service, "verify_session", lambda tok: dict(ADMIN))
    from archon.routers import skills

    fake_engine = _FakeSkillsEngine()
    monkeypatch.setitem(skills._DEPS, "skills_engine", fake_engine)
    request = make_request("/api/v1/skills/obsidian/write", "POST", token="tok_admin")

    result = skills.api_skills_obsidian_write(request, title="t", content="c", tags=None)

    assert result["status"] == "success"
    assert fake_engine.calls == [("t", "c", None)]


# --------------------------------------------------------------------------
# M-02 (c) — attach_vault_document: ``rel_path`` ohne Jail
# --------------------------------------------------------------------------

def test_attach_vault_document_rejects_traversal(notebook_env, tmp_path):
    engine, _raw_dir = notebook_env
    secret = tmp_path / "secret.md"
    secret.write_text("geheim", encoding="utf-8")

    with pytest.raises((ValueError, PermissionError, FileNotFoundError)):
        engine.add_source_from_vault("nb1", "../../secret.md")
