"""D3 (H-09-1): final three blanket ``# mypy: ignore-errors`` removals.

D2 removed 40 of 43 file-wide opt-outs; these three root modules were outside
its ownership. This test locks in the completion: no blanket pragma remains
anywhere in the checked-in Python sources, and the replacements are coded
``# type: ignore[code]`` comments rather than a new file-wide opt-out.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

D3_FILES = (
    "core_skills_engine.py",
    "local_memory_bridge.py",
    "research_engine_v2.py",
)

# Hidden dirs (.venv/.ci_venv/.mt-it/.git/...) are third-party or tooling,
# not Archon-owned sources. ``data`` is production state: read-only at most,
# never scanned here.
SKIP_DIRS = {
    "data", "node_modules", "site-packages", "__pycache__",
    "archive", "_archive_legacy", "scratch", "dist", "site",
}

BLANKET_PRAGMA = re.compile(r"^\s*#\s*mypy:\s*ignore-errors\b", re.IGNORECASE)
CODED_IGNORE = re.compile(r"#\s*type:\s*ignore\[[a-z][a-z0-9-]*", re.IGNORECASE)


def python_sources() -> list[Path]:
    files: list[Path] = []
    for current, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS]
        files.extend(Path(current) / n for n in names if n.endswith(".py"))
    return sorted(files)


def test_no_blanket_mypy_pragma_repo_wide() -> None:
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}:{lineno}"
        for path in python_sources()
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        )
        if BLANKET_PRAGMA.match(line)
    ]
    assert offenders == [], f"Blanket mypy pragmas found: {offenders}"


def test_d3_modules_have_no_blanket_pragma() -> None:
    for name in D3_FILES:
        path = ROOT / name
        assert path.is_file(), f"missing module: {name}"
        text = path.read_text(encoding="utf-8", errors="replace")
        assert not any(BLANKET_PRAGMA.match(line) for line in text.splitlines()), name


def test_d3_replacements_are_coded_ignores() -> None:
    coded = sum(
        1
        for name in D3_FILES
        for line in (ROOT / name).read_text(encoding="utf-8", errors="replace").splitlines()
        if CODED_IGNORE.search(line)
    )
    assert coded >= 6, f"expected coded ignores from D3, found {coded}"


def test_mypy_config_still_warns_on_unused_ignores() -> None:
    assert "warn_unused_ignores = True" in (ROOT / "mypy.ini").read_text(encoding="utf-8")
