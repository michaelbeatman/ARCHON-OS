"""A7-Leitplanke: Router oeffnen die State-DB nicht selbst.

Hintergrund (A5-Etappe 5): Der Pilot in `archon/routers/system.py` hat gezeigt,
wie eine request-scoped DB-Verbindung als `Depends()` sauber deklariert wird.
Der Rollout auf die beiden verbleibenden Kandidaten ist **nicht** erfolgt, weil
sie sync (`def`) sind: eine per Dependency erzeugte sqlite3-Verbindung darf
nicht in einem anderen Threadpool-Thread benutzt werden
(`ProgrammingError: SQLite objects created in a thread can only be used in
that same thread`). Der Fehler tritt zudem lastabhaengig auf, weil Python
Thread-Idents recycelt — er kann in Tests gruen bleiben und erst im Betrieb
knallen.

Test 1 haelt fest: kein Router-Handler oeffnet `_get_state_db()` /
`_get_profile_state_db()` direkt.
Test 2 pinnt die einzige bekannte Ausnahme (avatars.db in hermes_profiles.py),
damit eine dritte Stelle auffaellt statt still mitzuwachsen.

Rot-Beweis fuer Test 1 gegen den Vorstand des Piloten:
    mkdir -p /tmp/old && git show 5085cd91:archon/routers/system.py > /tmp/old/system.py
    ARCHON_ROUTERS_DIR=/tmp/old pytest tests/test_a7_router_db_open.py -k state_db
"""

import ast
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTERS_DIR = os.environ.get("ARCHON_ROUTERS_DIR", os.path.join(REPO, "archon", "routers"))

FORBIDDEN_STATE_DB = {"_get_state_db", "_get_profile_state_db"}

# Dokumentierte Ausnahme: Avatar-Sync in den Hermes-WebUI-Store.
# Bleibt im Handler, weil dort (a) der Pfad erst zur Laufzeit zwischen zwei
# Kandidaten gewaehlt wird, (b) ein Existenz-Guard den Block ueberspringt und
# (c) der Handler sync ist (Threadpool) — eine Dependency wuerde die
# Verbindung in einem anderen Thread erzeugen.
ALLOWED_SQLITE_CONNECT = {
    ("hermes_profiles.py", "api_save_hermes_profile"),
    ("hermes_profiles.py", "api_upload_hermes_profile_avatar"),
}


def _dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return "%s.%s" % (_dotted(node.value), node.attr)
    return ""


def _route_functions(path):
    """(Name, Knoten) aller Funktionen mit @router.<verb>-Dekorator."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                    and isinstance(dec.func.value, ast.Name)
                    and dec.func.value.id == "router"):
                yield node.name, node
                break


def _router_files():
    return [
        os.path.join(ROUTERS_DIR, fn)
        for fn in sorted(os.listdir(ROUTERS_DIR))
        if fn.endswith(".py")
    ]


def test_no_router_handler_opens_state_db_directly():
    """State-DB gehoert in eine Dependency, nicht in den Handler-Rumpf."""
    offenders = []
    for path in _router_files():
        for name, fn in _route_functions(path):
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and _dotted(node.func) in FORBIDDEN_STATE_DB:
                    offenders.append((os.path.basename(path), name, node.lineno,
                                      _dotted(node.func)))
    assert not offenders, (
        "Router-Handler oeffnet die State-DB selbst (Datei, Route, Zeile, Aufruf): "
        "%s — nutze stattdessen Depends(get_state_db_dep)" % offenders
    )


def test_sqlite_connect_in_routers_is_only_the_known_exception():
    """Nur die dokumentierten Avatar-Ausnahmen duerfen sqlite3.connect nutzen."""
    found = set()
    for path in _router_files():
        for name, fn in _route_functions(path):
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and _dotted(node.func) == "sqlite3.connect":
                    found.add((os.path.basename(path), name))
    unexpected = found - ALLOWED_SQLITE_CONNECT
    assert not unexpected, (
        "Neue direkte sqlite3-Verbindung in einem Router-Handler: %s — bitte "
        "bewerten (Dependency? Thread-Affinitaet? Pool?) und ALLOWED_SQLITE_CONNECT "
        "nur nach pruefbarer Begruendung erweitern" % sorted(unexpected)
    )
