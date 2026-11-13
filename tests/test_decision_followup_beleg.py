"""Punkt A: "ausgeführt" nur mit Beleg aus dem Antwort-Body.

Der Altstand uebernahm das Ergebnis eines Downstream-Aufrufs als Erfolg, ohne
den Body zu pruefen — ein Nicht-2xx oder eine Fehler-/Leer-Payload landete als
"ausgeführt" in der Owner-Meldung. Diese Tests fahren die Vertraege der drei
Zielendpunkte durch: Erfolg, Fehler-Body, Nicht-2xx und den Fall "HTTP 200,
aber nichts passiert".

Bewusst NICHT getestet wird die Formatierung im Telegram-Ping (das macht der
Adapter, siehe tests/test_telegram_gate_meldung.py) — hier geht es um den
Rueckgabestring, den ``api_decide_decision`` als ``ergebnis`` weiterreicht.
"""

import ast
import asyncio
import email.message
import os
import sys
import urllib.error

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import main  # noqa: E402

MISSION = "mission_freigabe"
GATE = "permission_gate"
SYNTHESE = "synthesis_freigabe"

OK_MARKER = "Folgeaktion ausgeführt"
NICHT_MARKER = "nicht ausgeführt"


def _folge(typ, dec, decision="approve"):
    return asyncio.run(main._decision_followup(typ, dec, decision))


def _http_fehler(status=500):
    return urllib.error.HTTPError("http://127.0.0.1:8501/x", status,
                                  "Fehler", email.message.Message(), None)


@pytest.fixture()
def move_selbst_api(monkeypatch):
    """Steuert die Antwort (oder Exception) des Move-Selbstaufrufs."""
    zustand = {
        "antwort": {"status": "ok", "task": {"id": "m1", "status": "in_progress"}},
        "aufrufe": [],
    }

    def selbst_api(method, path, payload=None, timeout=15.0):
        zustand["aufrufe"].append((method, path, payload))
        wert = zustand["antwort"]
        if isinstance(wert, Exception):
            raise wert
        return wert

    monkeypatch.setattr(main, "_decision_self_api", selbst_api)
    return zustand


# --------------------------------------------------------------- mission_freigabe

def test_mission_erfolg_meldet_ausgefuehrt(move_selbst_api):
    text = _folge(MISSION, {"typ": MISSION, "ref_id": "m1"})

    assert OK_MARKER in text, text
    assert NICHT_MARKER not in text, text
    assert "task.status=in_progress" in text, text
    method, path, payload = move_selbst_api["aufrufe"][0]
    assert (method, path) == ("POST", "/api/mission-control/tasks/move")
    assert payload == {"task_id": "m1", "target_status": "in_progress"}


def test_mission_fehlerbody_meldet_nicht_ausgefuehrt(move_selbst_api):
    move_selbst_api["antwort"] = {"status": "error", "detail": "Task nicht gefunden."}

    text = _folge(MISSION, {"typ": MISSION, "ref_id": "m1"})

    assert NICHT_MARKER in text, text
    assert OK_MARKER not in text, text
    assert "Task nicht gefunden." in text, text


def test_mission_nicht_2xx_meldet_nicht_ausgefuehrt(move_selbst_api):
    move_selbst_api["antwort"] = _http_fehler(500)

    text = _folge(MISSION, {"typ": MISSION, "ref_id": "m1"})

    assert NICHT_MARKER in text, text
    assert OK_MARKER not in text, text
    assert "Aufruf fehlgeschlagen" in text, text


def test_mission_status_ok_aber_task_nicht_verschoben(move_selbst_api):
    """HTTP 200 + 'ok', aber der Task steht weiter auf 'approval'."""
    move_selbst_api["antwort"] = {"status": "ok",
                                  "task": {"id": "m1", "status": "approval"}}

    text = _folge(MISSION, {"typ": MISSION, "ref_id": "m1"})

    assert NICHT_MARKER in text, text
    assert "approval" in text, text


def test_mission_antwort_ohne_task_objekt(move_selbst_api):
    move_selbst_api["antwort"] = {"status": "ok"}

    text = _folge(MISSION, {"typ": MISSION, "ref_id": "m1"})

    assert NICHT_MARKER in text, text
    assert "ohne Task-Objekt" in text, text


def test_mission_antwort_kein_json_objekt(move_selbst_api):
    move_selbst_api["antwort"] = ["ok"]

    text = _folge(MISSION, {"typ": MISSION, "ref_id": "m1"})

    assert NICHT_MARKER in text, text
    assert "kein JSON-Objekt" in text, text


def test_mission_ohne_ref_id_ruft_nichts_auf(move_selbst_api):
    text = _folge(MISSION, {"typ": MISSION, "ref_id": ""})

    assert NICHT_MARKER in text, text
    assert "ref_id" in text, text
    assert move_selbst_api["aufrufe"] == []


