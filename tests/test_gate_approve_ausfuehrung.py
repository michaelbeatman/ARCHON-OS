"""Gate-Freigabe muss wirklich ausfuehren (P2, Gate-Approve-Defekt).

Drei Zusagen, die vor dem Fix alle verletzt waren:

1. Ein ``tools_erweiterung``-Gate schreibt das Profil (heute: ``NameError``,
   weil ``main.py`` den Endpunkt nie importiert hatte).
2. Ein ``profil_loeschen``-Gate entfernt den Profilordner (dito).
3. Eine gescheiterte Ausfuehrung laesst das Gate ``pending`` (heute wurde
   ``approved`` VOR der Ausfuehrung persistiert — das Gate war verbrannt und
   ein zweiter Versuch antwortete ``already_decided``).

Bewusst NICHT verwendet: ``monkeypatch.setattr(main, "<name unter Test>")``.
Das legt genau den Namen an, dessen Fehlen der Defekt ist, und macht den Test
gruen ohne Fix. Der Pfad laeuft hier echt bis in die Dateiebene; nur die
Zielordner zeigen auf ``tmp_path``.
"""

import os
import sys

import pytest
from starlette.requests import Request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

GATE_TOOLS = "tools_erweiterung"
GATE_DELETE = "profil_loeschen"

VALID_PAYLOAD = {
    "id": "probe_agent",
    "name": "Probe Agent",
    "person_name": "Probe",
    "category": "1. Test",
    "model": "test/modell",
    "tools": ["read_file"],
}


@pytest.fixture()
def gate_umgebung(monkeypatch, tmp_path):
    """Verdrahtet main + Service auf tmp-Ziele und einen Gate-Zustand im Speicher."""
    import main
    from archon.services import profiles_service

    basis = tmp_path / "profiles"
    basis.mkdir()
    avatare = tmp_path / "avatars"
    avatare.mkdir()
    ap_json = tmp_path / "agent_profiles.json"

    zustand = {"gates": []}

    def lade_gates():
        return zustand

    def speichere_gates(daten):
        zustand["gates"] = daten.get("gates", [])

    def lege_gate(kind, detail, anforderer, payload):
        gate = {"id": "g_%d" % (len(zustand["gates"]) + 1), "kind": kind,
                "detail": detail, "requested_by": anforderer, "payload": payload,
                "status": "pending"}
        zustand["gates"].append(gate)
        return gate

    # main.py
    monkeypatch.setattr(main, "require_admin", lambda r: {"role": "admin"})
    monkeypatch.setattr(main, "_load_permission_gates", lade_gates)
    monkeypatch.setattr(main, "_save_permission_gates", speichere_gates)
    monkeypatch.setattr(main, "_create_permission_gate", lege_gate)
    monkeypatch.setattr(main, "add_ticker", lambda *a, **k: None)

    # Service (er hat die Namen selbst gebunden -> dieselben Namen patchen)
    monkeypatch.setattr(profiles_service, "_load_permission_gates", lade_gates)
    monkeypatch.setattr(profiles_service, "_create_permission_gate", lege_gate)
    monkeypatch.setattr(profiles_service, "get_hermes_profiles_base_dirs",
                        lambda: [str(basis)])
    monkeypatch.setattr(profiles_service, "avatars_dir", lambda: str(avatare))
    monkeypatch.setattr(profiles_service, "invalidate_hermes_profiles_cache", lambda: None)
    monkeypatch.setattr(profiles_service, "api_get_hermes_profiles", lambda: [])
    monkeypatch.setattr(profiles_service, "add_ticker", lambda *a, **k: None)
    monkeypatch.setattr(profiles_service, "agent_profiles_json_path", lambda: str(ap_json))
    profiles_service.configure(org_sync_node=lambda *a, **k: None)

    # Kein Netzzugriff: Telegram-Ping im Decide-Handler stilllegen.
    class _StillerTelegram:
        @staticmethod
        def send_telegram_message(*a, **k):
            return True

    monkeypatch.setitem(sys.modules, "telegram_notify", _StillerTelegram)

    return {"main": main, "service": profiles_service, "zustand": zustand,
            "basis": basis, "ap_json": ap_json}


