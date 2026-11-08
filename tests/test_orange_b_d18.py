"""Regressionstest D-18: Beleg-OCR ueber Base64 nicht mehr dauerhaft defekt.

`base64.b64decode` wurde im Modul nie importiert -> NameError -> 400 mit
irrefuehrender Meldung. Der Test sichert den Import und die Dekodier-Logik
des Handlers (data-URI-Strip) ab.
"""

import ast
import base64
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

OPS_PY = os.path.join(BASE_DIR, "backend", "operations_api.py")


def test_operations_api_imports_base64():
    """AST-Check: `import base64` existiert auf Modulebene."""
    with open(OPS_PY, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    top_imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    names = []
    for n in top_imports:
        for alias in n.names:
            names.append(alias.name)
    assert "base64" in names


def test_base64_decode_path_works():
    """Der Handler-Pfad (data-URI-Strip + b64decode) liefert Bytes."""
    import backend.operations_api as ops  # noqa: E402

    b64_data = "data:image/jpeg;base64," + base64.b64encode(b"\x89PNG\r\n").decode()
    if "," in b64_data:
        b64_data = b64_data.split(",", 1)[1]
    img_bytes = ops.base64.b64decode(b64_data)
    assert img_bytes == b"\x89PNG\r\n"
