# -*- coding: utf-8 -*-
"""Welle W6-D — Regressionstests fuer D09-H1 und D09-M4.

D09-H1: der Image-Digest im Manifest/`docker-compose.yml` und die Adapter-API
sind ein hartes Gate. Positivprobe auf den echten Produktivdateien, Negativ-
proben fuer Digest-Drift, Mount-Drift, Signatur-Drift, fehlende Patch-Marker
und Syntaxfehler. D09-M4: der letzte rohe ``Dict = Body(...)`` ist durch ein
Pydantic-Modell ersetzt; die Route bleibt eine 501-Notbremse.

Keine Container, keine Secrets, kein PostgreSQL, kein Coroutine-Replay.
Shell ist in Subagent-Sessions oft gesperrt — der Koordinator verifiziert
zentral (Ruff/MyPy/Pytest).
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _lesen(relativ: str) -> str:
    return (ROOT / relativ).read_text(encoding="utf-8")


def _smoke() -> Any:
    """Import im Funktionskoerper — haelt den Modul-Import am Dateianfang sauber."""
    import scripts.telegram_adapter_smoke_test as smoke

    return smoke


def _manifest_json() -> dict[str, Any]:
    return json.loads(_lesen("scripts/patches/MANIFEST.json"))


# ---------------------------------------------------------------------------
# D09-H1 — Image-Digest-Pinning + Adapter-Smoke-Test als hartes Gate
# ---------------------------------------------------------------------------


def test_d09_h1_gate_gruen_auf_produktivdateien(capsys: pytest.CaptureFixture[str]) -> None:
    """Der echte Produktivpfad muss Exit 0 liefern — sonst ist das Gate wertlos."""
    smoke = _smoke()
    bestanden, fehler = smoke.alle_pruefungen()
    assert fehler == [], fehler
    assert len(bestanden) == 4, bestanden
    assert smoke.main() == 0
    ausgabe = capsys.readouterr().out
    assert "ERGEBNIS: GRUEN" in ausgabe
    assert "FAIL" not in ausgabe


def test_d09_h1_manifest_digest_deckt_sich_mit_beiden_compose_services() -> None:
    """Digest ist in Manifest UND in beiden Hermes-Services identisch gepinnt."""
    smoke = _smoke()
    manifest = _manifest_json()
    digest = manifest["hermes_image"]["digest"]
    compose = _lesen("docker-compose.yml")
    assert digest.startswith("sha256:")
    for service in manifest["hermes_image"]["services"]:
        block = smoke._dienst_block(compose, service)
        assert f"{manifest['hermes_image']['reference']}@{digest}" in block


def test_d09_h1_digest_drift_wird_erkannt(tmp_path: Path) -> None:
    """Image-Bump ohne Manifest-Update muss das Gate rot machen."""
    smoke = _smoke()
    compose = _lesen("docker-compose.yml").replace(
        "sha256:276d44685c65c0cb2a25f190b63c65c8906f9dc76486fb1c05ae71b5826bda08",
        "sha256:" + "0" * 64,
    )
    ziel = tmp_path / "docker-compose.yml"
    ziel.write_text(compose, encoding="utf-8")
    _bestanden, fehler = smoke.alle_pruefungen(compose_pfad=ziel)
    assert any("nicht auf" in meldung and "gepinnt" in meldung for meldung in fehler), fehler


def test_d09_h1_mount_drift_wird_erkannt(tmp_path: Path) -> None:
    """Wird der Read-Only-Mount entfernt oder entschaerft, muss das Gate rot werden."""
    smoke = _smoke()
    compose = _lesen("docker-compose.yml").replace(
        "./scripts/patches/hermes_telegram_adapter.py:"
        "/opt/hermes/plugins/platforms/telegram/adapter.py:ro",
        "./scripts/patches/hermes_telegram_adapter.py:"
        "/opt/hermes/plugins/platforms/telegram/adapter.py:rw",
    )
    ziel = tmp_path / "docker-compose.yml"
    ziel.write_text(compose, encoding="utf-8")
    _bestanden, fehler = smoke.alle_pruefungen(compose_pfad=ziel)
    assert any("Mount" in meldung and "fehlt" in meldung for meldung in fehler), fehler


def test_d09_h1_api_signatur_drift_wird_erkannt() -> None:
    """Entferntes register(ctx) oder verdrehte Hook-Signatur muss auffallen."""
    smoke = _smoke()
    manifest = _manifest_json()
    quelle = _lesen("scripts/patches/hermes_telegram_adapter.py")

    ohne_register = quelle.replace("def register(ctx) -> None:", "def register(ctx, extra) -> None:")
    fehler = smoke.pruefe_adapter_api(manifest, ohne_register)
    assert any("API-Signatur register()" in meldung for meldung in fehler), fehler

    ohne_hook = quelle.replace("def telegram_deps_present() -> bool:", "def _deps_present() -> bool:")
    fehler = smoke.pruefe_adapter_api(manifest, ohne_hook)
    assert any("API-Funktion telegram_deps_present()" in meldung for meldung in fehler), fehler


def test_d09_h1_verlorener_patch_marker_wird_erkannt() -> None:
    """Nach einem Image-Bump ohne Patch darf das Gate nicht gruen werden."""
    smoke = _smoke()
    manifest = _manifest_json()
    quelle = _lesen("scripts/patches/hermes_telegram_adapter.py")
    ohne_patch = quelle.replace("_archon_req", "_archon_call")
    fehler = smoke.pruefe_adapter_api(manifest, ohne_patch)
    assert any("Patch-Marker '_archon_req'" in meldung for meldung in fehler), fehler


def test_d09_h1_syntaxfehler_wird_erkannt() -> None:
    """compileall-artige Syntaxpruefung ist Teil des harten Gates."""
    smoke = _smoke()
    manifest = _manifest_json()
    fehler = smoke.pruefe_adapter_api(manifest, "def kaputt(:\n")
    assert any("Syntaxfehler" in meldung for meldung in fehler), fehler


def test_d09_h1_main_exit_1_bei_fehler(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Der CI-Vertrag ist Exit-Code: ein Fehler muss Exit 1 liefern."""
    smoke = _smoke()
    monkeypatch.setattr(smoke, "alle_pruefungen", lambda: (["Manifest geladen"], ["FAIL Dummy"]))
    assert smoke.main() == 1
    ausgabe = capsys.readouterr().out
    assert "FAIL  FAIL Dummy" in ausgabe
    assert "ERGEBNIS: ROT" in ausgabe


