"""
Tests für backend/ephemeral_sandbox.py — S6-Hardening-Verifikation.

Diese Tests prüfen, dass der Fail-Closed-Pfad (ohne Docker) funktioniert.
Live-Docker-Tests (Netzwerk-Sperre, Speicher-Limit, Dateisystem-Isolation)
werden als skip markiert, da sie einen laufenden Docker-Daemon im Test-
Environment benötigen und nicht deterministisch ohne echten Docker laufen.
"""

import pytest
from unittest.mock import patch, MagicMock
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.ephemeral_sandbox import ephemeral_sandbox, EphemeralSandbox


class TestEphemeralSandboxFailClosed:
    """Tests für den Fail-Closed-Pfad (kein Docker verfügbar)."""

    def test_no_docker_returns_error_not_subprocess_fallback(self):
        """Ohne Docker CLI muss die Sandbox error zurückgeben, NICHT subprocess-Fallback."""
        with patch("subprocess.run") as mock_run:
            # docker info schlägt fehl
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            
            result = ephemeral_sandbox.execute_in_sandbox("print('hello')")
            
            assert result["status"] == "error"
            assert result["engine"] == "unavailable"
            assert result["exit_code"] == -1
            assert "S6-Hardening" in result["error"]
            assert result["limits_enforced"] is False
            # WICHTIG: subprocess.run mit sys.executable darf NICHT aufgerufen worden sein
            # Nur docker info wurde geprüft
            assert mock_run.call_count == 1
            assert "docker info" in str(mock_run.call_args)

    def test_docker_info_exception_returns_error(self):
        """Exception bei docker info → error, kein Fallback."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("docker not found")
            
            result = ephemeral_sandbox.execute_in_sandbox("print('hello')")
            
            assert result["status"] == "error"
            assert result["engine"] == "unavailable"
            assert result["limits_enforced"] is False

    def test_docker_available_uses_docker_path(self):
        """Mit Docker wird docker_micro_container engine genutzt (Structure-Test, kein echter Docker)."""
        with patch("subprocess.run") as mock_run:
            # docker info OK
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),  # docker info
                MagicMock(returncode=0, stdout="4\n", stderr="", timeout=30),  # docker run
            ]
            
            result = ephemeral_sandbox.execute_in_sandbox("print(2+2)")
            
            # Wenn docker info OK, wird docker run aufgerufen
            assert mock_run.call_count == 2
            # Der zweite Aufruf sollte docker run sein
            assert "docker run" in str(mock_run.call_args_list[1])


class TestEphemeralSandboxStructure:
    """Struktur-Tests für Antwort-Felder (kompatibel zu prompt_studio.js)."""

    def test_response_contains_limits_enforced(self):
        """Antwort muss limits_enforced Feld enthalten."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            result = ephemeral_sandbox.execute_in_sandbox("print('x')")
            assert "limits_enforced" in result

    def test_response_contains_memory_limit_mb(self):
        """Antwort muss memory_limit_mb enthalten."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            result = ephemeral_sandbox.execute_in_sandbox("print('x')")
            assert "memory_limit_mb" in result
            assert result["memory_limit_mb"] == 512

    def test_response_contains_network_enabled(self):
        """Antwort muss network_enabled enthalten."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            result = ephemeral_sandbox.execute_in_sandbox("print('x')")
            assert "network_enabled" in result
            assert result["network_enabled"] is False


# =============================================================================
# Live-Docker-Tests (nur mit echtem Docker-Daemon im Container lauffähig)
# Markiert als skip mit Begründung — NICHT als grün faken
# =============================================================================

@pytest.mark.skip(reason="Benötigt echten Docker-Daemon im Container (--network none Test). "
                          "Führen Sie manuell im Container aus: "
                          "docker exec ARCHON-OS python -m pytest tests/test_ephemeral_sandbox.py::TestEphemeralSandboxLive -v")
class TestEphemeralSandboxLive:
    """Live-Tests gegen echten Docker (nur im ARCHON-OS Container lauffähig)."""

    def test_network_isolation_no_outbound_tcp(self):
        """TCP-Verbindung nach außen muss scheitern (--network none)."""
        code = """
import socket
try:
    sock = socket.create_connection(("1.1.1.1", 443), timeout=3)
    sock.close()
    print("CONNECTED")  # Sollte NICHT erscheinen
except Exception as e:
    print(f"BLOCKED: {e}")
"""
        result = ephemeral_sandbox.execute_in_sandbox(code, network_enabled=False)
        # Mit --network none sollte der Connect fehlschlagen
        assert result["status"] in ("failed", "error")
        assert "BLOCKED" in result.get("stdout", "") or "BLOCKED" in result.get("stderr", "")

    def test_memory_limit_enforced(self):
        """Speicher-Limit (~100MB) muss greifen bei 1GB Allokation."""
        code = """
# Versuche ~1 GB zu allozieren (sollte am 512MB oder 100MB Limit scheitern)
try:
    data = bytearray(1024 * 1024 * 1024)  # 1 GB
    print("ALLOCATED")  # Sollte NICHT erscheinen
except MemoryError:
    print("MEMORY_LIMIT_HIT")
except Exception as e:
    print(f"OTHER_ERROR: {e}")
"""
        result = ephemeral_sandbox.execute_in_sandbox(code, memory_limit_mb=100)
        assert result["status"] in ("failed", "error")
        assert "MEMORY_LIMIT_HIT" in result.get("stdout", "") or "MemoryError" in result.get("stderr", "")

    def test_filesystem_isolation_no_service_token(self):
        """Service-Token außerhalb /sandbox muss unlesbar sein."""
        code = """
try:
    with open("/app/data/.archon_service_token", "r") as f:
        token = f.read()
    print(f"TOKEN_READ: {token[:20]}")  # Sollte NICHT erscheinen
except Exception as e:
    print(f"BLOCKED: {e}")
"""
        result = ephemeral_sandbox.execute_in_sandbox(code)
        assert result["status"] in ("failed", "error")
        assert "BLOCKED" in result.get("stdout", "") or "BLOCKED" in result.get("stderr", "")

    def test_engine_is_docker_micro_container(self):
        """Engine muss docker_micro_container sein (nicht isolated_subprocess)."""
        result = ephemeral_sandbox.execute_in_sandbox("print('hello')")
        assert result["engine"] == "docker_micro_container"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])