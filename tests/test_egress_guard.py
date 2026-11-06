"""
Tests für utils.egress_guard — SSRF-Schutz des Proxy-Endpunkts.

Geprüft wird die Entscheidung, nicht der HTTP-Request: erlaubte Ziele gehen
durch, interne/metadata/inoffizielle Ziele werden abgelehnt, und die
Umgebungs-Allowlist kann externe Hosts gezielt freigeben.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utils.egress_guard import EgressBlocked, check_target_url  # noqa: E402


# ---------------------------------------------------------------- erlaubt

@pytest.mark.parametrize("url", [
    "http://localhost:9119/",
    "http://127.0.0.1:8501/health",
    "http://host.docker.internal:20128/v1",
    "https://localhost:8787/x",
    "http://[::1]:8501/x",
])
def test_local_targets_allowed(url):
    assert check_target_url(url) == url.strip()


def test_env_allowlist_allows_explicit_host(monkeypatch):
    monkeypatch.setenv("ARCHON_PROXY_ALLOWED_TARGETS", "example.org:8080")
    assert check_target_url("http://example.org:8080/pfad")


def test_env_allowlist_port_must_match(monkeypatch):
    monkeypatch.setenv("ARCHON_PROXY_ALLOWED_TARGETS", "example.org:8080")
    with pytest.raises(EgressBlocked):
        check_target_url("http://example.org:9090/pfad")


# ---------------------------------------------------------------- blockiert

@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",   # Cloud-Metadaten
    "http://10.0.0.5/admin",
    "http://192.168.0.1/",
    "http://172.16.1.1/",
    "http://8.8.8.8/",
])
def test_private_and_public_ips_blocked(url):
    with pytest.raises(EgressBlocked):
        check_target_url(url)


def test_metadata_ip_blocked_even_when_allowlisted(monkeypatch):
    monkeypatch.setenv("ARCHON_PROXY_ALLOWED_TARGETS", "169.254.169.254")
    with pytest.raises(EgressBlocked) as err:
        check_target_url("http://169.254.169.254/latest/meta-data/")
    assert "nie erlaubt" in err.value.reason


@pytest.mark.parametrize("url", [
    "ftp://example.org/x",
    "file:///etc/passwd",
    "gopher://127.0.0.1:6379/_INFO",
    "//example.org/pfad",
])
def test_bad_schemes_blocked(url):
    with pytest.raises(EgressBlocked):
        check_target_url(url)


def test_credentials_in_url_blocked():
    with pytest.raises(EgressBlocked) as err:
        check_target_url("http://user:geheim@127.0.0.1:8501/")
    assert "Zugangsdaten" in err.value.reason


@pytest.mark.parametrize("url", ["", "   ", "http://"])
def test_empty_or_hostless_blocked(url):
    with pytest.raises(EgressBlocked):
        check_target_url(url)


def test_unknown_public_host_blocked():
    with pytest.raises(EgressBlocked) as err:
        check_target_url("http://beispiel.invalid/")
    assert "Allowlist" in err.value.reason