def _setze_gate(umgebung, kind, payload, gate_id):
    umgebung["zustand"]["gates"] = [{
        "id": gate_id, "kind": kind, "status": "pending",
        "detail": "Probe", "requested_by": "agent:probe", "payload": dict(payload),
    }]


def _entscheide(umgebung, gate_id, decision="approve"):
    main = umgebung["main"]
    pfad = "/api/permission-gates/%s/decide" % gate_id
    request = Request({
        "type": "http", "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": pfad, "raw_path": pfad.encode(),
        "query_string": b"", "root_path": "", "headers": [],
        "client": ("127.0.0.1", 1234), "server": ("testserver", 80),
        "app": main.app,
    })
    return main.api_decide_permission_gate(request, gate_id, {"decision": decision})


def test_tools_erweiterung_schreibt_profil(gate_umgebung):
    """Freigabe muss das Profil mit den neuen Tools schreiben."""
    _setze_gate(gate_umgebung, GATE_TOOLS, VALID_PAYLOAD, "g_tools")

    antwort = _entscheide(gate_umgebung, "g_tools")

    ergebnis = str(antwort.get("ergebnis", ""))
    assert "FEHLER" not in ergebnis, ergebnis
    assert antwort.get("error") is None, antwort

    yaml_pfad = gate_umgebung["basis"] / "probe_agent" / "profile.yaml"
    assert yaml_pfad.exists(), "Profil wurde nicht geschrieben (%s fehlt)" % yaml_pfad
    inhalt = yaml_pfad.read_text(encoding="utf-8")
    assert "read_file" in inhalt, inhalt
    assert gate_umgebung["zustand"]["gates"][0]["status"] == "approved"


def test_profil_loeschen_entfernt_profilordner(gate_umgebung):
    """Freigabe muss den Profilordner ins Archiv verschieben."""
    ziel = gate_umgebung["basis"] / "probe_agent"
    (ziel / "skills").mkdir(parents=True)
    _setze_gate(gate_umgebung, GATE_DELETE, {"profile_id": "probe_agent"}, "g_del")

    antwort = _entscheide(gate_umgebung, "g_del")

    ergebnis = str(antwort.get("ergebnis", ""))
    assert "FEHLER" not in ergebnis, ergebnis
    assert not ziel.exists(), "Profilordner existiert nach der Freigabe noch"
    archiv = list((gate_umgebung["basis"] / ".archive").glob("probe_agent_deleted_*"))
    assert archiv, "Kein Archivordner angelegt"
    assert gate_umgebung["zustand"]["gates"][0]["status"] == "approved"


def test_fehlgeschlagene_ausfuehrung_laesst_gate_pending(gate_umgebung):
    """Scheitert die Ausfuehrung, darf das Gate NICHT verbrannt werden."""
    kaputt = dict(VALID_PAYLOAD)
    kaputt["category"] = ""  # Schema-Validierung schlaegt fehl (echter Fehlerpfad)
    _setze_gate(gate_umgebung, GATE_TOOLS, kaputt, "g_kaputt")

    antwort = _entscheide(gate_umgebung, "g_kaputt")

    assert "FEHLER" in str(antwort.get("ergebnis", "")), antwort
    assert antwort.get("error"), "Antwort traegt keinen Fehler-Marker"
    assert antwort.get("status") == "error", antwort
    assert gate_umgebung["zustand"]["gates"][0]["status"] == "pending", (
        "Gate wurde trotz Fehlschlag verbraucht: %s"
        % gate_umgebung["zustand"]["gates"][0]["status"])

    # Wiederholbar: derselbe Gate-Record ist noch entscheidbar.
    antwort2 = _entscheide(gate_umgebung, "g_kaputt")
    assert antwort2.get("status") != "already_decided", antwort2


def test_ablehnung_wird_sofort_persistiert(gate_umgebung):
    """Ablehnung ist keine Ausfuehrung und wird sofort festgeschrieben."""
    _setze_gate(gate_umgebung, GATE_TOOLS, VALID_PAYLOAD, "g_nein")

    antwort = _entscheide(gate_umgebung, "g_nein", decision="reject")

    assert antwort.get("decision") == "reject"
    assert gate_umgebung["zustand"]["gates"][0]["status"] == "rejected"
    assert not (gate_umgebung["basis"] / "probe_agent").exists(), (
        "Ablehnung hat trotzdem geschrieben")
