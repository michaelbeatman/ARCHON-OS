"""
Zentraler, abgesicherter Docker-Zugriff für Archon OS.

Vorher: main.py sprach /var/run/docker.sock direkt an (15 Stellen), ohne TLS,
ohne Namens-Validierung, ohne Endpunkt-Allowlist. Ein kompromittierter
Endpunkt bedeutete Root auf dem Host.

Jetzt:
  * Transport umschaltbar per DOCKER_HOST (tcp://docker-socket-proxy:2375)
    mit Fallback auf den Unix-Socket.
  * Methoden-/Pfad-Allowlist: nur die tatsächlich benötigten Operationen.
  * Container-Namen werden strikt validiert (kein '/', kein '..', keine
    Query-Injection in den API-Pfad).
  * Fehler werden als DockerError gemeldet statt still als b"" zurueckzukommen.
"""

from __future__ import annotations

import json
import os
import re
import socket
import struct
from typing import Optional

__all__ = ["DockerError", "DockerClient", "docker_client", "validate_container_name"]

_CONTAINER_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")

# Erlaubte Operationen: (Methode, Pfad-Regex)
_ALLOWED = [
    ("GET", re.compile(r"^/containers/[^/]+/json$")),
    ("GET", re.compile(r"^/containers/[^/]+/logs\?.*$")),
    ("GET", re.compile(r"^/containers/[^/]+/stats\?.*$")),
    ("GET", re.compile(r"^/containers/json(\?.*)?$")),
    ("POST", re.compile(r"^/containers/[^/]+/exec$")),
    ("POST", re.compile(r"^/exec/[^/]+/start$")),
    ("POST", re.compile(r"^/containers/[^/]+/(start|stop|restart)$")),
]


class DockerError(RuntimeError):
    pass


def validate_container_name(name: str) -> str:
    if not name or not _CONTAINER_RE.match(str(name)):
        raise DockerError(f"Ungültiger Container-Name: {name!r}")
    return str(name)


def _decode_chunked(data: bytes) -> bytes:
    result = b""
    offset = 0
    while offset < len(data):
        line_end = data.find(b"\r\n", offset)
        if line_end == -1:
            break
        size_str = data[offset:line_end].strip()
        if not size_str:
            offset = line_end + 2
            continue
        try:
            size = int(size_str, 16)
        except ValueError:
            result += data[offset:]
            break
        if size == 0:
            break
        offset = line_end + 2
        result += data[offset:offset + size]
        offset += size + 2
    return result


