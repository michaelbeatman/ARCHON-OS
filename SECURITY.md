# Security Policy

## Architecture & Zero-Trust Design

Archon OS is built for **sovereign, self-hosted operation**:

- **Zero-Trust Docker Socket Proxy:** Containers never require a raw `/var/run/docker.sock` mount in production; container status and lifecycle actions flow strictly through an isolated `archon-admin_net` allowlist proxy (`tecnativa/docker-socket-proxy`).
- **Docker Worker Network Isolation (No Internet Route):** Ephemeral sandboxes and dedicated workers execute inside `archon-worker-zero-egress_net` / `archon-sandbox_net` configured with `internal: true` (no default gateway, no NAT masquerading, kernel-enforced `ENETUNREACH` for external IPs) or `--network none`, verified fail-closed before every container launch.
- **Non-Root & Read-Only Container Runtime:** The `archon-os` and `archon-worker` containers run as unprivileged UID `1000`, `read_only: true`, `cap_drop: [ALL]`, and `no-new-privileges:true`.
- **Localhost-First Network Binding:** All services bind to `127.0.0.1` by default unless explicitly opted into LAN/VPN exposure via `ARCHON_BIND_IP`.
- **Zero-Egress Gate & Privacy-Router Hard-Block:** Sensitive categories (`finance`, `contracts`, `crm`, `hr`, `gdpr`) route exclusively to verified `LOCAL_ON_PREM` endpoints and enforce a **hard fail-closed block** (`LOCAL_LLM_OFFLINE_HARD_BLOCK`) whenever the local model is offline — preventing silent cloud fallback or indirect egress via `omniroute`. `zero_egress_strict` extends this lock across all categories system-wide.
- **SHA-256 Cryptographic LLM-Dispatch Audit Chain:** Every executed and blocked LLM call is atomically recorded in `backend/audit_log.py` (`category="llm_dispatch"`) with sanitized `target_endpoint`, `target_host`, `provider`, `model`, and `egress_zone`, protected by SHA-256 hash chaining and column-to-payload tamper verification.
- **RBAC & Scoped API Keys:** 3-tier Role-Based Access Control (`admin`, `operator`, read-only `viewer`), PBKDF2-HMAC-SHA256 sessions, and token-bucket rate-limited scoped API keys.
- **Read-Only Showcase Isolation (`ARCHON_DEMO_MODE=true`):** Public demo deployments hard-block all mutations, shell/sandbox execution, container actions, and external LLM egress at the ASGI middleware layer.

## Supported Versions

| Version | Supported |
|---|---|
| `v0.5.2.x` | Yes |
| `< v0.5.2` | No |

## Reporting a Vulnerability

Please **do not** open public GitHub issues for exploitable security vulnerabilities.
Use [GitHub Private Vulnerability Reporting](https://github.com/michaelbeatman/ARCHON-OS/security/advisories/new) on this repository so we can validate, patch, and credit your finding responsibly.
