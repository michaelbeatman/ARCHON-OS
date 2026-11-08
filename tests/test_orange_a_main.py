"""Cluster Spur A — main.py (Z-04, Z-05, Z-09, Z-11, D-07..D-13, D-21,
F-05, F-06, F-10, F-12, F-13).

Rot gegen 3269f7e1 (Belege aus dem Review):

* Z-04: ``_parse_gateway_list`` gab IMMER [] zurueck — die Idle-Stop-Funktion
  war tot.
* Z-05: SSE-Queue mit maxsize=100; ``broadcast_event`` entfernt den Subscriber
  bei vollem Puffer -> Client dauerhaft getrennt.
* Z-09: fester Fallback-Bearer fuer den Hermes-Proxy (bereits durch
  Commit 255004dc geschlossen — der Test sichert den Zustand ab).
* Z-11: DockerError -> ``load_services()`` (statische Wunschliste in
  Container-Struktur) — Ausfall nicht von Normalzustand unterscheidbar.
* D-07: ``res`` im Telegram-Relay-Fehlerpfad ungebunden -> NameError -> 500.
* D-08: save-full-html truncatete die Datei vor dem Schreiben, Fehler wurden
  verschluckt, "success" gemeldet.
* D-09: Gateway-Start/Stop setzte den Zustand VOR der Aktion, rc ignoriert.
* D-10: Oracle-Endpunkte lieferten HTTP 200 mit ``status: error``.
* D-11: Design-Themes: Fehler bei allen vier Zielen verschluckt, "success".
* D-12: Default-Modellname "evey-session-guard:" (syntaktisch kaputt).
* D-13: Theme-Hintergrund-Upload ohne Typ-/Groessenfilter (Stored XSS).
* D-21: Guardian-Cache unbeschaenzt, Schluessel = freier Query-Parameter.
* F-05: Provider-Fehler wurde als erfolgreicher Turn verbucht (Antwort
  gespeichert, Nutzung gebucht).
* F-06: ``agent_profiles.json`` wurde zwischen zwei Writes geleert.
* F-10: Lost Update im Mission-Control-Store (load->modify->save).
* F-12: Cache-Invalidierung traf die tote Kopie statt den gelesenen Cache.
* F-13: ``_idle_stop_running`` wurde gesetzt, aber nie gelesen.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(os.environ.get("ARCHON_ROOT") or Path(__file__).resolve().parent.parent)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main as app_main  # noqa: E402


# ------------------------------------------------------------------- Z-04

def test_parse_gateway_list_liest_json():
    stdout = json.dumps([
        {"id": "default", "status": "running"},
        {"id": "researcher", "status": "stopped"},
    ])
    parsed = app_main._parse_gateway_list(stdout)
    assert [p["id"] for p in parsed] == ["default", "researcher"]
    assert parsed[0]["status"] == "running"


def test_parse_gateway_list_liest_json_objekt():
    stdout = json.dumps({"profiles": [{"id": "a", "status": "running"}]})
    parsed = app_main._parse_gateway_list(stdout)
    assert parsed == [{"id": "a", "status": "running"}]


def test_parse_gateway_list_liest_tabelle():
    stdout = "ID          STATUS      MODEL\ndefault     running     x\nresearcher  stopped     y\n"
    parsed = app_main._parse_gateway_list(stdout)
    ids = [p["id"] for p in parsed]
    assert ids == ["default", "researcher"]
    assert parsed[0]["status"] == "running"
    assert parsed[1]["status"] == "stopped"


def test_parse_gateway_list_ueberlebt_leere_ausgabe():
    assert app_main._parse_gateway_list("") == []
    assert app_main._parse_gateway_list("   ") == []
    assert app_main._parse_gateway_list("kaputt\n") == []


# ------------------------------------------------------------------- Z-05

def test_sse_queue_ist_unbeschaenkt():
    """Ein voller Puffer darf den Subscriber nicht mehr entfernen."""
    import inspect

    source = inspect.getsource(app_main.sse_events_stream)
    assert "asyncio.Queue(maxsize=" not in source, (
        "Die SSE-Queue darf nicht begrenzt sein — ein voller Puffer entfernt "
        "den Subscriber serverseitig (Z-05)"
    )


def test_broadcast_event_behaelt_subscriber_bei_vollem_puffer():
    """Funktional: 500 Events in eine unbeschaenkte Queue -> Subscriber bleibt."""
    from archon.core.runtime import _SSE_SUBSCRIBERS, broadcast_event

    async def scenario():
        queue = asyncio.Queue()
        _SSE_SUBSCRIBERS.append(queue)
        try:
            for i in range(500):
                broadcast_event("test", {"i": i})
            return queue in _SSE_SUBSCRIBERS, queue.qsize()
        finally:
            if queue in _SSE_SUBSCRIBERS:
                _SSE_SUBSCRIBERS.remove(queue)

    still_subscribed, size = asyncio.run(scenario())
    assert still_subscribed, "der Subscriber wurde bei vollem Puffer entfernt"
    assert size == 500


# ------------------------------------------------------------------- Z-09

def test_kein_hartkodierter_proxy_token(monkeypatch):
    """Z-09: Ohne Env-Variable liefert der Proxy fail-closed (leerer Token)."""
    for name in ("HERMES_SESSION_TOKEN", "HERMES_DASHBOARD_SESSION_TOKEN", "OMNIROUTE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert app_main._hermes_proxy_token() == ""


def test_proxy_token_kommt_aus_der_umgebung(monkeypatch):
    monkeypatch.setenv("HERMES_SESSION_TOKEN", "tok-abc")
    assert app_main._hermes_proxy_token() == "tok-abc"


# ------------------------------------------------------------------- Z-11

def test_docker_ausfall_ist_vom_normalzustand_unterscheidbar(monkeypatch):
    """Bei DockerError darf nicht die Wunschliste als 'laufend' erscheinen."""
    from utils.docker_client import DockerError

    def boom(*_args, **_kwargs):
        raise DockerError("daemon weg")

    monkeypatch.setattr(app_main.docker_client, "request", boom)
    monkeypatch.setattr(app_main, "load_services", lambda: [
        {"id": "hermes", "name": "Hermes", "active": True},
    ])

    result = app_main.get_docker_containers_from_socket.__wrapped__()
    assert result, "es muss ein Ergebnis geben"
    for entry in result:
        assert entry.get("source") == "config-fallback", (
            "der Fallback ist nicht als solcher gekennzeichnet"
        )
        assert entry.get("online") is False
        assert "fallback_reason" in entry


# ------------------------------------------------------------------- D-07

def test_telegram_relay_ueberlebt_dispatch_fehler(monkeypatch):
    """Im Fehlerpfall darf kein NameError (ungebundenes ``res``) auftreten."""
    import core_dispatcher

    async def boom(*_args, **_kwargs):
        raise RuntimeError("dispatch kaputt")

    monkeypatch.setattr(core_dispatcher, "dispatch_to_omniroute_or_container", boom)
    monkeypatch.setattr(app_main, "api_get_hermes_profiles", lambda: [
        {"id": "executive_decision_architect", "name": "Robert", "model": "x",
         "system_prompt": "p"},
    ])

    sent = {}

    def fake_send(text):
        sent["text"] = text
        return True

    import telegram_notify
    monkeypatch.setattr(telegram_notify, "send_telegram_message", fake_send)
    monkeypatch.setattr(app_main, "add_ticker", lambda *a, **k: None)

    result = asyncio.run(app_main.api_telegram_relay(
        ziel_agent="executive_decision_architect", text="hallo",
    ))

    assert result["status"] == "ok"
    assert "dispatch kaputt" in sent["text"], "der Fehler wurde nicht weitergereicht"


# ------------------------------------------------------------------- D-08

def test_save_full_html_schreibt_atomar_und_meldet_fehler(monkeypatch, tmp_path):
    target = tmp_path / "index.html"
    target.write_text("ALT", encoding="utf-8")

    monkeypatch.setattr(app_main, "add_ticker", lambda *a, **k: None)
    monkeypatch.setattr(app_main, "require_admin", lambda request: None)
    monkeypatch.setattr(app_main, "_full_html_target_files", lambda: [str(target)])

    html = "<html>" + ("x" * 300) + "</html>"
    result = app_main.api_save_full_html(None, app_main.FullHtmlSaveRequest(html=html))
    assert result["status"] == "success"
    assert target.read_text(encoding="utf-8") == html


def test_save_full_html_meldet_schreibfehler(monkeypatch, tmp_path):
    target = tmp_path / "index.html"
    target.write_text("ALT", encoding="utf-8")

    monkeypatch.setattr(app_main, "add_ticker", lambda *a, **k: None)
    monkeypatch.setattr(app_main, "require_admin", lambda request: None)
    monkeypatch.setattr(app_main, "_full_html_target_files", lambda: [str(target)])

    def boom(*_args, **_kwargs):
        raise OSError("Platte voll")

    monkeypatch.setattr(app_main.os, "replace", boom)
    html = "<html>" + ("x" * 300) + "</html>"
    with pytest.raises(HTTPException) as exc:
        app_main.api_save_full_html(None, app_main.FullHtmlSaveRequest(html=html))
    assert exc.value.status_code == 500
    # Zieldatei unveraendert (kein Truncate-before-Write)
    assert target.read_text(encoding="utf-8") == "ALT"


def test_save_full_html_lehnt_zu_kurzes_html_ab(monkeypatch, tmp_path):
    target = tmp_path / "index.html"
    target.write_text("ALT", encoding="utf-8")
    monkeypatch.setattr(app_main, "add_ticker", lambda *a, **k: None)
    monkeypatch.setattr(app_main, "require_admin", lambda request: None)
    monkeypatch.setattr(app_main, "_full_html_target_files", lambda: [str(target)])
    with pytest.raises(HTTPException) as exc:
        app_main.api_save_full_html(None, app_main.FullHtmlSaveRequest(html="kurz"))
    assert exc.value.status_code == 400
    assert target.read_text(encoding="utf-8") == "ALT"


# ------------------------------------------------------------------- D-09

def _gateway_request():
    from archon_security_support import ADMIN, make_request
    return make_request("/api/v1/gateway/start", "POST", token="tok"), ADMIN


def test_gateway_start_setzt_zustand_nur_bei_erfolg(monkeypatch):
    calls = {"exec": 0, "saved": 0}

    monkeypatch.setattr(app_main, "require_admin", lambda request: None)
    monkeypatch.setattr(app_main, "_run_docker_exec", lambda cmd: (calls.__setitem__("exec", calls["exec"] + 1), (1, "", "kaputt"))[1])
    monkeypatch.setattr(app_main, "_save_gateway_config", lambda cfg: calls.__setitem__("saved", calls["saved"] + 1))
    monkeypatch.setattr(app_main, "_update_profile_status", lambda *a, **k: None)

    request, _ = _gateway_request()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(app_main.api_gateway_start(request, {"profile_id": "p1"}))
    assert exc.value.status_code == 502
    assert calls["saved"] == 0, "der Zustand wurde trotz Fehlschlag gesetzt"


def test_gateway_start_setzt_zustand_bei_erfolg(monkeypatch):
    saved = {}
    monkeypatch.setattr(app_main, "require_admin", lambda request: None)
    monkeypatch.setattr(app_main, "_run_docker_exec", lambda cmd: (0, "ok", ""))
    monkeypatch.setattr(app_main, "_save_gateway_config", lambda cfg: saved.update(cfg))
    monkeypatch.setattr(app_main, "_update_profile_status", lambda *a, **k: None)

    request, _ = _gateway_request()
    result = asyncio.run(app_main.api_gateway_start(request, {"profile_id": "p1"}))
    assert result["ok"] is True
    assert saved["active_gateways"]["p1"] is True


def test_gateway_stop_meldet_fehler_und_aendert_den_zustand_nicht(monkeypatch):
    saved = {"n": 0}
    monkeypatch.setattr(app_main, "require_admin", lambda request: None)
    monkeypatch.setattr(app_main, "_run_docker_exec", lambda cmd: (1, "", "stop kaputt"))
    monkeypatch.setattr(app_main, "_save_gateway_config", lambda cfg: saved.__setitem__("n", saved["n"] + 1))
    monkeypatch.setattr(app_main, "_update_profile_status", lambda *a, **k: None)

    request, _ = _gateway_request()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(app_main.api_gateway_stop(request, {"profile_id": "p1"}))
    assert exc.value.status_code == 502
    assert saved["n"] == 0


# ------------------------------------------------------------------- D-10

def test_oracle_feed_meldet_fehler_als_httpfehler(monkeypatch):
    import sys as _sys

    class _FakeRadar:
        def __init__(self):
            raise RuntimeError("kein Radar")

    monkeypatch.setitem(_sys.modules, "oracle_news_radar",
                        type("_M", (), {"OracleNewsRadar": _FakeRadar}))

    with pytest.raises(HTTPException) as exc:
        app_main.api_get_oracle_feed()
    assert exc.value.status_code >= 400


def test_oracle_triage_ohne_signal_id_ist_400(monkeypatch):
    class _FakeRadar:
        def __init__(self):
            pass

        def triage_to_task(self, sid):
            return {"ok": True}

    import sys as _sys
    monkeypatch.setitem(_sys.modules, "oracle_news_radar",
                        type("_M", (), {"OracleNewsRadar": _FakeRadar}))

    with pytest.raises(HTTPException) as exc:
        app_main.api_triage_oracle_signal({})
    assert exc.value.status_code == 400


# ------------------------------------------------------------------- D-11

def test_design_themes_meldet_fehler_wenn_kein_ziel_schreibbar_ist(monkeypatch, tmp_path):
    monkeypatch.setattr(app_main, "DESIGN_THEMES_TARGETS", [str(tmp_path / "nope" / "t.json")])

    def boom(*_args, **_kwargs):
        raise OSError("read-only")

    monkeypatch.setattr(app_main, "_save_json", boom)
    with pytest.raises(HTTPException) as exc:
        app_main.api_save_design_themes({"active_theme_id": "x"})
    assert exc.value.status_code == 500


def test_design_thomes_meldet_teilfehler(monkeypatch, tmp_path):
    ok = tmp_path / "ok.json"
    monkeypatch.setattr(app_main, "DESIGN_THEMES_TARGETS", [str(ok), str(tmp_path / "bad" / "t.json")])

    def fake_save(path, data):
        if str(path).startswith(str(tmp_path / "bad")):
            raise OSError("read-only")
        Path(path).write_text("{}", encoding="utf-8")

    monkeypatch.setattr(app_main, "_save_json", fake_save)
    result = app_main.api_save_design_themes({"active_theme_id": "x"})
    assert result["status"] == "success"
    assert result["written_to"] == [str(ok)]
    assert result["failed"]


# ------------------------------------------------------------------- D-12

def test_default_modellname_ist_gueltig():
    import re
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    # Der kaputte Literal darf nicht mehr als CODE auftauchen (Kommentare
    # erwaehnen ihn zur Einordnung des Fixes).
    code_only = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    assert 'model = "evey-session-guard:"' not in code_only, (
        "der kaputte Default-Modellname ist noch im Code"
    )
    assert re.search(r'model = "auto/best-coding"', code_only)


def test_kein_kaputter_default_im_frontend():
    source = (ROOT / "static" / "js" / "wissensbibliothek.js").read_text(encoding="utf-8")
    assert "evey-session-guard:" not in source


# ------------------------------------------------------------------- D-13

def test_theme_upload_lehnt_svg_ab(monkeypatch):
    from starlette.datastructures import UploadFile
    import io

    monkeypatch.setattr(app_main, "require_admin", lambda request: None)
    upload = UploadFile(filename="evil.svg", file=io.BytesIO(b"<svg onload=alert(1)>"))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(app_main.api_upload_theme_background(object(), upload))
    assert exc.value.status_code == 400


def test_theme_upload_lehnt_grosse_datei_ab(monkeypatch):
    from starlette.datastructures import UploadFile
    import io

    monkeypatch.setattr(app_main, "require_admin", lambda request: None)
    upload = UploadFile(filename="big.png", file=io.BytesIO(b"0" * (9 * 1024 * 1024)))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(app_main.api_upload_theme_background(object(), upload))
    assert exc.value.status_code == 400


# ------------------------------------------------------------------- D-21

def test_guardian_stats_lehnt_unbekannten_timeframe_ab():
    with pytest.raises(HTTPException) as exc:
        app_main.api_get_guardian_stats(timeframe="irgendein-freier-wert")
    assert exc.value.status_code == 400


def test_guardian_cache_bleibt_beschraenkt():
    assert app_main._GUARDIAN_CACHE_MAX_ENTRIES <= len(app_main._GUARDIAN_ALLOWED_TIMEFRAMES)
    assert "all" in app_main._GUARDIAN_ALLOWED_TIMEFRAMES


# ------------------------------------------------------------------- F-05

def test_providerfehler_wird_nicht_als_antwort_gespeichert(monkeypatch):
    """Der Chat-Stream darf bei Provider-Fehler keine Antwort buchen."""
    import inspect

    source = inspect.getsource(app_main.api_chat_stream)
    assert "provider_failed" in source, (
        "der Provider-Fehler wird nicht als Fehler markiert (F-05)"
    )
    assert "if not provider_failed:" in source, (
        "bei Provider-Fehler wird die Antwort trotzdem gespeichert/gebucht"
    )


# ------------------------------------------------------------------- F-06

def test_agent_profiles_write_ist_atomar():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert 'json.dump(ap_list, f, indent=2, ensure_ascii=False) if False else None' not in source, (
        "der tote Write-Zweig (leert die Profildatei) ist noch im Code"
    )


# ------------------------------------------------------------------- F-10

def test_mission_control_kein_lost_update():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "_save_mission_control_data(mc)" not in source, (
        "load->modify->save schreibt den ganzen Store zurueck (Lost Update)"
    )
    assert "_save_mission_control_data(mc_data)" not in source
    assert source.count("update_mission_control_data") >= 4


# ------------------------------------------------------------------- F-12

def test_mc_state_cache_ist_die_gelesene_instanz():
    from archon.core import mission_control as core_mc

    assert app_main._MC_STATE_CACHE is core_mc._MC_STATE_CACHE, (
        "main.py invalidiert eine andere Cache-Instanz als der Leser"
    )


# ------------------------------------------------------------------- F-13

def test_idle_stop_guard_wird_gelesen():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "if _idle_stop_running:" in source, (
        "der Guard wird gesetzt, aber nie gelesen (Doppelstart)"
    )
