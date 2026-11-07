"""Regressionstest: kein Modulname darf in main.py doppelt zugewiesen werden.

Hintergrund (A5-Etappe 2): `ROLES_FILE` und `SERVICES_FILE` waren je zweimal auf
Modulebene zugewiesen — einmal ueber MEMORY_DIR, einmal ueber WORKSPACE_DIR.
Python nimmt still die letzte Zuweisung; die erste ist wirkungslos und macht
jedes Lesen der Datei zu einer Fehlinterpretation. Dieser Test macht solche
Doppelzuweisungen dauerhaft sichtbar.

Rot-Beweis gegen den Vorstand:
    ARCHON_MAIN_PATH=/pfad/zu/altem/main.py pytest tests/test_a5_no_duplicates.py
"""

import ast
import os
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_PATH = os.environ.get("ARCHON_MAIN_PATH", os.path.join(REPO, "main.py"))


def _assignments_per_name(path):
    """{Name: [Zeilen]} aller Modul-Ebene-Zuweisungen (auch annotierte)."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    seen = defaultdict(list)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                seen[target.id].append(node.lineno)
    return seen


def test_no_duplicate_module_level_assignments():
    """Jeder Modulname wird genau einmal zugewiesen."""
    seen = _assignments_per_name(MAIN_PATH)
    duplicates = {name: lines for name, lines in seen.items() if len(lines) > 1}
    assert not duplicates, (
        "Modulname(n) mehrfach auf Modulebene zugewiesen in %s — nur die letzte "
        "Zuweisung wirkt, alle frueheren sind still wirkungslos: %s"
        % (MAIN_PATH, duplicates)
    )
