"""Schreibpfad der Avatare: Laufzeitverzeichnis statt versioniertem static/avatars.

Befund (docs/PLAN_AVATAR_SCHREIBPFAD.md, Variante B): `avatars_dir()` zeigte auf
`APP_ROOT/static/avatars` — ein versioniertes Verzeichnis. Jede Materialisierung
eines data:-URI-Avatars liess getrackte PNGs als `M` im Working Tree stehen.

Diese Tests sichern drei Dinge:

1. Geschrieben wird **nie** unter `APP_ROOT/static/avatars` (der Kernbeweis).
2. Die Pfad-Aufloesung folgt der Reihenfolge Env -> /opt/data -> ~/.hermes.
3. Die beiden ehemaligen Router-Duplikate schreiben atomar (kein `*.tmp`-Rest).
"""
import base64
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from archon.core import profiles as profiles_mod  # noqa: E402

PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6300010000050001"
)
PNG_DATA_URI = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")


# ---------------------------------------------------------------------------
# Pfad-Aufloesung: die drei Faelle
# ---------------------------------------------------------------------------

def test_env_gewinnt_immer(monkeypatch, tmp_path):
    """ARCHON_AVATARS_DIR schlaegt auch einen vorhandenen Container-Pfad."""
    ziel = tmp_path / "frei_gewaehlt"
    monkeypatch.setenv(profiles_mod.AVATARS_DIR_ENV, str(ziel))
    monkeypatch.setattr(profiles_mod, "_container_data_available", lambda: True)

    assert profiles_mod.avatars_dir() == str(ziel)


def test_ohne_env_mit_opt_data_nimmt_container_pfad(monkeypatch):
    """Env leer + /opt/data vorhanden -> /opt/data/webui/static_avatars."""
    monkeypatch.delenv(profiles_mod.AVATARS_DIR_ENV, raising=False)
    monkeypatch.setattr(profiles_mod, "_container_data_available", lambda: True)

    assert profiles_mod.avatars_dir() == "/opt/data/webui/static_avatars"


def test_ohne_env_ohne_opt_data_nimmt_home_pendant(monkeypatch):
    """Env leer + kein /opt/data (Host) -> ~/.hermes/webui/static_avatars."""
    monkeypatch.delenv(profiles_mod.AVATARS_DIR_ENV, raising=False)
    monkeypatch.setattr(profiles_mod, "_container_data_available", lambda: False)

    erwartet = os.path.expanduser("~/.hermes/webui/static_avatars")
    assert profiles_mod.avatars_dir() == erwartet
    assert erwartet.endswith(os.path.join(".hermes", "webui", "static_avatars"))


@pytest.mark.parametrize("fall", ["env", "container", "host"])
def test_avatars_dir_ist_nie_der_versionierte_baum(monkeypatch, tmp_path, fall):
    """Standardaufloesung trifft nie zufaellig APP_ROOT/static/avatars."""
    monkeypatch.setattr(profiles_mod, "APP_ROOT", str(tmp_path))
    monkeypatch.delenv(profiles_mod.AVATARS_DIR_ENV, raising=False)
    if fall == "env":
        monkeypatch.setenv(profiles_mod.AVATARS_DIR_ENV, str(tmp_path / "laufzeit"))
    monkeypatch.setattr(profiles_mod, "_container_data_available",
                        lambda: fall == "container")

    ziel = Path(profiles_mod.avatars_dir()).resolve()
    legacy = Path(profiles_mod.avatars_legacy_dir()).resolve()

    assert ziel != legacy
    if fall != "env":
        assert tmp_path.resolve() not in ziel.parents


# ---------------------------------------------------------------------------
# Kernbeweis: Schreiben landet nicht im versionierten Baum
# ---------------------------------------------------------------------------

