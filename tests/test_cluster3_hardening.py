"""
Cluster 3 — Rot-Beweis und Regressionstests für die 🔴-Befunde
F20 (Docker-Socket-Proxy), F2/F26/R-05/N-12 (Command-Injection),
F5 (Sandbox-Härtung), F27 (Container-Limits).

Diese Tests sind bewusst als *Verhaltens*-Tests geschrieben: sie prüfen, dass

* kein Shell-String mehr gebaut wird (argv-Liste, kein shell=True),
* Eingaben gegen Allowlists validiert werden, bevor sie in ein Kommando laufen,
* die Sandbox nur mit Härtungs-Flags und gepinntem Image startet und bei
  Timeout den Container wirklich killt,
* der Proxy nicht mehr im gemeinsamen Agenten-Netz hängt und die
  Methoden-ACL nur noch lesen/starten/stoppen erlaubt,
* der App-Container harte Limits und Drop-All-Capabilities deklariert.

Gegen den Altstand (HEAD vor diesem Commit) schlagen sie fehl — das ist der
Rot-Beweis. Keine Assertion ist abgeschwächt.
"""

import asyncio
import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ---------------------------------------------------------------------------
# F2 / N-12 — task_self_healer: git checkout ohne Shell, mit Pfad-Allowlist
# ---------------------------------------------------------------------------

class TestTaskSelfHealerRollback:

    def _healer(self, tmp_path):
        from backend.task_self_healer import TaskSelfHealer
        return TaskSelfHealer(db_path=str(tmp_path / "heal.db"))

    def test_rollback_uses_argv_list_without_shell(self, tmp_path, monkeypatch):
        from backend import task_self_healer as tsh

        healer = self._healer(tmp_path)
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(tsh.subprocess, "run", fake_run)
        res = healer.rollback_git_changes("main.py")

        assert res["status"] == "success"
        assert isinstance(captured["cmd"], list), "Kommando muss argv-Liste sein"
        assert captured["cmd"] == ["git", "checkout", "--", "main.py"]
        assert captured["kwargs"].get("shell") is not True
        assert "shell" not in captured["kwargs"] or captured["kwargs"]["shell"] is False

    def test_rollback_rejects_shell_metacharacters(self, tmp_path, monkeypatch):
        from backend import task_self_healer as tsh

        healer = self._healer(tmp_path)
        monkeypatch.setattr(tsh.subprocess, "run",
                            MagicMock(side_effect=AssertionError("darf nicht laufen")))

        for payload in ("main.py; id", "main.py && id", "$(id)", "main.py|id"):
            res = healer.rollback_git_changes(payload)
            assert res["status"] == "error", payload

    def test_rollback_rejects_traversal_and_absolute_outside(self, tmp_path, monkeypatch):
        from backend import task_self_healer as tsh

        healer = self._healer(tmp_path)
        monkeypatch.setattr(tsh.subprocess, "run",
                            MagicMock(side_effect=AssertionError("darf nicht laufen")))

        for payload in ("../../etc/passwd", "/etc/passwd", "./../main.py"):
            res = healer.rollback_git_changes(payload)
            assert res["status"] == "error", payload

    def test_rollback_without_path_does_not_revert_everything(self, tmp_path, monkeypatch):
        """N-12: ohne expliziten Pfad kein `git checkout -- .` (fremde Arbeit bleibt)."""
        from backend import task_self_healer as tsh

        healer = self._healer(tmp_path)
        monkeypatch.setattr(tsh.subprocess, "run",
                            MagicMock(side_effect=AssertionError("darf nicht laufen")))

        res = healer.rollback_git_changes(None)
        assert res["status"] == "skipped"

    def test_auto_rollback_defaults_to_false(self, tmp_path, monkeypatch):
        """Ohne explizite Einstellung darf nicht zurückgerollt werden."""
        from backend import task_self_healer as tsh
        import backend.autonomy_settings as aut

        healer = self._healer(tmp_path)
        monkeypatch.setattr(aut, "get_module_config", lambda _s: {})

        calls = {"rollback": 0}
        monkeypatch.setattr(healer, "rollback_git_changes",
                            lambda p=None: calls.__setitem__("rollback", calls["rollback"] + 1)
                            or {"status": "success"})

        class _Res:
            content = "x" * 120

        monkeypatch.setattr("core_dispatcher.dispatch_to_omniroute_or_container",
                            lambda **kw: _Res())

        res = asyncio.run(healer.attempt_self_healing(
            task_id="t1", task_title="T", failed_code="print(1)", error_output="boom",
        ))
        assert calls["rollback"] == 0
        assert res["rollback_applied"] is False


# ---------------------------------------------------------------------------
# F26 / R-05 — fleet_self_healing: Allowlist + Socket-Pinning, kein Shell
# ---------------------------------------------------------------------------

