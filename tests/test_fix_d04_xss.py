"""Cluster 4 — D-04: Chat-Markdown ohne Sanitizer (XSS im App-Origin).

Rot gegen HEAD (909421d6): ``formatMarkdownText`` (``static/index.html:2646``)
gibt ``window.marked.parse(str)`` roh zurueck; ``DOMPurify`` kommt im Repo
nirgends vor. Dieselben Sinks: ``chat_engine.js`` (Chat-Bubble),
``agent_profiles.js``, ``prompt_studio.js`` sowie zwei direkte
``marked.parse``-Aufrufe in ``index.html``.

Geprueft wird:
1. DOMPurify ist als Datei vorhanden und wird vor ``chat_engine.js`` geladen.
2. Jeder ``marked.parse``-Aufruf laeuft durch ``sanitizeHtml``/``DOMPurify``
   (Ausnahme: der Helfer selbst).
3. **Funktional**: die *echte* ``formatMarkdownText``-Funktion aus
   ``index.html`` wird in Node mit jsdom + marked + DOMPurify ausgefuehrt und
   muss ``onerror``/``<script>`` entfernen.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("ARCHON_ROOT") or os.path.dirname(_HERE)
INDEX_HTML = os.path.join(ROOT, "static", "index.html")
DOMPURIFY_JS = os.path.join(ROOT, "static", "vendor", "dompurify.min.js")
MARKED_JS = os.path.join(ROOT, "static", "marked.min.js")

JS_SINKS = [
    "static/js/chat_engine.js",
    "static/js/agent_profiles.js",
    "static/js/prompt_studio.js",
]

HELPER_NAMES = ("sanitizeHtml", "formatMarkdownText")


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


# --------------------------------------------------------------------------
# 1. Dependency vorhanden und richtig eingebunden
# --------------------------------------------------------------------------

def test_dompurify_is_vendored():
    assert os.path.isfile(DOMPURIFY_JS), "DOMPurify fehlt unter static/vendor/"
    assert os.path.getsize(DOMPURIFY_JS) > 10_000, "DOMPurify-Datei ist zu klein/leer"
    assert "DOMPurify" in _read(DOMPURIFY_JS)[:2000]


def test_dompurify_loaded_before_chat_engine():
    html = _read(INDEX_HTML)
    purify_pos = html.find("vendor/dompurify.min.js")
    chat_pos = html.find("js/chat_engine.js")
    assert purify_pos != -1, "index.html laedt DOMPurify nicht"
    assert chat_pos != -1
    assert purify_pos < chat_pos, "DOMPurify muss vor chat_engine.js geladen werden"


# --------------------------------------------------------------------------
# 2. Kein roher marked.parse-Aufruf ausserhalb des Sanitizer-Helfers
# --------------------------------------------------------------------------

def _enclosing_function(source: str, position: int) -> str:
    start = source.rfind("function ", 0, position)
    if start == -1:
        return ""
    match = re.match(r"function\s+([A-Za-z_$][\w$]*)", source[start:start + 80])
    return match.group(1) if match else ""


def _unsanitized_marked_calls(source: str) -> list[int]:
    offenders: list[int] = []
    for match in re.finditer(r"marked\.parse\s*\(", source):
        prefix = source[max(0, match.start() - 80):match.start()]
        if "sanitizeHtml(" in prefix or "DOMPurify.sanitize(" in prefix:
            continue
        if _enclosing_function(source, match.start()) in HELPER_NAMES:
            continue
        offenders.append(source.count("\n", 0, match.start()) + 1)
    return offenders


@pytest.mark.parametrize("relative_path", ["static/index.html"] + JS_SINKS)
def test_no_raw_marked_parse(relative_path):
    source = _read(os.path.join(ROOT, relative_path))
    offenders = _unsanitized_marked_calls(source)
    assert not offenders, (
        f"{relative_path}: marked.parse ohne Sanitizer in Zeile(n) {offenders}"
    )
    if "marked.parse" not in source:
        # Kein eigener Parser im File: dann muss der gehaertete Helfer die
        # einzige Markdown->HTML-Bruecke sein (sonst gaebe es einen stillen Sink).
        assert "formatMarkdownText" in source, (
            f"{relative_path}: rendert Markdown ohne den Sanitizer-Helfer"
        )


def test_index_html_defines_sanitizer_helper():
    html = _read(INDEX_HTML)
    assert "DOMPurify.sanitize(" in html
    assert "USE_PROFILES" in html
    assert re.search(r"function\s+sanitizeHtml\s*\(", html)


# --------------------------------------------------------------------------
# 3. Funktionaler Nachweis mit der echten Funktion aus index.html
# --------------------------------------------------------------------------

def _extract_function(source: str, name: str) -> str:
    """Schneidet ``function <name>(...) {...}`` per Klammerzaehlung heraus."""
    match = re.search(rf"function\s+{name}\s*\(", source)
    if not match:
        raise AssertionError(f"Funktion {name} nicht gefunden")
    start = match.start()
    brace = source.find("{", match.end())
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(f"Funktion {name} nicht abgeschlossen")


NODE_SCRIPT = """
const fs = require('fs');
const { JSDOM } = require('jsdom');

const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>', { runScripts: 'outside-only' });
const { window } = dom;
global.window = window;
global.document = window.document;

window.eval(fs.readFileSync(process.env.MARKED_PATH, 'utf8'));
window.eval(fs.readFileSync(process.env.PURIFY_PATH, 'utf8'));

window.escapeHtml = function (value) {
  return String(value === null || value === undefined ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
};
global.escapeHtml = window.escapeHtml;

__FUNCTIONS__

const payload = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=2<\\/script>'
  + '\\n\\n**fett** und <a href="javascript:alert(1)">link</a>';

const html = formatMarkdownText(payload);
console.log(JSON.stringify({ html: html, hasMarkdown: html.indexOf('<strong>') !== -1 }));
"""


@pytest.fixture(scope="module")
def node_available():
    if not shutil.which("node"):
        pytest.skip("node nicht verfuegbar")
    node_modules = os.path.join(ROOT, "node_modules", "jsdom")
    if not os.path.isdir(node_modules):
        pytest.skip("jsdom nicht installiert")
    return True


def test_format_markdown_sanitizes_xss(node_available, tmp_path):
    html = _read(INDEX_HTML)
    functions = "\n\n".join(
        _extract_function(html, name) for name in HELPER_NAMES
    )
    script = NODE_SCRIPT.replace("__FUNCTIONS__", functions)
    script_path = tmp_path / "sanitize_probe.js"
    script_path.write_text(script, encoding="utf-8")

    env = dict(os.environ)
    env["MARKED_PATH"] = MARKED_JS
    env["PURIFY_PATH"] = DOMPURIFY_JS
    # Das Probe-Skript liegt ausserhalb des Repos; ohne NODE_PATH findet Node
    # das installierte jsdom nicht.
    env["NODE_PATH"] = os.path.join(ROOT, "node_modules")
    completed = subprocess.run(
        ["node", str(script_path)],
        cwd=ROOT, capture_output=True, text=True, timeout=120, env=env,
    )
    assert completed.returncode == 0, completed.stderr

    result = json.loads(completed.stdout.strip().splitlines()[-1])
    rendered = result["html"]
    assert "onerror" not in rendered.lower(), f"XSS-Vektor ueberlebt: {rendered}"
    assert "<script" not in rendered.lower(), f"<script> ueberlebt: {rendered}"
    assert "javascript:" not in rendered.lower(), f"javascript:-URL ueberlebt: {rendered}"
    assert result["hasMarkdown"], "Markdown-Rendering darf nicht komplett abgeschaltet werden"
