# -*- coding: utf-8 -*-
"""W6-E Regressions-Tests: CI-/Konfigurations-Gates und Undo-Store-Haertung.

Deckt D09-M1/M2/M5/M6/M8 sowie den vertraglichen W6-D-Smoke-Test-Gate ab.
Alle Pruefungen lesen die Produktivdateien als SSOT — kopierte Sollwerte
wuerden Drift im Gate unsichtbar machen.
"""

from __future__ import annotations

import ast
import configparser
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

import backend.operations_bulk as ops_bulk
from backend.operations_bulk import BulkActionDeps

ROOT = Path(__file__).resolve().parents[1]

BACKEND_CONTRACT = "importlinter:contract:backend-no-router-imports"
CORE_CONTRACT = "importlinter:contract:core-no-router-imports"

# Mindestmenge aus dem Audit; ALL_ROOT_MODULES muss dem Checkout entsprechen.
REQUIRED_ROOT_MODULES = (
    "api_provider.py",
    "views_core.py",
    "core_skills_engine.py",
    "watchdog_daemon.py",
    "local_security_guard.py",
    "backup_archon.py",
)
ALL_ROOT_MODULES = REQUIRED_ROOT_MODULES + (
    "main.py",
    "core_dispatcher.py",
    "dossier_builder.py",
    "jev_router.py",
    "local_memory_bridge.py",
    "oracle_news_radar.py",
    "archon_crm_mcp.py",
    "apollo_voice_engine.py",
    "create_lang_pages.py",
    "research_engine.py",
    "research_engine_v2.py",
    "seo_execution_agent.py",
    "telegram_notify.py",
    "update_dist.py",
)


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _config(relative: str) -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    cp.read(ROOT / relative, encoding="utf-8")
    return cp


def _multi(cp: configparser.ConfigParser, section: str, option: str) -> list[str]:
    raw = cp.get(section, option, fallback="")
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _step_containing(ci_text: str, marker: str) -> str:
    """Gibt den YAML-Step zurueck, der `marker` enthaelt (bis zum naechsten - name:)."""
    starts = [m.start() for m in re.finditer(r"(?m)^[ \t]*- name: ", ci_text)]
    pos = ci_text.index(marker)
    before = max([s for s in starts if s < pos], default=0)
    after = min([s for s in starts if s > pos], default=len(ci_text))
    return ci_text[before:after]


def _has_continue_on_error(step: str) -> bool:
    """Nur echte YAML-Keys zaehlen — Kommentare wie 'KEIN continue-on-error' nicht."""
    return any(
        re.search(r"^[ \t]*continue-on-error[ \t]*:", line) for line in step.splitlines()
    )


def _hashes_for(lock_text: str, pin: str) -> list[str]:
    """SHA-256-Werte einer Pin-Zeile inklusive der --hash-Fortsetzungszeilen."""
    lines = lock_text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(pin):
            block = lines[index : index + 40]
            end = next(
                (i for i, item in enumerate(block) if item.strip().startswith("# via")),
                len(block),
            )
            return re.findall(r"--hash=sha256:([0-9a-f]{64})", "\n".join(block[:end]))
    return []


# ---------------------------------------------------------------------------
# D09-M1 — MyPy gegen die ausgelieferte Runtime
# ---------------------------------------------------------------------------


def test_w6_e_mypy_targets_python_313() -> None:
    cp = _config("mypy.ini")
    assert cp.get("mypy", "python_version") == "3.13"
    assert "python_version = 3.11" not in _read("mypy.ini")
    # Kein CI-Flag darf die Config wieder auf eine andere Version ziehen.
    assert "--python-version" not in _read(".github/workflows/ci.yml")


# ---------------------------------------------------------------------------
# D09-M2 — beide Import-Contracts, Transitivitaet, echter CI-Gate
# ---------------------------------------------------------------------------


def test_w6_e_both_import_contracts_exist_and_are_strict() -> None:
    cp = _config(".importlinter")
    for section in (BACKEND_CONTRACT, CORE_CONTRACT):
        assert cp.has_section(section), f"Contract fehlt: {section}"
        assert cp.get(section, "type") == "forbidden"
        assert _multi(cp, section, "forbidden_modules") == ["archon.routers"]
        # allow_indirect_imports=false = der Linter meldet AUCH transitive Pfade.
        assert cp.get(section, "allow_indirect_imports", fallback="").lower() == "false"
    assert _multi(cp, BACKEND_CONTRACT, "source_modules") == ["backend"]
    assert _multi(cp, CORE_CONTRACT, "source_modules") == ["archon.core"]


def test_w6_e_import_linter_is_hash_pinned_in_ci_lock() -> None:
    lock = _read("requirements-ci.lock.txt")
    for pin in ("import-linter==2.17", "grimp==3.20", "click==8.5.1"):
        hashes = _hashes_for(lock, pin)
        assert hashes, f"{pin} fehlt oder ohne --hash=sha256 im CI-Lock"
        assert all(re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes)