def test_materialisieren_schreibt_nicht_in_static_avatars(monkeypatch, tmp_path):
    """Der eigentliche Befund: APP_ROOT/static/avatars bleibt unberuehrt."""
    monkeypatch.setattr(profiles_mod, "APP_ROOT", str(tmp_path))
    laufzeit = tmp_path / "opt_data_webui" / "static_avatars"
    monkeypatch.setenv(profiles_mod.AVATARS_DIR_ENV, str(laufzeit))

    pfad = profiles_mod.materialize_data_uri_avatar("probe_agent", PNG_DATA_URI)

    assert pfad == "/static/avatars/custom_probe_agent.png"
    assert (laufzeit / "custom_probe_agent.png").read_bytes() == PNG_BYTES
    versioniert = tmp_path / "static" / "avatars"
    assert not versioniert.exists(), (
        "Avatar wurde in das versionierte Verzeichnis geschrieben — genau der Befund"
    )
    assert not list(tmp_path.rglob("*.tmp")), "tmp-Rest nach os.replace"


# ---------------------------------------------------------------------------
# Lesekette: Laufzeit vor versioniertem Bestand
# ---------------------------------------------------------------------------

def test_resolve_avatar_file_laufzeit_vor_legacy(monkeypatch, tmp_path):
    """Gleicher Dateiname in beiden Verzeichnissen -> Laufzeit gewinnt."""
    monkeypatch.setattr(profiles_mod, "APP_ROOT", str(tmp_path))
    laufzeit = tmp_path / "laufzeit"
    legacy = tmp_path / "static" / "avatars"
    laufzeit.mkdir(parents=True)
    legacy.mkdir(parents=True)
    (laufzeit / "custom_a.png").write_bytes(b"neu")
    (legacy / "custom_a.png").write_bytes(b"alt")
    monkeypatch.setenv(profiles_mod.AVATARS_DIR_ENV, str(laufzeit))

    assert profiles_mod.resolve_avatar_file("custom_a.png") == str(laufzeit / "custom_a.png")


def test_resolve_avatar_file_faellt_auf_legacy_zurueck(monkeypatch, tmp_path):
    """Katalogbilder (avatar_NNN.jpg) bleiben im Repo und werden weiter gefunden."""
    monkeypatch.setattr(profiles_mod, "APP_ROOT", str(tmp_path))
    legacy = tmp_path / "static" / "avatars"
    legacy.mkdir(parents=True)
    (legacy / "avatar_007.jpg").write_bytes(b"katalog")
    monkeypatch.setenv(profiles_mod.AVATARS_DIR_ENV, str(tmp_path / "leer"))

    assert profiles_mod.resolve_avatar_file("avatar_007.jpg") == str(legacy / "avatar_007.jpg")


@pytest.mark.parametrize("name", ["", "..", "../../etc/passwd", "/etc/passwd", ".hidden"])
def test_resolve_avatar_file_lehnt_pfad_ausbruch_ab(monkeypatch, tmp_path, name):
    """Nur Basisnamen ohne Punkt-Praefix werden aufgeloest."""
    monkeypatch.setattr(profiles_mod, "APP_ROOT", str(tmp_path))
    assert profiles_mod.resolve_avatar_file(name) is None


# ---------------------------------------------------------------------------
# Duplikate in den Routern: atomar, kein *.tmp-Rest
# ---------------------------------------------------------------------------