class TestFleetSelfHealing:

    def test_rejects_injection_attempt(self, monkeypatch):
        from backend import fleet_self_healing as fsh

        monkeypatch.setattr(fsh.subprocess, "run",
                            MagicMock(side_effect=AssertionError("darf nicht laufen")))
        for payload in ("n8n; id", "n8n && id", "../n8n", "n8n/../x", "$(id)"):
            res = fsh.restart_service_container(payload)
            assert res["status"] in ("error", "rejected"), payload

    def test_restart_uses_argv_and_pinned_socket(self, monkeypatch):
        from backend import fleet_self_healing as fsh

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return MagicMock(returncode=0, stdout="n8n\n", stderr="")

        monkeypatch.setattr(fsh.subprocess, "run", fake_run)
        res = fsh.restart_service_container("n8n")

        assert res["status"] == "success"
        cmd = captured["cmd"]
        assert isinstance(cmd, list)
        assert cmd[0] == "docker"
        assert "-H" in cmd, "Auth-/ACL-Grenze: CLI muss am gepinnten Socket laufen"
        assert cmd[cmd.index("-H") + 1].startswith("unix://")
        assert cmd[-2:] == ["restart", "n8n"]
        assert captured["kwargs"].get("shell") is not True

    def test_container_name_is_validated(self, monkeypatch):
        from backend import fleet_self_healing as fsh
        from utils.docker_client import validate_container_name

        assert validate_container_name("n8n") == "n8n"
        monkeypatch.setattr(fsh.subprocess, "run", MagicMock(return_value=MagicMock(
            returncode=0, stdout="", stderr="")))
        # Alias-Auflösung bleibt erhalten (CRM -> ef47f1b25a78_CRM)
        res = fsh.restart_service_container("crm")
        assert res["container"] == "ef47f1b25a78_CRM"

    def test_check_fleet_uses_argv_ps(self, monkeypatch):
        from backend import fleet_self_healing as fsh

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(fsh.subprocess, "run", fake_run)
        monkeypatch.setattr(fsh, "restart_service_container",
                            lambda name: {"status": "stub", "service": name})
        fsh.check_fleet_and_heal.__wrapped__()

        cmd = captured["cmd"]
        assert isinstance(cmd, list)
        assert cmd[0] == "docker" and "ps" in cmd
        assert captured["kwargs"].get("shell") is not True


# ---------------------------------------------------------------------------
# F5 — ephemeral_sandbox: Härtung, Image-Pin, Netz-Isolation, Timeout-Kill
# ---------------------------------------------------------------------------

class TestSandboxHardening:

    def _run(self, **kwargs):
        from backend import ephemeral_sandbox as es
        with patch.object(es, "_resolve_host_path", return_value="/mnt/host/path"), \
             patch.object(es, "_ensure_sandbox_network", return_value=None), \
             patch.object(es.subprocess, "run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),   # docker info
                MagicMock(returncode=0, stdout="ok\n", stderr=""),  # docker run
            ]
            result = es.ephemeral_sandbox.execute_in_sandbox("print(1)", **kwargs)
            cmd = mock_run.call_args_list[1][0][0]
        return result, cmd

    def test_docker_run_carries_hardening_flags(self):
        result, cmd = self._run()
        assert result["status"] == "success"
        joined = " ".join(cmd)
        assert "--cap-drop=ALL" in joined
        assert "--read-only" in joined
        assert "--pids-limit=50" in joined
        assert "no-new-privileges" in joined
        assert "--user=1000:1000" in joined
        # Temp-Verzeichnis darf aus dem Container nicht beschreibbar sein
        mount = [c for c in cmd if ":/sandbox" in c]
        assert mount and mount[0].endswith(":ro"), mount

    def test_image_is_pinned_by_digest(self):
        _, cmd = self._run()
        images = [c for c in cmd if "python" in c and ":" in c]
        assert images, cmd
        assert "@sha256:" in images[0], f"Image nicht gepinnt: {images[0]}"

    def test_network_defaults_to_none(self):
        _, cmd = self._run()
        assert "--network" in cmd
        assert cmd[cmd.index("--network") + 1] == "none"

    def test_network_enabled_uses_isolated_internal_network(self):
        _, cmd = self._run(network_enabled=True)
        assert cmd[cmd.index("--network") + 1] == "archon-sandbox_net"

    def test_timeout_kills_container(self):
        from backend import ephemeral_sandbox as es

        with patch.object(es, "_resolve_host_path", return_value="/mnt/host/path"), \
             patch.object(es, "_ensure_sandbox_network", return_value=None), \
             patch.object(es.subprocess, "run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),
                subprocess.TimeoutExpired(cmd="docker run", timeout=1),
                MagicMock(returncode=0, stdout="", stderr=""),  # docker kill
                MagicMock(returncode=0, stdout="", stderr=""),  # docker rm -f
            ]
            result = es.ephemeral_sandbox.execute_in_sandbox("while True: pass", timeout_seconds=1)
            calls = [c[0][0] for c in mock_run.call_args_list]

        assert result["status"] == "timeout"
        flat = [" ".join(c) if isinstance(c, list) else str(c) for c in calls]
        assert any("kill" in f for f in flat), flat
        run_cmd = [c for c in calls if isinstance(c, list) and "run" in c][0]
        name_idx = run_cmd.index("--name")
        killed_name = run_cmd[name_idx + 1]
        assert any(killed_name in f and "kill" in f for f in flat), (killed_name, flat)