class DockerClient:
    def __init__(self) -> None:
        self._host = os.environ.get("DOCKER_HOST", "").strip()
        self._unix = os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock")

    # ---------------- Transport ----------------

    def _endpoint(self) -> tuple[str, str]:
        """(kind, target) - kind = 'tcp' | 'unix'."""
        host = self._host
        if host.startswith("tcp://"):
            return "tcp", host[len("tcp://"):]
        if host.startswith("http://"):
            return "tcp", host[len("http://"):]
        if host.startswith("unix://"):
            return "unix", host[len("unix://"):]
        return "unix", self._unix

    def _check_allowed(self, method: str, path: str) -> None:
        for m, rx in _ALLOWED:
            if m == method.upper() and rx.match(path):
                return
        raise DockerError(f"Docker-Operation nicht erlaubt: {method} {path}")

    def request(self, method: str, path: str, payload: Optional[dict] = None,
                timeout: float = 1.0) -> bytes:
        self._check_allowed(method, path)
        kind, target = self._endpoint()
        body = json.dumps(payload) if payload is not None else ""
        head = (
            f"{method.upper()} {path} HTTP/1.1\r\n"
            f"Host: localhost\r\n"
        )
        if body:
            head += f"Content-Type: application/json\r\nContent-Length: {len(body.encode())}\r\n"
        head += "Connection: close\r\n\r\n"

        if kind == "tcp":
            host, _, port = target.partition(":")
            sock = socket.create_connection((host, int(port or 2375)), timeout=timeout)
        else:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect(target)

        try:
            sock.sendall((head + body).encode())
            return self._read_response(sock)
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _read_response(self, sock: socket.socket) -> bytes:
        response = b""
        content_length = None
        chunked = False
        headers_parsed = False
        deadline_hit = False

        while True:
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                deadline_hit = True
                break
            if not chunk:
                break
            response += chunk
            if not headers_parsed and b"\r\n\r\n" in response:
                headers_part = response.split(b"\r\n\r\n", 1)[0]
                headers_parsed = True
                lower = headers_part.lower()
                chunked = b"transfer-encoding: chunked" in lower
                for line in headers_part.split(b"\r\n"):
                    if line.lower().startswith(b"content-length:"):
                        try:
                            content_length = int(line.split(b":", 1)[1].strip())
                        except Exception:
                            pass
            if headers_parsed:
                body_part = response.split(b"\r\n\r\n", 1)[1]
                if content_length is not None and len(body_part) >= content_length:
                    break
                if chunked and body_part.endswith(b"0\r\n\r\n"):
                    break

        parts = response.split(b"\r\n\r\n", 1)
        if len(parts) < 2:
            if deadline_hit:
                raise DockerError(f"Docker-Timeout nach {len(response)} Bytes")
            return b""
        if chunked:
            return _decode_chunked(parts[1])
        return parts[1]

    # ---------------- Bequeme Helfer ----------------

    def container_json(self, name: str) -> bytes:
        return self.request("GET", f"/containers/{validate_container_name(name)}/json")

    def container_logs(self, name: str, tail: int = 150) -> bytes:
        tail = max(1, min(int(tail), 5000))
        return self.request(
            "GET",
            f"/containers/{validate_container_name(name)}/logs?tail={tail}&stdout=true&stderr=true",
        )

    def container_stats(self, name: str) -> bytes:
        return self.request("GET", f"/containers/{validate_container_name(name)}/stats?stream=false")

    def container_action(self, name: str, action: str) -> bytes:
        name = validate_container_name(name)
        if action not in ("start", "stop", "restart"):
            raise DockerError(f"Ungültige Aktion: {action}")
        return self.request("POST", f"/containers/{name}/{action}")

    def exec_command(self, name: str, cmd: list[str], working_dir: str = "/app",
                     timeout: float = 6.0) -> bytes:
        name = validate_container_name(name)
        raw = self.request("POST", f"/containers/{name}/exec", {
            "AttachStdout": True,
            "AttachStderr": True,
            "Cmd": cmd,
            "WorkingDir": working_dir,
        }, timeout=timeout)
        try:
            exec_id = json.loads(raw.decode("utf-8"))["Id"]
        except Exception as e:
            raise DockerError(f"Exec-Instanz konnte nicht erstellt werden: {e}")
        return self.request("POST", f"/exec/{exec_id}/start",
                            {"Detach": False, "Tty": False}, timeout=timeout)


def parse_docker_stream(data: bytes) -> str:
    """Docker-Multiplex-Stream (8-Byte-Header je Frame) nach Text."""
    out = []
    offset = 0
    while offset < len(data):
        if len(data) - offset < 8:
            out.append(data[offset:].decode("utf-8", errors="ignore"))
            break
        try:
            size = struct.unpack(">I", data[offset + 4:offset + 8])[0]
        except Exception:
            out.append(data[offset:].decode("utf-8", errors="ignore"))
            break
        offset += 8
        out.append(data[offset:offset + size].decode("utf-8", errors="ignore"))
        offset += size
    return "".join(out)


def parse_docker_stream_bytes(data: bytes) -> bytes:
    out = b""
    offset = 0
    while offset < len(data):
        if len(data) - offset < 8:
            out += data[offset:]
            break
        try:
            size = struct.unpack(">I", data[offset + 4:offset + 8])[0]
        except Exception:
            out += data[offset:]
            break
        offset += 8
        out += data[offset:offset + size]
        offset += size
    return out


docker_client = DockerClient()