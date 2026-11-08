"""
Zentraler, abgesicherter Docker-Zugriff für Archon OS.

Vorher: main.py sprach /var/run/docker.sock direkt an (15 Stellen), ohne TLS,
ohne Namens-Validierung, ohne Endpunkt-Allowlist. Ein kompromittierter
Endpunkt bedeutete Root auf dem Host.

Jetzt:
  * Transport umschaltbar per DOCKER_HOST (tcp://docker-socket-proxy:2375)
    mit Fallback auf den Unix-Socket.
  * Der privilegierte Admin-Client hat dafuer einen eigenen Schalter
    (DOCKER_ADMIN_HOST), damit der Updater den Proxy nutzen kann, ohne dass
    die uebrigen Aufrufer ihren Transport wechseln.
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

__all__ = [
    "DockerError",
    "DockerClient",
    "DockerAdminClient",
    "docker_client",
    "docker_cli_host_args",
    "validate_container_name",
    "validate_image_ref",
]

_CONTAINER_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")

# Image-Referenzen (nousresearch/hermes-agent:latest, registry:5000/team/img@sha256:...).
# Bewusst ohne '?', '#', '%', '&' und ohne Leerraum: das sind Query-/Fragment-Anfaenge
# bzw. Encoding-Tricks, mit denen sich der API-Pfad umdeuten laesst.
_IMAGE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,200}$")

# Pfadbaustein fuer Container-Namen in Regex-Allowlists. Reserved-Woerter von
# /containers/<x>, die keine Container-IDs sind, werden ausgeschlossen, damit
# z.B. DELETE /containers/json nicht durch eine Namensregel faellt.
_CN_PAT = r"(?!json$|create$|prune$)[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
# Pfadbaustein fuer Image-Referenzen (darf '/' enthalten, weil Repos verschachtelt sind).
_REF_PAT = r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,200}"


# Erlaubte Operationen: (Methode, Pfad-Regex)
#
# Query-fähig, aber eng: `start`/`stop` nehmen optional genau EINEN Query-String
# (`?t=5&...`), weil Docker `stop` die Frist als Query-Parameter erwartet. Der
# Namensbaustein ist `_CN_PAT` (wie in der Admin-Allowlist) — ein Query-Anhang im
# Namen ist damit ausgeschlossen, und keine Regel greift über den Aktionsteil hinaus.
#
# `restart` bleibt bewusst OHNE Query-String und unverändert: der Proxy gibt es
# nicht frei (ALLOW_RESTARTS=0), Aufrufer stellen auf stop + start um (B2).
_ALLOWED = [
    ("GET", re.compile(r"^/containers/[^/]+/json$")),
    ("GET", re.compile(r"^/containers/[^/]+/logs\?.*$")),
    ("GET", re.compile(r"^/containers/[^/]+/stats\?.*$")),
    ("GET", re.compile(r"^/containers/json(\?.*)?$")),
    ("POST", re.compile(r"^/containers/[^/]+/exec$")),
    ("POST", re.compile(r"^/exec/[^/]+/start$")),
    ("POST", re.compile(rf"^/containers/{_CN_PAT}/(start|stop)(\?[^#]*)?$")),
    ("POST", re.compile(rf"^/containers/{_CN_PAT}/restart$")),
]

# Globaler Socket-Timeout bleibt klein (1 s): Lesepfade sollen schnell scheitern.
_DEFAULT_TIMEOUT = 1.0

# Nur Lebenszyklus-Aktionen, bei denen Docker die Verbindung offen hält, bis der
# Container wirklich steht, bekommen einen eigenen Timeout. `stop` wartet bis zu
# ~10 s auf SIGTERM/SIGKILL (gemessen: Aktion wirkt, Client meldete vorher
# "Timeout nach 0 Bytes" beim 1-s-Default). 20 s = Stop-Frist + Startzeit.
_ACTION_TIMEOUT = 20.0
_ACTION_TIMEOUTS = {"start": _ACTION_TIMEOUT, "stop": _ACTION_TIMEOUT}

# Eigener Transport-Schalter des Admin-Clients (Etappe 3). Bewusst NICHT
# DOCKER_HOST: das ist global und wuerde main.py, archon/routers/* und
# ephemeral_sandbox mitziehen, die andere Proxy-Flags brauchen.
_ADMIN_HOST_ENV = "DOCKER_ADMIN_HOST"

# ---------------------------------------------------------------------------
# Eigene, getrennte Allowlist fuer den privilegierten Admin-Client.
#
# Sie ist absichtlich NICHT in _ALLOWED eingerollt: _ALLOWED gilt fuer alle
# normalen Aufrufer (main.py, archon/routers/*, ephemeral_sandbox). Wuerde man
# 'Image pull' oder 'Container create/delete' dort hineinlegen, koennte jeder
# dieser Aufrufer den kompletten Hermes-Core austauschen. Der Admin-Client ist
# nur fuer den Updater gedacht (backend/hermes_updater.py).
#
# Genau die 12 Operationen, die Updater und Versionserkennung brauchen — nicht
# mehr: kein kill, kein pause, kein prune, kein build, kein volume, kein exec
# ausser dem Read-only-Versionsabruf.
# ---------------------------------------------------------------------------
_ADMIN_ALLOWED = [
    # --- Lesen (Versionserkennung, Container-Backup-Konfiguration) ---
    ("GET", re.compile(r"^/containers/json(\?.*)?$")),
    ("GET", re.compile(rf"^/containers/{_CN_PAT}/json$")),
    ("GET", re.compile(rf"^/images/{_REF_PAT}/json$")),
    # --- exec nur fuer 'hermes --version' (Erstellen + Start, kein Aufraeumen) ---
    ("POST", re.compile(rf"^/containers/{_CN_PAT}/exec$")),
    ("POST", re.compile(r"^/exec/[A-Za-z0-9]+/start$")),
    # --- Lebenszyklus des Core-Containers ---
    ("POST", re.compile(rf"^/containers/{_CN_PAT}/start$")),
    ("POST", re.compile(rf"^/containers/{_CN_PAT}/stop(\?.*)?$")),
    # --- Rename als Rollback-Pfad: Zielname wird im Regex mitvalidiert ---
    ("POST", re.compile(
        rf"^/containers/{_CN_PAT}/rename\?name=[A-Za-z0-9][A-Za-z0-9_.-]{{0,127}}$")),
    # --- Create: Name verpflichtend, damit kein unbenannter Nebenlaeufer entsteht ---
    ("POST", re.compile(
        rf"^/containers/create\?name=[A-Za-z0-9][A-Za-z0-9_.-]{{0,127}}$")),
    # --- Entfernen des Backup-Containers (Rollback-Aufraeumen) ---
    ("DELETE", re.compile(rf"^/containers/{_CN_PAT}(\?.*)?$")),
    # --- Image: Pull und Tag ---
    ("POST", re.compile(
        rf"^/images/create\?fromImage={_REF_PAT}(&[A-Za-z0-9_.=&/-]*)?$")),
    ("POST", re.compile(
        rf"^/images/{_REF_PAT}/tag\?repo=[A-Za-z0-9][A-Za-z0-9_.:/-]{{0,200}}"
        r"(&[A-Za-z0-9_.=&/-]*)?$")),
]


class DockerError(RuntimeError):
    pass


# Erfolgsstatus einer Lebenszyklus-Aktion. 304 = "laeuft bereits" (Docker-Antwort
# auf `start` bei laufendem Container, gemessen 08.11.2026), 204 = "erledigt".
_ACTION_OK_STATUS = frozenset({200, 204, 304})


def docker_cli_host_args() -> list[str]:
    """`-H`-Argumente fuer docker-CLI-Aufrufe, die den Unix-Socket brauchen.

    Manche Pfade sind strukturell Klasse C und bleiben am Socket: ``docker run --rm``
    in der Sandbox braucht ``attach``/``wait``, der Proxy gibt beides absichtlich nicht
    frei (gemessen: 403). Die docker-CLI folgt aber **global** ``DOCKER_HOST`` — ohne
    diese Bindung wuerden solche Aufrufe nach dem Setzen der Variable still ueber den
    Proxy laufen und erst mitten in der Ausfuehrung abbrechen. Deshalb pinnt jeder
    CLI-Aufruf hier explizit seinen Endpunkt; das ist keine Migration, sondern der
    Erhalt des bisherigen Verhaltens.
    """
    sock = os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock")
    return ["-H", f"unix://{sock}"]


def validate_container_name(name: str) -> str:
    if not name or not _CONTAINER_RE.match(str(name)):
        raise DockerError(f"Ungültiger Container-Name: {name!r}")
    return str(name)


def validate_image_ref(ref: str) -> str:
    """Image-Referenz fuer API-Pfade (repo[/img][:tag][@digest])."""
    text = str(ref or "")
    if not _IMAGE_REF_RE.match(text) or ".." in text or "//" in text:
        raise DockerError(f"Ungültige Image-Referenz: {ref!r}")
    return text


_TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")


def _validate_tag(tag: str) -> str:
    """Docker-Tag: kein '/', kein ':', kein Leerraum (Query-Sicherheit)."""
    text = str(tag or "")
    if not _TAG_RE.match(text):
        raise DockerError(f"Ungültiger Image-Tag: {tag!r}")
    return text


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
    _rules = _ALLOWED

    def __init__(self, host: Optional[str] = None, unix_socket: Optional[str] = None) -> None:
        self._custom_host = host
        self._custom_unix = unix_socket

    @property
    def _effective_host(self) -> str:
        # M-20: Dynamische Erkennung von DOCKER_HOST, damit Singleton nicht einfriert
        if self._custom_host is not None:
            return self._custom_host.strip()
        return os.environ.get("DOCKER_HOST", "").strip()

    @property
    def _effective_unix(self) -> str:
        if self._custom_unix is not None:
            return self._custom_unix
        return os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock")

    # ---------------- Transport ----------------

    def _endpoint(self) -> tuple[str, str]:
        """(kind, target) - kind = 'tcp' | 'unix'."""
        host = self._effective_host
        if host.startswith("tcp://"):
            return "tcp", host[len("tcp://"):]
        if host.startswith("http://"):
            return "tcp", host[len("http://"):]
        if host.startswith("unix://"):
            return "unix", host[len("unix://"):]
        return "unix", self._effective_unix

    def _check_allowed(self, method: str, path: str) -> None:
        for m, rx in self._rules:
            if m == method.upper() and rx.match(path):
                return
        raise DockerError(f"Docker-Operation nicht erlaubt: {method} {path}")

    def request(self, method: str, path: str, payload: Optional[dict] = None,
                timeout: float = _DEFAULT_TIMEOUT) -> bytes:
        """Rohantwort-Body. Der HTTP-Status wird verworfen — wer ihn braucht: request_status()."""
        return self._request_raw(method, path, payload, timeout)[1]

    def request_status(self, method: str, path: str, payload: Optional[dict] = None,
                       timeout: float = _DEFAULT_TIMEOUT) -> tuple[int, bytes]:
        """Wie request(), liefert aber (HTTP-Status, Body).

        Noetig, um "Container existiert nicht" (404) von "Abfrage erfolgreich" (200) zu
        unterscheiden: der Body allein ist in beiden Faellen JSON.
        """
        return self._request_raw(method, path, payload, timeout)

    def _request_raw(self, method: str, path: str, payload: Optional[dict] = None,
                     timeout: float = _DEFAULT_TIMEOUT) -> tuple[int, bytes]:
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

    def _read_response(self, sock: socket.socket) -> tuple[int, bytes]:
        """Liest die komplette Antwort und liefert (HTTP-Status, Body)."""
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
        status_line = parts[0].split(b"\r\n", 1)[0] if parts else b""
        try:
            status = int(status_line.split(b" ")[1])
        except (IndexError, ValueError):
            status = 0
        if len(parts) < 2:
            if deadline_hit:
                raise DockerError(f"Docker-Timeout nach {len(response)} Bytes")
            return status, b""
        if chunked:
            return status, _decode_chunked(parts[1])
        return status, parts[1]

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

    def container_action(self, name: str, action: str,
                         timeout: Optional[float] = None) -> bytes:
        """start/stop/restart ausfuehren — und den HTTP-Status pruefen.

        Frueher wurde der Status verworfen (`request()` gibt nur den Body zurueck).
        Ueber den Proxy ist das eine stille Falle: `POST .../restart` wird dort mit
        **403** beantwortet (ALLOW_RESTARTS=0), der Body ist eine HTML-Fehlerseite —
        der Aufrufer meldete trotzdem ``status: success``, waehrend nichts passierte.
        Gemessen 08.11.2026 am laufenden Stack. Deshalb hier explizit auswerten.

        Der Timeout ist pro Aktion gesetzt (_ACTION_TIMEOUTS) und nicht global
        angehoben: `stop`/`start` brauchen Sekunden, alles andere soll schnell
        scheitern. ``timeout`` ueberschreibt den Aktions-Default explizit.
        """
        name = validate_container_name(name)
        if action not in ("start", "stop", "restart"):
            raise DockerError(f"Ungültige Aktion: {action}")
        effective_timeout = _ACTION_TIMEOUTS.get(action, _DEFAULT_TIMEOUT) \
            if timeout is None else timeout
        status, body = self.request_status("POST", f"/containers/{name}/{action}",
                                           timeout=effective_timeout)
        if status not in _ACTION_OK_STATUS:
            raise DockerError(
                f"Docker-{action} fuer '{name}' abgelehnt (HTTP {status}): "
                f"{body[:160].decode('utf-8', errors='replace')!r}"
            )
        return body

    def restart_container(self, name: str) -> bytes:
        """Neustart als ``stop`` + ``start`` — fail-closed.

        Der Proxy gibt ``restart`` nicht frei (ALLOW_RESTARTS=0, Entscheidung B2:
        `restart` traefe jeden Container, den der Namensregex erwischt, inklusive
        Proxy und App). Der Neustart wird deshalb aus zwei freigegebenen Schritten
        gebaut.

        Scheitert ``stop``, wird ``start`` **nicht** ausgefuehrt: ein halb
        neugestarteter Container ist schlimmer als ein ehrlicher Fehler. Die
        DockerError-Meldung nennt die gescheiterte Phase, damit der Aufrufer sie
        weiterreichen kann.
        """
        name = validate_container_name(name)
        try:
            self.container_action(name, "stop")
        except DockerError as e:
            raise DockerError(
                f"Neustart von '{name}' abgebrochen, stop fehlgeschlagen: {e}"
            ) from e
        try:
            return self.container_action(name, "start")
        except DockerError as e:
            raise DockerError(
                f"Neustart von '{name}' unvollstaendig (Container gestoppt), "
                f"start fehlgeschlagen: {e}"
            ) from e

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


class DockerAdminClient(DockerClient):
    """Privilegierter Client fuer Image- und Container-Verwaltung.

    Gleicher Transport wie DockerClient (DOCKER_HOST bzw. Unix-Socket), aber
    eigene Allowlist (_ADMIN_ALLOWED). Nur der Updater darf das nutzen.

    Zusaetzlich DOCKER_ADMIN_HOST: eigener Transport-Ziel fuer genau diesen
    Client. DOCKER_HOST ist global und wuerde main.py, archon/routers/* und
    ephemeral_sandbox mitziehen, die andere Flags brauchen — deshalb ein
    eigener Name mit Fallback: DOCKER_ADMIN_HOST -> DOCKER_HOST -> Unix-Socket.

    Jede Methode validiert ihre Argumente, bevor sie den API-Pfad baut — ein
    Aufrufer kann also keinen Query-Anhang an einen Namen kleben.
    """

    _rules = _ADMIN_ALLOWED

    def __init__(self, host: Optional[str] = None, unix_socket: Optional[str] = None) -> None:
        super().__init__(host=host, unix_socket=unix_socket)

    @property
    def _effective_host(self) -> str:
        admin_host = os.environ.get(_ADMIN_HOST_ENV, "").strip()
        if admin_host:
            return admin_host
        if self._custom_host is not None:
            return self._custom_host.strip()
        return os.environ.get("DOCKER_HOST", "").strip()

    # ---------------- Assets ----------------

    def image_json(self, ref: str) -> bytes:
        return self.request("GET", f"/images/{validate_image_ref(ref)}/json")

    def pull_image(self, ref: str, tag: str = "latest",
                   timeout: float = 1800.0) -> tuple[int, bytes]:
        """Image ziehen; der Timeout gilt fuer den GANZEN Transfer.

        Die Dauer eines Pulls haengt an der Image-Groesse, nicht an der
        Antwortzeit des Daemons. Deshalb ein eigener, explizit setzbarer Timeout
        statt des pauschalen Socket-Timeouts (heute 120 s in hermes_updater.py:64).
        """
        ref = validate_image_ref(ref)
        tag_part = f"&tag={_validate_tag(tag)}" if tag else ""
        return self.request_status("POST", f"/images/create?fromImage={ref}{tag_part}",
                                   timeout=timeout)

    def tag_image(self, ref: str, repo: str, tag: str = "latest") -> tuple[int, bytes]:
        return self.request_status(
            "POST",
            f"/images/{validate_image_ref(ref)}/tag?repo={validate_image_ref(repo)}"
            f"&tag={_validate_tag(tag)}",
            timeout=120.0,
        )

    # ---------------- Container ----------------

    def create_container(self, name: str, payload: dict,
                         timeout: float = 120.0) -> tuple[int, bytes]:
        name = validate_container_name(name)
        return self.request_status("POST", f"/containers/create?name={name}",
                                   payload, timeout=timeout)

    def rename_container(self, name: str, new_name: str) -> tuple[int, bytes]:
        name = validate_container_name(name)
        new_name = validate_container_name(new_name)
        return self.request_status("POST", f"/containers/{name}/rename?name={new_name}",
                                   timeout=120.0)

    def remove_container(self, name: str, volumes: bool = False) -> tuple[int, bytes]:
        name = validate_container_name(name)
        flag = "true" if volumes else "false"
        return self.request_status("DELETE", f"/containers/{name}?v={flag}", timeout=120.0)

    def lifecycle(self, name: str, action: str, stop_timeout: int = 5) -> tuple[int, bytes]:
        name = validate_container_name(name)
        if action not in ("start", "stop"):
            raise DockerError(f"Ungültige Admin-Aktion: {action}")
        if action == "stop":
            return self.request_status("POST", f"/containers/{name}/stop?t={int(stop_timeout)}",
                                       timeout=120.0)
        return self.request_status("POST", f"/containers/{name}/start", timeout=120.0)


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