# ---------------------------------------------------------------------------
# D09-M4 — letzter roher Dict-Body in main.py
# ---------------------------------------------------------------------------


def _baum_main() -> ast.Module:
    return ast.parse(_lesen("main.py"))


def _sandbox_route(baum: ast.Module) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for knoten in baum.body:
        if not isinstance(knoten, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dekorator in knoten.decorator_list:
            if (
                isinstance(dekorator, ast.Call)
                and isinstance(dekorator.func, ast.Attribute)
                and dekorator.func.attr == "post"
            ):
                args = [ast.literal_eval(arg) for arg in dekorator.args]
                if args and args[0] == "/api/sandbox":
                    return knoten
    raise AssertionError("Route POST /api/sandbox fehlt")


def test_d09_m4_kein_roher_dict_body_mehr() -> None:
    """Weder `Dict = Body(...)` noch irgendein Body()-Aufruf bleibt in main.py."""
    baum = _baum_main()
    rohe = [
        ast.unparse(knoten)
        for knoten in ast.walk(baum)
        if isinstance(knoten, ast.Call)
        and isinstance(knoten.func, ast.Name)
        and knoten.func.id == "Body"
    ]
    assert rohe == [], rohe
    route = _sandbox_route(baum)
    annotationen = {arg.arg: ast.unparse(arg.annotation) for arg in route.args.args if arg.annotation}
    assert annotationen.get("payload") == "SandboxLegacyRequest", annotationen


def test_d09_m4_modell_ignoriert_unbekannte_felder() -> None:
    """Das Ersatzmodell validiert ein JSON-Objekt und toleriert alte Clients."""
    from pydantic import BaseModel, ConfigDict

    baum = _baum_main()
    klasse = next(
        knoten
        for knoten in baum.body
        if isinstance(knoten, ast.ClassDef) and knoten.name == "SandboxLegacyRequest"
    )
    namensraum: dict[str, Any] = {"BaseModel": BaseModel, "ConfigDict": ConfigDict}
    exec(compile(ast.Module(body=[klasse], type_ignores=[]), "<main.py>", "exec"), namensraum)
    modell = namensraum["SandboxLegacyRequest"]
    instanz = modell(code="print(1)", unbekannt="ignoriert")
    assert not hasattr(instanz, "unbekannt")


def test_d09_m4_notbremse_bleibt_501() -> None:
    """Die Route darf auch nach dem Schema-Fix nichts ausfuehren."""
    route = _sandbox_route(_baum_main())
    quellen = [ast.unparse(knoten) for knoten in ast.walk(route) if isinstance(knoten, ast.Raise)]
    assert any("status_code=501" in quelle for quelle in quellen), quellen
    aufrufe = [
        ast.unparse(knoten.func)
        for knoten in ast.walk(route)
        if isinstance(knoten, ast.Call) and isinstance(knoten.func, ast.Name)
    ]
    assert "require_admin" in aufrufe, aufrufe
