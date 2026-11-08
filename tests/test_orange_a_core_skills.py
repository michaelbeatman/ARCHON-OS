"""Cluster Spur A — core_skills_engine.py (M-10, M-11, Z-06, Z-07).

Rot gegen 3269f7e1 (Belege aus dem Review):

* M-10/Z-07: ``execute_mcp_tool`` lieferte hartkodierte Phantom-Telemetrie
  ("Quota remaining: 84%", "Latency metrics: OpenAI 300ms …") mit
  ``status: success`` — ohne dass ein MCP-Server ausgefuehrt wurde.
* M-11: ``restart_service`` verweigerte den Neustart, wenn das Docker-SDK
  nicht initialisiert war, obwohl der eigentliche Pfad ueber
  ``utils.docker_client`` (HTTP) laeuft.
* Z-06: ``git_safe_commit`` war toter Code (pytest-Timeout 30 s < gemessene
  Suite-Laufzeit ~60 s) und stagingte mit ``git add .`` den GESAMTEN
  Arbeitsbaum inkl. untracked Secrets/Backups.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(os.environ.get("ARCHON_ROOT") or Path(__file__).resolve().parent.parent)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core_skills_engine import (  # noqa: E402
    DockerControlSkill,
    GitTestingSkill,
    MCPAdapterSkill,
)


# ---------------------------------------------------------------- M-10 / Z-07

def _run(coro):
    return asyncio.run(coro)


def test_mcp_execute_ohne_verbundenen_server_meldet_keinen_erfolg():
    adapter = MCPAdapterSkill()
    result = _run(adapter.execute_mcp_tool("mcp__omniroute__omniroute_check_quota", {}))

    assert result["status"] != "success", "MCP-Ausfuehrung darf ohne Server kein Erfolg melden"
    assert result["error"] == "mcp_server_not_connected"


def test_mcp_execute_liefert_keine_erfundene_telemetrie():
    """Auch mit "verbundenem" Server darf keine Messzahl erfunden werden."""
    adapter = MCPAdapterSkill()
    _run(adapter.connect_mcp_server("omniroute"))
    result = _run(adapter.execute_mcp_tool("mcp__omniroute__omniroute_get_provider_metrics", {}))

    assert result["status"] != "success"
    blob = str(result)
    for fake in ("84%", "Quota remaining", "OpenAI 300ms", "Anthropic 450ms", "Local 50ms"):
        assert fake not in blob, f"Erfundene Telemetrie im Ergebnis: {fake!r}"


def test_mcp_antwort_nennt_die_ausgebliebene_ausfuehrung():
    adapter = MCPAdapterSkill()
    _run(adapter.connect_mcp_server("omniroute"))
    result = _run(adapter.execute_mcp_tool("mcp__omniroute__omniroute_best_combo_for_task", {}))

    assert result["error"] == "mcp_execution_not_implemented"
    assert "nicht implementiert" in result["message"]


def test_mcp_ungueltiger_toolname_bleibt_fehler():
    adapter = MCPAdapterSkill()
    result = _run(adapter.execute_mcp_tool("kein_mcp_tool", {}))
    assert result["status"] == "error"


# --------------------------------------------------------------------- M-11

def test_restart_service_arbeitet_ohne_docker_sdk(monkeypatch):
    """Ohne SDK-Client muss der Neustart ueber docker_client (HTTP) laufen."""
    skill = DockerControlSkill()
    skill.client = None  # SDK nicht initialisiert

    captured = {}

    class _FakeDc:
        def restart_container(self, name):
            captured["name"] = name
            return b"ok"

    monkeypatch.setattr("utils.docker_client.docker_client", _FakeDc())
    result = skill.restart_service("hermes-webui")

    assert result["status"] == "success", result
    assert captured["name"] == "hermes-webui"


def test_restart_service_meldet_dockerfehler(monkeypatch):
    from utils.docker_client import DockerError

    skill = DockerControlSkill()
    skill.client = None

    class _FakeDc:
        def restart_container(self, name):
            raise DockerError("stop fehlgeschlagen")

    monkeypatch.setattr("utils.docker_client.docker_client", _FakeDc())
    result = skill.restart_service("hermes-webui")

    assert result["status"] == "error"
    assert "stop fehlgeschlagen" in result["message"]


# --------------------------------------------------------------------- Z-06

def test_pytest_timeout_uebersteigt_die_gemessene_suite_laufzeit():
    assert GitTestingSkill.DEFAULT_PYTEST_TIMEOUT >= 120, (
        "pytest-Timeout muss ueber der gemessenen Suite-Laufzeit (~60 s) liegen, "
        "sonst ist der Commit-Pfad toter Code"
    )


def test_git_safe_commit_staged_keine_untracked_dateien(tmp_path, monkeypatch):
    """``git add .`` ist verboten: untracked Secrets/Backups duerfen nicht mit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)

    def _git(*args):
        os.system(f"git init -q && git config user.email t@t && git config user.name t")

    _git()
    tracked = repo / "tracked.txt"
    tracked.write_text("a", encoding="utf-8")
    os.system("git add tracked.txt && git commit -q -m init")

    tracked.write_text("b", encoding="utf-8")
    secret = repo / "untracked_secret.txt"
    secret.write_text("sk-verysecret", encoding="utf-8")

    calls = []

    class _FakeRes:
        returncode = 0
        stdout = "committed"
        stderr = ""

    def fake_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        return _FakeRes()

    monkeypatch.setattr("core_skills_engine.subprocess.run", fake_run)
    skill = GitTestingSkill()
    monkeypatch.setattr(skill, "run_pytest", lambda *a, **k: {"status": "success"})

    skill.git_safe_commit("msg")
    staged_cmds = [c for c in calls if c[:2] == ["git", "add"]]
    assert staged_cmds, "es wurde nichts gestaged"
    for cmd in staged_cmds:
        assert "." not in cmd[2:], f"git add . ist verboten: {cmd}"
        assert cmd[2] == "-u", f"nur versionierte Dateien duerfen gestaged werden: {cmd}"


def test_git_safe_commit_mit_pfadliste_staged_nur_diese_pfade(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)

    calls = []

    class _FakeRes:
        returncode = 0
        stdout = "committed"
        stderr = ""

    def fake_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        return _FakeRes()

    monkeypatch.setattr("core_skills_engine.subprocess.run", fake_run)
    skill = GitTestingSkill()
    monkeypatch.setattr(skill, "run_pytest", lambda *a, **k: {"status": "success"})

    skill.git_safe_commit("msg", paths=["core_skills_engine.py", "tests/x.py"])
    add_cmds = [c for c in calls if c[:2] == ["git", "add"]]
    commit_cmds = [c for c in calls if c[:2] == ["git", "commit"]]

    assert add_cmds and add_cmds[0][2:] == ["--", "core_skills_engine.py", "tests/x.py"]
    assert commit_cmds and commit_cmds[0][-2:] == ["core_skills_engine.py", "tests/x.py"]


def test_git_safe_commit_bricht_bei_fehlgeschlagenen_tests_ab(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "core_skills_engine.subprocess.run",
        lambda cmd, *a, **k: calls.append(list(cmd)) or pytest.fail("darf nicht giten"),
    )
    skill = GitTestingSkill()
    monkeypatch.setattr(skill, "run_pytest", lambda *a, **k: {"status": "failed"})

    result = skill.git_safe_commit("msg")
    assert result["status"] == "error"
    assert not calls
