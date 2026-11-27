"""S1 - hartes Import-Layer-Gate (D09/H-09-2).

``.importlinter`` ist die SSOT. Dieser Test liest sie als INI und enforced sie in
CI (``ci.yml:305`` ``pytest tests/ -q`` und ``:555`` ``coverage run -m pytest``).
Kein ``lint-imports``-Binary noetig: import-linter ist nicht in
``requirements-ci.lock.txt``; ein Hash-Pin wuerde SBOM + Full-Gate beruehren.

Nach F5 sind die ``ignore_imports`` vollstaendig getilgt: JEDER
``backend -> archon.routers``-Import (auch lazy) macht das Gate rot. Die
Negativprobe nutzt ein synthetisches allowed-Set, damit sie nicht vom
(jetzt leeren) Config-Zustand abhaengt und nicht tautologisch wird.
"""

from __future__ import annotations

import ast
import configparser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".importlinter"
BACKEND = ROOT / "backend"
CORE = ROOT / "archon" / "core"
CONTRACT_SECTION = "importlinter:contract:backend-no-router-imports"
CORE_CONTRACT_SECTION = "importlinter:contract:core-no-router-imports"

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


def _core_router_or_service_imports() -> list[ImportHit]:
    """D09-M2: archon.core darf weder archon.routers noch den Umweg
    archon.services importieren (transitiv gesperrt durch allow_indirect=False).
    """
    found: list[ImportHit] = []
    for path in sorted(CORE.rglob("*.py")):
        try:
            tree = ast.parse(
                path.read_text(encoding="utf-8", errors="replace"), filename=str(path)
            )
        except SyntaxError:
            continue
        src = _module_name(path)
        rel = str(path.relative_to(ROOT))
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                targets = [node.module]
            elif isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            for target in targets:
                if target.startswith(("archon.routers", "archon.services")):
                    found.append((src, target, rel, getattr(node, "lineno", 0)))
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
    # Bewusst gesetzt: import-linter 2.17 prueft mit
    # allow_indirect_imports=false DIREKTE und INDIREKTE (transitive) Importe.
    # Hier festgeschrieben, damit die Option nicht unbemerkt geaendert wird.
    assert cp.get(CONTRACT_SECTION, "allow_indirect_imports").lower() == "false"
    # F5-Schloss: die Ausnahmen muessen vollstaendig getilgt sein.
    assert _ignored_pairs(cp) == set(), (
        "F5 verletzt: backend-no-router-imports enthaelt noch "
        f"ignore_imports: {sorted(_ignored_pairs(cp))}"
    )


def test_every_ignored_import_actually_exists() -> None:
    """F5-Schloss plus Rueckwaerts-Sicherung gegen Config-Drift."""
    cp = _config()
    ignored = _ignored_pairs(cp)
    real = {(src, dst) for src, dst, _, _ in _router_imports()}

    # Alter Drift-Schutz (greift, falls die Liste doch wieder befuellt wird).
    stale = sorted(ignored - real)
    assert not stale, f"ignore_imports ohne realen Import (Config-Drift): {stale}"

    # F5: die Ausnahmen MUESSEN vollstaendig getilgt sein, sonst wird dieser
    # Test zum vakuumen Theater-Gate.
    assert ignored == set(), (
        f"F5 verletzt: {len(ignored)} ignore_imports uebrig: {sorted(ignored)}"
    )


def test_backend_has_no_undocumented_router_imports() -> None:
    """Das HARTE Ratchet-Gate nach F5: 0 Ausnahmen, jeder Import wird rot."""
    violations = _violations(_router_imports(), _ignored_pairs(_config()))
    assert not violations, (
        "Neue/undokumentierte Layer-Verletzung backend -> archon.routers:\n  "
        + "\n  ".join(violations)
    )