def test_w6_e_ci_runs_import_contracts_as_hard_gate() -> None:
    ci = _read(".github/workflows/ci.yml")
    step = _step_containing(ci, "lint-imports --no-logo .importlinter")
    assert "lint-imports --no-logo .importlinter" in step
    assert not _has_continue_on_error(step)
    assert "|| true" not in step


def test_w6_e_ci_has_no_continue_on_error_escape_hatch() -> None:
    ci = _read(".github/workflows/ci.yml")
    offenders = [
        line.strip()
        for line in ci.splitlines()
        if re.search(r"^[ \t]*continue-on-error[ \t]*:", line)
    ]
    assert not offenders, f"CI-Job darf nicht weichgestellt werden: {offenders}"


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _module_graph() -> dict[str, set[str]]:
    """Importkanten aller backend-/archon-Module (inkl. Lazy-Imports)."""
    graph: dict[str, set[str]] = {}
    for package in ("backend", "archon"):
        for path in sorted((ROOT / package).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            src = _module_name(path)
            edges = graph.setdefault(src, set())
            for node in ast.walk(tree):
                targets: list[str] = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    targets.append(node.module)
                    targets.extend(f"{node.module}.{alias.name}" for alias in node.names)
                elif isinstance(node, ast.Import):
                    targets.extend(alias.name for alias in node.names)
                for target in targets:
                    if target.startswith(("archon", "backend")):
                        edges.add(target)
    return graph


def _router_path(graph: dict[str, set[str]], source: str) -> tuple[str, ...] | None:
    """BFS: erster Pfad von `source` zu einer archon.routers-Kante, sonst None."""
    todo: list[tuple[str, tuple[str, ...]]] = [(source, (source,))]
    seen = {source}
    while todo:
        node, path = todo.pop(0)
        if node == "archon.routers" or node.startswith("archon.routers."):
            return path
        for nxt in sorted(graph.get(node, ())):
            if nxt not in seen:
                seen.add(nxt)
                todo.append((nxt, path + (nxt,)))
    return None


def test_w6_e_transitive_detector_catches_synthetic_chain() -> None:
    """Negativprobe der BFS: backend -> core -> services -> routers muss rot werden."""
    graph = {
        "backend.mod": {"archon.core.mod"},
        "archon.core.mod": {"archon.services.mod"},
        "archon.services.mod": {"archon.routers.decisions"},
        "archon.routers.decisions": set(),
    }
    path = _router_path(graph, "backend.mod")
    assert path is not None
    assert path[-1] == "archon.routers.decisions"
    assert "archon.core.mod" in path


def test_w6_e_no_transitive_backend_to_router_path_in_checkout() -> None:
    """Produktivpfad: kein backend-Modul darf (auch indirekt) routers erreichen."""
    graph = _module_graph()
    violations = [
        path
        for source in graph
        if source == "backend" or source.startswith("backend.")
        if (path := _router_path(graph, source)) is not None
    ]
    assert not violations, "Transitive Layer-Verletzung: " + "; ".join(
        " -> ".join(path) for path in violations[:5]
    )


# ---------------------------------------------------------------------------
# D09-M5 — alle Root-Module in compileall / bandit / ruff
# ---------------------------------------------------------------------------


def test_w6_e_static_gates_cover_every_root_module() -> None:
    ci = _read(".github/workflows/ci.yml")
    for marker in (
        "python -m compileall -q",
        "bandit -q -lll",
        "ruff check --select E9,F63,F7,F82",
    ):
        step = _step_containing(ci, marker)
        missing = [name for name in ALL_ROOT_MODULES if name not in step]
        assert not missing, f"{marker} erfasst nicht: {missing}"


def test_w6_e_root_module_list_matches_checkout() -> None:
    """Neue Root-Module duerfen nicht unbemerkt aus den Gates fallen."""
    actual = {path.name for path in ROOT.glob("*.py")}
    assert set(ALL_ROOT_MODULES) == actual, (
        f"Root-Modul-Liste veraltet: fehlt={sorted(actual - set(ALL_ROOT_MODULES))}, "
        f"entfernt={sorted(set(ALL_ROOT_MODULES) - actual)}"
    )


def test_w6_e_dockerfile_compiles_copied_root_modules() -> None:
    dockerfile = _read("Dockerfile")
    assert "COPY --chown=streamlituser:streamlitgroup *.py ./" in dockerfile
    assert "RUN python -m compileall -q *.py" in dockerfile


# ---------------------------------------------------------------------------
# W6-D — vertraglicher Adapter-Smoke-Test als harter CI-Schritt
# ---------------------------------------------------------------------------


def test_w6_e_ci_has_hard_telegram_adapter_smoke_gate() -> None:
    ci = _read(".github/workflows/ci.yml")
    step = _step_containing(ci, "python scripts/telegram_adapter_smoke_test.py")
    assert "python scripts/telegram_adapter_smoke_test.py" in step
    assert not _has_continue_on_error(step)
    assert "|| true" not in step


# ---------------------------------------------------------------------------
# D09-M8 — eine Dependency-SSOT
# ---------------------------------------------------------------------------


def test_w6_e_backend_manifest_removed_and_root_lock_is_ssot() -> None:
    assert not (ROOT / "backend" / "requirements.txt").exists()
    for name in ("Dockerfile", "backend/Dockerfile"):
        text = _read(name)
        assert "requirements.lock.txt" in text
        assert "backend/requirements.txt" not in text
    assert "backend/requirements.txt" not in _read(".github/workflows/ci.yml")


# ---------------------------------------------------------------------------
# D09-M6 — Undo-Store: RLock + TTL + atomischer CAS-Verbrauch
# ---------------------------------------------------------------------------


def _init_undo_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, assignee TEXT, "
        "status TEXT, block_kind TEXT, result TEXT)"
    )
    conn.execute(
        "CREATE TABLE task_events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "task_id TEXT, kind TEXT, payload TEXT, created_at TEXT)"
    )
    conn.execute(
        "INSERT INTO tasks (id, title, assignee, status, block_kind, result) "
        "VALUES ('t-1', 'Aufgabe', 'agent_a', 'todo', NULL, NULL)"
    )
    conn.commit()
    conn.close()


