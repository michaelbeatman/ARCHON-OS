"""D2 (H-09-1): no blanket ``# mypy: ignore-errors`` in owned production code.

The audit gate in ``ci.yml`` only has an effect if production modules are really
type-checked. This test guards the D2 rollout: every Python file inside the
agent's exclusive ownership must rely on concrete ``# type: ignore[code]``
annotations instead of a file-wide opt-out.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

OWNED_DIRS = ("archon", "backend", "scripts", "utils", "plugins")
OWNED_FILES = (
    "main.py",
    "core_dispatcher.py",
    "views_core.py",
    "watchdog_daemon.py",
    "local_security_guard.py",
    "api_provider.py",
    "jev_router.py",
)

BLANKET_PRAGMA = re.compile(r"^\s*#\s*mypy:\s*ignore-errors\b", re.IGNORECASE)
CODED_IGNORE = re.compile(r"#\s*type:\s*ignore\[[a-z][a-z0-9-]*", re.IGNORECASE)


def owned_python_files() -> list[Path]:
    files: list[Path] = []
    for directory in OWNED_DIRS:
        base = ROOT / directory
        if base.is_dir():
            files.extend(p for p in base.rglob("*.py") if ".mypy_cache" not in p.parts)
    for name in OWNED_FILES:
        path = ROOT / name
        if path.is_file():
            files.append(path)
    return sorted(set(files))


def test_no_blanket_mypy_pragma_in_owned_scope() -> None:
    offenders = []
    for path in owned_python_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if BLANKET_PRAGMA.match(line):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{lineno}")
    assert offenders == [], f"Blanket mypy pragmas found: {offenders}"


def test_coded_ignores_are_present_after_rollout() -> None:
    coded = sum(
        1
        for path in owned_python_files()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if CODED_IGNORE.search(line)
    )
    assert coded > 0, "D2 replaced pragmas with coded ignores; none found"


def test_mypy_config_keeps_unused_ignore_warning() -> None:
    config = (ROOT / "mypy.ini").read_text(encoding="utf-8")
    assert "warn_unused_ignores = True" in config