# ---------------------------------------------------------------------------
# F20 — Proxy: eigenes Verwaltungsnetz + enge Methoden-ACL
# ---------------------------------------------------------------------------

def _yaml(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return yaml.safe_load(f)


class TestSocketProxy:

    def _proxy_env(self, doc):
        svc = doc["services"]["docker-socket-proxy"]
        env = svc.get("environment") or {}
        if isinstance(env, list):
            env = dict(item.split("=", 1) for item in env if "=" in item)
        return svc, env

    def _resolve(self, value):
        """'${VAR:-0}' -> '0' (Default greift, weil VAR im Test nicht gesetzt ist)."""
        if isinstance(value, str) and value.startswith("${"):
            inner = value[2:-1]
            return inner.split(":-")[1] if ":-" in inner else ""
        return value

    def test_proxy_left_shared_agent_network(self):
        doc = _yaml("docker-compose.dev.yml")
        svc, _ = self._proxy_env(doc)
        nets = svc["networks"]
        assert nets == ["archon-admin_net"], nets
        netdef = doc["networks"]["archon-admin_net"]
        assert netdef.get("internal") is True

    def test_only_app_in_admin_net(self):
        doc = _yaml("docker-compose.dev.yml")
        members = [n for n, s in doc["services"].items()
                   if n != "docker-socket-proxy"
                   and "archon-admin_net" in (s.get("networks") or [])]
        assert members == ["archon"], members

    def test_prod_admin_net_has_only_app_and_orchestrator(self):
        doc = _yaml("docker-compose.yml")
        members = [n for n, s in doc["services"].items()
                   if n != "docker-socket-proxy"
                   and "archon-admin_net" in (s.get("networks") or {})]
        assert sorted(members) == ["archon-os", "hermes"], members

    def test_high_privilege_flags_disabled_by_default(self):
        _, env = self._proxy_env(_yaml("docker-compose.dev.yml"))
        for flag in ("ALLOW_CONTAINER_CREATE", "ALLOW_CONTAINER_DELETE",
                     "ALLOW_CONTAINER_RENAME", "ALLOW_IMAGE_PULL", "ALLOW_IMAGE_TAG",
                     "EXEC", "VOLUMES", "NETWORKS", "IMAGES", "SERVICES", "TASKS"):
            assert self._resolve(env[flag]) == "0", flag

    def test_read_and_lifecycle_flags_enabled(self):
        _, env = self._proxy_env(_yaml("docker-compose.dev.yml"))
        for flag in ("CONTAINERS", "ALLOW_START", "ALLOW_STOP", "INFO", "PING", "VERSION"):
            assert self._resolve(env[flag]) == "1", flag
        assert self._resolve(env["ALLOW_RESTARTS"]) == "0"

    def test_haproxy_cfg_has_no_container_subtree_allow(self):
        path = os.path.join(ROOT, "deploy/docker-socket-proxy/haproxy.cfg")
        with open(path, encoding="utf-8") as f:
            cfg = f.read()
        # Kein Praefix-Match auf den ganzen /containers-Teilbaum
        assert "/containers }" not in cfg
        # Jede allow-Regel ist an eine Methode gebunden
        for line in cfg.splitlines():
            stripped = line.strip()
            if stripped.startswith("http-request allow"):
                assert "METH_" in stripped, stripped
        # Default ist deny
        assert "http-request deny" in cfg

    def test_prod_compose_proxy_also_isolated(self):
        doc = _yaml("docker-compose.yml")
        svc, _ = self._proxy_env(doc)
        assert svc["networks"] == ["archon-admin_net"]


# ---------------------------------------------------------------------------
# F27 — App-Container: Limits, read-only, cap_drop
# ---------------------------------------------------------------------------

class TestAppContainerLimits:

    @pytest.mark.parametrize("fname,svcname", [
        ("docker-compose.dev.yml", "archon"),
        ("docker-compose.yml", "archon-os"),
    ])
    def test_limits_declared(self, fname, svcname):
        doc = _yaml(fname)
        svc = doc["services"][svcname]
        assert svc.get("mem_limit"), "mem_limit fehlt (deploy.* wirkt nicht ausserhalb Swarm)"
        # PID-Grenze: `pids_limit` oder (wenn ein deploy-Block existiert)
        # `deploy.resources.limits.pids` — Compose v5 verbietet beides zugleich.
        deploy_pids = (((svc.get("deploy") or {}).get("resources") or {})
                       .get("limits") or {}).get("pids")
        assert svc.get("pids_limit") == 200 or deploy_pids == 200
        assert svc.get("read_only") is True
        assert "no-new-privileges:true" in " ".join(svc.get("security_opt") or [])
        assert "ALL" in (svc.get("cap_drop") or [])
        assert svc.get("tmpfs"), "read_only braucht tmpfs fuer /tmp"

    def test_dev_stack_documents_reload_risk(self):
        path = os.path.join(ROOT, "docs/security/SECRETS_MANAGEMENT_UND_ROTATION.md")
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        assert "--reload" in text
        assert "Bind-Mount" in text or "bind-mount" in text.lower()
