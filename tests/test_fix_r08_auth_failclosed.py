"""Cluster 1 — R-08/F9: Auth-Gate faellt bei Fehlern offen aus.

Rot gegen HEAD (909421d6):

* ``auth_gate`` (``main.py:237-242``) liefert bei jeder Exception
  ``await call_next(request)`` — die Authentifizierung verschwindet still.
* ``AuthService.is_auth_enabled()`` schluckt eine kaputte ``settings.json``
  (``except Exception: pass``) und gibt danach ``False`` zurueck, was das Gate
  vollstaendig abschaltet.

Erwartet wird fail-closed: Fehler -> 503 "Auth unavailable", kaputte
Konfiguration -> Auth gilt als aktiv.
"""

from __future__ import annotations

import json

import pytest

from archon_security_support import GATE_PASSED, import_main, make_request, run_gate, status_of


# --------------------------------------------------------------------------
# is_auth_enabled: kaputte settings.json -> fail-closed (True)
# --------------------------------------------------------------------------

@pytest.fixture()
def isolated_settings(tmp_path, monkeypatch):
    """Lenkt alle Kandidatenpfade von ``is_auth_enabled`` in ein Temp-Verzeichnis."""
    import backend.auth_service as auth_module

    monkeypatch.setattr(auth_module, "WORKSPACE_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return auth_module, tmp_path


def test_corrupt_settings_fails_closed(isolated_settings):
    auth_module, tmp_path = isolated_settings
    (tmp_path / "settings.json").write_text('{"auth": {"enabled": tr', encoding="utf-8")

    assert auth_module.auth_service.is_auth_enabled() is True


def test_non_dict_settings_fails_closed(isolated_settings):
    auth_module, tmp_path = isolated_settings
    (tmp_path / "settings.json").write_text('["nicht", "ein", "dict"]', encoding="utf-8")

    assert auth_module.auth_service.is_auth_enabled() is True


def test_valid_settings_without_auth_section_stays_disabled(isolated_settings):
    """Eine lesbare Datei ohne ``auth``-Block ist kein Fehler -> Auth bleibt aus."""
    auth_module, tmp_path = isolated_settings
    (tmp_path / "settings.json").write_text(json.dumps({"theme": "dark"}), encoding="utf-8")

    assert auth_module.auth_service.is_auth_enabled() is False


def test_explicit_disabled_stays_disabled(isolated_settings):
    auth_module, tmp_path = isolated_settings
    (tmp_path / "settings.json").write_text(json.dumps({"auth": {"enabled": False}}), encoding="utf-8")

    assert auth_module.auth_service.is_auth_enabled() is False


def test_no_settings_file_stays_disabled(isolated_settings):
    """Kein Konfigurationsfile = Entwicklungsdefault, kein Fehlerfall."""
    auth_module, _ = isolated_settings

    assert auth_module.auth_service.is_auth_enabled() is False


# --------------------------------------------------------------------------
# auth_gate: jeder Fehler -> 503 statt Durchlassen
# --------------------------------------------------------------------------

def test_gate_returns_503_when_auth_check_raises(monkeypatch):
    main = import_main()
    import backend.auth_service as auth_module

    def _boom() -> bool:
        raise RuntimeError("settings.json unlesbar")

    # Auf der Singleton-Instanz patchen (nicht auf der Klasse): andere Tests
    # hinterlassen ein Instanz-Attribut, das das Klassen-Attribut verdeckt.
    monkeypatch.setattr(auth_module.auth_service, "is_auth_enabled", _boom)

    response = run_gate(main, make_request("/api/contracts", "GET"))

    assert status_of(response) == 503
    assert b"Auth unavailable" in response.body


def test_gate_returns_503_when_auth_service_import_fails(monkeypatch):
    """Importfehler des Auth-Moduls darf das Gate nicht oeffnen."""
    import sys

    main = import_main()
    monkeypatch.setitem(sys.modules, "backend.auth_service", None)

    response = run_gate(main, make_request("/api/contracts", "GET"))

    assert status_of(response) == 503
    assert b"Auth unavailable" in response.body


def test_gate_blocks_api_on_corrupt_settings(isolated_settings):
    """Kaputte settings.json -> Gate bleibt zu (401), nicht offen."""
    _auth_module, tmp_path = isolated_settings
    (tmp_path / "settings.json").write_text("{kaputt", encoding="utf-8")
    main = import_main()

    response = run_gate(main, make_request("/api/contracts", "GET"))

    assert status_of(response) == 401


def test_gate_still_passes_when_auth_disabled(monkeypatch):
    """Gegenprobe: ``auth.enabled=false`` bleibt durchlaessig (kein Aussperren)."""
    main = import_main()
    monkeypatch.setattr(main.auth_service, "is_auth_enabled", lambda: False)

    response = run_gate(main, make_request("/api/contracts", "GET"))

    assert status_of(response) == GATE_PASSED