def _undo_deps(db_path: Path) -> BulkActionDeps:
    def _connect(maintenance: bool = False) -> sqlite3.Connection:
        con = sqlite3.connect(str(db_path))
        con.row_factory = sqlite3.Row
        return con

    return BulkActionDeps(
        get_kanban_connection=_connect,
        load_kanban_meta=lambda: {"tasks": {}},
        sync_to_memory_bridge=lambda *_args: None,
        valid_kanban_statuses={"todo", "done"},
    )


def _seed_token(monkeypatch: pytest.MonkeyPatch, token: str, ttl: float) -> None:
    monkeypatch.setattr(ops_bulk, "_KANBAN_UNDO_STORE", {})
    now = time.time()
    ops_bulk._KANBAN_UNDO_STORE[token] = {
        "snapshot": [
            {
                "id": "t-1",
                "title": "Aufgabe",
                "status": "todo",
                "assignee": "agent_a",
                "tags": [],
                "block_kind": None,
                "result": None,
            }
        ],
        "action": "move",
        "created_at": now,
        "expires_at": now + ttl,
    }


def _silence_external_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    def _no_provider(_name: str) -> Any:
        raise RuntimeError("kein app_main im Test")

    monkeypatch.setattr(ops_bulk, "get_provider", _no_provider)
    monkeypatch.setattr(
        "backend.kanban_sidecar.update_kanban_meta", lambda fn: fn({"tasks": {}})
    )
    monkeypatch.setattr(
        "backend.audit_log.chained_audit_log.record_event", lambda **_kw: None
    )


def test_w6_e_prune_is_reentrant_under_the_undo_lock() -> None:
    """_prune_undo_store() darf aus bereits gesperrten Pfaden gerufen werden."""
    with ops_bulk._UNDO_LOCK:
        ops_bulk._prune_undo_store()


def test_w6_e_undo_token_is_consumed_exactly_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Zwei parallele Undo-Requests auf denselben Token: genau einer darf Erfolg haben."""
    db_path = tmp_path / "undo_race.db"
    _init_undo_db(db_path)
    _seed_token(monkeypatch, "undo_race_token", 600.0)
    _silence_external_effects(monkeypatch)
    deps = _undo_deps(db_path)

    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def _run() -> None:
        barrier.wait(timeout=10)
        try:
            result = ops_bulk.execute_kanban_bulk_undo(
                ops_bulk.KanbanBulkUndoRequest(undo_token="undo_race_token"), deps
            )
            outcomes.append(f"ok:{result['status']}")
        except HTTPException as exc:
            outcomes.append(f"http:{exc.status_code}")

    threads = [threading.Thread(target=_run, name=f"w6e-undo-{index}") for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert not any(thread.is_alive() for thread in threads), "Undo-Thread haengt (Deadlock?)"
    assert sorted(outcomes) == ["http:404", "ok:success"], outcomes
    assert "undo_race_token" not in ops_bulk._KANBAN_UNDO_STORE


def test_w6_e_expired_undo_token_is_removed_with_400(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "undo_expired.db"
    _init_undo_db(db_path)
    _seed_token(monkeypatch, "undo_expired_token", -1.0)
    _silence_external_effects(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        ops_bulk.execute_kanban_bulk_undo(
            ops_bulk.KanbanBulkUndoRequest(undo_token="undo_expired_token"),
            _undo_deps(db_path),
        )
    assert exc_info.value.status_code == 400
    assert "undo_expired_token" not in ops_bulk._KANBAN_UNDO_STORE
