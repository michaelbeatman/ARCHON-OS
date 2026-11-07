"""Service-Ebene: Gate-Verifikation (fail-closed) und agent_profiles.json-Sync.

Der Service wird hier direkt gerufen — ohne ``Request``, ohne HTTP-Stack. Genau
das war der Zweck der Extraktion: der Gate-Pfad in ``main.py`` und der
HTTP-Pfad teilen dieselbe Fachlogik.

Zwei Zusagen, die vorher nicht galten:

* Ein ``_approved_gate_id`` wurde nur auf Wahrheitswert geprueft
  (``bool(profile_data.get(...))``). Jeder Admin-Client konnte damit den
  Tools-Gate ueberspringen. Jetzt wird der Gate-Record geladen und geprueft.
* Der ``agent_profiles.json``-Sync leitete den Pfad aus ``__file__`` des Routers
  ab (``archon/routers/``) — dort liegt die Datei nie. Der Block war toter Code.
"""

import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from archon.services import profiles_service  # noqa: E402
from archon.services.profiles_service import (  # noqa: E402
    GateNotApproved, ProfileProtectedError, delete_profile, save_profile,
)

PAYLOAD = {
    "id": "probe_agent", "name": "Probe Agent", "person_name": "Probe",
    "category": "1. Test", "model": "test/modell", "tools": ["read_file"],
}


@pytest.fixture()
def service_umgebung(monkeypatch, tmp_path):
    basis = tmp_path / "profiles"
    basis.mkdir()
    avatare = tmp_path / "avatars"
    avatare.mkdir()
    ap_json = tmp_path / "agent_profiles.json"

    zustand = {"gates": []}

    def lade_gates():
        return zustand

    monkeypatch.setattr(profiles_service, "_load_permission_gates", lade_gates)
    # Kein Test darf ein echtes Gate in config/permission_gates.json schreiben.
    monkeypatch.setattr(
        profiles_service, "_create_permission_gate",
        lambda kind, detail, wer, payload: {
            "id": "g_angelegt", "kind": kind, "status": "pending",
            "detail": detail, "requested_by": wer, "payload": payload})
    monkeypatch.setattr(profiles_service, "get_hermes_profiles_base_dirs",
                        lambda: [str(basis)])
    monkeypatch.setattr(profiles_service, "avatars_dir", lambda: str(avatare))
    monkeypatch.setattr(profiles_service, "invalidate_hermes_profiles_cache", lambda: None)
    monkeypatch.setattr(profiles_service, "api_get_hermes_profiles", lambda: [])
    monkeypatch.setattr(profiles_service, "add_ticker", lambda *a, **k: None)
    monkeypatch.setattr(profiles_service, "agent_profiles_json_path", lambda: str(ap_json))
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path / "kein_home"))
    profiles_service.configure(org_sync_node=lambda *a, **k: None)

    return {"basis": basis, "ap_json": ap_json, "zustand": zustand}


def _gate(zustand, gate_id, kind, payload, status="pending"):
    zustand["gates"] = [{"id": gate_id, "kind": kind, "status": status,
                         "detail": "Probe", "requested_by": "agent:probe",
                         "payload": dict(payload)}]


def test_agent_profiles_json_wird_aktualisiert(service_umgebung):
    """Der Sync-Block laeuft nach dem APP_ROOT-Fix wirklich (vorher toter Code)."""
    ap = service_umgebung["ap_json"]
    ap.write_text(json.dumps([{"id": "anderer", "name": "Anderer"}]), encoding="utf-8")
    _gate(service_umgebung["zustand"], "g_ok", "tools_erweiterung", {"id": "probe_agent"})
    payload = dict(PAYLOAD)
    payload["_approved_gate_id"] = "g_ok"

    save_profile(payload)

    daten = json.loads(ap.read_text(encoding="utf-8"))
    ids = [e.get("id") for e in daten]
    assert "probe_agent" in ids, daten
    eintrag = next(e for e in daten if e.get("id") == "probe_agent")
    assert eintrag["model"] == "test/modell"
    assert eintrag["person_name"] == "Probe"
    assert "anderer" in ids, "bestehender Eintrag wurde verdraengt"


