"""Teil A (Paket 1): TTL-Cache fuer /api/roles und Avatar-Materialisierung.

Hintergrund (Grundpruefung 2026-11-07 §3.5): `/api/roles` parste bei jedem Poll
2,63 MB JSON (Median 64-80 ms). Der Cache sitzt auf `load_roles()`, damit auch
interne Leser (Boardroom-Router, Prompt-Aufbau) profitieren; invalidiert wird an
der einzigen Schreibstelle `save_roles()`.

Die Avatar-Tests sichern den zweiten Hebel: data:-URI-Avatare (Base64 im
profile.yaml) werden als Datei unter static/avatars materialisiert, statt in
jeder Listen-Antwort mitzufliegen.
"""
import base64
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from archon.core.cache import invalidate  # noqa: E402
from archon.core import profiles as profiles_mod  # noqa: E402

PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6300010000050001"
)


@pytest.fixture()
def main_module(tmp_path, monkeypatch):
    """main mit eigener ROLES_FILE und leerem Rollen-Cache."""
    import main as app_main

    roles_file = tmp_path / "roles.json"
    roles_file.write_text(json.dumps([{"id": "a", "name": "A"}]), encoding="utf-8")
    monkeypatch.setattr(app_main, "ROLES_FILE", str(roles_file))
    invalidate(app_main.load_roles)
    yield app_main, roles_file
    invalidate(app_main.load_roles)


def test_roles_cache_reads_file_once(main_module, monkeypatch):
    """Zwei Aufrufe -> die Datei wird genau einmal geparst (Attrappe zaehlt)."""
    app_main, _ = main_module
    calls = {"n": 0}
    real_load_json = app_main._load_json

    def counting_load_json(path, default):
        calls["n"] += 1
        return real_load_json(path, default)

    monkeypatch.setattr(app_main, "_load_json", counting_load_json)

    first = app_main.load_roles()
    second = app_main.load_roles()

    assert calls["n"] == 1, "Cache greift nicht: Datei wurde mehrfach gelesen"
    assert first == second == [{"id": "a", "name": "A"}]


def test_roles_cache_invalidated_on_save(main_module):
    """Nach save_roles liefert der naechste Lesezugriff den neuen Inhalt."""
    app_main, roles_file = main_module

    assert app_main.load_roles() == [{"id": "a", "name": "A"}]
    app_main.save_roles([{"id": "b", "name": "B"}])

    assert roles_file.read_text(encoding="utf-8").count('"b"') == 1
    assert app_main.load_roles() == [{"id": "b", "name": "B"}], \
        "Invalidierung an der Schreibstelle wirkt nicht"


def test_roles_cache_survives_out_of_band_write(main_module):
    """Fremdschreiben ohne save_roles bleibt bis TTL-Ablauf unsichtbar (bewusst).

    Dokumentiert die Grenze der TTL: sie deckt nur den Schreibpfad der App ab.
    """
    app_main, roles_file = main_module

    assert app_main.load_roles() == [{"id": "a", "name": "A"}]
    roles_file.write_text(json.dumps([{"id": "c", "name": "C"}]), encoding="utf-8")

    assert app_main.load_roles() == [{"id": "a", "name": "A"}]

    invalidate(app_main.load_roles)
    assert app_main.load_roles() == [{"id": "c", "name": "C"}]


def test_api_get_roles_returns_all_entries(main_module):
    """Die Antwort enthaelt weiterhin alle Rollen (keine Kuerzung durch den Cache)."""
    app_main, roles_file = main_module
    payload = [{"id": f"role_{i}", "name": f"Rolle {i}"} for i in range(7)]
    roles_file.write_text(json.dumps(payload), encoding="utf-8")
    invalidate(app_main.load_roles)

    result = app_main.api_get_roles()

    assert len(result) == 7
    assert [r["id"] for r in result] == [r["id"] for r in payload]


@pytest.fixture()
def avatar_dirs(tmp_path, monkeypatch):
    """Laufzeit-Ablage (Env) + versionierter Bestand (APP_ROOT) getrennt auf tmp_path.

    Der Schreibpfad muss die Env-Aufloesung nehmen; APP_ROOT zeigt ebenfalls auf
    tmp_path, damit "nichts unter static/avatars" beweisbar bleibt.
    """
    monkeypatch.setattr(profiles_mod, "APP_ROOT", str(tmp_path))
    runtime = tmp_path / "runtime_avatars"
    monkeypatch.setenv(profiles_mod.AVATARS_DIR_ENV, str(runtime))
    return runtime, tmp_path / "static" / "avatars"


def test_data_uri_avatar_is_materialized(avatar_dirs):
    """data:-URI -> Datei im Laufzeitverzeichnis + /static-Pfad als Rueckgabe."""
    runtime, legacy = avatar_dirs
    data_url = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")

    url = profiles_mod.materialize_data_uri_avatar("demo_agent", data_url)

    assert url == "/static/avatars/custom_demo_agent.png"
    written = runtime / "custom_demo_agent.png"
    assert written.read_bytes() == PNG_BYTES
    assert not legacy.exists(), "versioniertes static/avatars darf nicht beschrieben werden"


def test_materialize_is_idempotent(avatar_dirs):
    """Zweiter Aufruf schreibt nicht neu, liefert denselben Pfad."""
    runtime, _ = avatar_dirs
    data_url = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")

    first = profiles_mod.materialize_data_uri_avatar("demo_agent", data_url)
    target = runtime / "custom_demo_agent.png"
    mtime_before = target.stat().st_mtime_ns
    second = profiles_mod.materialize_data_uri_avatar("demo_agent", data_url)

    assert first == second == "/static/avatars/custom_demo_agent.png"
    assert target.stat().st_mtime_ns == mtime_before
    assert not (runtime / "custom_demo_agent.png.tmp").exists()


@pytest.mark.parametrize("bad_value", [
    "/static/avatars/avatar_001.jpg",
    "https://example.invalid/a.png",
    "data:image/png;base64,",          # leerer Inhalt
    "data:text/plain;base64,aGVsbG8=",  # kein Bild-MIME
    "",
])
def test_materialize_rejects_non_avatar_values(avatar_dirs, bad_value):
    """Alles, was kein verwertbarer Bild-data:-URI ist, bleibt beim Aufrufer."""
    runtime, legacy = avatar_dirs
    assert profiles_mod.materialize_data_uri_avatar("demo_agent", bad_value) is None
    assert not runtime.exists()
    assert not legacy.exists()


def test_materialize_rejects_unsafe_profile_id(avatar_dirs):
    """Pfad-Ausbruch ueber die Profil-ID ist ausgeschlossen."""
    runtime, legacy = avatar_dirs
    data_url = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")
    assert profiles_mod.materialize_data_uri_avatar("../../etc/passwd", data_url) is None
    assert not runtime.exists()
    assert not legacy.exists()
