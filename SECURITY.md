# Security Policy

## Architecture & Zero-Trust Design

Archon OS is built for **sovereign, self-hosted operation**:

- **Zero-Trust Docker Socket Proxy:** Containers never require a raw `/var/run/docker.sock` mount; container status and lifecycle actions flow strictly through an isolated `archon-admin_net` allowlist proxy (`tecnativa/docker-socket-proxy`).
- **Non-Root & Read-Only Container Runtime:** The `archon-os` application container runs as unprivileged UID `1000` (`streamlituser`), `read_only: true`, `cap_drop: [ALL]`, and `no-new-privileges:true`.
- **Localhost-First Network Binding:** All services bind to `127.0.0.1` by default unless explicitly opted into LAN/VPN exposure via `ARCHON_BIND_IP`.
- **RBAC & Scoped API Keys:** 3-tier Role-Based Access Control (`admin`, `operator`, read-only `viewer`), PBKDF2-HMAC-SHA256 sessions, and token-bucket rate-limited scoped API keys.
- **Dual-LLM Prompt Injection Guard & Zero-Egress Routing:** Untrusted external inputs pass quarantine sanitization, and sensitive workloads (`GDPR / Privacy Zero-Egress`) route exclusively to local Ollama / LM Studio models.
- **Read-Only Showcase Isolation (`ARCHON_DEMO_MODE=true`):** Public demo deployments hard-block all mutations, shell/sandbox execution, container actions, and external LLM egress at the ASGI middleware layer.

## Supported Versions

| Version | Supported |
|---|---|
| `v0.5.2.x` | Yes |
| `< v0.5.2` | No |

## Reporting a Vulnerability

Please **do not** open public GitHub issues for exploitable security vulnerabilities.
Use [GitHub Private Vulnerability Reporting](https://github.com/michaelbeatman/ARCHON-OS/security/advisories/new) on this repository so we can validate, patch, and credit your finding responsibly.
