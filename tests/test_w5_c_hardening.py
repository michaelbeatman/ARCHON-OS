# -*- coding: utf-8 -*-
"""W5-C / D10-M3..M8 — statische Produktivpfad-Regressionstests.

Geprueft werden die ECHTEN deployten Dateien: Ansible-Rolle,
``docker-compose.yml``, HAProxy-ACL und die drei Windows-Starter. Es werden
keine Container gestartet, keine Netze angelegt und keine Secrets eingebettet.
Der Koordinator verifiziert zusaetzlich zentral (Shell ist in Subagent-
Sessions haeufig gesperrt).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _service_block(text: str, name: str) -> str:
    """Einen Compose-Dienstblock bis zum naechsten Dienst auf gleicher Ebene isolieren."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line == f"  {name}:")
    end = len(lines)
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if line.startswith("  ") and not line.startswith("   "):
            content = line[2:]
            if content and not content.startswith(("#", "-")) and ":" in content:
                end = i
                break
    return "\n".join(lines[start:end])


def _cron_block(tasks: str, cron_name: str) -> str:
    """Cron-Task inkl. seines `when:`-Blocks (bis zum naechsten - name:)."""
    idx = tasks.index(cron_name)
    tail = tasks[idx:]
    return tail.split("- name:", 1)[0]


# ---------------------------------------------------------------------------
# D10-M3 — DR/Chaos-Cron im Default: eigenes archon_dr_enabled
# ---------------------------------------------------------------------------

def test_m3_dr_is_decoupled_from_observability_in_ansible_and_compose():
    variables = _read("ansible/roles/archon_node/vars/main.yml")
    tasks = _read("ansible/roles/archon_node/tasks/main.yml")
    compose = _read("docker-compose.yml")

    assert "archon_dr_enabled: true" in variables
    # Der Normal-Start bleibt observability=off — DR ist trotzdem aktiv.
    assert 'archon_observability: "off"' in variables
    assert "archon_dr_enabled | bool" in tasks

    for cron_name in ("archon-litestream-restore-test", "archon-chaos-resilience-test"):
        block = _cron_block(tasks, cron_name)
        assert "when:" in block, cron_name
        assert "archon_dr_enabled | bool" in block, cron_name
        assert 'archon_observability == "full"' not in block, cron_name

    # Nachweis im Produktiv-Deploy: docker ps muss litestream zeigen.
    assert "'litestream' not in running_observability_services.stdout_lines" in tasks
    # Opt-out skaliert den Default-Dienst auf 0 statt ihn zu verstecken.
    assert "--scale litestream=0" in tasks

    # Litestream ist ein Default-Dienst — kein profiles:-Gate mehr.
    litestream = _service_block(compose, "litestream")
    active_profiles = [
        line for line in litestream.splitlines()
        if line.lstrip().startswith("profiles:")
        and not line.lstrip().startswith("#")
    ]
    assert not active_profiles


# ---------------------------------------------------------------------------
# D10-M4 — Dead-Man-Switch: Pflicht-Env + unabhaengiger Heartbeat
# ---------------------------------------------------------------------------

def test_m4_deadman_switch_has_required_env_and_independent_heartbeat():
    compose = _read("docker-compose.yml")
    tasks = _read("ansible/roles/archon_node/tasks/main.yml")
    variables = _read("ansible/roles/archon_node/vars/main.yml")

    required = "${ARCHON_HEARTBEAT_WEBHOOK_URL:?ARCHON_HEARTBEAT_WEBHOOK_URL muss in .env gesetzt sein"
    # Produzent (archon-os) UND externer Autoheal duerfen nicht ohne Empfaenger starten.
    assert compose.count(required) >= 2
    assert "${ARCHON_HEARTBEAT_WEBHOOK_URL:-}" not in compose

    # Fail-Fast im Ansible-Deploy, bevor Container gestartet werden.
    assert "docker compose -f {{ archon_compose_file }} config --quiet" in tasks
    assert "fail fast" in tasks.lower()

    # Heartbeat unabhaengig vom ueberwachten 30-s-Loop: eigener 5-min-Cron.
    assert "archon_deadman_enabled: true" in variables
    heartbeat = _cron_block(tasks, "archon-deadman-heartbeat")
    assert 'minute: "*/5"' in heartbeat
    assert "set -a && . ./.env" in heartbeat
    assert "ARCHON_HEARTBEAT_WEBHOOK_URL" in heartbeat
    # Kein erfundenes externes Ziel im Code/Cron — nur .env liefert die URL.
    assert "http://" not in heartbeat
    assert "https://" not in heartbeat


