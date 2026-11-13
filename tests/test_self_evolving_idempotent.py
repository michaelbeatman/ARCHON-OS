"""Regressionstest: Selbst-Evolutions-Engine schreibt unveränderte Tools nicht neu.

Hintergrund: Die Engine schrieb bei jedem Lauf einen frischen Zeitstempel in
erzeugte Tool- und SKILL-Dateien. Dadurch war `git status` nach jedem Lauf
"geändert", obwohl der Inhalt identisch war — und die Dateien wanderten als
Dauer-Diff durch den Arbeitsbaum.

Der Test beweist beide Richtungen:
  * gleicher Code  -> zweiter Lauf darf NICHTS schreiben (mtime unverändert)
  * anderer Code   -> muss geschrieben werden
"""
import os
import time

import pytest

from backend import self_evolving_tooling as se


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    tools = tmp_path / "dynamic_tools"
    skills = tmp_path / "skills"
    tools.mkdir()
    skills.mkdir()
    monkeypatch.setattr(se, "DYNAMIC_TOOLS_DIR", str(tools))
    monkeypatch.setattr(se, "SKILLS_DIR", str(skills))
    eng = se.SelfEvolvingToolEngine(db_path=str(tmp_path / "mem.db"))
    # Die Engine schreibt am Ende auch in die 'learnings'-Tabelle. Die gehört zu einem
    # anderen Subsystem (agentic_memory.db) und wird von _init_db nicht angelegt —
    # produktiv existiert sie, in einer frischen DB nicht. Schema hier nachbilden.
    conn = __import__("sqlite3").connect(str(tmp_path / "mem.db"))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS learnings ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT, category TEXT, "
        "summary TEXT, obsidian_link TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.commit()
    conn.close()
    # Sandbox wird nicht gebraucht: der Test prüft nur das Schreibverhalten.
    monkeypatch.setattr(eng, "test_in_sandbox", lambda code, test, timeout_seconds=15: (True, "ok"))
    return eng, tools, skills


CODE_V1 = "def my_tool(a, b):\n    return a + b\n"
CODE_V2 = "def my_tool(a, b):\n    return a + b + 1\n"


def _run(eng, code):
    return eng.synthesize_and_evolve_tool(
        creator_agent="regressionstest",
        tool_name="idempotenz_probe",
        description="Addiert zwei Zahlen",
        implementation_code=code,
        verification_test_code="assert True",
        max_repair_iterations=1,
    )


def test_second_run_with_same_code_writes_nothing(engine):
    eng, tools, skills = engine

    first = _run(eng, CODE_V1)
    assert first.get("status") == "success", first

    tool_file = tools / "idempotenz_probe.py"
    skill_file = skills / "auto-idempotenz-probe" / "SKILL.md"
    assert tool_file.exists(), "Tool-Datei wurde beim ersten Lauf nicht geschrieben"
    assert skill_file.exists(), "SKILL.md wurde beim ersten Lauf nicht geschrieben"

    content_before = tool_file.read_text(encoding="utf-8")
    skill_before = skill_file.read_text(encoding="utf-8")
    mtime_before = tool_file.stat().st_mtime_ns
    skill_mtime_before = skill_file.stat().st_mtime_ns

    time.sleep(0.05)  # damit eine Änderung sicher eine neue mtime hätte

    second = _run(eng, CODE_V1)
    assert second.get("status") == "success", second

    assert tool_file.read_text(encoding="utf-8") == content_before, (
        "Tool-Datei wurde beim zweiten Lauf mit identischem Code neu geschrieben"
    )
    assert skill_file.read_text(encoding="utf-8") == skill_before, (
        "SKILL.md wurde beim zweiten Lauf mit identischem Code neu geschrieben"
    )
    assert tool_file.stat().st_mtime_ns == mtime_before, (
        "mtime der Tool-Datei hat sich geändert — es wurde geschrieben, obwohl der Inhalt gleich war"
    )
    assert skill_file.stat().st_mtime_ns == skill_mtime_before, (
        "mtime der SKILL.md hat sich geändert — es wurde geschrieben, obwohl der Inhalt gleich war"
    )


def test_changed_code_is_written(engine):
    eng, tools, skills = engine

    assert _run(eng, CODE_V1).get("status") == "success"
    tool_file = tools / "idempotenz_probe.py"
    before = tool_file.read_text(encoding="utf-8")

    assert _run(eng, CODE_V2).get("status") == "success"
    after = tool_file.read_text(encoding="utf-8")

    assert after != before, "Geänderter Code wurde nicht geschrieben"
    assert "a + b + 1" in after


def test_timestamp_in_header_stays_stable(engine):
    """Der Header-Zeitstempel darf beim zweiten Lauf nicht erneuert werden."""
    eng, tools, _ = engine
    assert _run(eng, CODE_V1).get("status") == "success"
    tool_file = tools / "idempotenz_probe.py"
    header_before = tool_file.read_text(encoding="utf-8").splitlines()[0]

    time.sleep(1.1)  # ISO-Zeitstempel hat Sekundenauflösung
    assert _run(eng, CODE_V1).get("status") == "success"
    header_after = tool_file.read_text(encoding="utf-8").splitlines()[0]

    assert header_after == header_before, (
        f"Zeitstempel im Header wurde erneuert: {header_before!r} -> {header_after!r}"
    )