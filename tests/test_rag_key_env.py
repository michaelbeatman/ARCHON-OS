"""Punkt B: RAG-API-Key kommt aus der Umgebung — fail-fast, kein Default.

Der Key stand als Klartext-Literal im Code. Die Tests pruefen den Ersatz:

* fehlend/leer/Whitespace -> ``MissingRagApiKeyError`` und **kein** subprocess,
* gesetzt -> Wert wird durchgereicht, die Meldung enthaelt den Wert nie,
* Startcheck meldet den Fehlfall als ERROR, ohne den Start zu kippen,
* das ``--api-key``-Argument ist im Code kein Literal mehr (AST-Guard).

Der Secret-Wert wird in diesen Dateien bewusst nirgends notiert — auch nicht
als Prefix. Der AST-Guard braucht ihn nicht.
"""

import ast
import logging
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import main  # noqa: E402

ENV = "ANYTHINGLLM_API_KEY"
FALSCHER_KEY = "probe-key-nur-im-test"


def _ohne_key(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)


def _mit_key(monkeypatch, wert=FALSCHER_KEY):
    monkeypatch.setenv(ENV, wert)


# --------------------------------------------------------------- _get_rag_api_key

def test_fehlt_wirft_klar_benannte_exception(monkeypatch):
    _ohne_key(monkeypatch)

    with pytest.raises(main.MissingRagApiKeyError) as fehler:
        main._get_rag_api_key()

    assert ENV in str(fehler.value), str(fehler.value)
    assert isinstance(fehler.value, RuntimeError)


@pytest.mark.parametrize("wert", ["", "   ", "\t\n"])
def test_leerer_oder_blanker_wert_zaehlt_als_fehlt(monkeypatch, wert):
    _mit_key(monkeypatch, wert)

    with pytest.raises(main.MissingRagApiKeyError):
        main._get_rag_api_key()


def test_gesetzter_wert_wird_zurueckgegeben(monkeypatch):
    _mit_key(monkeypatch, "  " + FALSCHER_KEY + "  ")

    assert main._get_rag_api_key() == FALSCHER_KEY


def test_meldung_enthaelt_den_key_nicht(monkeypatch):
    """Fehlermeldung nennt die Variable, nie einen Wert."""
    _mit_key(monkeypatch, "")
    with pytest.raises(main.MissingRagApiKeyError) as fehler:
        main._get_rag_api_key()

    assert FALSCHER_KEY not in str(fehler.value)
    assert "your_anythingllm_api_key_here" not in str(fehler.value)


def test_ohne_key_startet_kein_subprocess(monkeypatch):
    """Der Befehlsbau bricht VOR dem Popen ab — kein Start mit leerem Key."""
    _ohne_key(monkeypatch)
    gestartet = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: gestartet.append(a))

    with pytest.raises(main.MissingRagApiKeyError):
        cmd = [sys.executable, "tools/sync_vault_to_rag.py",
               "--api-key", main._get_rag_api_key(), "--all"]
        subprocess.Popen(cmd)

    assert gestartet == []


# --------------------------------------------------------------- Startcheck

def test_startcheck_meldet_fehlen_als_error(monkeypatch, caplog):
    _ohne_key(monkeypatch)

    with caplog.at_level(logging.ERROR, logger="archon_os"):
        ergebnis = main._check_rag_api_key_config()

    assert ergebnis is False
    meldungen = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert any(ENV in m for m in meldungen), meldungen
    assert any("[RAG-Sync]" in m for m in meldungen), meldungen


def test_startcheck_ist_am_lifespan_registriert():
    assert main._check_rag_api_key_config in main._STARTUP_HOOKS, (
        "Der RAG-Key-Startcheck ist nicht registriert — fehlende Keys blieben still")


def test_startcheck_kippt_den_start_nicht(monkeypatch):
    """Ein fehlender Key ist laut, aber kein Startabbruch (Begruendung im Bericht)."""
    _ohne_key(monkeypatch)

    assert main._check_rag_api_key_config() is False


def test_startcheck_mit_key_loggt_keinen_wert(monkeypatch, caplog):
    _mit_key(monkeypatch)

    with caplog.at_level(logging.DEBUG, logger="archon_os"):
        assert main._check_rag_api_key_config() is True

    assert all(FALSCHER_KEY not in r.getMessage() for r in caplog.records), (
        "Der Key darf in keiner Log-Zeile stehen")


# --------------------------------------------------------------- Statik-Guards

def _main_quelle():
    return open(os.path.join(REPO, "main.py"), encoding="utf-8").read()


def test_argv_baut_key_aus_der_umgebung():
    """``--api-key`` bekommt einen Funktionsaufruf, kein String-Literal."""
    baum = ast.parse(_main_quelle())
    treffer = []

    for node in ast.walk(baum):
        if not isinstance(node, ast.List):
            continue
        for index, element in enumerate(node.elts):
            if isinstance(element, ast.Constant) and element.value == "--api-key":
                assert index + 1 < len(node.elts), "kein Argument nach --api-key"
                treffer.append(node.elts[index + 1])

    assert treffer, "kein --api-key-Argument mehr in main.py gefunden"
    for argument in treffer:
        assert isinstance(argument, ast.Call), ast.dump(argument)
        assert getattr(argument.func, "id", "") == "_get_rag_api_key", ast.dump(argument)


def test_kein_hartkodierter_rag_key_mehr_in_main():
    """Heuristik ohne den Secret-Wert: kein Literal der Form XXXX-XXXX-XXXX-XXXX."""
    import re

    verdacht = re.findall(r"[A-Z0-9]{5}-[A-Z0-9]{7}-[A-Z0-9]{7}-[A-Z0-9]{7}", _main_quelle())
    assert verdacht == [], (
        "%d hartkodierte Key-Literale in main.py gefunden" % len(verdacht))


def test_env_example_hat_platzhalter_und_keinen_echten_key():
    inhalt = open(os.path.join(REPO, ".env.example"), encoding="utf-8").read()

    assert "%s=your_anythingllm_api_key_here" % ENV in inhalt, inhalt
    assert "your_anythingllm_api_key_here" in inhalt