def test_layer_gate_detects_a_violation() -> None:
    """Negativprobe gegen die ECHTE Gate-Logik (F5: synthetisches allowed).

    Nach F5 ist die reale ``ignore_imports``-Liste LEER; der Test darf daher
    NICHT mehr von einem nicht-leeren realen Config abhaengen. Er ruft
    weiterhin dieselben Hilfsfunktionen auf wie das Produktiv-Gate und prueft
    BEIDE Zweige: undokumentiert -> Violation, dokumentiert -> erlaubt.
    """
    snippet = (
        "from archon.routers.brand_new import thing\n"
        "from archon.routers._rbac import forbid_viewer_writes\n"
    )
    tree = ast.parse(snippet)
    imports = _imports_from_tree(
        tree, "backend.operations_api", "backend/operations_api.py"
    )

    # 1. Die echte AST-Extraktion findet beide backend -> archon.routers Importe.
    assert {dst for _, dst, _, _ in imports} == {
        "archon.routers.brand_new",
        "archon.routers._rbac",
    }

    # 2. NEGATIVZWEIG: mit LEEREM allowed (dem F5-Stand) meldet die echte
    #    Gate-Logik BEIDE Importe als Verletzung - kein stilles Gruen.
    violations = _violations(imports, set())
    assert len(violations) == 2, violations
    assert any(
        "backend.operations_api -> archon.routers.brand_new" in v for v in violations
    )
    assert any(
        "backend.operations_api -> archon.routers._rbac" in v for v in violations
    )

    # 3. POSITIVZWEIG: SYNTHETISCHES allowed, NICHT aus der realen Config.
    allowed = {("backend.operations_api", "archon.routers._rbac")}
    documented: list[ImportHit] = [
        (
            "backend.operations_api",
            "archon.routers._rbac",
            "backend/operations_api.py",
            2,
        )
    ]
    assert _violations(documented, allowed) == []

    # 4. Beide Zweige in EINEM Aufruf: genau der undokumentierte Import bleibt.
    violations = _violations(imports, allowed)
    assert len(violations) == 1, violations
    assert "backend.operations_api -> archon.routers.brand_new" in violations[0]


# ---------------------------------------------------------------------------
# D09-M2 — zweiter Contract: archon.core -> archon.routers (auch transitiv)
# ---------------------------------------------------------------------------


def test_core_contract_is_well_formed() -> None:
    cp = _config()
    assert cp.has_section(CORE_CONTRACT_SECTION)
    assert cp.get(CORE_CONTRACT_SECTION, "type") == "forbidden"
    assert _multi(cp, CORE_CONTRACT_SECTION, "source_modules") == ["archon.core"]
    assert _multi(cp, CORE_CONTRACT_SECTION, "forbidden_modules") == ["archon.routers"]
    assert cp.get(CORE_CONTRACT_SECTION, "allow_indirect_imports").lower() == "false"


def test_archon_core_has_no_router_or_service_import() -> None:
    """Der Umweg über archon.services ist transitiv ebenfalls gesperrt."""
    hits = _core_router_or_service_imports()
    assert not hits, (
        "D09-M2: archon.core importiert archon.routers/services:\n  "
        + "\n  ".join(f"{file}:{line}: {src} -> {dst}" for src, dst, file, line in hits)
    )


def test_documented_debt_is_bounded() -> None:
    """Altschuld-Ratchet: heute bei 0, darf NIE wieder steigen (F5-Finale).

    Tilgungskette (Modul-Paare ``backend -> archon.routers``):
      23 (S1) -> 21 (F1a) -> 18 (A1) -> 17 (A2) -> 3 (F4: 14 Router
      nach archon/routers/operations/__init__.py gehoben) -> 0 (F2:
      _rbac / auth / chat entfernt) -> F5: ignore_imports leer.
    Jeder neue Import macht rot - keine neuen Ausnahmen, kein Rueckrollen.
    """
    pairs = {(src, dst) for src, dst, _, _ in _router_imports()}
    assert len(pairs) == 0, (
        f"Altschuld-Ratchet greift: {len(pairs)} backend -> archon.routers "
        f"Paar(e) nach F5 (Ziel 0): {sorted(pairs)}. "
        "Tilgungsplan F1a/A1/A2/F4/F2/F5 pruefen."
    )
