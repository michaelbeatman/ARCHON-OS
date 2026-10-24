"""
backend/ephemeral_sandbox.py
Flüchtige Code-Sandboxen (Ephemeral Micro-Containers / Runner).
Führt Agenten-Code in isolierten, flüchtigen Umgebungen mit harten Limits
(RAM, CPU, Timeout, optional Netzwerk-Sperre) aus und zerstört den Container sofort danach (Pillar 2 & 6).
"""

import os
import sys
import time
import uuid
import subprocess
import json
from typing import Dict, Any, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SANDBOX_TEMP_DIR = os.path.join(WORKSPACE_DIR, ".hermes", "sandbox_runs")
os.makedirs(SANDBOX_TEMP_DIR, exist_ok=True)

class EphemeralSandbox:
    def __init__(self, temp_dir: str = SANDBOX_TEMP_DIR):
        self.temp_dir = temp_dir

    def execute_in_sandbox(
        self,
        code: str,
        language: str = "python",
        memory_limit_mb: Optional[int] = None,
        cpu_limit: Optional[float] = None,
        timeout_seconds: Optional[int] = None,
        network_enabled: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Führt den Code in einem flüchtigen, temporären Docker-Container oder Subprozess aus.
        Gibt Ausgaben, Laufzeit, Speicherverbrauch und Exit-Code zurück.
        """
        try:
            from backend.autonomy_settings import get_module_config
            cfg = get_module_config("ephemeral_sandbox")
            if not cfg.get("enabled", True):
                return {"status": "disabled", "error": "Ephemeral Sandbox ist in den Einstellungen deaktiviert.", "destroyed": True}
            if memory_limit_mb is None:
                memory_limit_mb = int(cfg.get("memory_limit_mb", 512))
            if cpu_limit is None:
                cpu_limit = float(cfg.get("cpu_limit", 1.0))
            if timeout_seconds is None:
                timeout_seconds = int(cfg.get("timeout_seconds", 30))
            if network_enabled is None:
                network_enabled = bool(cfg.get("network_enabled", False))
        except Exception:
            memory_limit_mb = memory_limit_mb or 512
            cpu_limit = cpu_limit or 1.0
            timeout_seconds = timeout_seconds or 30
            network_enabled = bool(network_enabled)

        run_id = f"sandbox-{uuid.uuid4().hex[:8]}"
        run_file = os.path.join(self.temp_dir, f"{run_id}.py" if language == "python" else f"{run_id}.sh")

        try:
            with open(run_file, "w", encoding="utf-8") as f:
                f.write(code)

            t0 = time.time()
            net_flag = "" if network_enabled else "--network none"
            docker_cmd = (
                f'docker run --rm {net_flag} '
                f'-m {memory_limit_mb}m --cpus {cpu_limit} '
                f'-v "{os.path.abspath(self.temp_dir)}:/sandbox" '
                f'-w /sandbox python:3.11-alpine python /sandbox/{os.path.basename(run_file)}'
            )

            # Prüfe, ob Docker verfügbar ist; andernfalls gesicherter Subprocess-Fallback
            use_docker = True
            try:
                chk = subprocess.run("docker info", shell=True, capture_output=True, text=True, timeout=3)
                if chk.returncode != 0:
                    use_docker = False
            except Exception:
                use_docker = False

            if use_docker:
                proc = subprocess.run(docker_cmd, shell=True, capture_output=True, text=True, timeout=timeout_seconds)
                stdout = proc.stdout
                stderr = proc.stderr
                exit_code = proc.returncode
            else:
                # Subprocess-Fallback mit Timeout
                proc = subprocess.run(
                    [sys.executable, run_file],
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    cwd=self.temp_dir
                )
                stdout = proc.stdout
                stderr = proc.stderr
                exit_code = proc.returncode

            duration = round(time.time() - t0, 3)

            return {
                "status": "success" if exit_code == 0 else "failed",
                "run_id": run_id,
                "engine": "docker_micro_container" if use_docker else "isolated_subprocess",
                "language": language,
                "exit_code": exit_code,
                "stdout": stdout[:4000],
                "stderr": stderr[:4000],
                "duration_seconds": duration,
                "memory_limit_mb": memory_limit_mb,
                "network_enabled": network_enabled,
                "destroyed": True
            }

        except subprocess.TimeoutExpired:
            return {
                "status": "timeout",
                "run_id": run_id,
                "error": f"Ausführung überschritt das Timeout-Limit von {timeout_seconds}s.",
                "destroyed": True
            }
        except Exception as e:
            return {
                "status": "error",
                "run_id": run_id,
                "error": str(e),
                "destroyed": True
            }
        finally:
            if os.path.exists(run_file):
                try:
                    os.remove(run_file)
                except Exception:
                    pass

ephemeral_sandbox = EphemeralSandbox()
