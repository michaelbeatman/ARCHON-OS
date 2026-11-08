"""Cluster Spur A — statische Frontend-Befunde (S-04, F-18, D-16, D-17).

Rot gegen 3269f7e1:

* S-04: ``static/js/skill_markt.js`` interpolierte ``logData.message``
  (Agent-/Tool-Ausgabe) unescaped in ein ``innerHTML``-Template — Stored XSS
  im Cockpit.
* F-18: derselbe Stream benutzte ``logDiv.innerHTML += logRow`` (quadratisches
  Neuparsen des gesamten Logs) ohne Zeilen-Decke.
* D-16: ``static/erp_studio.js`` legte bei API-Fehler eine lokale, erfundene
  gebuchte Rechnung an.
* D-17: ``static/js/wissensbibliothek.js`` meldete "erfolgreich gespeichert",
  ohne die HTTP-Antwort zu pruefen.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(os.environ.get("ARCHON_ROOT") or Path(__file__).resolve().parent.parent)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ------------------------------------------------------------------- S-04

def _log_handler_source() -> str:
    """Schneidet den ``onmessage``-Handler des Live-Logs heraus."""
    source = _read("static/js/skill_markt.js")
    marker = "logEventSource.onmessage = (event) => {"
    start = source.index(marker)
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError("onmessage-Handler nicht gefunden")


def _log_handler_code() -> str:
    """Wie oben, aber ohne Kommentarzeilen (Code-only)."""
    return "\n".join(
        line for line in _log_handler_source().splitlines()
        if not line.strip().startswith("//")
    )


def test_log_stream_escaped_die_agentenausgabe_nicht():
    handler = _log_handler_code()
    assert "${msg}" not in handler, (
        "Die Agenten-Ausgabe wird per Template-Interpolation in HTML gesetzt "
        "(XSS-Vektor)"
    )
    assert "msgEl.textContent" in handler, (
        "Die Nachricht muss ueber textContent gesetzt werden"
    )


def test_log_stream_nutzt_kein_innerHTML_plus():
    handler = _log_handler_code()
    assert "innerHTML +=" not in handler, (
        "innerHTML += parst das komplette Log bei jedem Event neu (quadratisch)"
    )
    assert "MAX_LOG_ROWS" in handler, "das Log braucht eine Zeilen-Decke"


def test_log_stream_wachstum_sinkt(tmp_path):
    """Funktionaler Nachweis mit einem minimalen DOM-Stub (ohne jsdom)."""
    handler = _log_handler_source()
    node = shutil.which("node")
    if not node:
        pytest.skip("node nicht verfuegbar")

    script = """
const created = [];
function makeEl(tag) {
  const el = {
    tagName: tag, className: "", textContent: "", children: [], childElementCount: 0,
    firstElementChild: null, innerHTML: "",
    appendChild(c) { this.children.push(c); this.childElementCount = this.children.length; this.firstElementChild = this.children[0]; return c; },
    removeChild(c) {
      const i = this.children.indexOf(c);
      if (i >= 0) this.children.splice(i, 1);
      this.childElementCount = this.children.length;
      this.firstElementChild = this.children[0] || null;
      return c;
    },
  };
  created.push(el);
  return el;
}
global.document = { createElement: makeEl, getElementById: () => null };
global.EventSource = function () { this.close = function () {}; };

const logDiv = makeEl("div");
logDiv.innerHTML = "";
global.document.getElementById = () => logDiv;

let logEventSource = { onmessage: null };
__HANDLER__

for (let i = 0; i < 500; i++) {
  logEventSource.onmessage({ data: JSON.stringify({ timestamp: Date.now(), message: "msg " + i }) });
}
console.log(JSON.stringify({ rows: logDiv.childElementCount, html: logDiv.innerHTML }));
"""
    script = script.replace("__HANDLER__", handler)

    probe = tmp_path / "orange_a_log_probe.js"
    try:
        probe.write_text(script, encoding="utf-8")
        completed = subprocess.run(
            [node, str(probe)], cwd=str(ROOT), capture_output=True, text=True, timeout=60
        )
        assert completed.returncode == 0, completed.stderr
        result = json.loads(completed.stdout.strip().splitlines()[-1])
        assert result["rows"] <= 200, f"Log waechst unbegrenzt: {result['rows']} Zeilen"
    finally:
        if probe.exists():
            probe.unlink()


# ------------------------------------------------------------------- D-16

def test_erp_studio_erfindet_keine_rechnung_bei_api_fehler():
    source = _read("static/erp_studio.js")
    assert "if (!createdViaApi)" not in source, (
        "Bei API-Fehler wird eine lokale, erfundene gebuchte Rechnung angelegt"
    )
    assert "if (!convertedViaApi)" not in source, (
        "Bei API-Fehler wird auch bei der Umwandlung ein Beleg erfunden"
    )
    assert "cachedOffers.unshift" not in source, (
        "Es darf keine Rechnung lokal erfunden werden"
    )


def test_erp_studio_meldet_den_fehler():
    source = _read("static/erp_studio.js")
    assert "resp.ok" in source
    assert "Es wurde nichts gebucht" in source, (
        "ein API-Fehler muss sichtbar werden (Fehlermeldung statt stiller Ersatzrechnung)"
    )


# ------------------------------------------------------------------- D-17

def test_wissensbibliothek_prueft_die_http_antwort():
    source = _read("static/js/wissensbibliothek.js")
    idx = source.index('const settingsResp = await fetch("/api/settings"')
    block = source[idx:idx + 1200]
    assert "settingsResp.ok" in block, (
        "Der Save-Block prueft kein res.ok — ein 500 wird als Erfolg gemeldet"
    )


def test_wissensbibliothek_meldet_erfolg_nur_bei_ok():
    source = _read("static/js/wissensbibliothek.js")
    idx = source.index("erfolgreich gespeichert!")
    window = source[max(0, idx - 3000):idx]
    assert "throw new Error" in window or "!settingsResp.ok" in window, (
        "Vor dem Erfolgs-Toast muss ein Fehlerpfad liegen"
    )