# ---------------------------------------------------------------------------
# D10-M5 — Socket-Proxy-Haertung und enge Ziel-Allowlist
# ---------------------------------------------------------------------------

def test_m5_socket_proxy_is_hardened_and_targets_are_narrow():
    compose = _read("docker-compose.yml")
    proxy = _service_block(compose, "docker-socket-proxy")

    assert 'user: "${SOCKET_PROXY_UID:-1000}:${SOCKET_PROXY_GID:-1000}"' in proxy
    assert "read_only: true" in proxy
    assert "cap_drop:" in proxy
    assert "- ALL" in proxy
    assert 'no-new-privileges:true' in proxy
    assert "pids: 128" in proxy
    assert "/run:rw,nosuid,size=8m" in proxy
    assert "/var/lib/haproxy:rw,nosuid,size=8m" in proxy
    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in proxy

    acl = _read("deploy/docker-socket-proxy/haproxy.cfg")
    # Frueher: beliebiger Container im erlaubten Netz. Jetzt: feste Namen + hex IDs.
    assert "[A-Za-z0-9_.-]+" not in acl
    assert "ARCHON-OS|hermes|hermes-agent" in acl
    assert "ef47f1b25a78_CRM" in acl  # KNOWN_SERVICES aus fleet_self_healing.py
    assert "proxy_managed_name" in acl  # ?name= an create/rename erzwungen
    assert "[A-Fa-f0-9]{12,64}" in acl  # Exec-IDs statt Container-Namen
    assert "http-request deny" in acl


# ---------------------------------------------------------------------------
# D10-M6 — Kein Override-Bypass in den drei Windows-Startpfaden
# ---------------------------------------------------------------------------

def test_m6_all_windows_starters_pin_the_hardened_compose_file():
    starters = (
        "archon-os-rebuild.bat",
        "archon-os-neu-starten.bat",
        "scripts/update_archon.bat",
    )
    for rel in starters:
        text = _read(rel)
        compose_lines = [line for line in text.splitlines() if "docker compose" in line]
        assert compose_lines, rel
        for line in compose_lines:
            assert "-f docker-compose.yml" in line, (rel, line)
        assert "config --quiet" in text, rel


# ---------------------------------------------------------------------------
# D10-M8 — Worker-Netz ueber den Proxy pruefbar + dokumentierter Vertrag
# ---------------------------------------------------------------------------

def test_m8_network_inspect_is_readable_and_contract_is_documented():
    compose = _read("docker-compose.yml")
    proxy = _service_block(compose, "docker-socket-proxy")
    acl = _read("deploy/docker-socket-proxy/haproxy.cfg")
    tasks = _read("ansible/roles/archon_node/tasks/main.yml")
    report = _read("audit_reports/w5_c_report.md")

    assert "NETWORKS=1" in proxy
    assert "archon-worker-zero-egress_net|archon-sandbox_net|archon-admin_net" in acl
    assert "/networks/(archon-worker-zero-egress_net" in acl
    assert "/json$ } METH_GET { env(NETWORKS) -m bool }" in acl
    # Der fruehere Subtree (create/connect/delete) ist weg.
    assert "/networks(/.*)?$" not in acl

    # Produktivpfad-Nachweis: der Ansible-Deploy prueft Internal=true hart.
    verify = next(
        block for block in tasks.split("- name:")
        if "Verify Zero-Egress worker network" in block
    )
    assert "docker compose -f {{ archon_compose_file }} exec -T archon-os" in verify
    assert "'network','inspect','archon-worker-zero-egress_net'" in verify
    assert "'Internal') is True" in verify
    assert "sys.exit(0 if" in verify

    # Vertrag an die Backend-Partition ist im Report dokumentiert (§0).
    assert "RuntimeError" in report
    assert "/readyz" in report
    assert "ensure_worker_zero_egress_network" in report