def test_agent_profiles_json_wird_nicht_angelegt_wenn_datei_fehlt(service_umgebung):
    """Fehlt die Datei, wird sie nicht erfunden (Existenz-Guard bleibt)."""
    _gate(service_umgebung["zustand"], "g_ok", "tools_erweiterung", {"id": "probe_agent"})
    payload = dict(PAYLOAD)
    payload["_approved_gate_id"] = "g_ok"
    assert not service_umgebung["ap_json"].exists()

    save_profile(payload)

    assert not service_umgebung["ap_json"].exists()


def test_save_verweigert_unverifiziertes_gate(service_umgebung):
    """Fail-closed: ein Gate, das es nicht gibt, darf NICHT durchlassen."""
    payload = dict(PAYLOAD)
    payload["_approved_gate_id"] = "gibt_es_nicht"
    with pytest.raises(GateNotApproved):
        save_profile(payload)
    assert not (service_umgebung["basis"] / "probe_agent").exists()


def test_save_verweigert_gate_mit_falschem_payload(service_umgebung):
    """Ein Gate fuer ein ANDERES Profil darf nicht fuer dieses Profil gelten."""
    _gate(service_umgebung["zustand"], "g_fremd", "tools_erweiterung",
          {"id": "anderer_agent"})
    payload = dict(PAYLOAD)
    payload["_approved_gate_id"] = "g_fremd"
    with pytest.raises(GateNotApproved):
        save_profile(payload)


def test_save_verweigert_bereits_entschiedenes_gate(service_umgebung):
    """Einmal-Nutzung: ein schon entschiedenes Gate ist kein Freibrief."""
    _gate(service_umgebung["zustand"], "g_alt", "tools_erweiterung",
          {"id": "probe_agent"}, status="approved")
    payload = dict(PAYLOAD)
    payload["_approved_gate_id"] = "g_alt"
    with pytest.raises(GateNotApproved):
        save_profile(payload)


def test_save_akzeptiert_passendes_gate(service_umgebung):
    """Positivfall: offenes Gate, richtiges Kind, richtiger Payload."""
    _gate(service_umgebung["zustand"], "g_ok", "tools_erweiterung", {"id": "probe_agent"})
    payload = dict(PAYLOAD)
    payload["_approved_gate_id"] = "g_ok"

    ergebnis = save_profile(payload)

    assert ergebnis["status"] == "success"
    assert (service_umgebung["basis"] / "probe_agent" / "profile.yaml").exists()


def test_delete_verweigert_gate_mit_falschem_kind(service_umgebung):
    """Ein Tools-Gate ist keine Loeschfreigabe."""
    _gate(service_umgebung["zustand"], "g_tools", "tools_erweiterung",
          {"profile_id": "probe_agent"})
    with pytest.raises(GateNotApproved):
        delete_profile("probe_agent", approved_gate_id="g_tools")


def test_delete_schuetzt_systemprofile(service_umgebung):
    for name in ("default", "hermes_default", "micha"):
        with pytest.raises(ProfileProtectedError) as exc:
            delete_profile(name)
        assert name in str(exc.value)


def test_delete_ohne_gate_legt_gate_an(service_umgebung, monkeypatch):
    """Ohne Gate-ID wird keine Aktion ausgefuehrt, sondern ein Gate erzeugt."""
    angelegt = {}

    def lege(kind, detail, wer, payload):
        angelegt.update({"kind": kind, "payload": payload})
        return {"id": "g_neu"}

    monkeypatch.setattr(profiles_service, "_create_permission_gate", lege)
    ziel = service_umgebung["basis"] / "probe_agent"
    ziel.mkdir()

    ergebnis = delete_profile("probe_agent")

    assert ergebnis["status"] == "pending_owner_approval"
    assert angelegt["kind"] == "profil_loeschen"
    assert ziel.exists(), "Ohne Freigabe darf nichts geloescht werden"