# --------------------------------------------------------------- permission_gate

@pytest.fixture()
def gate_umgebung(monkeypatch):
    """Gate-Store im Speicher + steuerbare Antwort des Decide-Endpunkts."""
    zustand = {
        "gates": {"gates": [{"id": "g1", "status": "approved"}]},
        "antwort": {"status": "ok", "gate_id": "g1", "decision": "approve",
                    "ergebnis": "Tools gespeichert"},
        "aufrufe": [],
    }

    def selbst_api(method, path, payload=None, timeout=15.0):
        zustand["aufrufe"].append((method, path, payload))
        wert = zustand["antwort"]
        if isinstance(wert, Exception):
            raise wert
        return wert

    monkeypatch.setattr(main, "_decision_self_api", selbst_api)
    monkeypatch.setattr(main, "_load_permission_gates", lambda: zustand["gates"])
    return zustand


def test_gate_erfolg_meldet_ausgefuehrt(gate_umgebung):
    text = _folge(GATE, {"typ": GATE, "ref_id": "g1"})

    assert OK_MARKER in text, text
    assert "persistiert als 'approved'" in text, text
    method, path, payload = gate_umgebung["aufrufe"][0]
    assert (method, path) == ("POST", "/api/permission-gates/g1/decide")
    assert payload == {"decision": "approve"}


def test_gate_fehlerbody_meldet_nicht_ausgefuehrt(gate_umgebung):
    """Der Endpunkt antwortet bei gescheiterter Ausfuehrung mit HTTP 200."""
    gate_umgebung["antwort"] = {
        "status": "error", "gate_id": "g1", "decision": "approve",
        "ergebnis": "FEHLER bei der Ausfuehrung: boom", "error": "boom"}

    text = _folge(GATE, {"typ": GATE, "ref_id": "g1"})

    assert NICHT_MARKER in text, text
    assert OK_MARKER not in text, text
    assert "boom" in text, text


def test_gate_status_ok_aber_nicht_persistiert(gate_umgebung):
    """'Unbekanntes Gate-Kind': status ok, aber das Gate bleibt 'pending'."""
    gate_umgebung["gates"] = {"gates": [{"id": "g1", "status": "pending"}]}
    gate_umgebung["antwort"] = {"status": "ok", "gate_id": "g1",
                                "decision": "approve",
                                "ergebnis": "Unbekanntes Gate-Kind - nichts ausgeführt"}

    text = _folge(GATE, {"typ": GATE, "ref_id": "g1"})

    assert NICHT_MARKER in text, text
    assert "pending" in text, text


def test_gate_already_decided_meldet_nicht_ausgefuehrt(gate_umgebung):
    gate_umgebung["antwort"] = {"status": "already_decided", "gate_id": "g1",
                                "decision": "approved"}

    text = _folge(GATE, {"typ": GATE, "ref_id": "g1"})

    assert NICHT_MARKER in text, text
    assert "already_decided" in text, text


def test_gate_nicht_2xx_meldet_nicht_ausgefuehrt(gate_umgebung):
    gate_umgebung["antwort"] = _http_fehler(503)

    text = _folge(GATE, {"typ": GATE, "ref_id": "g1"})

    assert NICHT_MARKER in text, text
    assert "Aufruf fehlgeschlagen" in text, text


def test_gate_fremdes_gate_in_der_antwort(gate_umgebung):
    gate_umgebung["antwort"] = {"status": "ok", "gate_id": "g9",
                                "decision": "approve", "ergebnis": "x"}

    text = _folge(GATE, {"typ": GATE, "ref_id": "g1"})

    assert NICHT_MARKER in text, text
    assert "g9" in text, text


def test_gate_store_nicht_lesbar_meldet_nicht_verifizierbar(gate_umgebung, monkeypatch):
    def kaputt():
        raise OSError("permission_gates.json unlesbar")

    monkeypatch.setattr(main, "_load_permission_gates", kaputt)

    text = _folge(GATE, {"typ": GATE, "ref_id": "g1"})

    assert NICHT_MARKER in text, text
    assert "nicht lesbar" in text, text


# --------------------------------------------------------------- synthesis_freigabe

@pytest.fixture()
def synthese_umgebung(monkeypatch):
    """Mission-Control-Store im Speicher + steuerbare Finalisierung."""
    store = {"tasks": [{"id": "p1", "status": "running"}]}
    zustand = {"store": store, "aufrufe": [], "finalisiert": 0}

    async def finalize(parent_pid, draft_path, synthese_text, approver_note,
                       daten=None):
        zustand["finalisiert"] += 1
        zustand["aufrufe"].append((parent_pid, draft_path, synthese_text,
                                   approver_note))
        for task in zustand["store"]["tasks"]:
            if task.get("id") == parent_pid:
                task["synthesis_finalized"] = True
                task["status"] = "completed"

    monkeypatch.setattr(main, "_finalize_synthesis_after_approval", finalize)
    monkeypatch.setattr(main, "_load_mission_control_data",
                        lambda: zustand["store"])
    return zustand


