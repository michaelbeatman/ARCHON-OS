"""Regressionstests fuer A5-Etappe 1: unveraenderliche Konstanten ausgelagert.

Drei Zusicherungen, jede einzeln pruefbar:

1. `test_constants_not_defined_in_main` — AST-Scan: die fuenf Namen sind in
   `main.py` **nicht** mehr auf Modulebene zugewiesen. Das ist der eigentliche
   Regressionsschutz: legt jemand die Definition zurueck, wird der Test rot.
2. `test_constants_bound_in_main` — `import main` und `getattr`; zusaetzlich
   Identitaet gegen `archon.core.constants` (keine stille Kopie, kein Fallback).
3. `test_constants_module_has_no_mutable_state` — `archon/core/constants.py`
   enthaelt auf Modulebene nur unveraenderliche Werte (str/int/float/tuple).
   Ein Dict/Set/List-Import dort waere die Rueckkehr von Fallstrick 24.

Fuer den Rot-Beweis laesst sich die zu pruefende Datei umbiegen:
    ARCHON_MAIN_PATH=/pfad/zu/altem/main.py pytest tests/test_a5_constants.py -k not_defined
"""

import ast
import os
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TESTS_DIR)
MAIN_PATH = os.environ.get("ARCHON_MAIN_PATH", os.path.join(REPO, "main.py"))

CONSTANT_NAMES = (
    "_AUTH_PUBLIC_PREFIXES",
    "_AUTH_PROTECTED_PREFIXES",
    "_DECISION_TYPEN",
    "DELEGATION_PROTOCOL_PROMPT",
    "STUDIO_BG_UPLOAD_DIR",
)

IMMUTABLE = (str, int, float, bool, tuple, frozenset, type(None))


def _module_level_assignments(path):
    """{Name: Zeile} aller Modul-Ebene-Zuweisungen (auch annotierte)."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                found[target.id] = (node.lineno, value)
    return found


def test_constants_not_defined_in_main():
    """Die fuenf Namen duerfen in main.py nicht mehr definiert sein."""
    defined = _module_level_assignments(MAIN_PATH)
    still = {n: defined[n][0] for n in CONSTANT_NAMES if n in defined}
    assert not still, (
        "Konstanten sind wieder in %s definiert (Zeile: %s) — sie gehoeren "
        "ausschliesslich nach archon/core/constants.py" % (MAIN_PATH, still)
    )


def test_constants_bound_in_main():
    """main.py muss alle fuenf Namen gebunden haben — und zwar dasselbe Objekt."""
    sys.path.insert(0, REPO)
    import main
    import archon.core.constants as constants

    for name in CONSTANT_NAMES:
        assert hasattr(main, name), "%s ist in main.py nicht gebunden" % name
        assert getattr(main, name) is getattr(constants, name), (
            "%s in main.py ist nicht dasselbe Objekt wie in archon.core.constants "
            "(Kopie oder Neudefinition statt Import)" % name
        )
        assert isinstance(getattr(main, name), IMMUTABLE), (
            "%s hat einen mutablen Typ %s" % (name, type(getattr(main, name)).__name__)
        )


def test_constants_module_has_no_mutable_state():
    """constants.py darf auf Modulebene keinen mutablen State definieren."""
    path = os.path.join(REPO, "archon", "core", "constants.py")
    defined = _module_level_assignments(path)
    assert defined, "constants.py definiert keine Modul-Konstanten — falscher Pfad?"

    mutable = {}
    for name, (_line, value) in defined.items():
        if isinstance(value, (ast.List, ast.Dict, ast.Set)):
            mutable[name] = type(value).__name__
        elif isinstance(value, ast.Call):
            func = getattr(value.func, "id", "")
            if func in {"list", "dict", "set"}:
                mutable[name] = "%s()" % func
    assert not mutable, (
        "mutable Werte in constants.py: %s — Listen/Dicts/Sets gehoeren nicht "
        "in ein Konstantenmodul (Fallstrick 24)" % mutable
    )