@pytest.fixture()
def upload_umgebung(monkeypatch, tmp_path):
    """Router + Service ohne echte Profil-/DB-Pfade.

    Seit dem Rollenzaun (RBAC) braucht die Upload-Route ein ``Request`` und
    einen verdrahteten Admin-Durchlass. Wir nutzen den echten ``require_admin``
    im Einzelnutzer-Modus (``auth.enabled=false``), damit der Test weiterhin den
    Schreibpfad prueft statt am Zaun zu enden.
    """
    from archon.routers import hermes_profiles as router_mod
    from archon.routers import _rbac as rbac_module
    import main as _main
    from starlette.requests import Request

    monkeypatch.setattr(_main.auth_service, "is_auth_enabled", lambda: False)
    monkeypatch.setattr(_main.auth_service, "get_fallback_admin",
                        lambda: {"id": "usr_admin", "username": "admin",
                                 "role": "admin", "permissions": {},
                                 "is_fallback": True})
    monkeypatch.setattr(rbac_module, "_checker", _main.require_admin)
    request = Request({
        "type": "http", "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": "/api/hermes/profiles/probe_agent/avatar",
        "raw_path": b"/api/hermes/profiles/probe_agent/avatar",
        "query_string": b"", "root_path": "", "headers": [],
        "client": ("127.0.0.1", 1234), "server": ("testserver", 80),
        "app": _main.app,
    })

    laufzeit = tmp_path / "laufzeit"
    monkeypatch.setenv(profiles_mod.AVATARS_DIR_ENV, str(laufzeit))
    monkeypatch.setattr(router_mod, "get_hermes_profiles_base_dirs", lambda: [])
    monkeypatch.setattr(router_mod, "invalidate_hermes_profiles_cache", lambda: None)
    monkeypatch.setattr(router_mod, "api_get_hermes_profiles", lambda: [])
    # Nur echte Home-Pfade (avatars.db) umbiegen — der Env-Pfad muss unberuehrt
    # bleiben, sonst wuerde die Aufloesung selbst verbogen.
    _echt_expand = os.path.expanduser
    monkeypatch.setattr(
        os.path, "expanduser",
        lambda p: str(tmp_path / "kein_home") if p.startswith("~") else _echt_expand(p))
    return router_mod, laufzeit, request


def test_router_upload_schreibt_atomar_in_laufzeitverzeichnis(upload_umgebung):
    """api_upload_hermes_profile_avatar: Nutzen des gemeinsamen Helfers, kein tmp."""
    router_mod, laufzeit, request = upload_umgebung

    antwort = router_mod.api_upload_hermes_profile_avatar(
        request, "probe_agent", {"image": PNG_DATA_URI})

    assert antwort["status"] == "success"
    assert antwort["avatar_url"] == "/static/avatars/custom_probe_agent.png"
    assert (laufzeit / "custom_probe_agent.png").read_bytes() == PNG_BYTES
    assert not list(laufzeit.glob("*.tmp"))


def test_service_save_schreibt_atomar_in_laufzeitverzeichnis(monkeypatch, tmp_path):
    """save_profile: gleicher Helfer, gleiche Atomaritaet, kein tmp-Rest."""
    from archon.services import profiles_service

    laufzeit = tmp_path / "laufzeit"
    monkeypatch.setenv(profiles_mod.AVATARS_DIR_ENV, str(laufzeit))
    monkeypatch.setattr(profiles_service, "get_hermes_profiles_base_dirs", lambda: [])
    monkeypatch.setattr(profiles_service, "invalidate_hermes_profiles_cache", lambda: None)
    monkeypatch.setattr(profiles_service, "api_get_hermes_profiles", lambda: [])
    monkeypatch.setattr(profiles_service, "add_ticker", lambda *a, **k: None)
    monkeypatch.setattr(profiles_service, "agent_profiles_json_path",
                        lambda: str(tmp_path / "agent_profiles.json"))
    monkeypatch.setattr(profiles_service, "_load_permission_gates",
                        lambda: {"gates": []})
    _echt_expand = os.path.expanduser
    monkeypatch.setattr(
        os.path, "expanduser",
        lambda p: str(tmp_path / "kein_home") if p.startswith("~") else _echt_expand(p))
    profiles_service.configure(org_sync_node=lambda *a, **k: None)

    nutzlast = {
        "id": "probe_agent", "name": "Probe Agent", "person_name": "Probe",
        "category": "1. Test", "model": "test/modell", "tools": [],
        "avatar": PNG_DATA_URI,
    }
    profiles_service.save_profile(nutzlast)

    assert (laufzeit / "custom_probe_agent.png").read_bytes() == PNG_BYTES
    assert not list(laufzeit.glob("*.tmp"))
    assert not (tmp_path / "static" / "avatars").exists()
