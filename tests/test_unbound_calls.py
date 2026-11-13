"""Regressionsbremse gegen eine ganze Fehlerklasse: ungebundene Aufrufe.

``main.py`` ist historisch gewachsen; Funktionen wurden in Router ausgelagert,
die Aufrufstelle blieb stehen. Ein ``NameError`` faellt dann erst im Betrieb auf
— und nur, wenn der Codepfad ueberhaupt ausgefuehrt wird.

Real aufgetreten (2026-11, Gate-Approve-Defekt):

    api_save_hermes_profile    main.py:2890  <- archon/routers/hermes_profiles.py:98
    api_delete_hermes_profile  main.py:2893  <- archon/routers/hermes_profiles.py:584
    get_llm_prices             main.py:4920  <- archon/routers/llm_providers.py:215
                                (still: stand in ``except Exception: pass``)
    parse_docker_stream_bytes  main.py:8936  <- utils/docker_client.py:250
                                (hart: kein try, Endpunkt antwortete 500)

Der Test sammelt jeden ``ast.Call`` mit ``ast.Name``-Funktion (also ``foo(...)``,
nicht ``obj.foo(...)``) und vergleicht gegen alle Bindungen der Datei. Er ist
bewusst grob: er fragt "wird dieser Name ueberhaupt irgendwo gebunden?", nicht
"ist er in diesem Scope sichtbar?" — genau die grobe Frage, die den Defekt
gefunden haette. Ein Treffer ist immer ein Fehler.
"""

import ast
import builtins
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_PY = os.path.join(REPO, "main.py")


class _Binder(ast.NodeVisitor):
    """Sammelt jeden Namen, den die Datei bindet (def/class/arg/Zuweisung/Import)."""

    def __init__(self):
        self.names = set()

    def _args(self, args):
        for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
            self.names.add(a.arg)
        if args.vararg:
            self.names.add(args.vararg.arg)
        if args.kwarg:
            self.names.add(args.kwarg.arg)

    def _record_function(self, node) -> None:
        self.names.add(node.name)
        self._args(node.args)
        self.generic_visit(node)

    def visit_FunctionDef(self, node) -> None:
        self._record_function(node)

    def visit_AsyncFunctionDef(self, node) -> None:
        self._record_function(node)

    def visit_Lambda(self, node):
        self._args(node.args)
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self.names.add(node.name)
        self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)
        self.generic_visit(node)

    def visit_Import(self, node):
        for alias in node.names:
            self.names.add(alias.asname or alias.name.split(".")[0])

    def visit_ImportFrom(self, node):
        for alias in node.names:
            if alias.name != "*":
                self.names.add(alias.asname or alias.name)

    def visit_ExceptHandler(self, node):
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_Global(self, node):
        self.names.update(node.names)

    def visit_Nonlocal(self, node):
        self.names.update(node.names)

    def visit_MatchAs(self, node):
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node):
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchMapping(self, node):
        if node.rest:
            self.names.add(node.rest)
        self.generic_visit(node)


def _unbound_calls(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    binder = _Binder()
    binder.visit(tree)
    bound = binder.names | set(dir(builtins))

    treffer = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name not in bound:
                treffer.setdefault(name, []).append(node.lineno)
    return {name: sorted(set(zeilen)) for name, zeilen in treffer.items()}


def test_main_py_ruft_nur_gebundene_namen_auf():
    treffer = _unbound_calls(MAIN_PY)
    assert not treffer, (
        "main.py ruft Namen auf, die es nirgends bindet (NameError zur Laufzeit): "
        "%s" % ", ".join("%s in Zeile(n) %s" % (n, z[:5]) for n, z in sorted(treffer.items())))
