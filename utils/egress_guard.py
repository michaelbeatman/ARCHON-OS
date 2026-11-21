"""
Egress-Guard für serverseitige HTTP-Zugriffe (SSRF-Schutz).

Hintergrund: `/api/proxy?url=…` holte jede vom Client übergebene URL
serverseitig ab — inklusive interner Ziele wie `http://127.0.0.1:8501`,
Docker-Netz-Namen oder `http://169.254.169.254/` (Cloud-Metadaten). Damit war
der Endpunkt ein offener SSRF-Kanal: er konnte interne Dienste erreichen, die
von außen nicht erreichbar sind, und deren Antworten zurückliefern.

Regel: **lokal oder explizit erlaubt — sonst blockiert.**

* Lokale Ziele (`localhost`, `127.0.0.1`, `::1`, `host.docker.internal`) sind
  erlaubt, weil die eingebetteten Web-UIs genau dort laufen.
* Alles andere muss per Umgebungsvariable `ARCHON_PROXY_ALLOWED_TARGETS`
  ausdrücklich freigegeben werden (kommagetrennt, `host:port` oder `host`).
* IP-Literale in privaten, Link-Local- und Metadaten-Bereichen werden auch dann
  abgelehnt, wenn sie nicht in der Allowlist stehen — sie sind nie ein
  legitimes Ziel für ein Web-UI-Embed.

Die Prüfung läuft vor dem Request, nicht danach: ein blockiertes Ziel wird
nicht angesprochen.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import Iterable, Optional, Set, Tuple
from urllib.parse import urlparse

from archon.core.config import config

__all__ = ["EgressBlocked", "check_target_url", "check_public_url", "allowed_targets"]

# Hosts, die per Definition lokal sind (eingebettete UIs im Container).
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}

# Nie erlaubt, auch nicht per Allowlist: Metadaten- und Link-Local-Bereiche.
_NEVER_ALLOWED = (
    ipaddress.ip_network("169.254.0.0/16"),   # Link-Local, Cloud-Metadaten
    ipaddress.ip_network("fd00:ec2::254/128"),  # AWS IPv6-Metadaten
)


class EgressBlocked(ValueError):
    """Ziel wurde vom Egress-Guard abgelehnt."""

    def __init__(self, reason: str, target: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.target = target


def _env_targets() -> Set[str]:
    raw = config.proxy_allowed_targets
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def allowed_targets() -> Set[str]:
    """Aktuell freigegebene Ziele (nur zur Diagnose/Anzeige)."""
    return set(_LOCAL_HOSTS) | _env_targets()


def _is_never_allowed(ip: ipaddress._BaseAddress) -> bool:
    return any(ip in net for net in _NEVER_ALLOWED)


def _match_allowlist(host: str, port: int, entries: Iterable[str]) -> bool:
    """`host` oder `host:port` muss exakt passen."""
    for entry in entries:
        if entry == host:
            return True
        if entry.startswith(host + ":") and entry == f"{host}:{port}":
            return True
    return False


def check_target_url(url: str, *, allowed: Optional[Iterable[str]] = None) -> str:
    """Prüft `url` gegen die Egress-Regeln und gibt sie unverändert zurück.

    Raises:
        EgressBlocked: wenn Schema, Zugangsdaten, Host oder Zielbereich
            unzulässig sind.
    """
    target = (url or "").strip()
    if not target:
        raise EgressBlocked("leere URL", target)

    parsed = urlparse(target)
    if parsed.scheme not in ("http", "https"):
        raise EgressBlocked(f"Schema '{parsed.scheme or '?'}' nicht erlaubt (nur http/https)", target)
    if parsed.username or parsed.password:
        raise EgressBlocked("URL mit Zugangsdaten ist nicht erlaubt", target)

    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise EgressBlocked("URL ohne Host", target)

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as err:
        raise EgressBlocked(f"Ungültiger Port in URL: {err}", target)

    # IP-Literal? Dann ohne DNS direkt bewerten.
    literal_ip = None
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        if _is_never_allowed(literal_ip):
            raise EgressBlocked(f"Metadaten-/Link-Local-Adresse {literal_ip} ist nie erlaubt", target)
        if literal_ip.is_loopback:
            return target
        entries = set(_env_targets() if allowed is None else allowed)
        if not _match_allowlist(host, port, entries):
            raise EgressBlocked(
                f"IP-Ziel {literal_ip} nicht freigegeben (ARCHON_PROXY_ALLOWED_TARGETS)", target
            )
        return target

    if host in _LOCAL_HOSTS:
        return target

    entries = set(_env_targets() if allowed is None else allowed)
    if _match_allowlist(host, port, entries):
        # DNS-Rebinding / Metadaten-Alias-Schutz: aufgeloeste IPs gegen verbotene Netze pruefen
        try:
            addr_info = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            for _fam, _type, _proto, _canon, sockaddr in addr_info:
                resolved_ip = ipaddress.ip_address(sockaddr[0])
                if (
                    _is_never_allowed(resolved_ip)
                    or resolved_ip.is_loopback
                    or resolved_ip.is_link_local
                    or resolved_ip.is_multicast
                    or (resolved_ip.is_private and ("." in host and not host.endswith(".internal")))
                ):
                    raise EgressBlocked(
                        f"Host '{host}' loest auf verbotene IP {resolved_ip} auf", target
                    )
        except socket.gaierror as err:
            raise EgressBlocked(
                f"DNS-Aufloesung fuer '{host}' fehlgeschlagen (Fail-Closed): {err}", target
            )
        return target

    raise EgressBlocked(
        f"Host '{host}' nicht in der Allowlist (ARCHON_PROXY_ALLOWED_TARGETS)", target
    )


def check_public_url(url: str, *, allow_private_targets: Optional[Iterable[str]] = None) -> str:
    """Prueft eine externe Web-URL gegen SSRF (nur http/https, keine privaten/internen/Metadaten-IPs).

    Gedacht fuer Web-Browsing-/Scraping-Agenten (z. B. VisualWebAgent), die oeffentliche
    Seiten abrufen duerfen, aber niemals interne Dienste (localhost, Docker-Netz, RFC1918,
    Cloud-Metadaten 169.254.169.254) oder `file://` erreichen duerfen.
    """
    target = (url or "").strip()
    if not target:
        raise EgressBlocked("leere URL", target)

    parsed = urlparse(target)
    if parsed.scheme not in ("http", "https"):
        raise EgressBlocked(f"Schema '{parsed.scheme or '?'}' nicht erlaubt (nur http/https)", target)
    if parsed.username or parsed.password:
        raise EgressBlocked("URL mit Zugangsdaten ist nicht erlaubt", target)

    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise EgressBlocked("URL ohne Host", target)

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as err:
        raise EgressBlocked(f"Ungueltiger Port in URL: {err}", target)

    explicit = set(_env_targets() if allow_private_targets is None else allow_private_targets)
    if host in _LOCAL_HOSTS or host.endswith(".local") or host.endswith(".internal"):
        if not _match_allowlist(host, port, explicit):
            raise EgressBlocked(f"Interner Host '{host}' fuer Web-Egress blockiert", target)

    def _reject_if_internal(ip: ipaddress._BaseAddress) -> None:
        if _is_never_allowed(ip):
            raise EgressBlocked(f"Metadaten-/Link-Local-Adresse {ip} ist nie erlaubt", target)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            if not _match_allowlist(host, port, explicit):
                raise EgressBlocked(f"Private/interne Ziel-IP {ip} ist fuer Web-Egress blockiert", target)

    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        _reject_if_internal(literal_ip)
        return target

    try:
        addr_info = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as err:
        raise EgressBlocked(f"DNS-Aufloesung fuer '{host}' fehlgeschlagen (Fail-Closed): {err}", target)

    for _fam, _type, _proto, _canon, sockaddr in addr_info:
        _reject_if_internal(ipaddress.ip_address(sockaddr[0]))

    return target
