"""Der Owner darf keine Erfolgsmeldung bekommen, wenn nichts passiert ist.

Der Telegram-Adapter wertete beim Gate-Klick nur ``status_code == 200`` aus.
Der Archon-Endpunkt antwortet aber auch bei gescheiterter Ausfuehrung mit 200
(der Transport war ja in Ordnung) und legt den Fehlschlag in den Body. Folge:
„✅ Rechte freigegeben - wird jetzt ausgefuehrt", waehrend nichts geschah.

Der Adapter ist als Einzeldatei ins Hermes-Image kopiert und importiert dort
``gateway.*``, das es in diesem Repo nicht gibt. Deshalb wird die zu testende
Funktion per ``ast`` aus der **echten** Datei geladen und isoliert ausgefuehrt —
kein Nachbau, keine Kopie der Logik.
"""

import ast
import json
import os
import typing

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADAPTER = os.path.join(REPO, "scripts", "patches", "hermes_telegram_adapter.py")

FUNKTION = "gate_decision_answer"
KONSTANTEN = {"GATE_OK_TEXT", "GATE_REJECT_TEXT"}


def _lade_adapter_funktion():
    quelle = open(ADAPTER, encoding="utf-8").read()
    baum = ast.parse(quelle)

    knoten = []
    for node in baum.body:
        if isinstance(node, ast.FunctionDef) and node.name == FUNKTION:
            knoten.append(node)
        elif isinstance(node, ast.Assign):
            for ziel in node.targets:
                if isinstance(ziel, ast.Name) and ziel.id in KONSTANTEN:
                    knoten.append(node)

    gefunden = {n.name for n in knoten if isinstance(n, ast.FunctionDef)}
    assert FUNKTION in gefunden, (
        "%s fehlt in %s — wurde die Funktion umbenannt oder entfernt? "
        "Der Adapter darf den Body nicht mehr ignorieren." % (FUNKTION, ADAPTER))

    modul = ast.Module(body=knoten, type_ignores=[])
    ast.fix_missing_locations(modul)
    namensraum = {"json": json, "Dict": typing.Dict, "Any": typing.Any}
    exec(compile(modul, ADAPTER, "exec"), namensraum)
    return namensraum[FUNKTION]


def test_funktion_wird_aus_der_echten_datei_geladen():
    """Absicherung des Testaufbaus: die Quelle ist die Produktionsdatei."""
    assert os.path.exists(ADAPTER)
    fn = _lade_adapter_funktion()
    assert callable(fn)


def test_erfolg_bei_200_ohne_fehler_marker():
    fn = _lade_adapter_funktion()
    text = fn("approve", 200, '{"status": "ok", "ergebnis": "Tools gespeichert fuer x"}', "g1")
    assert "wird jetzt ausgefuehrt" in text
    assert "fehlgeschlagen" not in text


def test_200_mit_fehler_marker_meldet_ehrlich():
    """Der Kernfall: 200 + Fehler im Body darf NICHT als Erfolg gelten."""
    fn = _lade_adapter_funktion()
    body = json.dumps({
        "status": "error", "gate_id": "g1",
        "ergebnis": "FEHLER bei der Ausfuehrung: name 'api_save_hermes_profile' is not defined",
        "error": "name 'api_save_hermes_profile' is not defined",
    })
    text = fn("approve", 200, body, "g1")
    assert "wird jetzt ausgefuehrt" not in text, text
    assert "fehlgeschlagen" in text, text
    assert "api_save_hermes_profile" in text, text


def test_200_mit_fehler_marker_ohne_error_feld():
    """Auch ein reines ``ergebnis`` mit FEHLER-Praefix zaehlt als Fehlschlag."""
    fn = _lade_adapter_funktion()
    text = fn("approve", 200, '{"ergebnis": "FEHLER bei der Ausfuehrung: kaputt"}', "g1")
    assert "fehlgeschlagen" in text, text


def test_200_mit_status_error_ohne_details():
    fn = _lade_adapter_funktion()
    text = fn("approve", 200, '{"status": "error"}', "g1")
    assert "fehlgeschlagen" in text, text


def test_ablehnung_bleibt_unveraendert():
    fn = _lade_adapter_funktion()
    text = fn("reject", 200, '{"status": "ok", "ergebnis": "Abgelehnt - NICHTS wurde geaendert."}', "g1")
    assert text.strip() == "\u274c Rechte verweigert - nichts wurde geaendert."


def test_transportfehler_bleibt_unveraendert():
    fn = _lade_adapter_funktion()
    text = fn("approve", 503, "", "g1")
    assert "Archon nicht erreichbar" in text
    assert "g1" in text


def test_kaputter_body_gibt_keinen_falschen_fehler():
    """Nicht-JSON (z. B. Proxy-Fehlerseite) darf den Erfolgsfall nicht kippen."""
    fn = _lade_adapter_funktion()
    text = fn("approve", 200, "<html>ok</html>", "g1")
    assert "wird jetzt ausgefuehrt" in text


def test_aufrufstelle_nutzt_die_funktion():
    """Der Callback muss die Funktion benutzen, nicht wieder nur den Code pruefen."""
    quelle = open(ADAPTER, encoding="utf-8").read()
    baum = ast.parse(quelle)
    aufrufe = [
        node for node in ast.walk(baum)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == FUNKTION
    ]
    assert aufrufe, "gate_decision_answer wird nirgends aufgerufen"


def test_kein_reiner_statuscode_vergleich_mehr(monkeypatch):
    """Der alte Kurzschluss ``ok = _resp.status_code == 200`` darf nicht zurueckkehren."""
    quelle = open(ADAPTER, encoding="utf-8").read()
    marker = 'ok = _resp.status_code == 200'
    assert marker not in quelle, (
        "Der Adapter prueft wieder nur den Statuscode und ignoriert den Body")
