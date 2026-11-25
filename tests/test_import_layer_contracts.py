"""S1 - hartes Import-Layer-Gate (D09/H-09-2).

``.importlinter`` ist die SSOT. Dieser Test liest sie als INI und enforced sie in
CI (``ci.yml:305`` ``pytest tests/ -q`` und ``:555`` ``coverage run -m pytest``).
Kein ``lint-imports``-Binary noetig: import-linter ist nicht in
``requirements-ci.lock.txt``; ein Hash-Pin wuerde SBOM + Full-Gate beruehren.

Verhindert insbesondere den alten Fehler ``No matches for ignored import``:
jeder Ignore-Eintrag muss einem realen Import entsprechen, und jeder neue
``backend -> archon.routers``-Import macht das Gate rot (Ratchet).

Nach unabhaengiger S1-Verifikation korrigiert: der Negativtest war urspruenglich
tautologisch. ``_imports_from_tree()`` und ``_violations()`` sind jetzt die
gemeinsamen Hilfsfunktionen von Produktiv-Gate UND Negativprobe.
"""

from __future__ import annotations

import ast
import configparser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".importlinter"
BACKEND = ROOT / "backend"
CONTRACT_SECTION = "importlinter:contract:backend-no-router-imports"

ImportHit = tuple[str, str, str, int]  # (quellmodul, zielmodul, datei, zeile)


def _config() -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    assert CONFIG.is_file(), f".importlinter fehlt: {CONFIG}"
    cp.read(CONFIG, encoding="utf-8")
    return cp


def _multi(
    cp: configparser.ConfigParser, section: str, option: str
) -> list[str]:
    raw = cp.get(section, option, fallback="")
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _ignored_pairs(cp: configparser.ConfigParser) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for line in _multi(cp, CONTRACT_SECTION, "ignore_imports"):
        assert "->" in line, f"ignore_imports-Zeile ohne '->': {line!r}"
        src, dst = (part.strip() for part in line.split("->", 1))
        pairs.add((src, dst))
    return pairs


def _module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports_from_tree(tree: ast.AST, src: str, rel: str) -> list[ImportHit]:
    """AST-Extraktion der archon.routers-Importe.

    Wird vom Produktiv-Scan _router_imports() UND von der Negativprobe
    verwendet, damit der Negativtest nicht an der echten Logik vorbeilaeuft.
    """
    found: list[ImportHit] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "archon.routers" or node.module.startswith(
                "archon.routers."
            ):
                found.append((src, node.module, rel, node.lineno))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "archon.routers" or alias.name.startswith(
                    "archon.routers."
                ):
                    found.append((src, alias.name, rel, node.lineno))
    return found


def _router_imports() -> list[ImportHit]:
    """Alle backend-Importe auf archon.routers.* - inkl. Lazy-Imports."""
    found: list[ImportHit] = []
    for path in sorted(BACKEND.rglob("*.py")):
        try:
            tree = ast.parse(
                path.read_text(encoding="utf-8", errors="replace"), filename=str(path)
            )
        except SyntaxError:
            continue
        found.extend(
            _imports_from_tree(tree, _module_name(path), str(path.relative_to(ROOT)))
        )
    return found


def _violations(
    imports: list[ImportHit], allowed: set[tuple[str, str]]
) -> list[str]:
    """Die EIGENTLICHE Gate-Logik - identisch fuer Produktiv-Scan und Negativprobe."""
    return [
        f"{file}:{line}: {src} -> {dst}"
        for src, dst, file, line in imports
        if (src, dst) not in allowed
    ]


def test_linter_config_is_well_formed() -> None:
    cp = _config()
    roots = _multi(cp, "importlinter", "root_packages")
    assert set(roots) == {"archon", "backend"}, (
        "root_packages muss archon UND backend enthalten (zwei Top-Level-Pakete); "
        f"gefunden: {roots}"
    )
    assert (
        cp.get("importlinter", "include_external_packages", fallback="False").lower()
        == "false"
    )
    assert cp.has_section(CONTRACT_SECTION)
    assert cp.get(CONTRACT_SECTION, "type") == "forbidden"
    assert _multi(cp, CONTRACT_SECTION, "source_modules") == ["backend"]
    assert _multi(cp, CONTRACT_SECTION, "forbidden_modules") == ["archon.routers"]
    # Bewusst gesetzt: die Regel betrifft direkte Importe; der transitive Pfad
    # ist ein separater S1-Neubefund (siehe .importlinter-Kommentar). Hier
    # festgeschrieben, damit die Option nicht unbemerkt geaendert wird.
    assert cp.get(CONTRACT_SECTION, "allow_indirect_imports").lower() == "true"


def test_every_ignored_import_actually_exists() -> None:
    """Verhindert 'No matches for ignored import' (Ursache des alten exit 1)."""
    cp = _config()
    real = {(src, dst) for src, dst, _, _ in _router_imports()}
    stale = sorted(_ignored_pairs(cp) - real)
    assert not stale, f"ignore_imports ohne realen Import (Config-Drift): {stale}"


def test_backend_has_no_undocumented_router_imports() -> None:
    """Das Ratchet-Gate: neue backend -> archon.routers Importe werden rot."""
    violations = _violations(_router_imports(), _ignored_pairs(_config()))
    assert not violations, (
        "Neue/undokumentierte Layer-Verletzung backend -> archon.routers:\n  "
        + "\n  ".join(violations)
    )


def test_layer_gate_detects_a_violation() -> None:
    """Negativprobe gegen die ECHTE Gate-Logik (nach S1-Verifikation korrigiert).

    Der erste Entwurf war tautologisch (hartcodierter Snippet + triviale
    Assertion, nie ein Aufruf der Gate-Logik). Dieser Test ruft dieselben
    Hilfsfunktionen auf wie das Produktiv-Gate und prueft BEIDE Zweige:
    undokumentiert -> Violation, dokumentiert -> erlaubt.
    """
    snippet = (
        "from archon.routers.brand_new import thing\n"
        "from archon.routers._rbac import forbid_viewer_writes\n"
    )
    tree = ast.parse(snippet)
    imports = _imports_from_tree(
        tree, "backend.operations_api", "backend/operations_api.py"
    )
    allowed = _ignored_pairs(_config())

    # 1. Die echte AST-Extraktion findet beide Importe.
    assert {dst for _, dst, _, _ in imports} == {
        "archon.routers.brand_new",
        "archon.routers._rbac",
    }

    # 2. Die echte Gate-Logik meldet GENAU den undokumentierten Import.
    violations = _violations(imports, allowed)
    assert len(violations) == 1, violations
    assert "backend.operations_api -> archon.routers.brand_new" in violations[0]

    # 3. Dokumentierte Paare bleiben erlaubt (beide Zweige der Logik geprueft).
    documented: list[ImportHit] = [
        ("backend.operations_api", "archon.routers._rbac", "backend/operations_api.py", 29)
    ]
    assert _violations(documented, allowed) == []


def test_documented_debt_is_bounded() -> None:
    """Altschuld darf nur sinken (Tilgung F1a/F1b/S3), nie steigen."""
    pairs = {(src, dst) for src, dst, _, _ in _router_imports()}
    assert len(pairs) <= 21, (
        f"Altschuld von 21 auf {len(pairs)} Paare gewachsen - "
        "S1-Ratchet greift, Tilgungsplan (F1b/S3) pruefen."
    )