def test_synthese_erfolg_meldet_ausgefuehrt(synthese_umgebung):
    text = _folge(SYNTHESE, {"typ": SYNTHESE, "ref_id": "p1",
                             "dossier": "/tmp/d.html", "kurzfassung": "Kurz"})

    assert OK_MARKER in text, text
    assert "synthesis_finalized=true" in text, text
    parent_pid, draft_path, kurz, note = synthese_umgebung["aufrufe"][0]
    assert (parent_pid, draft_path, kurz) == ("p1", "/tmp/d.html", "Kurz")


def test_synthese_parent_fehlt_meldet_nicht_ausgefuehrt(synthese_umgebung):
    """Die Finalisierung steigt bei unbekanntem Parent still aus."""
    synthese_umgebung["store"]["tasks"] = []

    text = _folge(SYNTHESE, {"typ": SYNTHESE, "ref_id": "p_fehlt"})

    assert NICHT_MARKER in text, text
    assert "nicht in Mission Control gefunden" in text, text


def test_synthese_ohne_wirkung_meldet_nicht_verifizierbar(synthese_umgebung, monkeypatch):
    """Der Aufruf kehrt zurueck, ohne den Store zu aendern."""
    async def no_op(*args, **kwargs):
        return None

    monkeypatch.setattr(main, "_finalize_synthesis_after_approval", no_op)

    text = _folge(SYNTHESE, {"typ": SYNTHESE, "ref_id": "p1"})

    assert NICHT_MARKER in text, text
    assert "synthesis_finalized nicht gesetzt" in text, text


def test_synthese_bereits_finalisiert_wird_nicht_erneut_ausgefuehrt(synthese_umgebung):
    synthese_umgebung["store"]["tasks"] = [
        {"id": "p1", "status": "completed", "synthesis_finalized": True}]

    text = _folge(SYNTHESE, {"typ": SYNTHESE, "ref_id": "p1"})

    assert NICHT_MARKER in text, text
    assert "bereits finalisiert" in text, text
    assert synthese_umgebung["finalisiert"] == 0


def test_synthese_store_nicht_lesbar_meldet_nicht_verifizierbar(
        synthese_umgebung, monkeypatch):
    def kaputt():
        raise OSError("mc_store.json unlesbar")

    monkeypatch.setattr(main, "_load_mission_control_data", kaputt)

    text = _folge(SYNTHESE, {"typ": SYNTHESE, "ref_id": "p1"})

    assert NICHT_MARKER in text, text
    assert "nicht lesbar" in text, text


# --------------------------------------------------------------- unveraenderte Pfade

def test_ablehnung_bleibt_unveraendert():
    text = _folge(MISSION, {"typ": MISSION, "ref_id": "m1"}, decision="reject")

    assert text == "Abgelehnt — keine Folgeaktion ausgeführt."
    assert "ausgeführt" in text


def test_unbekannter_typ_bleibt_unveraendert():
    text = _folge("unbekannt", {"typ": "unbekannt", "ref_id": "x"})

    assert "Keine Folgeaktion nötig" in text, text
    assert NICHT_MARKER not in text, text


def test_alle_zweige_liefern_einen_string():
    """Rueckgabetyp bleibt ``str`` — der Aufrufer schneidet ``ergebnis[:700]``."""
    text = _folge(MISSION, {"typ": MISSION, "ref_id": ""})

    assert isinstance(text, str) and text


# --------------------------------------------------------------- Statik-Guards

def test_followup_prueft_body_und_nicht_nur_den_aufruf():
    """Der Kern des Fixes: die drei Zweige delegieren an eine Prueffunktion."""
    quelle = open(os.path.join(REPO, "main.py"), encoding="utf-8").read()
    baum = ast.parse(quelle)

    funktionen = {n.name: n for n in ast.walk(baum) if isinstance(n, ast.AsyncFunctionDef)}
    for name in ("_followup_mission_start", "_followup_permission_gate",
                 "_followup_synthesis"):
        assert name in funktionen, "Folgeaktions-Zweig %s fehlt" % name

    koerper = ast.get_source_segment(
        quelle, funktionen["_followup_mission_start"]) or ""
    assert "_pruefe_move_antwort" in koerper, (
        "Move-Zweig prueft die Antwort nicht mehr (nur der Aufruf gilt als Erfolg)")
    assert "_pruefe_gate_antwort" in (
        ast.get_source_segment(quelle, funktionen["_followup_permission_gate"]) or "")
    assert "_pruefe_synthese_beleg" in (
        ast.get_source_segment(quelle, funktionen["_followup_synthesis"]) or "")
